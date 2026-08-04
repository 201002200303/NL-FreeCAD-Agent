"""
LLM Provider - 集成 OpenAI-compatible API，生成建模计划
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.tools.tool_specs import TOOL_SPECS
from app.tools.tool_registry import (
    build_tools_description,
    get_category_for_tool,
    get_category_summary,
    get_tools_by_categories,
    resolve_tool_specs_for_prompt,
)
from app.schemas.cad_state import DocumentState
from app.debug.trace_logger import (
    get_current_step_name,
    get_trace_session,
    is_debug_enabled,
)
from app.prompts import render

# 加载 .env（从 agent_service 目录）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)

# 长上下文阶段（如收尾倒角）单次调用失败率明显更高，失败一次就 abort 会白跑整轮
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_BASE_DELAY = 1.0


def _get_llm_config() -> tuple[str, str, str]:
    return (
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.getenv("LLM_MODEL", "gpt-4o-mini"),
    )


def _build_tools_description(tool_specs: dict | None = None) -> str:
    """Build the tools section of the system prompt."""
    specs = tool_specs or resolve_tool_specs_for_prompt()
    categories = sorted({
        cat for name in specs
        if (cat := get_category_for_tool(name))
    })
    summary = get_category_summary(categories or None)
    return f"{summary}\n\n{build_tools_description(specs)}"


def _fmt_vec(vec, ndigits: int = 1) -> str:
    """Format a 3D vector list as a compact string."""
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
    """Build a text summary of the current document state for the LLM.

    Includes real geometry feedback (bbox center/size, placement, visibility)
    so the LLM can reason about 3D positions instead of guessing coordinates.
    """
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


def build_system_prompt(
    document_state: Optional[DocumentState] = None,
    tool_categories: list[str] | None = None,
    tool_specs: dict | None = None,
) -> str:
    """构建 legacy 一次性 plan 的 system prompt。正文见 app/prompts/legacy_plan.md。"""
    if tool_specs is not None:
        tools_description = _build_tools_description(tool_specs)
    elif tool_categories:
        tools_description = _build_tools_description(
            resolve_tool_specs_for_prompt(tool_categories, allow_subset=True)
        )
    else:
        tools_description = _build_tools_description()
    doc_context = _build_document_context(document_state)
    doc_section = f"\n{doc_context}\n" if doc_context else ""
    return render("legacy_plan", DOC_SECTION=doc_section, TOOLS=tools_description)


def _message_text(message) -> str:
    """从 chat completion message 取出可解析文本。

    DeepSeek 等 reasoning 模型偶发把最终 JSON 放进 reasoning_content，
    而 content 为空；此时需回退读取 reasoning_content。
    """
    content = getattr(message, "content", None) or ""
    if isinstance(content, list):
        # 兼容部分 SDK 的多段 content
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
    """解析模型输出为 JSON 对象；容忍 markdown 代码块与前缀标签。"""
    if text is None:
        raise json.JSONDecodeError("Expecting value", "", 0)
    raw = text.strip()
    if not raw:
        raise json.JSONDecodeError("Expecting value", raw, 0)

    # ```json ... ``` 或 ``` ... ```
    if raw.startswith("```"):
        lines = raw.splitlines()
        # drop opening fence
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    # reasoning 偶发前缀 "json\n{...}"
    if raw.lower().startswith("json"):
        maybe = raw[4:].lstrip(" \t\r\n:")
        if maybe.startswith("{") or maybe.startswith("["):
            raw = maybe

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 再尝试截取第一个 {...} 块
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
    """One round trip. Returns (parsed, raw_response, error, raw_text)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=40960,
    )
    content = _message_text(response.choices[0].message)
    try:
        return _extract_json_object(content), response, None, content
    except json.JSONDecodeError as e:
        print(f"[LLM Provider] JSON 解析失败: {e}")
        print(f"[LLM Provider] 原始输出: {content}")
        return None, response, f"JSONDecodeError: {e}", content


def call_llm(
    user_input: str,
    system_prompt: str,
    *,
    transcript_note: str | None = None,
    record: bool = True,
) -> Optional[dict]:
    """
    调用 LLM API 获取结构化输出

    在 `conversation_scope` 内会自动带上本 session 的历史回合，并把本轮记进去。

    Args:
        user_input: 本轮发给模型的完整消息（含当前文档状态快照）
        system_prompt: 系统提示词
        transcript_note: 计入历史的精简版本；缺省则记 user_input 全文。
            文档状态是快照不是增量，累积全文会浪费 token 且让新旧状态互相矛盾，
            所以主循环应传一句话的回合说明。
        record: 置 False 时只读历史不写入（用于不属于建模主线的旁路调用）

    Returns:
        LLM 返回的 JSON 对象，失败时返回 None
    """
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


