# Development Plan — NL-FreeCAD-Agent

## Version Roadmap

### V0.1 — Project Bootstrap ✓

**目标**：项目初始化，骨架搭建，验证通信链路。

**内容**：
- [x] 项目目录结构
- [x] README.md 和文档
- [x] FastAPI 服务骨架 (`GET /health`, `POST /agent/plan`)
- [x] Pydantic schema 定义 (request, response, plan, tools, state)
- [x] 规则/stub plan 生成器 (关键词匹配)
- [x] FreeCAD Workbench 注册
- [x] FreeCAD 面板骨架 (PySide QDockWidget)
- [x] document_state.py 文档状态读取
- [x] executor.py 骨架 + 事务管理
- [x] .gitignore
- [x] 示例文件

---

### V0.2 — Rule-based Plan Display ✓

**目标**：完善规则引擎，FreeCAD 面板显示完整的 Plan JSON。

**内容**：
- [x] 扩展 planner.py 规则覆盖更多场景
- [x] 面板展示 Plan 步骤概要
- [x] 面板展示 missing_params 提问
- [x] 面板日志格式化输出

---

### V0.3 — Basic Execution ✓

**目标**：FreeCAD 插件能够执行 create_box 和 create_cylinder，executor 与 cad_tools 解耦。

**内容**：
- [x] cad_tools/ 模块拆分 (primitive_tools, modify_tools, export_tools)
- [x] TOOL_REGISTRY 注册表机制
- [x] executor.py 精简为纯调度+事务管理
- [x] 面板添加 "执行 Plan" 按钮
- [x] 端到端验证：输入 → plan → 执行 → FreeCAD 出现模型

---

### V0.4 — LLM Structured Output ✓

**目标**：接入 LLM，用 system prompt + user_input + tool_specs 生成建模 Plan，验证 LLM 输出能驱动建模。

**内容**：
- [x] 接入 OpenAI-compatible API (chat completions)
- [x] 构建 system prompt：角色 + 可用工具 + 输出格式 + 规则
- [x] 实现 LLM structured output (JSON mode)
- [x] 将已实现的 tool_specs 注入 prompt
- [x] LLM planner 替代规则 planner（规则保留为 fallback）
- [x] 验证：LLM 生成的 plan 能在 FreeCAD 中执行建模

---

### V0.5 — LangGraph Pipeline ✓

**目标**：搭好 LangGraph 链路，让 plan 生成经过 校验→重试 的完整 pipeline，替代直接调用。

**内容**：
- [x] 增强 AgentState：添加 retry_count、validation_errors 字段
- [x] parse_input_node：输入校验、文档状态摘要注入
- [x] plan_node：LLM 生成 + 支持重试时携带错误上下文
- [x] validate_plan_node：工具名校验、必填参数校验、参数类型校验、依赖校验
- [x] cad_graph.py 条件边：校验通过 → END，校验失败 → 重试（最多 2 次）
- [x] main.py 路由接入 graph agent，替代直接调用 generate_plan()
- [x] llm_provider 支持 document_state 和错误反馈上下文

---

### V0.6 — 工具大扩充 + 树状分类检索 ✓

**目标**：将工具从 6 个扩充到 22 个，建立树状分类检索机制，让 LLM 有足够武器处理复杂建模。

**FreeCAD 侧**（`freecad_addon/AICADAgent/cad_tools/`）：
- [x] `primitive_tools.py` — 新增 create_sphere, create_cone, create_torus
- [x] `boolean_tools.py` — 新建，TopoShape.fuse/cut/common
- [x] `feature_tools.py` — 实现 add_fillet, add_chamfer, cut_hole, mirror
- [x] `transform_tools.py` — 新建，实现 move, rotate, scale, copy_object
- [x] `export_tools.py` — 新增 export_step, export_stl
- [x] `__init__.py` — 注册 22 个工具

