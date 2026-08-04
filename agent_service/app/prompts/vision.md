<!--
用途: 多模态视觉评估（看 FreeCAD 视口截图）
调用方: app/vision/service.py → _build_prompt
占位符:
  [[USER_GOAL_BLOCK]]  — 可选「用户目标: ...」整行块（可空）
  [[PHASE_BLOCK]]      — 可选「当前阶段: ...」
  [[FOCUS_BLOCK]]      — 可选「特别关注: ...」
修改提示: 改「关注哪些视觉问题 / JSON 字段」时编辑本文件。
-->

请检查这张 FreeCAD 视口截图中的模型整体造型是否合理。
关注：左右是否对称、前后朝向是否符合常识、部件是否明显悬空/穿模、比例是否离谱、是否像一堆未贴合的方块。
不要编造精确尺寸；看不到的细节说不确定。

返回 JSON: {"verdict":"ok|warn|bad","summary":"...","issues":["..."],"suggestions":["..."]}
[[USER_GOAL_BLOCK]][[PHASE_BLOCK]][[FOCUS_BLOCK]]