def _build_cad_spec_prompt() -> str:
    """正文见 app/prompts/cad_spec.md。"""
    return render("cad_spec")


def generate_cad_spec_with_llm(user_input: str):
    """Generate CAD Spec via LLM. Returns None when LLM unavailable."""
    from app.cad_spec.schemas import CADFeature, CADSpec, SpecGenerationResult

    result = call_llm(user_input, _build_cad_spec_prompt(), record=False)
    if result is None:
        return None

    status = result.get("status", "ok")
    if status == "need_more_info":
        return SpecGenerationResult(
            status="need_more_info",
            user_input=user_input,
            question=result.get("question") or result.get("message"),
            cad_spec=CADSpec(
                model_type="generic",
                features=[],
                unknowns=["model_type"],
            ),
        )

    raw_spec = result.get("cad_spec")
    if not isinstance(raw_spec, dict):
        print("[LLM Provider] cad_spec 字段缺失或无效")
        return None

    try:
        features = [CADFeature(**item) for item in raw_spec.get("features", [])]
        if not features:
            return None
        cad_spec = CADSpec(
            model_type=raw_spec.get("model_type", "generic"),
            unit=raw_spec.get("unit", "mm"),
            coordinate_system=raw_spec.get("coordinate_system", "XYZ"),
            features=features,
            dimensions=raw_spec.get("dimensions") or {},
            unknowns=raw_spec.get("unknowns") or [],
            assumptions=raw_spec.get("assumptions") or [],
        )
        return SpecGenerationResult(
            status="ok",
            user_input=user_input,
            cad_spec=cad_spec,
        )
    except Exception as exc:
        print(f"[LLM Provider] CAD Spec 解析失败: {exc}")
        return None


def generate_plan_with_llm(
    user_input: str,
    document_state: Optional[DocumentState] = None,
) -> Optional[dict]:
    """
    使用 LLM 生成建模计划

    Args:
        user_input: 用户的自然语言输入
        document_state: 当前文档状态（可选，注入到 prompt）

    Returns:
        建模计划字典，失败时返回 None
    """
    system_prompt = build_system_prompt(document_state)
    result = call_llm(user_input, system_prompt, record=False)

    if result is None:
        return None

    required_fields = ["status", "goal", "plan"]
    for field in required_fields:
        if field not in result:
            print(f"[LLM Provider] 缺少必需字段: {field}")
            return None

    if not isinstance(result["plan"], list):
        print("[LLM Provider] plan 字段必须是列表")
        return None

    result.setdefault("assumptions", [])
    result.setdefault("missing_params", [])
    result.setdefault("question", None)

    return result


def _build_high_level_plan_prompt(
    document_state: Optional[DocumentState] = None,
    user_input: str = "",
) -> str:
    """构建高层计划生成的 system prompt。正文见 app/prompts/high_level_plan.md。"""
    doc_context = _build_document_context(document_state)
    doc_section = f"\n{doc_context}\n" if doc_context else ""
    knowledge_section = ""
    try:
        from app.modeling_knowledge import match_knowledge, format_knowledge_for_prompt

        matches = match_knowledge(user_input or "", limit=2)
        knowledge_section = format_knowledge_for_prompt(matches)
        if knowledge_section:
            knowledge_section = f"\n{knowledge_section}\n"
    except Exception:
        knowledge_section = ""

    return render(
        "high_level_plan",
        DOC_SECTION=doc_section,
        KNOWLEDGE=knowledge_section,
    )


def generate_high_level_plan_with_llm(
    user_input: str,
    document_state: Optional[DocumentState] = None,
) -> Optional[dict]:
    """
    使用 LLM 生成高层建模计划（phase-level）。

    V0.7: 用于闭环架构的 start_plan 端点。
    """
    system_prompt = _build_high_level_plan_prompt(document_state, user_input=user_input)
    result = call_llm(user_input, system_prompt)

    if result is None:
        return None

    required_fields = ["status", "user_input", "goal", "phases"]
    for field in required_fields:
        if field not in result:
            print(f"[LLM Provider] 缺少必需字段: {field}")
            return None

    if not isinstance(result["phases"], list):
        print("[LLM Provider] phases 字段必须是列表")
        return None

    result.setdefault("assumptions", [])
    result.setdefault("question", None)

    return result


