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
# max_tokens = 单次**输出**上限（不是上下文窗口），且**含推理 token**：
# deepseek-flash 是推理模型，thinking 不可关，推理与正式 JSON 共享这份预算。
# 端点实测上限 393216 —— 传 800000 会 400「valid range of max_tokens is [1, 393216]」。
# 给低了（如 16384）预算会被思考烧光，正式 JSON 写到一半 finish_reason=length，
# 用户看到的是「LLM 调用失败」。
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "393216") or "393216")
# 预算调大后单轮更久（实测 16k token ≈ 83s）；超时须同步放大，
# 否则只是把「截断」换成「超时」。
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "600") or "600")


def _get_llm_config() -> tuple[str, str, str]:
    return (
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"),
        os.getenv("LLM_MODEL", "deepseek-flash"),
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
        "5. create_cylinder / cad.cylinder 默认轴沿 Z（无 rot=圆盘平放）。"
        "侧轮轴沿 ±X：rot_y=90；轴沿 ±Y：rot_x=±90；立柱不转。"
        "成功后侧轮 size 最薄维≈轮宽。\n"
        "6. rot_x/y/z 是绕固定世界 X/Y/Z 轴旋转（度），不是欧拉 YPR；Code Mode 在 cad.cylinder 上直接传 rot_*。\n"
        "6b. cad.hole 默认 axis=Z；侧壁孔必须 axis=X 或 Y。\n"
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


_JSON_DECODER = json.JSONDecoder()


def _strip_code_fence(raw: str) -> str:
    """去掉 ```json / ``` 包裹。"""
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> dict:
    """取出模型输出里的第一个完整 JSON 对象，容忍前后杂音。

    推理模型（实测 deepseek-flash）偶尔在合法 JSON 之后再多吐一个 `}`、
    把对象重复一遍、或接一段说明文字。旧实现兜底取「第一个 { 到最后一个 }」，
    正好把多余的 `}` 包进切片，于是必然解析失败 → 重试两次全败 →
    用户看到「LLM 调用失败」。

    `JSONDecoder.raw_decode` 的语义正是「只解析开头那个完整值」，
    比手工 find/rfind 切片更稳，也不会被尾部杂音带偏。
    """
    if text is None:
        raise json.JSONDecodeError("Expecting value", "", 0)

    raw = _strip_code_fence(text.strip())
    if not raw:
        raise json.JSONDecodeError("Expecting value", raw, 0)

    if raw.lower().startswith("json"):
        maybe = raw[4:].lstrip(" \t\r\n:")
        if maybe.startswith(("{", "[")):
            raw = maybe

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        original_error = exc

    # 有前导说明文字 / 尾部多余内容：从每个 '{' 起试 parse 第一个完整对象
    index = raw.find("{")
    while index >= 0:
        try:
            obj, _end = _JSON_DECODER.raw_decode(raw[index:])
            return obj
        except json.JSONDecodeError:
            index = raw.find("{", index + 1)
    raise original_error


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
    # DeepSeek 要求 response_format=json_object 时 prompt 里必须出现字面 "json"
    # （app 各 system prompt 均满足，见 test_prompts.py 守卫）
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=LLM_MAX_TOKENS,
    )
    choice = response.choices[0]
    content = _message_text(choice.message)
    finish_reason = getattr(choice, "finish_reason", None)
    # 推理 token 与正式输出共享 max_tokens：把用量打出来，
    # 下次再遇 finish=length 能一眼看出是「思考烧光预算」还是「模型话多」。
    usage = getattr(response, "usage", None)
    reasoning_tokens = getattr(
        getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None
    )
    print(
        f"[LLM Provider] ok in {time.time() - t0:.1f}s "
        f"model={model} out_chars={len(content)} max_tokens={LLM_MAX_TOKENS} "
        f"finish={finish_reason} "
        f"completion_tokens={getattr(usage, 'completion_tokens', None)} "
        f"reasoning_tokens={reasoning_tokens}"
    )
    try:
        return _extract_json_object(content), response, None, content
    except json.JSONDecodeError as e:
        # finish_reason=length 表示撞上 max_tokens：JSON 是被截断的，
        # 这不是模型「写坏了」，调大 LLM_MAX_TOKENS 才能根治
        if finish_reason == "length":
            error = (
                f"JSONDecodeError: 输出被 max_tokens({LLM_MAX_TOKENS}) 截断"
                f"（reasoning_tokens={reasoning_tokens}），"
                f"请调大 LLM_MAX_TOKENS。原始错误: {e}"
            )
        else:
            error = f"JSONDecodeError: {e}"
        print(f"[LLM Provider] JSON 解析失败 (finish={finish_reason}): {e}")
        print(f"[LLM Provider] 原始输出尾部: {content[-400:]!r}")
        return None, response, error, content


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
