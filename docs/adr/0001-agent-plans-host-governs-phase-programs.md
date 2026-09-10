# ADR-0001: Agent plans; host governs Phase Programs

- Status: Accepted
- Date: 2026-08-06

## Context

逐工具调用让建模过程离散并放大上下文；完全自由的长程序又缺少可靠的阶段回滚、幂等和验收。项目曾同时保留 Plan-as-Script、query-driven agent 和 Code Mode 三种叙事，导致实现与文档缺少单一主线。

## Decision

Agent 自主决定模型拆分、建模策略和语义阶段，并为当前阶段生成受限 `cad.*` Phase Program。宿主拥有 Phase State，负责程序身份、预检、预算、单事务执行、Program Receipt、确定性 Acceptance 和阶段推进。

Soft Plan 是建议，不是控制真相。模型不能直接写入 Phase State，也不能通过把 Soft Plan 标记为 done 绕过失败验收。

## Consequences

- 复杂模型按语义阶段提交和局部修复。
- Code Mode 保留模型擅长的代码表达能力。
- FreeCAD 几何事实和确定性检查决定阶段是否通过。
- 未来 Typed CAD IR 位于 Phase Program Interface 后面，不改变 Agent 的工作单元。
- 旧 Plan-as-Script 与 query-driven 文档仅作为历史记录。

