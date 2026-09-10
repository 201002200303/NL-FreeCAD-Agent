# geometry_facts.py — 几何事实的唯一来源
#
# FreeCAD/OCC 的 Shape.BoundBox 对曲面是近似值：torus R20/r5 实测 54.12，真实外径 50
# （+8.2%）。它被用作验收 bbox_size、对齐/测量基准，会直接造成验收误判与对齐偏移。
# optimalBoundingBox() 给出紧致包围盒，且同样是世界坐标（含 Placement）。

import FreeCAD  # noqa: F401  (仅在 FreeCAD 环境可用)


def exact_bbox(shape):
    """Tight world-space bounding box for a Shape.

    优先 optimalBoundingBox()（对曲面紧致），无该 API 或失败时退回 BoundBox。
    """
    optimal = getattr(shape, "optimalBoundingBox", None)
    if optimal is not None:
        try:
            return optimal()
        except Exception:
            pass
    return shape.BoundBox
