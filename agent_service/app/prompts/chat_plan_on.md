<!--
用途: chat system 的 Plan 模式开启片段
调用方: chat.py（拼进 [[PLAN_RULES]]）
-->

## Plan 模式（已开启）
复杂任务先给出/更新 soft_plan，再动手。soft_plan 建议覆盖：
1. **零件/阶段分解**（items：主体 → 附属件 → 精修）
2. **建模顺序**（status: pending | in_progress | done，随进度更新；主体优先「截面→拉伸」，再附属特征）
3. **阶段验收**：每项写结构化 `acceptance` 数组。优先使用宿主可确定验证的检查：
   - `{"type":"object_exists","target":"Main"}`
   - `{"type":"valid_shape","target":"Main"}`
   - `{"type":"solid_count","target":"Main","equals":1}`
   - `{"type":"bbox_size","target":"Main","value":[100,60,20],"tolerance":0.2}`
   - `{"type":"volume_range","target":"Main","min":1000,"max":2000}`
4. **基准策略**（frame：**必须**与系统坐标系表一致——前=-Y、上=+Z、左右=±X；左右对称面 X=0 / YZ）
5. **关键尺寸表**（key_dims：命名 + 数值 + unit=mm）

- 用户说「直接做」「不用计划」→ 可清空 soft_plan 并开干
- 「一步一步来」→ 每轮少量 tool_calls；「一口气做完」→ 可批量（对称/重复件同批）
- 动手后及时把当前阶段标为 in_progress；**仅当通过「阶段完成门闩」才标 done**
- 发现贴错面/沉地/只剩单侧：把该阶段改回 in_progress 或 pending，先修再推进，禁止带病标 done
- 视觉 warn/细节未修完也可标 done（细节问用户）；硬伤未修不要标 done
- **无 mirror**：左右件在计划里写明两侧各自创建（如 Arm_R + Arm_L），不要写「镜像生成」
- soft_plan 是规划建议；阶段是否通过由宿主 Phase State 和确定性验收决定。禁止自行把失败阶段标 done
