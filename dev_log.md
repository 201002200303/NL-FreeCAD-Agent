# Development Log

## 2026-07-31: DeepSeek reasoning 空 content 导致 LLM 调用失败

**现象**: `next_step` 返回 `LLM 调用失败`；trace 显示 `content=""`，JSON 在 `reasoning_content`。
**根因**: `call_llm` 只读 `message.content`，reasoning 模型偶发把最终答案放进 `reasoning_content`。
**修复**: `_message_text` 回退 `reasoning_content`；`_extract_json_object` 容忍 ```json 与 `json\n{...}` 前缀。

## 2026-07-31: 草图曲线工具 arc / polyline / bspline

**新增**（对齐 FreeCAD Sketcher 脚本 API）:
- `sketch_add_arc`: `Part.ArcOfCircle`，mode=`three_point` | `center`（角度用度，内部转弧度）
- `sketch_add_polyline`: 连续 `LineSegment` + `Coincident`，可选 `closed`
- `sketch_add_bspline`: `Part.BSplineCurve.interpolate` / `buildFromPoles`

**改动**: `sketch_tools.py` + `__init__`；`tool_specs`/`tool_registry`；工具数 46→49。验证: registry/spec 对齐 + `scripts/verify_sketch_curves.py`

## 2026-07-31: Debug trace 可读化

**问题**: 一步拆成 llm_01_system_prompt / user_message / raw / parsed 多文件，难跟上下文。
**改动**: 每步主读 `llm_XX_trace.md`（工具列表→system prompt→user 上下文→模型输出）；session 根 `README.md`；去掉分散 md。

## 2026-07-31: 工具规范修复 + evaluate 队列推进 bug

**工具规范**（对照 tool_design / spec↔实现）:
1. `set_placement`/`apply_placement`：全 0 参数可复位原点；`mirror` 隐藏源对象
2. `revolve_sketch` 使用 axis_x/y/z；`create_sketch_on_face` face 大小写/越界校验
3. primitive/fillet/scale 数值校验；unit 仅 mm；`compare_orientation` 用 tolerance_ratio 判各向同性
4. executor abortTransaction 不掩盖原始错误；spec 描述同步

**evaluate 推进**（3 个 harness 失败根因）:
1. `normalize_evaluate_decision`：abstract step 未耗尽时禁止按 high_level 末阶段强制 finish
2. 成功推进不再依赖 LLM `phase_status=completed`；warning validator 不阻断
3. 连续失败≥2 或 `skip_and_continue` 时推进 abstract step，decision→continue

**配置**: LLM → DeepSeek (`https://api.deepseek.com`, `deepseek-v4-flash`)
**测试**: `test_v08_harness` + `test_tool_registry` 40 passed

## 2026-05-29: V0.8 CAD Harness Core

**目标**: Spec → Impact → Recipe → Abstract Step 队列 → 滚动 tool_calls → validators → 推进 queue（非 sub_plan 脚本）。

**改动**:
1. **Agent Service**: `cad_spec/`, `inspection/impact_map.py`, `recipes/registry.py`, `abstract_steps/planner.py`, `evaluation/validators.py` + `harness.py`, `debug/replay_trace.py`
2. **API**: `/agent/spec`, `/agent/impact_map`, `/agent/select_recipe`；`next_step`/`evaluate_step` 扩展 harness 字段（queue、abstract_step、validator_results）
3. **Graph**: `plan_next_step_node` 队列耗尽 finish；`evaluate_step_node` 校验通过后 harness 推进 abstract step
4. **FreeCAD**: `agent_runner.start_harness()` spec→impact→recipe→start_plan；evaluate 响应同步 queue/step
5. **测试**: `test_v08_harness.py` 12 项（spec/impact/recipe/next/evaluate/advance/replay API 流）

**设计**: Recipe 只含 abstract_steps，不含 tool sequence；每步 next 最多 3 个 tool_calls；deterministic validators 优先于 LLM finish 判断。

**UX**: Spec/Recipe 未匹配时 `start_harness` 自动回退 V0.7 LLM `start_plan`；404 提示旧版 Agent Service；按钮文案说明 Harness→LLM 双路径。

## 2026-05-30: V0.8.7 空间感知 + 路由统一