**服务端**（`agent_service/app/`）：
- [x] `tools/tool_specs.py` — 22 个工具 spec
- [x] `tools/tool_registry.py` — 树状分类 + 按类别检索
- [x] `llm_provider.py` — 支持 tool_categories 子集注入
- [x] `test_tool_registry.py` — registry/检索/校验测试通过
- [x] `tests/test_v06_freecad_tools.py` — FreeCAD 功能测试脚本（需在 FreeCAD 内运行）

---

### V0.7 — 闭环建模 Agent（当前）

**目标**：从"一次性脚本生成器"升级为"Observe-Plan-Act-Evaluate 闭环控制 Agent"。

**核心理念**：FreeCAD 驱动的闭环建模 Agent —— FreeCAD 负责 observe + act，Agent 负责 plan + decide。

**架构**：
```
FreeCAD 插件                          Agent Service
┌──────────────────────┐              ┌──────────────────────┐
│ panel.py             │              │ main.py              │
│ agent_runner.py      │──HTTP──────→ │ start_plan_graph     │
│ document_state.py    │              │ next_step_graph      │
│ executor.py          │              │ evaluate_graph       │
│ cad_tools/           │              │ planner.py           │
└──────────────────────┘              └──────────────────────┘
```

**三个 API 端点**：
- `POST /agent/start_plan` — 生成高层 phase plan（不绑定具体工具参数）
- `POST /agent/next_step` — 根据当前状态 + history 生成下一步 tool call
- `POST /agent/evaluate_step` — 接收执行前后状态，做确定性校验 + 决策

**关键决策**：
- 保留旧 `/agent/plan` 不动，panel.py 完全切换新 API
- LangGraph 扩展为多个独立 graph，共享扩展后的 AgentState
- Session 存 FreeCAD 端，每次请求发摘要给 Agent
- 确定性校验放 Agent Service 端
- 单步失败最多重试 2 次，都失败则跳过继续
- QThread 处理 HTTP，signal 回主线程做 FreeCAD 操作

**实现步骤**：

#### Step 1: 增强文档状态
- [x] `freecad_addon/AICADAgent/document_state.py` — 增加 bbox / topology / visible / placement / dependencies（完整依赖链）提取；只对有 Shape 的对象提取几何信息
- [x] `agent_service/app/schemas/cad_state.py` — 新增 BoundingBox / TopologySummary / PlacementSummary / DependencyInfo 模型；CADObject 增加 visible / bbox / topology / placement / dependencies 字段

#### Step 2: executor 改为单步执行器
- [x] `freecad_addon/AICADAgent/executor.py` — 新增 `execute_tool_call(tool_call) -> dict`；统一返回结构（call_id / status / tool / args / resolved_args / produced_objects / source_objects / name_map_update / message）；保留 `execute_plan()` 兼容旧路径

#### Step 3: 新增 agent_runner.py
- [x] `freecad_addon/AICADAgent/agent_runner.py` — QThread 闭环控制器：管理 session（user_input / phases / history / name_map）、HTTP 通信（子线程）、signal 回主线程执行 FreeCAD 操作、自动/单步执行模式、暂停/停止

#### Step 4: Agent Service — start_plan
- [x] `agent_service/app/schemas/session.py` — SessionSummary / Phase / HighLevelPlan 模型
- [x] `agent_service/app/graph/nodes.py` — 新增 generate_high_level_plan_node / validate_high_level_plan_node
- [x] `agent_service/app/graph/cad_graph.py` — 新增 `build_start_plan_graph()`
- [x] `agent_service/app/llm/planner.py` — 新增 `generate_high_level_plan()`
- [x] `agent_service/app/llm/llm_provider.py` — 新增高层规划 prompt
- [x] `agent_service/app/main.py` — 新增 `POST /agent/start_plan`

#### Step 5: Agent Service — next_step
- [x] `agent_service/app/graph/nodes.py` — 新增 plan_next_step_node / validate_next_step_node
- [x] `agent_service/app/graph/cad_graph.py` — 新增 `build_next_step_graph()`
- [x] `agent_service/app/llm/planner.py` — 新增 `generate_next_tool_calls()`
- [x] `agent_service/app/llm/llm_provider.py` — 新增单步规划 prompt
- [x] `agent_service/app/main.py` — 新增 `POST /agent/next_step`

