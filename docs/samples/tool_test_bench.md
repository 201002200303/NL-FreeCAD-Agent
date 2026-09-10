# 工具整测台（TEST）

脚本：`agent_service/data/_tool_test_bench.cad.py`  
新入库（`CAD_API_TEST`）：**`cad.sweep`**、**`cad.wedge`**

## 你怎么验

1. **重启 FreeCAD**（或重载 AICADAgent），吃到新 `create_wedge` / `make_sweep`
2. CAD Playground 粘贴 `_tool_test_bench.cad.py` → 运行
3. 对照下面打分，把反馈模板填回给我

## 模型应该长什么样（iso / 侧视）

整体：**马克杯坐在向上收窄的方锥台底座上，右侧有 C 形圆管把手**。

| 部件 | 期望视觉 |
|------|----------|
| **杯身 Cup** | 空心杯，高约 90mm（坐上垫片后整体约 z=22…112）；下口≈Ø64、上口≈Ø76；俯视同心圆环 |
| **把手 Handle** | 在杯子 **+X 一侧**（右侧）的 C 形弯管，截面≈Ø10；从杯壁中部伸出再弯回；**不应**穿到杯子中心或漂到原点 |
| **底座 Assembled** | 方锥台（底大顶小）+ 顶上扁圆柱垫片；高约到 z=22；杯子底面压在垫片上 |
| **相对关系** | 三件对齐中轴；草图用完即删，3D 里不应有黑线圈叠影 |

FreeCADCmd 冒烟（供对照）：`Cup` 体积≈9e4、`Handle` 完整 C（bbox 覆盖上/下接点，非 L）、`Assembled` 在 z≈0…22。

## 新工具参数

### `cad.wedge` [TEST] → `create_wedge`

```text
name
size=(L,W,H) 或 length/width/height   # → X/Y/Z
center=(x,y,z)                         # 几何中心
tip_scale ∈ (0,1]                      # 远端/近端
taper_axis = "X"|"Y"|"Z"               # 沿哪轴收窄
```

### `cad.sweep` [TEST] → `make_sweep`

```text
name
profile = 草图名      # 建议闭合圆
path = 草图名         # Wire / 折线
solid=True
frenet=False|True
```

圆形截面：路径插值成单根 BSpline 再 `makeTube`（避免折线多段 fuse 丢成 L）。

## 反馈模板

```text
整体: Pass / Fail
杯身 loft+cut: 
把手 sweep: 
底座 wedge: 
相对位置/穿模:
其它:
```
