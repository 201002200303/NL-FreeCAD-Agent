"""视觉辅助：用截图判断结构化几何验证盖不到的整体造型问题。"""

from app.vision.service import assess_viewport, vision_available

__all__ = ["assess_viewport", "vision_available"]