def _build_next_step_prompt(
    high_level_plan: dict,
    current_phase_id: str,
    execution_history: dict,
    name_map: dict[str, str],
    session_memory: dict | None = None,
    user_input: str = "",
    session_id: str | None = None,
    document_state: Optional[DocumentState] = None,
    current_abstract_step: dict | None = None,
) -> str:
    """构建单步规划生成的 system prompt。"""
    from app.runtime.context import build_llm_context

    tools_description = _build_tools_description()

    memory_text = build_llm_context(
        session_id=session_id,
        user_input=user_input,
        goal=high_level_plan.get("goal", ""),
        document_state=document_state,
        session_memory=session_memory,
        execution_history=execution_history,
        name_map=name_map,
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )

    # 当前阶段信息 + 全部阶段概览
    phases = high_level_plan.get("phases", [])
    from app.evaluation.phases import format_phases_overview
    phases_overview = format_phases_overview(high_level_plan, current_phase_id)
    current_phase = next((p for p in phases if p["phase_id"] == current_phase_id), None)
    phase_text = ""
    if current_phase:
        phase_text = f"""
## 当前阶段
- Phase ID: {current_phase_id}
- 标题: {current_phase.get('title', '')}
- 目标: {current_phase.get('intent', '')}
- 成功标准: {', '.join(current_phase.get('success_criteria', []))}
- 说明: 高层计划只给角色顺序；本步再决定具体建模路线与参数
"""

    knowledge_section = ""
    try:
        from app.modeling_knowledge import match_knowledge, format_knowledge_for_prompt

        intent_text = " ".join(
            [
                user_input or "",
                (current_phase or {}).get("intent", ""),
                (current_abstract_step or {}).get("intent", "")
                or (current_abstract_step or {}).get("title", ""),
            ]
        )
        knowledge_section = format_knowledge_for_prompt(match_knowledge(intent_text, limit=2))
        if knowledge_section:
            knowledge_section = f"\n{knowledge_section}\n"
    except Exception:
        knowledge_section = ""

    from app.design import format_design_brief

    design_brief = format_design_brief(
        user_input,
        high_level_plan=high_level_plan,
        goal=high_level_plan.get("goal", ""),
    )
    if design_brief:
        design_brief = f"\n{design_brief}\n"

    return render(
        "next_step",
        DESIGN_BRIEF=design_brief,
        PHASES=phases_overview,
        TOOLS=tools_description,
        PHASE_TEXT=phase_text,
        MEMORY=memory_text,
        KNOWLEDGE=knowledge_section,
        PHASE_ID=current_phase_id,
    )


def generate_next_tool_calls_with_llm(
    session_id: str,
    user_input: str,
    high_level_plan: dict,
    current_phase_id: str,
    document_state: DocumentState,
    execution_history: dict,
    name_map: dict[str, str],
    session_memory: dict | None = None,
) -> dict:
    """
    使用 LLM 生成下一步工具调用。

    V0.7: 用于闭环架构的 next_step 端点。
    """
    from app.memory.prompt import resolve_memory_pack, build_compact_document_context

    memory_pack = resolve_memory_pack(
        session_memory,
        execution_history,
        user_input=user_input,
        goal=high_level_plan.get("goal", ""),
        name_map=name_map,
        current_phase_id=current_phase_id,
    )
    system_prompt = _build_next_step_prompt(
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        execution_history=execution_history,
        name_map=name_map,
        session_memory=session_memory,
        user_input=user_input,
        session_id=session_id,
        document_state=document_state,
    )

    doc_context = build_compact_document_context(document_state, memory_pack)
    user_message = f"{doc_context}\n\n请生成下一步工具调用。"

    result = call_llm(
        user_message,
        system_prompt,
        transcript_note=f"[阶段 {current_phase_id}] 请生成下一步工具调用。",
    )

    if result is None:
        return {
            "decision": "abort",
            "phase_id": current_phase_id,
            "tool_calls": [],
            "message": "LLM 调用失败",
        }

    # 验证必需字段
    if "decision" not in result:
        result["decision"] = "execute"
    if "tool_calls" not in result:
        result["tool_calls"] = []

    result.setdefault("phase_id", current_phase_id)
    result.setdefault("message", None)
    result.setdefault("question", None)

    # Post-process: prevent premature finish
    from app.evaluation.phases import normalize_next_step_decision, get_next_phase_id

    normalized, advanced_phase = normalize_next_step_decision(
        result, high_level_plan, current_phase_id
    )
    if advanced_phase and not normalized.get("tool_calls"):
        # Re-generate tool calls for the new phase
        retry_prompt = _build_next_step_prompt(
            high_level_plan=high_level_plan,
            current_phase_id=advanced_phase,
            execution_history=execution_history,
            name_map=name_map,
            session_memory=session_memory,
            user_input=user_input,
            session_id=session_id,
            document_state=document_state,
        )
        retry_message = f"{doc_context}\n\n当前阶段 {current_phase_id} 已完成，请为阶段 {advanced_phase} 生成工具调用。"
        retry_result = call_llm(
            retry_message,
            retry_prompt,
            transcript_note=f"阶段 {current_phase_id} 已完成，请为阶段 {advanced_phase} 生成工具调用。",
        )
        if retry_result and retry_result.get("tool_calls"):
            normalized = retry_result
            normalized["decision"] = "execute"
            normalized["phase_id"] = advanced_phase
        else:
            normalized["decision"] = "execute"
            normalized["phase_id"] = advanced_phase

    return normalized


