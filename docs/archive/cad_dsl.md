# CAD DSL — Plan and Tool JSON Format

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


## 概述

Agent 不生成 FreeCAD Python 代码，而是生成结构化的 JSON Plan。Plan 中的每个步骤调用一个 CAD Tool。这种格式就是 NL-FreeCAD-Agent 的 CAD DSL。

## Plan 格式

### 顶层结构

```json
{
  "status": "ok | need_more_info",
  "goal": "一句话描述建模目标",
  "assumptions": ["假设1", "假设2"],
  "missing_params": ["参数名1", "参数名2"],
  "question": "当 status=need_more_info 时，向用户的澄清提问",
  "plan": [ ... ]
}
```

### PlanStep 结构

```json
{
  "step_id": "S1",
  "description": "人类可读的步骤描述",
  "tool": "create_box",
  "args": {
    "name": "BaseBlock",
    "length": 100,
    "width": 60,
    "height": 20,
    "unit": "mm"
  },
  "depends_on": [],
  "expected_result": {
    "object": "BaseBlock",
    "type": "Part::Box"
  }
}
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| step_id | string | 是 | 唯一标识，格式 S1, S2, ... |
| description | string | 是 | 人类可读描述 |
| tool | string | 是 | CAD Tool 名称，必须在 Tool Registry 中注册 |
| args | object | 是 | Tool 参数，必须符合 Tool Spec |
| depends_on | string[] | 否 | 依赖的前置 step_id |
| expected_result | object | 否 | 预期创建/修改的对象 |

### depends_on 语义

- 空列表：无依赖，可以最先执行
- 包含 step_id：必须等待依赖步骤完成后才能执行
- Executor 会按拓扑顺序执行步骤
- 如果依赖步骤失败，当前步骤会跳过

## 状态枚举

### Plan Status

| 值 | 说明 |
|----|------|
| ok | Plan 生成成功，可以执行 |
| need_more_info | 参数不足，需要用户补充信息 |

## 示例

### 完整 Plan：带安装孔的底板

```json
{
  "status": "ok",
  "goal": "创建一个带倒角的底板",
  "assumptions": ["单位 mm", "孔距边缘 10mm"],
  "missing_params": [],
  "question": null,
  "plan": [
    {
      "step_id": "S1",
      "description": "创建底板基体",
      "tool": "create_box",
      "args": {
        "name": "BasePlate", "length": 100, "width": 60, "height": 10, "unit": "mm"
      },
      "depends_on": [],
      "expected_result": { "object": "BasePlate", "type": "Part::Box" }
    },
    {
      "step_id": "S2",
      "description": "在四角添加安装孔",
      "tool": "cut_corner_holes",
      "args": {
        "target": "BasePlate", "hole_diameter": 5, "margin_x": 10, "margin_y": 10, "through_all": true
      },
      "depends_on": ["S1"],
      "expected_result": { "object": "BasePlate", "type": "Part::Cut" }
    },
    {
      "step_id": "S3",
      "description": "在外边添加倒角",
      "tool": "add_fillet",
      "args": {
        "target": "BasePlate", "radius": 3, "edge_selector": "outer_edges"
      },
      "depends_on": ["S2"],
      "expected_result": { "object": "BasePlate", "type": "Part::Fillet" }
    }
  ]
}
```

## Tool 参数类型

| JSON 类型 | 说明 | 示例 |
|-----------|------|------|
| string | 字符串 | `"mm"`, `"BasePlate"` |
| float | 浮点数 | `100.0`, `3.14` |
| int | 整数 | `4`, `10` |
| bool | 布尔值 | `true`, `false` |
| enum | 枚举字符串 | `"XY"`, `"XZ"`, `"YZ"` |