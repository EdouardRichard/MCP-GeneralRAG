"""T040: pure aggregation functions of ``services/memory_statistics.py``.

Caliber (tasks.md T038/T040, research.md R9, quickstart.md VS-11):

* salience percentiles use linear interpolation between the two order statistics
  (the same estimator ``percentile_cont`` implements in PostgreSQL, so the pure
  function and the SQL projection cannot disagree);
* buckets are half-open ``[lower, upper)`` on the frozen edges
  ``0.0/0.2/0.4/0.6/0.8/1.0`` and every value -- including an over-range one --
  lands in exactly one bucket, so the bucket counts sum to the sample count;
* an empty domain reports the real zero counts ``0`` and a ``null`` quantile,
  never a fabricated rate and never ``0`` standing in for "not measurable";
* no request payload can ever carry a free-text key: the aggregation only ever
  passes projection columns through and copies the fixed numeric vocabulary;
* a single sample is measurable (``p50 == p90 == p95 == value``), not a zero
  denominator;
* ``total`` is consistent with the browse endpoint's own caliber for the same
  domain and the same projection.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import BigInteger, cast, func, select, true
from sqlalchemy.dialects.postgresql import JSONB

from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.services.memory_statistics import (
    KINDS,
    PROVENANCES,
    SALIENCE_BUCKETS,
    STATUSES,
    aggregate_entry_rows,
    bucket_index,
    distribution,
    salience_summary,
)

#: The three free-text keys the 015 contract forbids plus the two the spec names.
FORBIDDEN_TEXT_KEYS = ("content", "content_excerpt", "title", "evidence", "query")


def _entry(**overrides) -> dict:
    """One projection entry row with realistic free text and a pending write status."""
    row = {
        "memory_id": 1,
        "knowledge_scope_id": 42,
        "kind": "episodic",
        "provenance": "soft",
        "status": "active",
        "write_status": "complete",
        "title": "Private note title",
        "content_text": "Private note body",
        "evidence_refs": [{"quote_excerpt": "private evidence"}],
        "inference_meta": {"supporting_evidence": ["private supporting evidence"]},
        "salience": 0.4,
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- #
# bucket boundaries
# --------------------------------------------------------------------------- #


def test_bucket_edges_are_half_open_lower_inclusive() -> None:
    """A value on an edge belongs to the bucket that edge opens."""
    assert [bucket_index(value) for value in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)] == [0, 1, 2, 3, 4, 5]
    # just below an edge stays in the previous bucket
    assert bucket_index(0.199999) == 0
    assert bucket_index(0.799999) == 3
    # exact binary floats sitting on an edge are not lost to floor-division rounding
    assert bucket_index(0.6) == 3 and bucket_index(1.4) == 5


def test_bucket_index_is_total_for_out_of_range_values() -> None:
    """Salience is not clamped by the model, so either tail must still bucket."""
    assert bucket_index(-0.5) == 0
    assert bucket_index(2.5) == len(SALIENCE_BUCKETS) - 1


def test_every_bucket_edge_is_reachable() -> None:
    values = [edge for edge, _ in SALIENCE_BUCKETS]
    counts = [0] * len(SALIENCE_BUCKETS)
    for value in values:
        counts[bucket_index(value)] += 1
    assert counts == [1] * len(SALIENCE_BUCKETS)


def test_salience_summary_on_empty_input_is_a_real_zero_not_a_rate() -> None:
    summary = salience_summary([])
    assert summary["p50"] is None and summary["p90"] is None and summary["p95"] is None
    assert summary["buckets"] == [
        {"lower": lower, "upper": upper, "count": 0} for lower, upper in SALIENCE_BUCKETS
    ]


def test_salience_summary_on_a_single_sample_is_measurable() -> None:
    summary = salience_summary([0.42])
    assert (summary["p50"], summary["p90"], summary["p95"]) == (0.42, 0.42, 0.42)
    assert [bucket["count"] for bucket in summary["buckets"]] == [0, 0, 1, 0, 0, 0]


def test_salience_summary_interpolates_like_percentile_cont() -> None:
    summary = salience_summary([0.1, 0.2])
    assert summary["p50"] == pytest.approx(0.15)
    assert summary["p90"] == pytest.approx(0.19)
    assert summary["p95"] == pytest.approx(0.195)


def test_salience_summary_buckets_values_on_the_boundary() -> None:
    summary = salience_summary([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    assert [bucket["count"] for bucket in summary["buckets"]] == [1, 1, 1, 1, 1, 1]
    assert summary["p50"] == pytest.approx(0.5)


def test_bucket_counts_always_sum_to_the_sample_count() -> None:
    values = [0.0, 0.05, 0.19, 0.2, 0.399, 0.4, 0.5, 0.7, 0.8, 0.99, 1.0, 1.5, -0.1]
    summary = salience_summary(values)
    assert sum(bucket["count"] for bucket in summary["buckets"]) == len(values)
    assert summary["p50"] is not None


# --------------------------------------------------------------------------- #
# domain-level aggregation
# --------------------------------------------------------------------------- #


def test_distribution_maps_the_frozen_vocabulary_and_defaults_to_zero() -> None:
    assert distribution({"episodic": 2, "unknown_vocabulary": 9}, KINDS) == {
        "episodic": 2, "semantic": 0, "procedural": 0,
    }


def test_aggregate_entry_rows_reports_an_unknown_value_under_other_never_by_guessing() -> None:
    stats = aggregate_entry_rows([_entry(kind="sensory", provenance="vibes", status="zombie")])
    assert stats["kind_distribution"] == {"episodic": 0, "semantic": 0, "procedural": 0, "other": 1}
    assert stats["provenance_distribution"] == {"hard": 0, "soft": 0, "distilled": 0, "other": 1}
    assert stats["status_distribution"] == {"active": 0, "superseded": 0, "retired": 0, "quarantined": 0, "other": 1}
    assert stats["total"] == 1


def test_aggregate_entry_rows_on_an_empty_domain_is_zero_counts() -> None:
    stats = aggregate_entry_rows([])
    assert stats["total"] == 0
    assert stats["kind_distribution"] == {"episodic": 0, "semantic": 0, "procedural": 0}
    assert stats["provenance_distribution"] == {"hard": 0, "soft": 0, "distilled": 0}
    assert stats["status_distribution"] == {"active": 0, "superseded": 0, "retired": 0, "quarantined": 0}
    assert (stats["p50"], stats["p90"], stats["p95"]) == (None, None, None)
    assert sum(bucket["count"] for bucket in stats["buckets"]) == 0


def test_aggregate_entry_rows_total_is_the_sum_of_every_observed_entry() -> None:
    rows = [
        _entry(kind="episodic", provenance="soft", status="active", salience=0.1),
        _entry(kind="semantic", provenance="hard", status="active", salience=0.5),
        _entry(kind="procedural", provenance="distilled", status="superseded", salience=0.9),
        _entry(kind="semantic", provenance="soft", status="retired", salience=0.9),
        _entry(kind="episodic", provenance="hard", status="quarantined", salience=0.0),
    ]
    stats = aggregate_entry_rows(rows)
    assert stats["total"] == len(rows)
    assert stats["kind_distribution"] == {"episodic": 2, "semantic": 2, "procedural": 1}
    assert stats["provenance_distribution"] == {"hard": 2, "soft": 2, "distilled": 1}
    assert stats["status_distribution"] == {"active": 2, "superseded": 1, "retired": 1, "quarantined": 1}
    assert sum(bucket["count"] for bucket in stats["buckets"]) == len(rows)
    assert stats["p50"] == pytest.approx(0.5)


def test_aggregate_entry_rows_ignores_a_missing_salience_and_reports_all_statuses() -> None:
    """A terminal status is a count of real data, never a zero denominator."""
    stats = aggregate_entry_rows([
        _entry(status="retired", provenance="hard"),
        _entry(status="quarantined", provenance="distilled"),
    ])
    assert stats["status_distribution"]["retired"] == 1
    assert stats["status_distribution"]["quarantined"] == 1
    assert stats["total"] == 2
    assert sum(bucket["count"] for bucket in stats["buckets"]) == 2


# --------------------------------------------------------------------------- #
# explicit no-body assertion
# --------------------------------------------------------------------------- #


def test_aggregate_entry_rows_payload_never_carries_a_free_text_key() -> None:
    stats = aggregate_entry_rows([
        _entry(title="Leaked title", content_text="Leaked body",
               content_excerpt="Leaked excerpt", query="Leaked query"),
    ])
    payload = json.dumps(stats, ensure_ascii=False, sort_keys=True)
    for key in FORBIDDEN_TEXT_KEYS:
        assert f'"{key}"' not in payload, f"free-text key {key!r} reached the aggregated payload"
    # The fixture's text values themselves must not have been copied either.
    for value in ("Leaked title", "Leaked body", "Leaked excerpt", "Leaked query"):
        assert value not in payload


def test_aggregate_entry_rows_emits_exactly_the_contract_key_set() -> None:
    """Construction, not filtering: the aggregation emits a fixed key set only."""
    stats = aggregate_entry_rows([_entry()])
    assert set(stats) == {
        "total", "kind_distribution", "provenance_distribution", "status_distribution",
        "p50", "p90", "p95", "buckets",
    }
    assert set(stats["kind_distribution"]) == set(KINDS)
    assert set(stats["provenance_distribution"]) == set(PROVENANCES)
    assert set(stats["status_distribution"]) == set(STATUSES)


def test_projection_vocabulary_matches_the_frozen_contract() -> None:
    """The numeric vocabulary is the schema's own property set, not a restatement."""
    from tests.memory_eval_datasets import load_schema

    schema = load_schema("memory-stats-response.schema.json")
    properties = schema["properties"]
    assert set(KINDS) == set(properties["kind_distribution"]["properties"])
    assert set(PROVENANCES) == set(properties["provenance_distribution"]["properties"])
    assert set(STATUSES) == set(properties["status_distribution"]["properties"])
    assert len(SALIENCE_BUCKETS) == 6


