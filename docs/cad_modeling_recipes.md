# CAD 建模样例集（Code Mode）

给外部/内部 LLM 建模前读的「正确写法」。与 `docs/cad_script_writer_prompt.md` 配套：那边是硬规则，这边是踩坑后的**可跑样板**。

> 要求：`agent_service` 下跑
> `python -c "from app.cad_program.validate import validate_cad_source; from pathlib import Path; validate_cad_source(Path('样例.cad.py').read_text(encoding='utf-8'))"`
> 通过（当前样例均已通过）。

---

## 装配写法（复杂模型先记这几条）

1. **尺寸栈（contact stack）**：从已知面算下一层的 center，别盲搬外部样例的 `translate`。
   `下层顶 = 上层底 + overlap(1mm)` → `center_z = (top + bottom) / 2`。
2. **旋转+布尔要警惕**：`move/rotate` 改的是 Placement；再 `fuse/pattern(fuse=True)` 容易丢位姿/双重偏移。
   - 能 `center=` 直接算世界坐标，就先别 rotate 后再 fuse。
   - 拼装后视觉一体的组（起落架腿+滑撬），**可以留独立零件不 fuse**。
3. **旋转后的 fuse 不是「合并视觉」**：只做装饰的贴合件不必 fuse；要一体再布尔，且只布尔**没再动过**的原语。
4. **重复件（桨叶/对称）**：用三角函数直接算各实例的世界 center + 绕自身 `rotate`，比 `move`+`polar_pattern(fuse)` 稳。
5. **动态名**：AST 校验禁 `str()`；名字列表先写死再循环取，或用 f-string。

---

## 样例 1：接触堆叠（云台相机）

从「板底面」往下叠：板 → 减震球 → 臂 → 相机 → 镜头。每层 center 由上一步 bbox 推，机头方向 **-Y**。

```python
# gimbal camera stack — 每层顶面贴上一层底面
body_bottom = 0
overlap = 1

plate_h = 3
plate_cz = body_bottom - plate_h / 2 + overlap
plate_bot = plate_cz - plate_h / 2
arm_h = 10
arm_cz = plate_bot - arm_h / 2 + overlap
arm_bot = arm_cz - arm_h / 2
cam_h = 12
cam_cz = arm_bot - cam_h / 2 + overlap
cam_y = -30
lens_h = 8
lens_cy = cam_y - 7.5 - lens_h / 2

cad.delete(["GimbalPlate", "GimbalDamper", "GimbalArm", "GimbalMotor", "CamBody", "CamLens", "CamGlass"])
cad.box(name="GimbalPlate", size=(18, 22, plate_h), center=(0, -22, plate_cz))
cad.sphere(name="GimbalDamper", radius=3.5, center=(0, -24, plate_bot - 3.5 + overlap))
cad.box(name="GimbalArm", size=(14, 6, arm_h), center=(0, -26, arm_cz))
cad.cylinder(name="GimbalMotor", radius=3.5, height=4, center=(-8, -26, arm_cz), rot_x=90)
cad.box(name="CamBody", size=(16, 14, cam_h), center=(0, cam_y, cam_cz))
cad.cylinder(name="CamLens", radius=5.5, height=lens_h, center=(0, lens_cy, cam_cz), rot_x=90)
cad.cylinder(name="CamGlass", radius=4.5, height=1.2, center=(0, lens_cy - lens_h / 2 - 0.6, cam_cz), rot_x=90)
```

要点：`rot_x=90` 让镜头轴沿 -Y（机头）；别给 extrude 传 center；整体放哪先定义 `body_bottom`。

---

## 样例 2：起落架（腿+滑撬，同轴竖直）

❌ 反例（散架来源）：腿 x=±28、滑撬 x=±34，再各自 `rotate` 去“够”，再 `fuse` → 横向偏置 + 旋转后布尔 = 漂移。

✅ 正例：腿与滑撬**同 x**，竖直贴合，留独立零件不 fuse。

```python
# landing gear — 腿顶贴机腹，滑撬贴腿底（重叠 1mm）
body_bottom = 0
leg_h = 30
leg_xy = 5
skid_r = 3
overlap = 1
leg_top_z = body_bottom + overlap
leg_bot_z = leg_top_z - leg_h
leg_cz = (leg_top_z + leg_bot_z) / 2
skid_cz = leg_bot_z - skid_r + overlap
gear_x = 26

cad.delete(["Skid_L", "Leg_L1", "Leg_L2", "Skid_R", "Leg_R1", "Leg_R2"])
cad.cylinder(name="Skid_L", radius=skid_r, height=104, center=(-gear_x, 0, skid_cz), rot_x=90)
cad.box(name="Leg_L1", size=(leg_xy, leg_xy, leg_h), center=(-gear_x, 22, leg_cz))
cad.box(name="Leg_L2", size=(leg_xy, leg_xy, leg_h), center=(-gear_x, -22, leg_cz))
cad.cylinder(name="Skid_R", radius=skid_r, height=104, center=(gear_x, 0, skid_cz), rot_x=90)
cad.box(name="Leg_R1", size=(leg_xy, leg_xy, leg_h), center=(gear_x, 22, leg_cz))
cad.box(name="Leg_R2", size=(leg_xy, leg_xy, leg_h), center=(gear_x, -22, leg_cz))
```

要点：`rot_x=90` 让滑撬轴沿 Y；重叠 1mm 保证相交。

---

## 样例 3：重复桨叶（不用 pattern，直接算世界坐标）

「双叶绕毂」：每个实例用 cos/sin 算世界 center，再绕自身 rotate。  
（`polar_pattern(fuse=True)` 对已带 Placement 的对象有坑；叶片用 box 直算更稳。）

```python
# propeller blades — 每个叶片直接算世界坐标
arm_len = 100
prop_r = 46
s2 = math.sqrt(2) / 2
blade_len = prop_r - 4
blade_mid = 2 + blade_len / 2

cad.delete(["BladeA_FL", "BladeB_FL", "Hub_FL"])
mx = -arm_len * s2
my = -arm_len * s2
spin = 65
cad.cylinder(name="Hub_FL", radius=5, height=5, center=(mx, my, 27))
for side, suffix in [(0, "A"), (1, "B")]:
    a = math.radians(spin + 180 * side)
    bx = mx + math.cos(a) * blade_mid
    by = my + math.sin(a) * blade_mid
    blade = cad.box(name="Blade" + suffix + "_FL", size=(blade_len, 9, 2.2), center=(bx, by, 27))
    cad.rotate(blade, axis="Z", angle=spin + 180 * side, center=(bx, by, 27))
```

要点：`for` 是「直接建多个独立件」，不是「for + rotate 手搓布齿」；均布齿轮仍优先 `polar_pattern`，但别在**已移动/旋转过**的对象上 fuse。

---

## 样例 4：X 四旋翼全机（已可跑）

完整脚本（机身/X 机臂/动力组/双叶桨/起落架/云台）：

`agent_service/data/_drone_quad_x.cad.py`

贴进 CAD Playground 直接运行（先 `cad.delete(names)` 清场）。

---

## 自检（写完对一遍）

- [ ] 接触件按「尺寸栈」算 center，不是抄外部 translate
- [ ] 旋转过的对象没有再 `fuse` / `pattern(fuse=True)`
- [ ] 纯装饰贴合件留独立零件，不乱布尔
- [ ] 动态名字没用 `str()`；循环里从名字列表取
- [ ] 机头方向记得是 **-Y**
