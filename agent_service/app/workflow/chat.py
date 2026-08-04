"""对话式建模主循环（Cursor / Claude Code 形态）。

一个 session = 一个文档 + 一条持续 transcript。用户随时发消息；模型用自然语言
回复，并可附带 tool_calls。客户端执行工具后把结果回灌，形成真正的 agent loop。

旧的 start_plan / next_step / evaluate_step 三段式仍保留作兼容；新 UI 走本模块。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from app import config
from app.conversation import conversation_scope, get_store
from app.conversation.transcript import Transcript
from app.design import format_design_brief
from app.llm.llm_provider import call_llm
from app.memory.prompt import build_compact_document_context, resolve_memory_pack
from app.prompts import render
from app.tools.tool_registry import resolve_tool_specs_for_prompt, build_tools_description
from app.vision import assess_viewport, vision_available
from app.vision.service import format_vision_for_prompt
from app.workflow.sanitize import sanitize_tool_calls


def chat_turn(
    *,
    session_id: Optional[str],
    message: str = "",
    document_state=None,
    tool_results: Optional[list[dict]] = None,
    viewport_image: Optional[dict] = None,
    plan_mode: Optional[bool] = None,
    vision_enabled: Optional[bool] = None,
    session_memory: Optional[dict] = None,
    name_map: Optional[dict] = None,
    soft_plan: Optional[dict] = None,
    user_goal: str = "",
) -> dict:
    """处理一轮对话。返回给 HTTP / 客户端的结构化结果。"""
    sid = session_id or f"session_{uuid.uuid4().hex[:8]}"
    plan_mode = config.CHAT_PLAN_MODE_DEFAULT if plan_mode is None else bool(plan_mode)
    use_vision = vision_available(request_enabled=vision_enabled)

    vision_result = None
    if use_vision and viewport_image and viewport_image.get("image_b64"):
        vision_result = assess_viewport(
            image_b64=viewport_image["image_b64"],
            mime=viewport_image.get("mime") or "image/png",
            user_goal=user_goal or message,
            phase_hint=_soft_plan_hint(soft_plan),
            focus=message[:200] if message else "",
        )

    with conversation_scope(sid) as transcript:
        if transcript is None:
            # 存储挂了也继续，只是无历史
            transcript = Transcript()

        pending = _build_pending_user(
            message=message,
            tool_results=tool_results,
            document_state=document_state,
            session_memory=session_memory,
            name_map=name_map or {},
            soft_plan=soft_plan,
            vision_result=vision_result,
            user_goal=user_goal,
        )
        system = _build_chat_system_prompt(
            plan_mode=plan_mode,
            vision_on=use_vision,
            user_goal=user_goal or message,
        )

        note = _transcript_note(message, tool_results, vision_result)
        # record=False：由本函数写入精简回合，避免把整份文档快照塞进历史
        result = call_llm(pending, system, record=False)
        if result is None:
            return {
                "status": "error",
                "session_id": sid,
                "message": "LLM 调用失败，请重试或检查 API 配置。",
                "tool_calls": [],
                "soft_plan": soft_plan,
                "vision": vision_result,
                "plan_mode": plan_mode,
                "vision_enabled": use_vision,
                "context_chars": transcript.total_chars,
            }

        parsed = _normalize_chat_result(result, soft_plan=soft_plan, plan_mode=plan_mode)
        assistant_text = json.dumps(
            {
                "message": parsed["message"],
                "tool_calls": parsed.get("tool_calls") or [],
                "status": parsed.get("status"),
                "soft_plan": parsed.get("soft_plan"),
            },
            ensure_ascii=False,
        )
        transcript.append_turn(note, assistant_text)

        parsed.update(
            {
                "session_id": sid,
                "vision": vision_result,
                "plan_mode": plan_mode,
                "vision_enabled": use_vision,
                "context_chars": transcript.total_chars,
                "turn_count": transcript.turn_count,
            }
        )
        return parsed


def compress_context(session_id: str, *, keep_recent_turns: int = 4) -> dict:
    """压缩历史：用 LLM 把旧回合收成一段摘要，保留最近若干回合 + 最早需求。"""
    store = get_store()
    transcript = store.load(session_id)
    if transcript.turn_count <= keep_recent_turns + 1:
        return {
            "status": "ok",
            "session_id": session_id,
            "message": "上下文尚短，无需压缩。",
            "context_chars": transcript.total_chars,
            "turn_count": transcript.turn_count,
        }

    # 最早一轮（需求）+ 中间待压缩 + 最近 keep_recent
    msgs = list(transcript.messages)
    head = msgs[:2]
    # 最近 keep_recent 个完整回合 = 2*keep_recent 条；若末尾有孤儿 note，一并保留
    recent_count = keep_recent_turns * 2
    if len(msgs) > recent_count and msgs[-recent_count]["role"] != "user":
        recent_count += 1
    recent = msgs[-recent_count:]
    middle = msgs[2 : len(msgs) - len(recent)]
    if not middle:
        return {
            "status": "ok",
            "session_id": session_id,
            "message": "没有可压缩的中间回合。",
            "context_chars": transcript.total_chars,
            "turn_count": transcript.turn_count,
        }

    middle_text = "\n\n".join(
        f"[{m['role']}] {m['content'][:1200]}" for m in middle
    )
    summary_prompt = render("compress").rstrip()
    # 用 call_llm 但要求 JSON 会别扭；直接走一次轻量文本调用
    summary = _call_text_llm(summary_prompt, middle_text) or "（中间过程已压缩，细节见文档状态。）"

    new_messages = [
        *head,
        {
            "role": "user",
            "content": f"【上下文已压缩】以下是此前建模过程的摘要，细节以当前文档状态为准：\n{summary}",
        },
        {
            "role": "assistant",
            "content": json.dumps(
                {"message": "已记住压缩摘要，继续以当前文档为准。", "tool_calls": []},
                ensure_ascii=False,
            ),
        },
        *recent,
    ]
    store.clear(session_id)
    store.append(session_id, new_messages)
    new_t = store.load(session_id)
    return {
        "status": "ok",
        "session_id": session_id,
        "message": f"上下文已压缩：{transcript.turn_count} 回合 → {new_t.turn_count} 回合。",
        "context_chars": new_t.total_chars,
        "turn_count": new_t.turn_count,
        "summary": summary,
    }


# ── helpers ───────────────────────────────────────────────────────

def _soft_plan_hint(soft_plan: dict | None) -> str:
    if not soft_plan:
        return ""
    items = soft_plan.get("items") or soft_plan.get("phases") or []
    parts = []
    for it in items[:8]:
        if isinstance(it, dict):
            parts.append(f"{it.get('id') or it.get('phase_id') or ''}:{it.get('title') or it.get('intent') or ''}")
        else:
            parts.append(str(it))
    return "; ".join(parts)


def _build_chat_system_prompt(*, plan_mode: bool, vision_on: bool, user_goal: str) -> str:
    """正文见 app/prompts/chat_system.md（及 plan/vision 片段）。"""
    tools = build_tools_description(resolve_tool_specs_for_prompt())
    brief = format_design_brief(user_goal) if user_goal else ""
    plan_rules = render("chat_plan_on" if plan_mode else "chat_plan_off").rstrip()
    vision_rules = render(
        "chat_vision_on" if vision_on else "chat_vision_off"
    ).rstrip()
    return render(
        "chat_system",
        BRIEF=brief,
        PLAN_RULES=plan_rules,
        VISION_RULES=vision_rules,
        TOOLS=tools,
    )


def _build_pending_user(
    *,
    message: str,
    tool_results: Optional[list[dict]],
    document_state,
    session_memory,
    name_map: dict,
    soft_plan: Optional[dict],
    vision_result: Optional[dict],
    user_goal: str,
) -> str:
    parts: list[str] = []
    if message and message.strip():
        parts.append(f"## 用户消息\n{message.strip()}")

    if tool_results:
        lines = ["## 工具执行结果（客户端回传）"]
        for item in tool_results:
            tc = item.get("tool_call") or {}
            er = item.get("execution_result") or {}
            tool = tc.get("tool") or er.get("tool") or "?"
            cid = tc.get("call_id") or er.get("call_id") or ""
            status = er.get("status", "?")
            produced = er.get("produced_objects") or []
            msg = er.get("message") or ""
            line = f"- [{cid}] {tool} → {status}"
            if produced:
                line += f" 产出={produced}"
            if msg and status != "success":
                line += f" 错误={msg}"
            lines.append(line)
        parts.append("\n".join(lines))

    memory_pack = resolve_memory_pack(
        session_memory,
        None,
        user_input=user_goal or message,
        goal=user_goal,
        name_map=name_map,
    )
    parts.append(build_compact_document_context(document_state, memory_pack))

    if soft_plan:
        parts.append(
            "## 当前 soft_plan\n```json\n"
            + json.dumps(soft_plan, ensure_ascii=False, indent=2)
            + "\n```"
        )

    if vision_text := format_vision_for_prompt(vision_result):
        parts.append(vision_text)

    if name_map:
        parts.append(
            "## name_map\n```json\n"
            + json.dumps(name_map, ensure_ascii=False)
            + "\n```"
        )

    parts.append(
        "请回复 JSON：必要时给出 tool_calls；若只需对话则 status=awaiting_user。"
    )
    return "\n\n".join(parts)


def _transcript_note(
    message: str,
    tool_results: Optional[list[dict]],
    vision_result: Optional[dict],
) -> str:
    bits = []
    if message and message.strip():
        bits.append(f"用户: {message.strip()[:500]}")
    if tool_results:
        names = []
        for item in tool_results[:12]:
            tc = item.get("tool_call") or {}
            er = item.get("execution_result") or {}
            names.append(f"{tc.get('tool','?')}→{er.get('status','?')}")
        bits.append("工具结果: " + ", ".join(names))
    if vision_result and not vision_result.get("skipped"):
        bits.append(f"视觉: {vision_result.get('verdict')} — {vision_result.get('summary','')[:120]}")
    return "；".join(bits) if bits else "（空回合）"


def _normalize_chat_result(result: dict, *, soft_plan, plan_mode: bool) -> dict:
    message = (result.get("message") or result.get("question") or "").strip()
    if not message and result.get("tool_calls"):
        message = "正在执行工具调用…"
    if not message:
        message = "（无文本回复）"

    tool_calls = sanitize_tool_calls(result.get("tool_calls") or [], prefix="chat")
    status = (result.get("status") or "").strip()
    if not status:
        if tool_calls:
            status = "awaiting_tools"
        elif result.get("question"):
            status = "awaiting_user"
        else:
            status = "awaiting_user"

    new_plan = result.get("soft_plan")
    if new_plan is None:
        new_plan = soft_plan if plan_mode else None

    return {
        "status": status,
        "message": message,
        "question": result.get("question"),
        "tool_calls": tool_calls,
        "soft_plan": new_plan,
    }


def _call_text_llm(system: str, user: str) -> Optional[str]:
    """压缩用的纯文本调用；失败返回 None。"""
    try:
        from openai import OpenAI

        if not config.OPENAI_API_KEY:
            return None
        client = OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user[:60000]},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[chat] compress llm failed: {exc}")
        return None
