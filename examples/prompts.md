# Example Prompts — NL-FreeCAD-Agent

This file documents example prompts for testing the Agent at various stages.

## V0.1/V0.2 — Rule-based (Keyword Matching)

Currently supported:
- "创建一个 100×60×20mm 的底座" → create_box plan
- "创建一个 R25 H50 的圆柱体" → create_cylinder plan
- "创建一个草图" → create_sketch plan
- "create a box 50x30x10 mm" → create_box plan

Not yet supported (returns need_more_info):
- Modifications: "把底板的厚度改为 15mm"
- Complex: "创建一个带安装孔的底板"
- Constraints: "创建一个完全约束的矩形草图"

## V0.5+ — LLM-driven (Future)

Expected to support:
- "创建一个 200×150×30mm 的铝板，四角有 M6 沉头孔，孔距边 15mm"
- "在底板上添加一个居中凸台，直径 40mm，高度 10mm"
- "给所有外边缘添加 R5 的倒角"
- "把 BasePlate 的厚度从 20 改为 15"
- "删除 Cylinder001"
- "导出为 STEP 文件到 D:/exports/plate.step"

## Multi-turn Examples (V0.6+)

```
Turn 1 User: "创建一个底板 200×150×30"
Turn 1 Agent: [Plan: create_box BasePlate 200×150×30]

Turn 2 User: "在四角添加 M8 通孔"
Turn 2 Agent: [Plan: cut_corner_holes on BasePlate, d=8, margin=12]

Turn 3 User: "给所有边添加 R3 倒角"
Turn 3 Agent: [Plan: add_fillet on BasePlate, r=3]

Turn 4 User: "加厚到 40mm"
Turn 4 Agent: [Plan: modify_param BasePlate.Height = 40]
```
