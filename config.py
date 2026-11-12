from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split("  #")[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def _path(env_name: str, default: str) -> Path:
    p = Path(os.environ.get(env_name, default))
    return p if p.is_absolute() else BASE_DIR / p


class Config:

    SECRET_KEY = os.environ.get("ORBE_SECRET_KEY", "dev-only-change-me")
    MAX_UPLOAD_MB = int(os.environ.get("ORBE_MAX_UPLOAD_MB", "10"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
    MAX_IMAGE_PIXELS = 50_000_000
    MIN_IMAGE_SIDE = 32
    MAX_ANALYSIS_SIDE = 2560


    UPLOAD_DIR = _path("ORBE_UPLOAD_DIR", "uploads")
    PROCESSED_DIR = _path("ORBE_PROCESSED_DIR", "processed")
    LOG_DIR = _path("ORBE_LOG_DIR", "logs")
    DATABASE_PATH = _path("ORBE_DATABASE", "data/orbe.db")
    RULES_PATH = _path("ORBE_RULES", "rules.json")


    MODEL_PATH = _path("ORBE_MODEL_PATH", "models/modelo_visao.pt")
    FALLBACK_MODEL = os.environ.get("ORBE_FALLBACK_MODEL", "yolo11s.pt")
    MODEL_FAMILY = os.environ.get("ORBE_MODEL_FAMILY", "yolo").lower()
    IMGSZ = int(os.environ.get("ORBE_IMGSZ", "640"))
    DEVICE = os.environ.get("ORBE_DEVICE", "") or None
    WARMUP_ON_START = os.environ.get("ORBE_WARMUP", "1") == "1"


    LLM_PROVIDER = os.environ.get("ORBE_LLM_PROVIDER", "none").lower()
    LLM_BASE_URL = os.environ.get("ORBE_LLM_BASE_URL", "")
    LLM_API_KEY = os.environ.get("ORBE_LLM_API_KEY", "")
    LLM_MODEL = os.environ.get("ORBE_LLM_MODEL", "")

    TESTING = False
