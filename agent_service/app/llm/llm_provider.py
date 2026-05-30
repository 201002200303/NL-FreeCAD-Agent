"""
LLM Provider - 集成 OpenAI-compatible API，生成建模计划
"""
import json
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from app.tools.tool_specs import TOOL_SPECS
from app.tools.tool_registry import build_tools_description, get_tools_by_categories
from app.schemas.cad_state import DocumentState
from app.debug.trace_logger import (
    get_current_step_name,
    get_trace_session,
    is_debug_enabled,
)

# 加载 .env（从 agent_service 目录）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


def _get_llm_config() -> tuple[str, str, str]:
    return (
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.getenv("LLM_MODEL", "gpt-4o-mini"),
    )


def _build_tools_description(tool_specs: dict | None = None) -> str:
    """Build the tools section of the system prompt."""
    return build_tools_description(tool_specs or TOOL_SPECS)


def _build_document_context(document_state: Optional[DocumentState]) -> str:
    """Build a text summary of the current document state for the LLM."""
    if not document_state or not document_state.objects:
        return ""

    lines = ["## 当前文档状态\n"]
    lines.append(f"文档名称: {document_state.document_name}")

    if document_state.objects:
        lines.append(f"文档中已有 {len(document_state.objects)} 个对象:")
        for obj in document_state.objects:
            props_str = ""
            if obj.properties:
                prop_items = [f"{k}={v}" for k, v in obj.properties.items()]
                props_str = f"，属性: {', '.join(prop_items)}"
            lines.append(f"  - `{obj.name}` (类型: {obj.type}){props_str}")

    if document_state.selected_objects:
        lines.append(f"当前选中: {', '.join(f'`{s}`' for s in document_state.selected_objects)}")

    lines.append("\n请在计划中引用已有对象的名称，修改操作使用 target 字段指向已有对象。")
    return "\n".join(lines)


def build_system_prompt(
    document_state: Optional[DocumentState] = None,
    tool_categories: list[str] | None = None,
    tool_specs: dict | None = None,
) -> str:
    """
    构建 system prompt，包含角色定义、工具列表、输出格式和规则。
    可选注入文档状态上下文；可按类别或 spec 子集注入工具。
    """
    if tool_specs is not None:
        tools_description = _build_tools_description(tool_specs)
    elif tool_categories:
        tools_description = _build_tools_description(get_tools_by_categories(tool_categories))
    else:
        tools_description = _build_tools_description()
    doc_context = _build_document_context(document_state)

    doc_section = f"\n{doc_context}\n" if doc_context else ""

    system_prompt = f"""你是一个专业的 CAD 建模助手，负责将用户的自然语言建模需求转换为可执行的建模计划。

## 你的任务
1. 理解用户的建模需求
2. 从可用工具中选择合适的工具
3. 为每个工具调用提取必要的参数
4. 生成一个完整的建模计划（JSON 格式）
{doc_section}
{tools_description}

## 输出格式要求

你必须返回一个 JSON 对象，包含以下字段：

```json
{{
  "status": "ok" 或 "need_more_info",
  "goal": "一句话描述建模目标",
  "plan": [
    {{
      "step_id": "step_1",
      "tool": "工具名称",
      "args": {{
        "参数1": "值1",
        "参数2": "值2"
      }},
      "description": "这一步做什么",
      "depends_on": []
    }}
  ],
  "assumptions": ["做出的假设1", "假设2"],
  "missing_params": ["缺少的参数1"],
  "question": "如果需要更多信息，提出问题（可选）"
}}
```

## 规则

1. **参数提取**：
   - 如果用户提供了具体数值（如"100mm"、"R25"），必须使用这些值
   - 如果用户未提供尺寸参数，询问用户而不是猜测
   - 长度单位默认使用 mm
   - 数值类型参数必须使用数字（不是字符串），例如 "length": 100 而非 "length": "100"

2. **对象命名**：
   - 为每个创建的对象使用有意义的英文名称（如 "BasePlate", "Pillar", "MainBody"）
   - 避免使用默认名称如 "Box", "Cylinder"

3. **步骤顺序**：
   - 按照逻辑顺序排列步骤（如先创建基础，再添加细节）
   - step_id 使用递增数字：step_1, step_2, step_3...
   - depends_on 用于标记步骤间的依赖关系

4. **信息不足时**：
   - 如果无法确定建模目标，设置 status 为 "need_more_info"
   - 在 question 字段中提出具体问题
   - plan 数组可以为空

5. **工具使用约束**：
   - 只使用上面列出的工具，tool 名称必须完全匹配
   - 必填参数必须全部提供
   - 修改/删除/导出类工具的 target 必须引用已有对象或前面步骤创建的对象名

## 示例

**用户输入**: "创建一个 100x60x20mm 的底座"

**输出**:
```json
{{
  "status": "ok",
  "goal": "创建一个长方体底座",
  "plan": [
    {{
      "step_id": "step_1",
      "tool": "create_box",
      "args": {{
        "name": "BasePlate",
        "length": 100,
        "width": 60,
        "height": 20,
        "unit": "mm"
      }},
      "description": "创建 100x60x20mm 的长方体底座",
      "depends_on": []
    }}
  ],
  "assumptions": ["使用毫米作为单位"],
  "missing_params": []
}}
```
"""
    return system_prompt


