import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/cad_agent.db")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-flash")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "393216") or "393216")
LLM_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "600") or "600")

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
# 输入侧预算（字符），与 max_tokens 无关：max_tokens 管单次**输出**，
# 这个管每轮往 prompt 里塞多少历史 + 文档上下文。
# 模型上下文 1M，所以这里给到 ~130K token 仍只用掉约 13%，留足空间。
# 调大的代价是每轮更慢更贵，也是这个值没直接顶到 1M 的原因。
CONVERSATION_BUDGET_CHARS = int(os.getenv("CONVERSATION_BUDGET_CHARS", "400000") or "400000")
