# 提示词集中目录（改这里即可）

所有发给模型的**角色/规则/输出格式**正文都在本目录的 `.md` 里。
Python 只负责拼动态片段（工具列表、文档状态、阶段概览等）。

## 怎么改

1. 打开对应 `.md`，文件顶部 `<!-- ... -->` 注释写了用途与占位符说明（不会进模型）。
2. 正文里 `[[NAME]]` 是运行时注入点，**不要删错名字**；可改周围文字。
3. JSON 示例里用普通 `{` / `}`，不要写成 `{{`。
4. 改完无需重启缓存逻辑以外的代码；若进程常驻，可重启 agent_service，或在代码里 `clear_cache()`。

## 文件索引

| 文件 | 何时用 | 主路径？ |
|------|--------|----------|
| `chat_system.md` | `POST /agent/chat` 系统提示 | ✅ 当前 UI 主路径 |
| `chat_plan_on.md` / `chat_plan_off.md` | chat 的 Plan 模式片段 | 拼进 chat_system |
| `chat_vision_on.md` / `chat_vision_off.md` | chat 视觉开关文案 | 拼进 chat_system |
| `compress.md` | `POST /agent/compress` 历史压缩 | 辅助 |
| `vision.md` | 视口截图评估（多模态） | 开关开启时 |
| `design_brief.md` | 用户原文 brief 片段 | chat / next_step / evaluate 共用 |
| `high_level_plan.md` | `start_plan` 高层阶段 | 旧闭环 API |
| `next_step.md` | `next_step` 单步工具调用 | 旧闭环 API |
| `evaluate.md` | `evaluate_step` 结果评估 | 旧闭环 API |
| `legacy_plan.md` | 一次性完整 plan（legacy） | 兼容/测试 |
| `cad_spec.md` | CAD Spec 结构化需求 | 旁路 |

## 调用方代码（一般不用改）

- `app/workflow/chat.py` → chat_system / compress
- `app/llm/llm_provider.py` → high_level / next_step / evaluate / legacy / cad_spec
- `app/design/brief.py` → design_brief
- `app/vision/service.py` → vision

## 占位符约定

统一 `[[UPPER_SNAKE]]`。常见：

- `[[TOOLS]]` — 工具说明（由 registry 生成）
- `[[BRIEF]]` / `[[DESIGN_BRIEF]]` — 需求原文块
- `[[DOC_SECTION]]` — 文档状态
- `[[MEMORY]]` / `[[KNOWLEDGE]]` — 记忆包 / 模式知识
- `[[PHASES]]` / `[[PHASE_TEXT]]` — 阶段概览 / 当前阶段
