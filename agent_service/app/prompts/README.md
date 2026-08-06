# 提示词（当前主路径 = Code Mode）

日常改建模风格只动这里。旧闭环提示词在
`agent_service/archive/legacy_closed_loop/prompts/`。

## 怎么改

1. 打开对应 `.md`，顶部 `<!-- ... -->` 是用途说明（不进模型）。
2. `[[NAME]]` 是运行时注入点，不要改错名字。
3. JSON 示例用普通 `{` / `}`。
4. **主路径不再注入 53 工具完整 schema**；模型通过 `execute_cad_program` 写受限 `cad.*` 程序；视觉开启时可另调 `capture_views`。
5. `packs/` 为可选任务细则（保留）；主 chat 默认只装 `chat_core` + plan/vision 片段。

## 文件索引

| 文件 | 何时用 |
|------|--------|
| `chat_core.md` | `POST /agent/chat` Code Mode 最小宪法 |
| `packs/*.md` | 可选任务规则包（gear/humanoid/…；主路径默认不注入） |
| `chat_plan_on.md` / `chat_plan_off.md` | Plan 模式开关片段 |
| `chat_vision_on.md` / `chat_vision_off.md` | 视觉开关文案 |
| `compress.md` | 历史压缩 |
| `vision.md` | 多视图视觉评估 |
| `design_brief.md` | 用户原文 brief 片段 |

## 调用方

- `app/workflow/chat.py` → `build_chat_system_prompt`（Core + brief + plan/vision）
- `app/cad_program/` → AST 校验与 `cad.*` 运行时映射
- `app/design/brief.py`
- `app/vision/service.py` → `assess_views`

架构与请求级数据流：

- [`docs/code_mode.md`](../../../docs/code_mode.md) — Code Mode 约定
- [`docs/request_walkthrough.md`](../../../docs/request_walkthrough.md) — 从发消息到执行的文件/行号地图（含本目录如何拼进 system/user）
