# Development Log

## 2026-09-10: 修「LLM 调用失败」——模型脏 JSON + 诊断分支自身崩溃

**现象**: 面板报「LLM 调用失败，请重试或检查 API 配置」。服务端日志显示该轮 **两次尝试都 JSON 解析失败**。

**两个根因（均实测复现）**:

1. **模型脏 JSON**：deepseek-flash 偶发在**合法 JSON 之后再吐一个多余的 `}`**（抓到真实样本，3577 字符，
   解析到 3576 就结束，尾部多一个 `}`；`finish_reason=stop`，**不是截断**）。
   而 `_extract_json_object` 的兜底是「第一个 `{` 到最后一个 `}`」切片 —— 正好把多余的 `}` 包进去，
   于是**必然**解析失败 → 重试同样失败 → 返回 None。
2. **诊断分支自己崩溃**：Windows 控制台是 GBK(cp936)，模型输出含 `↔`(U+2194) 时
   `print(f"... 原始输出: {content[:800]}")` 抛 `UnicodeEncodeError`。
   异常从 `_attempt_llm_call` 逃出，被 `call_llm` 当成「API 调用失败」——真正的解析错误反而被顶掉、原始输出也没了。

**改**:
1. `_extract_json_object` 改用标准库 `json.JSONDecoder().raw_decode`（语义正是「只解析开头那个完整值」），
   容忍尾部多余括号/重复对象/说明文字/前导散文；保留 markdown 围栏与前缀处理。抽出 `_strip_code_fence`。
2. 新增 `app/console.py::harden_console`，把 stdout/stderr 改为 `errors="replace"`（保留原编码，不整屏乱码）；
   在 `app/__init__.py` 导入即生效，覆盖服务端所有 print。**不再让生僻字符把诊断分支打崩**。
3. `_attempt_llm_call` 记录 `finish_reason`；若为 `length` 则错误信息直接点明
   「输出被 max_tokens 截断，请调大 LLM_MAX_TOKENS」，与「模型写坏 JSON」区分开。
   诊断打印改为只输出**尾部 400 字符**（JSON 坏点通常在尾部）。

**验**:
- `test_llm_json_parse.py`（10 项，含真实坏样本形态：尾随 `}` / 连续两个对象 / 前导散文 / 围栏）；
  修复前其中 4 项为红。
- `test_llm_provider_robustness.py`（6 项：控制台加固、新进程 import app 自动生效、
  截断 vs 写坏的归因、尾随杂音不再走重试）。
- 真机 `call_llm` 压测 8/8 成功（修复前 6 次中 1 次失败）；全量 pytest **189 passed**。

## 2026-09-10: 修「WinError 10061 服务拒连」报错不可读

**因**: 用户在面板发「创建一个人形的高达模型」→ `<urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>`。
根因是 **Agent 服务没启动**（8765 无监听），但报错原样透传，用户无法自诊。

**改**: 新增 `AICADAgent/http_errors.py::describe_http_failure`（无 FreeCAD/Qt 依赖），
`HTTPWorker` 失败时不再 `emit(str(e))`，改为翻译成「原因 + 怎么修」：
- 拒连（含 WinError 10061，urllib 会包在 `URLError.reason`）→ 报「服务未启动」+ 完整启动命令
- 超时 → 提示复杂模型较慢、可重试，不误导成配置错误
- 域名解析失败 / 连接被中断 / HTTP 状态码 → 各自说明
**验**: `test_client_http_errors.py`（6 项，含「不得出现 urlopen error 原文」与 runner 源码守卫）；
真连死端口复现原始异常并确认文案；pytest 173 passed。

## 2026-09-10: 切换 LLM/Vision 到 DeepSeek `deepseek-flash`（多模态已实测）

**因**: 换用 `https://api.deepseek.com` + `deepseek-flash`。先探针验证再落地。

**探针结论**（`GET /models` 仅有 `deepseek-flash` / `deepseek-v4-pro`）:
- **多模态成立**：无文字标注的图能正确报出「左黄三角/中绿方块/右紫圆」；同一提示词去掉图则答「未提供图片」，排除「猜中」。
- 走通 app 现有调用路径：`response_format=json_object`、图像+JSON 同时可用、`extra_body={"enable_thinking": False}` 被静默接受但不生效。
- **它仍是推理模型**：completion 里 reasoning 占大头（实测 1257/2084）；`max_tokens` 必须留出推理预算。
- **硬约束**：`json_object` 要求 prompt 里出现字面 `json`，否则 400。

**改**:
1. `.env` / `.env.example`：`OPENAI_BASE_URL=https://api.deepseek.com`、`LLM_MODEL`/`VISION_MODEL=deepseek-flash`，视觉复用同一 key（不再配第二家）。
2. `app/config.py`、`llm_provider._get_llm_config`：默认值从 OpenAI `gpt-4o` 改为 deepseek，避免缺 .env 时静默打到没有 key 的 OpenAI。
3. `llm_provider`：删除 qwen 专用的 `enable_thinking` 分支（DeepSeek 不生效，属上一家 provider 的死路径）。
4. `test_prompts.py`：新增守卫，锁死「所有 system prompt 必含 json」这条 DeepSeek 契约。

**验**: pytest 167 passed；真机 `/agent/chat` 200 且产出正确 `execute_cad_program`，`/agent/capabilities` 报 `vision.model=deepseek-flash`、`available=true`；视觉 `assess_views` 返回结构化 verdict；单轮 4.7–9.7s（qwen 约 30s）。

## 2026-09-10: 质量整改 F1–F8（分支 fix/review-hardening，不并主线）

**因**: 审查见 `docs/quality_review_action_plan.md`（D1–D14）。治愈点：门闩可绕、验收由被审模型自定、无 L3/L4 几何门禁、契约双源、握手失败即永久阻断、提示词互相矛盾、错误不可修复、曲面 bbox 近似。

**改**:
1. **F1 门闩**: `orchestrator.reconcile_soft_plan` 恒以宿主计划为权威，新增 `mark_current_phase`；`chat.py` 删自洽 reconcile，`done` 需宿主全 passed。
2. **F2 验收**: 进阶段即把 `acceptance` 冻结进 `phase_state`（只可追加），计划阶段必须有几何检查，否则不 PASS。
3. **F3 几何 Oracle**: 新建 `tests/geometry_oracle/`（18 用例 L3/L4）+ `test_geometry_oracle.py` 无 FreeCAD 门禁；发现曲面 `Shape.BoundBox` 偏大，新增 `geometry_facts.exact_bbox`（`optimalBoundingBox`）替换 6 处取 bbox。
4. **F4 契约单一源**: `app/cad_program/manifest.py` 为唯一源，`scripts/sync_cad_manifest.py` 生成/校验插件副本；executor 热加载 manifest；版本 `1.1`；wedge/sweep 移出模型可见目录（工具本体保留）。
5. **F5 握手**: 新增 `AICADAgent/capabilities.py`（无 FreeCAD 依赖）；执行门 `is False`，未知即放行；探测失败保持未知并按退避重试。
6. **F6 提示词**: `chat_core.md` 为唯一规则源——重复件按「干净源对象用 pattern / 已带 Placement 循环内新建」二选一；布尔接触统一「轻嵌 1mm」；配方与 writer 文档改为引用，不再自定相反规则。
7. **F7 布尔**: 两端 runtime 支持 N 操作数（位置参或列表）按序折叠；单/空操作数在调用前报 `cad.<api>` + 实收参数 + 正确写法；handler 报错包装成可修复提示。
8. **F8 卫生**: 删根目录 `test.py`、`prompts_test_robot*`；`.gitignore` 加 `.qoder/`；修 v06 重复 copy 撞名与 registry 精确计数断言；冒烟补 `create_wedge`；新增 server/plugin runtime 漂移守卫测试。