#### Step 6: Agent Service — evaluate_step + 确定性校验
- [x] `agent_service/app/graph/nodes.py` — 新增 evaluate_step_node（集成确定性校验 + LLM 评估）
- [x] `agent_service/app/graph/cad_graph.py` — 新增 `build_evaluate_graph()`
- [x] `agent_service/app/evaluation/rules.py` — 确定性校验规则（对象存在性 / 类型匹配 / topology / visibility）
- [x] `agent_service/app/llm/planner.py` — 新增 `evaluate_step_result()`
- [x] `agent_service/app/main.py` — 新增 `POST /agent/evaluate_step`

#### Step 7: panel.py 切换新 API
- [x] `freecad_addon/AICADAgent/panel.py` — 按钮改为"生成高层计划 / 单步执行 / 自动执行 / 暂停 / 停止"；日志改为执行轨迹格式；调用 agent_runner 而非直接 HTTP

#### Step 8: planner.py + llm_provider.py 扩展
- [x] `agent_service/app/llm/planner.py` — 三个独立函数：generate_high_level_plan / generate_next_tool_calls / evaluate_step_result
- [x] `agent_service/app/llm/llm_provider.py` — 三种 prompt 模式：高层规划 / 单步规划 / 评估判断

**验证**：
- [ ] 台灯建模端到端测试：输入 → 高层计划 → 逐步执行 → 闭环完成
- [ ] 单步失败修复测试：故意给错误参数，验证 Agent 生成替代方案
- [ ] 旧 API `/agent/plan` 仍可正常工作

---
### V0.7.x — Stabilization / 可观测性稳定

**目标**：不急着继续增加“智能”，而是让当前 V0.7 闭环系统变得可观察、可测试、可复盘、可回归。

**核心理念**：当前系统已经从“一次性脚本生成器”升级为 Observe-Plan-Act-Evaluate 闭环 Agent。下一步不是立刻进入完整 V0.8，而是先确保每一次建模过程都能被看懂、复盘和测试。

**内容**：

#### Step 1: Debug Trace 完整化

* [ ] `debug/trace_logger.py` — 完整记录 `start_plan / next_step / execution_result / evaluate_step`
* [ ] 每条 trace 必须包含 `session_id / phase_id / call_id / step_index / timestamp`
* [ ] 记录 `before_state / after_state / diff / execution_result / evaluation_result`
* [ ] 避免只记录 LLM response，必须记录真实 FreeCAD 执行结果
* [ ] 面板中显示当前 `session_id`，方便定位 debug session

#### Step 2: API Contract Examples

* [ ] `docs/api_contract_v07.md` — 记录 `/agent/start_plan`
* [ ] `docs/api_contract_v07.md` — 记录 `/agent/next_step`
* [ ] `docs/api_contract_v07.md` — 记录 `/agent/evaluate_step`
* [ ] `docs/api_contract_v07.md` — 记录 `/agent/log_execution`
* [ ] 每个 API 提供完整 request / response JSON 样例
* [ ] 每个 schema 提供最小合法样例和典型错误样例

#### Step 3: Evaluation Rules 测试化

* [ ] 为 `evaluation/rules.py` 建立 before/after state fixtures
* [ ] 测试 object_exists / shape_valid / source_hidden / bbox_close / volume_changed
* [ ] 每条规则必须输出明确 `error_code`
* [ ] `evaluate_step` 不允许只因为 LLM 判断成功就成功
* [ ] 几何事实优先由 deterministic rules 判断

#### Step 4: Golden Cases

* [ ] `golden_cases/box_with_fillet/`
* [ ] `golden_cases/lamp_model/`
* [ ] `golden_cases/base_with_holes/`
* [ ] 每个 golden case 保存 user_input、plan、trace、最终 document_state、截图或手动验收说明
* [ ] 每次大改后至少跑一个 golden case

