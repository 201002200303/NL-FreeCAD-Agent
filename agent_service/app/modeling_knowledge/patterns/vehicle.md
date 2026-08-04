---
keywords: [car, vehicle, 车, 小车, 汽车, wheel, 轮子]
---
# 车辆类开放模型

## 建议顺序（角色）
1. 车身主体
2. 驾驶舱 / 车顶（可选）
3. 车轮（通常 4 个）
4. 轴 / 灯 / 附件
5. 表面处理（圆角等）

## 比例约定
- 轮径大约为车身长度的 1/4~1/3
- 轮宽明显小于直径
- 车轮接地：轮子 bbox 的 zmin ≈ 0

## 建模注意
- create_cylinder 默认轴沿 Z；水平车轮需要 rot_x=90，使轴沿 Y，size 约为 [2R, H, 2R]
- 贴合车身侧面时优先 align_objects / place_relative，不要猜绝对坐标
- 四轮对称优先 mirror / distribute_along，减少重复放置
- 放置前先 get_object_detail 拿车身 size/center