**验**: pytest 166 passed；FreeCADCmd —— smoke 109/0、v06 14/0、oracle 18/0、cad_program_samples 7/0。
**注**: 改动均提交在 `fix/review-hardening`，未并入 dev/main。

## 2026-08-06: 整测台视觉修正（用户「不对哦」）

**因**: 把手折成 L（折线 makeTube 多段 fuse 丢段）、草图黑线叠影、fillet 竖棱选边炸脚本。
**修**: `make_sweep` 圆截面改 BSpline 单次 makeTube；整测删草图、去掉 fillet；冒烟 Handle C 形 z_span≈82、Assembled 齐。
**验**: 需重启 FreeCAD 再跑 `_tool_test_bench.cad.py`。

## 2026-08-06: 删保时捷样例

**删**: `_porsche_911.cad.py` / `docs/samples/porsche_911.md`（块状太丑，暴露工具能力不足）。下一步按工具清单逐个实验入库，不先堆丑样例。

## 2026-08-06: TEST 入库 sweep/wedge + 整测台

**加**: `cad.sweep`→`make_sweep`（圆截面 makeTube）、`cad.wedge`→`create_wedge`；`CAD_API_TEST={sweep,wedge}`。
**整测**: `data/_tool_test_bench.cad.py` + `docs/samples/tool_test_bench.md`（马克杯=loft/cut + sweep把手 + wedge底座）。
**冒烟**: Cup/Handle/Assembled bbox 合理。等人反馈 Pass/Fail。

## 2026-08-06: 四旋翼样例脚本（Code Mode）

**出**: `agent_service/data/_drone_quad_x.cad.py` — X 四旋翼+云台；机头=-Y。
**修**: 飘桨因 polar_pattern fuse Placement；桨叶改直接坐标。起落架/云台按接触重算。
**档**: `docs/samples/quad_drone_x.md` + 脚本加流程注释，作为多件装配参考样例。
**修工具**: fuse/pattern Placement；**再修**：fuse 后删源件（不只 Visibility=False）——根治「四臂各留 1 片幽灵扇叶」。样例改回 polar_pattern(fuse)。FreeCADCmd 全 PASS。

## 2026-08-06: 外部 LLM 写 cad 脚本提示词

**加**: `docs/cad_script_writer_prompt.md` — 读 chat_core/code_mode/manifest → 产出可粘 Playground 的 `cad.*`。

## 2026-08-06: CAD Playground 打不开

**因**: PySide6 无 `QPlainTextEdit.setTabStopWidth` → 打开面板 AttributeError。
**改**: 改用 `setTabStopDistance`；命令入口打印 traceback。

## 2026-08-06: CAD Playground（人当 LLM）

**做什么**: FreeCAD 内停靠面板粘贴 `cad.*` → `CadToolExecutor.execute_cad_program` → 3D 查看。
**入口**: Workbench「AI CAD Agent」→ CAD Playground（`playground.py`）。
**删**: 误做的批量 `tests/action_space/` 渠道（只要交互面板）。

## 2026-08-06: cad.move 接通位置参与 x/y/z 别名

**因**: `cad.move(obj, 0, -25, 55)` / `x=/y=/z=` 被丢掉 → 躯干不动、头颈按绝对 center 漂空。
**改**: runtime 映射位置参与 offset/dx 及 x→dx 别名（仍是相对平移）；双端同步；chat_core 写明相对语义。

## 2026-08-06: 修 cylinder/cone center+rot 映射

**因**: 高达 P3 肩关节 `center=(-24,0,70), rot_y=90` 实测中心≈(-19,0,65)；runtime 只在世界 Z 减 height/2，旋转后几何中心漂半高。
**改**: `Base = center - R*(0,0,h/2)`，R 与 `apply_placement` 同序；双端 runtime 同步；单测覆盖侧轮/竖轴/cone。

## 2026-08-06: 工具校验流水线设计 + 门闩债暂记

**记**: Phase 门闩 review 发现 → `docs/tech_debt.md`（暂缓）。
**设**: `docs/tool_validation_pipeline.md` — L0 契约→L4 cad 路径；对照 FreeCAD Placement/默认轴做几何 Oracle；现有 smoke/alignment/probe 归位。
**主线**: `development_mainline` 下一刀优先工具 Oracle，再收紧门闩。

## 2026-08-06: 文档收敛 — 请求级掌控地图

**因**: README/架构仍写旧 Plan/LangGraph；代码量大后难从入口跟数据流。
**改**:
- 新增 `docs/request_walkthrough.md`（发消息→chat→prompt→tool 三层→回灌，含行号）
- 重写 `README.md` 为 Code Mode 权威总览；architecture/code_mode/prompts README 互链
**注**: 未改运行时代码。

## 2026-08-06: 全面补默认朝向（不止圆柱）

**审计**: cone/torus 无 rot；hole/extrude/rotate/polar 默认轴 Z 未写入 Code Mode；rotate pivot 默认为世界原点。
**改**: cone/torus 支持 rot_*；tool_specs 写清默认轴/刀轴/拉伸方向/阵列轴；`chat_core`+compact 扩成「回转体/孔/草图拉伸/旋转阵列/盒子」速查；runtime cone/torus 支持 center=。

## 2026-08-06: 恢复圆柱/孔朝向规则（Code Mode 空间回归）

**因**: Code Mode 去掉 tool_specs/知识库后，`chat_core` 只留 frame，无「圆柱默认轴 Z / 侧轮 rot」；紧凑文档上下文也不再附空间规则 → 轮胎躺平、切削轴向错。
**改**: `chat_core` 增加朝向表（侧轮 `rot_y=90`，轴沿 Y 用 `rot_x`，`cad.hole` 须写 axis）；compact context 每轮附朝向速查；同步 llm_provider / vehicle pack。
**注**: 旧文档 rot_x=90（轴 Y）与当前 frame（前=-Y、轮在 ±X）不一致，侧轮以 `rot_y=90` 为准。

## 2026-08-05: 修草图拉伸「no closed profile」（同事务未 recompute）

**因**: `execute_cad_program` 整段一事务，中间不 recompute；`extrude_sketch` 读空 Shape→误报无闭合轮廓；模型误判 Body 归属并退回 box。另：`line/rect/circle` 位置参未映射、`rotate(center=)`/`extrude(center=)` 透传 TypeError。
**改**: extrude/loft 前 recompute + Edges 兜底成 Face；runtime 映射 line/rect/circle 位置参与 rotate center、丢弃 extrude.center；prompt 写明 Part 拉伸无需 Body。
**验**: FreeCADCmd 单事务 polyline→extrude PASS（体积正确）；`test_cad_runtime` 12 passed。

## 2026-08-05: cad.sketch「不可用」= FreeCAD 模块未热加载

**因**: session_5bace99a 报 `cad.sketch not available`；磁盘/symlink 已有映射，进程仍用启动时旧 `_CAD_TO_TOOL`；模型误判环境不支持草图→退回多 box fuse。
**改**: executor 每次 `execute_cad_program` reload `cad_program`；错误列出 known API；prompt 禁止因此放弃截面拉伸。
**验**: 需重启一次 FreeCAD 后新 reload 生效；其后改 runtime 无需再重启。

## 2026-08-05: 主体优先拉伸策略 + cad.sketch/extrude 接通

**因**: 复杂主体用旋转实体 cut/fuse 拼外形，拓扑易碎。
**改**:
- prompt：`chat_core`/`chat_plan_on`/`general_part` 要求主体优先「闭合截面→拉伸」，禁旋转实体拼主体。
- runtime：接通 `cad.sketch/polyline/rect/…/extrude/loft/pad/…` → 既有 TOOL_REGISTRY；同步插件 runtime。
**验**: `test_cad_runtime`（含 sketch→extrude）/ `test_prompts`。

