# Code Mode（当前主路径）

> 状态：已落地最小闭环（2026-08-04）。53 个底层工具仍保留在 FreeCAD 执行器内，不再作为主模型日常 schema。

## 一句话

模型输出受限 Python（`cad.*`）→ 服务端 AST 校验 → 客户端单事务执行 → 失败结构化回灌修码；成功后可选多视图 VLM 一次修订。

## 闭环

```text
用户消息
  → LLM：message + tool_calls[execute_cad_program{code}]
  → 服务端 prefilter（validate_cad_source）
  → 客户端 CadAPIRuntime + TOOL_REGISTRY，单 openTransaction
  → 失败：error_type / error_message / failed_line → 下一轮修码
  → 成功：可选 front/side/top/iso → VLM；verdict=bad 则一次修订
```

## 模块

| 位置 | 职责 |
|------|------|
| `agent_service/app/cad_program/validate.py` | AST 白名单（禁 import/逃逸/while/def；限节点与 cad 调用数） |
| `agent_service/app/cad_program/runtime.py` | `cad.*` → TOOL_REGISTRY；`size/center`、`fuse(a,b)`、`polar_pattern` 等参数映射 |
| `agent_service/app/workflow/chat.py` | Code Mode prompt；`prefilter_tool_calls`；`classify_chat_step` |
| `agent_service/app/prompts/chat_core.md` | 最小宪法（先理解再 code；阵列用 pattern） |
| `freecad_addon/.../cad_program/` | 与服务端同规则（UTF-8 同步；勿用 PowerShell Set-Content） |
| `freecad_addon/.../executor.py` | `execute_cad_program` 单事务分支 |
| `freecad_addon/.../viewport.py` | `capture_views` 多视图 |

## cad.* 约定（模型侧）

- 几何：`cad.box(name=..., size=(L,W,H), center=(x,y,z))`；`cad.cylinder(..., center=...)`
- 布尔：`cad.fuse(a, b)` / `cad.cut(a, b)`
- **圆周/直线均布必须用阵列**（禁止 `for` + `cad.rotate` 布齿）：
  - `cad.polar_pattern(tooth, count=12, fuse=True, fuse_name="ToothRing")`
  - `cad.linear_pattern(bar, count=4, offset=(12,0,0), fuse=True, fuse_name="BarRow")`
- `args.code` 绝不能为空

## 校验边界（重要）

| 层 | 有 | 无 |
|----|----|----|
| AST | 语法/沙箱 | 几何语义 |
| 执行 | 异常 → 回滚 | 缝隙/悬空门禁 |
| 文档回传 | 每轮 `document_state` + 紧凑 size/center | 工具结果摘要不带完整 bbox |
| 视觉 | 多视图 VLM（可关；失败跳过） | 精确尺寸验证 |

飘逸、该贴合却有缝：当前只要不抛异常即 `success`；需后续加轻量几何后置条件。

## Trace

debug 开启时步骤预分类：`code_gen` / `code_repair` / `tool_feedback` / `vision_revise`（meta 写 `step_kind`）。

## 测试

- 服务端：`test_cad_program_validate` / `test_cad_runtime` / `test_cad_pattern_api` / `test_cad_standard_samples` / `test_chat_code_*` / `test_cad_vision_loop`
- FreeCADCmd：`freecad_addon/AICADAgent/tests/test_cad_program_samples.py`
