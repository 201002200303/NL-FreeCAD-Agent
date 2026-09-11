# 质量审查与整改行动方案

> 审查日期：2026-09-10。基线 commit：`f743a12`（`dev`）+ 未提交 Phase Program WIP。
> 整改分支：`fix/review-hardening`；F1–F9 全部完成并已并入 `main`。
> 文中引用的证据文件（`data/_*.txt`、`data/_geometry_oracle_report.*`）位于被 gitignore 的
> `agent_service/data/`，属本地诊断产物，仓库内不提供。

## 结论（一句话）

方向（Code Mode + Agent 规划 / 宿主治理）成立；效果差的根因是**质量门在验错的对象**：
宿主只验「对象存在 / Shape 有效」，而用户感知的失败是尺寸、贴合、朝向与观感；
同时**几何地基（L3/L4 工具 Oracle）缺位**，Placement/朝向类缺陷只能靠人工补丁。

## 发现清单（证据）

| # | 严重度 | 发现 | 证据 |
|---|--------|------|------|
| D1 | P0 | 阶段验收由被审查的模型自己给，宿主只锁 status | `phase_program/orchestrator.py` `prepare_phase_tool_calls` 取 `current.get("acceptance")`；`data/_latest_session_analysis.txt` 实际只有 `object_exists`/`valid_shape` |
| D2 | P0 | 门闩可绕过：空 `phase_state` 时模型 status 原样透传 | `orchestrator.reconcile_soft_plan` 早返回 `return proposed`（`if not isinstance(host_plan, dict) or not phase_state`） |
| D3 | P0 | 门闩自洽：`chat.py` 第二次 reconcile 把模型计划同时当 proposed 与 host_plan | `workflow/chat.py` `reconcile_soft_plan(parsed.soft_plan, parsed.soft_plan, …)` |
| D4 | P0 | L3/L4 几何 Oracle 未建，全量测试只断言「不崩」 | `docs/tool_validation_pipeline.md` L3/L4「待建」；`tests/test_all_tools_smoke.py` 109 PASS 仅 status |
| D5 | P1 | 提示词与配方自相矛盾（pattern vs 直算坐标） | `prompts/chat_core.md`「必须用阵列」vs `docs/cad_modeling_recipes.md`「polar_pattern 有坑，直算更稳」vs `cad_script_writer_prompt.md` 折中 |
| D6 | P1 | 布尔「贴合无间隙」规则未进主提示词，相切 fuse 静默失败 | `data/_fail_check.txt` Neck 底 z=95 = Chest 顶 z=95 → `solid_count=2` 失败；overlap 仅写在 recipes |
| D7 | P1 | 错误不可修复：`cad.fuse([a,b,c])` 报 `a string or integer is required`；`cad.move(x=…)` 曾丢参 | `data/_fail_check.txt` seq=4/5/6 |
| D8 | P1 | cad 契约双端手工镜像；`manifest` 未热加载；版本号 `1.1-test`；TEST API 在目录里 | `cad_program/*` 服务端/插件各一份；`executor.py` 只 reload validate/runtime；`manifest.py` `CAD_API_VERSION="1.1-test"` |
| D9 | P1 | 握手未完成/失败即永久阻断建模，且提示含糊 | `agent_runner.py` `if self._cad_api_compatible is not True: … 已暂停建模执行`；`_on_capabilities_failed` 置 False 不重试 |
| D10 | P2 | 记忆层四套并行，规则三处重复 | 客户端 `session_memory.py` + 服务端 `memory/pack_builder.py` + `runtime/*` + `conversation/*`；朝向规则在 `chat_core.md` / `memory/prompt.py` / `llm_provider._build_document_context` |
| D11 | P2 | 无评测集、无 CI，「效果」无法度量 | 无 `.github`；`development_mainline.md` 自列「评测集」为待办 |
| D12 | P2 | 仓库脏：主线未提交、根目录无关文件、诊断产物 | 11 commits / 57 dirty；根目录 `test.py`（LeetCode）；`prompts_test_robot*.{txt,json}` |
| D13 | P1 | 曲面 bbox 用了近似值，污染验收与对齐 | `Shape.BoundBox` 对 torus R20/r5 报 54.12（真实 50）；`document_state.py:141` 用它作验收 `bbox_size`。由 F3 Oracle 实测发现 |
| D14 | P2 | 遗留测试断言过时/覆盖缺口 | `test_v06_freecad_tools.py` 断言 `registry_count == 54`；`test_all_tools_smoke.py` 未覆盖 `create_wedge` |
| D15 | P1 | 「整机必须 fuse 成一体」的隐含假设与三处机制互斥 | 实测高达会话陷入 `fuse → 删源件 → 验收失败 → 删了重建` 死循环；`boolean_tools.remove_objects` 删源件 vs 阶段验收 `object_exists Leg_R`；`export_tools.py` 只收单个 `target`，多零件只能靠 fuse 导出；相切静默多实体迫使提示词加「轻嵌 1mm」补丁 |