## 2026-08-05: 视觉门控 — 空文档跳过 + vision_memory 预算

**因**: 未建模就截空图；视觉无主线，warn 也一直修。
**改**:
- 客户端：无可见几何不截图；去掉无 CAD 时的 iso 兜底。
- 服务端：空文档 `skipped=empty_document`；`vision_memory`（阶段 acceptance、open_issues、每阶段最多 2 次自动修）客户端回传。
- 仅 bad（漂移/间隙/穿模/缺件）且预算未满才自动修；warn → ask_user，用 question 问，不自动改码。
**验**: `test_vision_memory` / `test_cad_vision_loop` / `test_prompts`。

## 2026-08-05: 同名覆盖 + 模型控截图

**因**: 高达会话叠出 100+ 对象（从不 delete、同名→001）；固定四视图偏斜、模型无法换角。
**改**:
- runtime：创建类 `cad.*` 同名先删再建；`cad.delete` 支持列表、缺失跳过；插件 `delete_object` 软失败。
- 新工具 `capture_views`（executor）；vision 开启时 prompt 要求主动选角；客户端优先用工具截图，未拍且 CAD 成功才补四视图。
- prompt：重建必须清旧件，禁 `*_Final` 盖住旧几何。
**验**: `test_cad_runtime` / `test_capture_policy` / `test_prompts`。

## 2026-08-04: 阵列语法优先 + 修 rotate 公转

**因**: 齿轮齿堆在边缘一点；日志显示模型用 `for+cad.rotate(pivot=0)`，但本机 `Placement.rotate` 只改朝向不绕原点公转。
**改**:
- `cad.polar_pattern(obj, count=…, fuse=…)` / `cad.linear_pattern(obj, offset=(dx,dy,dz), …)` 规范化位置参数；prompt 强制圆周均布走 pattern，禁 for+rotate 布齿。
- `transform_tools.rotate` 改为 `R*(Base-pivot)+pivot` 真公转（兜底）。
**验**: pattern API 单测；FreeCADCmd 标准样例含 polar 齿轮。

## 2026-08-04: 修插件 runtime.py 编码损坏 + 标准样例实测

**根因**: PowerShell `Set-Content` 同步 `cad_program/runtime.py` 时 UTF-8 损坏，注释与 `_CAD_TO_TOOL` 粘行 → `IndentationError: unexpected indent (runtime.py, line 14)`；模型误以为自己的 code 缩进问题。
**修**: 用 Python `Path.write_text(utf-8)` 重写插件 runtime/validate；禁止再用 PS Set-Content 同步。
**测**: 服务端标准样例 `test_cad_standard_samples`；FreeCADCmd `test_cad_program_samples.py` **6/6 PASS**（齿轮键槽/阶梯轴/支架/对称盒/单行齿轮/executor）。

## 2026-08-04: 修 execute_cad_program 空 code 死循环

**根因**: ① AST 禁 `list.append`（齿轮 `teeth.append` 被拒）；② prefilter 清空 code；③ `ToolCall` schema 丢掉 `blocked/preflight_error` → 客户端只见 `empty code`。
**修**: 允许安全集合方法；预校验保留原文+错误细节；schema 透传 blocked；`cad.*` 映射 size/center/位置 fuse/cut/rotate；`log_execution` 用 `trace.path`。
**验**: `test_cad_gear_regression` + 全量 84 passed。

## 2026-08-04: Code Mode 切片4 — 多视图 VLM + Trace 分 step

**多视图**: 客户端 `capture_views(front/side/top/iso)`；`execute_cad_program` 成功后优先多视图回传 `viewport_images`，失败降级单图或跳过。
**VLM**: `assess_views` 支持多图；`verdict=bad` → `revise_once`；VLM/截图异常 `skipped` 不阻断；`chat_core`/`vision.md` 要求硬伤一次 `execute_cad_program` 修订。
**Trace**: chat step 预分类 `code_gen|code_repair|tool_feedback`，meta 写回实际 `step_kind`（含 `vision_revise`）。
**验**: `test_cad_vision_loop` + 全量。

## 2026-08-04: Code Mode 最小闭环（execute_cad_program）

**因**: 上一轮「Context Working Set + 关键词路由」被否，改复现 CADDesigner 最小闭环——模型产出受限 CAD 程序，执行器跑，错了修。
**服务端**:
- 新增 `app/cad_program/{validate.py,runtime.py}` — AST 白名单（禁 import/属性逃逸/while/def/class，限 cad 调用/节点/循环数）；`cad.*` → TOOL_REGISTRY，紧凑结果 success/error_type/error_message/failed_line/created。
- `chat` 新增 `prefilter_tool_calls`：危险 `execute_cad_program` code 服务端直接拒绝并标 blocked。
- `build_chat_system_prompt` 改为 Core+brief+plan/vision，不再注入 53 工具工作集；`chat_core.md` 重写为 Code Mode 两阶段。
**客户端**:
- `cad_program/{validate.py,runtime.py}` 从服务端同步（包前缀改为 `AICADAgent`）。
- `executor.execute_tool_call` 增加 `execute_cad_program` 分支：单个 openTransaction → run_cad_program → 成功 commit/失败 abort。
- `agent_runner` 处理 blocked call（不执行，直接回灌服务端错误）。
**删**: `test_chat_working_set.py` / `test_routing.py`；`app/tools/routing.py` 与 `prompts/packs/*` 从主路径摘除。
**验**: `pytest` 74 passed。

## 2026-08-04: Context Working Set（规则包 + 工具预路由）

**路由**: `app/tools/routing.py` — 本地关键词决定 task/phase/rule_packs/tool_categories；无 Tool Search 往返。
**Prompt**: `chat_system.md` → `chat_core.md` + `prompts/packs/*`；齿轮不再注入人形/车辆规则。
**工具**: chat 只注入 Active 类别完整 schema + Core 查询工具 + Indexed 类别摘要；拆出 `pattern`，`cut_hole`→boolean。
**pad**: midplane=true 时 length=总厚；FC SideType Two sides 折半下发（`pad_params` 契约）。
**验**: routing/working_set/pad/prompts/registry 相关测试。

## 2026-08-04: chat-first 代码整理（删旧闭环耦合）

**客户端**: `agent_runner.py` 重写为仅 chat（~650 行）；删 AgentSession/start_plan/next_step/evaluate/restore；pause/resume chat-safe；panel 去 legacy 信号。
**服务端**: 瘦 `schemas/session.py`（仅 ToolCall/ExecutionResult）；删 extractor、tools/registry；cad_plan/cad_tools/replay_trace → archive；tutorial → archive/tutorial。
**验**: `pytest` 57 passed。

## 2026-08-04: 旧架构清理可行性评估 + 检查点提交

**评估**: `docs/legacy_cleanup_feasibility.md` — 客户端旧闭环可优先删；archive 可选；runtime/memory 勿整包删。
**本提交**: chat 提示词/timeout/cut_hole/mirror 下线等改动检查点，清理前先上 GitHub。

## 2026-08-04: 下线 mirror，对称改对侧 create；保留阵列

**因**: mirror 仍易藏源/不可见/Placement 双重偏移；用户要求取消。
**改**: 从 tool_specs/registry/FreeCAD TOOL_REGISTRY 移除；prompt 要求关于 X=0 对侧 create_*；`linear_pattern`/`polar_pattern`/`copy_object` 保留；mirror 函数改为显式报错。

## 2026-08-04: 紧凑文档上下文补「已隐藏」

