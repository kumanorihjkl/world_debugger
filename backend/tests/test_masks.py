"""Mask contour tests: synthetic rasters + mapping math (no API needed)."""

from app.services.masks import (
    extract_mask_tokens,
    raster_to_polygon,
    simplify,
    trace_boundary,
)


def _raster(rows: list[str]) -> tuple[bytes, int, int]:
    h = len(rows)
    w = len(rows[0])
    return (bytes(c == "#" for row in rows for c in row), w, h)


def test_trace_square_loop() -> None:
    raster, w, h = _raster(
        [
            "....",
            ".##.",
            ".##.",
            "....",
        ]
    )
    loop = trace_boundary(raster, w, h)
    assert len(loop) >= 4
    assert {p for p in loop} == {(1, 1), (2, 1), (1, 2), (2, 2)}


def test_empty_raster_has_no_polygon() -> None:
    raster, w, h = _raster(["....", "...."])
    assert trace_boundary(raster, w, h) == []
    assert raster_to_polygon(raster, w, h, (0, 0, 4, 2), 4, 2) is None


def test_mapping_to_normalized_coords() -> None:
    raster, w, h = _raster(
        [
            "....",
            ".##.",
            ".##.",
            "....",
        ]
    )
    poly = raster_to_polygon(raster, w, h, (100, 100, 300, 300), 1000, 1000)
    assert poly is not None
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    # Box covers [0.1, 0.3]^2; contour lives strictly inside it.
    assert min(xs) >= 0.1 and max(xs) <= 0.3
    assert min(ys) >= 0.1 and max(ys) <= 0.3
    assert max(xs) - min(xs) > 0.0


def test_simplify_caps_points() -> None:
    pts = [(float(i), 0.0) for i in range(200)]
    assert len(simplify(pts)) == 64
    assert len(simplify(pts[:10])) == 10


def test_extract_mask_tokens_doc_example() -> None:
    text = (
        "<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|>"
        "<|mask;x=0;y=0;data=46,101,~abc|>"
    )
    masks = extract_mask_tokens(text)
    assert len(masks) == 1
    assert masks[0]["encoding"] == "lossless"
    assert (masks[0]["width"], masks[0]["height"]) == (101, 46)