## 行动项与状态

状态图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 测试通过并标注完成

### F1 — 修 Phase 门闩（D2/D3）`[x]`
- 症状：空 `phase_state` 或模型自洽计划可让未执行的阶段被标 done 并 `done` 收尾。
- 改法：`reconcile_soft_plan` 始终以宿主计划为权威（宿主阶段不可被丢弃，模型新增阶段强制 pending）；
  新增 `mark_current_phase` 只做状态回显，`chat.py` 删除第二次自洽 reconcile；
  `done` 收尾需宿主 `phase_status == passed` 且无未完成项。
- 验收测试：`agent_service/test_phase_program.py`（空 phase_state 不可越权 / 首轮接受 / 换 id 不丢宿主阶段 /
  `mark_current_phase` 映射）、`agent_service/test_chat_phase_program.py`（首轮不得 done / 全 passed 才可 done /
  换 id 重写不得丢宿主阶段）。**结果：17 passed，全量 129 passed**。

### F2 — 宿主锁定验收（D1）`[x]`
- 症状：模型可放宽/替换/清空 acceptance 后让阶段 PASS。
- 改法：进入当前阶段时宿主把 `acceptance` 冻结进 `phase_state`，之后只允许**追加**（`lock_acceptance` 取并集、
  锁定项逐字保留，因此无法放宽 tolerance 或删检查）；计划阶段必须至少有一条几何检查
  （`bbox_size`/`bbox_center`/`volume_range`/`solid_count`），否则不予 PASS（仅 `ad_hoc` 退回默认检查）；
  `chat_plan_on.md` 同步写明该硬约束与冻结语义。
- 验收测试：`test_phase_program.py`（冻结进 state / 放宽被拒 / 追加允许 / tolerance 不可放宽 /
  无 acceptance 不 PASS / 无几何检查不 PASS / ad_hoc 仍走默认检查）。**结果：24 passed，全量 136 passed**。

### F3 — L3/L4 几何 Oracle 骨架（D4）`[x]`
- 症状：Placement/朝向类缺陷无自动门禁。
- 改法：新建 `freecad_addon/AICADAgent/tests/geometry_oracle/`：
  `cases.py`（18 条用例，L3 直调 registry / L4 走 `cad.*`，期望 bbox/中心/轴/体积/solid 数，
  每条注明 FreeCAD 出处）+ `oracle.py`（纯 Python 比较逻辑与 schema 校验）+ `runner.py`
  （读真实 Shape 事实、写 `agent_service/data/_geometry_oracle_report.{json,md}`）；
  覆盖 box anchor、cylinder 默认轴与 rot_x/rot_y、cone、rotate 默认/自转 pivot、hole 轴、
  fuse、cut、polar/linear pattern、sketch+extrude 方向、torus 轴。
- 验收测试：`agent_service/test_geometry_oracle.py`（FreeCAD-free 门禁：schema、AST 沙箱、
  比较逻辑对错样本、覆盖率族齐全）；FreeCADCmd 实跑 18/18。
- **Oracle 战果**：发现并修复 D13 —— `Shape.BoundBox` 对曲面近似（torus R20/r5 报 54.12 vs 真实 50），
  而 `document_state` 用它做验收 `bbox_size` 与对齐基准。新增唯一来源 `geometry_facts.exact_bbox`
  （优先 `optimalBoundingBox()`，已验证世界坐标），替换 6 处取 bbox。
  回归：oracle 18/18、placement/pattern/cad_program_samples 全绿、pytest 146 passed。

