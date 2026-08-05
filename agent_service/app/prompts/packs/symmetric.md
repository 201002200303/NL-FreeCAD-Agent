<!-- 用途: 对称规则包 -->

## 任务规则：对称
- **没有 `mirror` 工具**。关于 X=0 的左右对称：对侧再 `create_*`，相同尺寸、`pos_x`/中心 X 取负，名称 `_L`/`_R`
- 仅形体绕自身中心对称且无特殊朝向时，可用 `copy_object` + `set_placement` 翻到 `-center_x`
- 有倾斜/旋转的零件：对侧必须重新 create 并翻转相关 `rot_*`
- 圆周/线性重复用 `polar_pattern` / `linear_pattern`
