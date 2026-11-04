"""Runtime configuration from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _get_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Simple settings holder (no extra dependency)."""

    def __init__(self) -> None:
        self.model_api_key: str = os.environ.get("MODEL_API_KEY", "")
        self.model_base_url: str = os.environ.get(
            "MODEL_BASE_URL", "https://api.meta.ai/v1"
        )
        self.rule_model: str = os.environ.get("RULE_MODEL", "muse-spark-1.3")
        self.segmentation_model: str = os.environ.get("SEGMENTATION_MODEL", "sam-3.1")
        self.mock_meta_api: bool = _get_bool("MOCK_META_API", True)
        self.request_timeout_s: float = float(os.environ.get("REQUEST_TIMEOUT_S", "20"))
        self.max_retries: int = int(os.environ.get("MAX_RETRIES", "2"))
        self.sam_cache_ttl_s: float = float(os.environ.get("SAM_CACHE_TTL_S", "5"))


settings = Settings()
