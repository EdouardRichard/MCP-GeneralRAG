import importlib.util
from pathlib import Path


def test_no_decay_feedback_arm_is_rejected_and_reports_concentration():
    path = Path(__file__).parents[3] / "eval/memory_read_diagnostics.py"
    spec = importlib.util.spec_from_file_location("memory_read_diagnostics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.decay_comparison()
    assert report["unsafe_no_decay"]["compliant"] is False
    assert report["guarded_no_decay"]["salience_rank_uses"] == 0
    assert report["forced_decay"]["compliant"] is True
    for arm in report.values():
        assert len(arm["access_distribution"]) == 12
        assert 0 <= arm["top_k_concentration"] <= 1
        assert 0 <= arm["coverage"] <= 1
        assert arm["entropy"] >= 0
        assert len(arm["latency_ms"]) == 2
