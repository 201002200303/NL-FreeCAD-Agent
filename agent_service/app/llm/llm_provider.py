"""
LLM Provider - 集成 OpenAI-compatible API，生成建模计划
"""
import json
import os
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
        "7. 引用已有对象用其名称；修改操作用 target 字段指向已有对象。\n"
        "8. 每步后会回传新的世界坐标 bbox，请核对实际落点再继续。"
    )
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
        tools_description = _build_tools_description(
            resolve_tool_specs_for_prompt(tool_categories, allow_subset=True)
        )
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
        from openai import OpenAI

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

        message = response.choices[0].message
        content = _message_text(message)

        try:
            result = _extract_json_object(content)
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


def _build_cad_spec_prompt() -> str:
    return """你是一个 CAD 需求分析助手，负责将自然语言建模需求转成结构化 CAD Spec。

## 你的任务
1. 理解用户想建什么（包括开放需求如汽车、家具、机械件）
2. 输出结构化 features 列表，描述「要做什么」而非「怎么建」
3. 缺少尺寸时使用合理工程默认值，写入 assumptions
4. **禁止**输出 tool calls、FreeCAD 命令或具体对象名

## 输出 JSON 格式

```json
{
  "status": "ok" 或 "need_more_info",
  "user_input": "原始输入",
  "cad_spec": {
    "model_type": "car / box / lamp / shaft / generic 等",
    "unit": "mm",
    "coordinate_system": "XYZ",
    "features": [
      {
        "type": "body / box / cylinder / wheel / fillet / hole / chamfer 等",
        "name_hint": "语义名称如 Body / Wheel_FL",
        "dimensions": {"length": 100, "width": 60, "height": 20},
        "position": "relative hint 如 on_chassis_corner",
        "target_hint": "selected_or_primary_solid 或 null",
        "parameters": {}
      }
    ],
    "dimensions": {},
    "unknowns": [],
    "assumptions": ["未指定尺寸时的默认假设"]
  },
  "question": "status=need_more_info 时提问"
}
```

## 规则
- features 至少 1 项；开放模型（汽车）拆成 body、wheel、cabin 等语义 feature
- dimensions 缺省时给出合理 mm 默认值
- 无法理解的输入才返回 need_more_info
"""


def generate_cad_spec_with_llm(user_input: str):
    """Generate CAD Spec via LLM. Returns None when LLM unavailable."""
    from app.cad_spec.schemas import CADFeature, CADSpec, SpecGenerationResult

    result = call_llm(user_input, _build_cad_spec_prompt())
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
2. 将建模任务分解为若干个逻辑阶段（phase），类似 Cursor 的任务清单
3. 每个阶段只描述**意图与成功标准**，不要写具体工具、参数或尺寸
4. 具体尺寸、坐标、工具选择留给后续逐步执行（会读取实时文档状态）

## 重要约束
- **禁止**输出 tool calls、FreeCAD 命令、对象名、具体 mm 数值
- 阶段划分按建模逻辑顺序（先主体后细节）
- 开放模型（汽车、家具等）拆成 3~6 个可独立验证的阶段即可
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
      "intent": "这个阶段要做什么（意图级，不含尺寸）",
      "success_criteria": [
        "可验证的成功标准1",
        "可验证的成功标准2"
      ]
    }}
  ],
  "assumptions": ["仅记录用户已明确或必须说明的假设"],
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
    session_memory: dict | None = None,
    user_input: str = "",
) -> str:
    """构建单步规划生成的 system prompt。"""
    from app.memory.prompt import format_memory_for_prompt, resolve_memory_pack

    tools_description = _build_tools_description()

    memory_pack = resolve_memory_pack(
        session_memory,
        execution_history,
        user_input=user_input,
        goal=high_level_plan.get("goal", ""),
        name_map=name_map,
        current_phase_id=current_phase_id,
    )
    memory_text = format_memory_for_prompt(memory_pack, name_map=name_map)

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
3. 查看工作记忆（对象索引、查询缓存、错误记忆、最近关键事件）
4. 判断当前步骤缺少哪些几何事实
5. 为**当前阶段**生成下一步的工具调用（数量不限；可一次批量创建多个独立对象，如四个轮子）

{phases_overview}

{tools_description}

{phase_text}

{memory_text}

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
   - 一次可返回**任意数量**的 tool_calls，不要人为拆成 3 个一批；对称/重复部件（如四个轮子、多根立柱）应同一步批量创建
   - 可使用 registry 中**任意已注册工具**（primitives / boolean / features / transform / sketch / partdesign / surface / assembly / query / export），不要自我限制为 create_box/create_cylinder
   - tool 名称必须完全匹配 registry
   - 必填参数必须全部提供
   - query 工具也是合法 tool call；当缺少几何事实时，先 query，不要猜坐标

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

6. **Query-before-act**：
   - `summarize_document`：需要先了解当前文档对象树时使用
   - `get_object_detail(target)`：移动、贴附、对齐、修改已有对象前必须优先考虑
   - `measure_gap(obj_a, obj_b, axis)`：判断两个对象是否贴附/悬空时使用
   - `compare_orientation(target, expected_axis)`：判断车轮、杆件、圆柱朝向时使用
   - `list_topology(target)`：fillet/chamfer/boolean/sketch-on-face 或选择 face/edge 前使用
   - 对 `set_placement`、`move`、`rotate`、`add_fillet`、`add_chamfer`、`boolean_*`、`cut_hole`、`create_sketch_on_face`、`pad_to_face` 这类空间/拓扑敏感操作，如果 query_cache 没有相关 target，先返回 query tool call
   - query call 不代表阶段完成；query 后下一轮必须基于 query_cache / 对象索引 选择 act tool
   - 如果 query_cache 已有同一 target，不要重复 query；直接 act
   - 如果错误记忆中有 last_error 且 avoid_repeating=true，不要原样重试同一 tool+args；先修复根因或换方案

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
        session_memory=memory_pack,
        user_input=user_input,
    )

    doc_context = build_compact_document_context(document_state, memory_pack)
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
            session_memory=memory_pack,
            user_input=user_input,
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
   - 默认不要用 produced_objects、对象存在性、shape_valid、gap、orientation 阻断流程；这些只作为 debug/strict trace

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

    from app.memory.prompt import resolve_memory_pack, format_memory_for_prompt, build_compact_document_context

    memory_pack = resolve_memory_pack(
        session_memory,
        execution_history,
        goal=(high_level_plan or {}).get("goal", ""),
        current_phase_id=current_phase_id,
        current_abstract_step=current_abstract_step,
    )
    memory_text = format_memory_for_prompt(memory_pack)
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

    result = call_llm(user_message, system_prompt)

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

    from app.evaluation.phases import normalize_evaluate_decision
    return normalize_evaluate_decision(result, high_level_plan, current_phase_id)
