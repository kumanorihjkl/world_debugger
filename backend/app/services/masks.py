"""Mask contour extraction from SAM 3.1 records.

Decoding itself uses the official `meta_sam_parser` package (zero-dependency,
typed, built against the documented wire grammar). This module only:

1. pairs box tokens with mask tokens (documented order: box first, then mask),
2. traces the largest boundary loop of the decoded raster (Moore tracing),
3. maps raster pixels into normalized image coordinates via the record's
   box bounds (mask rasters are box-local per the official types).
"""

from __future__ import annotations

import re

_MASK_RE = re.compile(r"<\|mask;x=(\d+);y=(\d+)(?:;c=[\d.]+)?;data=(\d+),(\d+),([^|]*)\|>")

MAX_POLYGON_POINTS = 64


def extract_mask_tokens(text: str) -> list[dict]:
    """Extract raw mask records in wire order."""
    masks: list[dict] = []
    for match in _MASK_RE.finditer(text or ""):
        try:
            height, width = int(match.group(3)), int(match.group(4))
        except ValueError:
            continue
        payload = match.group(5)
        if width <= 0 or height <= 0 or not payload:
            continue
        masks.append(
            {
                "encoding": "lossless" if payload.startswith("~") else "one_bit",
                "payload": payload,
                "width": width,
                "height": height,
            }
        )
    return masks


def decode_raster(mask: dict) -> tuple[bytes, int, int] | None:
    """Decode a mask record to a (raster, width, height) tuple, or None."""
    from meta_sam_parser import SegmentationMask, decode_mask_to_raster

    try:
        raster = decode_mask_to_raster(
            SegmentationMask(
                encoding=mask["encoding"],
                payload=mask["payload"],
                width=mask["width"],
                height=mask["height"],
            )
        )
    except Exception:
        return None
    return (raster, mask["width"], mask["height"])


def _neighbors_8(x: int, y: int) -> list[tuple[int, int]]:
    # Clockwise starting west (Moore neighborhood).
    return [
        (x - 1, y),
        (x - 1, y - 1),
        (x, y - 1),
        (x + 1, y - 1),
        (x + 1, y),
        (x + 1, y + 1),
        (x, y + 1),
        (x - 1, y + 1),
    ]


def trace_boundary(raster: bytes, width: int, height: int) -> list[tuple[int, int]]:
    """Trace the largest 8-connected foreground boundary loop (Moore tracing)."""
    if len(raster) != width * height:
        return []

    def filled(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and raster[y * width + x] == 1

    visited: set[tuple[int, int]] = set()
    best: list[tuple[int, int]] = []
    for sy in range(height):
        for sx in range(width):
            if not filled(sx, sy) or (sx, sy) in visited:
                continue
            # Flood-fill this component to mark it visited.
            component: list[tuple[int, int]] = []
            stack = [(sx, sy)]
            visited.add((sx, sy))
            while stack:
                px, py = stack.pop()
                component.append((px, py))
                for nx, ny in _neighbors_8(px, py):
                    if filled(nx, ny) and (nx, ny) not in visited:
                        visited.add((nx, ny))
                        stack.append((nx, ny))
            loop = _trace_single(raster, width, height, filled, component[0])
            if len(loop) > len(best):
                best = loop
    return best


def _trace_single(
    raster: bytes,
    width: int,
    height: int,
    filled: object,
    start: tuple[int, int],
) -> list[tuple[int, int]]:
    is_filled = filled  # type: ignore[assignment]
    boundary = [start]
    # Backtrack pixel: pretend we entered from the west.
    prev = (start[0] - 1, start[1])
    current = start
    for _ in range(width * height + 1):
        neighborhood = _neighbors_8(*current)
        try:
            backtrack_index = neighborhood.index(prev)
        except ValueError:
            backtrack_index = 0
        found = None
        for k in range(1, 9):
            cand = neighborhood[(backtrack_index + k) % 8]
            if is_filled(*cand):  # type: ignore[operator]
                found = cand
                break
        if found is None:
            break
        if found == start and len(boundary) > 2:
            break
        prev, current = current, found
        boundary.append(current)
    return boundary


def simplify(points: list[tuple[float, float]], max_points: int = MAX_POLYGON_POINTS) -> list[tuple[float, float]]:
    if len(points) <= max_points:
        return points
    stride = len(points) / max_points
    return [points[int(i * stride)] for i in range(max_points)]


def raster_to_polygon(
    raster: bytes,
    width: int,
    height: int,
    bounds: tuple[float, float, float, float],
    src_w: int,
    src_h: int,
) -> list[tuple[float, float]] | None:
    """Convert a box-local raster to normalized image-space polygon points.

    `bounds` is the half-open (left, top, right, bottom) box in source pixels.
    """
    loop = trace_boundary(raster, width, height)
    if len(loop) < 3:
        return None
    left, top, right, bottom = bounds
    box_w = max(1.0, right - left)
    box_h = max(1.0, bottom - top)
    points = [
        (
            min(1.0, max(0.0, (left + (x + 0.5) / width * box_w) / src_w)),
            min(1.0, max(0.0, (top + (y + 0.5) / height * box_h) / src_h)),
        )
        for x, y in loop
    ]
    return simplify(points)