**因**: session_1aee9ae6 右侧已 mirror 且坐标对称，但旧 mirror 藏源；紧凑索引无 visible → 用户说「没对称」时模型以为视口刷新问题，对 L 侧 set_placement 双重偏移发癫。
**改**: `build_compact_document_context` 合并 live document_state 的可见性/bbox，汇总隐藏列表；prompt 禁止对镜像 Feature 乱 set_placement。

## 2026-08-04: chat 坐标系/镜像提示词纠偏（高达 session_7cba71d7）

**因**: 模型自定「前=+X」与 `place_relative`（right=+X/front=-Y）冲突；mirror 写 name_map 并藏源 → 半边肢体被劫持。
**提示**: `chat_system`/`chat_plan_on` 锁定 frame=前-Y/左右±X；完成门闩；清理 Temp/001；tool_specs 写明锚点与 mirror 双侧保留。
**代码**: `mirror` 不再返回 `source`、不隐藏源（防 name_map 改写）。

## 2026-08-04: 缓解 chat timeout

**原因**: 完整 system(~18k)+工具表时 qwen 单轮~30s；`max_tokens=40960`+推理+视觉+重试易超客户端 300s。
**改**: `LLM_MAX_TOKENS=8192`、`LLM_TIMEOUT_SEC=180`、重试默认 2；尝试 `enable_thinking=False`；HTTP 超时 600s；`.env` 关 VISION、对话预算改 120k。

## 2026-08-04: cut_hole 改为 Part::Cut / Pocket

**旧**: 内存 `shape.cut` + 新 Feature 并隐藏原件，像「删掉」。
**新**: 默认 `Part::Cylinder` 刀 + `Part::Cut` 布尔求差；可选 `body`→草图圆+Pocket；校验 Solids/体积，失败回滚不藏基体；增 `axis`。
**提示**: chat_system 要求打孔用 cut_hole 且后续只用新对象名。

## 2026-08-04: 修 chat 阻塞事件循环（客户端像没响应）

**原因**: `async /agent/chat` 内同步 `call_llm` 堵死 uvicorn；一次调用约 40s，期间 health/其它请求全挂。
**证据**: `session_7203fb68` 服务端已落库完整回复，但等待期间连接堆积。
**修**: `asyncio.to_thread(chat_turn)`；客户端发送即显示「正在请求模型…」。

## 2026-08-04: 切换 LLM/Vision 至阿里云 qwen3.8-max-preview

**.env**: `OPENAI_BASE_URL=token-plan…/compatible-mode/v1`，`LLM_MODEL`/`VISION_MODEL=qwen3.8-max-preview`，`VISION_ENABLED=1`。密钥仅本地 `.env`。

## 2026-08-04: 修 call_id 幂等误跳过（✓ 却产出旧名）

**现象**: 阶段2 create 天线显示 `✓ → Pelvis`，实际未执行；get_object_detail 找不到新对象。
**原因**: executor 仅按 call_id 去重，模型每轮重用 T1/T2，返回阶段1缓存结果且 status=success。
**修**: 同 id 且 tool+args 相同才跳过；UI 对 skipped 显示 ↷ 非 ✓；prompt 强调 call_id 全会话唯一。

## 2026-08-04: chat 建模原则提示词（工程师模式）

**改**: `chat_system.md` 纳入规划/基准/先大后小/mirror/可追溯尺寸等原则；`chat_plan_on` 明确 soft_plan 四块（分解/顺序/frame/key_dims）；`design_brief` 对齐冲突优先级。
**适配**: 输出仍为 chat JSON（message + tool_calls + soft_plan），非旧 step_id/operation 格式。

## 2026-08-04: 归档旧闭环链路

**提交前快照**: `101b2d2`（chat-first + prompts 集中）。
**归档至** `agent_service/archive/legacy_closed_loop/`：旧 API（plan/start/next/evaluate/spec…）、提示词、abstract_steps/cad_spec/evaluation/recipes/modeling_knowledge、专测。
**Live**: 仅 `/agent/chat` + compress + capabilities + session；`app/prompts/` 只留 chat_*；`workflow/sanitize.py` 抽出。
**pytest**: `norecursedirs=archive`。

## 2026-08-04: 提示词集中到 app/prompts/

**目录**: `agent_service/app/prompts/*.md` + `README.md` 索引；`[[PLACEHOLDER]]` 注入；文件头 `<!-- 用途/调用方 -->` 注释不进模型。
**接线**: chat / compress / vision / design_brief / high_level / next_step / evaluate / legacy / cad_spec 均改读 md；改提示词只改 md。
**测试**: `test_prompts.py`。

## 2026-08-04: 工具批让出 UI 帧（防假死）

**改动**: `_execute_chat_tools` 改为队列 + `QTimer.singleShot(0)` 逐个执行；每工具后 `processEvents(50ms)`。stop 清空队列并用 `_chat_epoch` 作废进行中的批。

## 2026-08-04: Cursor 式面板（Transcript + Composer）

**UI**: 重写 `panel.py`；新增 `chat_ui.py`（`TranscriptView` / `ComposerBar`）。删 Plan 独立框；发送/停止进输入条；过程（plan/tools/vision/queue）以 thinking 灰色等宽字进对话流；日志改为可折叠抽屉。
**Runner**: 新增 `chat_event{kind,text,meta}`；`show_panel` 强制重建 dock 避免旧控件残留。

## 2026-08-04: 对话插话改为排队（修竞态）

**策略**: 忙时不叠 HTTP；消息入队，当前轮 `awaiting_user/done/error` 或用户点停止后再发。`_chat_epoch` 作废过期回调。
**顺带**: `start_plan` 写入 `high_level_plan.user_input`（evaluate brief 回取依赖此字段）。

## 2026-08-04: 对话式建模 + 视觉层 + resume 断层

**形态**: UI 从「生成计划→单步/自动」改为 Cursor 式对话框（`panel.py`）；主入口 `POST /agent/chat` + `POST /agent/compress`；旧三段式 API 仍保留兼容。
**循环**: 用户消息 → LLM（自然语言 + 可选 tool_calls）→ 客户端执行 → tool_results 回灌；忙时插话排队；Plan 模式 / 视觉辅助为开关。
**视觉**: `app/vision/` + FreeCAD `viewport.capture_viewport`；`.env`：`VISION_ENABLED` / `VISION_MODEL` / `VISION_API_KEY` / `VISION_BASE_URL`；`GET /agent/capabilities`。
**resume**: 手工改文档 → `format_resume_note` 写入 transcript。
**测试**: `test_chat_vision.py`。

## 2026-08-04: 对话上下文累积（步骤间不再冷启动）

**问题**: 每次 LLM 调用只发 `[system, user]` 两条，模型看不到自己上一步定了什么坐标系、为什么那么定，逐步重猜 → 步骤割裂。
**新增 `app/conversation/`**（三层各一职）:
- `transcript.py` — `Transcript` 值对象：`append_turn` / `render(system, pending_user)` / 预算内修剪
- `store.py` — `ConversationStore`，与 runtime 共用 sqlite 文件但独立表 `conversation_messages`（对话可单独压缩清空，不动事件日志）
- `__init__.py` — `conversation_scope(session_id)` contextvar 作用域，写法对齐 `debug/trace_logger`，避免参数穿三层

**记什么（关键取舍）**: 存**助手原始输出**（缺失的连续性就在这）＋**一行工具结果**；**不存**每轮 user_message 里的文档状态快照——那是快照不是增量，累积既烧 token 又让新旧状态互相矛盾。完整快照只作为当前轮最后一条 user 消息发出。`call_llm` 新增 `transcript_note`（计入历史的精简版）与 `record`（旁路调用如 cad_spec/legacy plan 不入库）。
**修剪**: 默认 120k 字符（`CONVERSATION_BUDGET_CHARS` 可调），始终保留最早那轮（含原始需求），中间成对丢弃，省略标记并入首条保留消息以维持 user/assistant 交替。
**接线**: `main.py` 三个端点与 trace 同层开作用域；作用域退出只落库新增部分。存储故障降级为无历史，不拖垮建模。

