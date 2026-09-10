# -*- coding: utf-8 -*-
"""L5 无头驱动：用真实 LLM + 宿主 + FreeCAD 跑一条用户需求，输出收敛指标。

为什么需要它
------------
L1-L4 已有自动门禁（pytest + 几何 Oracle），但「效果」全在 L5 —— 真实 LLM 规划、
宿主门闩、装配、导出。此前 L5 无任何可重复的驱动方式，只能靠人手在 GUI 里点，
结果无法跨版本比较。

本脚本镜像 `agent_runner.py` 的客户端循环（见其 `_post_chat` / `_execute_chat_tools`），
但去掉了 Qt：

    POST /agent/chat {message, document_state, phase_state, ...}
      -> status=awaiting_tools + tool_calls
      -> 本地 CadToolExecutor 逐个执行
      -> POST /agent/chat {tool_results=[...], message=""}
      -> 直到 status != awaiting_tools

必须在 FreeCADCmd 内运行（需要真实的 cad.* 执行环境与 addon 导入路径）。

用法
----
    cd <repo root>
    $env:EVAL_GOAL   = '创建一个人形的高达模型'          # 可选，默认即此
    $env:EVAL_OUT    = 'agent_service/data/_eval_run.txt'  # 可选
    $env:EVAL_MAX_TURNS = '30'                             # 可选
    & 'D:\\freecad\\bin\\freecadcmd.exe' -c "import runpy; runpy.run_path(r'scripts/eval_run.py', run_name='__main__')"

需求一律通过 `EVAL_GOAL` 传入：`freecadcmd -c` 会把额外位置参数当成待打开的文件，
因此本脚本不读 argv。

**提示词请从 `docs/agent_eval_playbook.md` 逐字复制**，不要改写或手抄 ——
跨版本指标只有在提示词字面冻结时才可比。该手册同时给出判据与基线表。

跑完会打印 SESSION_ID；再用判读器看阶段轨迹与指标：

    python scripts/session_report.py <SESSION_ID>

已知与面板客户端的差异（判读时须记住）
--------------------------------------
1. `vision_enabled` 恒为 False —— FreeCADCmd 无 GUI，无法截图。
   GUI 下视觉会额外给出 verdict，本驱动拿不到。
2. 同一进程内复用同一文档；面板会话可能跨文档。
3. 启动时会 `chdir` 到 `agent_service/data/eval_runs/<goal>/`，让模型写的相对路径
   导出落在隔离目录里，不污染仓库根。

前置条件：Agent 服务已启动（否则 POST 直接失败）。
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_PARENT = REPO_ROOT / "freecad_addon"
if str(ADDON_PARENT) not in sys.path:
    sys.path.insert(0, str(ADDON_PARENT))

import FreeCAD  # noqa: E402

from AICADAgent.document_state import get_document_state  # noqa: E402
from AICADAgent.executor import CadToolExecutor  # noqa: E402
from AICADAgent.session_memory import SessionMemory  # noqa: E402

BASE_URL = os.environ.get("EVAL_BASE_URL") or "http://127.0.0.1:8765"
HTTP_TIMEOUT_SEC = 600
DEFAULT_GOAL = "创建一个人形的高达模型"
DONE_STATES = {"done", "completed"}


def _goal() -> str:
    # 不用 argv：freecadcmd -c 会把位置参数当成待打开的文件而报错
    return os.environ.get("EVAL_GOAL") or DEFAULT_GOAL


def _slug(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "_" for c in text]
    return "".join(keep)[:40] or "run"


class Tee:
    """同时写文件与 stdout —— 后台运行时也能实时观察进度。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.fh = io.TextIOWrapper(
            open(path, "wb"), encoding="utf-8", errors="replace", write_through=True
        )

    def __call__(self, msg: str = "") -> None:
        line = str(msg)
        self.fh.write(line + "\n")
        try:
            print(line)
        except Exception:  # noqa: BLE001 - 控制台编码问题不该中断评测
            pass


