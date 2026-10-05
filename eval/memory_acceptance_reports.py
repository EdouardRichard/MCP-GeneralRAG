"""Evidence helpers: exclusive output creation and measured quality comparisons."""
import json
from pathlib import Path


def write_report(path, report):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


def compare_quality(baseline, current, *, tolerance=1e-6):
    differences = []
    compared = 0
    for group, metrics in baseline.items():
        if not group.endswith("_metrics") or not isinstance(metrics, dict):
            continue
        for name, values in metrics.items():
            if "latency" in name:
                continue
            for statistic, expected in values.items():
                actual = current.get(group, {}).get(name, {}).get(statistic)
                compared += 1
                if actual is None or abs(actual - expected) > tolerance:
                    differences.append({"metric": f"{group}.{name}.{statistic}",
                                        "historical": expected, "current": actual})
    return {"passed": compared > 0 and not differences, "compared": compared,
            "tolerance": tolerance, "differences": differences}
