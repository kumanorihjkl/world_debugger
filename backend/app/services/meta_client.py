"""Thin client for the Meta Model API with timeout, retry, and clean errors."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from app.config import settings

T = TypeVar("T")


class MetaAPIError(RuntimeError):
    """User-visible Meta API failure (network, timeout, malformed response)."""


class MetaAPIPermanentError(MetaAPIError):
    """Bad request (e.g. HTTP 400): retrying unchanged will never succeed."""


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int | None = None,
    timeout_s: float | None = None,
) -> T:
    """Run fn with bounded retries on transient failures."""
    limit = settings.max_retries if max_retries is None else max_retries
    last_exc: Exception | None = None
    for attempt in range(limit + 1):
        try:
            return fn()
        except MetaAPIPermanentError:
            raise
        except MetaAPIError as exc:
            last_exc = exc
            if attempt >= limit:
                break
            time.sleep(min(2.0, 0.5 * (attempt + 1)))
    assert last_exc is not None
    raise last_exc


@dataclass
class MetaClient:
    """Holds API credentials and endpoint config. Transport is per-call."""

    api_key: str = ""
    base_url: str = "https://api.meta.ai/v1"

    def __post_init__(self) -> None:
        self.api_key = self.api_key or settings.model_api_key
        self.base_url = self.base_url or settings.model_base_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def openai_client(self) -> Any:
        """OpenAI-compatible client pointed at the Meta Model API."""
        from openai import OpenAI

        if not self.configured:
            raise MetaAPIError(
                "MODEL_API_KEY is not set. Set it in your environment or .env file."
            )
        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=settings.request_timeout_s,
        )
