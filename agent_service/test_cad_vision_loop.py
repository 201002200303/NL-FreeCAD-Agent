"""多视图 VLM：成功执行后评估；失败/不可用降级跳过。"""

from app.vision.service import (
    assess_views,
    format_vision_for_prompt,
    needs_code_revision,
    vision_available,
)
from app.workflow.chat import classify_chat_step


def test_assess_views_skips_when_disabled(monkeypatch):
    monkeypatch.setattr("app.vision.service.vision_available", lambda **kw: False)
    res = assess_views(
        views=[{"name": "iso", "image_b64": "abc", "mime": "image/png"}],
        user_goal="建箱子",
    )
    assert res["skipped"] is True
    assert res["verdict"] == "skip"


def test_assess_views_skips_when_no_images():
    res = assess_views(views=[], user_goal="建箱子")
    assert res["skipped"] is True
    assert res["reason"] == "empty_images"


def test_assess_views_calls_vlm_with_multiple_images(monkeypatch):
    calls = {}

    class FakeChoice:
        def __init__(self):
            self.message = type("M", (), {"content": '{"verdict":"bad","summary":"左右不对称","issues":["右臂缺失"],"suggestions":["补右臂"]}'})()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeClient:
        def __init__(self, **kw):
            pass

        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    calls["kwargs"] = kwargs
                    return FakeResp()

    monkeypatch.setattr("app.vision.service.vision_available", lambda **kw: True)
    monkeypatch.setattr("app.config.VISION_API_KEY", "k")
    monkeypatch.setattr("app.config.VISION_MODEL", "vision-x")
    monkeypatch.setattr("app.config.VISION_BASE_URL", "http://x")
    monkeypatch.setattr("openai.OpenAI", FakeClient)

    res = assess_views(
        views=[
            {"name": "front", "image_b64": "AAA", "mime": "image/png"},
            {"name": "iso", "image_b64": "BBB", "mime": "image/png"},
        ],
        user_goal="建高达",
    )
    assert res["ok"] is True
    assert res["verdict"] == "bad"
    assert "右臂" in "".join(res["issues"])
    content = calls["kwargs"]["messages"][1]["content"]
    # text + 2 images
    assert len(content) == 3
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert "front" in content[0]["text"] or "多视图" in content[0]["text"]


def test_needs_code_revision_only_on_hard_issues():
    assert needs_code_revision({"verdict": "bad", "issues": ["缺腿"]}) is True
    assert needs_code_revision({"verdict": "warn", "issues": ["比例略怪"]}) is False
    assert needs_code_revision({"verdict": "ok"}) is False
    assert needs_code_revision({"skipped": True, "verdict": "skip"}) is False
    assert needs_code_revision(None) is False


def test_format_vision_mentions_revision_hint_when_bad():
    text = format_vision_for_prompt(
        {
            "ok": True,
            "verdict": "bad",
            "summary": "缺右臂",
            "issues": ["右臂缺失"],
            "suggestions": ["补右臂"],
            "revise_once": True,
        },
        allow_revise=True,
    )
    assert "execute_cad_program" in text or "修订" in text


def test_format_vision_budget_exhausted():
    text = format_vision_for_prompt(
        {"ok": True, "verdict": "bad", "summary": "仍悬空", "issues": ["悬空"], "revise_blocked": "budget"},
        memory={"stop_reason": "budget"},
        allow_revise=False,
    )
    assert "预算" in text or "不要继续" in text


def test_classify_chat_step_names():
    assert classify_chat_step(message="建箱", tool_results=None) == "code_gen"
    assert (
        classify_chat_step(
            message="",
            tool_results=[{"tool_call": {"tool": "execute_cad_program"}, "execution_result": {"status": "error"}}],
        )
        == "code_repair"
    )
    assert (
        classify_chat_step(
            message="",
            tool_results=[{"tool_call": {"tool": "execute_cad_program"}, "execution_result": {"status": "success"}}],
            vision_hard_issue=True,
        )
        == "vision_revise"
    )
    assert (
        classify_chat_step(
            message="",
            tool_results=[{"tool_call": {"tool": "execute_cad_program"}, "execution_result": {"status": "success"}}],
        )
        == "tool_feedback"
    )
