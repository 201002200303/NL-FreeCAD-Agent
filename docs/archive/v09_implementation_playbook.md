# V0.9 架构升级实施手册（可执行版）

> **归档文档**：本文记录的是已被取代的历史方案，不是当前实现依据。
> 当前主线见 [development_mainline.md](../development_mainline.md) / [code_mode.md](../code_mode.md)；归档清单见 [README.md](./README.md)。


> 历史说明：本文曾是 V0.9 的执行依据，现已归档为路线演进记录。当前唯一执行依据见 [development_mainline.md](../development_mainline.md)。
> 按顺序执行，每完成一个阶段跑一次对应测试，通过后再进下一阶段。
> 基线：`0ca25ae`（dev 分支）。运行环境：Windows / PowerShell / Python 3.12。

---

## 0. 总体目标

把项目从「每轮全量回传状态的 prompt-driven agent」升级为「事件溯源 + checkpoint 可恢复 + 感知驱动」的 CAD coding agent。对齐 Cursor/Codex 式工作流：

```
粗计划(只排顺序) → 单步观察 → 缺事实先 query → 小步执行(幂等) → 硬验收 → repair/continue
                     ↑ 全程 event log + checkpoint，可暂停/恢复/崩溃续跑 ↑
```

---

## 1. 已完成部分（本轮已落地，无需重做）

### 1.1 服务端 Runtime 生命周期（agent_service）

| 文件 | 内容 |
|---|---|
| `app/runtime/diff.py` | **新建**。`compact_objects()` 把 document_state 压成对象指纹列表（name/type/visible/size/center/pos）；`diff_documents(before, after)` 返回 `{changed, added, removed, modified, summary}` |
| `app/runtime/reducer.py` | **新建**。`reduce_events(base_run_state, events)`：在 checkpoint 快照之上重放事件重建 RunState（completed_action_ids / pending_action_ids / unresolved_errors / completed_steps / current_phase_id / status） |
| `app/runtime/store.py` | 新增 `list_sessions(limit)` 和 `action_ids_with_event(session_id, event_type)`（幂等查询） |
| `app/runtime/service.py` | 新增 `pause_session()`（写 USER_PAUSED 事件 + checkpoint 存暂停时文档快照 `paused_document_objects`）；`resume_session()`（重放 checkpoint 后事件 → diff 检测用户手工改模 → 写 DOCUMENT_CHANGED_BY_USER + USER_RESUMED → 返回 run_state + document_changes）；`get_session_snapshot()`（恢复视图）；`list_sessions()`；`completed_action_ids()`。`build_context_slice` 新增 `user_document_changes` 字段 |
| `app/runtime/context.py` | `_format_runtime_slice` 输出「用户在暂停期间手工修改了文档」段落，注入 LLM |
| `app/schemas/request.py` | 新增 `PauseSessionRequest` / `ResumeSessionRequest` |
| `app/schemas/response.py` | 新增 `SessionSnapshotResponse` / `SessionListResponse` / `PauseSessionResponse` / `ResumeSessionResponse` |
| `app/main.py` | 新增 4 个端点：`GET /agent/sessions`、`GET /agent/session/{id}`、`POST /agent/session/{id}/pause`、`POST /agent/session/{id}/resume` |

### 1.2 FreeCAD 端可靠性（freecad_addon/AICADAgent）

| 文件 | 内容 |
|---|---|
| `executor.py` | **幂等**：`_completed_call_ids` + `_completed_results`；重复 call_id 直接返回缓存结果并标 `skipped_duplicate=True`（只对 act 工具去重，query 可重跑）；`seed_completed_call_ids()` 供恢复时灌入服务端已成功的 action_ids；`has_executed()` |
| `agent_runner.py` | `HTTPWorker` 支持 GET；新增信号 `session_restored` / `paused_state_changed`；批量执行时收集 `_last_batch_results`；**evaluate 载荷改进**：优先送第一个失败的 call（而非盲目取 history[-1]），多 call 批次附 `batch_summary`；**repair 闭环修复**：repair calls 执行后回到 `_request_evaluation` 而不是直接 next_step，且更新 `_last_tool_call` / `_before_step_state` |
| `session_memory.py` | 新增 `restore_from_pack(pack)`：从 checkpoint 里存的 memory pack 重建记忆 |

### 1.3 更早已完成（前几轮）

