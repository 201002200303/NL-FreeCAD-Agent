# 已知技术债

> 只记录**当前仍未解决**的问题。已修复项见下方"已还清"表，避免读者被过时清单误导。
> 最近更新：2026-09-11（F1–F9 与 L5 验证完成后）。

## 未解决

| ID | 严重度 | 问题 | 影响 | 相关代码 |
|----|--------|------|------|---------|
| TD-PHASE-4 | P2 | 同一轮里出现多个 `execute_cad_program` 时，`reduce_phase_feedback` 只归约**最后一个**回执（`relevant[-1]`） | 模型若在一轮里发多个阶段程序，只有最后一个会进入 Phase State；其余执行了但不入账 | `app/phase_program/orchestrator.py` |
| TD-PLAN-1 | P2 | 阶段归属不一致：`gate=passed` 时 `soft_plan` 仍可能显示部分阶段 pending | 纯显示问题，几何与导出均正常，但会误导 GUI 用户对进度的判断 | `workflow/chat.py`、soft_plan 归约 |
| TD-VISION-1 | P2 | 视觉 `warn → 自动修码` 闭环未在 GUI 手动验证 | 无头驱动只能验到"裁决"这一步；闭环行为缺证据 | `app/vision/service.py`、`panel.py` |
| TD-BBOX-1 | P3 | `Shape.BoundBox` 对曲面近似，旧接口仍存在于少数路径 | 已由 `geometry_facts.exact_bbox`（优先 `optimalBoundingBox()`）在多数路径解决，但未全量替换 | `document_state.py` |
| TD-CI-1 | P3 | 无 CI | 回归靠本地 `pytest` + FreeCADCmd 门禁，无法在提交时自动拦截 | 仓库无 `.github/` |
| TD-ORACLE-1 | P3 | 几何 Oracle 覆盖面仍有缺口 | 新增 `cad.*` API 时若不补 L3/L4 用例，就会重演"sweep/wedge 无 Oracle 只能下线"的局面 | `freecad_addon/AICADAgent/tests/geometry_oracle/cases.py` |

## 已还清（保留记录，便于追溯）

| 原 ID | 问题 | 由谁修 |
|-------|------|--------|
| TD-PHASE-1 | 空 `phase_state` 时模型可未执行就标全阶段 done | F1 —— 宿主计划成为权威，`done` 收尾需 `phase_status == passed` |
| TD-PHASE-2 | 只锁 status、不锁 `acceptance` / `phase_id`，失败后可放宽验收绕过 | F2 —— `lock_acceptance` 冻结进 Phase State，只允许追加 |
| TD-PHASE-3 | 握手完成前合法执行可能被误拒 | F5 —— 执行门改 `is False`（未知即放行）+ 退避重试 |
| — | 工具层缺对照官方 Placement / 默认轴的几何 Oracle | F3 —— L3/L4 Oracle 建成（19/0），并因此抓到 `Shape.BoundBox` 曲面偏差（D13） |
| — | 整机装配被隐含要求"必须 fuse 成一体"，与三处机制互斥 | F9 —— 新增 `cad.compound`，导出支持多目标 |
| — | 提示词与配方对"阵列 vs 直算坐标"自相矛盾 | F6 —— `chat_core.md` 成为唯一规则源 |
| — | `cad.fuse([a,b,c])` 报底层错误、第三个操作数被静默丢弃 | F7 —— 布尔支持 N 操作数并给可操作错误 |

完整审查与整改过程见 [quality_review_action_plan.md](./quality_review_action_plan.md)（D1–D15 → F1–F9）。

## 验收与回归门禁

改动后先跑 L0–L4，再决定是否重跑 L5：

```powershell
# L0–L1：无 FreeCAD
cd agent_service ; F:\ANACONDA\python.exe -m pytest -q        # 246 passed

# L2–L4：FreeCADCmd
& 'D:\freecad\bin\freecadcmd.exe' -c "import runpy; runpy.run_path(r'<repo>\freecad_addon\AICADAgent\tests\geometry_oracle\runner.py', run_name='__main__')"
```

流程与判据见 [tool_validation_pipeline.md](./tool_validation_pipeline.md) 与 [agent_eval_playbook.md](./agent_eval_playbook.md)。
