# Phase Program Code Mode（当前主路径）

核心分工：Agent 自主规划建模路径和语义阶段；宿主维护 Phase State，负责程序身份、事务、幂等、确定性 Acceptance、State Diff 与阶段提交。Soft Plan 只用于规划和展示，不能绕过宿主门闩。

```text
Agent 提议 soft_plan / 当前阶段程序
  → 宿主附加 phase_id + program_hash + execution_key + acceptance
  → 服务端预检
  → FreeCAD 单事务执行
  → Program Receipt（产出 + State Diff）
  → 宿主确定性 Acceptance
  → PASS：提交并推进下一阶段
  → FAIL：保持当前阶段，只回灌失败事实供局部修复
```

> 状态：已落地 Phase Program 主线（2026-08-06）。53 个底层工具仍保留在 FreeCAD 执行器内，不再作为主模型日常 schema。
> **请求级走读（文件/行号/提示词）**：[request_walkthrough.md](./request_walkthrough.md)

## 一句话

模型自主规划语义阶段并输出受限 Python（`cad.*`）→ 宿主生成程序身份并预检 → 客户端单事务执行 → 确定性验收决定阶段推进或局部修复；视觉只补充语义检查。

## 闭环

```text
用户消息
  → LLM：message + tool_calls[execute_cad_program{code}]
  → 服务端 prefilter（validate_cad_source）
  → 客户端 CadAPIRuntime + TOOL_REGISTRY，单 openTransaction
  → Program Receipt：program_hash / execution_key / State Diff
  → 确定性 Acceptance：对象、Shape、Solid、bbox、体积等
  → 失败：error_type / failed_line / checks → 当前阶段修码
  → 通过：宿主提交当前阶段并推进 Soft Plan
  → 成功：模型可 `capture_views` 选角；未拍则客户端补拍 front/side/top/iso → VLM
  → 空文档不评估；仅 bad + 阶段预算未满才自动修；warn 问用户
```

## 模块

| 位置 | 职责 |
|------|------|
| `agent_service/app/cad_program/validate.py` | AST 白名单（禁 import/逃逸/while/def；限节点与 cad 调用数） |
| `agent_service/app/cad_program/manifest.py` | 模型可见操作的唯一目录与版本 |
| `agent_service/app/cad_program/runtime.py` | `cad.*` → TOOL_REGISTRY；同名创建先删再建；`cad.delete` 支持列表且缺失跳过 |
| `agent_service/app/phase_program/` | Phase State reducer、确定性 Acceptance、宿主门闩 |
| `agent_service/app/vision/memory.py` | `vision_memory` 阶段验收与修订预算 |
| `agent_service/app/workflow/chat.py` | Code Mode prompt；空文档跳过视觉；预算门控 |
| `agent_service/app/prompts/chat_core.md` | 最小宪法（先理解再 code；阵列用 pattern；重建先删） |
| `freecad_addon/.../cad_program/` | 与服务端同规则（UTF-8 同步；勿用 PowerShell Set-Content） |
| `freecad_addon/.../executor.py` | `execute_cad_program` / `capture_views` 分支 |
| `freecad_addon/.../viewport.py` | `capture_views`；模型截图优先、未拍补拍 |

## cad.* 约定（模型侧）

- 几何：`cad.box(name=..., size=(L,W,H), center=(x,y,z))`；`cad.cylinder(..., center=..., rot_x/y/z=...)`
- **朝向**：圆柱默认轴 +Z（无 rot = 平放）。侧轮 `rot_y=90`（轴沿 X）；轴沿 Y 用 `rot_x=±90`；`cad.hole` 侧壁孔必须 `axis=X|Y`
- **主体优先**：`cad.sketch` → `cad.polyline/rect/circle` → `cad.extrude`；多截面用 `cad.loft`；禁止旋转实体拼主体外形
- 布尔：`cad.fuse(a, b)` / `cad.cut(a, b)`（操作数可传多个或名字列表）
- **整机装配**：`cad.compound([a, b, c], name="Mecha")` —— 不布尔、不删源件；**不要**对整机逐个 `fuse`
  （fuse 会删源件，后续阶段验收找不到中间件）；装配阶段验收别用 `solid_count == 1`
- 导出：`cad.export_step(target=..., filepath=...)`；省略 `target` 导出整个文档，也可传名字列表
- **圆周/直线均布必须用阵列**（禁止 `for` + `cad.rotate` 布齿）：
  - `cad.polar_pattern(tooth, count=12, fuse=True, fuse_name="ToothRing")`
  - `cad.linear_pattern(bar, count=4, offset=(12,0,0), fuse=True, fuse_name="BarRow")`
- `args.code` 绝不能为空

建模样例/装配写法：见 [cad_modeling_recipes.md](./cad_modeling_recipes.md)（接触堆叠、起落架、桨叶、四旋翼）。

## 校验边界（重要）

| 层 | 有 | 无 |
|----|----|----|
| AST + runtime | 语法/沙箱、循环与操作预算 | 精确 CAD 几何关系 |
| 执行 | 事务、回滚、程序幂等、State Diff | 跨重启持久化 Program Receipt |
| 确定性 Acceptance | 对象、Shape、Solid、bbox、体积、对象数 | 精确同轴/共面/曲面间距 |
| 视觉 | 多视图 VLM（可关；失败跳过） | 精确尺寸证明 |

精确贴合、同轴、共面和草图闭合仍需后续只读 FreeCAD Query Adapter；不能用视觉替代。

## Trace

debug 开启时步骤预分类：`code_gen` / `code_repair` / `tool_feedback` / `vision_revise`（meta 写 `step_kind`）。

## 测试

- 服务端：`test_cad_program_validate` / `test_cad_runtime` / `test_cad_pattern_api` / `test_cad_standard_samples` / `test_chat_code_*` / `test_cad_vision_loop`
- FreeCADCmd：`freecad_addon/AICADAgent/tests/test_cad_program_samples.py`
