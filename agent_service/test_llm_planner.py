"""
测试 V0.4 LLM 集成的计划生成功能
"""
import os
import sys
import json
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.llm.planner import generate_plan

def test_llm_planner():
    """测试 LLM 生成的计划"""
    
    test_cases = [
        "创建一个 100x60x20mm 的底座",
        "创建半径25mm、高度50mm的圆柱体",
        "我想要一个长宽高都是50mm的立方体",
        "做一个大一点的盒子，长200宽150高100",
    ]
    
    print("=" * 80)
    print("V0.4 LLM 计划生成测试")
    print("=" * 80)
    
    for i, user_input in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {user_input}")
        print("-" * 80)
        
        result = generate_plan(user_input)
        
        if result is None:
            print("❌ LLM 返回 None")
            continue
        
        print(f"状态: {result.get('status')}")
        print(f"目标: {result.get('goal')}")
        print(f"假设: {result.get('assumptions')}")
        print(f"缺失参数: {result.get('missing_params')}")
        
        if result.get('question'):
            print(f"问题: {result['question']}")
        
        plan = result.get('plan', [])
        print(f"\n计划步骤数: {len(plan)}")
        
        for step in plan:
            print(f"  - Step {step.get('step_id')}: {step.get('tool')}")
            print(f"    描述: {step.get('description')}")
            args = step.get('args', {})
            print(f"    参数: {json.dumps(args, ensure_ascii=False, indent=6)}")
        
        print("\n完整 JSON:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("-" * 80)


if __name__ == "__main__":
    test_llm_planner()
