# NL-FreeCAD-Agent

自然语言驱动的 FreeCAD 特征树建模 Agent。

---

## 项目简介

NL-FreeCAD-Agent 是一个 Windows 原生工具，允许用户使用自然语言操控 FreeCAD 的特征树进行参数化建模。它不是一个端到端的 STL 生成器，而是一个**受控的 CAD Tool 编排系统**：用户描述建模意图 → Agent 生成可解释的多步骤建模计划 → FreeCAD 插件在当前文档中逐步执行 CAD Tool → 特征树实时反映变更。

## 项目背景

FreeCAD 是一个强大的开源参数化 CAD 平台，但其操作门槛较高。用户需要理解 Part、PartDesign、Sketch、约束系统等概念才能高效建模。另一方面，LLM 直接生成 FreeCAD Python 代码存在严重问题：

- **不可控**：LLM 生成的脚本可能包含错误 API 调用、遗漏 `doc.recompute()`、破坏现有模型。
- **不可解释**：用户无法理解 LLM "为什么"选择某个操作序列。
- **不可交互**：脚本一次性执行，用户无法中途干预或修改单个步骤。
- **不可撤销**：执行失败后难以回滚到安全状态。

NL-FreeCAD-Agent 通过引入 **CAD Tool** 抽象层和 **Plan** 中间表示解决上述问题。

## 项目目标

- 用户用自然语言描述建模需求
- Agent 生成结构化的、可审计的多步骤建模计划（Plan）
- FreeCAD 插件按照 Plan 逐步执行受控 CAD Tool
- 特征树实时新增、修改、删除对象
- 用户可随时手动修改模型，也可继续用自然语言调整
- 支持导出 STEP / STL

## 核心设计理念

### 1. CAD Tool 而非 FreeCAD Python 代码

LLM 不直接生成 FreeCAD Python 脚本。LLM 只输出 JSON 格式的 CAD Tool 调用。每个 CAD Tool 是预定义的、经过测试的 FreeCAD 操作封装。这保证了：

- **安全性**：Tool 内部做参数校验、边界检查、错误处理。
- **可控性**：每个 Tool 的输出可预测。
- **可组合性**：Tool 可以被编排、重排、回滚。

### 2. Plan 中间表示

Plan 是自然语言与 CAD 操作之间的中间表示。它是 JSON 格式的步骤序列，每个步骤包含：

- `step_id`：步骤唯一标识
- `tool`：CAD Tool 名称
- `args`：参数
- `depends_on`：依赖的前置步骤
- `expected_result`：预期结果

Plan 可被审计、修改、重放、持久化。

### 3. 双进程架构

系统分为两个独立进程：

- **Agent 服务端（FastAPI）**：负责计划生成和决策，运行在普通 Python 环境。
- **FreeCAD 插件端**：负责 CAD 操作执行，运行在 FreeCAD GUI 进程内。

两者通过 HTTP（127.0.0.1）通信。Agent 服务不直接操作 FreeCAD GUI，FreeCAD 插件不承担 LLM 推理。

### 4. 人工在环

用户始终处于建模循环中。Plan 生成后展示给用户确认；每个步骤执行后用户可以检查、撤销或手动调整模型。

## 系统架构

```
┌──────────────────────────────────────────────────┐
│                   FreeCAD GUI                     │
│  ┌────────────────────────────────────────────┐  │
│  │          AICADAgent Workbench              │  │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────┐  │  │
│  │  │  Panel   │  │ Executor │  │ DocState│  │  │
│  │  │ (PySide) │  │          │  │         │  │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬────┘  │  │
│  │       │             │             │        │  │
│  │       │    HTTP POST to /agent/plan        │  │
│  │       │             │                      │  │
│  └───────┼─────────────┼──────────────────────┘  │
│          │             │                          │
│          │    FreeCAD Document API                │
│          │    (Part, Sketcher, Mesh, ...)         │
└──────────┼─────────────┼──────────────────────────┘
           │             │
           │   HTTP (127.0.0.1:8765)
           │             │
┌──────────┼─────────────┼──────────────────────────┐
│          ▼             ▼                          │
│           Agent Service (FastAPI)                 │
│  ┌────────────────────────────────────────────┐  │
│  │              LangGraph                      │  │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────┐  │  │
│  │  │  Planner │  │ Extractor│  │  Tools  │  │  │
│  │  │  Node    │  │  Node    │  │ Registry│  │  │
│  │  └──────────┘  └──────────┘  └─────────┘  │  │
│  └────────────────────────────────────────────┘  │
│                    │                              │
│              SQLite (调用记录)                     │
└───────────────────────────────────────────────────┘
```

