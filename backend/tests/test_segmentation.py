"""SAM output parser tests using the documented special-token grammar."""

from app.services.segmentation import parse_sam_text

DOC_EXAMPLE = (
    "<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|>"
    "<|mask;x=0;y=0;data=46,101,~...|>,"
    "1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561|>"
    "<|mask;x=0;y=0;data=46,81,~...|>,"
    "2<|box;x1=516;y1=117;x2=536;y2=150;w=537;h=561|>"
    "<|mask;x=0;y=0;data=34,21,~...|>"
)


def test_parse_doc_example_normalizes_by_wh() -> None:
    dets = parse_sam_text(DOC_EXAMPLE, "thing")
    assert len(dets) == 3
    first = dets[0]["bbox"]
    assert first == [
        353 / 537,
        382 / 561,
        453 / 537,
        427 / 561,
    ]
    assert all(0.0 <= v <= 1.0 for d in dets for v in d["bbox"])
    assert all(d["confidence"] == 1.0 for d in dets)


def test_parse_confidence_variant() -> None:
    text = "<0f>1<|box;x1=444;y1=625;x2=679;y2=850;w=1800;h=1200;c=0.9609375|>"
    dets = parse_sam_text(text, "cup")
    assert len(dets) == 1
    assert dets[0]["confidence"] == 0.9609375
    assert dets[0]["concept"] == "cup"


def test_empty_output_is_no_detections() -> None:
    assert parse_sam_text("", "cup") == []
    assert parse_sam_text("no matches here", "cup") == []
