# CAD Tool Design — 分层设计

> 更新说明 (2026-07-31)：本文 Layer 1「高层语义工具」（make_base_plate 等）已被
> recipe/pattern 机制取代，当前 46 个工具全部为 Layer 2-4。高层组合逻辑见
> `agent_service/app/recipes/` 与 `docs/development_plan.md`（CAD coding agent 方向）。
> 其余分层、定义规范、执行约定仍然有效。

## 设计原则

1. **单一职责**：每个 Tool 只做一件事
2. **参数校验**：Tool 内部校验参数合法性
3. **错误安全**：失败不破坏现有模型
4. **可组合**：Tool 之间通过对象名称耦合

## 分层架构

### Layer 1: 高层语义工具

封装常用建模模式，减少 Plan 中的步骤数。

```
make_base_plate(name, length, width, height)
  → create_box + add fillet (internally)

add_mounting_holes(target, count, pattern, diameter)
  → cut holes in specified pattern

add_stiffener(target, position, thickness)
  → sketch + pad at position
```

这些工具内部调用 Layer 2 的 primitive 工具。

### Layer 2: CAD Primitive 工具

直接映射 FreeCAD 基本操作。

```
Primitive:
  create_box(name, length, width, height)
  create_cylinder(name, radius, height)
  create_sphere(name, radius)
  create_cone(name, radius1, radius2, height)

Sketcher:
  create_sketch(name, plane)
  draw_rectangle(sketch, x, y, w, h)
  draw_circle(sketch, x, y, radius)
  sketch_add_arc(sketch, mode, ...)          # Part.ArcOfCircle
  sketch_add_polyline(sketch, points, closed)
  sketch_add_bspline(sketch, points, mode)   # interpolate | poles
  add_constraint(sketch, constraint_type, ...)

PartDesign:
  pad_sketch(name, sketch, length)
  pocket_sketch(name, sketch, length)
  revolve_sketch(name, sketch, angle)

Boolean:
  union(targets)
  cut(base, tool)
  intersect(a, b)
```

### Layer 3: 修改工具

修改已有对象的属性或特征。

```
add_fillet(target, radius, edges)
add_chamfer(target, size, edges)
modify_param(target, param, value)
delete_object(target)
rename_object(target, new_name)
```

### Layer 4: 导出工具

文件和格式导出。

```
export_step(target, filepath)
export_stl(target, filepath, tolerance)
export_obj(target, filepath)
save_fcstd(filepath)
```

## Tool 定义规范

每个 Tool 在 `agent_service/app/tools/tool_specs.py` 中定义：

```python
{
    "tool_name": {
        "description": "...",
        "parameters": {
            "param_name": {
                "type": "string|float|int|bool",
                "description": "...",
                "default": <default_value>  # optional
            }
        },
        "required": ["param1", "param2"],
    }
}
```

## 执行约定

### 事务管理

每个步骤在执行前打开事务，成功后提交，失败后回滚：

```python
doc.openTransaction(f"{step_id}: {tool}")
try:
    result = tool_method(**args)
    doc.commitTransaction()
    doc.recompute()
except Exception:
    doc.abortTransaction()
    raise
```

### 对象命名

- `name` 参数指定 FreeCAD 内部对象名
- 如果重名，FreeCAD 会自动追加数字后缀（如 `BaseBlock001`）
- Executor 返回实际创建的对象名

### 依赖解析

- Executor 检查 `depends_on` 列表
- 跳过依赖未满足的步骤
- 失败步骤导致后续依赖步骤跳过

## MVP 工具清单

| Tool | 状态 | 说明 |
|------|------|------|
| create_box | 已实现 | 创建 Part::Box |
| create_cylinder | 已实现 | 创建 Part::Cylinder |
| create_sketch | Stub | 创建 Sketcher::SketchObject |
| pad_sketch | Stub | PartDesign::Pad |
| cut_center_hole | Stub | 中心通孔 |
| cut_corner_holes | Stub | 四角通孔 |
| add_fillet | Stub | 倒圆角 |
| add_chamfer | Stub | 倒角 |
| modify_param | 已实现 | 修改对象参数 |
| delete_object | 已实现 | 删除对象 |
| export_step | Stub | 导出 STEP |
| export_stl | Stub | 导出 STL |
| save_fcstd | 已实现 | 保存文档 |
