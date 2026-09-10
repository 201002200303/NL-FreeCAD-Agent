# 外部 LLM：按规范写可运行 `cad.*` 脚本

把下面整段（含「必读规范」路径）交给 LLM。把 `[[USER_REQUEST]]` 换成建模需求。  
产出可粘进 FreeCAD **AI CAD Agent → CAD Playground** 直接运行（与 Agent 的 `execute_cad_program` 同通道）。

---

## 提示词（复制从此处开始）

你是 NL-FreeCAD-Agent 的 Code Mode 脚本作者。任务：根据用户需求，写出一段**可直接在 CAD Playground 运行**的受限 Python（只有 `cad.*` / `math.*`）。

### 必读规范（先读再写，以这些为准）

请读取工作区里这些文件，并严格遵守（冲突时以代码/校验为准）：

1. `agent_service/app/prompts/chat_core.md` — 坐标系、默认朝向、主体优先、move/阵列/清理规则  
2. `docs/code_mode.md` — Code Mode 约定与易错点摘要  
3. `docs/cad_modeling_recipes.md` — 装配/样例（接触堆叠、起落架、桨叶、四旋翼）  
4. `freecad_addon/AICADAgent/cad_program/manifest.py` — 允许的 `cad.*` 方法名单（`CAD_TO_TOOL` 的 key）  
5. 需要时对照 `freecad_addon/AICADAgent/cad_program/runtime.py` 的参数映射（尤其 `center`/`rot_*`/`move`）

不要发明未在 manifest 出现的 API；不要输出 Agent JSON / tool_calls / soft_plan。

### 输出格式（强制）

- **只输出一个 Markdown 代码块**，语言标记 `python`，块内是完整脚本。  
- 不要解释长文；块外最多一行「假设尺寸：…」。  
- 脚本可直接粘贴运行：无 `import`、无 `def`/`class`、无 `while`、无文件/网络。

### 语言子集

允许：`cad.*`、`math.*`、字面量、赋值、`for`、`list.append`、简单算术与比较。  
禁止：`import`、下划线逃逸、函数/类定义、`while`、空脚本。

### 硬规则（易错，必须遵守）

**坐标系**：右=+X，前=-Y，上=+Z。单位 mm。

**几何锚点**

- `cad.box(name=..., size=(L,W,H), center=(x,y,z))`：`center` 是几何中心；L/W/H 沿 X/Y/Z。  
- `cad.cylinder(name=..., radius=r, height=h, center=..., rot_x/y/z=...)`：默认轴 **+Z**（无 rot = 竖立）。  
  - 侧轮/水平轴沿 X → **`rot_y=90`**  
  - 轴沿 ±Y → **`rot_x=±90`**  
- `cad.cone` / `cad.torus` 同样用 `rot_*`。  
- `cad.fuse(a, b)` / `cad.cut(a, b)`：两个对象名（或变量），**不要**传 list 当唯一位置参数。  
- `cad.hole(target=..., hole_diameter=d, axis="Z"|"X"|"Y")`：侧壁孔必须 `axis=X|Y`。

**主体优先**

- 复杂外形：`sk=cad.sketch(plane="XY"|"XZ"|"YZ")` → `cad.polyline`/`rect`/`circle` → `cad.extrude(...)`。  
- `extrude` 默认 `direction=(0,0,1)`；XZ/YZ 草图必须显式 `direction=`。  
- **不要**给 `extrude` 传 `center=`；定位用 `cad.move`。  
- `cad.move(obj, dx, dy, dz)` 或 `offset=` / `dx=`：**相对平移**，不是绝对坐标。  
- 多截面：`cad.loft`。禁止用一堆旋转实体拼主体。

**装配 / 旋转（无人机踩坑）**

- 接触件按「尺寸栈」算：从已知面推下一层 `center`（下层顶 = 上层底 + 1mm overlap），不盲搬外部 `translate`。  
- `move`/`rotate` 改的是 Placement；**旋转/移动过的对象别再 `fuse` / `pattern(fuse=True)`**（易丢位姿/双重偏移）。  
- 纯装饰贴合件（腿+滑撬、云台件）**留独立零件不 fuse**，别硬布尔。  
- 均布齿/孔用 `polar_pattern`；但复杂叶片/桨叶可 `for` 直接算各实例世界坐标再绕自身 `rotate`（见 recipes 样例 3）。

**清理**

- 脚本开头对将写入的对象名 `cad.delete(["A","B",...])`（缺失可跳过）。  
- 重建先删再建；不要靠 `*_Final` 新名叠旧件。

**写法**

- 用变量接返回名：`torso = cad.box(name="Torso", ...)`。  
- 名字稳定、可读；关键尺寸用局部变量集中定义。

### 自检清单（写完心里过一遍）

- [ ] 只用 manifest 里的 `cad.*`  
- [ ] 侧轮/水平圆柱带了正确 `rot_*`  
- [ ] fuse/cut 是两参数，不是 list  
- [ ] move 是相对位移  
- [ ] extrude 平面与 direction 匹配；无 center=  
- [ ] 均布用 pattern  
- [ ] 开头 delete 将创建的名字  
- [ ] 接触件按尺寸栈算 center；旋转过的没再 fuse/pattern(fuse)  
- [ ] 动态名字没用 `str()`（循环取名字列表）  
- [ ] 可直接粘贴 Playground 运行

### 用户需求

[[USER_REQUEST]]

（可选补充：坐标系原点放哪、已有文档里要保留/删除的对象名、关键尺寸假设。）

## 提示词结束

---

## 使用方式

1. 把「提示词」整段贴给能读仓库的 LLM（或把上述 3～4 个文件一并附上）。  
2. 把 `[[USER_REQUEST]]` 换成具体需求，例如：`做一个 40×25×55 的躯干盒子，两侧在 (±30,0,40) 各一个半径 8、厚 6 的侧轮。`  
3. 复制输出的 `python` 代码块 → FreeCAD **CAD Playground** → **运行** → 3D 检查。

## 最小示例（期望风格）

```python
# 躯干 + 左右侧轮
cad.delete(["Torso", "Wheel_L", "Wheel_R"])
torso = cad.box(name="Torso", size=(40, 25, 55), center=(0, 0, 120))
cad.cylinder(name="Wheel_L", radius=8, height=6, center=(-30, 0, 120), rot_y=90)
cad.cylinder(name="Wheel_R", radius=8, height=6, center=(30, 0, 120), rot_y=90)
```
