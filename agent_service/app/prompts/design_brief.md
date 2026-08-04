<!--
用途: 「用户原文最高优先级」片段，注入 chat system
调用方: app/design/brief.py → format_design_brief
占位符:
  [[BRIEF_TEXT]] — 截断后的用户原文
  [[GOAL_LINE]]  — 可选「（目标摘要：...）」整行，可空
-->

## 原始需求（用户原文，最高优先级）
具体尺寸、坐标系、对称关系与外观要求一律以本节为准；
与 soft_plan 或你的假设冲突时，以本节为准。不要重新发明这里已经写死的数值。
未写明的尺寸可在 message 中声明合理工程假设，并记入 soft_plan.key_dims。

[[BRIEF_TEXT]]
[[GOAL_LINE]]