### F4 — cad 契约单一源（D8）`[x]`
- 改法：`agent_service/app/cad_program/manifest.py` 为唯一源，新增 `scripts/sync_cad_manifest.py`
  生成/校验插件副本（`--check` 不一致即退出 1）；`executor` 热加载补 `manifest`（必须先于
  validate/runtime reload，否则模块级常量不刷新）；`CAD_API_VERSION` = `1.1`（去 `-test`）；
  删除无引用的 `CAD_API_TEST`；`wedge`/`sweep` 移出模型可见目录（工具本体与 `TOOL_SPECS` 保留），
  两份 runtime 里随之失效的 sweep/wedge 归一化分支删除。
- 验收测试：`test_cad_contract_manifest.py`（版本/插件一致、实验 API 不可见但工具保留、
  生成副本与 canonical 逐字一致、drift 能检出、executor 确实 reload manifest）。
  **结果：7 passed，全量 151 passed；FreeCAD 侧 oracle 18/18、cad_program_samples 7/7。**

### F5 — 握手 fail-open（D9）`[x]`
- 症状：探测未回/失败即把 `_cad_api_compatible` 置 False，且执行门是 `is not True`，等于永久阻断建模。
- 改法：新增无 FreeCAD/Qt 依赖的 `AICADAgent/capabilities.py::evaluate_cad_api_compatibility`
  （语义：只有两端都报了版本且不同才算不兼容）；执行门改为 `is False`（未知即放行）；
  探测失败保持 `None` 并按 3s 递增退避重试最多 5 次。
- 验收测试：`agent_service/test_agent_capabilities.py`——策略纯逻辑单测（匹配/缺字段/空白/确认不一致）
  + 源码守卫（门闩是 `is False`、失败保持未知、有重试）。**结果：6 passed，全量 157 passed**；
  已用 `git show HEAD:` 验证守卫在改动前确实会红。

### F6 — 消除语义矛盾（D5/D6）`[x]`
- 改法：`chat_core.md` 成为唯一规则源：重复件的**允许写法**按实际能力收敛，
  布尔接触统一「允许 1mm 轻嵌」；配方文档改为引用主提示词，不再自定相反规则。
- 验收测试：`test_prompts.py`（关键规则存在且无互斥表述）。

### F7 — 错误可修复化（D7）`[x]`
- 症状：`cad.fuse([a,b,c])` 报底层 `a string or integer is required`；`cad.fuse(a,b,c)` 第 3 个操作数被静默丢弃。
- 改法：布尔 API 接受 N 个操作数（位置参数或列表，兼容 `base=`/`tool=`），按顺序两两折叠，
  中间件在下次布尔时被删；单操作数/空操作数在调用前报出 `cad.<api>` + 实收参数 + 正确写法；
  handler 抛错时包装为「api + base/tool + 原因 + 建议」。
- 验收测试：`test_cad_runtime.py`（列表 fuse 折叠 / 多位置操作数不丢 / 单操作数带 hint 报错）。
  **结果：15 passed，全量 165 passed**；服务端与插件两份 runtime 除 import 前缀外逐字一致。

### F8 — 仓库卫生与测试完整性（D12/D14）`[x]`
- 改法：根目录无关文件（`test.py`、`prompts_test_robot*`）已删、`.qoder/` 入 `.gitignore`、WIP 落基线 commit `c6f8b7d`；
  v06 的 `registry_count == 54` 改为 `>= 54`（去精确计数脆性），并修 s11 复用 `BallCopy` 的撞名失败；
  冒烟补 `create_wedge` 用例，`all_registry_tools_invoked` 恢复通过；
  新增 `test_server_and_plugin_runtime_stay_in_sync` 守卫两端 runtime 漂移。
- 验收：pytest **166 passed**；FreeCADCmd 冒烟 **109/0**、v06 **14/0**、oracle **18/0**、cad_program_samples **7/0**。
- 分支 `fix/review-hardening` 已提交 F1–F8（后续 F9 与 L5 验证亦在该分支完成，最终并入 `main`）。

