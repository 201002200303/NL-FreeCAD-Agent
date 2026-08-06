"""客户端截图策略：模型 capture 优先，未拍才补四视图。"""

from pathlib import Path
import importlib.util


def _load_viewport():
    path = Path(__file__).resolve().parents[1] / "freecad_addon" / "AICADAgent" / "viewport.py"
    spec = importlib.util.spec_from_file_location("aicad_viewport_policy", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_normalize_view_names_caps_and_dedupes():
    vp = _load_viewport()
    assert vp.normalize_view_names(["front", "front", "iso", "side", "top", "back"]) == [
        "front",
        "iso",
        "side",
        "top",
    ]


def test_extract_prefers_last_successful_capture():
    vp = _load_viewport()
    results = [
        {
            "tool_call": {"tool": "capture_views"},
            "execution_result": {
                "status": "success",
                "viewport_images": [{"name": "front", "image_b64": "A"}],
            },
        },
        {
            "tool_call": {"tool": "capture_views"},
            "execution_result": {
                "status": "success",
                "viewport_images": [
                    {"name": "side", "image_b64": "B"},
                    {"name": "iso", "image_b64": "C"},
                ],
            },
        },
    ]
    imgs = vp.extract_tool_capture_images(results)
    assert [x["name"] for x in imgs] == ["side", "iso"]


def test_autofill_only_when_cad_ok_without_capture_call():
    vp = _load_viewport()
    assert (
        vp.should_autofill_multiview(
            [
                {
                    "tool_call": {"tool": "execute_cad_program"},
                    "execution_result": {"status": "success"},
                }
            ]
        )
        is True
    )
    assert (
        vp.should_autofill_multiview(
            [
                {
                    "tool_call": {"tool": "execute_cad_program"},
                    "execution_result": {"status": "success"},
                },
                {
                    "tool_call": {"tool": "capture_views"},
                    "execution_result": {"status": "error"},
                },
            ]
        )
        is False
    )
    assert vp.should_autofill_multiview([]) is False