def post(endpoint: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _phase_line(phase_state: dict | None) -> str:
    state = phase_state or {}
    return f"gate={state.get('status')} current={state.get('phase_id')}"


def _items_of(soft_plan: dict | None) -> list:
    plan = soft_plan or {}
    return plan.get("items") or plan.get("phases") or []


def _check_handshake(log) -> None:
    """打印服务端契约版本 —— 跨版本比较指标前必须确认它。"""
    try:
        raw = urllib.request.urlopen(BASE_URL + "/agent/capabilities", timeout=10).read()
        caps = json.loads(raw)
        log(f"服务端 cad_api_version = {caps.get('cad_api_version')}")
    except Exception as exc:  # noqa: BLE001
        log(f"capabilities 探测失败（服务是否已启动？）: {exc}")


def run(goal: str, max_turns: int, log) -> dict:
    doc = FreeCAD.newDocument("EvalRun_" + _slug(goal))
    executor = CadToolExecutor(doc)
    memory = SessionMemory(goal=goal, user_input=goal)

    session_id = None
    soft_plan = None
    phase_state = None
    vision_memory = None
    message = goal
    tool_results: list = []
    final_status = None
    started = time.monotonic()
    turns_used = 0

    for turn in range(1, max_turns + 1):
        turns_used = turn
        try:
            doc_state = get_document_state()
        except Exception as exc:  # noqa: BLE001
            log(f"[turn {turn}] document_state 读取失败: {exc}")
            doc_state = None

        # 与面板一致：先把文档状态喂给 memory，再取 pack 上送
        try:
            memory.sync_from_document(doc_state)
            memory_pack = memory.build_pack()
        except Exception:  # noqa: BLE001
            memory_pack = None

        payload = {
            "session_id": session_id,
            "message": message,
            "document_state": doc_state,
            "tool_results": tool_results,
            "viewport_image": None,
            "viewport_images": [],
            "plan_mode": True,
            "vision_enabled": False,  # FreeCADCmd 无 GUI
            "session_memory": memory_pack,
            "name_map": {},
            "soft_plan": soft_plan,
            "phase_state": phase_state,
            "vision_memory": vision_memory,
            "user_goal": goal,
            "debug_mode": False,
        }

        t0 = time.monotonic()
        try:
            resp = post("/agent/chat", payload)
        except Exception as exc:  # noqa: BLE001
            log(f"[turn {turn}] POST 失败: {type(exc).__name__}: {exc}")
            break

        session_id = resp.get("session_id") or session_id
        soft_plan = resp.get("soft_plan")
        phase_state = resp.get("phase_state")
        vision_memory = resp.get("vision_memory")
        status = resp.get("status")
        calls = resp.get("tool_calls") or []
        final_status = status

        log(
            f"\n[turn {turn}] {time.monotonic() - t0:.1f}s  status={status}  "
            f"{_phase_line(phase_state)}"
        )
        if resp.get("message"):
            log(f"  msg: {str(resp['message'])[:240]}")
        for item in _items_of(soft_plan):
            if isinstance(item, dict):
                log(
                    f"    - {item.get('id')} {str(item.get('status')):12s} "
                    f"{str(item.get('title'))[:52]}"
                )
        for call in calls:
            log(
                f"    call {call.get('call_id')} {call.get('tool')} "
                f"blocked={call.get('blocked')}"
            )

        if status != "awaiting_tools" or not calls:
            log(f"\n[结束] status={status}（非 awaiting_tools 或无可执行工具）")
            break

        results = []
        for call in calls:
            tc = time.monotonic()
            try:
                res = executor.execute_tool_call(call)
            except Exception as exc:  # noqa: BLE001
                res = {
                    "status": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "call_id": call.get("call_id"),
                    "tool": call.get("tool"),
                }
            results.append({"tool_call": call, "execution_result": res})
            log(
                f"      exec {call.get('tool')} -> {res.get('status')} "
                f"({time.monotonic() - tc:.1f}s) {str(res.get('message') or '')[:130]}"
            )

        message = ""
        tool_results = results

    # ── 收尾统计 ──────────────────────────────────────────────────────────
    elapsed = time.monotonic() - started
    try:
        doc.recompute()
        names = [o.Name for o in doc.Objects]
    except Exception:  # noqa: BLE001
        names = []

    items = _items_of(soft_plan)
    done = [i for i in items if str(i.get("status")).lower() in DONE_STATES]

    log("\n" + "=" * 78)
    log("收敛指标（跨版本比较用）")
    log("=" * 78)
    log(f"  session_id           : {session_id}")
    log(f"  终态 status          : {final_status}")
    log(f"  终态 gate            : {(phase_state or {}).get('status')}")
    log(f"  阶段推进             : {len(done)}/{len(items)}")
    log(f"  轮次                 : {turns_used}")
    log(f"  耗时                 : {elapsed:.0f}s")
    log(f"  文档对象数           : {len(names)}")
    log(f"  对象                 : {', '.join(names[:30])}")
    log("=" * 78)
    log(f"判读: python scripts/session_report.py {session_id}")

    return {
        "session_id": session_id,
        "status": final_status,
        "gate": (phase_state or {}).get("status"),
        "phases_done": len(done),
        "phases_total": len(items),
        "turns": turns_used,
        "seconds": round(elapsed, 1),
        "objects": names,
    }


def main() -> int:
    goal = _goal()
    max_turns = int(os.environ.get("EVAL_MAX_TURNS") or 30)
    out = Path(os.environ.get("EVAL_OUT") or (REPO_ROOT / "agent_service" / "data" / f"_eval_{_slug(goal)}.txt"))
    log = Tee(out)

    # 模型常写相对路径导出（如 cad.export_step("Gundam", "gundam.step")），
    # 会落在进程 CWD。切到独立目录，避免污染仓库根，也让各次评测互不干扰。
    # 该目录在 agent_service/data/ 下，已被 gitignore。
    scratch = REPO_ROOT / "agent_service" / "data" / "eval_runs" / _slug(goal)
    scratch.mkdir(parents=True, exist_ok=True)
    os.chdir(scratch)

    log("=" * 78)
    log(f"L5 无头驱动   goal={goal}   max_turns={max_turns}")
    log(f"工作目录       {scratch}")
    log("=" * 78)
    _check_handshake(log)

    result = run(goal, max_turns, log)

    try:
        FreeCAD.closeDocument(FreeCAD.ActiveDocument.Name)
    except Exception:  # noqa: BLE001
        pass

    log(f"EVAL_RESULT={json.dumps(result, ensure_ascii=False)}")
    print("SESSION_ID=" + str(result.get("session_id")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
