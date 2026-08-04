---
keywords: [gear, pinion, sprocket, 齿轮, 齿圈, 齿轮轴, 直齿, 渐开线, involute, spur gear, 模数]
---
# 标准直齿圆柱齿轮（渐开线）建模技能

> 目标：外观与尺寸符合「标准齿轮」认知（均匀轮齿 + 轮毂/腹板 + 中心孔），禁止「圆盘 + 单方块」糊弄。

## 0. 默认参数（用户未指定时采用）

| 符号 | 含义 | 默认 |
|------|------|------|
| m | 模数 (mm) | 2 |
| z | 齿数 | 20 |
| α | 压力角 | 20° |
| b | 齿宽 (mm) | 10~20（按体量，默认 15） |
| d_hub | 中心孔直径 | ≈ 0.3·d（且 < 齿根圆直径的 0.6 倍） |

关键公式（直齿）：

- 分度圆直径 `d = m·z`
- 齿顶圆直径 `da = d + 2m = m(z+2)`
- 齿根圆直径 `df = d - 2.5m = m(z-2.5)`（标准齿高制）
- 齿距角 `τ = 360°/z`
- 齿厚（分度圆弦厚近似）`s ≈ π·m/2`

**先算尺寸，再建模。** 粗计划阶段只写阶段意图；具体 m/z/b 在 next_step 落数。

## 1. 推荐阶段划分（start_plan）

1. **P1 齿圈**：完整圆周上的全部轮齿（或齿根圆盘 + 全齿阵列融合体）
2. **P2 轮体/腹板**：连接齿根与中心的实体（可与 P1 一次 fuse）
3. **P3 轴孔**：中心孔（及可选键槽）

成功标准必须可验收：

- P1：存在 ≥ z 个齿的圆周分布实体（或单一融合体，外轮廓呈齿形），**不得**只有 1 个齿
- P2：主体与齿圈相连、同轴
- P3：孔在轴心，孔直径符合默认/用户值

## 2. 标准建模工序（next_step 按此执行）

### 路线 A（首选：极坐标阵列）

当前工具集无专用渐开线生成器时，用**梯形/楔形齿**逼近标准齿形（仍须满齿数圆周阵列）。真渐开线用路线 B。

1. **齿根圆盘**  
   `create_cylinder(name=RootDisc, radius=df/2, height=b, pos=原点)`  
   轴沿 Z，盘心在原点。

2. **单齿实体（径向楔块）**  
   - 齿高 `h = 2.25m`（齿顶高 m + 齿根高 1.25m）  
   - 齿位于 +Y：齿根处嵌入圆盘 ≥ 0.5m，保证 boolean_fuse 有效重叠  
   - 齿宽方向沿圆周用较小厚度（≈ `π·m/2` 量级），高度 = b  
   - 命名 `Tooth1`  
   - **禁止**把唯一的方块当作完成品

3. **圆周阵列（强制）**  
   ```
   polar_pattern(
     target=Tooth1, count=z, angle=360, axis=Z,
     origin_x=0, origin_y=0, origin_z=0,
     name_prefix=Tooth,
     fuse=true, fuse_name=ToothRing
   )
   ```  
   - 必须一次阵列满 z 齿；**禁止**手写 10+ 次 `copy_object`+`rotate`  
   - `fuse=true` 得到 `ToothRing`，再与 `RootDisc`：`boolean_fuse → GearBlank`

4. **轮毂（可选独立阶段）**  
   若腹板半径明显小于齿根：再 `create_cylinder` 较小半径圆柱并 fuse。否则 RootDisc 已兼轮体。

5. **中心孔**  
   `create_cylinder(name=BoreTool, radius=d_hub/2, height=b+余量)`  
   `boolean_cut(base=GearBlank, tool=BoreTool, name=Gear)`  
   孔轴与齿轮轴重合（原点、Z）。

### 路线 B（渐开线齿廓，更专业）

在具备草图折线能力时使用：

1. 按渐开线参数方程采样齿廓点（压力角 α=20°），半齿对称  
2. `create_sketch` + `sketch_add_polyline` 画单齿封闭轮廓（含齿根圆过渡）  
3. `pad_sketch` / `extrude_sketch` 得 `Tooth1`（齿宽 b）  
4. 同路线 A 步骤 3：`polar_pattern` + fuse  
5. 中心孔同 A

渐开线点（齿面一侧，示意）：以基圆 `rb = (d/2)·cos(α)` 为基准，滚角 ψ 从 0 增至齿顶；点坐标  
`x = rb(cosψ + ψ·sinψ)`, `y = rb(sinψ − ψ·cosψ)`，再旋转/镜像拼成整齿。点数量建议每侧 8~16。

## 3. 硬性禁止

- ❌ 圆盘 + **单个**长方体齿就宣称完成  
- ❌ 复制失败后跳过，只保留 1 齿进入打孔  
- ❌ 扇区「5 齿×4 组」多层 fuse 连环（脆、难修）；一律 `polar_pattern`  
- ❌ 齿数 z < 12 还声称「标准齿轮」（除非用户指定少齿）  
- ❌ 中心孔直径 ≥ 齿根圆直径（几何穿透齿根）

## 4. 验收检查清单（evaluate 前自检）

1. `summarize_document` / `get_object_detail`：最终实体外接圆半径 ≈ `da/2`  
2. 俯视应看到**整圈**齿，而非光环+一牙  
3. 体积应明显大于光圆盘（多出的是轮齿体积）  
4. 中心孔后仍保持圆环状齿圈，勿切飞

## 5. 工具选择速查

| 意图 | 工具 |
|------|------|
| 齿根/轮毂/孔刀具 | `create_cylinder` |
| 简化单齿 | `create_box` 或 sketch+pad |
| 满圈轮齿 | **`polar_pattern`**（必选） |
| 合并 | `boolean_fuse` |
| 轴孔 | `boolean_cut` |
| 查尺寸 | `get_object_detail` |

## 6. 对用户说法的映射

- 「标准齿轮 / 齿轮」→ 路线 A 或 B，z=20, m=2，除非另有指定  
- 「大齿轮 / 小齿轮」→ 调 z 或 m，保持 α=20°  
- 「齿轮轴」→ 本技能齿轮 + 另附阶梯轴技能，再同轴装配