**问题**: LLM 回退路径建模缺 3D 空间感知，对象坐标靠臆造，多体模型（汽车）无法装配。根因: `_build_document_context` 只喂 name/type，丢弃了已采集的 bbox/placement。

**改动**:
1. `llm_provider._build_document_context`: 注入每对象 center/size/pos/rot/volume/visible + 空间定位规则（基于已有对象坐标计算，禁止臆造；create_cylinder 默认轴 Z，水平需绕 X 转 90°）。next_step/evaluate 双 prompt 同时受益。
2. `planner.is_harness_session()`: 单一谓词统一 Harness-vs-LLM 路由（需 cad_spec + 非空 queue）；`nodes.py` plan_next_step/evaluate_step 改用它，消除散落条件。
3. 测试 12→14（harness session 谓词 + LLM 回退路由）。
4. `development_plan.md` 新增 V0.8.7（1+2 已完成，3 validators 回退路径 / 4 朝向装配约束 待做）。

**架构差异结论**: V0.8 期望"复杂建模走可控轨道"，实际 6 个 recipe 仅覆盖单 primitive/单特征，复杂任务必走 LLM 回退；Spec 为规则非 LLM；validators/impact_map 在回退路径未生效。详见 V0.8.7 与下方 review。

## 2026-05-30: V0.8 架构统一（Spec LLM + 单轨 queue + 全局 validators）

**改动**:
1. **Spec LLM**: `generate_cad_spec_with_llm` 优先；规则 `_generate_cad_spec_with_rules` 作 API 不可用回退；Harness 不再 Spec 失败就 skip
2. **统一控制**: `build_queue_from_phases` 将 start_plan phases → abstract_step 队列（step_type=llm_phase）；`plan_next_step` 对 llm_phase 调 LLM、对 recipe step 调确定性 tool_calls
3. **全局 validators**: `resolve_validator_names` + evaluate 全路径跑 validators；queue 推进不再依赖 cad_spec
4. **Server 权威**: start_plan/evaluate 响应带 queue/step；FreeCAD `_sync_session_from_evaluate` 纯同步，删 `_advance_abstract_step_if_validated`
5. **测试**: 19 项（LLM spec mock、queue 统一、llm_phase next_step、全局 validators）

**流程**: Spec(LLM) → Impact → Recipe(可选) → start_plan(queue) → next/evaluate(统一 abstract step 推进)

## 2026-05-30: 修复 robot 误匹配 recipe + fillet 死循环

**问题**: robot 误选 `box_with_fillet_recipe`(2步) 覆盖 5 phase LLM 队列；fillet target=`Torso, Head, Base` 整串当对象名；skip 不推进 AS2 死循环。

**改动**: `select_recipe` 复杂 model_type 返回 llm_fallback；`should_use_recipe_queue` 阶段多于 recipe 时用 LLM 队列；`_resolve_target_name` 解析逗号 target；skip 连续失败时 server 推进 abstract step。测试 23 项。

## 2026-05-29: V0.7 闭环建模 Agent

**目标**: 从 Plan-as-Script 升级为 Observe-Plan-Act-Evaluate 闭环控制。

**改动**:
1. **FreeCAD 端**: `document_state.py` 增强 bbox/topology/visible/placement/dependencies；`executor.py` 新增 `execute_tool_call()`；新建 `agent_runner.py`（QThread 闭环控制器）；`panel.py` 切换新 UI（高层计划/单步/自动/暂停/停止）
2. **Agent Service**: 新增三个 API（`/agent/start_plan`, `/agent/next_step`, `/agent/evaluate_step`）；LangGraph 扩展为 3 个独立 graph；`cad_state.py`/`session.py` schema 升级；`planner.py`/`llm_provider.py` 三种 prompt 模式；`evaluation/rules.py` 确定性校验
3. **决策**: 保留旧 `/agent/plan`；Session 存 FreeCAD 端；失败最多重试 2 次后 skip_and_continue

**架构**: FreeCAD 驱动循环（observe+act），Agent 负责 plan+decide

**Bugfix**: P1 完成后过早 finish — 新增 `evaluation/phases.py` 阶段推进逻辑；evaluate/next_step 禁止非末阶段返回 finish；evaluate 请求携带 high_level_plan + current_phase_id

