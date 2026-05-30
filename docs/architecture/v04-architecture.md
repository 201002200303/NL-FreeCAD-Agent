# V0.4 Architecture - LLM Integration

## System Architecture Diagram

```mermaid
graph TB
    subgraph FreeCAD插件端
        Panel[面板UI]
        Executor[执行器]
    end
    subgraph Agent服务端-FastAPI
        API[API端点]
        Planner[计划生成器]
        LLM[LLM调用器]
        Fallback[规则引擎回退]
    end
    subgraph 工具模块-cad_tools
        Registry[工具注册表]
        Tools[工具实现]
    end
    Panel -->|POST /agent/plan| API
    API --> Planner
    Planner -->|优先调用| LLM
    Planner -->|失败时回退| Fallback
    LLM -->|OpenAI API| LLMAPI[外部LLM服务]
    API --> Panel
    Panel -->|执行Plan| Executor
    Executor --> Registry
    Registry --> Tools
```

## Workflow

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as FastAPI
    participant Plan as Planner
    participant LLM as LLM调用器
    participant FB as 规则引擎
    
    U->>API: POST /agent/plan
    API->>Plan: generate_plan
    
    alt LLM调用成功
        Plan->>LLM: call_llm(prompt)
        LLM->>LLM: 构建系统提示词+注入工具规范
        LLM-->>Plan: Plan JSON
    else LLM调用失败
        Plan->>FB: fallback_generate
        FB-->>Plan: Plan JSON
    end
    
    Plan-->>API: Plan JSON
    API-->>U: HTTP 200
```

## Core Components

| 模块 | 文件 | 职责 |
|------|------|------|
| LLM调用 | llm_provider.py | OpenAI API封装 |
| 计划生成 | planner.py | LLM优先+规则回退 |
| 提示词 | prompts/system_prompt.md | 系统提示词模板 |

## Key Changes

- llm_provider.py: 封装OpenAI API调用
- planner.py: 改为LLM优先+规则回退
- 系统提示词工程: 注入工具规范
- JSON模式输出: 强制结构化返回

## Next Version

[V0.5 LangGraph工作流](./v05-architecture.md)
