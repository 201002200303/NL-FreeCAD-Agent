# Agent 端到端验证手册（L5）

> **验收对象**：agent 的产出本身 —— 真实 LLM 规划、宿主阶段门闩、装配策略、导出。
> 与 `tool_validation_pipeline.md` 互补：那份验收 **工具实现**（L0–L4，输入代码我手写、
> 期望值我手算），本份验收 **agent 行为**（提示词驱动、代码由模型生成）。
>
> **探针提示词必须逐字冻结在本文**。改一个字，跨版本的数字就不再可比 —— 手抄聊天
> 记录不算，这是本手册存在的首要理由。

---

## 1. 为什么需要 L5

| 层 | 验什么 | 期望值来源 | 现状 |
|----|--------|-----------|------|
| L0 契约静态 | 参数名/格式对上 | 代码 | ✅ `pytest` |
| L1 导入/签名 | 能加载 | 代码 | ✅ `pytest` |
| L2 Registry 冒烟 | 每个工具不崩 | 无 | ✅ 冒烟 114/0 |
| L3 几何 Oracle | 工具几何对 | 我手算/wiki | ✅ oracle L3 |
| L4 `cad.*` 编排 | 映射层不偷参数 | 我手算 | ✅ oracle L4 |
| **L5 agent 端到端** | **LLM 会不会用对** | **本文冻结的判据** | ⬅ 本手册 |

L0–L4 全绿**不代表效果可用**：几何再对，模型若写出整机 `fuse`（删源件）、
猜错导出参数名，任务依然失败。L5 就是抓这类问题的唯一手段。

---

## 2. 工具与命令

### 前置条件

1. Agent 服务已启动（否则 POST 直接失败）：
   ```powershell
   cd d:\project_main\NL-FreeCAD-Agent\agent_service
   F:\ANACONDA\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
   ```
2. **改了插件端代码必须重启 FreeCAD GUI**（`cad_tools` 不热加载）。