**Bugfix**: cut_hole/fillet 对 Part::Feature 原地修改导致 `{target}_Hole` 不存在 → `assign_shape_result` 在 result_name 不同时创建新对象；HTTP 500 因 repair_tool_calls 缺 call_id → `_sanitize_tool_calls`；HTTP timeout 120→300s

**Debug 模式**: `app/debug/trace_logger.py` + `call_llm` 挂钩；API 写 request/LLM response/execution；FreeCAD 面板勾选 + `POST /agent/log_execution`；目录 `agent_service/debug_sessions/`

## 2026-05-29: V0.6 Bug Fix - Placement 二次应用 + 名称链追踪

**问题**: Fillet/Boolean/Scale/Mirror 生成新 Part::Feature 时，Placement 被二次应用（位置偏移）；源对象未隐藏导致视觉重叠；后续步骤引用旧名。

**改动**:
1. `_helpers.py` `assign_shape_result()` - 隐藏源对象（`Visibility=False`），删除 `feat.Placement = target.Placement`
2. `boolean_tools.py` `_boolean_result()` - 隐藏 base/tool 对象，删除 Placement 赋值
3. `feature_tools.py` `mirror()` - 删除 Placement 赋值
4. `transform_tools.py` `scale()` - 隐藏源对象，删除 Placement 赋值
5. `executor.py` - 新增 `name_map` 追踪对象名变化（Base→Base_Fillet），`_rewrite_args()` 自动解析后续步骤中的旧名引用

**根因**: Part::Cylinder 等参数化对象的 Shape 已包含世界坐标（Placement 已应用），创建 Part::Feature 时再赋值 Placement 导致位置翻倍。

## 2026-05-29: V0.6 工具大扩充 + 树状分类检索

**目标**: 工具 6→22，建立分类检索，解除 LLM 建模能力瓶颈。

**改动**:
1. FreeCAD 侧新增 `boolean_tools.py`, `transform_tools.py`, `_helpers.py`；扩展 primitive/feature/export
2. TOOL_REGISTRY 注册 22 个工具（primitives/boolean/features/transform/export）
3. `tool_specs.py` 同步 22 个 spec
4. `tool_registry.py` — TOOL_CATEGORIES + get_tools_by_categories + infer_categories_for_task
5. `llm_provider.py` — build_system_prompt 支持 tool_categories 子集注入
6. 测试: test_tool_registry.py + test_pipeline.py 全通过；FreeCAD 功能测试脚本 test_v06_freecad_tools.py

**API 参考**: FreeCAD Topological data scripting (fuse/cut/common, makeSphere/Cone/Torus, makeFillet/Chamfer, exportStep/exportStl)

## 2026-05-29: V0.6+ 高级工具 + 拓扑选边

**新增**: list_topology, 草图链(7), PartDesign(5), 曲面(3), 装配(4); 增强选边(face_selector/zone/longest)
**调研**: FreeCAD 拓扑命名问题 — Edge1/Face1 为 1-based 索引，修改后重排；操作前 list_topology + 语义选择器

## 2026-05-29: 位置控制工具 + 超时优化

**问题**: 创建对象只能在原点堆叠，LLM 无法指定位置；客户端请求经常超时。

**改动**:
1. `primitive_tools.py` - create_box/create_cylinder 增加 pos_x/pos_y/pos_z 参数
2. `modify_tools.py` - 新增 set_placement 工具（位置+旋转）
3. `tool_specs.py` - 更新工具规格，增加位置参数和 set_placement
4. `llm_provider.py` - max_tokens 40960→4096（减少生成时间）
5. `panel.py` - 客户端 timeout 30→120 秒

## 2026-05-28: V0.2-V0.3 API 调用验证

**目标**: 清理 executor.py，打通 API→plan→执行链路，验证工具调用建模

**改动**:
1. `executor.py` - 删除 8 个 stub 方法 (NotImplementedError)，保留 5 个真实接口: create_box, create_cylinder, modify_param, delete_object, save_fcstd
2. `panel.py` - 添加"执行计划"按钮和 `_on_execute_plan()` 方法，缓存 plan 并调用 executor 执行

