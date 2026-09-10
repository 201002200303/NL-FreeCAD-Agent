# Historical Architecture — NL-FreeCAD-Agent

> 本文记录 V0.1 的 Plan-as-Script 架构，不是当前实现依据。当前主线见 [code_mode.md](code_mode.md) 与 [development_mainline.md](development_mainline.md)。下文“不让 LLM 生成代码”等决策已被 ADR-0001 取代。

## 双进程架构

```
┌─────────────────────────────────────────────┐
│              FreeCAD GUI Process             │
│                                             │
│  AICADAgent Workbench                       │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  │
│  │ Panel   │  │ Executor │  │ DocState  │  │
│  │ (PySide)│  │          │  │ Reader    │  │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  │
│       │            │              │         │
│       │   HTTP POST /agent/plan   │         │
│       │            │              │         │
│       │     FreeCAD Python API    │         │
│       │     (Part, Mesh, ...)     │         │
└───────┼────────────┼──────────────┼─────────┘
        │            │              │
        │   HTTP (127.0.0.1:8765)   │
        │            │              │
┌───────┼────────────┼──────────────┼─────────┐
│       ▼            ▼              ▼         │
│           Agent Service Process              │
│                                             │
│  FastAPI + LangGraph                         │
│  ┌──────────────────────────────────────┐   │
│  │  Planner → Tool Selector → Validator │   │
│  └──────────────────────────────────────┘   │
│                  │                           │
│            SQLite (records)                  │
└──────────────────────────────────────────────┘
```

## 为什么采用双进程架构

FreeCAD 内置的 Python 环境是 FreeCAD 自己打包的，依赖管理受限。将 Agent 服务独立出来有以下好处：

1. **依赖隔离**：Agent 服务可以使用任意 Python 包（langgraph, openai, sqlalchemy 等），不受 FreeCAD 内置 Python 限制。
2. **独立开发**：Agent 服务可以单独测试、单独部署、单独重启，不依赖 FreeCAD GUI。
3. **安全隔离**：LLM 推理和 API 调用在独立进程中，不影响 FreeCAD GUI 的稳定性。
4. **轻量 FreeCAD 插件**：FreeCAD 插件只做 UI 和 CAD 操作，不需要引入 langgraph、openai 等重量级依赖。HTTP 请求使用标准库 `urllib.request`。

## 通信方式

| 阶段 | 协议 | 方向 | 说明 |
|------|------|------|------|
| V0.1 | HTTP POST | FreeCAD → Agent | 请求建模计划 |
| V0.1 | HTTP Response | Agent → FreeCAD | 返回 Plan JSON |
| V0.7+ | WebSocket | 双向 | 实时流式推送、步骤执行状态 |

## 数据流

### Step 1: 用户输入
```
User types in FreeCAD panel
  → panel.py captures text
  → document_state.py reads current doc state
```

### Step 2: 发送请求
```
POST /agent/plan
{
  "user_input": "创建一个 100×60×20mm 的底座",
  "document_state": { ... }
}
```

### Step 3: Agent 处理
```
planner.py (V0.1: rules, V0.5+: LLM)
  → Parse intent
  → Match keywords / extract params
  → Generate Plan JSON
  → Return response
```

### Step 4: 展示 Plan
```
FreeCAD panel displays the Plan JSON
User reviews and confirms
```

### Step 5: 执行 Plan (V0.3+)
```
executor.py iterates over plan steps
  → For each step:
    → doc.openTransaction()
    → Call tool method (create_box, etc.)
    → doc.commitTransaction()
    → doc.recompute()
    → Log result to panel
```

### Step 6: 用户交互
```
User inspects FreeCAD feature tree
  → Can continue manual modeling
  → Can send new natural language request for modification
```

## 关键设计决策

### 不让 LLM 直接生成 FreeCAD Python 代码

原因：
- FreeCAD Python API 复杂且文档不全，LLM 容易生成错误代码
- 生成的代码可能缺少 `doc.recompute()`、事务管理等关键步骤
- 无法对代码进行参数校验和安全检查
- 代码不可审计、不可版本化

替代方案：
- LLM 只输出结构化 JSON（CAD Tool + args）
- 每个 Tool 是预定义的、经过测试的操作封装
- Tool 内部处理 FreeCAD API 的细节、边界检查和错误恢复

### 不在 FastAPI 中操作 FreeCAD

原因：
- FastAPI 进程无法直接访问 FreeCAD GUI 和文档对象
- FreeCAD Python 模块只能在 FreeCAD 进程内使用
- 保持 Agent 服务的无状态和可独立测试性

### 使用 Plan 中间表示

Plan 是自然语言到 CAD 操作的桥梁。它提供：
- 可解释性：用户可以理解 Agent 的建模思路
- 可审计性：Plan 可以被记录、回放、分析
- 可修改性：用户或 Agent 可以在执行前修改 Plan
- 可恢复性：执行失败时可以从 Plan 的某个步骤重试