**明确不做**：

* [ ] 不做完整 HTN
* [ ] 不做 WebSocket
* [ ] 不做 Agent 主动请求 FreeCAD
* [ ] 不做复杂 phase rollback
* [ ] 不做多 Agent 协作
* [ ] 不做大规模 prompt 重构

**验证**：

* [ ] 跑一次台灯建模，debug session 中能完整复盘所有请求、响应、执行结果和评估结果
* [ ] `replay_trace.py` 能校验已有 trace 的 schema 和执行链路
* [ ] evaluation rules 单元测试通过
* [ ] 旧 `/agent/plan` 仍可正常工作

---

### V0.8 — CAD Harness Core

**目标**：在 V0.7 闭环基础上，引入 CAD Harness Workflow，让 Agent 在可控轨道中建模，而不是自由生成复杂计划。

**核心理念**：

```
Spec → Inspect → Recipe → Step → Verify → Repair
```

也就是：

1. 用户自然语言先转成 CAD Spec；
2. 扫描真实 FreeCAD 文档状态；
3. 生成 Model Impact Map；
4. 选择建模 Recipe；
5. Recipe 展开为 Abstract Step 队列；
6. 每次只滚动生成当前 Abstract Step 的 1–3 个 tool calls；
7. FreeCAD 执行后重新 observe；
8. 用 Geometry Validators 验证；
9. 失败时局部 repair；
10. 只有局部修复失败后才考虑 replan。

**架构原则**：

* FreeCAD 仍然负责 observe + act；
* Agent Service 负责 spec / inspect / recipe selection / next_step / evaluate；
* Recipe 不是完整 tool script；
* Abstract Step 不是 sub_plan；
* tool calls 仍然在执行时根据当前 `document_state` 滚动生成；
* deterministic validators 优先于 LLM 语义判断；
* 所有关键过程必须写入 trace。

**新增模块建议**：

```
agent_service/app/
├── cad_spec/
│   ├── schemas.py
│   └── generator.py
├── inspection/
│   ├── impact_map.py
│   └── risk_analysis.py
├── recipes/
│   ├── registry.py
│   ├── primitive_recipes.py
│   ├── boolean_recipes.py
│   └── feature_recipes.py
├── abstract_steps/
│   ├── schemas.py
│   └── planner.py
├── evaluation/
│   ├── rules.py
│   ├── validators.py
│   └── postconditions.py
└── debug/
    ├── trace_logger.py
    └── replay_trace.py
```

**新增或扩展 API**：

* [ ] `POST /agent/spec` — 自然语言 → CAD Spec
* [ ] `POST /agent/impact_map` — CAD Spec + document_state → Model Impact Map
* [ ] `POST /agent/select_recipe` — 根据 CAD Spec 和当前状态选择 Recipe
* [ ] `POST /agent/next_step` — 保留并扩展，增加 current_recipe / current_abstract_step
* [ ] `POST /agent/evaluate_step` — 保留并扩展，增加 validator results / postcondition results

**验证**：

* [ ] 用户输入不会直接变成完整 tool plan
* [ ] 所有复杂建模必须先经过 CAD Spec 和 Recipe selection
* [ ] 每个 tool_call 都能追溯到 recipe 和 abstract_step
* [ ] trace 中能看到 Spec → Impact Map → Recipe → Step → Verify 的完整链路

---

### V0.8.1 — CAD Spec

**目标**：将用户自然语言需求转成结构化 CAD 需求，先解决“要做什么”，再考虑“怎么做”。

**内容**：

* [ ] 新增 `CADSpec` schema
* [ ] 字段包括 `model_type / unit / coordinate_system / features / dimensions / unknowns / assumptions`
* [ ] 用户缺少尺寸时使用默认工程尺寸，并写入 `assumptions`
* [ ] CAD Spec 可被 UI 展示和人工确认
* [ ] CAD Spec 不包含 tool calls
* [ ] CAD Spec 不绑定 FreeCAD 对象名

