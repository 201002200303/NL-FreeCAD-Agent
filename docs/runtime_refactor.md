# V0.9 Runtime Refactor — 改进目录（审计后执行版）

> 基线提交：`0ca25ae`（大改前）  
> 本文件是可执行目录，不是愿景清单。

## 审计结论

原 13 项目录方向正确，但需要收口：

1. **第一刀只做基础设施**：Event Log + Checkpoint + Context 投影 + bbox 修复 + 粗计划收紧  
2. **复用 `data/runtime.db`（sqlite3）**，不新开 LangGraph checkpointer  
3. **不先建空目录**：建模 Skill 库、相对定位工具、硬验收扩展放到感知可用之后  
4. **向后兼容**：FreeCAD 客户端继续传 `session_memory`；服务端并行写入 durable runtime  
5. **感知必须并行**：`bbox=null` 是小车翻车根因之一，不能排到很后面

## Phase 1（本轮）

- [x] `app/runtime/`：EventType / Store / Service / Context Builder  
- [x] `start_plan` / `next_step` / `evaluate_step` / `log_execution` 写事件与 checkpoint  
- [x] LLM Context 注入 Runtime State（最近事件、相关 CAD、未解决错误、阶段摘要）  
- [x] 粗计划 prompt：只排顺序+角色，禁止工艺细节  
- [x] FreeCAD `document_state`：Shape.isNull 检查、Body→Tip fallback、Shape.BoundBox 回退  
- [x] `test_runtime.py`

## Phase 2（✅ 已完成）

- [x] `/agent/session/{id}` 读取 checkpoint + events，支持暂停后恢复  
- [x] FreeCAD `pause/resume` 改为写 `USER_PAUSED/USER_RESUMED` 事件，不再只靠内存布尔  
- [x] query completeness：`bbox` 缺失不算 covers；强制重新查询  
- [x] document revision diff：人工改模后注入 `DOCUMENT_CHANGED_BY_USER`

## Phase 3（✅ 代码落地；golden case 待人工）

- [x] 相对定位工具（align/place_relative/distribute）  
- [x] 硬几何验收（grounded/touching/no_overlap/size_close）  
- [x] 建模 pattern / skill 检索  
- [x] action_id 幂等（executor 去重）与批内依赖（query_policy）  
- [ ] golden-case 真实小车回归（见 playbook F3）

## 非目标（本阶段不做）

- 替换整个 LangGraph 拓扑  
- 重写全部 49 个工具  
- 一次性实现完整重规划 UI  
