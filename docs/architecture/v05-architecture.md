# V0.5 Architecture - LangGraph Workflow

## System Architecture Diagram

```mermaid
graph TB
    subgraph FreeCAD插件端
        Panel[面板UI]
        Executor[执行器]
    end
    subgraph Agent服务端-FastAPI
        API[API端点]
        Graph[LangGraph工作流]
        Planner[计划生成器]
        LLM[LLM调用器]
        Validator[验证器]
    end
    subgraph 工具模块
        Registry[工具注册表]
    end
    Panel -->|POST /agent/plan| API
    API --> Graph
    Graph --> Planner
    Planner -->|优先| LLM
    LLM -->|OpenAI API| LLMAPI[外部LLM]
    Graph --> Validator
    Graph -->|返回Plan| API
    API --> Panel
    Panel -->|执行| Executor
    Executor --> Registry
```

## LangGraph Workflow

```mermaid
graph LR
    Start([开始]) --> ParseInput[解析输入]
    ParseInput --> GeneratePlan[生成计划]
    GeneratePlan --> ValidatePlan[验证计划]
    ValidatePlan --> IsValid{验证通过?}
    IsValid -->|是| ReturnPlan[返回Plan]
    IsValid -->|否| CheckRetry{重试<2?}
    CheckRetry -->|是| InjectError[注入错误信息]
    InjectError --> GeneratePlan
    CheckRetry -->|否| Fallback[回退规则引擎]
    Fallback --> ReturnPlan
    ReturnPlan --> End([结束])
```

## Workflow Details

```mermaid
sequenceDiagram
    participant API as FastAPI
    participant G as LangGraph
    participant Plan as Planner
    participant LLM as LLM
    participant V as Validator
    
    API->>G: invoke(user_input)
    G->>G: 1. parse_input_node
    G->>Plan: 2. plan_node
    Plan->>LLM: call_llm
    LLM-->>Plan: Plan JSON
    Plan-->>G: plan_json
    G->>V: 3. validate_plan_node
    V->>V: 检查工具/参数/类型/依赖
    V-->>G: validation_errors
    
    alt 验证通过
        G-->>API: plan_json
    else 验证失败且重试<2
        G->>G: retry_count += 1
        G->>G: 注入错误信息
        G->>Plan: 重新生成
        Note over G,Plan: 循环直到通过或达上限
    else 重试达上限
        G->>Plan: fallback规则引擎
    end
```

## Core Components

| 模块 | 文件 | 职责 |
|------|------|------|
| 工作流 | cad_graph.py | LangGraph图定义 |
| 节点 | nodes.py | parse/plan/validate |
| 验证器 | validators.py | Plan结构验证 |

## Key Changes

- cad_graph.py: 定义工作流图
- 自动重试机制 (最多2次)
- 错误信息注入 (帮助LLM修正)
- validators.py: Plan验证逻辑

## Next Version

[V0.6 工具扩充](./v06-architecture.md) → [V0.7 闭环 Agent](./v07-architecture.md)
