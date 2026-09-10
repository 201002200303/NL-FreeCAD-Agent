# 四旋翼样例（X 布局 + 云台相机）

可运行脚本：`agent_service/data/_drone_quad_x.cad.py`（粘进 CAD Playground 即可）。

这是「多件装配」的**标准写法**：不是把外部 JS 逐行翻译，而是按我们的锚点（`center=`）**按接触关系重算**。适合当后续复杂模型的参考模板。

## 建模流程（先想清楚再写）

1. **定原点**：机身底面放 `z=0`，中心在原点。所有高度都从 `body_bottom=0` 推。
2. **尺寸集中**：`arm_len / prop_r / leg_h / overlap ...` 放顶部，后面只引用变量。
3. **接触优先**：每新增一层，先写「它的顶 = 上一层的底」，再反算 `center`。不要先填 translate 再猜。
4. **清单命名**：`names` 列表先列全 → `cad.delete(names)`，保证重跑干净。
5. **分组建**：机身 → 机臂/动力组 → 起落架 → 云台。每组内先主体后细节。

## 四条易错点（无人机里踩过）

- **桨叶**：建一片叶 → `rotate` → `polar_pattern(count=2, fuse=True)`。工具 fuse 后会**删除**原件/副本，只留 `fuse_name`，不会留幽灵扇叶。
- **起落架**：腿与滑撬**同轴竖直**，不要「先平移再 rotate 去够」。
- **云台**：从上往下叠，每层用 `上一层底 - 高/2 + overlap` 推 z。
- **贴合**：允许 `overlap=1mm` 轻嵌；引用 fuse 结果名，不要再改已删除的源件名。
- **整机出口**：机身/机臂/起落架/云台等**整机装配用 `cad.compound([...], name="Drone")`**，
  不要逐个 fuse —— fuse 会删源件，且后续阶段验收会找不到中间件。fuse 只用于局部单件（如单个旋翼）。
  导出用 `cad.export_step(target="Drone", ...)`，或省略 `target` 导出整个文档。

## 为什么总出现「多余扇叶 / 叠影」

旧实现：`fuse=True` / `boolean_fuse` 只把源件 `Visibility=False`。隐藏不可靠 → 原桨叶仍显示，四臂各留 1 片 = 4 片多余。

**根治（已落地）**：fuse/cut/pattern(fuse) 后 `removeObject` 删源件，不只隐藏。脚本侧始终用返回的结果名。

## 结构参考

- 机臂：`cad.rotate(arm, axis="Z", angle=ang, center=arm_center)`，**绕自身中心**转，不绕世界原点。
- 圆柱横置：轴沿 Y 用 `rot_x=90`；轴沿 X 用 `rot_y=90`。
- 循环里重名：用 `tag` 后缀，不重跑同名会走 runtime 先删再建，也已在 `names` 里显式 delete。

## 自检（粘贴前）

- [ ] 所有将创建的名字在 `cad.delete` 里
- [ ] 每个 `rotate` 都带了自身 `center`
- [ ] 起落架腿与滑撬 x/y 对齐，z 按「底=顶」
- [ ] 云台各件 z 从 `body_bottom` 一层层推，没有拍脑袋 translate
