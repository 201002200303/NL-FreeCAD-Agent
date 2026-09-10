# -*- coding: utf-8 -*-
"""会话判读：把运行记录还原成可读轨迹与收敛指标。

为什么需要它
------------
Code Mode 的 chat 路径**不写 `session_events`**（那套富事件属于另一条流程），
但每轮会把 `phase_state` / `soft_plan` / `tool_calls` 以 JSON note 写进
`conversation_messages`。这是「效果」唯一的现成度量通道 —— 没有它，跑完一次
建模只能靠肉眼看模型，说不清是否真推进到 passed、是否用了 compound、几轮收敛。

用法
----
    python scripts/session_report.py                 # 最近 5 个有转录的会话
    python scripts/session_report.py <session_id>    # 指定会话

指标含义见输出末尾「收敛指标」：期望 gate=passed、status=done、阶段全推进、
计划不含整机 fuse。
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "agent_service" / "data" / "runtime.db"

DONE_STATES = {"done", "completed"}
# 计划里出现这些措辞＝仍想把整机布尔成一体（compound 方案落地后应为 False）
WHOLE_FUSE_MARKERS = ("fuse 为", "fuse成", "fuse 成", "fuse 单一", "fuse为")


def _use_utf8_stdout() -> None:
    """Windows 控制台是 GBK；轨迹里含 →/× 等字符，不加固会直接抛 UnicodeEncodeError。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - 尽力而为
                pass


def _extract_code(note: dict) -> str:
    """取 note.tool_calls 里 execute_cad_program 的代码，用于判定**实际调了哪些 API**。"""
    chunks = []
    for call in note.get("tool_calls") or []:
        if not isinstance(call, dict) or call.get("tool") != "execute_cad_program":
            continue
        code = (call.get("args") or {}).get("code")
        if code:
            chunks.append(str(code))
    return "\n".join(chunks)


def load_turns(session_id: str) -> tuple[list[dict], list[tuple]]:
    """返回（助手轮次, 全部消息）。助手轮次＝能解析出 phase_state 的 note。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = list(
            conn.execute(
                "select seq, role, content from conversation_messages "
                "where session_id=? order by seq",
                (session_id,),
            )
        )
    finally:
        conn.close()

    turns = []
    for seq, role, content in rows:
        if role != "assistant":
            continue
        try:
            note = json.loads(content)
        except Exception:
            continue
        if not isinstance(note, dict) or "phase_state" not in note:
            continue
        plan = note.get("soft_plan") or {}
        items = plan.get("items") or plan.get("phases") or []
        turns.append(
            {
                "seq": seq,
                "status": note.get("status"),
                "gate": (note.get("phase_state") or {}).get("status"),
                "current": (note.get("phase_state") or {}).get("phase_id"),
                "phases": [
                    (it.get("id"), it.get("status"), it.get("title"))
                    for it in items
                    if isinstance(it, dict)
                ],
                "checks": (note.get("phase_state") or {}).get("checks") or [],
                "code": _extract_code(note),
            }
        )
    return turns, rows


def report(session_id: str) -> None:
    turns, rows = load_turns(session_id)
    if not rows:
        print(f"[{session_id}] 无转录（session_id 不对，或该路径不落库）")
        return

    print("=" * 74)
    print(f"会话 {session_id}   助手轮次(含计划)={len(turns)}   总消息={len(rows)}")
    print("=" * 74)

    for turn in turns:
        print(
            f"\n[seq {turn['seq']}] status={turn['status']} "
            f"gate={turn['gate']} current={turn['current']}"
        )
        for pid, state, title in turn["phases"]:
            flag = {"done": "ok", "completed": "ok", "in_progress": ".."}.get(str(state), "  ")
            print(f"    [{flag:2s}] {pid} {str(state):12s} {str(title)[:46]}")
        for check in turn["checks"][:4]:
            if isinstance(check, dict) and not check.get("passed", True):
                wanted = check.get("value") or check.get("equals")
                print(f"    ! check {check.get('type')} want={wanted} got={check.get('actual')}")

    last = turns[-1] if turns else {}
    phases = last.get("phases") or []
    done = [p for p in phases if str(p[1]).lower() in DONE_STATES]
    code_all = "\n".join(t.get("code") or "" for t in turns)
    plan_all = "\n".join(str(p[2]) for t in turns for p in (t.get("phases") or []))
    fails = [
        (seq, str(content)[:160])
        for seq, role, content in rows
        if role == "user" and "工具结果" in str(content) and "error" in str(content).lower()
    ]

    print("\n" + "-" * 74)
    print("收敛指标")
    print("-" * 74)
    print(f"  终态 gate            : {last.get('gate')}   (期望 passed)")
    print(f"  终态 status          : {last.get('status')}   (期望 done)")
    print(f"  阶段推进             : {len(done)}/{len(phases)}")
    print(f"  助手轮次             : {len(turns)}   (越快收敛越好)")
    print(f"  代码用 cad.compound  : {'cad.compound' in code_all}")
    print(f"  代码用 cad.fuse      : {code_all.count('cad.fuse')} 次")
    print(f"  计划含整机 fuse      : {any(m in plan_all for m in WHOLE_FUSE_MARKERS)}   (期望 False)")
    print(f"  工具失败轮次         : {len(fails)}")
    for seq, body in fails[:5]:
        print(f"      seq={seq} {body}")
    print("-" * 74)


def main() -> int:
    _use_utf8_stdout()
    if not DB_PATH.exists():
        print(f"找不到 {DB_PATH}")
        return 1

    if len(sys.argv) > 1:
        for session_id in sys.argv[1:]:
            report(session_id)
            print()
        return 0

    conn = sqlite3.connect(DB_PATH)
    try:
        recent = [
            row[0]
            for row in conn.execute(
                "select session_id from conversation_messages "
                "group by session_id order by max(id) desc limit 5"
            )
        ]
    finally:
        conn.close()
    for session_id in recent:
        report(session_id)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
