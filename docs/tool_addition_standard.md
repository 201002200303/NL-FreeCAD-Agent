# CAD 工具新增与验收标准

> 本文是后续新增工具的唯一执行规范。  
> 工具数以 `TOOL_SPECS` / `TOOL_REGISTRY` 对齐为准（当前约 54 个）。  
> 相关旧文：`docs/tool_design.md`（分层思想）、`docs/api_contract_v08.md`（API 契约）。

---

## 1. 工具在系统里的位置

本项目是双进程架构：**Agent Service 只声明工具契约；FreeCAD 插件真正执行。**

```
LLM (next_step)
  → tool_call JSON { call_id, tool, args, expected_effect }
  → Agent Service 校验 TOOL_SPECS / query_policy
  → FreeCAD AgentRunner 收到 tool_calls
  → CadToolExecutor.execute_tool_call()
  → TOOL_REGISTRY[tool](doc, **args)
  → 返回统一 result → evaluate_step
```

| 角色 | 路径 | 职责 |
|------|------|------|
| **实现（执行侧）** | `freecad_addon/AICADAgent/cad_tools/*.py` | FreeCAD API 真实操作 |
| **注册（执行侧）** | `freecad_addon/AICADAgent/cad_tools/__init__.py` → `TOOL_REGISTRY` | 名字 → Python 函数 |
| **调度** | `freecad_addon/AICADAgent/executor.py` | 事务、name_map、幂等、统一返回 |
| **契约（服务侧）** | `agent_service/app/tools/tool_specs.py` → `TOOL_SPECS` | 给 LLM 看的参数 schema |
| **分类** | `agent_service/app/tools/tool_registry.py` → `TOOL_CATEGORIES` | 类别树 / 关键词推断 |
| **查询门禁** | `agent_service/app/tools/query_policy.py` | 空间危险操作是否先 query |
| **验收** | `agent_service/app/evaluation/validators.py` | 可选硬几何校验 |

**铁律：`TOOL_SPECS` 的 key 集合必须与 FreeCAD `TOOL_REGISTRY` 的 key 集合完全一致。**  
缺一边会导致「LLM 规划了但执行 Unknown tool」或「能执行但 LLM 不知道」。

---

## 2. 工具分类（写进哪个文件）

| 类别 | FreeCAD 模块 | 典型工具 | 说明 |
|------|--------------|----------|------|
| `primitives` | `primitive_tools.py` | create_box / cylinder / sphere… | 创建基本体 |
| `boolean` | `boolean_tools.py` | boolean_fuse / cut / common | 布尔 |
| `features` | `feature_tools.py` | fillet / chamfer / cut_hole / mirror | 特征 |
| `transform` | `transform_tools.py` / `placement_tools.py` / `modify_tools.py` | move / align / set_placement… | 变换与相对定位 |
| `query` | `query_tools.py` | get_object_detail / measure_gap… | **只读**，`kind=query` |
| `sketch` | `sketch_tools.py` | create_sketch / sketch_add_* | 草图 |
| `partdesign` | `partdesign_tools.py` | pad / pocket / revolve… | PartDesign |
| `surface` | `surface_tools.py` | loft / sweep / revolve | 曲面 |
| `assembly` | `assembly_tools.py` / `compound_tools.py` | create_assembly / mate_* / make_compound | 装配（compound=不做布尔的整机组合） |
| `export` | `export_tools.py` | save_fcstd / export_step / stl | 导出 |

新增时优先放入已有模块；只有新领域才新建 `xxx_tools.py`。

共享逻辑放 `cad_tools/_helpers.py`（`get_object` / `get_shape` / `assign_shape_result` / 拓扑选择等），禁止在工具里复制粘贴取对象代码。

---

## 3. 函数签名与返回约定

### 3.1 签名（强制）

```python
def my_tool(doc, *, name="...", target="", **kwargs) -> dict:
    """一句话说明。参数用关键字为主，默认值写在签名里。"""
    ...
```

- **第一个参数必须是 `doc`**（`FreeCAD.Document`），由 executor 注入。
- 其余参数与 `TOOL_SPECS.parameters` **同名**。
- LLM 传来的 `args` 会 `**` 展开；不要用 `*args` 位置参数。
- 对象引用字段优先用约定名：`target` / `base` / `tool` / `sketch` / `reference` / `name` / `result_name` 等（见 §6）。

### 3.2 Act 工具返回（修改文档）

最少字段：

```python
{
    "tool": "my_tool",          # 工具名
    "object": "ResultName",     # 主结果对象 FreeCAD.Name（必填，有产出时）
    "source": "OldName",        # 可选：被替换/隐藏的源对象名 → 触发 name_map
    "type": "Part::Feature",    # 可选：结果类型
    # 其他诊断字段随意，但必须 JSON 可序列化
}
```

