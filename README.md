# NL-FreeCAD-Agent

自然语言驱动的 FreeCAD 特征树建模 Agent（Windows）。

**当前主路径：Phase Program Code Mode** — Agent 自主规划语义阶段并输出受限 `cad.*` 程序；宿主负责程序身份、单事务执行、确定性验收、State Diff 和阶段推进。

| 想了解… | 文档 |
|---------|------|
| **一次请求怎么走（行号级）** | **[docs/request_walkthrough.md](docs/request_walkthrough.md)** ← 掌控入口 |
| 当前开发主线 | [docs/development_mainline.md](docs/development_mainline.md) |
| **工具能否用（校验流水线）** | **[docs/tool_validation_pipeline.md](docs/tool_validation_pipeline.md)** |
| Code Mode 约定与闭环 | [docs/code_mode.md](docs/code_mode.md) |
| 已知技术债 | [docs/tech_debt.md](docs/tech_debt.md) |
| 提示词文件 | [agent_service/app/prompts/README.md](agent_service/app/prompts/README.md) |
| 架构演进（含归档） | [docs/architecture/README.md](docs/architecture/README.md) |

---

## 一句话

用户描述意图 → Agent 规划语义阶段 → 返回 Phase Program → 宿主预检并在 FreeCAD 单事务执行 → 确定性验收与 State Diff → 通过后推进、失败只修当前阶段 → 可选多视图 VLM 补充语义检查。

底层仍有完整 `TOOL_REGISTRY`（约 53 个），但**不再把完整 schema 塞进主模型上下文**；模型通过 `cad.box` / `cad.polar_pattern` 等薄 API 间接调用。

---

## 系统架构

```
┌──────────────────────────────────────────────────┐
│                   FreeCAD GUI                     │
│  Panel → AgentRunner → Executor → TOOL_REGISTRY  │
│          cad_program.runtime / viewport / memory │
└───────────────────────┬──────────────────────────┘
                        │ HTTP 127.0.0.1:8765
                        │ POST /agent/chat
┌───────────────────────▼──────────────────────────┐
│              Agent Service (FastAPI)              │
│  workflow/chat → prompts + transcript → LLM      │
│  cad_program/validate  vision/  memory/  runtime/│
└──────────────────────────────────────────────────┘
```

- **服务端**：推理、prompt、AST 预检、会话 transcript、视觉评估  
- **插件端**：GUI、真实 CAD 执行、文档状态、截图、客户端 session_memory  
- **旧 Plan/LangGraph 闭环**：`agent_service/archive/legacy_closed_loop/`（非主路径）

---

## 核心设计

1. **Code Mode**：模型写受限 Python（`cad.*`），不是自由 FreeCAD 脚本，也不是日常挑选 53 个 tool schema。  
2. **三层工具**：`cad.*`（L1）→ `cad_program` 映射（L2）→ `TOOL_REGISTRY` 实现（L3）。详见走读文档 §7。  
3. **双进程**：Agent 不碰 FreeCAD GUI；插件不做 LLM。  
4. **人工在环**：可对话澄清、停手、改指示；视觉 warn 默认问用户而非空转修码。
5. **Agent 规划、宿主治理**：soft_plan 可动态调整；Phase State 只能由程序回执和确定性验收推进。

---

## 项目目录（活跃）

```
NL-FreeCAD-Agent/
├── docs/
│   ├── request_walkthrough.md   # 请求级数据流（推荐先读）
│   ├── code_mode.md
│   └── architecture/            # 历史版本；V0.10 = Code Mode
├── agent_service/
│   ├── app/
│   │   ├── main.py              # FastAPI：/agent/chat 等
│   │   ├── workflow/chat.py     # 对话主循环
│   │   ├── cad_program/         # AST 校验 + runtime 规则（与插件同步）
│   │   ├── prompts/             # chat_core / plan / vision …
│   │   ├── llm/                 # OpenAI-compatible
│   │   ├── vision/              # 多视图评估 + 修订预算
│   │   ├── memory/              # 服务端 memory 格式化
│   │   ├── conversation/        # transcript
│   │   ├── tools/tool_specs.py  # 53 工具契约（对齐/测试，非主 prompt）
│   │   └── runtime/             # 会话事件（可选）
│   ├── archive/                 # 旧闭环（勿当主路径）
│   └── test_*.py
├── freecad_addon/AICADAgent/
│   ├── panel.py / chat_ui.py
│   ├── agent_runner.py          # 客户端 chat loop
│   ├── executor.py              # 事务执行
│   ├── cad_program/             # 与服务端同规则 runtime
│   ├── cad_tools/               # TOOL_REGISTRY 真实实现
│   ├── session_memory.py
│   ├── document_state.py
│   └── viewport.py
└── scripts/                     # verify_spec_alignment 等
```

---

## Windows 环境准备

### 1. FreeCAD

推荐 FreeCAD 0.21+ / 1.0+。[下载](https://www.freecad.org/downloads.php)。

### 2. Python（Agent 服务）

```powershell
cd agent_service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# 配置 .env：OPENAI_API_KEY / OPENAI_BASE_URL / LLM_MODEL 等
```

### 3. 安装插件

```powershell
# 开发推荐：符号链接（可能需管理员）
mklink /D %APPDATA%\FreeCAD\Mod\AICADAgent D:\project_main\NL-FreeCAD-Agent\freecad_addon\AICADAgent
```

或 `xcopy` 复制到 `%APPDATA%\FreeCAD\Mod\AICADAgent`。重启 FreeCAD 后选 Workbench **AI CAD Agent**。

### 4. 启动服务

```powershell
cd agent_service
.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

- Health: http://127.0.0.1:8765/health  
- Swagger: http://127.0.0.1:8765/docs  

---

## 主 API

### `POST /agent/chat`

对话式建模主入口。请求体见 `app/schemas/request.py`（`ChatRequest`）。

典型字段：`session_id`、`message`、`document_state`、`tool_results`、`session_memory`、`soft_plan`、`vision_memory`、`plan_mode`、`vision_enabled`。

响应（`ChatResponse`）：`status`（`awaiting_tools` / `awaiting_user` / `done` / `error`）、`message`、`tool_calls`、`soft_plan`、`vision`、`vision_memory` 等。

### 其它

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/agent/capabilities` | 视觉是否可用、plan 默认等 |
| POST | `/agent/compress` | 压缩会话 transcript |

旧 `/agent/plan` 等闭环 API 已不在主路径（见 archive）。

---

## 模型侧 tool_calls（主路径）

```json
{
  "message": "创建 100×60×20 底板并四角打孔",
  "tool_calls": [
    {
      "tool": "execute_cad_program",
      "args": {
        "transaction": "base_plate",
        "code": "plate = cad.box(name=\"BasePlate\", size=(100, 60, 20), center=(0, 0, 10))\n"
      },
      "description": "创建底板"
    }
  ],
  "status": "awaiting_tools",
  "soft_plan": { "items": [], "key_dims": { "unit": "mm" } }
}
```

视觉开启时可另发 `capture_views`。约定详见 `docs/code_mode.md` 与 `prompts/chat_core.md`。

---

## 错误与回滚

| 场景 | 处理 |
|------|------|
| AST 非法 | 服务端 `prefilter` 标 `blocked`，客户端不执行 |
| 执行异常 | 插件 `abortTransaction`，回传 `error_type` / `failed_line` |
| 服务不可达 | 面板报错 |
| 视觉 bad | 预算内可自动修码；warn → 问用户 |

---

## License

MIT
