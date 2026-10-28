from birr.read.muse import parse as parse_muse
from birr.segment.roboflow import parse as parse_roboflow


def test_muse_parses_json_in_text():
    notes = parse_muse(
        'Here: {"notes": [{"denomination": 200, "confidence": 0.9, "status": "read"}]}'
    )
    assert [(n.denomination, n.status) for n in notes] == [(200, "read")]


def test_muse_malformed_becomes_unclear():
    notes = parse_muse("I see some money")
    assert [n.status for n in notes] == ["unclear"]


def test_muse_unknown_status_becomes_unclear():
    notes = parse_muse('{"notes": [{"denomination": 10, "status": "maybe"}]}')
    assert notes[0].status == "unclear"


def test_roboflow_polygon_to_normalized_box():
    body = {
        "prompt_results": [
            {
                "predictions": [
                    {"confidence": 0.97, "masks": [[[10, 20], [110, 20], [110, 70], [10, 70]]]}
                ]
            }
        ]
    }
    (region,) = parse_roboflow(body, width=200, height=100)
    assert region.box == (0.05, 0.2, 0.5, 0.5)
    assert region.confidence == 0.97