### 通信方式

| 方向 | 协议 | 说明 |
|------|------|------|
| FreeCAD → Agent | HTTP POST | 发送用户输入 + 文档状态，请求建模计划 |
| Agent → FreeCAD | HTTP Response | 返回 Plan JSON |
| 后续扩展 | WebSocket | 实时流式推送步骤执行状态 |

### 数据流

1. 用户在 FreeCAD 面板输入自然语言
2. 插件读取当前文档状态（对象列表、选中对象）
3. 插件向 Agent 服务发送 POST `/agent/plan`
4. Agent 解析输入、生成 Plan、返回 JSON
5. 插件展示 Plan 供用户确认
6. 插件按步骤调用 CAD Tool executor
7. 每个步骤在 FreeCAD 特征树中创建/修改对象
8. 执行结果反馈到面板日志

## MVP 功能范围

### V0.1（当前阶段）

- FreeCAD 插件面板（PySide QTextEdit + QPushButton）
- FastAPI 服务：`GET /health` + `POST /agent/plan`
- 规则/stub 生成建模 Plan
- Pydantic schema 定义
- 项目目录结构

### 后续版本将加入

- FreeCAD 特征树操作（create_box, create_cylinder 等）
- LangGraph 编排 Agent 流程
- LLM structured output 接入
- 多轮对话和修改
- SQLite 调用记录
- 导出 STEP / STL
- 事务回滚和错误恢复

### 当前阶段不做什么

- 不接入真实 LLM
- 不做复杂 Sketcher 约束系统
- 不做 PartDesign 全流程
- 不做 Docker 容器化
- 不做 Web 前端页面
- 不让 LLM 输出任意 Python 代码
- 不让 FastAPI 直接操作 FreeCAD GUI

## 技术栈

| 组件 | 技术 |
|------|------|
| Agent 框架 | LangGraph |
| Web 框架 | FastAPI |
| 数据校验 | Pydantic v2 |
| 数据库 | SQLite + aiosqlite + SQLAlchemy |
| LLM 接口 | OpenAI-compatible API（后续） |
| FreeCAD GUI | PySide (Qt) |
| FreeCAD Python API | FreeCAD 内置 Python 3.11 |
| 进程通信 | HTTP (127.0.0.1)，后续 WebSocket |
| 目标 OS | Windows 10/11 |

## 项目目录结构

```
NL-FreeCAD-Agent/
├── README.md
├── .gitignore
│
├── agent_service/               # Agent 服务端
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── __init__.py
│       ├── main.py              # FastAPI 入口
│       ├── config.py            # 配置管理
│       ├── graph/               # LangGraph 图定义
│       │   ├── __init__.py
│       │   ├── state.py
│       │   ├── nodes.py
│       │   └── cad_graph.py
│       ├── schemas/             # Pydantic schema
│       │   ├── __init__.py
│       │   ├── request.py
│       │   ├── response.py
│       │   ├── cad_plan.py
│       │   ├── cad_tools.py
│       │   └── cad_state.py
│       ├── tools/               # CAD Tool 注册
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   └── tool_specs.py
│       ├── llm/                 # LLM 接口（后续）
│       │   ├── __init__.py
│       │   ├── planner.py
│       │   └── extractor.py
│       └── db/                  # 数据库
│           ├── __init__.py
│           ├── database.py
│           ├── models.py
│           └── repository.py
│
├── freecad_addon/               # FreeCAD 插件
│   └── AICADAgent/
│       ├── Init.py
│       ├── InitGui.py
│       ├── commands.py
│       ├── panel.py
│       ├── executor.py
│       ├── document_state.py
│       ├── cad_tools/
│       │   ├── __init__.py
│       │   ├── primitive_tools.py
│       │   ├── sketch_tools.py
│       │   ├── feature_tools.py
│       │   ├── modify_tools.py
│       │   └── export_tools.py
│       └── resources/
│           └── icons/
│               └── README.md
│
├── examples/
│   ├── sample_plan.json
│   ├── test_requests.json
│   └── prompts.md
│
└── docs/
    ├── architecture.md
    ├── cad_dsl.md
    ├── tool_design.md
    └── development_plan.md
```

