"""视觉辅助：用截图判断结构化几何验证盖不到的整体造型问题。"""

from app.vision.memory import (
    count_visible_objects,
    empty_vision_memory,
    should_allow_vision_revise,
    update_vision_memory,
)
from app.vision.service import assess_viewport, assess_views, vision_available

__all__ = [
    "assess_viewport",
    "assess_views",
    "vision_available",
    "count_visible_objects",
    "empty_vision_memory",
    "should_allow_vision_revise",
    "update_vision_memory",
]
