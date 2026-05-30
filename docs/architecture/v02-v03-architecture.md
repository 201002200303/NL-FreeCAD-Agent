# V0.2-V0.3 Architecture - End-to-End Flow

## System Architecture Diagram

```mermaid
graph TB
    subgraph FreeCAD插件端
        Panel[面板UI-panel.py]
        DocState[文档状态-document_state.py]
        Executor[执行器-executor.py]
    end
    subgraph Agent服务端-FastAPI
        API[API端点-main.py]
        Planner[规则引擎-planner.py]
        Schemas[数据模型-schemas]
    end
    subgraph 工具模块-cad_tools
        Registry[工具注册表]
        Primitive[基础几何]
        Modify[修改操作]
        Export[导出功能]
    end
    Panel -->|POST /agent/plan| API
    DocState --> Panel
    API --> Planner
    Planner --> Schemas
    Planner --> API
    API --> Panel
    Panel -->|执行Plan| Executor
    Executor --> Registry
    Registry --> Primitive
    Registry --> Modify
    Registry --> Export
```

## Workflow

```mermaid
sequenceDiagram
    participant U as 用户
    participant P as FreeCAD面板
    participant API as FastAPI
    participant R as 规则引擎
    participant E as 执行器
    participant T as 工具模块
    U->>P: 输入自然语言
    P->>P: 收集文档状态
    P->>API: POST /agent/plan
    API->>R: generate_plan
    R-->>API: Plan JSON
    API-->>P: HTTP 200
    P->>U: 显示Plan JSON
    U->>P: 点击执行按钮
    P->>E: 调用executor执行Plan
    loop 遍历Plan步骤
        E->>T: 查找并调用工具函数
        T-->>E: 返回执行结果
        E->>E: 提交事务
    end
    E-->>P: 执行完成
    P->>U: 显示执行结果
```

## Communication Design

### API 通信
- **协议**: HTTP/REST + JSON
- **服务地址**: http://127.0.0.1:8765

### 工具注册表
TOOL_REGISTRY: create_box, create_cylinder, modify_param, delete_object, save_fcstd

## Core Components

| 模块 | 文件 | 职责 |
|------|------|------|
| 插件端 | panel.py | 面板UI + 执行按钮 |
| 插件端 | executor.py | Plan执行 + 事务管理 |
| 工具模块 | cad_tools/ | 工具注册表 + 工具实现 |

## Key Changes

### V0.2: 执行器重构
- executor.py 从单体拆分为调度器
- 引入 TOOL_REGISTRY 注册表机制

### V0.3: 工具模块化
- 创建 cad_tools/ 目录结构
- panel.py 添加执行按钮

## Next Version

[V0.4 LLM集成](./v04-architecture.md)