## Windows 环境准备

### 1. 安装 FreeCAD

从 [FreeCAD 官网](https://www.freecad.org/downloads.php) 下载 Windows 安装包并安装。

推荐 FreeCAD 0.21+ 或 1.0+。

### 2. 安装 Python

Agent 服务需要独立的 Python 环境（推荐 Python 3.11+）：

```powershell
# 下载安装 Python 3.11+
# https://www.python.org/downloads/
python --version
```

### 3. 安装 Agent 服务依赖

```powershell
cd agent_service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## FreeCAD 插件安装方式

将 `freecad_addon/AICADAgent` 目录复制或符号链接到 FreeCAD Mod 目录：

```powershell
# FreeCAD Mod 目录通常位于:
# %APPDATA%\FreeCAD\Mod\
# 或
# C:\Users\<用户名>\AppData\Roaming\FreeCAD\Mod\

# 方法 1: 直接复制
xcopy /E /I freecad_addon\AICADAgent %APPDATA%\FreeCAD\Mod\AICADAgent

# 方法 2: 符号链接（开发推荐，需要管理员权限）
mklink /D %APPDATA%\FreeCAD\Mod\AICADAgent D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent
```

重启 FreeCAD 后，在 Workbench 下拉菜单中可以看到 "AI CAD Agent"。

## Agent 服务启动方式

```powershell
cd agent_service
.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

服务启动后访问：
- Health check: http://127.0.0.1:8765/health
- API docs (Swagger): http://127.0.0.1:8765/docs

## API 设计

### `GET /health`

返回服务健康状态。

**Response:**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### `POST /agent/plan`

根据用户输入和文档状态生成建模计划。

**Request:**
```json
{
  "user_input": "创建一个 100×60×20mm 的底座",
  "document_state": {
    "document_name": "Unnamed",
    "objects": [],
    "selected_objects": []
  }
}
```

**Response (成功):**
```json
{
  "status": "ok",
  "goal": "创建一个长方体底座",
  "assumptions": ["单位默认为 mm"],
  "missing_params": [],
  "question": null,
  "plan": [
    {
      "step_id": "S1",
      "description": "创建长方体底座",
      "tool": "create_box",
      "args": {
        "name": "BaseBlock",
        "length": 100,
        "width": 60,
        "height": 20,
        "unit": "mm"
      },
      "depends_on": [],
      "expected_result": {
        "object": "BaseBlock",
        "type": "Part::Box"
      }
    }
  ]
}
```

**Response (缺参数):**
```json
{
  "status": "need_more_info",
  "goal": "创建一个底板",
  "assumptions": [],
  "missing_params": ["length", "width", "height"],
  "question": "请补充底板的长度、宽度和厚度，默认单位为 mm。",
  "plan": []
}
```

### 后续 API（待实现）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/refine` | 在已有模型基础上修改 |
| POST | `/agent/analyze` | 分析当前文档状态 |
| GET  | `/agent/history` | 查询历史调用记录 |
| WS   | `/agent/ws` | WebSocket 实时通信 |

## 建模计划 Plan 格式

Plan 是一个结构化的 JSON，描述从自然语言需求到 CAD 操作的完整映射。

```json
{
  "status": "ok",
  "goal": "创建一个带四个安装孔和倒角的底板",
  "assumptions": [
    "单位默认为 mm",
    "孔距边缘 10mm"
  ],
  "missing_params": [],
  "plan": [
    {
      "step_id": "S1",
      "description": "创建底板实体",
      "tool": "create_box",
      "args": {
        "name": "BasePlate",
        "length": 100,
        "width": 60,
        "height": 10,
        "unit": "mm"
      },
      "depends_on": [],
      "expected_result": {
        "object": "BasePlate",
        "type": "Part::Box"
      }
    },
    {
      "step_id": "S2",
      "description": "在底板四角创建通孔",
      "tool": "cut_corner_holes",
      "args": {
        "target": "BasePlate",
        "hole_diameter": 5,
        "margin_x": 10,
        "margin_y": 10,
        "through_all": true
      },
      "depends_on": ["S1"],
      "expected_result": {
        "object": "BasePlate",
        "type": "Part::Cut"
      }
    },
    {
      "step_id": "S3",
      "description": "添加外边倒角",
      "tool": "add_fillet",
      "args": {
        "target": "BasePlate",
        "radius": 3,
        "edge_selector": "outer_edges"
      },
      "depends_on": ["S2"],
      "expected_result": {
        "object": "BasePlate",
        "type": "Part::Fillet"
      }
    }
  ]
}
```

### Plan 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `ok` 或 `need_more_info` |
| `goal` | string | 建模目标的一句话描述 |
| `assumptions` | string[] | Agent 所做的假设 |
| `missing_params` | string[] | 缺少的参数名列表 |
| `question` | string\|null | 当 `status` 为 `need_more_info` 时，向用户提问 |
| `plan` | Step[] | 建模步骤序列 |

### Step 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `step_id` | string | 步骤唯一标识，格式 `S1`, `S2`, ... |
| `description` | string | 本步骤的人类可读描述 |
| `tool` | string | CAD Tool 名称 |
| `args` | object | Tool 参数 |
| `depends_on` | string[] | 依赖的前置步骤 step_id 列表 |
| `expected_result` | object | 预期结果描述 |

## CAD Tool 设计

### 工具分层

```
高层语义工具
├── make_base_plate      (底板)
├── add_mounting_holes   (安装孔)
├── add_stiffener        (加强筋)
└── ...

底层 CAD Primitive 工具
├── create_box
├── create_cylinder
├── create_sketch
├── pad_sketch
├── cut_center_hole
├── cut_corner_holes
└── ...

修改管理工具
├── add_fillet
├── add_chamfer
├── modify_param
├── delete_object
└── ...

导出工具
├── export_step
├── export_stl
├── save_fcstd
└── ...
```

### Tool 定义格式

每个 CAD Tool 在 `tool_specs.py` 中以 JSON Schema 形式定义：

```python
TOOL_SPECS = {
    "create_box": {
        "description": "创建一个长方体",
        "parameters": {
            "name": {"type": "string", "description": "对象名称"},
            "length": {"type": "float", "description": "长度 (mm)"},
            "width": {"type": "float", "description": "宽度 (mm)"},
            "height": {"type": "float", "description": "高度 (mm)"},
            "unit": {"type": "string", "default": "mm"}
        },
        "required": ["name", "length", "width", "height"]
    }
}
```

## 错误处理设计

| 错误场景 | 处理方式 |
|----------|----------|
| Agent 服务不可达 | 面板显示连接错误，建议检查服务是否启动 |
| 无法解析用户输入 | 返回 `need_more_info`，引导用户补充信息 |
| CAD Tool 参数无效 | Executor 校验参数，返回明确错误信息 |
| FreeCAD 操作失败 | Executor 捕获异常，`doc.abortTransaction()` 回滚 |
| 步骤依赖未满足 | Executor 检查 `depends_on`，跳过无法执行的步骤 |
| 对象重名 | 自动生成唯一名称或提示用户重命名 |

## 开发路线

| 版本 | 内容 |
|------|------|
| V0.1 | 项目初始化：README、目录结构、FastAPI stub、FreeCAD 面板骨架、Pydantic schema |
| V0.2 | 规则生成建模 plan，插件显示 plan JSON |
| V0.3 | 插件逐步执行 create_box / create_cylinder |
| V0.4 | 引入 LangGraph plan 生成节点 |
| V0.5 | 接入 LLM structured output |
| V0.6 | 多轮修改、文档状态感知、错误恢复、SQLite 记录 |
| V0.7 | 全量 CAD Tool 实现、导出功能 |
| V0.8 | WebSocket 实时通信、流式 plan 生成 |

## 后续扩展方向

- **LLM 接入**：通过 OpenAI-compatible API 接入多种 LLM（GPT-4、Claude、本地模型）。
- **多轮对话**：支持在已有模型基础上增量修改（"把底板的厚度改为 15mm"）。
- **PartDesign 支持**：Body、Sketch、Pad、Pocket、Revolution 等 PartDesign 工作流。
- **约束系统**：Sketcher 几何约束和尺寸约束的自动推理。
- **Assembly 支持**：多零件装配建模。
- **参数化模板**：预定义常用零件模板（齿轮、轴承座、法兰等）。
- **历史回放**：基于 SQLite 记录完整建模历史，支持回放和审计。
- **BOM 生成**：从 FreeCAD 文档自动生成物料清单。

---

## License

MIT
