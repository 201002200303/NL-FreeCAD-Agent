# Code Mode（当前主路径）

> 状态：已落地最小闭环（2026-08-04）。53 个底层工具仍保留在 FreeCAD 执行器内，不再作为主模型日常 schema。  
> **请求级走读（文件/行号/提示词）**：[request_walkthrough.md](./request_walkthrough.md)

## 一句话

模型输出受限 Python（`cad.*`）→ 服务端 AST 校验 → 客户端单事务执行 → 失败结构化回灌修码；成功后可选多视图 VLM 一次修订。

## 闭环

```text
用户消息
  → LLM：message + tool_calls[execute_cad_program{code}]
  → 服务端 prefilter（validate_cad_source）
  → 客户端 CadAPIRuntime + TOOL_REGISTRY，单 openTransaction
  → 失败：error_type / error_message / failed_line → 下一轮修码
  → 成功：模型可 `capture_views` 选角；未拍则客户端补拍 front/side/top/iso → VLM
  → 空文档不评估；仅 bad + 阶段预算未满才自动修；warn 问用户
```

## 模块

| 位置 | 职责 |
|------|------|
| `agent_service/app/cad_program/validate.py` | AST 白名单（禁 import/逃逸/while/def；限节点与 cad 调用数） |
| `agent_service/app/cad_program/runtime.py` | `cad.*` → TOOL_REGISTRY；同名创建先删再建；`cad.delete` 支持列表且缺失跳过 |
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
