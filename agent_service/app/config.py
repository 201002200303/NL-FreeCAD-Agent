import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/cad_agent.db")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16384") or "16384")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "180") or "180")

VERSION = "0.2.0"

LLM_DEBUG = os.getenv("LLM_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
LLM_DEBUG_DIR = os.getenv("LLM_DEBUG_DIR", "")

# ── Vision（视觉辅助）─────────────────────────────────────────────
# 主模型若无视觉能力，可单独指定视觉模型。默认关闭。
def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


VISION_ENABLED = _env_bool("VISION_ENABLED", False)
VISION_API_KEY = os.getenv("VISION_API_KEY", "") or OPENAI_API_KEY
VISION_BASE_URL = os.getenv("VISION_BASE_URL", "") or OPENAI_BASE_URL
VISION_MODEL = os.getenv("VISION_MODEL", "")  # 空则无法调用（避免误用纯文本模型）
VISION_MAX_EDGE = int(os.getenv("VISION_MAX_EDGE", "1024"))

# ── Chat agent 默认偏好（客户端可覆盖）────────────────────────────
CHAT_PLAN_MODE_DEFAULT = _env_bool("CHAT_PLAN_MODE_DEFAULT", True)
CONVERSATION_BUDGET_CHARS = int(os.getenv("CONVERSATION_BUDGET_CHARS", "120000") or "120000")