Executor 会自动补：`status=success`、`call_id`、`produced_objects`、`name_map_update`。

**name_map 规则**：若 `source` 与 `object` 不同，后续步骤里旧名会自动改写成新名。生成新对象并隐藏源时务必设置 `source`。

### 3.3 Query 工具返回（只读）

必须：

```python
{
    "kind": "query",                 # 强制：否则会被当 act，进幂等缓存/改 name_map
    "tool": "get_object_detail",
    "query_target": "Body",          # 或 query_targets: ["A","B"]
    "query_result": { ... },         # 结构化事实；bbox 尽量带 size+center
}
```

建议用 `_query_result(...)` 辅助（见 `query_tools.py`）。  
**bbox 不完整不算覆盖 query 要求**（`has_spatial_facts` 需要 size+center）。

### 3.4 错误处理

- 参数非法 / 对象不存在 → `raise ValueError("清晰中文或英文原因")`。
- Executor 会 `abortTransaction`，返回 `status=error` + `message`。
- **不要**吞掉异常后假装成功；**不要**在失败路径半改文档还不抛错。

---

## 4. 服务侧 Spec 写法

在 `agent_service/app/tools/tool_specs.py` 增加一项：

```python
"align_objects": {
    "description": "一句话 + 何时优先用（给 LLM 看）",
    "parameters": {
        "target": {"type": "string", "description": "要移动的对象"},
        "reference": {"type": "string", "description": "参考对象"},
        "axis": {"type": "string", "default": "z", "description": "x/y/z"},
        "mode": {"type": "string", "default": "stack", "description": "min/max/center/stack"},
        "offset": {"type": "float", "default": 0, "description": "额外间隙 mm"},
    },
    "required": ["target", "reference"],
},
```

约定：

| 字段 | 要求 |
|------|------|
| `description` | 写清语义 + 与相近工具的区别（如「优先于 set_placement」） |
| `parameters.*.type` | `string` / `float` / `int` / `bool` / `array` |
| `default` | 可选参数必须有默认值，且与 Python 签名一致 |
| `required` | 仅列无默认值的必填项 |
| 单位 | 长度默认 mm；角度默认度；在 description 里写明 |

然后在 `tool_registry.py` 的对应 `TOOL_CATEGORIES[...]["tools"]` 列表中加入名字；若有中文/英文触发词，补到 `infer_categories_for_task` 的关键词表。

---

## 5. 如何调用（三层）

### 5.1 LLM / Agent 闭环（主路径）

`POST /agent/next_step` 返回：

```json
{
  "decision": "execute",
  "tool_calls": [
    {
      "call_id": "P2_S1",
      "tool": "align_objects",
      "args": {
        "target": "Wheel_FL",
        "reference": "Body",
        "axis": "z",
        "mode": "stack",
        "offset": 0
      },
      "description": "把前左轮贴到车身底面",
      "expected_effect": {
        "validators": ["verify_touching"],
        "touching": {"obj_a": "Body", "obj_b": "Wheel_FL", "axis": "Z"}
      }
    }
  ]
}
```

FreeCAD `AgentRunner` 对每个 call 调 `executor.execute_tool_call(tool_call)`。

### 5.2 插件内直接调用（调试）

```python
from AICADAgent.executor import CadToolExecutor
ex = CadToolExecutor()
ex.execute_tool_call({
    "call_id": "manual_1",
    "tool": "create_box",
    "args": {"name": "Box1", "length": 10, "width": 10, "height": 10},
})
```

或绕过 executor（无事务/无幂等，仅单元测试）：

```python
from AICADAgent.cad_tools import TOOL_REGISTRY
TOOL_REGISTRY["create_box"](FreeCAD.ActiveDocument, name="Box1", length=10, width=10, height=10)
```

### 5.3 旧 Plan API（兼容）

`POST /agent/plan` 仍可能产出逐步 plan；最终仍落到同一 `TOOL_REGISTRY`。新工具不必单独适配旧 API，只要名字在 registry 即可。

---

## 6. 参数命名与 name_map

### 6.1 常用参数名

| 参数 | 含义 |
|------|------|
| `name` | 新建对象名（create_* / boolean_* / pad_*） |
| `result_name` | 可选结果名（scale / fillet / cut_hole） |
| `target` | 被操作的已有对象 |
| `base` / `tool` | 布尔被切体 / 刀具 |
| `reference` | 相对定位参考 |
| `sketch` / `body` / `profile` / `path` | 草图链依赖 |
| `pos_x/y/z` | 绝对位置（Box 为最小角；Cylinder 底面圆心；Sphere 球心） |
| `rot_x/y/z` | 绕固定轴旋转（度），**不是**欧拉 YPR |
| `dx/dy/dz` | 相对位移 |

