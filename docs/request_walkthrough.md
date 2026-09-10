# 一次建模请求的数据流（掌控地图）

> **当前权威入口**。配合 [code_mode.md](./code_mode.md)、[prompts/README](../agent_service/app/prompts/README.md)。  
> 旧 Plan / LangGraph 路径见 `agent_service/archive/` 与 [architecture/](./architecture/README.md) 历史文档。

示例用户话：`做一个 100×60×20 的底板，四角打孔`

---

## 0. 总览

```text
[FreeCAD GUI]
  panel._on_send
    → agent_runner.send_chat
      → _post_chat  (采 document_state / memory / 可选截图)
        → HTTP POST 127.0.0.1:8765/agent/chat
            → main.chat
              → workflow.chat_turn
                → (可选) vision.assess_views
                → build_chat_system_prompt + _build_pending_user
                → llm.call_llm  (system + transcript 历史 + pending user)
                → prefilter_tool_calls (AST)
            ← ChatResponse { message, tool_calls, soft_plan, phase_state, … }
        → _on_chat_response
          → _execute_chat_tools
            → executor.execute_tool_call
              → execute_cad_program → cad_program.runtime → TOOL_REGISTRY
            → _post_chat(tool_results=…)  ← 回灌，再进服务端
```

双进程边界：**服务端不做 FreeCAD GUI；插件不做 LLM 推理。**

---

## 1. UI 发消息

| 步骤 | 文件 | 行号（约） | 做什么 |
|------|------|-----------|--------|
| 用户点发送 | `freecad_addon/AICADAgent/panel.py` | `_on_send` ~127–135 | 同步 debug/plan/vision 开关，调用 runner |
| 入队 / 开聊 | `freecad_addon/AICADAgent/agent_runner.py` | `send_chat` 326–361 | 建 `ChatSession`、`CadToolExecutor`；忙则排队 |
| 组 HTTP 包 | 同上 | `_post_chat` 422–499 | 采状态 → `HTTPWorker("/agent/chat", payload)` |

**payload 关键字段**（`_post_chat` 468–483）：

| 字段 | 来源 |
|------|------|
| `message` | 用户原文（回灌轮为空字符串） |
| `document_state` | `document_state.get_document_state()` |
| `tool_results` | 本轮刚执行完的工具结果（首轮 `[]`） |
| `session_memory` | `chat.memory.build_pack()`（客户端四层记忆） |
| `name_map` / `soft_plan` / `phase_state` / `vision_memory` / `user_goal` | `ChatSession`；其中 phase_state 是宿主控制真相 |
| `plan_mode` / `vision_enabled` / `debug_mode` | UI 开关 |
| `viewport_images` | 模型 `capture_views` 或客户端补拍 |

---

## 2. HTTP 入口

| 步骤 | 文件 | 行号（约） | 做什么 |
|------|------|-----------|--------|
| 路由 | `agent_service/app/main.py` | `chat` 95–136 | 解析 `ChatRequest`，`asyncio.to_thread(chat_turn, …)` |
| 预分类 | `workflow/chat.py` | `classify_chat_step` 34–62 | `code_gen` / `code_repair` / `tool_feedback` / `vision_revise`（写 debug meta） |
| Schema | `schemas/request.py` / `response.py` | — | 请求/响应 Pydantic |

---

## 3. `chat_turn`：一轮服务端决策

文件：`agent_service/app/workflow/chat.py`，入口 `chat_turn` **65–223**。

### 3.1 可选视觉（有图 + 有几何时）

| 步骤 | 文件 | 行号（约） |
|------|------|-----------|
| 空文档跳过 | `chat.py` 86–134 | `count_visible_objects`；空 → `skipped=empty_document` |
| 多视图评估 | `vision/service.py` `assess_views` ~50 | 用 `prompts/vision.md` |
| 修订预算 | `vision/memory.py` | `should_allow_vision_revise`；仅 bad 且预算未满才自动修 |

首轮「做一个底板」通常文档为空 → **跳过视觉**。

### 3.2 拼上下文 → 调 LLM

```text
system  = build_chat_system_prompt(...)     # chat.py 343–362
pending = _build_pending_user(...)          # chat.py 365–434
messages = transcript.render(system, pending)  # conversation/transcript.py 70–78
result   = call_llm(pending, system, record=False)  # llm/llm_provider.py 223+
```

`call_llm` 在存在 active transcript 时用 **system + 历史回合 + 本轮 pending**（不是只发一句 user）。

### 3.3 出站处理

| 步骤 | 位置 | 做什么 |
|------|------|--------|
| 规范化 | `_normalize_chat_result` + `phase_program` | status / tool_calls / soft_plan；宿主再附加程序身份并归约 phase_state |
| AST 预检 | `prefilter_tool_calls` 226–259 | `validate_cad_source`；失败标 `blocked` |
| 记 transcript | `append_turn(note, assistant_json)` ~209 | 历史用精简 note，避免整份文档快照 |

