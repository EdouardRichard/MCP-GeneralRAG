"""Regression reruns must preserve the reports they are compared against."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "eval/run_regression_011.py"
    spec = importlib.util.spec_from_file_location("regression_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fresh_directory_redirects_all_report_outputs(runner, tmp_path):
    configure = getattr(runner, "configure_output_directory", None)
    assert callable(configure), "runner has no safe output-directory support"
    groups = configure(tmp_path)
    for group in groups:
        assert Path(group["output"]).parent == tmp_path
        if "cmd" in group:
            cmd = group["cmd"]("dataset.json") if "prepare" in group else group["cmd"]()
            for flag in ("--output", "--format-report"):
                if flag in cmd:
                    assert Path(cmd[cmd.index(flag) + 1]).parent == tmp_path
    assert all("011_" in g["output"] for g in runner.GROUPS)


def test_existing_artifact_is_never_overwritten(runner, tmp_path):
    configure = getattr(runner, "configure_output_directory", None)
    assert callable(configure), "runner has no artifact protection"
    (tmp_path / "012_001_regression_report.json").write_text("historical")
    with pytest.raises(FileExistsError):
        configure(tmp_path)
    assert (tmp_path / "012_001_regression_report.json").read_text() == "historical"


def test_missing_metric_cannot_pass_non_regression(runner, tmp_path):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps({"recall": 1.0, "mrr": 1.0}))
    new.write_text(json.dumps({"recall": 1.0}))
    group = {"id": "incomplete", "output": str(new), "historical": str(old), "extract": dict}
    result = runner._compare(group)
    assert result["all_passed"] is False, "intersection-only comparison hides missing metrics"


def test_eval_has_no_synthetic_vector_implementation():
    path = Path(__file__).resolve().parents[3] / "eval/run_eval.py"
    assert "def _hash_vector" not in path.read_text(encoding="utf-8")


def test_historical_quickstart_test_does_not_rewrite_its_baseline(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "integration/test_quickstart_001_report.py"
    spec = importlib.util.spec_from_file_location("quickstart_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    historical = tmp_path / "historical.json"
    historical.write_text('{"generated_at":"historical"}')
    monkeypatch.setattr(module, "_REPORT_PATH", historical)
    module.TestQuickstart001Report().test_report_written_and_all_pass()
    assert historical.read_bytes() == b'{"generated_at":"historical"}'