### 6.2 会参与 name_map 改写的字段

`executor.py` 中 `_NAME_REF_FIELDS`：

```text
target, base, tool, sketch, body, part, part1, part2, assembly, profile, path
```

若新工具用了新的「对象名字段」（如 `reference`），**必须**把该字段加入 `_NAME_REF_FIELDS`，否则恢复会话/重命名后会找不到对象。

`query_policy.TARGET_FIELDS` 也要同步（用于 query-before-act 提取引用对象）。

### 6.3 call_id 与幂等

- 每个 tool_call 必须有唯一 `call_id`。
- Act 成功后同 `call_id` 重放会被跳过（`skipped_duplicate`）。
- Query 不进幂等缓存，可重复查询。

---

## 7. Query-before-act 与风险工具

若工具属于「空间/拓扑敏感」（依赖当前 bbox、面、边、间隙），加入：

`agent_service/app/tools/query_policy.py`

- `RISKY_TOOLS`
- `QUERY_BY_TOOL`（建议先 `get_object_detail` 或 `list_topology`）

批内规则（已实现）：同 batch 里**更早** create 产出的名字，不算幽灵对象，不强制 query。  
前向引用（先用后建）仍会报 `QUERY_REQUIRED`。

---

## 8. 新增工具标准流程（Checklist）

按顺序做，全部勾完才算完成。

### A. 设计

- [ ] 单一职责：一个工具只做一件可验证的事
- [ ] 与现有工具不重叠；若重叠，在 description 写清「优先用哪个」
- [ ] 确定类别、Python 文件、是否 query
- [ ] 列出参数 / 默认值 / required
- [ ] 写清失败模式（对象不存在、尺寸非法、拓扑不满足）

### B. 实现（FreeCAD）

- [ ] 在对应 `*_tools.py` 实现 `func(doc, **args) -> dict`
- [ ] 用 `_helpers.get_object` / `get_shape`；改 Shape 优先 `assign_shape_result`
- [ ] Act：返回 `object`（及需要时的 `source`）
- [ ] Query：返回 `kind=query` + `query_result`（bbox 尽量含 size/center）
- [ ] 非法参数 `raise ValueError`
- [ ] 注册到 `cad_tools/__init__.py` 的 `TOOL_REGISTRY`

### C. 契约（Agent Service）

- [ ] `tool_specs.py` 增加同名 spec
- [ ] `tool_registry.py` 加入类别列表 + 必要关键词
- [ ] 若引用新对象字段：更新 `executor._NAME_REF_FIELDS` 与 `query_policy.TARGET_FIELDS`
- [ ] 若空间敏感：更新 `RISKY_TOOLS` / `QUERY_BY_TOOL`
- [ ] 若需引导 LLM：在 `llm_provider` 空间规则/工具说明中加一句（可选但推荐）

### D. 测试与计数

- [ ] 更新 `agent_service/test_tool_registry.py` 中工具总数断言
- [ ] 可选：FreeCAD 内 smoke 脚本放 `freecad_addon/AICADAgent/tests/test_<tool>.py`
- [ ] 跑：`python -m pytest test_tool_registry.py -q`
- [ ] 确认 `len(TOOL_SPECS) == len(TOOL_REGISTRY)`（两边各自统计）

### E. 文档与日志

- [ ] `dev_log.md` 顶部记一条：工具名、用途、数量变化
- [ ] 复杂工具在本文件或 `tool_design.md` 补一句使用注意

---

## 9. 验收标准（Definition of Done）

新工具必须同时满足：

| # | 标准 | 如何验 |
|---|------|--------|
| 1 | **双侧注册一致** | specs key == registry key |
| 2 | **可被 LLM 看见** | next_step system prompt 的工具列表含该工具 |
| 3 | **可被执行** | FreeCAD 中 `execute_tool_call` 返回 `status=success` |
| 4 | **事务安全** | 故意非法参数 → `status=error`，文档无脏状态 |
| 5 | **返回契约正确** | Act 有 `object`；Query 有 `kind=query` |
| 6 | **name_map 不丢** | 产生替换对象时带 `source`；引用字段在 `_NAME_REF_FIELDS` |
| 7 | **空间工具可感知** | 危险操作已进 query_policy；query 结果含可用空间事实 |
| 8 | **单元测试更新** | `test_tool_registry` 通过；有专项测则一并通过 |
| 9 | **不写死绝对坐标偏好** | 定位类优先相对 API；description 写明 |
| 10 | **幂等友好** | 依赖稳定 `call_id`；不在工具内自造随机名导致无法重放理解 |

