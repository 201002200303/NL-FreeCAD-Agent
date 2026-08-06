<!-- 用途: 通用零件规则包；调用方: chat build_chat_system_prompt -->

## 任务规则：通用零件
- 先大体后细节：主体（优先闭合截面→拉伸，矩形可用 box）→ 凸台/腔体/布尔 → 孔槽 → fillet/chamfer；禁止一上来倒圆角；禁止旋转实体拼主体外形
- 主特征命名用语义英文（`Base`/`Blank`），禁用无意义 `Box001`
- fillet/chamfer 半径约相邻最小尺寸 5%~15%；禁止复杂体 `edge_selector=all`
- 布尔/替换若产生 Temp/001 等，删除或隐藏被替代的旧可见件
- 打孔优先 `cut_hole`，之后只引用返回的新对象名
- success 不等于几何正确：看产出名与 bbox