def call_llm(user_input: str, system_prompt: str) -> Optional[dict]:
    """
    调用 LLM API 获取结构化输出

    Args:
        user_input: 用户的自然语言输入
        system_prompt: 系统提示词

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

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=40960
        )

        content = response.choices[0].message.content

        try:
            result = json.loads(content)
            if trace and step_name:
                trace.log_llm_call(
                    step_name,
                    label=llm_label,
                    system_prompt=system_prompt,
                    user_message=user_input,
                    raw_response=response,
                    parsed=result,
                    model=model,
                )
            return result
        except json.JSONDecodeError as e:
            print(f"[LLM Provider] JSON 解析失败: {e}")
            print(f"[LLM Provider] 原始输出: {content}")
            if trace and step_name:
                trace.log_llm_call(
                    step_name,
                    label=llm_label,
                    system_prompt=system_prompt,
                    user_message=user_input,
                    raw_response=response,
                    parsed=None,
                    model=model,
                    error=str(e),
                )
            return None

    except Exception as e:
        print(f"[LLM Provider] API 调用失败: {e}")
        if trace and step_name:
            trace.log_llm_call(
                step_name,
                label=llm_label,
                system_prompt=system_prompt,
                user_message=user_input,
                raw_response=None,
                parsed=None,
                model=model,
                error=str(e),
            )
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
    result = call_llm(user_input, system_prompt)

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


def _build_high_level_plan_prompt(document_state: Optional[DocumentState] = None) -> str:
    """构建高层计划生成的 system prompt。"""
    doc_context = _build_document_context(document_state)
    doc_section = f"\n{doc_context}\n" if doc_context else ""

    return f"""你是一个专业的 CAD 建模助手，负责将用户的自然语言建模需求分解为高层建模阶段。

## 你的任务
1. 理解用户的建模需求
2. 将建模任务分解为若干个逻辑阶段（phase）
3. 为每个阶段定义目标和成功标准
4. **不要**生成具体的工具调用或参数
{doc_section}

## 输出格式要求

你必须返回一个 JSON 对象，包含以下字段：

```json
{{
  "status": "ok" 或 "need_more_info",
  "user_input": "用户原始输入",
  "goal": "一句话描述建模目标",
  "phases": [
    {{
      "phase_id": "P1",
      "title": "阶段标题",
      "intent": "这个阶段要做什么",
      "success_criteria": [
        "成功标准1",
        "成功标准2"
      ]
    }}
  ],
  "assumptions": ["假设1", "假设2"],
  "question": "如果需要更多信息，提出问题（可选）"
}}
```

## 规则

1. **阶段划分**：
   - 按照逻辑顺序划分阶段（如先创建基础，再添加细节）
   - 每个阶段应该有明确的目标
   - phase_id 使用 P1, P2, P3...

2. **成功标准**：
   - 为每个阶段定义可验证的成功标准
   - 例如："存在一个可见的底座实体"、"底座顶部有圆角"

3. **信息不足时**：
   - 如果无法确定建模目标，设置 status 为 "need_more_info"
   - 在 question 字段中提出具体问题

## 示例

**用户输入**: "创建一个台灯模型"