**效果**: next_step → evaluate_step → next_step 现在是一条连续消息流，形如 coding agent 的 `assistant 决策 → tool result → assistant 决策`。
**测试**: 新增 `test_conversation.py`（22 项）；全量 123 passed。
**注**: 测试用 `tempfile.mkdtemp` 而非 `tmp_path`（本机 pytest 临时目录权限被拒，仓库既有约定如此）。

## 2026-08-04: 需求原文回注 + 验证闭环打通 + LLM 重试

**根因（最重要）**: `user_input` 是 `_build_next_step_prompt` 的形参却**从未进入提示词正文**——只喂了知识检索，而记忆包 `working_lines = [goal or user_input]` 又把它丢掉。于是每步只看得到一句 `goal`，用户写的尺寸/坐标系/对称要求全程不可见，模型逐步重新猜坐标。
**改动**: 新增 `app/design/`（设计意图层，与 memory「发生了什么」分开）；`format_design_brief` 原样渲染需求原文，注入 next_step 与 evaluate 提示词（evaluate 无 user_input，从 `high_level_plan.user_input` 回取）。

**验证闭环**: 模型在 `expected_effect.validators` 里**自己点名**的验证器此前被恒 False 的 `strict_validation` 一起吞掉，验证器从未运行。改为两种来源分离——自声明的总是跑，配方/步骤默认后置条件仍归 strict。
**阻断策略单一来源**: `BLOCKING_VALIDATORS` / `is_blocking_validator` / `blocking_failures` 收进 `evaluation/validators.py`；`should_advance_abstract_step` 真正使用 `validator_results`（此前收参不用，判断散在调用点）。端到端行为不变，只是从两处收敛到一处。

**LLM 重试**: `call_llm` 拆出 `_attempt_llm_call`，3 次指数退避，异常与 JSON 截断都重试——修 P4 收尾阶段单次失败即 abort、倒角全不执行。

**提示词硬规则**: 对称件必须 `mirror`（禁手算对侧坐标，已知高频不对称成因）；精修阶段倒角/圆角取相邻最小尺寸 5%~15%，禁整体 `edge_selector=all`。

**清理**: 删除 `app/graph/`（`state.py` 零引用、`cad_graph.py` 空壳、`nodes.py` 仅 re-export）；`scripts/diag_failing_tests.py` 改指 `app.workflow.service`。
**测试**: 新增 `test_v09_closed_loop.py`（17 项）；全量 101 passed。

**注**: `mirror` 工具本就存在（`tool_specs.py`），缺的是硬规则不是工具。未做：持续 messages 数组（见下）与视觉闭环。

## 2026-08-03: 拆 LangGraph，工作流收成 app.workflow

**结构**: 新增 `app/workflow/service.py` 为唯一脊柱（`start_plan`/`next_step`/`evaluate_step`/`legacy_plan`）；`main.py` 变 HTTP 薄壳；`graph/cad_graph.py` 删除；`graph/nodes.py` 仅作兼容 re-export。
**收敛**: evaluate 决策只 normalize 一次（去掉 `llm_provider` 内第二次）；abstract_step_queue 只在 `workflow.start_plan` 构建一次（去掉 node/main 双建）。
**依赖**: requirements 去掉 langgraph/langchain；旧 `/agent/plan` 改为 `legacy_plan` 纯函数循环。
**测试**: 84 passed。

## 2026-08-02: create_box anchor=center（修键槽偏心「斜槽」）

**根因**: Part::Box 的 pos 是角点 (xmin,ymin,zmin)；LLM 用 pos_y=0 以为居中，实际 y=0..width，圆柱侧切偏心像斜槽。
**改动**: `create_box` 增 `anchor=min|center`；tool_specs 写清；`stepped_shaft.md` 键槽强制 center + 禁 fillet all。

## 2026-08-02: 上下文阶段窗口 + query 不洗批 + phase/queue 同步

**query**: `boolean_*` 对文档/记忆已存在对象不再 QUERY_REQUIRED；validate 改为 query **prepend** 原批（不丢计划）。
**phase**: evaluate 以 abstract_step_queue 为权威，禁止 LLM 单独跳 phase；next_step 不再自动进阶；runner 跟 step_id。
**context**: SessionMemory `phase_events` / `phase_conclusions`；prompt 优先注入当前阶段轨迹与已完成结论。
**测试**: `test_phase_sync.py` + query_policy/harness 回归。

## 2026-08-01: 工具新增与验收标准文档

**新增**: `docs/tool_addition_standard.md` — 双侧注册位置、函数/返回契约、LLM 调用格式、name_map/query_policy、Checklist 与 DoD；`tool_design.md` 顶部指向该文。

## 2026-08-01: 全量工具冒烟测试 + 修复 5 处接口问题

**测试**: FreeCADCmd 跑 `tests/test_all_tools_smoke.py`（54 工具）；初测 105/109，修后 **109/109**。
**发现并修**:
1. `linear_pattern` 末尾 `return result}` 语法错误（无法 import）
2. `scale`: FC1.1 `Shape.scale(factor, base)` 仅等比；非等比改 Matrix；先 copy 防 immutable
3. `copy_object` 返回 `source` 污染 executor name_map → `modify_param` 打到副本；改为 `copied_from`
4. `measure_gap`/`compare_orientation`: FC1.1 PrimitivePy 无 `getBoundBox` → 用 Shape.BoundBox
5. `pad_to_face` 跨 Body UpToFace 静默坏几何 → 回退 Length + note；`revolve_sketch` 用 ReferenceAxis；`pad_sketch` SideType；Horizontal 约束单参

## 2026-08-01: 修 copy_object + 阵列工具 + 三篇建模技能文档

**P0**: `copy_object` 误把 `name` 传给 `Document.copyObject` 第3参（应为 bool）→ 改为正确 copy 后物化为指定 Name 的 `Part::Feature`。
**阵列**: 新增 `polar_pattern` / `linear_pattern`（FreeCAD + tool_specs/registry，52→54）；query_policy 识别阵列产物名与 `fuse_name`。
**知识**: `gear.md` / `mouse.md` / `stepped_shaft.md` 专业工序文档；retrieval 截断 1500→6000。
**测试**: `test_pattern_tools.py`（FreeCAD 侧）；`test_tool_registry`/`test_knowledge` 更新。

## 2026-08-01: V0.9 手册阶段 A~F 落地

**A**: runner pause/resume 持久化 + restore_session；panel 暂停/继续切换、恢复会话、回答并继续、checkpoint/事件数显示。
**B**: `align_objects` / `place_relative` / `distribute_along`（49→52）；spec/registry/query_policy/prompt；FreeCAD `tests/test_placement_tools.py`。
**C**: validators `verify_grounded/no_overlap/touching/size_close` + `test_validators_v09.py`。
**D**: `app/modeling_knowledge/` patterns + retrieval，注入 start_plan/next_step；`test_knowledge.py`。
**E**: ask_user → 面板回答并继续；evaluate 回传 name_map 进 checkpoint。
**F**: `test_lifecycle.py`；回归 `76 passed`。

## 2026-08-01: V0.9 生命周期基建（部分完成）+ 实施手册

**已落地**: 服务端 `runtime/diff.py`（文档 diff）+ `runtime/reducer.py`（事件→RunState）+ pause/resume/snapshot/list 四个 API（`/agent/session/*`）；executor call_id 幂等去重；agent_runner 批量结果收集 + evaluate 聚焦失败 call + batch_summary + repair 后回 evaluate 闭环；session_memory.restore_from_pack。
**执行依据**: `docs/v09_implementation_playbook.md`。

