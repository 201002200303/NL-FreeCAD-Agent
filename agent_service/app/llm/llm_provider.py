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

# 加载 .env（从 agent_service 目录）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


def _get_llm_config() -> tuple[str, str, str]:
    return (
        os.getenv("OPENAI_API_KEY", ""),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.getenv("LLM_MODEL", "gpt-4o-mini"),
    )


def build_system_prompt() -> str:
    """
    构建 system prompt，包含角色定义、工具列表、输出格式和规则
    """
    # 构建可用工具的描述
    tools_description = "## 可用的建模工具\n\n"
    for tool_name, tool_spec in TOOL_SPECS.items():
        tools_description += f"### {tool_name}\n"
        tools_description += f"**描述**: {tool_spec['description']}\n"
        tools_description += f"**参数**:\n"
        for param_name, param_info in tool_spec['parameters'].items():
            required = "✓ 必需" if param_name in tool_spec.get('required', []) else "可选"
            param_type = param_info.get('type', 'any')
            param_desc = param_info.get('description', '')
            default = param_info.get('default', '')
            default_str = f"，默认值: {default}" if default else ""
            tools_description += f"  - `{param_name}` ({param_type}, {required}): {param_desc}{default_str}\n"
        tools_description += "\n"

    system_prompt = f"""你是一个专业的 CAD 建模助手，负责将用户的自然语言建模需求转换为可执行的建模计划。

## 你的任务
1. 理解用户的建模需求
2. 从可用工具中选择合适的工具
3. 为每个工具调用提取必要的参数
4. 生成一个完整的建模计划（JSON 格式）

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
      "description": "这一步做什么"
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

2. **对象命名**：
   - 为每个创建的对象使用有意义的英文名称（如 "BasePlate", "Pillar", "MainBody"）
   - 避免使用默认名称如 "Box", "Cylinder"

3. **步骤顺序**：
   - 按照逻辑顺序排列步骤（如先创建基础，再添加细节）
   - step_id 使用递增数字：step_1, step_2, step_3...

4. **信息不足时**：
   - 如果无法确定建模目标，设置 status 为 "need_more_info"
   - 在 question 字段中提出具体问题
   - plan 数组可以为空

5. **只使用已实现工具**：
   - 目前只实现了 create_box 和 create_cylinder
   - 如果用户需求需要其他工具，说明当前不支持

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
      "description": "创建 100x60x20mm 的长方体底座"
    }}
  ],
  "assumptions": ["使用毫米作为单位"],
  "missing_params": []
}}
```

**用户输入**: "创建一个圆柱体，半径25mm，高度50mm"

**输出**:
```json
{{
  "status": "ok",
  "goal": "创建一个圆柱体",
  "plan": [
    {{
      "step_id": "step_1",
      "tool": "create_cylinder",
      "args": {{
        "name": "Pillar",
        "radius": 25,
        "height": 50,
        "unit": "mm"
      }},
      "description": "创建半径25mm、高度50mm的圆柱体"
    }}
  ],
  "assumptions": [],
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
            max_tokens=2000
        )
        
        content = response.choices[0].message.content
        
        # 解析 JSON
        try:
            result = json.loads(content)
            return result
        except json.JSONDecodeError as e:
            print(f"[LLM Provider] JSON 解析失败: {e}")
            print(f"[LLM Provider] 原始输出: {content}")
            return None
            
    except Exception as e:
        print(f"[LLM Provider] API 调用失败: {e}")
        return None


def generate_plan_with_llm(user_input: str) -> Optional[dict]:
    """
    使用 LLM 生成建模计划
    
    Args:
        user_input: 用户的自然语言输入
        
    Returns:
        建模计划字典，失败时返回 None
    """
    system_prompt = build_system_prompt()
    result = call_llm(user_input, system_prompt)
    
    if result is None:
        return None
    
    # 验证返回格式
    required_fields = ["status", "goal", "plan"]
    for field in required_fields:
        if field not in result:
            print(f"[LLM Provider] 缺少必需字段: {field}")
            return None
    
    # 确保 plan 是列表
    if not isinstance(result["plan"], list):
        print("[LLM Provider] plan 字段必须是列表")
        return None
    
    # 添加默认值
    result.setdefault("assumptions", [])
    result.setdefault("missing_params", [])
    result.setdefault("question", None)
    
    return result