- `query_policy.py` 批内感知（同批 create→boolean 不再误杀）+ `test_query_policy.py` 12 项
- bbox 感知修复（document_state 多级回退、geometry_facts 归一化、covers 需 size+center）
- runtime 事件日志 + checkpoint 基础（`test_runtime.py`）
- 粗计划 prompt 只排顺序+角色

---

## 2. 剩余任务（按顺序执行）

### 阶段 A：暂停/恢复接线（FreeCAD 端）— ✅ 已完成

**目标**：暂停不再只是内存布尔；FreeCAD 重启后能恢复会话继续建模。

#### A1. `agent_runner.py` — pause/resume 持久化

改 `pause()`：
```python
def pause(self):
    self.paused = True
    self.paused_state_changed.emit(True)
    self.log_message.emit("⏸ 已暂停（状态已保存到服务端）")
    if self.session:
        try:
            doc_state = get_document_state()
        except Exception:
            doc_state = None
        payload = {"document_state": doc_state, "reason": "user_pause"}
        self._lifecycle_worker = HTTPWorker(
            f"/agent/session/{self.session.session_id}/pause", payload)
        self._lifecycle_worker.start()   # fire-and-forget
```

改 `resume()`：
```python
def resume(self):
    if not self.paused:
        return
    if not self.session:
        self.paused = False
        return
    doc_state = get_document_state()
    self._lifecycle_worker = HTTPWorker(
        f"/agent/session/{self.session.session_id}/resume",
        {"document_state": doc_state})
    self._lifecycle_worker.request_completed.connect(self._on_resume_completed)
    self._lifecycle_worker.request_failed.connect(lambda e: self._continue_after_resume())
    self._lifecycle_worker.start()

def _on_resume_completed(self, result: dict):
    changes = result.get("document_changes")
    if changes and changes.get("changed"):
        self.log_message.emit(f"⚠ 检测到暂停期间文档被手工修改: {changes.get('summary')}")
        # 让记忆同步最新文档，LLM 下一轮会从 runtime context 读到变化事件
        try:
            self.session.refresh_memory_from_document(get_document_state())
        except Exception:
            pass
    self._continue_after_resume()

def _continue_after_resume(self):
    self.paused = False
    self.paused_state_changed.emit(False)
    self.log_message.emit("▶ 继续执行...")
    if self.auto_mode:
        self.execute_next_step()
```

#### A2. `agent_runner.py` — 会话恢复 `restore_session`

新增方法（FreeCAD 重启后从服务端恢复）：
```python
def restore_session(self, session_id: str):
    """GET /agent/session/{id} → 重建 AgentSession + executor 幂等种子。"""
    self._restore_worker = HTTPWorker(f"/agent/session/{session_id}", method="GET")
    self._restore_worker.request_completed.connect(self._on_restore_completed)
    self._restore_worker.request_failed.connect(self._on_request_failed)
    self._restore_worker.start()

def _on_restore_completed(self, result: dict):
    if result.get("status") != "ok":
        self.error_occurred.emit(f"恢复失败: {result.get('message')}")
        return
    run_state = result.get("run_state") or {}
    plan = run_state.get("high_level_plan") or {}
    plan.setdefault("session_id", result.get("session_id"))
    self.session = AgentSession(
        user_input=result.get("user_input") or "", high_level_plan=plan)
    self.session.session_id = result.get("session_id")
    self.session.abstract_step_queue = run_state.get("abstract_step_queue")
    self.session.current_abstract_step = run_state.get("current_abstract_step")
    self.session.current_phase_id = run_state.get("current_phase_id") or self.session.current_phase_id
    self.session.name_map = run_state.get("name_map") or {}
    self.session.memory.restore_from_pack(run_state.get("session_memory"))
    self.executor = CadToolExecutor()
    self.executor.name_map = dict(self.session.name_map)
    self.executor.seed_completed_call_ids(result.get("completed_action_ids"))
    try:
        self.session.refresh_memory_from_document(get_document_state())
    except Exception:
        pass
    self.log_message.emit(f"✓ 会话已恢复: {self.session.session_id}")
    self.session_restored.emit(result)
```

注意：恢复后要触发一次 resume 端点（带当前 document_state），让服务端做用户改模 diff。可在 `_on_restore_completed` 末尾直接调 `self.resume()` 前先 `self.paused = True`。

#### A3. `panel.py` — UI 接线

