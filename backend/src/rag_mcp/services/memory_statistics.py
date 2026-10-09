"""Domain-level memory statistics (015 T038, FR-044..FR-046).

The aggregation is done **at the SQL/projection layer only**.  Nothing in this
module reads ``MemoryEntry.content_text``, ``title``, ``evidence_refs``,
``inference_meta`` or any other free-form column, and nothing calls
``memory_reader.public_entry`` (which returns ``content_excerpt = content[:300]``)
to trim the body afterwards.  The response is therefore zero-body **by
construction**: :func:`aggregate_entry_rows` and :func:`domain_statistics` can
only ever emit the fixed numeric vocabulary below, so a free-text key has no code
path that could produce it.

Caliber (research.md R9):

* ``total`` / ``kind_distribution`` / ``provenance_distribution`` /
  ``status_distribution`` -- the completed ``manifest`` projection of the scope
  (the same predicate ``GET /api/memories`` uses, so the two endpoints cannot
  disagree about what "this domain currently holds" means).  A stale or absent
  manifest is reported as a real zero, never as a current reading.
* ``salience_distribution`` -- quantiles from ``percentile_cont`` (the same
  linear-interpolation estimator :func:`salience_summary` implements) over
  ``MemorySalience.salience`` restricted to the rows the completed manifest is
  allowed to report; buckets use the frozen edges and :func:`bucket_index`.
* ``consolidation_run_count`` -- distinct ``ConsolidationRunObservation.run_id``
  per scope, matching the run-list caliber of ``GET /consolidation/runs``.
* ``rollback_count`` -- ``MemoryEvent`` rows of type ``rollback`` in the scope.

A zero denominator (an empty domain) is reported as zero counts of real data and
``null`` quantiles -- never as a rate of 100 % and never as a measured zero.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Float, cast, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from rag_mcp.models.consolidation_run import ConsolidationRunObservation
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.models.memory_event import MemoryEvent
from rag_mcp.models.memory_projection_meta import MemoryProjectionMeta
from rag_mcp.models.memory_salience import MemorySalience

#: Frozen value vocabularies (memory-stats-response.schema.json property sets).
KINDS = ("episodic", "semantic", "procedural")
PROVENANCES = ("hard", "soft", "distilled")
STATUSES = ("active", "superseded", "retired", "quarantined")

#: Frozen bucket edges.  Buckets are half-open ``[lower, upper)``, the last closed.
#: Membership is decided by **exact comparison against these constants**, not by
#: floating-point division: ``0.6 // 0.2`` is ``2.0`` in binary floating point
#: (0.6/0.2 == 2.9999999999999996), so a floor-division index would file a value
#: sitting exactly on an edge into the previous bucket.
SALIENCE_BUCKET_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
SALIENCE_BUCKETS = tuple(
    (lower, SALIENCE_BUCKET_EDGES[index + 1] if index + 1 < len(SALIENCE_BUCKET_EDGES) else None)
    for index, lower in enumerate(SALIENCE_BUCKET_EDGES)
)

#: Quantiles the contract pins, with their ``percentile_cont`` fractions.
SALIENCE_FRACTIONS = (("p50", 0.5), ("p90", 0.9), ("p95", 0.95))

#: ``jsonb_extract_path_text`` is only ever applied to these closed vocabularies.
_VOCABULARY_COLUMNS = ("kind", "provenance", "status")
_VOCABULARIES = {"kind": KINDS, "provenance": PROVENANCES, "status": STATUSES}


def bucket_index(value: float) -> int:
    """The unique bucket holding ``value`` (lower-inclusive, upper-exclusive).

    Salience is not clamped by the model (``SalienceService.update`` can return
    more than 1.0), so the top bucket is left open and both tails still bucket to
    exactly one index; the bucket counts therefore always sum to the sample count.
    """
    value = float(value)
    index = 0
    for edge in SALIENCE_BUCKET_EDGES[1:]:
        if value < edge:
            return index
        index += 1
    return len(SALIENCE_BUCKETS) - 1


def _quantile(ordered: list[float], fraction: float) -> float:
    """Linear interpolation between order statistics (``percentile_cont``)."""
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower_index = int(position // 1)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    weight = position - lower_index
    return ordered[lower_index] * (1.0 - weight) + ordered[upper_index] * weight


def salience_summary(values) -> dict:
    """``{p50, p90, p95, buckets}`` for a salience sample.

    An empty sample yields ``None`` quantiles and all-zero buckets: the honest
    representation of "no data", not a rate and not a fabricated zero.
    """
    ordered = sorted(float(value) for value in values)
    counts = [0] * len(SALIENCE_BUCKETS)
    for value in ordered:
        counts[bucket_index(value)] += 1
    summary = {
        name: (_quantile(ordered, fraction) if ordered else None)
        for name, fraction in SALIENCE_FRACTIONS
    }
    summary["buckets"] = [
        {"lower": lower, "upper": upper, "count": count}
        for (lower, upper), count in zip(SALIENCE_BUCKETS, counts, strict=True)
    ]
    return summary


def distribution(counts: dict, vocabulary: tuple[str, ...]) -> dict[str, int]:
    """The sealed vocabulary with real observed counts, so every key always exists."""
    return {name: int(counts.get(name, 0)) for name in vocabulary}


def aggregate_entry_rows(rows) -> dict:
    """Aggregate already-projected entry rows into the contract's numeric block.

    Only ``kind``/``provenance``/``status``/``salience`` are ever read, and only
    the fixed vocabularies are ever written, so no body text can survive even if a
    caller hands in raw ``memory_entries``-shaped dictionaries.
    """
    rows = list(rows)
    observed: dict[str, dict[str, int]] = {column: {} for column in _VOCABULARY_COLUMNS}
    salience: list[float] = []
    for row in rows:
        for column in _VOCABULARY_COLUMNS:
            value = row.get(column)
            observed[column][value] = observed[column].get(value, 0) + 1
        value = row.get("salience")
        salience.append(float(value) if value is not None else 0.0)

    distributions: dict[str, dict[str, int]] = {}
    for column in _VOCABULARY_COLUMNS:
        vocabulary = _VOCABULARIES[column]
        output = {name: observed[column].get(name, 0) for name in vocabulary}
        # A value outside the sealed vocabulary is reported as its own count
        # instead of being silently folded into a known bucket.
        extra = sum(count for name, count in observed[column].items() if name not in output)
        if extra:
            output["other"] = extra
        distributions[column] = output

    summary = salience_summary(salience)
    return {
        "total": len(rows),
        "kind_distribution": distributions["kind"],
        "provenance_distribution": distributions["provenance"],
        "status_distribution": distributions["status"],
        "p50": summary["p50"],
        "p90": summary["p90"],
        "p95": summary["p95"],
        "buckets": summary["buckets"],
    }


def _entries_lateral():
    """The manifest's entries expanded one row per memory (no body columns)."""
    return func.jsonb_each(MemoryProjectionMeta.payload["state"]["entries"]) \
        .table_valued("key", "value").lateral()


