<!--
用途: 多模态视觉评估（看 FreeCAD 视口截图）
调用方: app/vision/service.py → _build_prompt
占位符:
  [[USER_GOAL_BLOCK]]  — 可选「用户目标: ...」整行块（可空）
  [[PHASE_BLOCK]]      — 可选「当前阶段: ...」+ 验收标准
  [[FOCUS_BLOCK]]      — 可选「特别关注: ...」
修改提示: 改「关注哪些视觉问题 / JSON 字段」时编辑本文件。
-->

请检查这些 FreeCAD 多视图截图中的模型是否满足**本阶段验收标准**（若有）。
硬伤（verdict=bad）：明显部件漂移/悬空、大间隙该贴合却分离、严重穿模、缺关键件、严重左右不对称、姿态崩坏。
细节（verdict=warn）：略方块、小倒角缺失、轻微比例别扭、装饰不足——这些应标 warn，不要当 bad。
ok：达到本阶段最低可读造型即可，勿追求最终精模。
不要编造精确尺寸；看不到的细节说不确定；勿重复「已知/已提过的问题」。

返回 JSON: {"verdict":"ok|warn|bad","summary":"...","issues":["..."],"suggestions":["..."]}
[[USER_GOAL_BLOCK]][[PHASE_BLOCK]][[FOCUS_BLOCK]]
