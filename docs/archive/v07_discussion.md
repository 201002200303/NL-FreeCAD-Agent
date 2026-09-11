# V0.7 架构升级讨论稿

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


## 一、当前状态（V0.6）

### 1.1 整体流程

```
用户输入自然语言 → 读取文档状态(仅一次) → LLM 生成完整计划(全部步骤)
→ 用户确认 → 盲执行所有步骤 → 完成
```

### 1.2 数据流

```
FreeCAD 插件 (panel.py)
  │
  ├── document_state.py 读取当前文档所有对象 → 发给 Agent Service (一次性快照)
  │
  ├── POST /agent/plan { user_input, document_state }
  │
  ▼
Agent Service (FastAPI + LangGraph)
  │
  ├── parse_input_node → plan_node(LLM) → validate_plan_node → END
  │   (校验失败最多重试2次，重试时携带错误信息)
  │
  ▼
返回完整 Plan JSON (例: 7步全部步骤)
  │
  ▼
FreeCAD 插件 (executor.py)
  │
  ├── for step in plan:
  │     tool_func(doc, **args)  ← 无感知，无反馈，不看文档状态
  │     doc.commitTransaction()
```

### 1.3 核心缺陷

| 问题 | 描述 |
|------|------|
| **无感知执行** | 生成计划后，executor 逐条执行，每步之间**不读取文档状态**，不知道上一步实际产生了什么结果 |
| **一次性规划** | LLM 在收到请求时**一次性生成全部步骤**，无法根据执行中间状态调整后续步骤 |
| **文档状态粗糙** | `document_state.py` 只提取对象名、类型、基础参数；Shape 信息只写 `<Shape object>` 占位符，缺少 BoundingBox、拓扑摘要等关键信息 |
| **无回退机制** | 步骤执行失败后只有 break，无法回退到安全状态重新规划 |
| **双进程通信单向** | FreeCAD → Agent 是单向 HTTP POST，Agent 无法在执行过程中请求 FreeCAD 刷新状态 |

### 1.4 已修复的 Bug（刚完成）

| Bug | 根因 | 修复 |
|-----|------|------|
| Fillet 产生两个可见对象 | `assign_shape_result` 对参数化对象 (Part::Cylinder) 创建新 Part::Feature 但没隐藏源对象 | 隐藏源对象 `Visibility=False` |
| 位置偏移 (Placement 二次应用) | `obj.Shape` 已含世界坐标，创建新 Part::Feature 时再赋 Placement 导致翻倍 | 不再赋值 Placement |
| 名称链断裂 | Base fillet 后产生 Base_Fillet，后续步骤仍引用 Base | executor 新增 `name_map` 自动追踪 |

### 1.5 现有组件清单

| 文件 | 职责 |
|------|------|
| `freecad_addon/AICADAgent/panel.py` | PySide 面板 UI，发送请求，展示计划，触发执行 |
| `freecad_addon/AICADAgent/executor.py` | 逐步执行计划，事务管理，名称链追踪 |
| `freecad_addon/AICADAgent/document_state.py` | 读取 FreeCAD 文档快照（粗糙） |
| `freecad_addon/AICADAgent/cad_tools/` | 37 个工具函数（primitives/boolean/features/transform/sketch/partdesign/surface/assembly/export/query） |
| `agent_service/app/main.py` | FastAPI 路由 `POST /agent/plan` |
| `agent_service/app/graph/cad_graph.py` | LangGraph 工作流：parse→plan→validate→END |
| `agent_service/app/graph/nodes.py` | 节点函数（parse_input, plan, validate_plan） |
| `agent_service/app/llm/planner.py` | LLM 优先 + 规则引擎回退 |
| `agent_service/app/llm/llm_provider.py` | 构建 prompt，调 OpenAI-compatible API |
| `agent_service/app/tools/tool_specs.py` | 工具规格定义（给 LLM 看的） |
| `agent_service/app/tools/tool_registry.py` | 工具分类检索 |

---

## 二、期望状态（V0.7）

### 2.1 核心理念

**像 Cursor / Claude Code 一样工作**：
1. 先生成一个**高层计划**（类似 Cursor 的 task breakdown）
2. **逐步执行**，每步执行前**感知当前状态**（类似 Claude Code 每步操作前读文件/跑测试）
3. 根据中间结果**动态调整**后续步骤
4. 失败时**有回退能力**

### 2.2 期望流程

```
用户输入 → 读取文档状态 → LLM 生成高层计划（概览级，不是逐条工具调用）

用户确认后：
  ┌→ 读取当前文档状态（完整快照）
  │  ↓
  │  执行当前步骤
  │  ↓
  │  收集执行结果（成功/失败 + 实际产生的对象信息）
  │  ↓
  │  LLM 评估：当前状态是否符合预期？
  │  ↓
  │  ├── 符合 → 推进到下一步
  │  ├── 偏差 → 调整后续步骤 / 插入修正步骤
  │  └── 严重失败 → 回退到安全点，重新规划
  │
  └── 循环直到所有步骤完成
```