---

## 4. 提示词怎么拼（System）

`build_chat_system_prompt`（`chat.py` 343–362）：

```text
render("chat_core",
  BRIEF        = format_design_brief(user_goal)   # design/brief.py → design_brief.md
  PLAN_RULES   = chat_plan_on.md 或 chat_plan_off.md
  VISION_RULES = chat_vision_on.md 或 chat_vision_off.md
)
```

| 文件 | 作用 |
|------|------|
| `prompts/chat_core.md` | **最小宪法**：Code Mode 工作方式、`cad.*` 约定、坐标系、朝向、输出 JSON |
| `prompts/chat_plan_on.md` | soft_plan 阶段/验收/门闩 |
| `prompts/chat_vision_on.md` | bad 才自动修、warn 问用户、`capture_views` |
| `prompts/design_brief.md` | 把用户原文收成 brief（`[[BRIEF]]`） |
| `prompts/packs/*.md` | 可选任务包；**主路径默认不注入** |
| `prompts/vision.md` | 仅 VLM 评估用，不进主 chat system |
| `prompts/compress.md` | `/agent/compress` 压缩历史 |

**重要**：主模型 **不再注入 53 工具完整 schema**。建模知识写在 `chat_core` + 每轮 user 里的「朝向速查」。

改风格：先改 `chat_core.md`；见 `prompts/README.md`。

---

## 5. 提示词怎么拼（本轮 User = pending）

`_build_pending_user`（`chat.py` 365–434）按块拼接：

| 顺序 | 块 | 内容来源 |
|------|----|----------|
| 1 | `## 用户消息` | 首轮：用户原文；回灌轮可无 |
| 2 | `## 工具执行结果` | `tool_results`：call_id / tool / status / 错误 |
| 3 | 紧凑文档上下文 | `memory/prompt.py` → `build_compact_document_context`（对象 size/center + **朝向速查**） |
| 4 | `## 当前 soft_plan` + `宿主阶段门闩` | Agent 规划 JSON + 宿主 phase_state/Acceptance/State Diff |
| 5 | vision_memory | `format_vision_memory_for_prompt` |
| 6 | 视觉评估结果 | `format_vision_for_prompt` |
| 7 | `## name_map` | 对象改名链 |
| 8 | 收尾指令 | 「请回复 JSON…」 |

再叠上 **transcript 历史**（`transcript.py` `_trim`：保最早需求 + 近期回合，超预算砍中间）。

---

## 6. 模型输出形态（Tool Function 对外接口）

主路径对模型暴露的不是 53 个 OpenAI function，而是 **JSON 里的 tool_calls**，通常只有：

### A. `execute_cad_program`（建模）

```json
{
  "tool": "execute_cad_program",
  "args": {
    "transaction": "base_plate",
    "code": "plate = cad.box(name=\"BasePlate\", size=(100,60,20), center=(0,0,10))\n..."
  },
  "description": "创建底板"
}
```

服务端：`prefilter` → `cad_program/validate.py` `validate_cad_source`（~222）。  
客户端：`executor._execute_cad_program`（~95–164）→ `run_cad_program`。

### B. `capture_views`（视觉，可选）

```json
{ "tool": "capture_views", "args": { "views": ["front","side","top","iso"] } }
```

`executor._execute_capture_views` → `viewport.capture_views`。

其它 `create_box` 等 **仍可被 runtime 间接调用**，但不应再作为主模型日常选型。

---

## 7. Tool Function 三层架构

```text
┌─────────────────────────────────────────────────────────────┐
│ L1  模型可见薄 API：cad.box / cad.cut / cad.polar_pattern … │
│     约定写在 chat_core.md；执行走 execute_cad_program.code   │
└───────────────────────────┬─────────────────────────────────┘
                            │ _CAD_TO_TOOL 映射
┌───────────────────────────▼─────────────────────────────────┐
│ L2  cad_program runtime                                     │
│     freecad_addon/.../cad_program/runtime.py  (~18–54 映射表)│
│     agent_service/app/cad_program/runtime.py  （镜像，测/预检）│
│     validate.py：AST 白名单（禁 import/while/def…）          │
└───────────────────────────┬─────────────────────────────────┘
                            │ registry[tool_name](doc, **args)
┌───────────────────────────▼─────────────────────────────────┐
│ L3  TOOL_REGISTRY（真实 FreeCAD 实现）                        │
│     freecad_addon/.../cad_tools/__init__.py  TOOL_REGISTRY   │
│     primitive/boolean/feature/transform/sketch/…             │
│     服务端契约镜像：app/tools/tool_specs.py（对齐脚本用）      │
└─────────────────────────────────────────────────────────────┘
```

