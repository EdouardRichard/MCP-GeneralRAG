def test_regression_suite_entrypoint_exists():
    from pathlib import Path
    assert (Path(__file__).parents[3] / "eval").exists()