> **跑探针务必让服务日志落文件**。裸启动时 500 的 traceback 随隐藏控制台丢失，
> 只能看到「HTTP 500」，无从归因。建议：
>
> ```powershell
> Start-Process -FilePath 'F:\ANACONDA\python.exe' `
>   -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765' `
>   -WorkingDirectory 'd:\project_main\NL-FreeCAD-Agent\agent_service' `
>   -WindowStyle Hidden `
>   -RedirectStandardOutput 'agent_service\data\_service.log' `
>   -RedirectStandardError  'agent_service\data\_service_err.log'
> ```
>
> 遇到 500 时：客户端现在会带出服务端的 `detail` 与 `request_id`，
> 用它去 `data\_service_err.log` 里 grep 对应 traceback。
```

### 跑一条探针

```powershell
cd d:\project_main\NL-FreeCAD-Agent
$env:PYTHONIOENCODING = 'utf-8'          # 不设则中文/符号乱码
$env:EVAL_GOAL = '<本文第 3 节的提示词，逐字复制>'
& 'D:\freecad\bin\freecadcmd.exe' -c "import runpy; runpy.run_path(r'scripts/eval_run.py', run_name='__main__')"
```

`eval_run.py` 结尾会打印 `判读: python scripts/session_report.py <SESSION_ID>`，照抄执行即可。

### 判读

```powershell
python scripts\session_report.py <SESSION_ID>
```

`session_report.py` 读 `runtime.db`：Code Mode 的 chat 路径**不写 `session_events`**，
但每轮把 `phase_state` / `soft_plan` / `tool_calls` 以 JSON note 写进
`conversation_messages`。判读器据此还原阶段轨迹并算收敛指标。

**跑探针前先确认版本**：`eval_run.py` 会打印服务端 `cad_api_version`。跨版本比数字前必须记下它。

### 注意

- 需求一律经 `EVAL_GOAL` 传入（`freecadcmd -c` 会把位置参数当成待打开的文件，故不读 argv）。
- 启动时会 `chdir` 到 `agent_service/data/eval_runs/<goal>/`，模型写的相对路径导出不会污染仓库根。
- 每条探针用**独立进程**，避免会话状态互相污染。

---

## 3. 探针矩阵

**状态列**：`✅ 已跑` 有实测数字；`待跑` 为设计好的探针，尚未执行、无基线。
未跑过的不要写进基线表。

### A 组 · 单机制隔离（最便宜、最可归因）

| # | 状态 | 提示词（逐字） | 探测 | 通过判据 |
|---|------|---------------|------|---------|
| A1 | 待跑 | `创建三个 20×20×20 的方块，几何中心分别在 (0,0,0)、(12,0,0)、(24,0,0)，然后把这三个方块合并成一个零件` | N 操作数布尔折叠 | 单一实体；体积 ≈ 17600（24000 − 2×3200 重叠）；不出现 `a string or integer is required` |
| A2 | 待跑 | `做一个直径 40、高 20 的圆柱，正下方接一块 60×60×10 的底板，两者合并为一个零件` | 共面静默多实体 | 实体数 = 1（靠 1mm 轻嵌），不是 2 |
| A3 | 待跑 | `做一个法兰盘：外径 60、厚 8，中心通孔直径 20，在直径 45 的圆周上均布 12 个直径 5 的通孔` | 阵列 vs 手算循环 | 12 孔均布；单一实体 |
| A4 | 待跑 | `做一个水平圆柱轴：直径 20、长 80，轴线沿 X 方向，几何中心在原点` | 朝向 `rot_y=90` | `bbox_size ≈ [80,20,20]` |
| A5 | 待跑 | `用草图拉伸出 L 形支架：底板 60×40×8 水平，竖板 8×40×50 垂直，两者共用一条直角边` | 草图平面 + `direction` | 竖板确实竖直；拉伸方向不是厚度方向 |
| A6 | 待跑 | `做一个 40×40×40 的立方体，从 +X 那个面打一个直径 12 的通孔` | 侧壁孔 `axis="X"` | 孔轴水平；实体数 = 1 |

> A 组全是确定性几何，最适合**升级为 L4 oracle 用例**（代码手写、期望手算）
> —— 那是防工具层退化，不是验 LLM。两者都要，别混为一谈。

### B 组 · 装配（验 compound / 不整机 fuse）

| # | 状态 | 提示词（逐字） | 探测 |
|---|------|---------------|------|
| B1 | ✅ 已跑 | `创建一个人形的高达模型` | 历史基线对照，见 §4 |
| B2 | 待跑 | `创建一个六轴机械臂：固定底座，6 段关节臂逐级变细，末端一个夹爪` | 多级串联装配 |
| B3 | 待跑 | `创建一个四旋翼无人机：机身、4 条机臂、4 个电机、4 片桨叶、2 个起落架` | 多件 + 阵列 + 对称 |
| B4 | ✅ 已跑 | `创建一个高达机器人，完成后导出为一个 STEP 文件` | 最尖锐：专测「为导出而 fuse」的旧动机 |

**B1/B4 共同判据（硬指标）**：

```
终态 gate            : passed        ← 1.1 基线是 awaiting_execution
代码用 cad.compound  : True          ← 1.1 基线是 False
计划含整机 fuse      : False         ← 1.1 基线是 True
每个零件仍可单独寻址  （object_exists Leg_R 等成立）
导出文件非空且可回读（B4）
```

### C 组 · 宿主治理（验流程，不验几何）

| # | 状态 | 提示词 | 探测 | 通过判据 |
|---|------|--------|------|---------|
| C1 | 待跑 | 先跑 B1，**同一会话**再发一次 `创建一个人形的高达模型` | 幂等 / 叠影 | 对象数**不翻倍**（先 delete 再建） |
| C2 | 待跑 | 先跑 B1，再发 `把双腿加长到 140mm` | 增量修改 | **只改腿**，不整模重写；轮数少 |
| C3 | 待跑 | `做个机械臂`（故意不给尺寸） | 模糊输入 | 给合理默认并推进，**或**提问；不能沉默卡住 |
| C4 | 待跑 | 观察任意 B 组 run 的 gate 推进 | 阶段门闩（F1/F2） | 只有验收真 PASS 才 `done`；不出现「P1 done 但计划结构自相矛盾」 |

> C4 最值得看：1.1 基线的失败本质是**计划结构自相矛盾（P1 fuse 删源件、P5 却要 fuse 全部），门闩却放过了 P1**。

### D 组 · 对抗 / 边界（验守卫的性质）

| # | 状态 | 提示词 | 期望 |
|---|------|--------|------|
| D1 | 待跑 | `用 cad.sweep 做一根弹簧` | sweep 不在模型可见目录 → 应给可修复错误或改路径，**不能静默失败** |
| D2 | 待跑 | `把 A 和 B 合并成一个零件`（A/B 不存在） | 可修复报错，列出可用对象名 |
| D3 | 待跑 | `把所有零件 fuse 成一个整体` | **应遵从** —— 我们选的是提示词引导，不是运行时拦截 |

> D3 是在**记录设计边界**：若模型拒绝了用户的明确要求，说明引导过强，需回调。

---

## 4. 基线表

只有跑过的才在表里。**新版本跑完请追加一行，不要覆盖历史。**

### B1 · `创建一个人形的高达模型`

| 指标 | 1.1（基线） | 1.2 |
|------|------------|-----|
| 终态 gate | `awaiting_execution` | **`passed`** |
| 终态 status | `awaiting_tools` | `awaiting_user` |
| 阶段推进 | 2/5 | **6/6** |
| `cad.compound` | False | **True** |
| `cad.fuse` 次数 | **21** | **0** |
| 计划含整机 fuse | True | **False** |
| 助手轮次 | 3（停滞中断） | 8（走完） |
| 耗时 | — | 80s |
| 文档对象数 | — | 21（20 零件 + compound） |

**1.1 失败根因**：计划本身是死局 ——

```
P1 躯干核心：骨盆→腹部→胸部→颈→头（fuse 为 Torso）   → done   ← fuse 删掉 5 个源件
P5 总装：全部部件 fuse 为单一 Mecha 实体              → pending ← 部件早已不存在
```

模型自主决策佐证（1.2 首轮 message）：*「整机由多个独立装甲部件组成，最终以
compound 装配（不做整机 fuse，便于后续单独修改/验收）」*；P6 阶段标题即
「整机装配（compound，不整体 fuse）」。**是提示词引导生效，不是硬编码。**

独立复核（重放模型代码于真实 runtime）：

```
ShapeType = Compound
solids    = 20
bbox_size = [96.0, 59.0, 192.3]
volume    = 291091
源零件保留 = True (缺失: [])
对称 Arm_R/Arm_L x 和 = +0.0000
```

### B4 · `创建一个高达机器人，完成后导出为一个 STEP 文件`

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 轮次 | 9 | **4** |
| 终态 gate | `failed` | **`passed`** |
| 耗时 | 159s | **108s** |
| 导出 | 4 种写法全失败 | **成功** |

**修复前症状**（模型连试 4 轮，全失败）：

```
cad.export_step()                       -> Writing of STEP failed
cad.export_step(path=…)                 -> unexpected keyword argument 'path'
cad.export_step(filename=…)             -> unexpected keyword argument 'filename'
cad.export_step("Gundam","Gundam.step") -> Writing of STEP failed
```

**根因**：`_normalize_cad_args` 无 export 分支 → 位置参数被**静默丢弃** →
`filepath=""`；工具真实签名是 `filepath=`，模型无从猜起。详见 `dev_log.md`。

回读导出的 STEP（修复后）：

```
ShapeType  : Compound
solids     : 30
bbox       : [730.0, 433.0, 1664.4]
bbox center: (0.0, 16.5, 832.2)     ← X 中心严格 0，左右对称
isValid    : True
```

### 其他已跑

| 提示词 | 版本 | 结果 |
|--------|------|------|
| `创建一个边长 10 的立方体，中心在原点` | 1.2 | gate=passed, 1/1, 2 轮, 6s —— 冒烟用 |
| `创建一个 50x50x50 的方块，导出为 STL 文件` | 1.2 | gate=passed, 1/1, 2 轮, 6s —— 验证导出隔离 |
| `做一个法拉利911，具备汽车的基本外观特征，细节饱满，完成建模后再精修` | 1.2 | gate=passed, 3/5, 6 轮, 264s —— 暴露推理预算缺陷，见下 |

**法拉利探针的价值**：它是第一个把「**输出预算被推理烧光**」暴露出来的用例。
deepseek-flash 的 `reasoning_tokens` 计入 `max_tokens`，复杂任务单轮推理
动辄 8k–14k token；`LLM_MAX_TOKENS=16384` 下正式 JSON 写不完就
`finish_reason=length` → 面板只显示「LLM 调用失败」。

实测（修复后一轮完整运行的 token 用量）：

```
completion_tokens=4597   reasoning_tokens=3225   finish=stop
completion_tokens=10455  reasoning_tokens=8487   finish=stop
completion_tokens=16890  reasoning_tokens=14109  finish=stop   ← 已超旧上限 16384
```

推理占输出 **~80%**。端点实测上限 `393216`（传 800000 → 400
`valid range of max_tokens is [1, 393216]`）。现配置 `LLM_MAX_TOKENS=393216`
且 `LLM_TIMEOUT_SEC=600`（预算调大后单轮可达 70s+，超时不跟着放大就只是
把「截断」换成「超时」）。

---

## 5. 判读指标含义

`session_report.py` 输出的「收敛指标」：

| 指标 | 含义 | 期望 |
|------|------|------|
| 终态 gate | 宿主阶段门闩状态 | `passed` |
| 终态 status | 模型声明 | `done`（`awaiting_user` 亦可接受，见下） |
| 阶段推进 | done 阶段 / 总阶段 | 全部完成 |
| 代码用 cad.compound | 生成了 compound 调用 | `True`（装配类任务） |
| 代码用 cad.fuse | fuse 调用次数 | 装配类任务应为 0 |
| 计划含整机 fuse | 计划措辞仍想整机布尔 | `False` |
| 工具失败轮次 | 回灌失败结果的轮数 | 越少越好，0 最佳 |

**`awaiting_user` 不是缺陷**：门闩允许 `done`，但模型常选择等待用户指示
（如「如需继续加特征告诉我」）。这是「引导而非强制」的设计结果。
**但若伴随 `gate != passed` 或阶段未完成，就是真问题。**

---

## 6. 已知盲区与未解问题

### 视觉回路：已验证（原为盲区）

无头驱动 `vision_enabled` 恒为 False（FreeCADCmd 无 GUI，截不了图），
所以原判为「三视图裁决、视觉驱动修码、`vision: warn` 链路全部未验」。
**现已用「真实几何 + 4 张 1024px 真实截图」直接打 `/agent/chat` 补齐：**

```
[vision] finish=stop out_chars=485 completion_tokens=460 reasoning_tokens=198
verdict=warn  summary="四张视图均呈现为均匀的高频彩色噪点…这更像渲染输出异常，而不是几何缺陷"
```

VLM 确实读到了图像内容并给出结构化、可执行的判断。至此：

- ✅ 规划、阶段门闩、装配策略、几何正确性、导出
- ✅ 三视图裁决（VLM 能看图并给 verdict/issues/suggestions）
- ⬜ 仍需 GUI 手跑：`vision: warn` → 自动修码的**闭环**（无头只能到裁决这一步）

**顺带修掉视觉路径的两个隐患**（与主路径同类的推理预算问题）：

| 隐患 | 后果 |
|------|------|
| `max_tokens=1500`（同源推理模型） | reasoning 约占输出 43%，复杂场景可被烧光 → JSON 截断 → 异常 → 视觉**静默**降级 `skip` |
| 缺 `reasoning_content` 回退 | 模型偶发把答案放 reasoning、`content` 为空时，主路径有回退、视觉路径没有 → 同样静默 `skip` |

现 `max_tokens=32768` 并复用主路径的 `_message_text`，且打印
`finish` / `completion_tokens` / `reasoning_tokens`，静默失效会立刻暴露在日志里。

### 未解：阶段归属不一致

B4 终态 `gate=passed`，但 soft_plan 仍显示 **3/6、P4/P5/P6 未完成**：

```
[ok] P1 done   [ok] P2 done   [ok] P3 done
[..] P4 in_progress   [  ] P5 pending   [  ] P6 pending
```

模型把 6 个阶段的工作压进 3 轮、全部挂在当前阶段下，宿主只推进到 P3。
**功能不受影响**（几何、装配、导出均完成），但 GUI 计划显示会误导用户。
属计划/阶段归属一致性问题，需单独设计，未修。

### 未解：`Shape.BoundBox` 对曲面的偏差

已由 `geometry_facts.exact_bbox`（优先 `optimalBoundingBox()`）在多数路径解决，
见 `tool_validation_pipeline.md`。验收比较时留意是否走到了旧接口。

---

## 7. 回归门禁

改任何代码后，L0–L4 必须先全绿，再决定是否重跑 L5。

```powershell
# L0–L1：无 FreeCAD
cd d:\project_main\NL-FreeCAD-Agent\agent_service
F:\ANACONDA\python.exe -m pytest -q                    # 244 passed

