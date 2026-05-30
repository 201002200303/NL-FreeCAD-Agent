# Development Log

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