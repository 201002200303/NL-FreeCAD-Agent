"""本地任务/阶段路由：决定 rule packs 与工具工作集类别。

不调用 LLM；关键词 + soft_plan 阶段启发。chat 组装 system prompt 时使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RouteDecision:
    task_type: str
    phase: str
    rule_packs: tuple[str, ...]
    tool_categories: tuple[str, ...]
    capability_warnings: tuple[str, ...] = ()
    confidence: float = 0.0


# 无匹配时的有界建模子集（非整表 53 工具）
_FALLBACK_CATEGORIES = (
    "primitives",
    "sketch",
    "partdesign",
    "boolean",
    "transform",
    "pattern",
    "query",
)

_TASK_RULES: list[tuple[str, tuple[str, ...], float]] = [
    # (task_type, keywords, confidence)
    ("spur_gear", ("齿轮", "渐开线", "模数", "齿数", "压力角", "分度圆", "齿顶圆", "齿根圆", "gear", "involute"), 0.92),
    ("humanoid", ("人形", "机器人", "双足", "手臂", "腿", "头", "躯干", "antenna", "robot"), 0.9),
    ("vehicle", ("车", "汽车", "轮子", "车灯", "底盘", "vehicle", "wheel"), 0.88),
    ("assembly", ("装配", "配合", "同轴", "assembly", "mate"), 0.85),
]

_PHASE_EXPORT_KW = ("导出", "保存", "export", "step", "stl", "fcstd", "save")
_PHASE_VALIDATE_KW = ("检查", "验证", "测量", "validate", "measure", "校验")
_PHASE_REFINE_KW = ("倒角", "圆角", "fillet", "chamfer", "精修")


def route(
    *,
    message: str = "",
    user_goal: str = "",
    soft_plan: Optional[dict] = None,
) -> RouteDecision:
    text = f"{user_goal or ''}\n{message or ''}".strip().lower()
    # 中文关键词不 lower 也能匹配；英文 lower 便于对照
    text_raw = f"{user_goal or ''}\n{message or ''}"
    haystack = text_raw  # 保留原文以匹配中文

    task_type, confidence = _detect_task(haystack)
    phase = _detect_phase(haystack, soft_plan)

    if phase == "export":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=_packs_for_task(task_type),
            tool_categories=("export", "query"),
            capability_warnings=(),
            confidence=max(confidence, 0.8),
        )

    if phase == "validate":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=_packs_for_task(task_type),
            tool_categories=("query",),
            capability_warnings=(),
            confidence=max(confidence, 0.75),
        )

    if task_type == "spur_gear":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=("general_part", "gear"),
            tool_categories=("sketch", "partdesign", "pattern", "boolean"),
            capability_warnings=("exact_involute_tool_unavailable",),
            confidence=confidence,
        )

    if task_type == "humanoid":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=("general_part", "symmetric", "humanoid"),
            tool_categories=("primitives", "boolean", "features", "transform", "pattern", "query"),
            capability_warnings=(),
            confidence=confidence,
        )

    if task_type == "vehicle":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=("general_part", "symmetric", "vehicle"),
            tool_categories=("primitives", "boolean", "features", "transform", "pattern", "query"),
            capability_warnings=(),
            confidence=confidence,
        )

    if task_type == "assembly":
        return RouteDecision(
            task_type=task_type,
            phase=phase,
            rule_packs=("general_part", "assembly"),
            tool_categories=("assembly", "transform", "query"),
            capability_warnings=(),
            confidence=confidence,
        )

    # general / fallback
    cats = _infer_categories_from_keywords(haystack) or _FALLBACK_CATEGORIES
    return RouteDecision(
        task_type="general_part",
        phase=phase,
        rule_packs=("general_part", "symmetric"),
        tool_categories=tuple(cats),
        capability_warnings=(),
        confidence=confidence if confidence else 0.4,
    )


def _detect_task(text: str) -> tuple[str, float]:
    for task_type, keywords, conf in _TASK_RULES:
        if any(kw.lower() in text.lower() or kw in text for kw in keywords):
            return task_type, conf
    return "general_part", 0.4


def _detect_phase(text: str, soft_plan: Optional[dict]) -> str:
    lower = text.lower()
    if any(kw in text or kw in lower for kw in _PHASE_EXPORT_KW):
        return "export"
    if any(kw in text or kw in lower for kw in _PHASE_VALIDATE_KW):
        return "validate"
    if any(kw in text or kw in lower for kw in _PHASE_REFINE_KW):
        return "refine"

    if soft_plan:
        items = soft_plan.get("items") or soft_plan.get("phases") or []
        for it in items:
            if not isinstance(it, dict):
                continue
            if (it.get("status") or "") == "in_progress":
                title = (it.get("title") or it.get("intent") or "").lower()
                if any(k in title for k in ("导出", "export", "保存")):
                    return "export"
                if any(k in title for k in ("验证", "检查", "validate")):
                    return "validate"
                if any(k in title for k in ("倒角", "圆角", "fillet", "精修")):
                    return "refine"
                return "modeling"
    return "modeling"


def _packs_for_task(task_type: str) -> tuple[str, ...]:
    mapping = {
        "spur_gear": ("general_part", "gear"),
        "humanoid": ("general_part", "symmetric", "humanoid"),
        "vehicle": ("general_part", "symmetric", "vehicle"),
        "assembly": ("general_part", "assembly"),
        "general_part": ("general_part", "symmetric"),
    }
    return mapping.get(task_type, ("general_part",))


def _infer_categories_from_keywords(text: str) -> tuple[str, ...]:
    """轻量类别启发；无命中则返回空，由调用方用 fallback。"""
    keyword_map = {
        "primitives": ("box", "cube", "长方体", "cylinder", "圆柱", "sphere", "球", "cone", "圆锥", "torus", "圆环"),
        "boolean": ("合并", "fuse", "cut", "切割", "布尔", "打孔", "开槽", "hole"),
        "features": ("倒角", "fillet", "chamfer", "圆角"),
        "transform": ("移动", "move", "旋转", "rotate", "缩放", "scale", "复制", "对齐", "placement"),
        "pattern": ("阵列", "pattern", "polar", "圆周", "等距"),
        "export": ("导出", "export", "step", "stl", "保存", "save"),
        "query": ("查询", "拓扑", "测量", "间隙", "measure", "检查"),
        "sketch": ("草图", "sketch", "轮廓", "圆弧", "折线", "样条", "约束"),
        "partdesign": ("拉伸", "pad", "pocket", "切除", "凸台"),
        "surface": ("放样", "loft", "扫掠", "sweep"),
        "assembly": ("装配", "assembly", "配合", "mate"),
    }
    found: list[str] = []
    lower = text.lower()
    for cat, keywords in keyword_map.items():
        if any(kw in text or kw in lower for kw in keywords):
            found.append(cat)
    return tuple(found)