### 2.3 关键机制

#### 2.3.1 文档状态感知（Document State Awareness）

每步执行前，从 FreeCAD 文档获取**完整且结构化**的状态：

```python
# 期望的文档状态格式
{
  "document_name": "Unnamed",
  "objects": [
    {
      "name": "Base",
      "type": "Part::Feature",
      "visible": true,
      "bbox": {"x": [-90, 90], "y": [-90, 90], "z": [0, 20]},
      "topology": {"faces": 5, "edges": 6, "vertices": 6},
      "placement": {"pos": [0, 0, 0], "rot": [0, 0, 0]},
    },
    {
      "name": "Base_Fillet",
      "type": "Part::Feature",
      "visible": true,
      "bbox": {"x": [-90, 90], "y": [-90, 90], "z": [0, 20]},
      "topology": {"faces": 7, "edges": 9, "vertices": 9},
      "placement": {"pos": [0, 0, 0], "rot": [0, 0, 0]},
    }
  ]
}
```

对比现在的粗糙版本（只有 name/type/几个 float 属性）。

#### 2.3.2 逐步执行循环（Step-by-Step Execution Loop）

```
                    ┌──────────────┐
                    │  高层计划     │
                    │  (概览级)    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
              ┌─────│  取下一步     │
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │ 读文档状态    │ ← 每步都读
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │ LLM 生成具体  │ ← 可以调整
              │     │ tool 调用     │
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │ 执行 tool     │
              │     └──────┬───────┘
              │            │
              │     ┌──────▼───────┐
              │     │ 评估结果      │
              │     └──┬───┬───┬───┘
              │        │   │   │
              │    成功 │ 偏差 │ 失败
              │        │   │   │
              │        ▼   ▼   ▼
              │     继续  调整  回退
              │            │   │
              └────────────┘   │
                        (重新规划)
```

#### 2.3.3 高层计划 vs 具体步骤

**现在**：LLM 一次性生成所有具体 tool 调用
```json
{
  "plan": [
    {"tool": "create_cylinder", "args": {"name": "Base", "radius": 90, ...}},
    {"tool": "add_fillet", "args": {"target": "Base", "radius": 5}},
    {"tool": "create_cylinder", "args": {"name": "Stem", ...}},
    // ... 7步全写死
  ]
}
```

**期望**：LLM 先给高层计划，具体步骤逐步展开
```json
{
  "high_level_plan": [
    {"phase": "底座", "description": "创建圆柱底座并倒圆角"},
    {"phase": "支柱", "description": "创建细长支柱连接底座"},
    {"phase": "灯罩", "description": "创建灯罩并倒圆角"},
    {"phase": "细节", "description": "添加开关按钮"}
  ]
}
```

每个 phase 执行时再展开为具体 tool 调用，展开时能看到**当前文档状态**。

#### 2.3.4 回退机制（V0.8 实现，V0.7 预留接口）

| 级别 | 触发条件 | 行为 |
|------|---------|------|
| 步骤级 | 单步 tool 执行报错 | 当前事务 rollback，LLM 看到错误后生成替代方案 |
| 阶段级 | 一个 phase 完成后评估发现不符合预期 | 回退到 phase 开始前，重新生成该 phase 的子步骤 |
| 整体级 | 架构性错误（如底座设计不合理导致后续全部受影响） | 回退到最初，重新生成高层计划 |

### 2.4 需要改造的组件

| 组件 | 改动 | 优先级 |
|------|------|--------|
| `document_state.py` | 增强：补 BoundingBox、拓扑摘要、Visibility、Placement 精确值 | P0 |
| `executor.py` | 改造：逐步执行 + 每步前后读文档状态 + 返回执行结果给 LLM | P0 |
| `panel.py` | 改造：支持逐步执行 UI（进度显示、每步确认/跳过） | P1 |
| `planner.py` | 新增：单步规划模式（接收文档状态+历史，生成下一步） | P0 |
| `llm_provider.py` | 改造：支持两种 prompt 模式（整体规划 / 单步规划） | P0 |
| `cad_graph.py` | 重构：从线性流改为循环流（execute→observe→decide→execute） | P0 |
| `nodes.py` | 新增：execute_node, observe_node, decide_node | P0 |
| Agent↔FreeCAD 通信 | 新增：Agent 能主动请求 FreeCAD 刷新文档状态（当前只有 FreeCAD→Agent 单向） | P0 |

### 2.5 通信架构变化

**现在**：
```
FreeCAD ──HTTP POST──→ Agent Service ──HTTP Response──→ FreeCAD
（单次请求-响应）
```

**期望**：
```
FreeCAD ──POST /agent/plan──→ Agent (生成高层计划)
FreeCAD ←──返回高层计划───── Agent

FreeCAD ──POST /agent/execute_step──→ Agent (执行步骤N，附带当前文档状态)
FreeCAD ←──返回具体tool调用+评估─── Agent

... 循环 ...

FreeCAD ──POST /agent/finish──→ Agent (完成)
```