**示例结构**：

```json
{
  "model_type": "shaft",
  "unit": "mm",
  "coordinate_system": "X_axis",
  "features": [
    {
      "type": "stepped_shaft",
      "segments": [
        {"length": 40, "diameter": 20},
        {"length": 60, "diameter": 35},
        {"length": 40, "diameter": 20}
      ]
    },
    {
      "type": "keyway",
      "position": "middle_segment",
      "width": 8,
      "depth": 3
    }
  ],
  "unknowns": [],
  "assumptions": [
    "未指定单位时默认使用 mm"
  ]
}
```

**验证**：

* [ ] CAD Spec schema 测试通过
* [ ] 固定输入能生成稳定结构
* [ ] 缺尺寸场景能明确写入 assumptions
* [ ] 不允许在 CAD Spec 阶段生成 tool calls

---

### V0.8.2 — Model Impact Map

**目标**：在执行前明确本次建模会影响哪些对象，降低选错目标对象、误删对象、错误布尔操作的风险。

**内容**：

* [ ] 根据 `document_state` 识别 `target_objects`
* [ ] 标注 `affected_geometry`
* [ ] 标注 `helper_objects`
* [ ] 标注 `expected_changes`
* [ ] 标注 `risk_points`
* [ ] 高风险操作必须经过 Impact Map
* [ ] UI 中展示 Impact Map，用户可确认或取消

**高风险操作包括**：

* [ ] boolean_cut
* [ ] fillet / chamfer
* [ ] delete / hide
* [ ] transform existing object
* [ ] modify source object
* [ ] operation requiring face / edge selection

**验证**：

* [ ] 对已有对象加孔时，Impact Map 能正确识别 target object
* [ ] 对空文档新建模型时，Impact Map 能说明会新建哪些对象
* [ ] target object 不明确时，不进入执行阶段
* [ ] trace 中记录 Impact Map

---

### V0.8.3 — Recipe Registry

**目标**：沉淀常见 CAD 建模模式，减少 LLM 自由发挥，让 Agent 在有限、可测试的建模轨道中工作。

**第一批 Recipe**：

* [ ] `primitive_box_recipe`
* [ ] `primitive_cylinder_recipe`
* [ ] `box_with_fillet_recipe`
* [ ] `cylinder_base_recipe`
* [ ] `hole_cut_recipe`
* [ ] `boolean_cut_recipe`

**Recipe 结构**：

* [ ] `recipe_id`
* [ ] `applicable_model_types`
* [ ] `required_inputs`
* [ ] `abstract_steps`
* [ ] `postconditions`
* [ ] `risk_points`
* [ ] `validators`

**明确限制**：

* [ ] Recipe 不包含完整 tool sequence
* [ ] Recipe 不提前绑定真实对象名
* [ ] Recipe 不直接执行 FreeCAD 操作
* [ ] Recipe 只描述建模模式、抽象步骤和验证标准

**验证**：

* [ ] 每个 Recipe 有 schema 测试
* [ ] 每个 Recipe 能展开为 Abstract Step 队列
* [ ] LLM 只能从 registry 中选择 recipe，不能凭空发明 recipe
* [ ] 不匹配任何 recipe 时进入 ask_user 或 fallback，而不是自由规划

---

### V0.8.4 — Abstract Step Queue

**目标**：在 phase 和 tool_call 之间增加轻量中间层，避免纯 `next_step` 漂移，也避免完整 `sub_plan` 盲执行。

**Abstract Step schema**：

* [ ] `step_id`
* [ ] `step_type`
* [ ] `intent`
* [ ] `input_refs`
* [ ] `expected_outputs`
* [ ] `postconditions`
* [ ] `allowed_tool_categories`
* [ ] `max_retry`
* [ ] `risk_level`

**关键规则**：