**不达标的典型反例：**

- 只改了 FreeCAD 没改 `TOOL_SPECS`
- Query 忘了 `kind=query`，被当成 act 缓存
- 返回 FreeCAD 对象 / Vector 等不可 JSON 序列化字段
- 用 `Edge1` 硬编码却不提示先 `list_topology`
- 新建对象不隐藏源，导致视觉重叠且 name_map 断裂

---

## 10. 推荐的可选验收器

在 `expected_effect.validators` 中声明（默认 warning，strict 才阻断）：

| Validator | 用途 |
|-----------|------|
| `verify_object_exists` | 结果对象存在 |
| `verify_shape_valid` | Shape 有效 |
| `verify_grounded` | zmin≈0 |
| `verify_touching` | 两体间隙 |
| `verify_no_overlap` | bbox 过度重叠 |
| `verify_size_close` | 尺寸误差 |
| `verify_attachment_gap` | 贴附间隙 |
| `verify_orientation` | 主轴/薄轴朝向 |

新工具若有明确几何承诺，应在 description 或示例 `expected_effect` 中示范如何挂 validator。

---

## 11. 最小新增模板

### FreeCAD：`cad_tools/my_tools.py`

```python
from AICADAgent.cad_tools._helpers import get_object, get_shape


def my_tool(doc, target="", factor=1.0):
    if float(factor) <= 0:
        raise ValueError("factor must be > 0")
    obj = get_object(doc, target)
    shape = get_shape(obj)
    # ... 修改或生成 ...
    return {
        "tool": "my_tool",
        "object": obj.Name,
        "source": target,   # 若生成了新对象则填旧名，否则可省略
    }
```

### 注册

```python
# cad_tools/__init__.py
from AICADAgent.cad_tools.my_tools import my_tool
TOOL_REGISTRY["my_tool"] = my_tool
```

### Spec

```python
# tool_specs.py
"my_tool": {
    "description": "...",
    "parameters": {
        "target": {"type": "string", "description": "目标对象"},
        "factor": {"type": "float", "default": 1.0, "description": "..."},
    },
    "required": ["target"],
},
```

### 分类

```python
# tool_registry.py → TOOL_CATEGORIES["transform"]["tools"] 追加 "my_tool"
```

---

## 12. 注意事项（踩坑清单）

1. **Placement 二次应用**：参数化对象 `Shape` 常已含世界坐标；生成 `Part::Feature` 时不要再盲目 `feat.Placement = src.Placement`（见 `assign_shape_result`）。
2. **拓扑命名不稳**：`Edge1`/`Face1` 会变；操作前 query，或用语义选择器（`top`/`+Z`/`longest`）。
3. **单位**：仅 mm / 度；不要引入 inch。
4. **不要在工具里调 LLM 或 HTTP**；工具必须是纯本地 CAD 操作。
5. **不要把高层「做一辆车」做成单个 tool**；高层用粗计划 + pattern，工具保持原子。
6. **Windows / FreeCAD Python**：实现侧依赖 FreeCAD 模块，服务侧测试不能 import `FreeCAD`；服务侧只测 specs/registry，执行测放 FreeCAD 内脚本。
7. **修改工具数后**同步改 `test_tool_registry.py` 与（若有）`tests/test_v06_freecad_tools.py` 的计数断言。

---

## 13. 快速对照：改哪些文件

新增一个普通 Act 工具时，最少改动：

```text
freecad_addon/AICADAgent/cad_tools/<module>.py     # 实现
freecad_addon/AICADAgent/cad_tools/__init__.py     # TOOL_REGISTRY
agent_service/app/tools/tool_specs.py              # TOOL_SPECS
agent_service/app/tools/tool_registry.py           # TOOL_CATEGORIES (+关键词)
agent_service/test_tool_registry.py                # 数量断言
dev_log.md                                         # 一行记录
```

按需追加：

```text
freecad_addon/AICADAgent/executor.py               # _NAME_REF_FIELDS
agent_service/app/tools/query_policy.py            # RISKY / TARGET_FIELDS
agent_service/app/llm/llm_provider.py              # prompt 引导
agent_service/app/evaluation/validators.py         # 新验收器
freecad_addon/AICADAgent/tests/test_*.py           # FreeCAD smoke
```

---

## 14. 维护

- 工具契约变更（改名、改必填参数）视为 **破坏性变更**：同步改 FreeCAD 实现、旧 session 可能失败，需在 `dev_log.md` 标明。
- 删除工具：双侧删除 + 测例计数 -1；不要留「半边僵尸」。
- 本文与代码冲突时，以 `TOOL_REGISTRY` / `TOOL_SPECS` 源码为准，并回写本文。
