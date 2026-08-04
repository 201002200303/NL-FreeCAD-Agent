# 归档：旧闭环建模链路（V0.7–V0.9）

归档日期：2026-08-04  
原因：主路径改为对话式 `POST /agent/chat`；旧 API / 提示词 / 包不再进生产。

**不要把本目录加回 `app/` 的 pytest 默认收集路径。**  
恢复时参考 `http/main_closed_loop_snapshot.py` 与 `workflow/service_closed_loop.py`。

## 曾暴露的 API（已下线）

- `POST /agent/plan` — legacy 一次性 plan
- `POST /agent/start_plan` / `/next_step` / `/evaluate_step` — 三段式闭环
- `POST /agent/spec` / `/impact_map` / `/select_recipe` — V0.8 旁路

## 目录

| 路径 | 内容 |
|------|------|
| `prompts/` | high_level_plan / next_step / evaluate / legacy_plan / cad_spec |
| `packages/` | abstract_steps, cad_spec, evaluation, inspection, recipes, modeling_knowledge |
| `workflow/service_closed_loop.py` | start_plan / next_step / evaluate_step / legacy_plan |
| `llm/` | planner.py + llm_provider 旧函数快照 |
| `tools/query_policy*.py` | query-before-act 策略（live 已移除；覆盖检查迁入 geometry_facts） |
| `schemas/` | 旧 request/response 快照 |
| `http/` | 含旧路由的 main 快照 |
| `tests/` | 专测旧链路的用例（不随 CI 跑） |

## 当前 live 主路径

- API：`/agent/chat`、`/agent/compress`、`/agent/capabilities`、session lifecycle
- 提示词：`app/prompts/chat_*.md` 等
- 代码：`app/workflow/chat.py`
