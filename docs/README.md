# 文档索引

> 仓库根部的 [README.md](../README.md) 是作品集入口；本页是**文档地图**。
> 想按时间线看"这个项目怎么一步步变成现在这样"，读 [development_path.md](./development_path.md)。

---

## 先读这四篇

| 文档 | 回答什么问题 |
|------|-------------|
| **[request_walkthrough.md](./request_walkthrough.md)** | 一次建模请求从 UI 到 FreeCAD 怎么走？带行号与提示词 |
| **[code_mode.md](./code_mode.md)** | 当前主路径 Phase Program Code Mode 的约定是什么？ |
| **[development_path.md](./development_path.md)** | 开发路径与里程碑：V0.1 → 现在，每步解决了什么 |
| **[architecture/README.md](./architecture/README.md)** | 逐版架构演进（V0.1–V0.7）+ 关键设计决策 |

## 设计与规范

| 文档 | 内容 |
|------|------|
| [tool_design.md](./tool_design.md) | CAD 工具分层设计（L1 `cad.*` → L2 映射 → L3 `TOOL_REGISTRY`） |
| [tool_addition_standard.md](./tool_addition_standard.md) | **新增工具的唯一执行规范**：注册位置、接口、验收清单 |
| [cad_modeling_recipes.md](./cad_modeling_recipes.md) | 建模配方与易错点（装配、阵列、贴合、朝向） |
| [cad_script_writer_prompt.md](./cad_script_writer_prompt.md) | 给外部 LLM 的 `cad.*` 脚本写作规范（可直接粘进 CAD Playground） |
| [adr/0001-agent-plans-host-governs-phase-programs.md](./adr/0001-agent-plans-host-governs-phase-programs.md) | ADR：Agent 规划、宿主治理 Phase Program |
| [code_mode.md](./code_mode.md) | Code Mode 约定与闭环 |

## 质量与验证

本项目对"效果"分五层验证（L1 单测 → L5 端到端），文档如下：

| 文档 | 内容 |
|------|------|
| [tool_validation_pipeline.md](./tool_validation_pipeline.md) | L0–L4 工具校验流水线：几何 Oracle、Placement/朝向实测 |
| **[agent_eval_playbook.md](./agent_eval_playbook.md)** | L5 端到端手册：冻结提示词、判据、基线表、执行纪律 |
| [quality_review_action_plan.md](./quality_review_action_plan.md) | 一次完整质量审查（D1–D15）与整改（F1–F9）的全过程 |
| [tech_debt.md](./tech_debt.md) | 已知技术债与暂缓原因 |

## 样例与素材

| 路径 | 内容 |
|------|------|
| [samples/quad_drone_x.md](./samples/quad_drone_x.md) + [.cad.py](./samples/quad_drone_x.cad.py) | 四旋翼无人机完整建模脚本（多件装配标准写法） |
| [assets/](./assets/) | 界面截图 |

## 历史归档

| 路径 | 内容 |
|------|------|
| [archive/README.md](./archive/README.md) | 归档清单：被取代的架构文档、Plan-as-Script 时代的 API 契约等 |
| [architecture/v01–v07](./architecture/) | 各版本架构快照（历史记录） |
