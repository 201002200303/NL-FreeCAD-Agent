"""pad_sketch midplane 参数契约。

midplane=True 时，调用方传入的 length 表示**总厚度**（关于草图面对称）。
FreeCAD 1.1+ 的 SideType=\"Two sides\" 会对每一侧施加 Length，故下发 API 时须折半。
实现见 freecad_addon/.../partdesign_tools.py（须与本函数语义一致）。
"""

from __future__ import annotations


def resolve_pad_midplane_params(
    length: float,
    *,
    midplane: bool,
    has_side_type: bool,
) -> dict:
    """返回下发给 FreeCAD Pad 的长度与对称方式。

    Returns:
        api_length: 写入 Pad.Length 的值
        side_type: \"Two sides\" | \"One side\" | None（无 SideType 属性时）
        use_midplane_flag: 是否设置旧版 Midplane=True
    """
    length = float(length)
    if midplane and has_side_type:
        return {
            "api_length": length / 2.0,
            "side_type": "Two sides",
            "use_midplane_flag": False,
        }
    if midplane:
        return {
            "api_length": length,
            "side_type": None,
            "use_midplane_flag": True,
        }
    if has_side_type:
        return {
            "api_length": length,
            "side_type": "One side",
            "use_midplane_flag": False,
        }
    return {
        "api_length": length,
        "side_type": None,
        "use_midplane_flag": False,
    }
