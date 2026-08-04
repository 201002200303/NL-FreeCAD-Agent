# 提示词（当前主路径）

日常改建模风格只动这里。旧闭环提示词已迁到
`agent_service/archive/legacy_closed_loop/prompts/`。

## 怎么改

1. 打开对应 `.md`，顶部 `<!-- ... -->` 是用途说明（不进模型）。
2. `[[NAME]]` 是运行时注入点，不要改错名字。
3. JSON 示例用普通 `{` / `}`。

## 文件索引

| 文件 | 何时用 |
|------|--------|
| `chat_system.md` | `POST /agent/chat` 系统提示（**主文件**） |
| `chat_plan_on.md` / `chat_plan_off.md` | Plan 模式开关片段 |
| `chat_vision_on.md` / `chat_vision_off.md` | 视觉开关文案 |
| `compress.md` | 历史压缩 |
| `vision.md` | 视口截图评估 |
| `design_brief.md` | 用户原文 brief 片段 |

## 调用方

- `app/workflow/chat.py`
- `app/design/brief.py`
- `app/vision/service.py`