### 执行路径（示例：`cad.box`）

1. `executor.execute_tool_call`（214+）发现 `tool == execute_cad_program`
2. `_execute_cad_program`：`openTransaction` → `run_cad_program(code, registry=TOOL_REGISTRY)`
3. runtime 把 `cad.box(name=..., size=..., center=...)` 映射为 `create_box(doc, ...)`
4. `cad_tools/primitive_tools.py` `create_box` 调 FreeCAD API
5. 整段成功 → `_commit`；任一步异常 → `_rollback`，回传 `error_type` / `failed_line`

### 直接工具路径（少见）

若 `tool_calls` 里直接出现 `create_box`：`execute_tool_call` 214+ 走 `TOOL_REGISTRY.get` + 单工具事务（幂等 `call_id`）。

### 对齐与漂移

- 规格：`agent_service/app/tools/tool_specs.py` ↔ 实现：`cad_tools/*`
- 校验：`scripts/verify_spec_alignment.py`
- **`cad_program/` 双端各一份**，改一边必须同步另一边（勿用 PowerShell `Set-Content` 破坏 UTF-8）

---

## 8. 客户端执行与回灌

| 步骤 | 文件 | 行号（约） |
|------|------|-----------|
| 收到响应 | `agent_runner._on_chat_response` 509–538 | `awaiting_tools` → 执行 |
| UI 展示 | `_publish_chat_response` 540–585 | soft_plan / vision / message |
| 逐个执行 | `_execute_chat_tools` / `_run_next_chat_tool` 587+ | `QTimer` 让出 UI；`blocked` 不调 FreeCAD |
| 回灌 | 队列空 → `_post_chat(message="", tool_results=results)` ~609 | 再进 `/agent/chat` |

回灌轮：`classify` → `tool_feedback` 或失败则 `code_repair`；pending 里带工具结果 + 新文档状态；模型修码或继续。

---

## 9. 用「底板四角打孔」串一轮

| # | 位置 | 发生的事 |
|---|------|----------|
| 1 | panel 127 | 用户发送 |
| 2 | runner 326→422 | payload：message=原文，doc 空，memory 空 pack |
| 3 | main 95 | `POST /agent/chat` |
| 4 | chat_turn | 无图跳过视觉；system=`chat_core`+plan+vision；pending=用户消息+空文档上下文 |
| 5 | call_llm | 模型返回 JSON：`execute_cad_program` + `cad.box` + `cad.hole`/`polar` 等 |
| 6 | prefilter | AST 通过则下发；失败 `blocked` |
| 7 | runner 530 | `_execute_chat_tools` |
| 8 | executor 95 | 单事务跑完 code；特征树出现对象 |
| 9 | runner 609 | `tool_results` 回灌 |
| 10 | chat_turn | 若开视觉且有几何：可评估；否则确认成功 / soft_plan 更新 / `done` |

修码轮：执行错误 → pending 含 `错误=…`；step_kind=`code_repair`；模型改 `args.code` 再发。

---

## 10. 目录速查（改哪里）

| 想改… | 去哪 |
|-------|------|
| 建模风格 / cad 约定 / 输出 JSON | `app/prompts/chat_core.md` |
| Plan / 视觉开关文案 | `chat_plan_*.md` / `chat_vision_*.md` |
| 拼装逻辑 | `app/workflow/chat.py` |
| AST 沙箱 | `app/cad_program/validate.py`（并同步 addon） |
| `cad.*` → 工具映射 | `*/cad_program/runtime.py`（双端同步） |
| FreeCAD 真实行为 | `freecad_addon/.../cad_tools/*.py` |
| 工具 schema（测试/对齐） | `app/tools/tool_specs.py` |
| 客户端 loop / HTTP | `agent_runner.py` |
| 事务 / 幂等 | `executor.py` |
| 会话历史预算 | `app/conversation/transcript.py` |
| 客户端工作记忆 | `session_memory.py` |
| 服务端 memory 格式化 | `app/memory/prompt.py` |
| HTTP API | `app/main.py` |
| 旧闭环 | `agent_service/archive/legacy_closed_loop/`（勿当主路径） |

---

## 11. 相关文档

| 文档 | 用途 |
|------|------|
| [code_mode.md](./code_mode.md) | Code Mode 闭环与 cad 约定 |
| [architecture/README.md](./architecture/README.md) | 版本演进；V0.10 = 当前 |
| [prompts/README.md](../agent_service/app/prompts/README.md) | 提示词文件索引 |
| [tool_design.md](./tool_design.md) | 底层工具设计（偏 L3） |