## 2026-07-31: 修复 query_before_act 误杀同批创建（幽灵对象循环）

**现象**: `session_d107267a` 中 LLM 一步批量 `[create_sphere→A, scale A→B, create_box→C, boolean_cut(base=B, tool=C)]`，被 `query_before_act` 标记 B 为 QUERY_REQUIRED → 整批被替换为 `get_object_detail(B)` → B 还没创建 → "Object not found" → LLM 死循环。
**根因**: 政策只看文档/缓存里有没有 B，不知道 B 是同批更早的 call 产生的。
**修复**: `query_policy.py` 批量感知——`_batch_producer_index` 收集每个 call 之前同批已产出的对象名（`expected_effect.new_object` / `args.name` / `args.result_name`）；`validate_query_before_act` 对 risky call 的每个引用 target（`base/tool/obj_a/obj_b/part1/part2` 全部），若由更早同批 call 产出则跳过查询要求；前向引用仍报错。
**测试**: `test_query_policy.py` 12 项（含原 bug 复现 + 前向引用仍报错）；`test_pipeline/test_v08_harness/test_geometry_facts/test_runtime` 40 passed。

## 2026-07-31: 修复 query 空转（bbox/摘要/covers）

**现象**: P2 在 `get_object_detail`↔`list_topology` 循环；有 volume 但无 size。
**根因**:
1. `get_object_detail`/`document_state` 对 loft 的 bbox 仍空，而 `list_topology` 有 bbox
2. query 摘要只认 `bbox.size`，丢掉 topology 的 `bbox.x/y/z`
3. `query_cache` compact 丢掉 size；covers 只要命中 target 就算覆盖
**修复**: 统一 spatial facts；list_topology/get_object_detail 补 size+center；covers 要求 size+center；prompt 禁止 incomplete 空转。

## 2026-07-31: Runtime Phase1 — Event Log + Checkpoint + 粗计划/感知

**审计**: 大改目录收口为 Phase1；基线 `0ca25ae`；详见 `docs/runtime_refactor.md`。
**新增**: `app/runtime/`（sqlite event log + checkpoint + context slice）；API 接线 start/next/evaluate/log。
**粗计划**: start_plan prompt 只输出顺序+角色，禁止工艺细节。
**感知**: FreeCAD `document_state` 加强 bbox（isNull / Body.Tip / Shape.BoundBox 回退）。
**测试**: `test_runtime.py`。

## 2026-07-31: DeepSeek reasoning 空 content 导致 LLM 调用失败

**现象**: `next_step` 返回 `LLM 调用失败`；trace 显示 `content=""`，JSON 在 `reasoning_content`。
**根因**: `call_llm` 只读 `message.content`，reasoning 模型偶发把最终答案放进 `reasoning_content`。
**修复**: `_message_text` 回退 `reasoning_content`；`_extract_json_object` 容忍 ```json 与 `json\n{...}` 前缀。

## 2026-07-31: 草图曲线工具 arc / polyline / bspline

**新增**（对齐 FreeCAD Sketcher 脚本 API）:
- `sketch_add_arc`: `Part.ArcOfCircle`，mode=`three_point` | `center`（角度用度，内部转弧度）
- `sketch_add_polyline`: 连续 `LineSegment` + `Coincident`，可选 `closed`
- `sketch_add_bspline`: `Part.BSplineCurve.interpolate` / `buildFromPoles`

**改动**: `sketch_tools.py` + `__init__`；`tool_specs`/`tool_registry`；工具数 46→49。验证: registry/spec 对齐 + `scripts/verify_sketch_curves.py`

## 2026-07-31: Debug trace 可读化

**问题**: 一步拆成 llm_01_system_prompt / user_message / raw / parsed 多文件，难跟上下文。
**改动**: 每步主读 `llm_XX_trace.md`（工具列表→system prompt→user 上下文→模型输出）；session 根 `README.md`；去掉分散 md。

## 2026-07-31: 工具规范修复 + evaluate 队列推进 bug

**工具规范**（对照 tool_design / spec↔实现）:
1. `set_placement`/`apply_placement`：全 0 参数可复位原点；`mirror` 隐藏源对象
2. `revolve_sketch` 使用 axis_x/y/z；`create_sketch_on_face` face 大小写/越界校验
3. primitive/fillet/scale 数值校验；unit 仅 mm；`compare_orientation` 用 tolerance_ratio 判各向同性
4. executor abortTransaction 不掩盖原始错误；spec 描述同步

**evaluate 推进**（3 个 harness 失败根因）:
1. `normalize_evaluate_decision`：abstract step 未耗尽时禁止按 high_level 末阶段强制 finish
2. 成功推进不再依赖 LLM `phase_status=completed`；warning validator 不阻断
3. 连续失败≥2 或 `skip_and_continue` 时推进 abstract step，decision→continue

**配置**: LLM → DeepSeek (`https://api.deepseek.com`, `deepseek-v4-flash`)
**测试**: `test_v08_harness` + `test_tool_registry` 40 passed

## 2026-05-29: V0.8 CAD Harness Core

**目标**: Spec → Impact → Recipe → Abstract Step 队列 → 滚动 tool_calls → validators → 推进 queue（非 sub_plan 脚本）。

**改动**:
1. **Agent Service**: `cad_spec/`, `inspection/impact_map.py`, `recipes/registry.py`, `abstract_steps/planner.py`, `evaluation/validators.py` + `harness.py`, `debug/replay_trace.py`
2. **API**: `/agent/spec`, `/agent/impact_map`, `/agent/select_recipe`；`next_step`/`evaluate_step` 扩展 harness 字段（queue、abstract_step、validator_results）
3. **Graph**: `plan_next_step_node` 队列耗尽 finish；`evaluate_step_node` 校验通过后 harness 推进 abstract step
4. **FreeCAD**: `agent_runner.start_harness()` spec→impact→recipe→start_plan；evaluate 响应同步 queue/step
5. **测试**: `test_v08_harness.py` 12 项（spec/impact/recipe/next/evaluate/advance/replay API 流）

**设计**: Recipe 只含 abstract_steps，不含 tool sequence；每步 next 最多 3 个 tool_calls；deterministic validators 优先于 LLM finish 判断。

**UX**: Spec/Recipe 未匹配时 `start_harness` 自动回退 V0.7 LLM `start_plan`；404 提示旧版 Agent Service；按钮文案说明 Harness→LLM 双路径。

## 2026-05-30: V0.8.7 空间感知 + 路由统一

**问题**: LLM 回退路径建模缺 3D 空间感知，对象坐标靠臆造，多体模型（汽车）无法装配。根因: `_build_document_context` 只喂 name/type，丢弃了已采集的 bbox/placement。

**改动**:
1. `llm_provider._build_document_context`: 注入每对象 center/size/pos/rot/volume/visible + 空间定位规则（基于已有对象坐标计算，禁止臆造；create_cylinder 默认轴 Z，水平需绕 X 转 90°）。next_step/evaluate 双 prompt 同时受益。
2. `planner.is_harness_session()`: 单一谓词统一 Harness-vs-LLM 路由（需 cad_spec + 非空 queue）；`nodes.py` plan_next_step/evaluate_step 改用它，消除散落条件。
3. 测试 12→14（harness session 谓词 + LLM 回退路由）。
4. `development_plan.md` 新增 V0.8.7（1+2 已完成，3 validators 回退路径 / 4 朝向装配约束 待做）。

**架构差异结论**: V0.8 期望"复杂建模走可控轨道"，实际 6 个 recipe 仅覆盖单 primitive/单特征，复杂任务必走 LLM 回退；Spec 为规则非 LLM；validators/impact_map 在回退路径未生效。详见 V0.8.7 与下方 review。

## 2026-05-30: V0.8 架构统一（Spec LLM + 单轨 queue + 全局 validators）