**输出**:
```json
{{
  "status": "ok",
  "user_input": "创建一个台灯模型",
  "goal": "创建一个由底座、支柱、灯罩组成的台灯模型",
  "phases": [
    {{
      "phase_id": "P1",
      "title": "底座",
      "intent": "创建圆柱底座并倒圆角",
      "success_criteria": [
        "存在一个可见的底座实体",
        "底座大致为圆柱形",
        "底座有圆角"
      ]
    }},
    {{
      "phase_id": "P2",
      "title": "支柱",
      "intent": "在底座中心创建竖直支柱",
      "success_criteria": [
        "支柱位于底座中心",
        "支柱底部与底座相接"
      ]
    }},
    {{
      "phase_id": "P3",
      "title": "灯罩",
      "intent": "在支柱顶部创建灯罩",
      "success_criteria": [
        "灯罩位于支柱顶部"
      ]
    }}
  ],
  "assumptions": ["单位使用 mm"]
}}
```
"""


def generate_high_level_plan_with_llm(
    user_input: str,
    document_state: Optional[DocumentState] = None,
) -> Optional[dict]:
    """
    使用 LLM 生成高层建模计划（phase-level）。

    V0.7: 用于闭环架构的 start_plan 端点。
    """
    system_prompt = _build_high_level_plan_prompt(document_state)
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
) -> str:
    """构建单步规划生成的 system prompt。"""
    tools_description = _build_tools_description()

    # 构建历史摘要
    history_text = ""
    recent = execution_history.get("recent", [])
    if recent:
        history_text = "## 最近执行历史\n"
        for entry in recent[-5:]:  # 最近5步
            status = entry.get("status", "unknown")
            tool = entry.get("tool", "")
            msg = entry.get("message", "")
            history_text += f"- {tool}: {status}"
            if msg:
                history_text += f" - {msg}"
            history_text += "\n"

    # 构建 name_map
    name_map_text = ""
    if name_map:
        name_map_text = "## 对象名称映射\n"
        for old, new in name_map.items():
            name_map_text += f"- {old} → {new}\n"

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
"""

    return f"""你是一个专业的 CAD 建模助手，负责根据当前文档状态和高层计划，生成下一步的具体工具调用。

## 你的任务
1. 查看当前文档状态
2. 查看高层计划和当前阶段
3. 查看最近执行历史
4. 为**当前阶段**生成下一步的工具调用（1-3个）

{phases_overview}

{tools_description}

{phase_text}

{history_text}

{name_map_text}

## 输出格式要求

你必须返回一个 JSON 对象，包含以下字段：

```json
{{
  "decision": "execute" 或 "ask_user" 或 "finish" 或 "abort",
  "phase_id": "当前阶段ID",
  "tool_calls": [
    {{
      "call_id": "P1_S1",
      "tool": "工具名称",
      "args": {{
        "参数1": "值1"
      }},
      "description": "这一步做什么",
      "expected_effect": {{
        "new_object": "预期生成的对象名",
        "type": "预期对象类型"
      }}
    }}
  ],
  "message": "决策说明（可选）",
  "question": "如果 decision 是 ask_user，提出问题"
}}
```

## 规则

1. **工具调用**：
   - 每次生成 1-3 个工具调用
   - 只使用可用工具，tool 名称必须完全匹配
   - 必填参数必须全部提供

2. **对象引用**：
   - 使用 name_map 中的最新名称引用对象
   - 例如：如果 name_map 有 "Base" → "Base_Fillet"，则使用 "Base_Fillet"
   - fillet/chamfer/cut_hole 等特征工具默认生成新对象（如 TableLamp_Hole），后续步骤应引用新对象名

3. **决策类型**：
   - execute: 继续执行工具调用（当前阶段还有步骤要做）
   - ask_user: 需要用户输入更多信息
   - finish: **仅当所有阶段（P1~Pn）全部完成**时才可使用
   - abort: 无法继续

4. **阶段规则**：
   - 当前阶段完成后，**不要**返回 finish，应继续为当前或下一阶段生成 tool_calls
   - 如果当前阶段 intent 已满足但还有后续阶段，继续 execute 并生成下一阶段的 tool_calls（phase_id 改为下一阶段）

5. **call_id 格式**：
   - 使用 {current_phase_id}_S1, {current_phase_id}_S2...

## 示例

**输出**:
```json
{{
  "decision": "execute",
  "phase_id": "P1",
  "tool_calls": [
    {{
      "call_id": "P1_S1",
      "tool": "create_cylinder",
      "args": {{
        "name": "Base",
        "radius": 90,
        "height": 20
      }},
      "description": "创建圆柱底座",
      "expected_effect": {{
        "new_object": "Base",
        "type": "Part::Cylinder"
      }}
    }}
  ]
}}
```
"""


