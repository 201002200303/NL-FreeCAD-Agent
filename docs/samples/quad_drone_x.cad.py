# ════════════════════════════════════════════════════════════════
# 四旋翼样例（X 布局 + 云台相机）— Code Mode 标准装配写法
# ════════════════════════════════════════════════════════════════
#
# 建模流程（写任何复杂装配前，先按这个顺序想清楚）：
#   1. 定原点     机身底面 = z0，中心 = (0,0)。所有高度从这里推。
#   2. 尺寸集中   关键数全放顶部变量；后面只引用，不写魔法数。
#   3. 接触优先   每件先写「我的顶 = 上一层的底」，再反算 center。
#                 禁止：先抄一个 translate，再靠 rotate 去“够”。
#   4. 清单命名   names 先列全 → cad.delete(names)，重跑不留叠影。
#   5. 分组建     机身 → 机臂/动力 → 起落架 → 云台；先主体后细节。
#
# 本脚本要点：
#   - 桨叶用 polar_pattern(fuse) 成对桨；工具 fuse 后会删源件，不留幽灵扇叶。
#   - 起落架腿与滑撬同 x 竖直贴合，不“先平移再 rotate 去够”。
#   - 贴合处允许 overlap=1mm 轻嵌，避免视觉悬空。
#
# 坐标系：右=+X，前=-Y，上=+Z，单位 mm。
# ════════════════════════════════════════════════════════════════

# ── 1) 尺寸集中 ─────────────────────────────────────────────────
arm_len = 100        # 电机轴距（中心到电机）
prop_r  = 46         # 螺旋桨半径
s2 = math.sqrt(2) / 2
arm_half = arm_len / 2 + 10          # 机臂中心离原点的对角距离（根部埋入机身）
blade_len = prop_r - 4               # 单叶长（留出桨毂）
blade_mid = 2 + blade_len / 2        # 桨叶中心离电机轴距离

# 机身：底 z=0，顶 z=26 —— 全场高度基准
body_h = 26
body_z = body_h / 2
body_bottom = 0

# 起落架：竖直腿贴机腹，滑撬贴腿底；overlap 允许 1mm 轻嵌
leg_h, leg_xy, skid_r, overlap = 30, 5, 3, 1
leg_top_z = body_bottom + overlap
leg_bot_z = leg_top_z - leg_h
leg_cz = (leg_top_z + leg_bot_z) / 2
skid_cz = leg_bot_z - skid_r + overlap
gear_x = 26                 # 左右滑撬 |x|
gear_y1, gear_y2 = 22, -22  # 前后腿 y

# 云台：从上往下叠 —— 每层顶面贴上一层底面
plate_h = 3
plate_cz = body_bottom - plate_h / 2 + overlap
plate_bot = plate_cz - plate_h / 2
arm_h = 10
arm_cz = plate_bot - arm_h / 2 + overlap
arm_bot = arm_cz - arm_h / 2
cam_h = 12
cam_cz = arm_bot - cam_h / 2 + overlap
cam_y = -30                        # 机头 = -Y，相机挂在机腹前部
lens_h = 8
lens_cy = cam_y - 7.5 - lens_h / 2 # 镜头从相机前脸伸出

# ── 2) 清理清单（含旧版可能留下的名字，缺失会跳过）────────────────
names = [
    "Body", "Canopy", "GPS",
    "Vent0", "Vent1", "Vent2", "Vent3", "Vent4",
    "Stripe_L", "Stripe_R", "NoseLED", "Cam_L", "Cam_R",
    "Battery", "PowerBtn", "TailLED",
    "Arm_FL", "Arm_BL", "Arm_BR", "Arm_FR",
    "Mount_FL", "Mount_BL", "Mount_BR", "Mount_FR",
    "Motor_FL", "Motor_BL", "Motor_BR", "Motor_FR",
    "Cap_FL", "Cap_BL", "Cap_BR", "Cap_FR",
    "Blade_FL", "Blade_BL", "Blade_BR", "Blade_FR",
    "Prop_FL", "Prop_BL", "Prop_BR", "Prop_FR",
    "Hub_FL", "Hub_BL", "Hub_BR", "Hub_FR",
    "ArmLED_FL", "ArmLED_BL", "ArmLED_BR", "ArmLED_FR",
    "Skid_L", "Leg_L1", "Leg_L2", "Skid_R", "Leg_R1", "Leg_R2",
    "Gear_L1", "Gear_L", "Gear_R1", "Gear_R",
    "GimbalPlate", "GimbalDamper", "GimbalArm", "GimbalMotor",
    "CamBody", "CamLens", "CamGlass", "Down_L", "Down_R",
    # 旧版残留，一并清掉
    "BladeA_FL", "BladeB_FL", "PropAsm_FL", "TipAsm_FL", "BladeSk_FL",
    "PropAsm_BL", "PropAsm_BR", "PropAsm_FR",
    "TipAsm_BL", "TipAsm_BR", "TipAsm_FR",
    "BladeSk_BL", "BladeSk_BR", "BladeSk_FR",
]
cad.delete(names)

# ── 3) 机身组 ───────────────────────────────────────────────────
cad.box(name="Body", size=(58, 96, body_h), center=(0, 0, body_z))
cad.box(name="Canopy", size=(44, 70, 14), center=(0, 0, 23))
cad.box(name="GPS", size=(20, 30, 4), center=(0, 4, 26))

# 顶部散热孔：5 条小条，名字从列表取（沙箱禁 str(i) 拼名）
vent_names = ["Vent0", "Vent1", "Vent2", "Vent3", "Vent4"]
for i in range(5):
    cad.box(name=vent_names[i], size=(14, 2, 2), center=(8 - 4 * i, 20, 23))

