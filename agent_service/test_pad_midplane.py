"""pad_sketch midplane 契约：length 在 midplane=true 时表示总厚度。"""

from app.tools.pad_params import resolve_pad_midplane_params


def test_midplane_with_side_type_keeps_total_thickness():
    """FC SideType=Two sides 对每侧施加 Length；入参 length 为总厚时须折半下发。"""
    p = resolve_pad_midplane_params(10.0, midplane=True, has_side_type=True)
    assert p["api_length"] == 5.0
    assert p["side_type"] == "Two sides"
    assert p["use_midplane_flag"] is False


def test_midplane_without_side_type_uses_midplane_flag():
    p = resolve_pad_midplane_params(10.0, midplane=True, has_side_type=False)
    assert p["api_length"] == 10.0
    assert p["use_midplane_flag"] is True
    assert p["side_type"] is None


def test_one_side_passthrough():
    p = resolve_pad_midplane_params(10.0, midplane=False, has_side_type=True)
    assert p["api_length"] == 10.0
    assert p["side_type"] == "One side"
    assert p["use_midplane_flag"] is False
