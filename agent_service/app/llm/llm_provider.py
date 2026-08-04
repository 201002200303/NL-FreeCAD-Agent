"""LLM Provider — OpenAI-compatible 调用 + 文档上下文辅助。

旧闭环的 plan / next_step / evaluate / cad_spec 生成函数已归档至
`archive/legacy_closed_loop/llm/`。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.debug.trace_logger import (
    get_current_step_name,
    get_trace_session,
)
from app.schemas.cad_state import DocumentState
from app.tools.tool_registry import (
    build_tools_description,
    get_category_for_tool,
    get_category_summary,
    resolve_tool_specs_for_prompt,
)

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

LLM_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_ATTEMPTS", "2") or "2")
LLM_RETRY_BASE_DELAY = float(os.getenv("LLM_RETRY_BASE_DELAY", "1.0") or "1.0")
# max_tokens = 输出上限（与输入里的工具表无关）。40960 过大易拖慢/超时；默认给足一轮多 tool_calls
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16384") or "16384")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "180") or "180")


def _get_llm_config() -> tuple[str, str, str]:
    return (
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.getenv("LLM_MODEL", "gpt-4o-mini"),
    )


def _build_tools_description(tool_specs: dict | None = None) -> str:
    specs = tool_specs or resolve_tool_specs_for_prompt()
    categories = sorted({
        cat for name in specs
        if (cat := get_category_for_tool(name))
    })
    summary = get_category_summary(categories or None)
    return f"{summary}\n\n{build_tools_description(specs)}"


def _fmt_vec(vec, ndigits: int = 1) -> str:
    if not vec:
        return "?"
    try:
        return "[" + ", ".join(f"{float(v):.{ndigits}f}" for v in vec) + "]"
    except (TypeError, ValueError):
        return str(vec)


def _fmt_range(lo, hi, ndigits: int = 1) -> str:
    try:
        return f"[{float(lo):.{ndigits}f}, {float(hi):.{ndigits}f}]"
    except (TypeError, ValueError):
        return "?"


def _build_document_context(document_state: Optional[DocumentState]) -> str:
    """文档状态摘要（bbox / placement），供 chat 与 memory 注入。"""
    if not document_state or not document_state.objects:
        return ""

    lines = ["## 当前文档状态（含真实几何反馈）\n"]
    lines.append(f"文档名称: {document_state.document_name}")
    lines.append(
        "坐标说明：x/y/z=世界坐标包围盒范围[min,max]；center/size 由该范围导出；"
        "pos=Placement 基点（Part::Box 为角点 xmin,ymin,zmin；Cylinder 为底面圆心）。单位 mm。"
    )

    if document_state.objects:
        lines.append(f"文档中已有 {len(document_state.objects)} 个对象:")
        for obj in document_state.objects:
            parts = [f"`{obj.name}` (类型: {obj.type})"]

            if obj.bbox:
                parts.append(f"x={_fmt_range(obj.bbox.xmin, obj.bbox.xmax)}")
                parts.append(f"y={_fmt_range(obj.bbox.ymin, obj.bbox.ymax)}")
                parts.append(f"z={_fmt_range(obj.bbox.zmin, obj.bbox.zmax)}")
                parts.append(f"size={_fmt_vec(obj.bbox.size)}")
            if obj.placement and obj.placement.base:
                parts.append(f"pos={_fmt_vec(obj.placement.base)}")
                if obj.placement.rotation_euler and any(
                    abs(a) > 1e-6 for a in obj.placement.rotation_euler
                ):
                    parts.append(f"rot_euler={_fmt_vec(obj.placement.rotation_euler)}")
            if obj.topology and obj.topology.volume is not None:
                parts.append(f"volume={obj.topology.volume:.1f}")
            if not obj.visible:
                parts.append("已隐藏")

            props_str = ""
            if obj.properties:
                prop_items = [f"{k}={v}" for k, v in obj.properties.items()]
                props_str = f"，属性: {', '.join(prop_items)}"

            lines.append(f"  - " + "，".join(parts) + props_str)

    if document_state.selected_objects:
        lines.append(f"当前选中: {', '.join(f'`{s}`' for s in document_state.selected_objects)}")

    lines.append(
        "\n## 空间定位规则（重要）\n"
        "1. 必须基于上方已有对象的 x/y/z 范围计算坐标，禁止凭空臆造绝对坐标。\n"
        "2. Part::Box：pos 是包围盒最小角 (xmin,ymin,zmin)；Length/Width/Height 沿 X/Y/Z。\n"
        "3. 贴附外表面（消除空隙）：贴 +X 面 pos_x=目标.xmax；贴 -X 面 pos_x=目标.xmin-自身.Length；"
        "贴 +Y/-Y/+Z/-Z 同理用 ymax/ymin/zmax/zmin。y/z 也要对齐，避免只贴 x 却悬空。\n"
        "4. 例：车灯贴车头 Body +X 端面 → pos_x=Body.xmax，pos_y/pos_z 与 Body 该端面 y/z 范围对齐。\n"
        "5. create_cylinder 默认轴沿 Z。水平车轮（轴沿 Y）：create_cylinder 传 rot_x=90，"
        "或 create_cylinder + set_placement(rot_x=90)。成功后 size 应约为 [2R, H, 2R]。\n"
        "6. set_placement 的 rot_x/y/z 是绕固定 X/Y/Z 轴旋转（度），不是欧拉 YPR。\n"
        "7. 涉及贴合/对齐/堆叠时优先 align_objects / place_relative，不要手算坐标再 set_placement。\n"
        "8. 引用已有对象用其名称；修改操作用 target 字段指向已有对象。\n"
        "9. 每步后会回传新的世界坐标 bbox，请核对实际落点再继续。"
    )
    return "\n".join(lines)


def _message_text(message) -> str:
    content = getattr(message, "content", None) or ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or item))
        content = "".join(parts)
    content = str(content).strip()
    if content:
        return content

    reasoning = getattr(message, "reasoning_content", None) or ""
    return str(reasoning).strip()


def _extract_json_object(text: str) -> dict:
    if text is None:
        raise json.JSONDecodeError("Expecting value", "", 0)
    raw = text.strip()
    if not raw:
        raise json.JSONDecodeError("Expecting value", raw, 0)

    if raw.startswith("```"):
        lines = raw.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    if raw.lower().startswith("json"):
        maybe = raw[4:].lstrip(" \t\r\n:")
        if maybe.startswith("{") or maybe.startswith("["):
            raw = maybe

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _attempt_llm_call(
    messages: list[dict],
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> tuple[Optional[dict], object, Optional[str], str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=LLM_TIMEOUT_SEC)
    t0 = time.time()
    # qwen3.x 推理模型 thinking 很重；能关则关，不支持时回退
    kwargs = dict(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=LLM_MAX_TOKENS,
    )
    try:
        response = client.chat.completions.create(
            **kwargs, extra_body={"enable_thinking": False}
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "enable_thinking" in msg or "thinking" in msg or "invalidparameter" in msg:
            response = client.chat.completions.create(**kwargs)
        else:
            raise
    content = _message_text(response.choices[0].message)
    print(
        f"[LLM Provider] ok in {time.time() - t0:.1f}s "
        f"model={model} out_chars={len(content)} max_tokens={LLM_MAX_TOKENS}"
    )
    try:
        return _extract_json_object(content), response, None, content
    except json.JSONDecodeError as e:
        print(f"[LLM Provider] JSON 解析失败: {e}")
        print(f"[LLM Provider] 原始输出: {content[:800]}")
        return None, response, f"JSONDecodeError: {e}", content


def call_llm(
    user_input: str,
    system_prompt: str,
    *,
    transcript_note: str | None = None,
    record: bool = True,
) -> Optional[dict]:
    """调用 LLM，返回 JSON 对象；失败返回 None。"""
    api_key, base_url, model = _get_llm_config()

    if not api_key:
        print("[LLM Provider] 警告: OPENAI_API_KEY 未设置，跳过 LLM 调用")
        return None

    trace = get_trace_session()
    step_name = get_current_step_name()
    llm_label = trace.next_llm_label() if trace and step_name else ""

    from app.conversation import active_transcript

    transcript = active_transcript()
    if transcript is not None:
        messages = transcript.render(system_prompt, user_input)
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

    response = None
    error = None
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            result, response, error, raw_text = _attempt_llm_call(
                messages, api_key=api_key, base_url=base_url, model=model,
            )
        except Exception as e:
            result, response, error, raw_text = None, None, f"{type(e).__name__}: {e}", ""
            print(f"[LLM Provider] API 调用失败 (第 {attempt + 1} 次): {e}")

        if result is not None:
            if transcript is not None and record:
                transcript.append_turn(transcript_note or user_input, raw_text)
            if trace and step_name:
                trace.log_llm_call(
                    step_name, label=llm_label,
                    system_prompt=system_prompt, user_message=user_input,
                    raw_response=response, parsed=result, model=model,
                )
            return result

        if attempt < LLM_MAX_ATTEMPTS - 1:
            time.sleep(LLM_RETRY_BASE_DELAY * (2 ** attempt))

    if trace and step_name:
        trace.log_llm_call(
            step_name, label=llm_label,
            system_prompt=system_prompt, user_message=user_input,
            raw_response=response, parsed=None, model=model,
            error=f"{error} (已重试 {LLM_MAX_ATTEMPTS} 次)",
        )
    return None


def summarize_execution_for_transcript(
    last_tool_call: dict,
    execution_result: dict,
    deterministic_checks: dict | None = None,
) -> str:
    """一行工具结果摘要，写入对话历史。"""
    tool = last_tool_call.get("tool", "?")
    call_id = last_tool_call.get("call_id", "")
    args = last_tool_call.get("args") or {}
    arg_text = ", ".join(f"{k}={v}" for k, v in list(args.items())[:8])
    status = execution_result.get("status", "unknown")

    line = f"执行结果 [{call_id}] {tool}({arg_text}) → {status}"
    if produced := execution_result.get("produced_objects"):
        line += f"；产出对象 {', '.join(map(str, produced))}"
    if status != "success" and (msg := execution_result.get("message")):
        line += f"；错误：{msg}"
    if issues := (deterministic_checks or {}).get("issues"):
        line += f"；检查发现：{'; '.join(map(str, issues))}"
    return line + "。请评估并决定下一步。"


# 兼容旧测试名
_summarize_execution_for_transcript = summarize_execution_for_transcript
