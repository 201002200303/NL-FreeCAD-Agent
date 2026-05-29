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

### V0.4 — LLM Structured Output (当前)

**目标**：接入 LLM，用 system prompt + user_input + tool_specs 生成建模 Plan，验证 LLM 输出能驱动建模。

**内容**：
- [ ] 接入 OpenAI-compatible API (chat completions)
- [ ] 构建 system prompt：角色 + 可用工具 + 输出格式 + 规则
- [ ] 实现 LLM structured output (JSON mode)
- [ ] 将已实现的 tool_specs 注入 prompt
- [ ] LLM planner 替代规则 planner（规则保留为 fallback）
- [ ] 验证：LLM 生成的 plan 能在 FreeCAD 中执行建模

**可验证**：
1. 启动 agent_service
2. 输入任意自然语言建模需求（不限关键词）
3. LLM 返回结构化 plan
4. 在 FreeCAD 中执行，模型正确创建

---

### V0.5 — LangGraph Integration

**目标**：引入 LangGraph 编排 LLM plan 生成流程，增加校验、重试、文档状态推断。

**内容**：
- [ ] 实现 graph/cad_graph.py 的完整工作流
- [ ] parse_input → llm_plan → validate_plan 节点
- [ ] 集成 tool_specs 到 plan 校验
- [ ] 支持从文档状态中推断参数
- [ ] 错误重试机制

---

### V0.6 — Multi-turn & Persistence

**目标**：支持多轮修改、文档状态感知、错误恢复。

**内容**：
- [ ] conversation_id 多轮对话支持
- [ ] 读取当前文档对象状态并传入 Agent
- [ ] 基于现有模型生成修改 plan
- [ ] SQLite 记录 plan 和 execution 历史
- [ ] 错误恢复：步骤失败后支持重试/跳过/回滚全部
- [ ] /agent/refine 端点

---

### V0.7 — Full Tool Implementation

**目标**：实现所有 MVP CAD Tools。

**内容**：
- [ ] create_sketch + pad_sketch
- [ ] cut_center_hole / cut_corner_holes
- [ ] add_fillet / add_chamfer
- [ ] export_step / export_stl
- [ ] 工具单元测试

---

### V0.8 — Real-time Communication

**目标**：WebSocket 实时通信。

**内容**：
- [ ] WebSocket 端点 /agent/ws
- [ ] 流式返回 plan 生成进度
- [ ] 步骤执行状态实时推送
- [ ] 面板实时更新

---

## 未来扩展 (V1.0+)

### PartDesign 工作流
- Body 管理
- Sketch + Pad + Pocket + Revolution
- 参考平面和基准面

### Sketcher 约束系统
- 几何约束 (水平/垂直/平行/相切/同心)
- 尺寸约束自动推理
- 完全约束检查

### 参数化模板
- 齿轮生成器
- 轴承座生成器
- 法兰生成器
- 用户自定义模板

### Assembly 支持
- 多零件装配
- 配合关系推理
- BOM 生成

### 高级特性
- 版本历史回放
- 建模过程可视化
- 非破坏性参数化修改
- 多 Agent 协作建模
