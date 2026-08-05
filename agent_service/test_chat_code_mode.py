"""chat code-mode 主路径：execute_cad_program 可见，53 工具 schema 不再进 system。"""

from app.workflow.chat import build_chat_system_prompt


def test_chat_system_offers_code_mode_not_53_tool_schemas():
    prompt = build_chat_system_prompt(
        message="建一个高达",
        user_goal="建一个高达",
        plan_mode=False,
        vision_on=False,
    )

    assert "execute_cad_program" in prompt
    # 旧工具 schema 标题不应出现
    assert "### create_box" not in prompt
    assert "### mate_coaxial" not in prompt
    assert "### pad_sketch" not in prompt
    assert "当前工具工作集" not in prompt  # 旧工作集注入已移除
    # code mode 语义
    assert "cad.box" in prompt or "cad.*" in prompt or "CAD 程序" in prompt
