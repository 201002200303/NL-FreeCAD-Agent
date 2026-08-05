<!-- 用途: 装配规则包 -->

## 任务规则：装配
- 多零件先定位基准与接口，再配合（`mate_planes` / `mate_coaxial`）
- 改已有对象前先 query；`align_objects` 只移动所选 axis
- 选边/面先 `list_topology`；避免脆弱的裸 Face 编号作为长期语义
