# 工具可用性校验流水线

> 目的：流程再好，底层 `TOOL_REGISTRY` / `cad.*` 若参数、Placement、默认轴错了，建模仍会翻车。  
> 本文定义**如何编排校验**，不一次实现全部用例。权威几何语义以 FreeCAD 文档为准。

## FreeCAD 官方锚点（校验时对照）

| 主题 | 官方来源 | 我们要钉死的事实 |
|------|----------|------------------|
| Placement / 朝向 | [wiki Placement](https://wiki.freecad.org/Placement)、[Rotation API 博文](https://blog.freecad.org/2023/01/16/the-rotation-api-in-freecad/) | `Placement = Base + Rotation`；`Rotation(axis, angle_deg)`；绕点转用三参 `Placement(pos, rot, center)`，center **不持久化** |
| Box 原点 | Part::Box 原生行为 | Placement.Base = **角点** (xmin,ymin,zmin)，不是几何中心；我们的 `anchor=center` 是内部换算 |
| Cylinder / Cone | Part 基本体 | 默认轴 **局部 +Z**；底面圆心在 Base；侧轮必须显式旋转 |
| Euler | wiki / Rotation API | `Rotation(yaw,pitch,roll)` ≠ 我们 prompt 里的「绕世界轴依次 rot_x/y/z」——工具层必须写清用哪一种 |

校验用例的「期望值」应能追溯到上表，而不是「看起来差不多」。

---

## 五层流水线（由便宜到贵）

```text
L0 契约静态          无需 FreeCAD
L1 导入/签名烟雾      stub 或 import（现有 verify_tool_fixes）
L2 Registry 冒烟      FreeCADCmd：每个工具跑一次不崩
L3 几何 Oracle        FreeCADCmd：对照期望 bbox/轴/体积
L4 cad.* 编排路径     FreeCADCmd：经 runtime 映射，不直调 TOOL_REGISTRY
```

编排入口建议（后续可做成 `scripts/run_tool_validation.ps1`）：

```text
1) python scripts/verify_spec_alignment.py
2) python agent_service/test_cad_contract_manifest.py   # 或 pytest 子集
3) python scripts/verify_tool_fixes.py                  # 无 FC 的静态修复检查
4) FreeCADCmd → test_all_tools_smoke.py                 # L2
5) FreeCADCmd → tests/geometry_oracle/runner.py          # L3 + L4（已建，同一张表用 layer 区分）
→ 汇总 JSON/Markdown 报告：哪层、哪工具、期望 vs 实测
```

**已实现（2026-09-10）**：`freecad_addon/AICADAgent/tests/geometry_oracle/`

```text
cases.py    用例表（纯 Python）：L3=直调 TOOL_REGISTRY，L4=execute_cad_program
oracle.py   期望 schema + 比较逻辑（纯 Python，无 FreeCAD）
runner.py   读真实 Shape 事实、跑用例、写 agent_service/data/_geometry_oracle_report.{json,md}
```

跑法（FreeCADCmd；无它则跳过，报告标 `SKIPPED_NO_FREECAD`）：

```powershell
D:\freecad\bin\freecadcmd.exe -c "import sys; sys.path.insert(0, r'<repo>\freecad_addon\AICADAgent\tests\geometry_oracle'); import runner; raise SystemExit(runner.main())"
```

用例表现状：18 条覆盖 box anchor / cylinder 默认轴与 rot_x,rot_y / cone / rotate 默认与自转 pivot /
hole 轴 / fuse / cut / polar,linear pattern / sketch+extrude 方向 / torus 轴。全绿。

pytest 侧有 FreeCAD-free 门禁 `agent_service/test_geometry_oracle.py`：校验用例 schema、
期望值不写错、L4 程序过 AST 沙箱、比较逻辑对错样本都判对。

本机无 `FreeCADCmd` 时：L0–L1 仍必须绿；L2–L4 标记 `SKIPPED_NO_FREECAD`，不得假装通过。

---

## 各层查什么

### L0 — 契约（参数名/格式有没有对上）

| 检查 | 现有资产 |
|------|----------|
| `TOOL_SPECS` ↔ 实现函数参数名 | `scripts/verify_spec_alignment.py` |
| `cad.*` manifest ↔ runtime ↔ 插件副本 | `test_cad_contract_manifest.py` |
| `CAD_API_VERSION` 双端一致 | capabilities 握手 + manifest |
| 禁止幽灵 API（get/document/…） | 同上 |

**产出**：参数疏漏清单（spec 有实现无 / 实现有 spec 无）。

### L1 — 能加载、签名合理

| 检查 | 现有资产 |
|------|----------|
| 模块可 import、关键逻辑单元 | `scripts/verify_tool_fixes.py` |
| 服务端 runtime 单测（无 FC） | `test_cad_runtime.py` |

不证明「在 FreeCAD 里几何对」。

### L2 — 每个工具至少成功一次（不崩）

| 检查 | 现有资产 |
|------|----------|
| 全 registry 各调一次 | `freecad_addon/.../tests/test_all_tools_smoke.py` |
| 一键脚本 | `tests/run_smoke.bat` |

**缺口**：只断言 `status=success`，几乎不查 bbox/轴。适合回归「又 ImportError 了」，不适合抓朝向 bug。

### L3 — 几何 Oracle（参数/方向有没有疏漏）★ 主战场

对**高风险工具**建用例表（YAML/Python 均可），每条：

```text
tool + args
→ 在干净 Document 执行
→ recompute
→ 读 Shape.BoundBox / Placement / Volume / Solids
→ 与 expected 比（容差写死）
```

**优先覆盖（按翻车频率）**

| 族 | 必须钉的期望 |
|----|----------------|
| `create_box` | `anchor=min`：Base=角点；`anchor=center`：bbox.center≈给定 center；size=(L,W,H)→X/Y/Z |
| `create_cylinder` / cone / torus | 无 rot：轴 +Z，高度沿 Z；`rot_y=90`：轴沿 +X（侧轮）；`rot_x=90`：轴沿 +Y |
| `rotate` | 默认 pivot=世界原点 vs `center=` 物体中心——各一条；角度单位=度 |
| `move` / `set_placement` | 只改位置不偷改旋转；center vs corner 语义 |
| `cut_hole` | `axis=Z/X/Y` 后孔方向与 bbox 最薄维一致 |
| `polar_pattern` / `linear_pattern` | count、轴、中心；fuse 后体积/件数 |
| `sketch` + `extrude` | plane=XY/XZ/YZ + direction 默认 +Z；XZ 草图必须显式 direction |
| boolean cut/fuse | 体积增减方向正确；无效 Shape 必失败 |

**期望值怎么定**

1. 手算或对照 wiki（Placement / 默认轴）。  
2. 或「黄金运行」：确认 GUI 正确后，把实测 bbox/轴写入 fixture（注明 FreeCAD 版本）。  
3. 禁止用 LLM 生成期望值当真理。

**探针雏形**：`_probe_rotate.py` / `_probe_placement.py` —— 应升级为可断言、可汇总的 Oracle，而不是手工看 print。

**首个 Oracle 战果（2026-09-10）**：`Shape.BoundBox` 对曲面是近似值——torus R20/r5 报 54.12（真实 50，+8.2%），
而 `document_state` 把它当作验收 `bbox_size` 与对齐基准。已引入唯一来源
`AICADAgent/geometry_facts.py::exact_bbox`（优先 `optimalBoundingBox()`，世界坐标且紧致），
替换 `document_state` / `query_tools` / `placement_tools` / `transform_tools` / `_helpers` 中的取 bbox 处。
回归：oracle 18/18、placement/pattern/cad_program_samples 全绿。

### L4 — 走 `cad.*` 路径（防映射层偷换参数）

同一几何期望，改走：

```text
execute_cad_program / run_cad_program(code)
  → _CAD_TO_TOOL + _normalize_cad_args
  → TOOL_REGISTRY
```

专门抓：`center=` 丢失、`rot_*` 未映射、`extrude.center` 误传、同名删除再建等。  
服务端 `test_cad_runtime` 测映射逻辑；**真实 Shape** 仍要 FreeCADCmd。

---

## 报告格式（建议）

每条用例一行：

```json
{
  "layer": "L3",
  "tool": "create_cylinder",
  "case": "side_wheel_rot_y_90",
  "status": "pass|fail|skip",
  "expected": {"axis": "+X", "size_thin": 8},
  "actual": {"axis_hint": "+Z", "bbox_size": [40,40,8]},
  "ref": "https://wiki.freecad.org/Placement"
}
```

CI：有 FreeCADCmd 跑 L0–L4；无则 L0–L1 必过 + L2–L4 skip。

---

## CAD Playground（人工当 LLM）

FreeCAD Workbench **AI CAD Agent** → **CAD Playground**：粘贴 `cad.*` → 同通道 `execute_cad_program` → 3D 查看。  
实现：`freecad_addon/AICADAgent/playground.py`。  
外部 LLM 写脚本提示词：`docs/cad_script_writer_prompt.md`。

## 实施顺序（务实）

1. 用 Playground 手测高风险 `cad.*`。  
2. **固化编排脚本**：串 L0→L1→（可选）L2。  
3. 把反复踩坑的场景收成 L3/L4 断言。  
4. 其余工具维持 L2 冒烟。

---

## 和现有文档的关系

| 文档 | 关系 |
|------|------|
| `tool_addition_standard.md` | 新增工具流程；本文补「怎么证明能用」 |
| `tool_design.md` | 分层思想；偏设计 |
| `development_mainline.md` | 产品主线是阶段程序；**工具 Oracle 是地基质量门** |
| Phase Acceptance | 验收运行时模型产出；**本文验收工具实现本身** |

---

## 已知债务（门闩，非本流水线）

阶段宿主门闩仍有空子（空 `phase_state` 可标 done、acceptance 可被模型改松等）——见 `docs/tech_debt.md`。与工具几何正确性正交，不阻塞本流水线落地。