# 侧饰条 / 首尾细节：机头 = -Y
cad.box(name="Stripe_L", size=(1.5, 48, 5), center=(-22, -2, 16))
cad.box(name="Stripe_R", size=(1.5, 48, 5), center=(22, -2, 16))
cad.box(name="NoseLED", size=(24, 2, 3), center=(0, -47.3, -6))
cad.cylinder(name="Cam_L", radius=3.2, height=2.5, center=(-13, -47.5, 5), rot_x=90)  # 轴沿 Y → rot_x=90
cad.cylinder(name="Cam_R", radius=3.2, height=2.5, center=(13, -47.5, 5), rot_x=90)
cad.box(name="Battery", size=(32, 3, 13), center=(0, 47.5, -2))
cad.cylinder(name="PowerBtn", radius=2.5, height=2, center=(0, 49.5, 2), rot_x=90)
cad.box(name="TailLED", size=(14, 2, 2.5), center=(0, 47.3, 7))

# ── 4) 机臂与动力组（45° X 布局）─────────────────────────────────
# 每臂：先算世界坐标（mx,my），box 建好再绕自身中心转 ang。
# 关键点：cad.rotate 必须带 center=自身中心；默认绕世界原点会把件甩飞。
arms = [
    {"tag": "FL", "sx": -1, "sy": -1, "spin": 65},
    {"tag": "BL", "sx": -1, "sy": 1,  "spin": 155},
    {"tag": "BR", "sx": 1,  "sy": 1,  "spin": 245},
    {"tag": "FR", "sx": 1,  "sy": -1, "spin": 335},
]

for cf in arms:
    tag, sx, sy, spin = cf["tag"], cf["sx"], cf["sy"], cf["spin"]
    mx = sx * arm_len * s2      # 电机中心
    my = sy * arm_len * s2
    ax = sx * arm_half * s2     # 机臂中心
    ay = sy * arm_half * s2
    ang = math.degrees(math.atan2(my, mx))

    arm = cad.box(name="Arm_" + tag, size=(arm_len - 4, 13, 7), center=(ax, ay, 8))
    cad.rotate(arm, axis="Z", angle=ang, center=(ax, ay, 8))

    cad.cylinder(name="Mount_" + tag, radius=9.5, height=6, center=(mx, my, 13))
    cad.cylinder(name="Motor_" + tag, radius=8, height=9, center=(mx, my, 19.5))
    cad.cylinder(name="Cap_" + tag, radius=3, height=2.5, center=(mx, my, 25))
    cad.cylinder(name="Hub_" + tag, radius=5, height=5, center=(mx, my, 27))

    # 双叶桨：建一片叶 + polar_pattern(fuse) 成对桨——工具已修 Placement，正规写法可用
    blade = cad.box(name="Blade_" + tag, size=(blade_len, 9, 2.2), center=(mx + blade_mid, my, 27))
    cad.rotate(blade, axis="Z", angle=spin, center=(mx, my, 27))
    cad.polar_pattern(blade, count=2, angle=360, axis="Z", center=(mx, my, 27), name_prefix="Blade_" + tag, fuse=True, fuse_name="Prop_" + tag)

    lx = sx * (arm_len - 4) * s2   # 臂端航行灯
    ly = sy * (arm_len - 4) * s2
    led = cad.box(name="ArmLED_" + tag, size=(8, 10, 2), center=(lx, ly, 4))
    cad.rotate(led, axis="Z", angle=ang, center=(lx, ly, 4))

# ── 5) 起落架：不旋转、不 fuse —— 腿与滑撬同 x，竖直贴合 ──────────
# 反面教材：腿在 x=±28、滑撬在 x=±34，再 rotate 去够 → 视觉直接散架。
cad.cylinder(name="Skid_L", radius=skid_r, height=104, center=(-gear_x, 0, skid_cz), rot_x=90)
cad.box(name="Leg_L1", size=(leg_xy, leg_xy, leg_h), center=(-gear_x, gear_y1, leg_cz))
cad.box(name="Leg_L2", size=(leg_xy, leg_xy, leg_h), center=(-gear_x, gear_y2, leg_cz))
cad.cylinder(name="Skid_R", radius=skid_r, height=104, center=(gear_x, 0, skid_cz), rot_x=90)
cad.box(name="Leg_R1", size=(leg_xy, leg_xy, leg_h), center=(gear_x, gear_y1, leg_cz))
cad.box(name="Leg_R2", size=(leg_xy, leg_xy, leg_h), center=(gear_x, gear_y2, leg_cz))

# ── 6) 云台相机：层层贴合，z 全部由 body_bottom 推出 ──────────────
cad.box(name="GimbalPlate", size=(18, 22, plate_h), center=(0, -22, plate_cz))
cad.sphere(name="GimbalDamper", radius=3.5, center=(0, -24, plate_bot - 3.5 + overlap))
cad.box(name="GimbalArm", size=(14, 6, arm_h), center=(0, -26, arm_cz))
cad.cylinder(name="GimbalMotor", radius=3.5, height=4, center=(-8, -26, arm_cz), rot_x=90)
cad.box(name="CamBody", size=(16, 14, cam_h), center=(0, cam_y, cam_cz))
cad.cylinder(name="CamLens", radius=5.5, height=lens_h, center=(0, lens_cy, cam_cz), rot_x=90)
cad.cylinder(name="CamGlass", radius=4.5, height=1.2, center=(0, lens_cy - lens_h / 2 - 0.6, cam_cz), rot_x=90)
cad.cylinder(name="Down_L", radius=2.5, height=2, center=(-10, -18, body_bottom - 1))
cad.cylinder(name="Down_R", radius=2.5, height=2, center=(10, -18, body_bottom - 1))