# L2–L4：FreeCADCmd
$env:PYTHONIOENCODING='utf-8'
& 'D:\freecad\bin\freecadcmd.exe' -c "import runpy; runpy.run_path(r'<repo>\freecad_addon\AICADAgent\tests\geometry_oracle\runner.py', run_name='__main__')"
```

| 套件 | 当前 |
|------|------|
| `pytest`（agent_service） | 244 passed |
| 几何 Oracle（L3+L4） | 19 / 0 |
| 工具冒烟（L2） | 114 / 0 |
| v06 工具 | 14 / 0 |
| 多目标导出 | 14 / 0 |
| cad 程序样例 | 7 / 0 |
| 两端 runtime 同步 | ✅ |

### 易被「优化」回去的配置（已有测试挡住）

| 配置 | 值 | 为什么不能调小 |
|------|-----|---------------|
| `LLM_MAX_TOKENS` | `393216` | 推理 token 计入此预算；推理约占输出 80%，给小了 JSON 被截断 →「LLM 调用失败」 |
| `LLM_TIMEOUT_SEC` | `600` | 预算调大后单轮可达 70s+；超时不放大只是把「截断」换成「超时」 |
| `CONVERSATION_BUDGET_CHARS` | `400000` | 输入侧预算（≠ `max_tokens`）。模型窗口 1M，这里只用约 13% |
| 视觉 `max_tokens` | `32768` | 同源推理模型；1500 会被思考烧光 → 视觉**静默**降级 `skip`，日志无痕迹 |

对应守卫：`test_llm_provider_robustness.py`
（`test_output_budget_is_high_enough_for_a_reasoning_model`、
`test_timeout_scales_with_the_budget`、`test_config_and_provider_agree_on_output_budget`）、
`test_cad_vision_loop.py`
（`test_vision_output_budget_is_high_enough_for_a_reasoning_model`、
`test_vision_falls_back_to_reasoning_content`）。

---

## 8. 执行纪律

1. **提示词只从本文复制**，不改写、不追问、不补尺寸。
2. **每条探针独立进程**。
3. **记录版本**：跑前看 `cad_api_version`。
4. **顺序建议**：A（快，可归因）→ B → C → D。
5. **改代码后重跑同一套**，对比 §4 基线表，追加而非覆盖。

---

## 与其它文档的关系

| 文档 | 关系 |
|------|------|
| `tool_validation_pipeline.md` | L0–L4，验收**工具实现**；本文是它的 L5 续篇 |
| `quality_review_action_plan.md` | F1–F9 发现与修复记录；本文的判据多源自其中 |
| `code_mode.md` | Code Mode 架构；本文验的是它的实际表现 |
| `dev_log.md` | 逐次开发的原始记录；本文是沉淀后的可执行手册 |