def generate_next_tool_calls_with_llm(
    session_id: str,
    user_input: str,
    high_level_plan: dict,
    current_phase_id: str,
    document_state: DocumentState,
    execution_history: dict,
    name_map: dict[str, str],
) -> dict:
    """
    使用 LLM 生成下一步工具调用。

    V0.7: 用于闭环架构的 next_step 端点。
    """
    system_prompt = _build_next_step_prompt(
        high_level_plan=high_level_plan,
        current_phase_id=current_phase_id,
        execution_history=execution_history,
        name_map=name_map,
    )

    # 构建用户消息（包含文档状态）
    doc_context = _build_document_context(document_state)
    user_message = f"{doc_context}\n\n请生成下一步工具调用。"

    result = call_llm(user_message, system_prompt)

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
        )
        retry_message = f"{doc_context}\n\n当前阶段 {current_phase_id} 已完成，请为阶段 {advanced_phase} 生成工具调用。"
        retry_result = call_llm(retry_message, retry_prompt)
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
    """构建步骤评估的 system prompt。"""
    from app.evaluation.phases import format_phases_overview

    phases_section = format_phases_overview(high_level_plan, current_phase_id)

    return f"""你是一个专业的 CAD 建模助手，负责评估工具调用的执行结果，并决定下一步动作。

{phases_section}

## 你的任务
1. 查看最后执行的工具调用和结果
2. 查看当前文档状态
3. 判断**当前阶段**的执行是否成功
4. 决定下一步动作（继续当前阶段 / 进入下一阶段 / 修复）

## 输出格式要求

你必须返回一个 JSON 对象，包含以下字段：

```json
{{
  "decision": "continue" 或 "repair" 或 "skip_and_continue" 或 "finish" 或 "replan" 或 "abort",
  "phase_status": "in_progress" 或 "completed" 或 "failed",
  "updated_current_phase_id": "当前阶段ID（如果阶段完成则指向下一阶段）",
  "message": "决策说明",
  "repair_tool_calls": [
    {{
      "tool": "工具名称",
      "args": {{}},
      "description": "修复步骤"
    }}
  ]
}}
```

## 决策类型

- **continue**: 执行成功，继续下一步
- **repair**: 执行失败，需要修复（提供 repair_tool_calls）
- **skip_and_continue**: 执行失败，跳过此步骤继续
- **finish**: **仅当所有阶段全部完成**时才可使用（最后一个阶段的成功标准已满足）
- **replan**: 需要重新规划当前阶段
- **abort**: 无法继续，终止执行

## 评估规则

1. **成功判断**：
   - 检查 execution_result.status 是否为 "success"
   - 检查 produced_objects 是否符合预期

2. **阶段完成 vs 全部完成**：
   - 当前阶段 intent 满足 → phase_status="completed", decision="continue", updated_current_phase_id 指向**下一阶段**
   - **禁止**在当前阶段完成但还有后续阶段时返回 decision="finish"
   - 只有最后一个阶段完成时才返回 decision="finish"

3. **失败处理**：
   - 参数问题 → repair
   - 无法修复 → skip_and_continue

## 示例（P1 完成，还有 P2）

**输出**:
```json
{{
  "decision": "continue",
  "phase_status": "completed",
  "updated_current_phase_id": "P2",
  "message": "P1 底座完成，进入 P2 灯杆"
}}
```
"""


def evaluate_step_with_llm(
    session_id: str,
    last_tool_call: dict,
    execution_result: dict,
    document_state: DocumentState,
    execution_history: dict,
    high_level_plan: dict | None = None,
    current_phase_id: str | None = None,
) -> dict:
    """
    使用 LLM 评估步骤执行结果。

    V0.7: 用于闭环架构的 evaluate_step 端点。
    """
    system_prompt = _build_evaluate_prompt(high_level_plan, current_phase_id)

    # 构建用户消息
    doc_context = _build_document_context(document_state)

    user_message = f"""## 最后执行的工具调用
```json
{json.dumps(last_tool_call, ensure_ascii=False, indent=2)}
```

## 执行结果
```json
{json.dumps(execution_result, ensure_ascii=False, indent=2)}
```

{doc_context}

请评估执行结果并决定下一步动作。
"""

    result = call_llm(user_message, system_prompt)

    if result is None:
        # 默认继续
        return {
            "decision": "continue",
            "phase_status": "in_progress",
            "message": "LLM 调用失败，默认继续",
        }

    # 验证必需字段
    if "decision" not in result:
        result["decision"] = "continue"

    result.setdefault("phase_status", "in_progress")
    result.setdefault("message", None)
    result.setdefault("repair_tool_calls", [])

    from app.evaluation.phases import normalize_evaluate_decision
    return normalize_evaluate_decision(result, high_level_plan, current_phase_id)