def _build_evaluate_prompt(
    high_level_plan: dict | None = None,
    current_phase_id: str | None = None,
) -> str:
    """构建步骤评估的 system prompt。正文见 app/prompts/evaluate.md。"""
    from app.design import format_design_brief
    from app.evaluation.phases import format_phases_overview

    phases_section = format_phases_overview(high_level_plan, current_phase_id)

    design_brief = format_design_brief(
        high_level_plan=high_level_plan,
        goal=(high_level_plan or {}).get("goal", ""),
    )
    if design_brief:
        design_brief = f"\n{design_brief}\n"

    return render(
        "evaluate",
        DESIGN_BRIEF=design_brief,
        PHASES=phases_section,
    )


def _summarize_execution_for_transcript(
    last_tool_call: dict,
    execution_result: dict,
    deterministic_checks: dict | None = None,
) -> str:
    """一行工具结果，形如 coding agent 的 tool result 消息。

    历史里保留的是「做了什么、成没成、产出了谁」，不是文档全量快照。
    """
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


def evaluate_step_with_llm(
    session_id: str,
    last_tool_call: dict,
    execution_result: dict,
    document_state: DocumentState,
    execution_history: dict,
    high_level_plan: dict | None = None,
    current_phase_id: str | None = None,
    *,
    deterministic_checks: dict | None = None,
    validator_results: list[dict] | None = None,
    current_abstract_step: dict | None = None,
    session_memory: dict | None = None,
) -> dict:
    """
    使用 LLM 评估步骤执行结果。

    V0.7: 用于闭环架构的 evaluate_step 端点。
    """
    system_prompt = _build_evaluate_prompt(high_level_plan, current_phase_id)

    from app.memory.prompt import resolve_memory_pack, build_compact_document_context
    from app.runtime.context import build_llm_context

    memory_pack = resolve_memory_pack(
        session_memory,
        execution_history,
        goal=(high_level_plan or {}).get("goal", ""),
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )
    memory_text = build_llm_context(
        session_id=session_id,
        goal=(high_level_plan or {}).get("goal", ""),
        document_state=document_state,
        session_memory=session_memory,
        execution_history=execution_history,
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )
    doc_context = build_compact_document_context(document_state, memory_pack)
    checks_section = ""
    if deterministic_checks is not None:
        checks_section += f"""## 确定性检查结果
```json
{json.dumps(deterministic_checks, ensure_ascii=False, indent=2)}
```

"""
    if validator_results is not None:
        checks_section += f"""## 几何校验结果
```json
{json.dumps(validator_results, ensure_ascii=False, indent=2)}
```

"""
    step_section = ""
    if current_abstract_step:
        step_section = f"""## 当前计划阶段
```json
{json.dumps(current_abstract_step, ensure_ascii=False, indent=2)}
```

"""

    user_message = f"""## 最后执行的工具调用
```json
{json.dumps(last_tool_call, ensure_ascii=False, indent=2)}
```

## 执行结果
```json
{json.dumps(execution_result, ensure_ascii=False, indent=2)}
```

{checks_section}{step_section}{memory_text}

{doc_context}

请结合上述记忆、检查结果与文档状态，评估执行结果并决定下一步动作。
"""

    result = call_llm(
        user_message,
        system_prompt,
        transcript_note=_summarize_execution_for_transcript(
            last_tool_call, execution_result, deterministic_checks
        ),
    )

    if result is None:
        checks_passed = (deterministic_checks or {}).get("passed", True)
        blocking_failed = any(
            (not item.get("passed")
             and item.get("validator") in {"verify_object_exists", "verify_shape_valid"})
            for item in (validator_results or [])
        )
        return {
            "decision": "continue",
            "phase_status": "completed" if checks_passed and not blocking_failed else "in_progress",
            "message": "LLM 调用失败，依据校验结果默认继续",
            "repair_tool_calls": [],
        }

    # 验证必需字段
    if "decision" not in result:
        result["decision"] = "continue"

    result.setdefault("phase_status", "in_progress")
    result.setdefault("message", None)
    result.setdefault("repair_tool_calls", [])
    # Decision normalization happens once, in workflow.evaluate (not here).
    return result

