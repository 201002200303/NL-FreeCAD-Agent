"""导出目标选择（不依赖 FreeCAD / Qt，便于单测）。

`export_step` / `export_stl` 原先只接受单个 target，于是「多零件模型」必须先
fuse 成整机才能导出 —— 这正是装配阶段被迫做布尔、进而删源件的根源。

现在：
    target=""            导出文档内全部**可见**实体对象
    target="Mecha"       单个对象（显式点名时允许隐藏对象）
    target=["A", "B"]    多个对象（调用方组合成 compound 再导出）

真源是 FreeCAD 文档；这里只做「按名字挑出可导出对象」的纯决策。

为什么整文档导出要排除隐藏对象：`hole`/`fillet`/`chamfer` 走
`assign_shape_result` —— 新建结果对象并把**原参数件 Visibility=False**。
若把它们一起导出，STEP 里会出现新旧两份重叠几何（本项目一直在治的「叠影」）。
显式点名时则放行，因为那是「我就要这个」。
"""

from __future__ import annotations

# 基准/原点类对象不是几何实体，导出它们会产出空文件
SKIP_TYPE_IDS = frozenset({
    "App::Origin",
    "App::Line",
    "App::Plane",
    "App::Point",
})


def is_exportable(type_id: str) -> bool:
    return str(type_id or "") not in SKIP_TYPE_IDS


def select_export_names(target, objects) -> list[str]:
    """按 target 挑出要导出的名字（保持文档顺序、去重）。

    objects: 可迭代的 (name, type_id, visible)。
    target 为空/None → 全部**可见**的可导出对象；显式指定但缺失 → ValueError（列出可用名）。
    """
    entries = [(str(name), str(type_id or ""), bool(visible)) for name, type_id, visible in objects]
    visible_exportable = [
        name for name, type_id, visible in entries if is_exportable(type_id) and visible
    ]
    known = [name for name, type_id, _ in entries if is_exportable(type_id)]

    if target is None or (isinstance(target, str) and not target.strip()):
        if not visible_exportable:
            raise ValueError(
                "文档里没有可导出的实体对象（只有基准/原点，或已全部隐藏）。"
                "请先建模，或显式指定 target。"
            )
        return visible_exportable

    wanted = [target] if isinstance(target, str) else list(target)
    names: list[str] = []
    missing: list[str] = []
    for raw in wanted:
        name = str(raw or "").strip()
        if not name:
            continue
        if name not in known:
            missing.append(name)
            continue
        if name not in names:
            names.append(name)

    if missing:
        available = ", ".join(known) or "（无）"
        raise ValueError(
            f"导出目标不存在: {missing}。可用对象: {available}。"
            "省略 target 可导出整个文档。"
        )
    if not names:
        raise ValueError("导出目标为空；省略 target 可导出整个文档。")
    return names
