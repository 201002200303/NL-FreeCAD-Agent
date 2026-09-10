# compound_tools.py — 把多个零件组合成单一对象（不做布尔）
#
# 为什么需要它：整机装配若用 fuse，boolean_tools 会 remove_objects 删掉源零件，
# 后续阶段的验收（object_exists Leg_R / Arm_R ...）就必然失败 —— 实测高达会话
# 因此在「fuse → 删源件 → 验收失败 → 删了重建」之间死循环。
# 而且 fuse 要求接触面有实体重叠（见 chat_core.md「接触与布尔」），共面/微隙
# 会静默产成多实体，于是又被迫在提示词里加「轻嵌 1mm」的补丁。
#
# compound 只把零件装进一个容器：
#   - 零件仍是各自独立实体（不布尔、不要求重叠）
#   - 源零件保留，后续阶段仍可改单个零件
#   - 导出 STEP/STL 仍是单一文件（Part::Feature 可直接作 export target）

import Part

from AICADAgent.cad_tools._helpers import get_object, get_world_shape


def make_compound(doc, name="Compound", targets=None):
    """组合多个对象为一个 Part::Feature（Compound），保留全部源对象。"""
    if isinstance(targets, str):
        targets = [targets]
    names = [str(t).strip() for t in (targets or []) if str(t or "").strip()]
    if not names:
        raise ValueError(
            "make_compound 需要至少一个源对象：targets=['A', 'B']。"
            "若要把零件合并成一个实体，请用 boolean_fuse。"
        )

    shapes = []
    for source in names:
        try:
            shapes.append(get_world_shape(get_object(doc, source)))
        except ValueError as exc:
            raise ValueError(
                f"compound 源对象不可用: {exc}。"
                f"当前请求: {names}；请先创建或改用正确的对象名。"
            ) from exc

    compound = Part.makeCompound(shapes)

    feat = doc.addObject("Part::Feature", name)
    feat.Label = name
    # 几何已带世界坐标，Placement 保持单位矩阵（与 assign_shape_result 同约定）
    feat.Shape = compound

    return {
        "tool": "make_compound",
        "object": feat.Name,
        "label": feat.Label,
        "type": "Part::Feature",
        "sources": names,
        "source_count": len(names),
        "solids": len(compound.Solids),
    }