# --------------------------------------------------------------------------- #
# total consistency with the browse endpoint (same domain, same caliber)
# --------------------------------------------------------------------------- #


def _browse_caliber_total():
    """The browse endpoint's own predicate and counting caliber (api/memory.py:283-290)."""
    entries = func.jsonb_each(MemoryProjectionMeta.payload["state"]["entries"]) \
        .table_valued("key", "value").lateral()
    conditions = (MemoryProjectionMeta.projection_type == "manifest",
                  MemoryProjectionMeta.status == "complete",
                  MemoryProjectionMeta.payload["verification_version"].as_integer() == 1)
    return entries, conditions


@pytest.mark.asyncio
async def test_stats_total_matches_the_browse_caliber_for_the_same_domain(db_session):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from rag_mcp.models.knowledge_scope import KnowledgeScope
    from rag_mcp.services.memory_statistics import domain_statistics
    from rag_mcp.utils.snowflake import generate_id

    sid = generate_id()
    db_session.add(KnowledgeScope(scope_id=sid, name=f"015 stats {uuid4()}",
                                  slug=f"c015-eval-stats-{sid}", scope_type="project",
                                  domain_key="generic"))
    await db_session.commit()

    result = await domain_statistics(db_session, sid)
    assert result["total"] == 0
    salience = result["salience_distribution"]
    assert salience["p50"] is None and salience["p90"] is None and salience["p95"] is None
    assert sum(bucket["count"] for bucket in salience["buckets"]) == 0
    assert result["status_distribution"] == {"active": 0, "superseded": 0, "retired": 0, "quarantined": 0}
    assert result["rollback_count"] == 0
    assert result["consolidation_run_count"] == 0
    assert result["scope_id"] == str(sid)
    assert result["domain_key"] == "generic"
    parsed = datetime.fromisoformat(result["generated_at"])
    assert parsed.tzinfo is not None and parsed <= datetime.now(UTC) + timedelta(seconds=5)

    # Record one real memory through the production service, then compare calibers.
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
    from rag_mcp.services.memory_service import MemoryService

    service = MemoryService(db_session, embedding_provider=LocalCPUEmbeddingProvider())
    written = await service.record({
        "scope_id": sid, "kind": "episodic", "provenance": "soft",
        "content": "015 statistics consistency probe: keep the scope explicit.",
        "inference_meta": {"source": "015 T040", "confidence": 0.8, "model_version": "015.eval.1",
                           "time": datetime.now(UTC).isoformat(), "supporting_evidence": []},
    })
    assert written["memory_id"] is not None

    result = await domain_statistics(db_session, sid)
    entries, conditions = _browse_caliber_total()
    data = cast(entries.c.value, JSONB)
    browse_total = await db_session.scalar(
        select(func.count()).select_from(MemoryProjectionMeta).join(entries, true())
        .where(MemoryProjectionMeta.knowledge_scope_id == sid, *conditions))
    assert result["total"] == browse_total == 1
    salience = result["salience_distribution"]
    assert sum(bucket["count"] for bucket in salience["buckets"]) == result["total"]
    assert salience["p50"] is not None and salience["p50"] == salience["p90"] == salience["p95"]
    assert len(result["generated_at"]) >= 20