> 更正：D14 说 v06 的 `registry_count == 54` 已过时——实测注册表仍是 54 项，
> 真正问题是「精确计数」使新增工具即红，故改为下界断言；`create_wedge` 未覆盖属实（已补）。

### F9 — 整机装配改用 compound（D15）`[x]`
- 症状：整机装配逐个 `fuse` 时，`boolean_tools` 按设计 `remove_objects` 删源零件，后续阶段验收
  `object_exists Leg_R / Arm_R` 必然失败，模型转而「删了重建」，形成死循环；同时 fuse 要求接触面
  有实体重叠，相切/微隙会静默产成多实体，于是又被迫在提示词里加「轻嵌 1mm」补丁。
- 实测依据（FreeCADCmd 探针）：三个互不接触零件上，`fuse` 产出 **3 个实体**、体积与包围盒与
  `Part.makeCompound` **完全相同** —— 对整机装配，fuse 相对 compound **零收益**，却额外承担
  布尔风险、重叠要求与源件删除。
- 改法：
  - 新增 `cad.compound([...], name=...)` → `make_compound`（`cad_tools/compound_tools.py`）：
    不布尔、不要求重叠、**不删源件**，零件保持独立实体；`Part::Feature` 可直接作导出 target。
  - 新增 `AICADAgent/export_selection.py`（FreeCAD-free）：`export_step` / `export_stl` 现支持
    `target` 省略=整文档、单名、名字列表（多对象内部组合为 compound 导出），缺失目标报可修复提示。
    **整文档导出排除隐藏对象**：`hole`/`fillet`/`chamfer` 走 `assign_shape_result` 会把原参数件
    `Visibility=False`，若一起导出 STEP 里就有新旧两份重叠几何（叠影）；显式点名则放行。
  - `chat_core.md` 新增「装配用 compound，不要整机 fuse」节，明确 fuse 仅用于局部单件；
    `cad_script_writer_prompt.md` / `cad_modeling_recipes.md` / `code_mode.md` 同步，
    并修掉 `cad_script_writer_prompt.md` 里与 F7 冲突的「fuse/cut 是两参数，不是 list」。
  - `CAD_API_VERSION` 1.1 → **1.2**（契约新增 API）；`TOOL_SPECS`/`TOOL_CATEGORIES` 补
    `make_compound`（boolean 类，工具数 54 → 55）。
- 验收测试：`test_cad_compound.py`（列表/位置参数、变量返回、**不删源件**、同名只替换结果名）、
  `test_export_selection.py`（整文档/单名/列表/去重/跳过基准/排除隐藏/可修复报错）；
  Oracle 新增 `l4_compound_two_disjoint_boxes`（多实体、体积、bbox、valid）；
  FreeCADCmd 新增 `tests/test_export_multi.py`（含 STEP 回读确认 2 实体、整文档导出跳过基准、
  排除 `cut_hole` 隐藏的源件）。
- **结果：pytest 207 passed；oracle 19/19、冒烟 114/0、v06 14/0、export_multi 14/0、samples 7/0。**
- **L5 活体验证（同一需求对照）**：新增 `scripts/session_report.py` 度量 Code Mode 每轮
  阶段轨迹（该路径不写 session_events，note 落在 conversation_messages）。无头驱动
  （镜像 agent_runner 循环、无 Qt）跑「创建一个人形的高达模型」：

  | 指标 | 1.1 基线 | 1.2 新版 |
  |---|---|---|
  | 终态 gate | `awaiting_execution` | **`passed`** |
  | 阶段推进 | 2/5 | **6/6** |
  | `cad.compound` | False | **True** |
  | `cad.fuse` | 21 次 | **0 次** |
  | 计划含整机 fuse | True | **False** |

  模型自主写出「整机装配（compound，不整体 fuse）」阶段；独立复核 20 零件全保留、
  `ShapeType=Compound`、对称误差 0、单文件 STEP 可导出。另观察到 F2 硬约束在真实链路上
  驳回了一次缺几何检查的 acceptance（第 7 轮），模型随后补齐并重跑通过。

## 执行纪律

每个行动项按 **先写测试 → 改代码 → 跑测试 → 自审 → 必要时再改** 循环；
测试通过后在本文件对应标题勾选 `[x]`，并记一行 `dev_log.md`。
