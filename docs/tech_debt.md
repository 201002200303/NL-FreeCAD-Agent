# 已知技术债（暂缓）

> 不阻塞当前主线开发；修之前先看优先级。记录日期：2026-08-06。

## Phase 宿主门闩（review 发现，暂缓）

来源：Phase Program 纵向改造后的 code review。

| ID | 严重度 | 摘要 |
|----|--------|------|
| TD-PHASE-1 | P1 | 空 `phase_state={}` 时 `reconcile_soft_plan` 不锁定 status，模型可未执行就标全阶段 done |
| TD-PHASE-2 | P1 | 只锁 status、不锁 `acceptance` / phase_id；失败后可改松验收或换阶段名绕过 |
| TD-PHASE-3 | P2 | capabilities 握手完成前 `_cad_api_compatible is None`，合法执行可能被误拒 |
| TD-PHASE-4 | P2 | 同轮多个 `execute_cad_program` 只归约最后一次回执 |

相关代码：`app/phase_program/orchestrator.py`、`agent_runner.py`（握手）、ADR-0001。

## 工具几何 Oracle

流程见 [`tool_validation_pipeline.md`](./tool_validation_pipeline.md)。现状：L0/L1/L2 有雏形；L3/L4 几何期望用例尚未系统化。
