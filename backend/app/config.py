import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CACHE_DIR = Path(os.environ.get("KAI_LUT_CACHE", ROOT / "cache"))
DB_PATH = CACHE_DIR / "market.sqlite"
UNIVERSE_PATH = DATA_DIR / "universe.json"

TTL_HOURS = float(os.environ.get("KAI_LUT_TTL_HOURS", "12"))
WORKERS = max(1, int(os.environ.get("KAI_LUT_WORKERS", "10")))
LIMIT = int(os.environ["KAI_LUT_LIMIT"]) if os.environ.get("KAI_LUT_LIMIT") else None
COOLDOWN_SECONDS = int(os.environ.get("KAI_LUT_COOLDOWN", "300"))
CHUNK_SIZE = max(50, int(os.environ.get("KAI_LUT_CHUNK", "250")))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 KailutScreen/1.0"
)