* [ ] Abstract Step 不能直接包含完整 tool_calls 列表
* [ ] 每次 `next_step` 只能针对当前 Abstract Step 生成 1–3 个 tool calls
* [ ] 每个 Abstract Step 完成后必须通过 validators
* [ ] 失败后优先 repair 当前 Abstract Step
* [ ] 不默认回退整个 phase
* [ ] 不默认重建整个 model

**验证**：

* [ ] 一个 Recipe 能展开为 2–5 个 Abstract Steps
* [ ] 当前 Abstract Step 未完成时，不推进到下一步
* [ ] Abstract Step 完成必须有 validator result
* [ ] trace 能显示当前 recipe、当前 abstract_step 和对应 tool_call

---

### V0.8.5 — Geometry Validators

**目标**：用确定性几何规则替代 LLM 判断基础正确性，防止 Agent “说成功但模型明显不对”。

**第一批 validators**：

* [ ] `verify_object_exists`
* [ ] `verify_shape_valid`
* [ ] `verify_solid_count`
* [ ] `verify_bbox_close`
* [ ] `verify_bbox_center_close`
* [ ] `verify_volume_increased`
* [ ] `verify_volume_decreased`
* [ ] `verify_source_hidden`
* [ ] `verify_no_unexpected_visible_objects`
* [ ] `verify_dependency_created`

**原则**：

* [ ] 对象是否存在由规则判断
* [ ] Shape 是否 valid 由规则判断
* [ ] bbox 是否接近由规则判断
* [ ] 体积变化由规则判断
* [ ] 源对象是否隐藏由规则判断
* [ ] LLM 只辅助语义判断，例如“是否像台灯”
* [ ] validator 失败必须返回明确 `error_code`
* [ ] validator 失败不能被 LLM 直接覆盖

**验证**：

* [ ] 每个 validator 有 before/after state fixture
* [ ] 每个 validator 有成功和失败测试
* [ ] `evaluate_step` 输出 validator results
* [ ] golden cases 中至少使用 5 个 validators

---

### V0.8.6 — Trace Replay / Golden Cases

**目标**：让每一次建模过程可复盘、可回归，避免项目变成黑盒。

**内容**：

* [ ] 新增 `debug/replay_trace.py`
* [ ] replay 第一版不真实执行 FreeCAD，只校验 trace 的 schema 和流程一致性
* [ ] 校验每个 request / response 是否合法
* [ ] 校验每个 tool_call 是否有 `call_id`
* [ ] 校验每次 decision 是否属于合法枚举
* [ ] 校验 phase / abstract_step 推进是否合法
* [ ] 校验 validators 是否被执行
* [ ] 校验失败时是否进入 repair / ask_user / skip_with_warning

**Golden Cases**：

* [ ] `box_with_fillet`
* [ ] `lamp_model`
* [ ] `base_with_holes`

每个 Golden Case 保存：

* [ ] user_input
* [ ] CAD Spec
* [ ] Model Impact Map
* [ ] selected Recipe
* [ ] Abstract Step queue
* [ ] trace
* [ ] final document_state
* [ ] 手工截图或人工验收说明

**验证**：

* [ ] replay_trace 能跑通至少一个完整 debug session
* [ ] 每次大改后至少跑一个 golden case
* [ ] 失败 case 也要保存，作为回归样例

---

### V0.9 — Controlled Repair

**目标**：加入可控的局部修复能力，而不是直接做复杂全局回滚。

**内容**：

* [ ] 当前 tool_call 失败后最多 retry 2 次
* [ ] 当前 Abstract Step 失败后允许 repair
* [ ] `repair_tool_calls` 必须有 `call_id`
* [ ] repair 后必须重新 observe + evaluate
* [ ] 连续失败后进入 `ask_user` 或 `skip_with_warning`
* [ ] repair 过程必须写入 trace
* [ ] 不允许 repair 阶段直接整体重规划

**明确不做**：

* [ ] 不做默认 phase rollback
* [ ] 不做默认 global rollback
* [ ] 不做自动删除大量对象恢复状态
* [ ] 不做无限重试

**验证**：

