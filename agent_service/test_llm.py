"""测试 LLM API 是否可用"""
from app.llm.llm_provider import call_llm, build_system_prompt

system_prompt = build_system_prompt()
result = call_llm("create a box", system_prompt)

if result:
    print("LLM 调用成功！")
    print(f"状态: {result.get('status')}")
    print(f"目标: {result.get('goal')}")
    if result.get('plan'):
        print(f"计划步骤数: {len(result['plan'])}")
        for step in result['plan']:
            print(f"  - {step.get('tool')}: {step.get('description')}")
else:
    print("LLM 调用失败，请检查 API 配置")
