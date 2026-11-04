"""SAM 3.1 segmentation layer.

Wire format follows the official Meta Model API docs
(`dev.meta.ai/docs/sam/segmenting`, `/docs/sam/reading-segmentation`):

- `POST /v1/responses` with `model="sam-3.1"`, one user message carrying a
  short noun-phrase `input_text` prompt plus one `input_image` part.
- `stream: true`; accumulate `response.output_text.delta` until completion.
- Output is special-token text: `<0f>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>
  <|mask;...|>,...` with coordinates in source pixels (`w`/`h` = image size).
- `metadata: {"include_confidence": "true", "mask_encoding": "one_bit"}`.

One request per concept. Absent concepts stream to an empty `output_text`,
which is a normal result, not an error.
"""

from __future__ import annotations

import re
import time

from app.config import settings
from app.services.meta_client import (
    MetaAPIError,
    MetaAPIPermanentError,
    MetaClient,
    call_with_retry,
)

# <|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|> — parse by key, not position.
_BOX_RE = re.compile(
    r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([\d.]+))?\|>"
)

_cache: dict[str, tuple[float, list[dict]]] = {}


def _cache_get(key: str) -> list[dict] | None:
    hit = _cache.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > settings.sam_cache_ttl_s:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: list[dict]) -> None:
    _cache[key] = (time.time(), value)
    if len(_cache) > 64:
        oldest = min(_cache.items(), key=lambda kv: kv[1][0])[0]
        _cache.pop(oldest, None)


def clear_cache() -> None:
    _cache.clear()


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def parse_sam_text(text: str, prompt: str) -> list[dict]:
    """Parse SAM special-token output into normalized detections.

    Box corners are source pixels; divide by the reported `w`/`h`.
    Records pair one box with one mask (box first); the mask raster is
    box-local, so its contour is mapped through the box bounds.
    """
    from app.services import masks as mask_service

    mask_tokens = mask_service.extract_mask_tokens(text)
    detections: list[dict] = []
    for index, match in enumerate(_BOX_RE.finditer(text or "")):
        x1, y1, x2, y2, w, h = (int(match.group(i)) for i in range(1, 7))
        if w <= 0 or h <= 0:
            continue
        conf_group = match.group(7)
        try:
            confidence = float(conf_group) if conf_group is not None else 1.0
        except ValueError:
            confidence = 1.0
        polygon: list[tuple[float, float]] | None = None
        if index < len(mask_tokens):
            decoded = mask_service.decode_raster(mask_tokens[index])
            if decoded is not None:
                raster, mw, mh = decoded
                # Official semantics: box corners inclusive, half-open bounds.
                polygon = mask_service.raster_to_polygon(
                    raster, mw, mh, (x1, y1, x2 + 1, y2 + 1), w, h
                )
        detections.append(
            {
                "concept": prompt,
                "selector_id": "",
                "bbox": [
                    _clamp01(x1 / w),
                    _clamp01(y1 / h),
                    _clamp01(x2 / w),
                    _clamp01(y2 / h),
                ],
                "confidence": confidence,
                "polygon": polygon,
            }
        )
    return detections


def mock_segment(prompts: list[str], image_variant: str = "default") -> list[dict]:
    """Fixture detections. `image_variant` lets tests simulate object movement."""
    detections: list[dict] = []
    for prompt in prompts:
        key = prompt.strip().lower()
        for concept, bbox, conf in _FIXTURE_LAYOUT:
            if concept in key or key in concept:
                box = list(bbox)
                if image_variant == "far" and concept in {"cup", "bottle"}:
                    # Simulate the drink moved away: shift right.
                    box = [0.78, 0.10, 0.93, 0.35]
                if image_variant == "empty_zone" and concept == "box":
                    continue
                detections.append(
                    {
                        "concept": concept,
                        "selector_id": "",
                        "bbox": box,
                        "confidence": conf,
                    }
                )
    return detections


# (concept-keyword, bbox [x0,y0,x1,y1], confidence)
_FIXTURE_LAYOUT: list[tuple[str, list[float], float]] = [
    ("laptop", [0.10, 0.45, 0.45, 0.85], 0.96),
    ("cup", [0.55, 0.55, 0.70, 0.80], 0.93),
    ("bottle", [0.72, 0.50, 0.84, 0.82], 0.91),
    ("box", [0.30, 0.55, 0.60, 0.88], 0.90),
    ("bag", [0.20, 0.50, 0.45, 0.85], 0.88),
]


def _stream_sam_text(oa: object, prompt: str, image_base64: str) -> str:
    """Stream one SAM request and return the accumulated output text."""
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    try:
        with oa.responses.stream(  # type: ignore[union-attr]
            model=settings.segmentation_model,
            input=[
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{image_base64}",
                        },
                    ],
                }
            ],
            metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
        ) as stream:
            chunks: list[str] = []
            for event in stream:
                if getattr(event, "type", "") == "response.output_text.delta":
                    chunks.append(getattr(event, "delta", ""))
            final = stream.get_final_response()
            status = getattr(final, "status", "completed")
            if status != "completed":
                raise MetaAPIError(f"SAM 3.1 response did not complete (status={status}).")
            return "".join(chunks)
    except APITimeoutError as exc:
        raise MetaAPIError(f"SAM 3.1 timed out for {prompt!r}: {exc}") from exc
    except APIConnectionError as exc:
        raise MetaAPIError(f"SAM 3.1 connection failed for {prompt!r}: {exc}") from exc
    except APIStatusError as exc:
        if exc.status_code == 400:
            # Bad prompt/metadata: permanent for this request, do not retry.
            raise MetaAPIPermanentError(f"SAM 3.1 rejected the request: {exc}") from exc
        raise MetaAPIError(f"SAM 3.1 request failed for {prompt!r}: {exc}") from exc


def segment_with_sam(
    image_base64: str,
    prompts: list[str],
    client: MetaClient | None = None,
) -> list[dict]:
    """Call SAM 3.1 once per prompt; returns normalized detections."""
    meta = client or MetaClient()
    oa = meta.openai_client()

    detections: list[dict] = []
    for prompt in prompts:
        short = prompt.strip()
        if not short or len(short.split()) > 6:
            raise MetaAPIPermanentError(
                f"Invalid SAM prompt {prompt!r}: use a short single-object noun phrase."
            )

        def _call(p: str = short) -> list[dict]:
            text = _stream_sam_text(oa, p, image_base64)
            return parse_sam_text(text, p)

        key = f"{hash(image_base64) % 10_000_000}:{short}"
        cached = _cache_get(key)
        if cached is not None:
            detections.extend(cached)
            continue
        result = call_with_retry(_call)
        _cache_put(key, result)
        detections.extend(result)
    return detections


def segment(
    image_base64: str,
    prompts: list[str],
    client: MetaClient | None = None,
    image_variant: str = "default",
) -> tuple[list[dict], bool]:
    """Unified entry point. Returns (detections, mocked)."""
    if settings.mock_meta_api:
        return mock_segment(prompts, image_variant), True
    if not image_base64:
        raise MetaAPIError("Empty frame: could not read the camera snapshot.")
    return segment_with_sam(image_base64, prompts, client), False
