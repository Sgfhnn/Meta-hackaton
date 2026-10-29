import json

from evals import eval_matrix


def write_evidence(tmp_path, name, **evidence):
    (tmp_path / name).write_text(json.dumps(evidence))


def test_exact_wrong_and_rescan_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_matrix, "EVIDENCE", tmp_path)
    write_evidence(
        tmp_path,
        "exact.json",
        gt_total=150,
        true_denoms=[100, 50],
        arm_a_notes=[{"denom": 100}, {"denom": 50}],
        arm_a_total=150,
        arm_b_notes=[{"denom": 100, "conf": None}, {"denom": 50, "conf": 0.8}],
        arm_b_total=150,
    )
    write_evidence(
        tmp_path,
        "wrong.json",
        gt_total=100,
        true_denoms=[100],
        arm_a_notes=[],
        arm_a_total=None,
        arm_b_notes=[{"denom": 50}],
        arm_b_total=50,
    )
    write_evidence(
        tmp_path,
        "rescan.json",
        gt_total=100,
        true_denoms=[100],
        arm_a_notes=[],
        arm_a_total=None,
        arm_b_notes=[],
        arm_b_total=None,
        plain_resolved=False,
        guided_resolved=True,
    )

    evidence = eval_matrix.load_evidence()
    outcomes = {r["photo"]: r["outcome"] for r in eval_matrix.rows(evidence) if r["arm"] == "B"}
    assert outcomes == {"exact": "exact", "wrong": "wrong", "rescan": "rescan"}

    summary = eval_matrix.gate_summary(evidence)
    assert summary["B"]["exact_totals"] == 1
    assert summary["B"]["wrong_totals"] == 1
    assert summary["B"]["rescans"] == 1
    assert summary["guided_minus_plain"] == 1
    assert summary["gate_v2"]["zero_wrong_totals"] is False


def test_per_note_uses_multiset_matching():
    correct, total = eval_matrix.note_score([{"denom": 100}, {"denom": 100}], [100, 50])
    assert (correct, total) == (1, 2)


def test_mean_conf_skips_missing_and_none():
    assert eval_matrix.mean_conf([{"conf": None}, {}, {"conf": 0.5}]) == 0.5
    assert eval_matrix.mean_conf([{"conf": None}, {}]) == ""
