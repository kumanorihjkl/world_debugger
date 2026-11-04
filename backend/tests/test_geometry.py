"""Geometry unit tests: near/far, overlap, zones, normalized distance."""

from app.models.scene import BoundingBox
from app.services import geometry as geo


def _box(x0: float, y0: float, x1: float, y1: float) -> BoundingBox:
    return BoundingBox(x_min=x0, y_min=y0, x_max=x1, y_max=y1)


def test_iou_overlap() -> None:
    a = _box(0.1, 0.1, 0.5, 0.5)
    b = _box(0.3, 0.3, 0.7, 0.7)
    assert geo.overlaps(a, b)
    assert 0.0 < geo.iou(a, b) < 1.0


def test_no_overlap() -> None:
    a = _box(0.0, 0.0, 0.2, 0.2)
    b = _box(0.8, 0.8, 1.0, 1.0)
    assert not geo.overlaps(a, b)
    assert geo.iou(a, b) == 0.0


def test_near_far_normalized_distance() -> None:
    close_a = _box(0.10, 0.45, 0.30, 0.65)
    close_b = _box(0.32, 0.45, 0.50, 0.65)
    far_b = _box(0.78, 0.10, 0.93, 0.35)
    assert geo.normalized_distance(close_a, close_b) < 0.15
    assert geo.normalized_distance(close_a, far_b) > 0.15


def test_overlapping_gap_is_zero() -> None:
    a = _box(0.1, 0.1, 0.5, 0.5)
    b = _box(0.3, 0.3, 0.7, 0.7)
    assert geo.normalized_distance(a, b) == 0.0


def test_zone_centroid_inside() -> None:
    zone = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    assert geo.bbox_inside_zone(_box(0.4, 0.4, 0.5, 0.5), zone)
    assert not geo.bbox_inside_zone(_box(0.0, 0.0, 0.1, 0.1), zone)


def test_zone_overlap_ratio_rectangle_fast_path() -> None:
    zone = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]
    assert geo.bbox_zone_overlap_ratio(_box(0.4, 0.4, 0.5, 0.5), zone) == 1.0
    assert geo.bbox_zone_overlap_ratio(_box(0.0, 0.0, 0.1, 0.1), zone) == 0.0
