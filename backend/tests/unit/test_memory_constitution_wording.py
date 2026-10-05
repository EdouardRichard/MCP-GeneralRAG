from pathlib import Path


def test_current_blueprint_matches_ratified_thirteen_principle_constitution():
    root = Path(__file__).parents[3]
    constitution = (root / ".specify/memory/constitution.md").read_text(encoding="utf-8")
    blueprint_path = root / "外置型记忆回路-开发实施蓝图.md"
    plan = (root / "specs/012-memory-foundation-write-read-loop/plan.md").read_text(encoding="utf-8")
    assert "**Version**: 1.4.0" in constitution
    assert len([line for line in constitution.splitlines() if line.startswith("### ")]) == 13
    assert "Pre-Research Gate (v1.4.0)" in plan and "XIII Governed Trajectory" in plan
    # Root blueprints are optional local inputs excluded from version control.
    if blueprint_path.exists():
        blueprint = blueprint_path.read_text(encoding="utf-8")
        assert "十三原则，XII = 外置记忆回路，XIII = 受治理轨迹" in blueprint
        assert "十二原则" not in blueprint
        assert "宪法 v1.4.0 已于 2026-10-04 批准生效" in blueprint
