import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
DATA_DIR.mkdir(exist_ok=True, parents=True)

SESSIONS_FILE = DATA_DIR / "sessions.json"
HEALTHY_FILE  = DATA_DIR / "healthy_sessions.json"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = set()
_raw = os.getenv("ADMIN_IDS", "").strip()
if _raw:
    for x in _raw.split(","):
        x = x.strip()
        if x.lstrip("-").isdigit():
            ADMIN_IDS.add(int(x))

PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "admin")
SECRET_KEY     = os.getenv("SECRET_KEY", "please-change-me")
PORT           = int(os.getenv("PORT", 8080))
HOST           = os.getenv("HOST", "0.0.0.0")
