"""Reducer for the host-owned Phase Program lifecycle."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from app.phase_program.acceptance import (
    evaluate_acceptance,
    has_geometric_check,
    normalize_acceptance,
)

_ACCEPTANCE_ERROR_EMPTY = (
    "phase declares no structured acceptance; add at least one geometric check "
    "(bbox_size / bbox_center / volume_range / solid_count)"
)
_ACCEPTANCE_ERROR_WEAK = (
    "phase acceptance lacks a geometric check "
    "(bbox_size / bbox_center / volume_range / solid_count)"
)


@dataclass(frozen=True)
class PhaseReduction:
    soft_plan: Optional[dict]
    phase_state: dict
    feedback: str = ""


def _items(plan: Optional[dict]) -> list[dict]:
    if not isinstance(plan, dict):
        return []
    values = plan.get("items") or plan.get("phases") or []
    return [item for item in values if isinstance(item, dict)]


def _phase_id(item: dict) -> str:
    return str(item.get("id") or item.get("phase_id") or "").strip()


def _current_phase(plan: Optional[dict]) -> Optional[dict]:
    items = _items(plan)
    for item in items:
        if str(item.get("status") or "").lower() == "in_progress":
            return item
    for item in items:
        if str(item.get("status") or "pending").lower() not in {"done", "completed"}:
            return item
    return None


def _normalized_program(code: str) -> str:
    lines = str(code or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def _program_hash(code: str) -> str:
    return hashlib.sha256(_normalized_program(code).encode("utf-8")).hexdigest()


def _set_phase_outcome(plan: Optional[dict], phase_id: str, passed: bool) -> Optional[dict]:
    if not isinstance(plan, dict):
        return plan
    updated = copy.deepcopy(plan)
    items = updated.get("items") or updated.get("phases") or []
    current_index = None
    for index, item in enumerate(items):
        if isinstance(item, dict) and _phase_id(item) == phase_id:
            current_index = index
            item["status"] = "done" if passed else "in_progress"
            break
    if passed and current_index is not None:
        for item in items[current_index + 1 :]:
            if isinstance(item, dict) and str(item.get("status") or "pending").lower() not in {
                "done",
                "completed",
            }:
                item["status"] = "in_progress"
                break
    return updated


def _acceptance_key(check: dict) -> str:
    return json.dumps(check, ensure_ascii=False, sort_keys=True)


def lock_acceptance(locked: Any, proposed: Any) -> list[dict]:
    """Host-owned acceptance: locked checks survive; the Agent may only add.

    Relaxing a locked check is impossible because the locked version is always
    kept verbatim and every check is required to pass.
    """
    merged: list[dict] = []
    seen: set[str] = set()
    for check in list(locked or []) + list(proposed or []):
        if not isinstance(check, dict) or not check.get("type"):
            continue
        key = _acceptance_key(check)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(check))
    return merged


def prepare_phase_tool_calls(
    tool_calls: list[dict],
    *,
    session_id: str,
    soft_plan: Optional[dict],
    phase_state: Optional[dict],
) -> tuple[list[dict], dict]:
    """Attach host-owned identity and locked acceptance to CAD program calls."""
    prepared: list[dict] = []
    state = dict(phase_state or {})
    current = _current_phase(soft_plan) or {}
    phase_id = _phase_id(current) or str(state.get("phase_id") or "ad_hoc")
    locked = state.get("acceptance") if str(state.get("phase_id") or "") == phase_id else None
    acceptance = lock_acceptance(locked, normalize_acceptance(current.get("acceptance")))

    for call in tool_calls or []:
        if not isinstance(call, dict) or call.get("tool") != "execute_cad_program":
            prepared.append(call)
            continue
        args = dict(call.get("args") or {})
        code = str(args.get("code") or "")
        digest = _program_hash(code)
        execution_key = f"{session_id}:{phase_id}:{digest[:16]}"
        args.update(
            {
                "phase_id": phase_id,
                "acceptance": acceptance,
                "program_hash": digest,
                "execution_key": execution_key,
            }
        )
        prepared.append({**call, "args": args})
        state = {
            **state,
            "phase_id": phase_id,
            "status": "awaiting_execution",
            "attempt": int(state.get("attempt") or 0) + 1,
            "program_hash": digest,
            "execution_key": execution_key,
            "acceptance": acceptance,
            "checks": [],
            "error": None,
        }
    return prepared, state


def _default_checks(produced: list[str], state_diff: dict) -> list[dict]:
    if produced:
        checks = [{"type": "object_exists", "target": name} for name in produced]
        if state_diff:
            checks.append({"type": "document_changed"})
        return checks
    return [{"type": "document_changed"}] if state_diff else []


def reduce_phase_feedback(
    soft_plan: Optional[dict],
    tool_results: Optional[list[dict]],
    document_state: Any,
    phase_state: Optional[dict],
) -> PhaseReduction:
    """Reduce real execution receipts into host phase truth."""
    relevant = []
    for item in tool_results or []:
        call = (item or {}).get("tool_call") or {}
        result = (item or {}).get("execution_result") or {}
        if call.get("tool") == "execute_cad_program" or result.get("tool") == "execute_cad_program":
            relevant.append((call, result))
    if not relevant:
        return PhaseReduction(soft_plan, dict(phase_state or {}), "")

    call, result = relevant[-1]
    args = call.get("args") or {}
    phase_id = str(args.get("phase_id") or (phase_state or {}).get("phase_id") or "ad_hoc")
    base = {
        **dict(phase_state or {}),
        "phase_id": phase_id,
        "program_hash": result.get("program_hash") or args.get("program_hash"),
        "execution_key": result.get("execution_key") or args.get("execution_key"),
        "state_diff": result.get("state_diff") or {},
    }
    if str(result.get("status") or "").lower() != "success":
        state = {**base, "status": "failed", "checks": [], "error": result.get("message") or "execution failed"}
        plan = _set_phase_outcome(soft_plan, phase_id, False)
        return PhaseReduction(plan, state, format_phase_feedback(state))

    acceptance = normalize_acceptance(args.get("acceptance"))
    produced = [str(name) for name in (result.get("produced_objects") or []) if name]
    state_diff = result.get("state_diff") or {}
    planned_phase = phase_id != "ad_hoc"

    # 计划阶段必须有结构化验收；只有 ad_hoc 才退回默认检查。
    if planned_phase and not acceptance:
        state = {**base, "status": "failed", "checks": [], "error": _ACCEPTANCE_ERROR_EMPTY}
        return PhaseReduction(
            _set_phase_outcome(soft_plan, phase_id, False), state, format_phase_feedback(state)
        )

    checks = acceptance or _default_checks(produced, state_diff)
    evaluated = evaluate_acceptance(checks, document_state, state_diff=state_diff)
    passed = bool(evaluated) and all(check.get("passed") for check in evaluated)

    # 仅存在性/有效性检查不足以证明几何；拒绝靠弱验收推进阶段。
    if passed and planned_phase and not has_geometric_check(checks):
        state = {
            **base,
            "status": "failed",
            "checks": evaluated,
            "error": _ACCEPTANCE_ERROR_WEAK,
        }
        return PhaseReduction(
            _set_phase_outcome(soft_plan, phase_id, False), state, format_phase_feedback(state)
        )

    state = {
        **base,
        "status": "passed" if passed else "failed",
        "checks": evaluated,
        "error": None if passed else "deterministic acceptance failed",
    }
    plan = _set_phase_outcome(soft_plan, phase_id, passed)
    return PhaseReduction(plan, state, format_phase_feedback(state))


def _items_ref(plan: dict) -> list:
    """Return the live phase list inside a plan dict (items / phases)."""
    for key in ("items", "phases"):
        values = plan.get(key)
        if isinstance(values, list):
            return values
    plan["items"] = []
    return plan["items"]


def mark_current_phase(plan: Optional[dict], phase_state: Optional[dict]) -> Optional[dict]:
    """Reflect the host-owned phase status for the current phase into the plan.

    This is presentation only; the control truth stays in phase_state.
    """
    if not isinstance(plan, dict):
        return plan
    phase_id = str((phase_state or {}).get("phase_id") or "")
    if not phase_id:
        return copy.deepcopy(plan)
    state_status = str((phase_state or {}).get("status") or "")
    marked = copy.deepcopy(plan)
    for item in _items(marked):
        if _phase_id(item) != phase_id:
            continue
        if state_status in {"awaiting_execution", "failed"}:
            item["status"] = "in_progress"
        elif state_status == "passed":
            item["status"] = "done"
        break
    return marked


def reconcile_soft_plan(
    proposed: Optional[dict],
    host_plan: Optional[dict],
    *,
    phase_state: Optional[dict],
) -> Optional[dict]:
    """Let the Agent edit plan content while the host retains phase statuses.

    The host plan is authoritative whenever it has phases: its phases cannot be
    dropped, and their statuses cannot be changed by the Agent.  New phases the
    Agent adds are accepted but stay `pending` until the host advances them.
    """
    host_items = _items(host_plan) if isinstance(host_plan, dict) else []
    if not host_items:
        return mark_current_phase(proposed, phase_state)

    proposed_by_id = {
        _phase_id(item): item for item in _items(proposed) if _phase_id(item)
    }

    reconciled = copy.deepcopy(host_plan)
    seen: set[str] = set()
    for item in _items(reconciled):
        pid = _phase_id(item)
        seen.add(pid)
        incoming = proposed_by_id.get(pid)
        if not incoming:
            continue
        # Agent may edit content, but status stays host-owned.
        host_status = item.get("status")
        item.update({key: value for key, value in incoming.items() if key != "status"})
        if host_status is not None:
            item["status"] = host_status

    for extra in _items(proposed):
        pid = _phase_id(extra)
        if not pid or pid in seen:
            continue
        cloned = copy.deepcopy(extra)
        cloned["status"] = "pending"
        _items_ref(reconciled).append(cloned)

    return mark_current_phase(reconciled, phase_state)


def format_phase_feedback(phase_state: Optional[dict]) -> str:
    if not phase_state or not phase_state.get("phase_id"):
        return ""
    lines = [
        "## 宿主阶段门闩",
        f"- phase_id: {phase_state.get('phase_id')}",
        f"- status: {phase_state.get('status') or 'idle'}",
    ]
    if diff := phase_state.get("state_diff"):
        lines.append(f"- state_diff: {diff.get('summary') or diff}")
    for check in phase_state.get("checks") or []:
        marker = "PASS" if check.get("passed") else "FAIL"
        lines.append(
            f"- [{marker}] {check.get('type')} {check.get('target') or ''} actual={check.get('actual')}"
        )
    if phase_state.get("error"):
        lines.append(f"- error: {phase_state.get('error')}")
    lines.append("阶段状态由宿主维护；不得通过改写 soft_plan 绕过失败验收。")
    return "\n".join(lines)
