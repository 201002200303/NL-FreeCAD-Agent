# executor.py — CAD Tool executor: plan dispatch + transaction management

import FreeCAD

from AICADAgent.cad_tools import TOOL_REGISTRY

# args 中引用文档对象名的字段
_NAME_REF_FIELDS = frozenset({
    "target", "base", "tool", "sketch", "body",
    "part", "part1", "part2", "assembly",
    "profile", "path",
})


def _same_tool_payload(cached: dict, tool_name: str, args: dict) -> bool:
    if (cached.get("tool") or "") != (tool_name or ""):
        return False
    return (cached.get("args") or {}) == (args or {})


class CadToolExecutor:
    """Executes a modeling plan step-by-step on the active FreeCAD document.

    Each step wraps the tool call with transaction management:
    - openTransaction before operations
    - commitTransaction on success
    - abortTransaction on failure
    - doc.recompute() after commit

    Maintains a name_map so that later steps referencing a replaced object
    (e.g. "Base" after fillet produced "Base_Fillet") are auto-resolved.
    """

    def __init__(self, doc=None):
        self.doc = doc or FreeCAD.ActiveDocument
        if self.doc is None:
            raise RuntimeError("No active FreeCAD document")
        self.name_map: dict[str, str] = {}
        # Idempotency: call_ids that already produced side effects.
        # Replaying the same call_id (retry / resume) is a no-op.
        self._completed_call_ids: set[str] = set()
        self._completed_results: dict[str, dict] = {}

    def seed_completed_call_ids(self, call_ids):
        """Mark call_ids as already executed (e.g. restored from server events)."""
        for cid in call_ids or []:
            if cid:
                self._completed_call_ids.add(str(cid))

    def has_executed(self, call_id: str) -> bool:
        return bool(call_id) and str(call_id) in self._completed_call_ids

    def _resolve(self, name: str) -> str:
        """Follow the name chain to the latest object name."""
        visited = set()
        while name in self.name_map and name not in visited:
            visited.add(name)
            name = self.name_map[name]
        return name

    def _rewrite_args(self, args: dict) -> dict:
        """Return a copy of args with object-name references resolved."""
        rewritten = {}
        for key, value in args.items():
            if key in _NAME_REF_FIELDS and isinstance(value, str):
                rewritten[key] = self._resolve(value)
            else:
                rewritten[key] = value
        return rewritten

    # ── Transaction helpers ──────────────────────────────────────────

    def _begin(self, name: str = "AI CAD Tool Step"):
        self.doc.openTransaction(name)

    def _commit(self):
        self.doc.commitTransaction()
        self.doc.recompute()

    def _rollback(self):
        self.doc.abortTransaction()

    # ── Plan execution ───────────────────────────────────────────────

    def execute_plan(self, plan: list[dict]) -> list[dict]:
        """Execute an entire plan, returning results per step."""
        results = []
        for step in plan:
            result = self.execute_step(step)
            results.append(result)
            if result.get("status") == "error":
                break
        return results

    def _execute_cad_program(self, call_id: str, args: dict) -> dict:
        """Run execute_cad_program in a single transaction with compact result."""
        from AICADAgent.cad_program import run_cad_program

        code = (args or {}).get("code") or ""
        transaction = (args or {}).get("transaction") or f"txn_{call_id}"
        try:
            self._begin(f"{call_id}: execute_cad_program")
            res = run_cad_program(
                code,
                doc=self.doc,
                registry=TOOL_REGISTRY,
                transaction=transaction,
            )
            if res.get("success"):
                self._commit()
                created = res.get("created") or []
                return {
                    "call_id": call_id,
                    "status": "success",
                    "tool": "execute_cad_program",
                    "args": args,
                    "resolved_args": args,
                    "produced_objects": created,
                    "source_objects": [],
                    "name_map_update": {},
                    "message": None,
                    "transaction": res.get("transaction"),
                    "checks": res.get("checks"),
                }
            try:
                self._rollback()
            except Exception:
                pass
            return {
                "call_id": call_id,
                "status": "error",
                "tool": "execute_cad_program",
                "args": args,
                "resolved_args": args,
                "produced_objects": res.get("created") or [],
                "source_objects": [],
                "name_map_update": {},
                "message": res.get("error_message") or res.get("error_type") or "cad program failed",
                "error_type": res.get("error_type"),
                "failed_line": res.get("failed_line"),
                "violations": res.get("violations"),
            }
        except Exception as e:  # noqa: BLE001
            try:
                self._rollback()
            except Exception:
                pass
            return {
                "call_id": call_id,
                "status": "error",
                "tool": "execute_cad_program",
                "args": args,
                "resolved_args": args,
                "produced_objects": [],
                "source_objects": [],
                "name_map_update": {},
                "message": str(e),
            }

    def execute_tool_call(self, tool_call: dict) -> dict:
        """Execute a single tool call; returns call_id / produced_objects / name_map_update."""
        call_id = tool_call.get("call_id", "unknown")
        tool_name = tool_call.get("tool", "")
        args = tool_call.get("args", {})

        if tool_name == "execute_cad_program":
            return self._execute_cad_program(call_id, args)

        # Idempotency: skip ONLY when same call_id AND same tool+args already
        # succeeded (resume/replay). Chat 常每轮重用 T1/T2——若只按 call_id
        # 跳过，会显示 ✓ 却返回上一阶段的 produced（如天线 create → Pelvis）。
        if self.has_executed(call_id):
            cached = self._completed_results.get(str(call_id))
            if cached is not None and _same_tool_payload(cached, tool_name, args):
                result = dict(cached)
                result["skipped_duplicate"] = True
                result["message"] = (
                    result.get("message")
                    or "duplicate call_id+payload — already executed, skipped"
                )
                return result
            # 同 id、不同内容：放行真正执行（覆盖缓存）

        tool_func = TOOL_REGISTRY.get(tool_name)
        if tool_func is None:
            return {
                "call_id": call_id,
                "status": "error",
                "tool": tool_name,
                "args": args,
                "resolved_args": args,
                "produced_objects": [],
                "source_objects": [],
                "name_map_update": {},
                "message": f"Unknown tool: {tool_name}",
            }

        resolved_args = self._rewrite_args(args)

        try:
            self._begin(f"{call_id}: {tool_name}")
            result = tool_func(self.doc, **resolved_args)
            result["call_id"] = call_id
            result["status"] = "success"
            is_query = result.get("kind") == "query"

            # Track name chain
            source = result.get("source")
            obj_name = result.get("object")
            name_map_update = {}
            if not is_query and source and obj_name and source != obj_name:
                self.name_map[source] = obj_name
                name_map_update = {source: obj_name}

            # Build enhanced result
            produced = []
            if obj_name and not is_query:
                produced.append(obj_name)

            source_objects = []
            if source and not is_query:
                source_objects.append(source)

            self._commit()

            final = {
                "call_id": call_id,
                "status": "success",
                "tool": tool_name,
                "args": args,
                "resolved_args": resolved_args,
                "produced_objects": produced,
                "source_objects": source_objects,
                "name_map_update": name_map_update,
                "message": None,
                **{k: v for k, v in result.items() if k not in [
                    "call_id", "status", "tool", "args", "resolved_args",
                    "produced_objects", "source_objects", "name_map_update", "message"
                ]}
            }
            # Register act (non-query) side effects for idempotent replay
            if not is_query and call_id:
                self._completed_call_ids.add(str(call_id))
                self._completed_results[str(call_id)] = final
            return final
        except Exception as e:
            try:
                self._rollback()
            except Exception:
                pass
            return {
                "call_id": call_id,
                "status": "error",
                "tool": tool_name,
                "args": args,
                "resolved_args": resolved_args,
                "produced_objects": [],
                "source_objects": [],
                "name_map_update": {},
                "message": str(e),
            }

    def execute_step(self, step: dict) -> dict:
        """Execute a single plan step. Looks up the tool in TOOL_REGISTRY.

        Legacy API for backward compatibility. Use execute_tool_call() for V0.7+.
        """
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        step_id = step.get("step_id", "?")

        tool_func = TOOL_REGISTRY.get(tool_name)
        if tool_func is None:
            return {
                "step_id": step_id,
                "status": "error",
                "message": f"Unknown tool: {tool_name}",
            }

        resolved_args = self._rewrite_args(args)

        try:
            self._begin(f"{step_id}: {tool_name}")
            result = tool_func(self.doc, **resolved_args)
            result["step_id"] = step_id
            result["status"] = "success"

            # Track name chain
            source = result.get("source")
            obj_name = result.get("object")
            if source and obj_name and source != obj_name:
                self.name_map[source] = obj_name

            self._commit()
            return result
        except Exception as e:
            try:
                self._rollback()
            except Exception:
                pass
            return {
                "step_id": step_id,
                "status": "error",
                "tool": tool_name,
                "message": str(e),
            }