**改动**:
1. **Spec LLM**: `generate_cad_spec_with_llm` 优先；规则 `_generate_cad_spec_with_rules` 作 API 不可用回退；Harness 不再 Spec 失败就 skip
2. **统一控制**: `build_queue_from_phases` 将 start_plan phases → abstract_step 队列（step_type=llm_phase）；`plan_next_step` 对 llm_phase 调 LLM、对 recipe step 调确定性 tool_calls
3. **全局 validators**: `resolve_validator_names` + evaluate 全路径跑 validators；queue 推进不再依赖 cad_spec
4. **Server 权威**: start_plan/evaluate 响应带 queue/step；FreeCAD `_sync_session_from_evaluate` 纯同步，删 `_advance_abstract_step_if_validated`
5. **测试**: 19 项（LLM spec mock、queue 统一、llm_phase next_step、全局 validators）

**流程**: Spec(LLM) → Impact → Recipe(可选) → start_plan(queue) → next/evaluate(统一 abstract step 推进)

## 2026-05-30: 修复 robot 误匹配 recipe + fillet 死循环

**问题**: robot 误选 `box_with_fillet_recipe`(2步) 覆盖 5 phase LLM 队列；fillet target=`Torso, Head, Base` 整串当对象名；skip 不推进 AS2 死循环。

**改动**: `select_recipe` 复杂 model_type 返回 llm_fallback；`should_use_recipe_queue` 阶段多于 recipe 时用 LLM 队列；`_resolve_target_name` 解析逗号 target；skip 连续失败时 server 推进 abstract step。测试 23 项。

## 2026-05-29: V0.7 闭环建模 Agent

**目标**: 从 Plan-as-Script 升级为 Observe-Plan-Act-Evaluate 闭环控制。

**改动**:
1. **FreeCAD 端**: `document_state.py` 增强 bbox/topology/visible/placement/dependencies；`executor.py` 新增 `execute_tool_call()`；新建 `agent_runner.py`（QThread 闭环控制器）；`panel.py` 切换新 UI（高层计划/单步/自动/暂停/停止）
2. **Agent Service**: 新增三个 API（`/agent/start_plan`, `/agent/next_step`, `/agent/evaluate_step`）；LangGraph 扩展为 3 个独立 graph；`cad_state.py`/`session.py` schema 升级；`planner.py`/`llm_provider.py` 三种 prompt 模式；`evaluation/rules.py` 确定性校验
3. **决策**: 保留旧 `/agent/plan`；Session 存 FreeCAD 端；失败最多重试 2 次后 skip_and_continue

**架构**: FreeCAD 驱动循环（observe+act），Agent 负责 plan+decide

**Bugfix**: P1 完成后过早 finish — 新增 `evaluation/phases.py` 阶段推进逻辑；evaluate/next_step 禁止非末阶段返回 finish；evaluate 请求携带 high_level_plan + current_phase_id

**Bugfix**: cut_hole/fillet 对 Part::Feature 原地修改导致 `{target}_Hole` 不存在 → `assign_shape_result` 在 result_name 不同时创建新对象；HTTP 500 因 repair_tool_calls 缺 call_id → `_sanitize_tool_calls`；HTTP timeout 120→300s

**Debug 模式**: `app/debug/trace_logger.py` + `call_llm` 挂钩；API 写 request/LLM response/execution；FreeCAD 面板勾选 + `POST /agent/log_execution`；目录 `agent_service/debug_sessions/`

## 2026-05-29: V0.6 Bug Fix - Placement 二次应用 + 名称链追踪

**问题**: Fillet/Boolean/Scale/Mirror 生成新 Part::Feature 时，Placement 被二次应用（位置偏移）；源对象未隐藏导致视觉重叠；后续步骤引用旧名。

**改动**:
1. `_helpers.py` `assign_shape_result()` - 隐藏源对象（`Visibility=False`），删除 `feat.Placement = target.Placement`
2. `boolean_tools.py` `_boolean_result()` - 隐藏 base/tool 对象，删除 Placement 赋值
3. `feature_tools.py` `mirror()` - 删除 Placement 赋值
4. `transform_tools.py` `scale()` - 隐藏源对象，删除 Placement 赋值
5. `executor.py` - 新增 `name_map` 追踪对象名变化（Base→Base_Fillet），`_rewrite_args()` 自动解析后续步骤中的旧名引用

**根因**: Part::Cylinder 等参数化对象的 Shape 已包含世界坐标（Placement 已应用），创建 Part::Feature 时再赋值 Placement 导致位置翻倍。

## 2026-05-29: V0.6 工具大扩充 + 树状分类检索

**目标**: 工具 6→22，建立分类检索，解除 LLM 建模能力瓶颈。

**改动**:
1. FreeCAD 侧新增 `boolean_tools.py`, `transform_tools.py`, `_helpers.py`；扩展 primitive/feature/export
2. TOOL_REGISTRY 注册 22 个工具（primitives/boolean/features/transform/export）
3. `tool_specs.py` 同步 22 个 spec
4. `tool_registry.py` — TOOL_CATEGORIES + get_tools_by_categories + infer_categories_for_task
5. `llm_provider.py` — build_system_prompt 支持 tool_categories 子集注入
6. 测试: test_tool_registry.py + test_pipeline.py 全通过；FreeCAD 功能测试脚本 test_v06_freecad_tools.py

**API 参考**: FreeCAD Topological data scripting (fuse/cut/common, makeSphere/Cone/Torus, makeFillet/Chamfer, exportStep/exportStl)

## 2026-05-29: V0.6+ 高级工具 + 拓扑选边

**新增**: list_topology, 草图链(7), PartDesign(5), 曲面(3), 装配(4); 增强选边(face_selector/zone/longest)
**调研**: FreeCAD 拓扑命名问题 — Edge1/Face1 为 1-based 索引，修改后重排；操作前 list_topology + 语义选择器

## 2026-05-29: 位置控制工具 + 超时优化

**问题**: 创建对象只能在原点堆叠，LLM 无法指定位置；客户端请求经常超时。

**改动**:
1. `primitive_tools.py` - create_box/create_cylinder 增加 pos_x/pos_y/pos_z 参数
2. `modify_tools.py` - 新增 set_placement 工具（位置+旋转）
3. `tool_specs.py` - 更新工具规格，增加位置参数和 set_placement
4. `llm_provider.py` - max_tokens 40960→4096（减少生成时间）
5. `panel.py` - 客户端 timeout 30→120 秒

## 2026-05-28: V0.2-V0.3 API 调用验证

**目标**: 清理 executor.py，打通 API→plan→执行链路，验证工具调用建模

**改动**:
1. `executor.py` - 删除 8 个 stub 方法 (NotImplementedError)，保留 5 个真实接口: create_box, create_cylinder, modify_param, delete_object, save_fcstd
2. `panel.py` - 添加"执行计划"按钮和 `_on_execute_plan()` 方法，缓存 plan 并调用 executor 执行