def _manifest_conditions(scope_id: int):
    """The completed-manifest predicate ``GET /api/memories`` uses (api/memory.py:285)."""
    return (MemoryProjectionMeta.knowledge_scope_id == scope_id,
            MemoryProjectionMeta.projection_type == "manifest",
            MemoryProjectionMeta.status == "complete",
            MemoryProjectionMeta.payload["verification_version"].as_integer() == 1)


async def _entry_projection(session: AsyncSession, scope_id: int):
    """Count, classify and quantile the completed manifest of ``scope_id`` in SQL."""
    entries = _entries_lateral()
    data = cast(entries.c.value, JSONB)
    salience = cast(func.jsonb_extract_path_text(data, "salience"), Float)
    statement = select(
        func.count(),
        *(func.count().filter(func.jsonb_extract_path_text(data, column) == name).label(f"{column}_{name}")
          for column in _VOCABULARY_COLUMNS for name in _VOCABULARIES[column]),
        *(func.percentile_cont(fraction).within_group(salience.asc()).label(name)
          for name, fraction in SALIENCE_FRACTIONS),
    ).select_from(MemoryProjectionMeta).join(entries, true()).where(*_manifest_conditions(scope_id))
    return (await session.execute(statement)).one()


def _projection_blocks(row) -> tuple[int, dict]:
    """Split the projection tuple into the total and the fixed numeric vocabularies."""
    total = int(row[0] or 0)
    offset = 1
    distributions: dict[str, dict[str, int]] = {}
    for column in _VOCABULARY_COLUMNS:
        distributions[column] = {name: int(row[offset + index] or 0)
                                 for index, name in enumerate(_VOCABULARIES[column])}
        offset += len(_VOCABULARIES[column])
    quantiles = {name: (None if row[offset + index] is None else float(row[offset + index]))
                 for index, (name, _fraction) in enumerate(SALIENCE_FRACTIONS)}
    return total, {"distributions": distributions, "quantiles": quantiles}


