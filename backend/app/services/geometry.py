"""Deterministic 2D geometry over normalized image-space boxes.

All coordinates are normalized to [0, 1]. Distances are normalized by the
image diagonal (sqrt(2) in normalized space) so they stay in [0, 1].
Never claim real-world metric distances from a single RGB frame.
"""

from __future__ import annotations

import math

from app.models.scene import BoundingBox

_DIAGONAL = math.sqrt(2.0)


def centroid(bbox: BoundingBox) -> tuple[float, float]:
    return ((bbox.x_min + bbox.x_max) / 2.0, (bbox.y_min + bbox.y_max) / 2.0)


def area(bbox: BoundingBox) -> float:
    w = max(0.0, bbox.x_max - bbox.x_min)
    h = max(0.0, bbox.y_max - bbox.y_min)
    return w * h


def intersection_area(a: BoundingBox, b: BoundingBox) -> float:
    w = max(0.0, min(a.x_max, b.x_max) - max(a.x_min, b.x_min))
    h = max(0.0, min(a.y_max, b.y_max) - max(a.y_min, b.y_min))
    return w * h


def iou(a: BoundingBox, b: BoundingBox) -> float:
    inter = intersection_area(a, b)
    union = area(a) + area(b) - inter
    if union <= 0:
        return 0.0
    return inter / union


def overlaps(a: BoundingBox, b: BoundingBox) -> bool:
    return intersection_area(a, b) > 0.0


def bbox_gap(a: BoundingBox, b: BoundingBox) -> float:
    """Edge-to-edge gap in normalized units (0 when overlapping)."""
    dx = max(0.0, max(a.x_min - b.x_max, b.x_min - a.x_max))
    dy = max(0.0, max(a.y_min - b.y_max, b.y_min - a.y_max))
    return math.hypot(dx, dy)


def centroid_distance(a: BoundingBox, b: BoundingBox) -> float:
    ax, ay = centroid(a)
    bx, by = centroid(b)
    return math.hypot(ax - bx, ay - by)


def normalized_distance(a: BoundingBox, b: BoundingBox) -> float:
    """Gap normalized by image diagonal, in [0, 1]."""
    return bbox_gap(a, b) / _DIAGONAL


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test."""
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            x_intersect = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def bbox_inside_zone(bbox: BoundingBox, polygon: list[tuple[float, float]]) -> bool:
    """True when the bbox centroid is inside the zone polygon."""
    cx, cy = centroid(bbox)
    return point_in_polygon(cx, cy, polygon)


def bbox_zone_overlap_ratio(
    bbox: BoundingBox, polygon: list[tuple[float, float]], samples: int = 25
) -> float:
    """Fraction of a bbox covered by a zone, estimated on a grid.

    Exact polygon-bbox clipping is overkill for the MVP; a deterministic
    grid sample is predictable and easy to test.
    """
    if not polygon:
        return 0.0
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    zx0, zx1 = min(xs), max(xs)
    zy0, zy1 = min(ys), max(ys)
    # Fast path: use bbox-vs-zone-bbox overlap when zone is a rectangle.
    if len(polygon) == 4 and set(xs).__len__() == 2 and set(ys).__len__() == 2:
        zone_box = BoundingBox(x_min=zx0, y_min=zy0, x_max=zx1, y_max=zy1)
        inter = intersection_area(bbox, zone_box)
        a = area(bbox)
        return inter / a if a > 0 else 0.0
    n = max(2, int(math.sqrt(samples)))
    hits = 0
    total = 0
    for i in range(n):
        for j in range(n):
            fx = (i + 0.5) / n
            fy = (j + 0.5) / n
            px = bbox.x_min + fx * (bbox.x_max - bbox.x_min)
            py = bbox.y_min + fy * (bbox.y_max - bbox.y_min)
            total += 1
            if point_in_polygon(px, py, polygon):
                hits += 1
    return hits / total if total else 0.0