1. **暂停按钮变为暂停/继续切换**：
   - 连接 `paused_state_changed` 信号；paused=True 时按钮文本改「继续」，点击调 `_runner.resume`；paused=False 时改回「暂停」。
2. **新增「恢复会话」按钮**（放在「生成计划」旁）：
   - 点击 → `HTTPWorker("/agent/sessions", method="GET")` 拉取会话列表 → 用 `QtGui.QInputDialog.getItem` 让用户选一个 status 为 paused/running 的 session → 调 `_runner.restore_session(session_id)`。
   - 连接 `session_restored` 信号 → 复用 `_on_plan_generated` 的逻辑填充计划树（run_state.high_level_plan 里有 phases/queue）。

**验收 A**（手动，FreeCAD 内）：
1. 开始建模 → 自动执行中点暂停 → 在 FreeCAD 里手动添加一个 Box → 点继续 → 日志必须出现「检测到暂停期间文档被手工修改: 新增 Box」，且下一轮 LLM trace 的 prompt 里有该段落。
2. 暂停后完全关闭 FreeCAD → 重开 → 点「恢复会话」→ 选中会话 → 计划树恢复、阶段正确、继续单步能接着做。
3. 服务端验收（无 FreeCAD 也可测）：见阶段 F 的 `test_lifecycle.py`。

---

### 阶段 B：相对定位工具（消灭坐标瞎猜）— ✅ 已完成

**目标**：新增 3 个工具，让 LLM 用「相对关系」而不是绝对坐标放置对象。

#### B1. FreeCAD 端 `freecad_addon/AICADAgent/cad_tools/placement_tools.py`（新建）

三个工具（全部纯函数 `func(doc, **args) -> dict`，复用 `_helpers.get_object`）：

1. **`align_objects(doc, target, reference, axis, mode, offset=0)`**
   - axis: `"x"|"y"|"z"`；mode: `"min"|"center"|"max"|"stack"`（stack = target 的 min 贴 reference 的 max，即「放在上面/旁边」）
   - 实现：取两者 world bbox（`Shape.BoundBox`，参考 `query_tools` 的取法），算 target 在该轴需要平移的 delta，改 `Placement.Base`。
   - 返回 `{"object": target, "moved_by": [dx,dy,dz], "kind": "act"}`。

2. **`place_relative(doc, target, reference, anchor, dx=0, dy=0, dz=0)`**
   - anchor: `"center"|"top"|"bottom"|"left"|"right"|"front"|"back"`（reference bbox 上的锚点）
   - 把 target 的 bbox 中心移到 reference 锚点 + (dx,dy,dz)。

3. **`distribute_along(doc, targets, axis, spacing)`**
   - targets: 逗号分隔对象名；沿 axis 以等间距排列（首个不动）。

#### B2. 注册与 spec

- `cad_tools/__init__.py`：TOOL_REGISTRY 注册 3 个（49→52）。
- `agent_service/app/tools/tool_specs.py`：加 3 个 spec（描述里写明「优先于 set_placement/move 使用，避免猜绝对坐标」）。
- `agent_service/app/tools/tool_registry.py`：加入 `transform` 类。
- `query_policy.py`：`align_objects`/`place_relative` 加入 `RISKY_TOOLS`，`QUERY_BY_TOOL` 映射到 `get_object_detail`。

#### B3. Prompt 引导

`llm_provider.py` 的 `_build_next_step_prompt` 空间定位规则里加一条：
「涉及贴合/对齐/堆叠时优先 align_objects / place_relative，不要手算坐标再 set_placement」。

**验收 B**：
- `test_tool_registry.py` 更新工具数断言（49→52，同时修掉 `freecad_addon/AICADAgent/tests/test_v06_freecad_tools.py` 里过期的 `== 22` 断言）。
- FreeCAD 手测脚本 `freecad_addon/AICADAgent/tests/test_placement_tools.py`：建两个 box → `align_objects` stack 后验证 target.zmin == reference.zmax（容差 1e-6）；`place_relative` 后验证中心点；`distribute_along` 验证间距。

---

### 阶段 C：硬几何验收扩展 — ✅ 已完成

**目标**：evaluate 能确定性地发现「悬空、穿模、没接地、尺寸不对」。

#### C1. `agent_service/app/evaluation/validators.py` 新增 4 个

已有 12 个（exists/shape_valid/bbox_close/attachment_gap/orientation 等）。新增：

