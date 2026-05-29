# Development Log

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