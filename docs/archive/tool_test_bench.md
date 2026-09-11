# 工具整测台（TEST）

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


> **2026-09-10 起**：`cad.sweep` / `cad.wedge` **已从模型可见目录移除**（即
> `CAD_TO_TOOL` 不再包含它们，`CAD_API_TEST` 已删除）。工具本体仍在
> `TOOL_REGISTRY`（L2 冒烟覆盖）。原因：两者没有几何 Oracle 用例，暴露给模型只会换来失败回合。
>
> 想恢复 `cad.*` 路径：先在 `agent_service/app/cad_program/manifest.py` 加回映射，
> 跑 `python scripts/sync_cad_manifest.py`，并**必须先补 L3/L4 Oracle 用例**
> （`freecad_addon/AICADAgent/tests/geometry_oracle/cases.py`）。

脚本：`agent_service/data/_tool_test_bench.cad.py`（本地人工台产物，位于被 gitignore 的 `agent_service/data/`，仓库内不提供）

## 你怎么验

1. **重启 FreeCAD**（或重载 AICADAgent），吃到新 `create_wedge` / `make_sweep`
2. 用 L3 直调路径验证（`cad.*` 路径已关）：
   `D:\freecad\bin\freecadcmd.exe -c "import sys; sys.path.insert(0, r'<repo>\freecad_addon'); import runpy; runpy.run_path(r'<repo>\freecad_addon\AICADAgent\tests\test_all_tools_smoke.py', run_name='__main__')"`
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