* [ ] 故意让 fillet 目标不存在，系统能进入 repair
* [ ] 故意让 boolean_cut 失败，系统能记录失败原因
* [ ] repair 失败两次后系统能停止或询问用户
* [ ] 不出现 HTTP 500 直接中断闭环

---

### V0.10 — Human Review + Refinement

**目标**：加入人工可控的 refine，而不是让 Agent 无限自动修改模型。

**内容**：

* [ ] `POST /agent/refine_spec`
* [ ] `POST /agent/refine_recipe`
* [ ] `POST /agent/refine_step`
* [ ] UI 支持展示和编辑 CAD Spec
* [ ] UI 支持展示和确认 Impact Map
* [ ] UI 支持展示当前 Recipe 和 Abstract Step
* [ ] refine 不直接改 FreeCAD，必须重新进入 next_step
* [ ] `conversation_id` 可以在此阶段引入，但只服务于 spec/refine，不用于无限上下文堆叠

**验证**：

* [ ] 用户能修改 CAD Spec 后重新选择 Recipe
* [ ] 用户能拒绝 Impact Map，系统不执行高风险操作
* [ ] 用户能要求“只修改当前 step”，系统不重做整个模型
* [ ] refine 过程完整写入 trace

---

## 未来扩展 (V1.0+)

### PartDesign + Sketcher 工作流

**目标**：支持更工程化的参数化建模。

**内容**：

* [ ] create_body
* [ ] create_sketch
* [ ] sketch_add_rect / circle / line / polyline
* [ ] pad_sketch
* [ ] pocket_sketch
* [ ] revolve_sketch
* [ ] datum plane
* [ ] active body 管理

---

### Sketcher 约束系统

**目标**：让草图可控、可验证、可参数化。

**内容**：

* [ ] 水平 / 垂直 / 平行 / 垂直 / 相切 / 同心约束
* [ ] 尺寸约束自动推理
* [ ] 完全约束检查
* [ ] 草图闭合检查
* [ ] 约束冲突检测

---

### Advanced Rollback

**目标**：在系统足够稳定后，再考虑更复杂的回退能力。

**内容**：

* [ ] Abstract Step rollback
* [ ] Phase rollback
* [ ] Global replan
* [ ] 对象依赖链恢复
* [ ] visibility 恢复
* [ ] transaction snapshot
* [ ] rollback trace replay

---

### Real-time Communication

**目标**：在闭环逻辑稳定后，再优化交互体验。

**内容**：

* [ ] WebSocket 端点 `/agent/ws`
* [ ] 流式返回计划生成进度
* [ ] 步骤执行状态实时推送
* [ ] 面板实时更新
* [ ] 可中断执行

---

### 参数化模板库

**目标**：沉淀常见机械零件生成器。

**内容**：

* [ ] 齿轮生成器
* [ ] 轴承座生成器
* [ ] 法兰生成器
* [ ] 阶梯轴生成器
* [ ] 带孔底座生成器
* [ ] 支架生成器

---

### Assembly 支持

**目标**：支持多零件装配和装配约束。

**内容**：

* [ ] 多零件管理
* [ ] 配合关系推理
* [ ] 装配约束
* [ ] BOM 生成
* [ ] 爆炸图生成

---

### Visual Review

**目标**：利用截图辅助语义评估，但不替代几何验证。

**内容**：

* [ ] 自动切换 front / top / isometric view
* [ ] phase 完成后截图
* [ ] LLM 根据截图做语义评估
* [ ] 截图评估只作为辅助，不覆盖 deterministic validators

---

### Multi-Agent CAD Workflow

**目标**：只有在单 Agent 工作流稳定后，再考虑多 Agent。

**内容**：

* [ ] Spec Agent
* [ ] Recipe Agent
* [ ] Geometry Validator Agent
* [ ] Repair Agent
* [ ] Review Agent

**前置条件**：

* [ ] trace 稳定
* [ ] validators 稳定
* [ ] recipe registry 稳定
* [ ] golden cases 稳定
* [ ] 单 Agent 工作流可回归
