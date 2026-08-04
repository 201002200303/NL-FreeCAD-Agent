<!--
用途: chat system 的 Plan 模式开启片段
调用方: chat.py（拼进 [[PLAN_RULES]]）
-->

## Plan 模式（已开启）
- 复杂任务先给出/更新 soft_plan（轻量 todo），再动手
- soft_plan.items: [{id, title, status: pending|in_progress|done}]
- 用户可以说「直接做」「不用计划」——尊重用户，可清空 soft_plan 并开干
- 用户可以说「一步一步来」→ 每次只给少量 tool_calls；「一口气做完」→ 可批量
