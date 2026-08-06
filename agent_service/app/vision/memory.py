"""视觉会话记忆：阶段验收 + 修订预算，避免空转抛光。"""

from __future__ import annotations

from typing import Any, Optional

DEFAULT_MAX_REVISES = 2


def empty_vision_memory(*, max_revises: int = DEFAULT_MAX_REVISES) -> dict[str, Any]:
    return {
        "phase_id": "",
        "acceptance": "",
        "last_verdict": "",
        "last_summary": "",
        "open_issues": [],
        "revise_count_in_phase": 0,
        "max_revises_per_phase": int(max_revises),
        "stop_reason": None,
    }


def count_visible_objects(document_state: Any) -> int:
    """文档中可见对象数；无几何时不应跑视觉。"""
    if document_state is None:
        return 0
    if hasattr(document_state, "objects"):
        objs = list(getattr(document_state, "objects") or [])
    elif isinstance(document_state, dict):
        objs = list(document_state.get("objects") or [])
    else:
        return 0
    n = 0
    for obj in objs:
        if isinstance(obj, dict):
            if obj.get("visible", True):
                n += 1
        else:
            if getattr(obj, "visible", True):
                n += 1
    return n


def current_phase(soft_plan: Optional[dict]) -> dict[str, str]:
    """返回当前阶段 {id, title, acceptance}；优先 in_progress，否则首个 pending。"""
    if not soft_plan:
        return {"id": "", "title": "", "acceptance": ""}
    items = soft_plan.get("items") or soft_plan.get("phases") or []
    chosen = None
    fallback = None
    for it in items:
        if not isinstance(it, dict):
            continue
        status = str(it.get("status") or "").lower()
        pid = str(it.get("id") or it.get("phase_id") or "").strip()
        title = str(it.get("title") or it.get("intent") or "").strip()
        acceptance = str(it.get("acceptance") or "").strip()
        row = {"id": pid or title, "title": title, "acceptance": acceptance}
        if status == "in_progress":
            chosen = row
            break
        if status in ("", "pending") and fallback is None:
            fallback = row
    return chosen or fallback or {"id": "", "title": "", "acceptance": ""}


def _issue_key(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())[:160]


def update_vision_memory(
    prev: Optional[dict],
    *,
    soft_plan: Optional[dict] = None,
    vision_result: Optional[dict] = None,
) -> dict[str, Any]:
    """根据 soft_plan 阶段与本轮视觉结果更新 memory。"""
    mem = dict(empty_vision_memory())
    if isinstance(prev, dict):
        mem.update({k: prev.get(k, mem.get(k)) for k in mem})
        mem["open_issues"] = list(prev.get("open_issues") or [])

    phase = current_phase(soft_plan)
    phase_id = phase.get("id") or ""
    if phase_id and phase_id != (mem.get("phase_id") or ""):
        mem["phase_id"] = phase_id
        mem["revise_count_in_phase"] = 0
        mem["stop_reason"] = None
        mem["open_issues"] = []
    elif phase_id and not mem.get("phase_id"):
        mem["phase_id"] = phase_id

    if phase.get("acceptance"):
        mem["acceptance"] = phase["acceptance"]
    elif phase.get("title") and not mem.get("acceptance"):
        mem["acceptance"] = f"完成本阶段「{phase['title']}」的最低可读造型即可，细节可后议"

    if not vision_result or vision_result.get("skipped"):
        return mem

    verdict = str(vision_result.get("verdict") or "").lower()
    mem["last_verdict"] = verdict
    mem["last_summary"] = str(vision_result.get("summary") or "")[:400]

    existing = {
        _issue_key(i.get("text") if isinstance(i, dict) else i): i
        for i in (mem.get("open_issues") or [])
        if i
    }
    for raw in vision_result.get("issues") or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = _issue_key(text)
        if key in existing:
            continue
        status = "open"
        if verdict == "warn":
            status = "ask_user"  # 细节：询问用户，不自动修
        existing[key] = {"id": f"v{len(existing)+1}", "text": text[:240], "status": status}
    mem["open_issues"] = list(existing.values())[:20]

    if verdict == "ok":
        for issue in mem["open_issues"]:
            if isinstance(issue, dict) and issue.get("status") == "open":
                issue["status"] = "accepted"
        mem["stop_reason"] = "phase_ok"
    return mem


def should_allow_vision_revise(memory: Optional[dict], vision_result: Optional[dict]) -> bool:
    """仅 bad 且本阶段预算未用尽时允许自动改码。"""
    if not vision_result or vision_result.get("skipped"):
        return False
    if str(vision_result.get("verdict") or "").lower() != "bad":
        return False
    mem = memory or empty_vision_memory()
    if mem.get("stop_reason") in ("budget", "user", "phase_ok"):
        return False
    count = int(mem.get("revise_count_in_phase") or 0)
    max_r = int(mem.get("max_revises_per_phase") or DEFAULT_MAX_REVISES)
    return count < max_r


def note_vision_revise_attempt(memory: Optional[dict]) -> dict[str, Any]:
    """登记一次因视觉硬伤触发的自动修订额度。"""
    mem = dict(memory or empty_vision_memory())
    mem["revise_count_in_phase"] = int(mem.get("revise_count_in_phase") or 0) + 1
    max_r = int(mem.get("max_revises_per_phase") or DEFAULT_MAX_REVISES)
    if mem["revise_count_in_phase"] >= max_r:
        mem["stop_reason"] = "budget"
    return mem


def format_vision_memory_for_prompt(memory: Optional[dict]) -> str:
    if not memory:
        return ""
    lines = ["## 视觉主线（vision_memory）"]
    if memory.get("phase_id"):
        lines.append(f"- 阶段: {memory.get('phase_id')}")
    if memory.get("acceptance"):
        lines.append(f"- 本阶段验收: {memory.get('acceptance')}")
    lines.append(
        f"- 本阶段视觉修订: {memory.get('revise_count_in_phase', 0)}/"
        f"{memory.get('max_revises_per_phase', DEFAULT_MAX_REVISES)}"
    )
    if memory.get("stop_reason"):
        lines.append(f"- 停止原因: {memory.get('stop_reason')}")
    ask = [
        i.get("text")
        for i in (memory.get("open_issues") or [])
        if isinstance(i, dict) and i.get("status") == "ask_user"
    ][:6]
    open_hard = [
        i.get("text")
        for i in (memory.get("open_issues") or [])
        if isinstance(i, dict) and i.get("status") == "open"
    ][:6]
    if open_hard:
        lines.append("- 待修硬伤: " + "；".join(open_hard))
    if ask:
        lines.append("- 细节待确认（勿自动改码，询问用户）: " + "；".join(ask))
    lines.append(
        "- 规则: 仅明显漂移/间隙/穿模/缺件(verdict=bad)且预算未满才自动修；"
        "warn 细节用 question 问用户。"
    )
    return "\n".join(lines)
