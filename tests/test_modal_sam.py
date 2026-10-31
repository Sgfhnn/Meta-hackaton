"""Modal SAM endpoint helpers (modal_sam/detect.py) and its boxes as the backend reads them."""

import base64

import pytest

from birr.segment import sam
from modal_sam import detect

JPEG = base64.b64encode(b"\xff\xd8 fake jpeg bytes").decode()


def test_parse_request_defaults():
    image, prompt, threshold = detect.parse_request({"image": JPEG})
    assert image.startswith(b"\xff\xd8")
    assert prompt == "banknote"
    assert threshold == 0.5


@pytest.mark.parametrize(
    "body",
    [
        "not a dict",
        {},
        {"image": ""},
        {"image": "not base64!!"},
        {"image": JPEG, "prompt": ""},
        {"image": JPEG, "prompt": "x" * 61},
        {"image": JPEG, "threshold": 1.5},
        {"image": JPEG, "threshold": True},
        {"image": JPEG, "threshold": "0.5"},
    ],
)
def test_parse_request_rejects(body):
    with pytest.raises(detect.BadRequest):
        detect.parse_request(body)


def test_parse_request_size_limit(monkeypatch):
    monkeypatch.setattr(detect, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(detect.BadRequest):
        detect.parse_request({"image": JPEG})


def test_from_xyxy_clips_filters_and_sorts():
    boxes = [[10, 20, 110, 220], [-5, -5, 50, 50], [700, 500, 900, 700], [30, 30, 30, 90]]
    scores = [0.6, 0.9, 0.8, 0.95]
    found = detect.from_xyxy(boxes, scores, 800, 600, threshold=0.5)
    assert [d["score"] for d in found] == [0.9, 0.8, 0.6]  # zero-width box dropped
    assert found[0]["box"] == [0.0, 0.0, 50.0, 50.0]  # clipped at the top-left
    assert found[1]["box"] == [700.0, 500.0, 800.0, 600.0]  # clipped at the bottom-right
    assert detect.from_xyxy(boxes, scores, 800, 600, threshold=0.85) == found[:1]


def test_from_xywh_normalized_to_pixels():
    found = detect.from_xywh_normalized([[0.25, 0.5, 0.5, 0.25]], [0.7], 800, 600, 0.5)
    assert found == [{"box": [200.0, 300.0, 600.0, 450.0], "score": 0.7}]


def test_backend_reads_endpoint_boxes():
    """Same photo size on both sides: the backend's regions are the endpoint's boxes, normalized."""
    found = detect.from_xywh_normalized([[0.1, 0.2, 0.3, 0.4]], [0.88], 768, 576, 0.5)
    regions = sam.regions_from_modal({"model": "sam3.1", "detections": found}, 768, 576)
    assert len(regions) == 1
    assert regions[0].box == pytest.approx((0.1, 0.2, 0.3, 0.4), abs=1e-3)
    assert regions[0].score == pytest.approx(0.88)