async def _salience_values(session: AsyncSession, scope_id: int) -> list[float]:
    """Measured salience of the completed manifest's entries, column-only SQL.

    The subquery restricts ``memory_salience`` to the entries the completed
    manifest reports, so the quantile sample and ``total`` describe one caliber.
    Only ``memory_id`` and ``salience`` are selected -- never ``MemoryEntry``'s
    free-text columns.
    """
    entries = _entries_lateral()
    manifest_rows = select(cast(entries.c.key, BigInteger).label("memory_id")) \
        .select_from(MemoryProjectionMeta).join(entries, true()).where(*_manifest_conditions(scope_id))
    values = (await session.execute(
        select(MemorySalience.salience)
        .where(MemorySalience.memory_id.in_(manifest_rows)))).scalars().all()
    return [float(value) for value in values if value is not None]


async def domain_statistics(session: AsyncSession, scope_id: int) -> dict:
    """Aggregate one domain into the ten contract keys.

    ``scope_id`` is the already-resolved identity (the endpoint resolves
    ``scope_ref`` through the shared ``MemoryScopeResolver``), so this function
    performs no address resolution of its own.
    """
    scope = await session.get(KnowledgeScope, scope_id)
    domain_key = (scope.domain_key if scope is not None else None) or ""
    total, blocks = _projection_blocks(await _entry_projection(session, scope_id))

    salience_values = await _salience_values(session, scope_id)
    if salience_values:
        summary = salience_summary(salience_values)
        quantiles = {name: summary[name] for name, _fraction in SALIENCE_FRACTIONS}
        buckets = summary["buckets"]
    else:
        # Zero denominator: real zero counts and unmatched quantiles, never 100 %.
        quantiles = {name: None for name, _fraction in SALIENCE_FRACTIONS}
        buckets = [{"lower": lower, "upper": upper, "count": 0}
                   for lower, upper in SALIENCE_BUCKETS]

    rollback_count = await session.scalar(
        select(func.count()).select_from(MemoryEvent).where(
            MemoryEvent.knowledge_scope_id == scope_id, MemoryEvent.event_type == "rollback"))
    consolidation_run_count = await session.scalar(
        select(func.count(func.distinct(ConsolidationRunObservation.run_id))).where(
            ConsolidationRunObservation.knowledge_scope_id == scope_id))

    return {
        "scope_id": str(scope_id),
        "domain_key": domain_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "kind_distribution": blocks["distributions"]["kind"],
        "provenance_distribution": blocks["distributions"]["provenance"],
        "status_distribution": blocks["distributions"]["status"],
        "salience_distribution": {
            "p50": quantiles["p50"],
            "p90": quantiles["p90"],
            "p95": quantiles["p95"],
            "buckets": buckets,
        },
        "consolidation_run_count": int(consolidation_run_count or 0),
        "rollback_count": int(rollback_count or 0),
    }
