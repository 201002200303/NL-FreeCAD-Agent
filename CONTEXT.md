# Domain Context

## Purpose

NL-FreeCAD-Agent 是一个自然语言驱动的 FreeCAD 建模 Agent。模型负责理解设计意图和选择建模路径；宿主负责保证路径可执行、可验证、可回退。

## Core concepts

### Semantic Phase（语义阶段）

复杂建模任务中的一个有明确目标的工作阶段，例如“建立主体”“添加孔槽”“创建阵列”或“完成倒角”。阶段描述建模意图，不展开成底层工具步骤。

### Soft Plan（软计划）

由 Agent 提议并可动态调整的语义阶段列表，用于规划和 UI 展示。Soft Plan 不是执行控制的事实来源；阶段是否完成由宿主的 Phase State 决定。

### Phase Program（阶段程序）

Agent 为当前语义阶段生成的一段受限 `cad.*` 程序。一个 Phase Program 在一次事务中执行，并携带宿主生成的程序身份和结构化 Acceptance。

### Phase State（阶段状态）

宿主管理的当前阶段事实，包括阶段身份、执行状态、尝试次数、程序身份、执行差异和 Acceptance 结果。模型可以建议计划，但不能直接写入或伪造 Phase State。

### Acceptance（确定性验收）

宿主根据 FreeCAD 文档事实执行的结构化检查，例如对象存在、Shape 有效、实体数量、包围盒尺寸和体积范围。视觉检查补充外观与语义判断，但不能替代确定性 Acceptance。

### Program Receipt（程序回执）

Phase Program 执行后由 FreeCAD Adapter 返回的事实记录，包括程序哈希、执行身份、产出对象、State Diff、检查和错误。它用于幂等、防止重复副作用和阶段推进。

### State Diff（状态差异）

Phase Program 执行前后文档状态的紧凑差异，包括新增、删除和发生尺寸、位置、可见性或类型变化的对象。

## Invariants

- Agent 决定怎么建；宿主决定一次阶段执行是否可以提交。
- Soft Plan 可以变化，Phase State 只能由宿主依据执行回执和 Acceptance 更新。
- 一个 Phase Program 对应一个语义阶段和一次事务。
- 阶段失败只修复当前阶段，不应重做已提交阶段。
- 相同执行身份和相同程序不得重复产生副作用。
- 几何事实来自 FreeCAD 文档状态或只读查询，而不是模型猜测。

## Known gaps（暂缓）

当前仍未解决的问题集中在 [docs/tech_debt.md](docs/tech_debt.md)：

- 同一轮出现多个 Phase Program 时，只归约最后一个回执（`TD-PHASE-4`）。
- `gate=passed` 时 soft_plan 的阶段显示归属不一致（`TD-PLAN-1`，纯显示问题）。
- 视觉 `warn → 自动修码` 闭环未在 GUI 手动验证（`TD-VISION-1`）。

已解决的问题（宿主门闩 TD-PHASE-1/2/3、工具层几何 Oracle）见 `tech_debt.md` 的"已还清"表。