1. **`verify_grounded(after_state, tool_call, ...)`**：target bbox 的 zmin 距 0 平面 ≤ tol（默认 1.0mm）。expected_effect 里 `{"validators": ["verify_grounded"]}` 时启用。
2. **`verify_no_overlap(a, b)`**：两对象 bbox 重叠体积 / 较小者体积 ≤ 30%（bbox 级近似，不做布尔）。失败给 repair_hint（沿最小重叠轴移开的距离）。
3. **`verify_touching(a, b, axis)`**：`measure_gap` 逻辑复用，gap ≤ tol 才通过，失败给出带符号 delta 的 repair_hint（对应 move 的参数）。
4. **`verify_size_close(target, expected_size, tol_ratio=0.15)`**：bbox size 与期望尺寸误差 ≤ 15%。

全部返回统一结构：`{validator, passed, error_code, message, expected, actual, delta, repair_hint}`。

#### C2. 接线

- `validators.py` 的 `VALIDATOR_REGISTRY`（或对应分发 dict）注册 4 个名字。
- `llm_provider.py` next_step prompt 的 expected_effect 说明中列出可用 validator 名，让 LLM 在生成 tool_call 时可以声明 `expected_effect.validators`。
- 默认仍是 warning 不阻断（遵循 development_plan 的轻验证原则）；strict 模式下阻断（`harness.py` 已有 strict_validation 通道）。

**验收 C**：`agent_service/test_validators_v09.py`（新建，纯 dict fixture 不需要 FreeCAD）：
- 悬空 box（zmin=5）→ verify_grounded 失败且 delta=5；
- 两个重叠 box → verify_no_overlap 失败且 repair_hint 方向正确；
- 相距 3mm 的两 box → verify_touching 失败，repair_hint 的 move 距离=3；
- size [100,60,20] vs 期望 [100,60,40] → verify_size_close 失败。

---

### 阶段 D：建模知识库（modeling_knowledge）— ✅ 已完成

**目标**：粗计划和单步规划能检索到建模范式，而不是纯靠模型临场发挥。

#### D1. 目录结构

```
agent_service/app/modeling_knowledge/
├── __init__.py
├── retrieval.py          # 关键词检索：match_knowledge(user_input, intent) -> list[dict]
└── patterns/
    ├── vehicle.md        # 车类：部件顺序（车身→轮→轴→细节）、比例（轮径≈车长1/4）、
    │                     #   轮子必须 rot_x=90、四轮对称用 mirror、贴地 zmin=0
    ├── enclosure.md      # 壳体类：外壳→抽壳/pocket→开孔→圆角；壁厚 2-3mm
    ├── bracket.md        # 支架类：底板→立板→加强筋→孔位
    └── coordinate_conventions.md  # Z 向上、cylinder 默认轴 Z、sketch 平面选择规则
```

每个 pattern 文件头部放 YAML front-matter：`keywords: [car, 车, vehicle, 小车]`，正文 ≤ 40 行，只写**范式与比例**，禁止具体坐标。

#### D2. `retrieval.py`