**验证结果**:
- ✓ FastAPI 服务启动成功 (http://127.0.0.1:8765)
- ✓ `POST /agent/plan` 正确返回 create_box plan (100x60x20mm)
- ✓ `POST /agent/plan` 正确返回 create_cylinder plan (R25 H50)
- ✓ `GET /health` 返回 status: ok

**下一步**: 在 FreeCAD 中测试完整流程 - 输入需求 → 生成 plan → 执行建模

## 2026-05-28: executor.py 与 cad_tools/ 解耦重构

**目标**: 将 executor.py 中的 5 个工具方法拆分到 cad_tools/ 下对应模块，executor 仅做调度和事务管理。

**改动**:
1. `cad_tools/primitive_tools.py` - 实现 create_box、create_cylinder 纯函数（参数为 doc）
2. `cad_tools/modify_tools.py` - 实现 modify_param、delete_object 纯函数
3. `cad_tools/export_tools.py` - 实现 save_fcstd 纯函数
4. `cad_tools/__init__.py` - 构建 TOOL_REGISTRY，提供 get_tool/list_tool_names
5. `executor.py` - 删除所有工具方法，改为通过 TOOL_REGISTRY 调度（getattr → registry lookup）

**架构**: 工具函数签名统一为 `func(doc, **args) -> dict`，executor 负责事务管理（begin/commit/rollback）和计划执行。

## 2026-05-28: FreeCAD 端到端验证通过

**验证内容**: 在 FreeCAD 中完成完整流程测试 — 面板输入自然语言 → 调用 API 生成 plan → 点击执行按钮 → FreeCAD 特征树中成功创建模型（create_box / create_cylinder）。

**结果**: V0.2-V0.3 目标达成，API→plan→executor→cad_tools 全链路打通。

## 2026-05-28: LLM 接入与建模验证

**目标**: 接入 LLM 替代纯规则引擎，实现自然语言驱动的建模计划生成。

**改动**:
1. `llm_provider.py` - 新增 LLM 集成模块：
   - `build_system_prompt()`: 构建 system prompt，自动注入 TOOL_SPECS（12 个工具）
   - `call_llm()`: 调用 OpenAI-compatible API（支持自定义 base_url），使用 JSON mode
   - `generate_plan_with_llm()`: 生成 + 格式校验 + 默认值填充
2. `planner.py` - 改为 LLM 优先、规则引擎回退：`generate_plan()` → `generate_plan_with_llm()` → 失败则 `_generate_plan_with_rules()`
3. `config.py` - 新增环境变量：`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`

**架构**: LLM 返回结构化 JSON（status/goal/plan），plan 中的 tool 字段与 TOOL_REGISTRY 对齐。规则引擎保留作为 fallback。

**验证结果**: LLM 生成计划 → executor 执行 → FreeCAD 建模成功。

## 2026-05-29: V0.5 LangGraph Pipeline

**目标**: 搭好 LangGraph 链路，实现 plan 生成的校验+重试机制，替代直接调用。

**改动**:
1. `state.py` - AgentState 增加 retry_count、validation_errors 字段
2. `nodes.py` - 重写三个节点函数：
   - `parse_input_node`: 输入校验、初始化重试状态
   - `plan_node`: 调用 generate_plan，重试时携带错误上下文
   - `validate_plan_node`: 工具名/必填参数/类型/依赖校验，调用 `_validate_plan()`
   - `should_end()`: 条件路由（ok→end, fail&retry<2→retry, fail&retry>=2→end）
3. `cad_graph.py` - 构建完整工作流图：
   - parse_input → plan → validate_plan → 条件边
   - 校验通过→END；校验失败且 retry<2→retry_bump→plan（重试）；retry>=2→END
   - `get_cad_agent()` 单例模式返回编译后的 graph
4. `llm_provider.py` - 增强 prompt 构建：
   - `build_system_prompt(document_state)`: 支持注入文档状态上下文
   - `_build_document_context()`: 格式化当前文档对象列表
   - 修复 max_tokens 从 200000 改为 4096（适配阿里云 API 限制）
5. `planner.py` - `generate_plan()` 传递 document_state 到 LLM
6. `main.py` - `/agent/plan` 路由改为调用 graph agent：
   - 构建 input_state，调用 `agent.invoke()`
   - 处理校验失败和错误状态映射

**架构**: parse_input→plan→validate→(条件)→end/retry，最多重试2次。重试时将错误信息注入 user_input 让 LLM 自我纠正。

**验证结果**:
- ✓ 8个单元测试全部通过（校验正确plan、错误工具名、缺少参数、类型错误、路由逻辑）
- ✓ API 端点测试通过（POST /agent/plan 返回 LLM 生成的 plan）
- ✓ 完整 graph 执行测试通过（从输入到最终状态的全链路）

## 2026-05-31: 去掉 Spec 前置，纯 Plan 闭环 + 全步 LLM 调试

**目标**: 取消 FreeCAD 执行链中的 spec/impact/recipe；全局 plan 后 Cursor 式逐步推进；调试记录每步 LLM 输入/输出。

**改动**:
1. **FreeCAD**: `panel`/`agent_runner` 直接 `start_plan`，删除 harness 四段式前置
2. **start_plan**: 始终从 phases 构建 abstract step queue，不再走 recipe 分支
3. **next_step**: 统一 LLM 生成 tool_calls（移除 cad_spec 确定性分支）
4. **evaluate_step**: 每步必调 LLM（附带确定性校验/validator 结果）；成功且 `phase_status=completed` 时推进 queue
5. **高层 plan prompt**: 只输出意图级阶段，禁止预先展开尺寸/工具

**调试**: 单 session 目录下 `001_start_plan`、`00N_next_step_*`、`00N_evaluate_step_*` 均含 `llm_01_*.md`（evaluate 成功路径亦有）。

## 2026-05-31: 空间定位最小修复（车轮朝向 + 贴附 + bbox）

**问题**: `set_placement` 把 rot 当 YPR 导致 rot_x=90 车轮仍竖直；bbox 用局部 BoundBox 与旋转不一致；车灯只贴 x 未对齐 y/z；validator 成功仍报 not found。

**改动**:
1. **FreeCAD**: `_helpers.apply_axis_rotation` + `set_placement`/`create_cylinder(rot_*)` 绕轴旋转；`document_state` 改 `getBoundBox()` 世界坐标，过滤 Origin/Axis 噪声
2. **LLM**: `_build_document_context` 输出 x/y/z 范围 + 贴面/车轮/pos 角点规则
3. **validators**: `verify_object_exists` 成功 message 修正；**trace**: `open_existing` 不再覆盖 session_summary

## 2026-05-31: development_plan 关键时刻 + Pull 链路 rationale

**改动**: Version Roadmap 增「关键时刻/版本依赖链/设计原则(Codex+SW 对照)」；V0.8–V0.11 各节补「为什么」与上下游；8.3 明确 Push→Pull query-before-act；exit criteria 阻塞 V0.9；修复文档转义损坏。

## 2026-05-31: SessionMemory 四层工作记忆

**问题**: history 是流水账，prompt 只取 recent[-5] 与 runner 发 20 条不一致；query_result 未结构化进 prompt；失败无 avoid_repeating。

**改动**:
1. **FreeCAD** `session_memory.py` + `AgentSession.record_tool_result/refresh_memory_from_document`：working/object/error/query_cache/progress/long_summary
2. **Agent** `app/memory/` prompt 格式化 + history 回退 pack；`next_step`/`evaluate_step` 收 `session_memory`；prompt 改读 memory pack + 紧凑 object 索引（非全量 document_state）
3. **query_policy**: `query_cache_covers_target` 优先于 history 扫描

## 2026-05-31: 解绑 tool use 类别限制

**问题**: abstract step / recipe 的 `allowed_tool_categories` 仅列 6 类；category 推断默认 `primitives`；prompt 未明确 sketch/partdesign/surface/assembly 可用。

**改动**:
1. `tool_registry`: `ALL_TOOL_CATEGORIES`、`resolve_tool_specs_for_prompt()` 默认全量 46 工具；未匹配任务推断回退全类别
2. `build_queue_from_phases` / recipes: `allowed_tool_categories=[]` 表示不限
3. prompt 注入 category summary + 全量 spec；next_step 规则明确可用全部 registry 工具

## 2026-05-31: 取消每步 1-3 个 tool call 上限

**改动**: `llm_provider` next_step prompt 去掉 1-3 限制，允许一步批量（如四轮子同批）；`development_plan` 设计原则同步。