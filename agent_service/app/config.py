import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/cad_agent.db")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

VERSION = "0.1.0"

LLM_DEBUG = os.getenv("LLM_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
LLM_DEBUG_DIR = os.getenv("LLM_DEBUG_DIR", "")
