"""
=============================================================================
FastAPI 教学示例 — 业务逻辑层 (planner.py)
=============================================================================
关键设计原则：这个文件是纯 Python，不 import 任何 FastAPI 的东西。

为什么这样设计？
  - 你可以直接在命令行 python planner.py 测试它，不需要启动服务器
  - 以后把规则匹配换成 LLM，只需要改这个文件，main.py 一行不动
  - 写单元测试时，不需要 mock 任何 HTTP 相关的东西

这就是 FastAPI 推崇的"关注点分离"：
  main.py    → 关心 HTTP（路由、请求解析、响应序列化）
  schemas.py → 关心数据形状（校验、文档）
  planner.py → 关心业务逻辑（建模推理）
=============================================================================
"""

import re


def generate_plan(user_input: str) -> dict:
    """
    根据用户输入生成建模计划的纯函数。

    Args:
        user_input: 用户原始输入文本，如 "画一个 100x60x20mm 的底座"

    Returns:
        dict，结构必须与 schemas.PlanResponse 匹配。
        返回 dict 而不是 PlanResponse 对象，是为了保持纯函数风格 —
        组装 Pydantic 对象的活交给 main.py 的路由函数去做。
    """
    text = user_input.lower()

    # 提取尺寸：正则匹配 "100x60x20" 或 "100×60×20" 或 "100*60*20"
    dims = _extract_dimensions(user_input)

    # ─── 规则 1：长方体 / 底座 ───
    if any(kw in text for kw in ["底座", "长方体", "盒子", "box", "底板", "baseplate", "block"]):
        length = dims.get("length", 100)
        width = dims.get("width", 60)
        height = dims.get("height", 20)
        return {
            "status": "ok",
            "goal": f"创建一个 {length}×{width}×{height}mm 的长方体",
            "assumptions": ["单位默认为 mm"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": f"创建 {length}×{width}×{height}mm 长方体",
                    "tool": "create_box",
                    "args": {
                        "name": "BaseBlock",
                        "length": length,
                        "width": width,
                        "height": height,
                        "unit": "mm",
                    },
                    "depends_on": [],
                }
            ],
        }

    # ─── 规则 2：圆柱体 ───
    if any(kw in text for kw in ["圆柱", "cylinder", "柱体"]):
        radius = dims.get("radius", 25)
        height = dims.get("height", 50)
        return {
            "status": "ok",
            "goal": f"创建一个 R{radius}×H{height}mm 的圆柱体",
            "assumptions": ["单位默认为 mm"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": f"创建 R{radius}×H{height}mm 圆柱体",
                    "tool": "create_cylinder",
                    "args": {
                        "name": "Cylinder",
                        "radius": radius,
                        "height": height,
                        "unit": "mm",
                    },
                    "depends_on": [],
                }
            ],
        }

    # ─── 规则 3：草图 ───
    if any(kw in text for kw in ["草图", "sketch"]):
        return {
            "status": "ok",
            "goal": "创建草图",
            "assumptions": ["草图平面默认为 XY"],
            "missing_params": [],
            "question": None,
            "plan": [
                {
                    "step_id": "S1",
                    "description": "创建草图",
                    "tool": "create_sketch",
                    "args": {"name": "Sketch", "plane": "XY"},
                    "depends_on": [],
                }
            ],
        }

    # ─── 无法识别 ───
    return {
        "status": "need_more_info",
        "goal": "无法确定建模目标",
        "assumptions": [],
        "missing_params": [],
        "question": (
            "请描述您想创建的模型。"
            "当前支持：长方体（底座）、圆柱体、草图。"
            '示例："创建一个 100×60×20mm 的底座"'
        ),
        "plan": [],
    }


def simulate_execution(plan: list[dict]) -> list[dict]:
    """
    模拟执行建模计划（不会真的操作 FreeCAD，只返回模拟结果）。

    这个函数演示了：FastAPI 端点可以接收复杂的嵌套数据，
    经过业务逻辑处理后，返回结构化的结果。

    Args:
        plan: 步骤列表，每个步骤是 dict（已被 FastAPI 从 JSON 解析为 PlanStep 再转 dict）

    Returns:
        执行结果列表
    """
    results = []
    for step in plan:
        results.append({
            "step_id": step.get("step_id", "?"),
            "success": True,
            "message": f"[模拟执行] 调用工具 {step.get('tool', '?')}，参数 {step.get('args', {})}",
        })
    return results


# ─── 辅助函数 ───

def _extract_dimensions(text: str) -> dict[str, float]:
    """从文本中提取尺寸参数。"""
    dims: dict[str, float] = {}

    # 匹配 "100×60×20" 或 "100x60x20" 或 "100*60*20"
    pattern = r"(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)\s*[×x\*]\s*(\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    if match:
        dims["length"] = float(match.group(1))
        dims["width"] = float(match.group(2))
        dims["height"] = float(match.group(3))
        return dims

    # 匹配 "R25" 或 "半径25"
    radius_pattern = r"[Rr]\s*(\d+(?:\.\d+)?)"
    match = re.search(radius_pattern, text)
    if match:
        dims["radius"] = float(match.group(1))

    return dims


# =========================================================================
# 你可以直接运行这个文件来测试业务逻辑：
#   cd agent_service/tutorial
#   python planner.py
# =========================================================================
if __name__ == "__main__":
    print("=== 测试 generate_plan ===")
    result = generate_plan("画一个 100x60x20mm 的底座")
    print(f"status: {result['status']}")
    print(f"goal:   {result['goal']}")
    print(f"plan:   {result['plan'][0]['tool']} → {result['plan'][0]['args']}")

    print("\n=== 测试无法识别 ===")
    result2 = generate_plan("帮我做个复杂的装配体")
    print(f"status:   {result2['status']}")
    print(f"question: {result2['question']}")

    print("\n=== 测试 simulate_execution ===")
    results = simulate_execution(result["plan"])
    for r in results:
        print(f"  {r['step_id']}: {r['success']} — {r['message']}")