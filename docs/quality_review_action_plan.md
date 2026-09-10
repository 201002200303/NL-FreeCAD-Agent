# 质量审查与整改行动方案

> 审查日期：2026-09-10。基线 commit：`f743a12`（`dev`）+ 未提交 Phase Program WIP。
> 整改分支：`fix/review-hardening`（**不并入 dev/main**，效果确认后再合）。

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

## 行动项与状态

状态图例：`[ ]` 未开始 · `[~]` 进行中 · `[x]` 测试通过并标注完成

### F1 — 修 Phase 门闩（D2/D3）`[x]`
- 症状：空 `phase_state` 或模型自洽计划可让未执行的阶段被标 done 并 `done` 收尾。
- 改法：`reconcile_soft_plan` 始终以宿主计划为权威；`chat.py` 删除第二次自洽调用；
  `done` 收尾需宿主存在至少一个 `passed` 阶段且无未完成项。
- 验收测试：`agent_service/test_phase_program.py`（宿主权威 / 新阶段保留 pending）、
  `agent_service/test_chat_phase_program.py`（首轮不得 done）。

### F2 — 宿主锁定验收（D1）`[x]`
- 症状：模型可放宽/替换/清空 acceptance 后让阶段 PASS。
- 改法：进入当前阶段时由宿主把 `phase_id + acceptance` 冻结进 `phase_state`；
  后续同阶段只允许**追加**检查，禁止移除或放宽；空 acceptance 视为不合格不予 PASS。
- 验收测试：`test_phase_program.py`（放宽被拒 / 追加允许 / 空检查不 PASS）。

### F3 — L3/L4 几何 Oracle 骨架（D4）`[x]`
- 症状：Placement/朝向类缺陷无自动门禁。
- 改法：新建 `freecad_addon/AICADAgent/tests/geometry_oracle/`：
  用例表（tool + args + 期望 bbox/轴/体积）+ runner（FreeCADCmd 执行，产出 JSON/Markdown 报告），
  无 FreeCAD 时标记 `SKIPPED_NO_FREECAD` 而非假装通过；覆盖高风险族（box anchor、cylinder rot、rotate pivot、hole axis、pattern、sketch/extrude direction、boolean）。
- 验收测试：骨架自检可在无 FreeCAD 下跑（解析/汇总逻辑），有 FreeCADCmd 时出实测报告。

### F4 — cad 契约单一源（D8）`[x]`
- 改法：`agent_service/app/cad_program/manifest.py` 为唯一源，插件副本由脚本生成/校验；
  热加载补 `manifest`；`CAD_API_VERSION` 去掉 `-test`；TEST API 从模型可见目录移除（保留工具本身）。
- 验收测试：`test_cad_contract_manifest.py`（双端一致 + 无 TEST 残留）。

### F5 — 握手 fail-open（D9）`[x]`
- 改法：`_cad_api_compatible` 为 `None`/失败时**允许执行**；仅显式版本不一致才拦；失败自动重试。
- 验收测试：`test_cad_contract_manifest.py` + 静态断言（插件侧不可用 pytest 时用源码守卫）。

### F6 — 消除语义矛盾（D5/D6）`[x]`
- 改法：`chat_core.md` 成为唯一规则源：重复件的**允许写法**按实际能力收敛，
  布尔接触统一「允许 1mm 轻嵌」；配方文档改为引用主提示词，不再自定相反规则。
- 验收测试：`test_prompts.py`（关键规则存在且无互斥表述）。

### F7 — 错误可修复化（D7）`[x]`
- 改法：`_normalize_cad_args` 支持 `cad.fuse([a,b,c])` / `cad.cut(base, [tools])`；
  错误返回带「出错参数 + 建议改法」。
- 验收测试：`test_cad_runtime.py`（列表 fuse / 错误 hint）。

### F8 — 仓库卫生与提交（D12）`[x]`
- 改法：删根目录无关文件与临时产物；WIP 先落基线 commit；整改按 F1–F7 分步提交到 `fix/review-hardening`。
- 不并入 `dev`/`main`。

## 执行纪律

每个行动项按 **先写测试 → 改代码 → 跑测试 → 自审 → 必要时再改** 循环；
测试通过后在本文件对应标题勾选 `[x]`，并记一行 `dev_log.md`。