或者用 WebSocket 保持长连接（V0.7+ 可考虑）。

### 2.6 类比

| 概念 | Coding Agent (Cursor/Claude Code) | CAD Agent (本项目 V0.7) |
|------|----------------------------------|------------------------|
| 代码库状态 | 文件系统、git diff、linter 输出 | FreeCAD Document 快照 |
| 计划 | Task breakdown / TODO list | 高层建模计划 (phase 级) |
| 逐步执行 | 每步写代码 → 跑测试 → 看结果 | 每步调 tool → 读文档状态 → 评估 |
| 回退 | git checkout / undo | FreeCAD transaction rollback |
| 上下文窗口 | 当前文件 + 相关文件 + 错误信息 | 文档状态 + 已完成步骤 + 执行结果 |

---

## 三、实现路径（最终版）

详见 `development_plan.md` V0.7 章节，共 8 个 Step：

1. **增强文档状态** — document_state.py + cad_state.py schema
2. **executor 改为单步执行器** — execute_tool_call() + 统一返回结构
3. **新增 agent_runner.py** — QThread 闭环控制器
4. **Agent Service — start_plan** — 高层计划生成 graph + endpoint
5. **Agent Service — next_step** — 单步规划 graph + endpoint
6. **Agent Service — evaluate_step** — 确定性校验 graph + endpoint
7. **panel.py 切换新 API** — 新按钮 + 执行轨迹日志
8. **planner.py + llm_provider.py 扩展** — 三种 prompt 模式

V0.8 再实现：分层 Plan Agent（任务分解）+ 阶段级/整体级回退。

---

## 四、开放问题（已解决 / 延后）

| 问题 | 决议 |
|------|------|
| 单步规划的 LLM 调用开销 | V0.7 每步都调 LLM，不做快速通道；V0.8 可考虑简单步骤本地规则 |
| 文档状态粒度 | 完整依赖链 + bbox/topology/placement/visibility；只对有 Shape 的对象提取几何信息 |
| 事务边界 | 每个 tool 调用是一个事务（现有逻辑不变） |
| 并发 | V0.7 不做并行执行，每步串行 |
| 通信方式 | V0.7 继续 HTTP 多次请求；WebSocket 推到 V0.8+ |

---

## 五、最终决策记录（质询结论）

### 5.1 V0.7 范围
**完全替换**原 V0.7 定义（分层 Plan Agent）。原"decompose → sub_plan → merge"移至 V0.8。V0.7 专注于闭环架构。

### 5.2 API 设计
**三个独立端点**：
- `POST /agent/start_plan` — 生成高层 phase plan
- `POST /agent/next_step` — 根据当前状态 + history 生成下一步 tool call
- `POST /agent/evaluate_step` — 接收执行前后状态，做确定性校验 + 决策

`next_step` 的 decision 取值：`execute` / `ask_user` / `repair` / `replan` / `finish` / `abort`

`evaluate_step` 的 decision 取值：`continue` / `repair` / `skip_and_continue` / `replan` / `finish` / `abort`

### 5.3 LangGraph 策略
**保留并扩展**，采用**多个独立 graph，共享扩展后的 AgentState**：
- `build_cad_graph()` — 旧 `/agent/plan` 使用，不变
- `build_start_plan_graph()` — `parse_input → generate_high_level_plan → validate_high_level_plan → END`
- `build_next_step_graph()` — `summarize_state → plan_next_tool_calls → validate_tool_calls → END`
- `build_evaluate_graph()` — `diff_state → deterministic_check → llm_judge → route_decision → END`

### 5.4 旧 API 兼容
**保留 `/agent/plan` 不动**，panel.py 完全切换新 API。`executor.execute_plan()` 也保留兼容。

### 5.5 Session 存储
**FreeCAD 端存储 session**，每次请求发**摘要**给 Agent：
- 最近 5 步详细结果
- 之前步骤的状态计数（成功 N 步，失败 M 步）
- name_map 全量
- phases 全量
- 当前 document_state 全量

### 5.6 修复策略
**单步失败最多重试 2 次**（与现有 validate_plan 重试逻辑一致）。2 次修复都失败后**跳过该步骤，标记为 failed，继续下一个 phase**。中等失败和严重失败推到 V0.8。

### 5.7 确定性校验位置
**放在 Agent Service 端**做完整校验。`/agent/evaluate_step` 接收完整 `before_state` + `after_state`，Agent 自己做 diff 分析和规则校验。

### 5.8 文档状态依赖链
**保留完整依赖链**（`InList` / `OutList`）。大型模型时做截断处理。

### 5.9 线程模型
**QThread 处理 HTTP 通信**，通过 signal 回主线程做 FreeCAD 操作。自动执行循环跑在 QThread 里，每步执行完通知主线程执行 FreeCAD tool call。

### 5.10 Graph 扩展方式
**多个独立 graph**，各自有 entry point 和 END。共享扩展后的 AgentState（新增 optional 字段保持向后兼容）。main.py 三个端点分别调三个 graph。