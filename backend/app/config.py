import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "sample.duckdb"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

MAX_ROW_LIMIT = int(os.getenv("MAX_ROW_LIMIT", "1000"))
MAX_SUBQUERY_DEPTH = int(os.getenv("MAX_SUBQUERY_DEPTH", "3"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
