# Development Mainline

## Product direction

NL-FreeCAD-Agent 的主线是 **Phase Program Code Mode**：Agent 像建模工程师一样自主选择建模路径；宿主像 CAD 编译器和施工监理一样保证每个阶段可执行、可验证、可回退。

```text
用户目标
  → Agent 生成/更新 Soft Plan（语义阶段）
  → Agent 生成当前 Phase Program
  → CAD Program Kernel 预检与预算
  → FreeCAD Adapter 单事务执行
  → Program Receipt（hash / diff / result）
  → deterministic Acceptance
  → Phase State reducer
  → pass: 下一阶段 / fail: 当前阶段局部修复
```

## Control truth

- Soft Plan：Agent 建议与 UI 展示，可动态修改。
- Phase State：宿主控制真相，模型不可直接写入。
- Program Receipt：执行事实，包括程序身份、文档前后指纹和 State Diff。
- Acceptance：基于 FreeCAD 文档事实的确定性检查；视觉只补充外观和语义判断。

## Implemented foundation

- Phase Program 身份：`phase_id + normalized program hash + execution_key`。
- 阶段状态：`awaiting_execution / passed / failed`，含 attempt、checks、diff、error。
- 宿主门闩：失败阶段不能通过模型改写 Soft Plan 跳过。
- 确定性检查：对象存在/缺失、Shape 有效、Solid 数、bbox 尺寸/中心、体积范围、对象数、文档变化。
- Program Receipt：执行前后文档指纹、State Diff、幂等重放判定。
- CAD Program Manifest：validator 和 runtime 从同一操作目录派生，并进行双端版本握手。
- Runtime budgets：循环展开、实际 CAD 调用、布尔调用和执行时间限制。

## Next vertical slices

1. **工具几何 Oracle（优先地基）**：按 [tool_validation_pipeline.md](./tool_validation_pipeline.md) 编排 L0–L4，用 FreeCADCmd 对照官方 Placement/默认轴校验高风险工具。
2. 收紧 Phase 宿主门闩（见 [tech_debt.md](./tech_debt.md) TD-PHASE-*）。
3. 扩展只读 FreeCAD Query Adapter（间距、相交、同轴等）。
4. Typed CAD IR（Phase Program Interface 不变）。
5. 持久化 Program Receipt，重启后幂等仍由文档指纹保护。
4. 建立标准建模评测集，记录首次成功率、阶段修复次数、token、展开操作数和几何有效率。

任何新增工具、提示词或视觉策略都应服务于上述纵向链路，不再建立平行主路径。

