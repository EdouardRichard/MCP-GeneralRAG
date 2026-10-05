"""Repeatable feedback experiment using the production salience and RRF code."""
import math
from statistics import median, quantiles
from time import perf_counter

from rag_mcp.fusion.rrf import weighted_memory_rrf
from rag_mcp.services.salience_service import SalienceService


def decay_comparison():
    reports = {}
    for arm in ("unsafe_no_decay", "guarded_no_decay", "forced_decay"):
        salience = {mid: 0.0 for mid in range(1, 13)}
        accesses = dict(salience)
        durations, selected_sets = [], []
        rank_uses = 0
        service = SalienceService()
        for day in range(120):
            started = perf_counter()
            rotated = list(salience)[day % 12:] + list(salience)[:day % 12]
            paths = {"dense": rotated, "recency": rotated, "kind": list(salience)}
            signals = {mid: value if arm == "unsafe_no_decay" else service.rank_signal(value,
                       decay_rate=.05 if arm == "forced_decay" else 0, age_days=1) for mid, value in salience.items()}
            if arm != "guarded_no_decay":
                paths["salience"] = sorted(signals, key=lambda mid: (-signals[mid], mid))
                rank_uses += 1
            ranked = weighted_memory_rrf(paths, {"dense": 1, "recency": .5, "kind": .3, "salience": .2})
            selected = {row["memory_id"] for row in ranked[:3]}
            selected_sets.append(selected)
            for mid in salience:
                accesses[mid] += int(mid in selected)
                salience[mid] = service.update(salience[mid], access_count=int(mid in selected),
                                               age_days=1 if arm == "forced_decay" else 0)
            durations.append((perf_counter() - started) * 1000)
        total = sum(accesses.values())
        probabilities = [value / total for value in accesses.values() if value]
        reports[arm] = {"compliant": arm != "unsafe_no_decay", "salience_rank_uses": rank_uses,
            "access_distribution": accesses, "top_k_concentration": sum(sorted(accesses.values(), reverse=True)[:3]) / total,
            "coverage": sum(value > 0 for value in accesses.values()) / len(accesses),
            "entropy": -sum(p * math.log2(p) for p in probabilities),
            "top_k_overlap": sum(len(a & b) / 3 for a, b in zip(selected_sets, selected_sets[1:])) / (len(selected_sets) - 1),
            "latency_ms": {"p50": median(durations), "p95": quantiles(durations, n=20)[18]}}
    return reports