```python
def match_knowledge(text: str, limit: int = 2) -> list[dict]:
    """关键词命中 → [{"pattern_id", "content"}]，无命中返回 []"""
```
实现：遍历 patterns/*.md，解析 front-matter keywords，对 text 做大小写不敏感的包含匹配，按命中词数排序取前 limit。

#### D3. 注入

- `llm_provider._build_high_level_plan_prompt`：命中 pattern 时追加「## 建模参考（仅指导顺序与比例）」段。
- `_build_next_step_prompt`：当前 phase intent 命中时注入（同样最多 2 个、每个截断 1500 字符）。
- trace 里记录 matched pattern_id（写进 debug trace 的 meta）。

**验收 D**：`agent_service/test_knowledge.py`：
- "做一个小车" 命中 vehicle；"做个盒子外壳" 命中 enclosure；"画个圆" 不命中；
- mock 验证 start_plan prompt 包含「建模参考」段。

---

### 阶段 E：面板 UX 完善（在阶段 A 的 UI 改动之上）— ✅ 已完成

1. **ask_user 闭环**：`_on_evaluate_completed`/next_step 返回 `ask_user` 时，面板弹出输入区（或复用建模需求输入框 + 「回答并继续」按钮），把回答追加到 `session.user_input`（格式：`原需求\n[用户补充] 回答`），然后 `execute_next_step()`。
2. **进度条以 queue 完成数驱动**（已有 `_update_progress`，确认 evaluate 响应里的 queue steps status 被同步）。
3. **会话状态行**加显示 checkpoint_id 和「事件数」（从 resume/restore 响应取），方便观察持久化在工作。

**验收 E**：FreeCAD 手动：ask_user 场景能回答并继续；恢复会话后进度条正确。

---

### 阶段 F：测试与回归 — ✅ 单测已完成（golden case 仍需人工）

#### F1. 服务端单测（无 FreeCAD 依赖，pytest 直接跑）

新建 `agent_service/test_lifecycle.py`：
```
- test_pause_writes_event_and_checkpoint:
    start_session → pause_session(带 doc) → 事件里有 USER_PAUSED，checkpoint.status=paused，
    run_state 里有 paused_document_objects
- test_resume_detects_user_changes:
    pause 时 doc 有 [A]，resume 时 doc 有 [A, B] → 返回 document_changes.added=[B]，
    事件里有 DOCUMENT_CHANGED_BY_USER + USER_RESUMED
- test_resume_replays_post_checkpoint_events:
    checkpoint 后手动 append TOOL_SUCCEEDED(action_id=X) → resume 后
    run_state.completed_action_ids 含 X
- test_reducer_rebuilds_state: 直接测 reduce_events 的各事件分支
- test_diff_documents: added/removed/modified(position/size/visibility) 各一例
- test_session_snapshot_and_list: get_session_snapshot / list_sessions
```

新建 `agent_service/test_validators_v09.py`（见阶段 C）、`test_knowledge.py`（见阶段 D）。

#### F2. 回归命令

```powershell
cd d:\project_main\NL-FreeCAD-Agent\agent_service
python -m pytest test_query_policy.py test_geometry_facts.py test_runtime.py `
  test_lifecycle.py test_validators_v09.py test_knowledge.py `
  test_tool_registry.py test_pipeline.py test_v08_harness.py -q
```
全部通过为准（当前基线 40 passed + 新增）。

#### F3. FreeCAD 真机 golden case（人工，最后做一次）

1. 启动服务：`agent_service> .venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8765`
2. FreeCAD 输入「做一个简单的小车，四个轮子要贴合车身且接地」→ 自动执行。
3. 检查清单：
   - [ ] 粗计划只有角色顺序，无坐标/工具名
   - [ ] 轮子创建前有 query（trace 可见）
   - [ ] 有 align_objects / place_relative 调用（而非纯 set_placement 猜坐标）
   - [ ] validator 结果里能看到 grounded / touching 检查
   - [ ] 中途暂停→手工加个 box→继续，LLM prompt 里出现用户改模段落
   - [ ] 重启 FreeCAD 恢复会话可继续

---

## 3. 执行顺序与依赖

```
阶段 A（暂停/恢复接线）        ← 服务端已就绪，只差客户端两个文件
   ↓
阶段 B（相对定位工具）         ← 独立，可与 C 并行
阶段 C（硬验收）               ← 独立，可与 B 并行
   ↓
阶段 D（知识库）               ← 独立
阶段 E（面板 UX）              ← 依赖 A
   ↓
阶段 F（测试回归 + golden case）
```

## 4. 每阶段完成后必做

1. `python -m pytest <相关测试> -q` 通过；
2. `ReadLints` 无新错误；
3. 在 `dev_log.md` 顶部追加一条简短记录（现象/改动/测试结论，≤6 行）；
4. 不要提交 git（等用户确认后统一提交）。

## 5. 风险与注意事项

- **executor 与 session 双 name_map**：恢复会话时必须同时灌两处（见 A2 代码），否则旧名解析断链。
- **EvaluateStepRequest 的 execution_result 是自由 dict**：`batch_summary` 不需要改 pydantic schema，但 evaluate 的 LLM prompt 若要利用它，需在 `llm_provider.evaluate_step_with_llm` 的 user message 里透传（已透传整个 execution_result 的就不用动，需确认）。
- **pause 的 HTTP 是 fire-and-forget**：网络失败时暂停仍生效（本地布尔），只是服务端少一个事件，可接受。
- **知识库禁止写死坐标**：pattern 只给顺序、比例、朝向约定，否则会重蹈 recipe 固化覆盖 LLM 队列的老 bug。
- **Windows 控制台编码**：测试脚本避免打印 emoji（此前踩过 GBK 编码坑）。