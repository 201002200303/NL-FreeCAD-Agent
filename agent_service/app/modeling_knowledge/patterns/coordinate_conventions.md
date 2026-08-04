---
keywords: [coordinate, 坐标, sketch, 草图, placement, 朝向, axis]
---
# 坐标与朝向约定

- Z 轴向上；世界原点是默认装配参考
- create_cylinder 默认轴沿 Z；水平圆柱/车轮用 rot_x=90
- Part::Box 的 pos 是包围盒最小角 (xmin,ymin,zmin)
- 贴附优先用 align_objects(mode=stack) 或 place_relative(anchor=...)
- 草图平面：XY 默认；贴面草图用 create_sketch_on_face，先 list_topology
- 禁止凭空臆造绝对坐标；先 query 已有对象 size/center
