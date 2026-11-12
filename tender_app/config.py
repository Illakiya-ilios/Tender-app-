"""Application configuration loaded from the .env file."""
from pathlib import Path

from dotenv import load_dotenv
import os

# Load .env from the project root (one level above this package).
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash").strip()

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Working directory for extracted bids and audit JSON (Stage 3 bid evaluation).
EVAL_DIR = Path(__file__).resolve().parent / "eval_runs"
EVAL_DIR.mkdir(exist_ok=True)

# SQLite database file for the persistent Dashboard overview (tenders + evaluations).
DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def require_api_key() -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Add it to the .env file at the project root."
        )
    return GOOGLE_API_KEY
