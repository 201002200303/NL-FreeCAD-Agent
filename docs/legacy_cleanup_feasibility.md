# 旧架构清理可行性评估

日期：2026-08-04  
范围：chat-first 主路径已稳定后，旧闭环与冗余代码可否删除。

## 结论摘要

| 目标 | 可行性 | 建议 |
|------|--------|------|
| 客户端删旧闭环（`start_plan`/`next_step`/`evaluate`） | **高** | 优先做；约可砍 `agent_runner.py` 一半 |
| 服务端删 `archive/legacy_closed_loop/` | **中** | 可删，但先确认不再需要对照；git 历史已保留 |
| 精简 `runtime` / `memory` 旧字段 | **中低** | 第二阶段；与 pause/resume、session 快照耦合 |
| 删 `.qoder` / 调试产物 / 本地测试文件 | **高** | 勿提交；保持 gitignore |

**推荐顺序**：先提交当前工作区检查点 → 再删客户端死代码 → 再视需要删 archive / 瘦 runtime。

---

## 1. 已确认事实

### Live 主路径（保留）

- FreeCAD：`send_chat` → `_post_chat` → `/agent/chat` → 工具执行 → 回灌
- 服务端：`app/main.py` 仅暴露 chat / compress / capabilities / session / log_execution
- 旧 API 已不在 live `main.py`

### 旧闭环现状

- 服务端实现：已迁至 `agent_service/archive/legacy_closed_loop/`（`2c4e2c9`）
- 客户端：`agent_runner.py` 仍含完整旧状态机，Panel **不再调用**
- Panel 将 `plan_generated` / `step_completed` 接成空操作

### 调用关系（客户端）

| 符号 | Panel/UI 调用？ | 仅 runner 内部？ | 服务端仍存在？ |
|------|----------------|------------------|----------------|
| `start_plan` | 否 | 自引用 | 否（已归档） |
| `execute_next_step` | 否 | pause/resume/restore 会调 | 否 |
| `_request_evaluation` | 否 | 旧步完成后 | 否 |
| `AgentSession` | 否 | restore/pause 旧路径 | 部分 session API 仍活 |
| `ChatSession` + `send_chat` | **是** | 主路径 | **是** |

---

## 2. 分阶段删除方案

### Phase A — 客户端死代码（推荐立刻做，风险低）

**可删 / 可移出 `AgentRunner`：**

- `AgentSession` 整类（若 pause/resume 一并改为 chat-only）
- `start_plan` / `_on_start_plan_completed`
- `execute_next_step` / `_on_next_step_completed`
- `_request_evaluation` / `_on_evaluate_completed`
- 旧信号：`plan_generated` / `step_completed` / `evaluation_completed` / `phase_changed`
- 依赖旧 API 的 auto_mode 步进逻辑

**需一并改的耦合点（否则删了会断）：**

- `pause` / `resume` / `restore_session` 当前重建 `AgentSession` 并 `execute_next_step`
  - 选项 A1：暂停功能暂标 deprecated，chat 路径只保留 `stop` + 排队
  - 选项 A2：pause/resume 改为只挂起 `_chat_busy` / HTTP，不碰旧 session
- `_log_tool_execution` 里用 `self.session.session_id` → 应改为 `self.chat.session_id`

**预期收益：** `agent_runner.py` 从 ~1250 行降到 ~500–700 行；主路径一眼可见。

**风险：** 低。旧服务端路由已不存在，旧客户端路径本身已无法跑通。

### Phase B — archive 目录（可选）

- `agent_service/archive/legacy_closed_loop/` 整树可删
- 优点：仓库更干净
- 代价：失去「不查 git 就能对照」的便利；`2c4e2c9` / 更早 commit 仍可恢复
- 建议：Phase A 合并稳定后再删；或保留 README + 删 packages/tests

### Phase C — 服务端半旧模块（谨慎）

仍被 chat/session 间接使用，**不要整包删**：

| 模块 | 用途 | 处理 |
|------|------|------|
| `app/runtime/*` | session pause/resume/list、事件 | 保留；可去掉 `record_next_step` 等死 API |
| `app/memory/pack_builder.py` | execution_history → memory fallback | chat 主要用客户端 SessionMemory；可标 deprecated |
| `app/memory/geometry_facts.py` | 几何事实 / query 覆盖 | chat 上下文仍可能用 |
| `app/schemas/session.py` 里 `HighLevelPlan` | 旧模型 | 可迁 archive 或删，需查 import |
| `app/debug/replay_trace.py` 对 next_step 分支 | 调试 | 可删旧分支 |

### Phase D — 明确不要提交的噪音

- `.qoder/`、`debug_sessions/`、`*.db`、`.env`、本地 `prompts_test_robot*`、`test.py`
- 这些与架构清理无关，提交检查点时排除

---

## 3. 「不必要架构」判断

| 项 | 是否不必要 | 说明 |
|----|------------|------|
| 旧三段式客户端 | **是** | API 已死，UI 已切 chat |
| archive 快照 | 非运行时必要 | 文档/考古价值；可后删 |
| soft_plan | **否** | chat plan_mode 在用 |
| SessionMemory / name_map | **否** | 回灌上下文依赖 |
| runtime session | **部分必要** | pause/list 若产品还要则保留 |
| 全量工具表注入 | 性能债，非死代码 | 属优化，不是删除项 |
| HTTPWorker | **否** | chat 仍用 |

---

## 4. 建议落地顺序

1. **本提交**：把当前 chat 修复/提示词/工具改动推到 `origin/dev`（清理前检查点）
2. **下一 PR**：Phase A — 拆/删 `agent_runner` 旧闭环，pause 改为 chat-safe
3. **再下一 PR**（可选）：删 archive 或只留 README；清 runtime 死方法
4. 不做「大爆炸」单 PR 同时删客户端 + archive + runtime

---

## 5. 验收标准（Phase A）

- Panel 发消息 → 多轮 tool_calls → done/awaiting_user 正常
- `stop` / 排队插话仍可用
- 无对 `/agent/start_plan|next_step|evaluate_step` 的引用
- `rg "AgentSession|start_plan|execute_next_step" freecad_addon` 仅剩文档或零命中
- 相关 pytest / smoke 不依赖旧路径