**验证结果**:
- ✓ FastAPI 服务启动成功 (http://127.0.0.1:8765)
- ✓ `POST /agent/plan` 正确返回 create_box plan (100x60x20mm)
- ✓ `POST /agent/plan` 正确返回 create_cylinder plan (R25 H50)
- ✓ `GET /health` 返回 status: ok

**下一步**: 在 FreeCAD 中测试完整流程 - 输入需求 → 生成 plan → 执行建模

## 2026-05-28: executor.py 与 cad_tools/ 解耦重构

**目标**: 将 executor.py 中的 5 个工具方法拆分到 cad_tools/ 下对应模块，executor 仅做调度和事务管理。

**改动**:
1. `cad_tools/primitive_tools.py` - 实现 create_box、create_cylinder 纯函数（参数为 doc）
2. `cad_tools/modify_tools.py` - 实现 modify_param、delete_object 纯函数
3. `cad_tools/export_tools.py` - 实现 save_fcstd 纯函数
4. `cad_tools/__init__.py` - 构建 TOOL_REGISTRY，提供 get_tool/list_tool_names
5. `executor.py` - 删除所有工具方法，改为通过 TOOL_REGISTRY 调度（getattr → registry lookup）

**架构**: 工具函数签名统一为 `func(doc, **args) -> dict`，executor 负责事务管理（begin/commit/rollback）和计划执行。

## 2026-05-28: FreeCAD 端到端验证通过

**验证内容**: 在 FreeCAD 中完成完整流程测试 — 面板输入自然语言 → 调用 API 生成 plan → 点击执行按钮 → FreeCAD 特征树中成功创建模型（create_box / create_cylinder）。

**结果**: V0.2-V0.3 目标达成，API→plan→executor→cad_tools 全链路打通。

## 2026-05-28: LLM 接入与建模验证

**目标**: 接入 LLM 替代纯规则引擎，实现自然语言驱动的建模计划生成。

**改动**:
1. `llm_provider.py` - 新增 LLM 集成模块：
   - `build_system_prompt()`: 构建 system prompt，自动注入 TOOL_SPECS（12 个工具）
   - `call_llm()`: 调用 OpenAI-compatible API（支持自定义 base_url），使用 JSON mode
   - `generate_plan_with_llm()`: 生成 + 格式校验 + 默认值填充
2. `planner.py` - 改为 LLM 优先、规则引擎回退：`generate_plan()` → `generate_plan_with_llm()` → 失败则 `_generate_plan_with_rules()`
3. `config.py` - 新增环境变量：`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`

**架构**: LLM 返回结构化 JSON（status/goal/plan），plan 中的 tool 字段与 TOOL_REGISTRY 对齐。规则引擎保留作为 fallback。

**验证结果**: LLM 生成计划 → executor 执行 → FreeCAD 建模成功。

## 2026-05-29: V0.5 LangGraph Pipeline

**目标**: 搭好 LangGraph 链路，实现 plan 生成的校验+重试机制，替代直接调用。

**改动**:
1. `state.py` - AgentState 增加 retry_count、validation_errors 字段
2. `nodes.py` - 重写三个节点函数：
   - `parse_input_node`: 输入校验、初始化重试状态
   - `plan_node`: 调用 generate_plan，重试时携带错误上下文
   - `validate_plan_node`: 工具名/必填参数/类型/依赖校验，调用 `_validate_plan()`
   - `should_end()`: 条件路由（ok→end, fail&retry<2→retry, fail&retry>=2→end）
3. `cad_graph.py` - 构建完整工作流图：
   - parse_input → plan → validate_plan → 条件边
   - 校验通过→END；校验失败且 retry<2→retry_bump→plan（重试）；retry>=2→END
   - `get_cad_agent()` 单例模式返回编译后的 graph
4. `llm_provider.py` - 增强 prompt 构建：
   - `build_system_prompt(document_state)`: 支持注入文档状态上下文
   - `_build_document_context()`: 格式化当前文档对象列表
   - 修复 max_tokens 从 200000 改为 4096（适配阿里云 API 限制）
5. `planner.py` - `generate_plan()` 传递 document_state 到 LLM
6. `main.py` - `/agent/plan` 路由改为调用 graph agent：
   - 构建 input_state，调用 `agent.invoke()`
   - 处理校验失败和错误状态映射

**架构**: parse_input→plan→validate→(条件)→end/retry，最多重试2次。重试时将错误信息注入 user_input 让 LLM 自我纠正。

**验证结果**:
- ✓ 8个单元测试全部通过（校验正确plan、错误工具名、缺少参数、类型错误、路由逻辑）
- ✓ API 端点测试通过（POST /agent/plan 返回 LLM 生成的 plan）
- ✓ 完整 graph 执行测试通过（从输入到最终状态的全链路）

## 2026-05-31: 去掉 Spec 前置，纯 Plan 闭环 + 全步 LLM 调试

**目标**: 取消 FreeCAD 执行链中的 spec/impact/recipe；全局 plan 后 Cursor 式逐步推进；调试记录每步 LLM 输入/输出。

**改动**:
1. **FreeCAD**: `panel`/`agent_runner` 直接 `start_plan`，删除 harness 四段式前置
2. **start_plan**: 始终从 phases 构建 abstract step queue，不再走 recipe 分支
3. **next_step**: 统一 LLM 生成 tool_calls（移除 cad_spec 确定性分支）
4. **evaluate_step**: 每步必调 LLM（附带确定性校验/validator 结果）；成功且 `phase_status=completed` 时推进 queue
5. **高层 plan prompt**: 只输出意图级阶段，禁止预先展开尺寸/工具

**调试**: 单 session 目录下 `001_start_plan`、`00N_next_step_*`、`00N_evaluate_step_*` 均含 `llm_01_*.md`（evaluate 成功路径亦有）。

## 2026-05-31: 空间定位最小修复（车轮朝向 + 贴附 + bbox）

**问题**: `set_placement` 把 rot 当 YPR 导致 rot_x=90 车轮仍竖直；bbox 用局部 BoundBox 与旋转不一致；车灯只贴 x 未对齐 y/z；validator 成功仍报 not found。

**改动**:
1. **FreeCAD**: `_helpers.apply_axis_rotation` + `set_placement`/`create_cylinder(rot_*)` 绕轴旋转；`document_state` 改 `getBoundBox()` 世界坐标，过滤 Origin/Axis 噪声
2. **LLM**: `_build_document_context` 输出 x/y/z 范围 + 贴面/车轮/pos 角点规则
3. **validators**: `verify_object_exists` 成功 message 修正；**trace**: `open_existing` 不再覆盖 session_summary

## 2026-05-31: development_plan 关键时刻 + Pull 链路 rationale

**改动**: Version Roadmap 增「关键时刻/版本依赖链/设计原则(Codex+SW 对照)」；V0.8–V0.11 各节补「为什么」与上下游；8.3 明确 Push→Pull query-before-act；exit criteria 阻塞 V0.9；修复文档转义损坏。

## 2026-05-31: SessionMemory 四层工作记忆

**问题**: history 是流水账，prompt 只取 recent[-5] 与 runner 发 20 条不一致；query_result 未结构化进 prompt；失败无 avoid_repeating。

**改动**:
1. **FreeCAD** `session_memory.py` + `AgentSession.record_tool_result/refresh_memory_from_document`：working/object/error/query_cache/progress/long_summary
2. **Agent** `app/memory/` prompt 格式化 + history 回退 pack；`next_step`/`evaluate_step` 收 `session_memory`；prompt 改读 memory pack + 紧凑 object 索引（非全量 document_state）
3. **query_policy**: `query_cache_covers_target` 优先于 history 扫描

## 2026-05-31: 解绑 tool use 类别限制

**问题**: abstract step / recipe 的 `allowed_tool_categories` 仅列 6 类；category 推断默认 `primitives`；prompt 未明确 sketch/partdesign/surface/assembly 可用。

**改动**:
1. `tool_registry`: `ALL_TOOL_CATEGORIES`、`resolve_tool_specs_for_prompt()` 默认全量 46 工具；未匹配任务推断回退全类别
2. `build_queue_from_phases` / recipes: `allowed_tool_categories=[]` 表示不限
3. prompt 注入 category summary + 全量 spec；next_step 规则明确可用全部 registry 工具

## 2026-05-31: 取消每步 1-3 个 tool call 上限

**改动**: `llm_provider` next_step prompt 去掉 1-3 限制，允许一步批量（如四轮子同批）；`development_plan` 设计原则同步。