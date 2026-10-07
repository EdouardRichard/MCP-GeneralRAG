"""Constant-time request-activity accounting and bounded cross-process signals (013 T082/T084).

Automatic (idle/volume) consolidation admission must prove that no real
foreground, ingestion or rebuild work is in flight. Within one process that is
an O(1) counter update; across processes (management vs. MCP writer/reader —
separate entry points, separate memory) it is a bounded published snapshot in
``runtime_activity_signals`` (migration 0104).

Failures are conservative: a missing or stale peer observation never reads as
"idle", it reports ``activity_observation_stale`` and the automatic attempt is
skipped with a reason. Passive traffic (SSE streams, health/liveness, static
assets) is explicitly *not* foreground work.
"""

from __future__ import annotations

import inspect
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

ACTIVITY_KINDS = ('foreground', 'ingestion', 'rebuild')

#: Explicit definition of foreground work for the management HTTP surface:
#: only API/MCP dispatch counts; SSE, health, metrics, docs and static assets
#: are passive for automatic-admission purposes.
PASSIVE_HTTP_PATHS = ('/health', '/api/events', '/runtime/metrics', '/openapi.json', '/docs', '/redoc')

PUBLISH_INTERVAL_SECONDS = 5.0
STALE_AFTER_SECONDS = 30.0

REASON_FOREGROUND_ACTIVE = 'foreground_activity'
REASON_INGESTION_ACTIVE = 'ingestion_activity'
REASON_REBUILD_ACTIVE = 'rebuild_activity'
REASON_STALE = 'activity_observation_stale'
REASON_IDLE_INSUFFICIENT = 'idle_seconds_insufficient'


@dataclass(frozen=True)
class ActivitySnapshot:
    """One process's current activity (monotonic clock, never wall clock)."""

    foreground_active: int
    last_foreground_at: float | None
    ingestion_active: int
    rebuild_active: int


@dataclass(frozen=True)
class ProcessActivity:
    """A published peer snapshot; ``stale`` means it cannot prove idleness."""

    instance_id: UUID
    process_role: str
    instance_mode: str
    foreground_active: int
    last_foreground_at: datetime | None
    ingestion_active: bool
    rebuild_active: bool
    volume_hint_scope_ids: tuple[int, ...]
    volume_hint_published_at: datetime | None
    published_at: datetime
    stale: bool


class RuntimeActivity:
    """Process-local, constant-time activity counters and offline volume hints."""

    def __init__(self, *, monotonic=None):
        self._monotonic = monotonic or time.monotonic
        self._started_at = self._monotonic()
        self._counts = dict.fromkeys(ACTIVITY_KINDS, 0)
        self._last_foreground_at = None
        self._hints: set[int] = set()

    def begin(self, kind: str = 'foreground') -> None:
        if kind not in ACTIVITY_KINDS:
            raise ValueError('invalid activity kind')
        self._counts[kind] += 1
        if kind == 'foreground':
            self._last_foreground_at = self._monotonic()

    def end(self, kind: str = 'foreground') -> None:
        if kind not in ACTIVITY_KINDS:
            raise ValueError('invalid activity kind')
        self._counts[kind] = max(0, self._counts[kind] - 1)
        if kind == 'foreground':
            self._last_foreground_at = self._monotonic()

    @contextmanager
    def track(self, kind: str = 'foreground'):
        """Release on success, exception and cancellation alike."""
        self.begin(kind)
        try:
            yield
        finally:
            self.end(kind)

    def snapshot(self) -> ActivitySnapshot:
        return ActivitySnapshot(self._counts['foreground'], self._last_foreground_at,
                                self._counts['ingestion'], self._counts['rebuild'])

    def idle_seconds(self, *, now: float | None = None) -> float:
        """Seconds since the last foreground activity (or tracker start)."""
        reference = self._monotonic() if now is None else now
        return max(0.0, reference - (self._last_foreground_at or self._started_at))

    def reset(self) -> None:
        for kind in ACTIVITY_KINDS:
            self._counts[kind] = 0
        self._last_foreground_at = None
        self._started_at = self._monotonic()
        self._hints.clear()


_ACTIVITY: RuntimeActivity | None = None
_IDENTITY: tuple[UUID, str, str] | None = None
_IDENTITY_LOCK = threading.Lock()
_PEER_HINT_CURSOR: dict[UUID, datetime] = {}


def get_runtime_activity() -> RuntimeActivity:
    """The process-wide activity tracker (management, writer MCP and reader MCP)."""
    global _ACTIVITY
    if _ACTIVITY is None:
        _ACTIVITY = RuntimeActivity()
    return _ACTIVITY


def mark_volume_hint(scope_id: int) -> None:
    """O(1) offline nudge after one successful ordinary memory write (T083).

    A hint is a *check now* nudge, never a durable trigger: the maintenance tick
    re-verifies the real pending count and every idle condition, and any
    rejection discards it.
    """
    if isinstance(scope_id, bool) or not isinstance(scope_id, int) or scope_id <= 0:
        return
    get_runtime_activity()._hints.add(scope_id)


def peek_volume_hints() -> tuple[int, ...]:
    return tuple(sorted(get_runtime_activity()._hints))


def drain_volume_hints() -> tuple[int, ...]:
    tracker = get_runtime_activity()
    hints = tuple(sorted(tracker._hints))
    tracker._hints.clear()
    return hints


def clear_volume_hint(scope_id: int) -> None:
    get_runtime_activity()._hints.discard(scope_id)


def process_identity() -> tuple[UUID, str, str]:
    """(instance_id, process_role, instance_mode) used when publishing activity."""
    global _IDENTITY
    if _IDENTITY is None:
        from rag_mcp.config import get_settings

        with _IDENTITY_LOCK:
            if _IDENTITY is None:
                mode = getattr(get_settings(), 'instance_mode', 'writer')
                _IDENTITY = (uuid4(), 'management' if mode == 'writer' else 'mcp', mode)
    return _IDENTITY


def set_process_identity(instance_id: UUID, *, process_role: str, instance_mode: str) -> tuple:
    """Entry points (management, writer/reader MCP) publish their real identity."""
    global _IDENTITY
    if process_role not in ('management', 'mcp') or instance_mode not in ('writer', 'reader'):
        raise ValueError('invalid process identity')
    with _IDENTITY_LOCK:
        _IDENTITY = (instance_id, process_role, instance_mode)
    return _IDENTITY


def is_passive_http_path(path: str) -> bool:
    """Foreground = real API/MCP work; streaming, liveness and assets are passive."""
    if path in PASSIVE_HTTP_PATHS or path.startswith('/assets/'):
        return True
    return not path.startswith(('/api/', '/mcp'))


def track_tool_calls(server) -> int:
    """Wrap every registered MCP tool so real dispatch is activity-visible.

    Applied to both writer and reader MCP entry points; the wrapper releases the
    count in a ``finally``, so failing or cancelled tool calls cannot pin the
    process permanently busy.
    """
    manager = getattr(server, '_tool_manager', None)
    tools = getattr(manager, '_tools', None) or {}
    tracker = get_runtime_activity()
    wrapped = 0
    for tool in tools.values():
        function = getattr(tool, 'fn', None)
        if function is None or getattr(function, '__consolidation_tracked__', False):
            continue

        async def wrapper(*args, __function=function, **kwargs):
            with tracker.track('foreground'):
                result = __function(*args, **kwargs)
                if inspect.isawaitable(result):
                    result = await result
                return result

        wrapper.__consolidation_tracked__ = True
        wrapper.__name__ = getattr(function, '__name__', 'mcp_tool')
        tool.fn = wrapper
        wrapped += 1
    return wrapped


async def publish_activity(session, *, identity=None, snapshot=None, volume_hints=None,
                           now=None) -> ProcessActivity:
    """Upsert this process's bounded activity snapshot (never a foreground write)."""
    from rag_mcp.models.runtime import RuntimeActivitySignal

    instance_id, process_role, instance_mode = identity or process_identity()
    snapshot = get_runtime_activity().snapshot() if snapshot is None else snapshot
    hints = peek_volume_hints() if volume_hints is None else tuple(sorted(set(volume_hints)))
    stamp = now or await session.scalar(text('SELECT clock_timestamp()'))
    idle = get_runtime_activity().idle_seconds()
    last_foreground = (stamp - timedelta(seconds=idle)) if (
        snapshot.last_foreground_at is not None or snapshot.foreground_active > 0) else None
    row = await session.get(RuntimeActivitySignal, instance_id, populate_existing=True)
    if row is None:
        row = RuntimeActivitySignal(instance_id=instance_id)
        session.add(row)
    row.process_role, row.instance_mode = process_role, instance_mode
    row.foreground_active = snapshot.foreground_active
    row.last_foreground_at = last_foreground
    row.ingestion_active = snapshot.ingestion_active > 0
    row.rebuild_active = snapshot.rebuild_active > 0
    row.volume_hint_scope_ids = list(hints)
    row.volume_hint_published_at = stamp if hints else None
    row.published_at = stamp
    row.state, row.released_at = 'active', None
    await session.flush()
    return ProcessActivity(instance_id, process_role, instance_mode, snapshot.foreground_active,
                           last_foreground, row.ingestion_active, row.rebuild_active, hints,
                           row.volume_hint_published_at, stamp, False)


async def release_activity(session, *, identity=None) -> None:
    from rag_mcp.models.runtime import RuntimeActivitySignal

    instance_id = (identity or process_identity())[0]
    row = await session.get(RuntimeActivitySignal, instance_id, populate_existing=True)
    if row is None:
        return
    row.state = 'released'
    row.released_at = await session.scalar(text('SELECT clock_timestamp()'))
    row.foreground_active, row.ingestion_active, row.rebuild_active = 0, False, False
    row.volume_hint_scope_ids, row.volume_hint_published_at = [], None
    await session.flush()


async def observe_peers(session, *, exclude_instance_id=None,
                        stale_after_s: float = STALE_AFTER_SECONDS) -> list[ProcessActivity]:
    """Read other processes' published activity; stale rows stay visible as stale.

    Only processes with a *live* instance registration are considered: a dead
    process cannot be doing foreground work, and its last snapshot must not pin
    automatic consolidation off forever.
    """
    from rag_mcp.models import InstanceRegistry
    from rag_mcp.models.runtime import RuntimeActivitySignal

    now = await session.scalar(text('SELECT clock_timestamp()'))
    statement = (select(RuntimeActivitySignal, InstanceRegistry.expires_at)
                 .join(InstanceRegistry, InstanceRegistry.instance_id == RuntimeActivitySignal.instance_id)
                 .where(RuntimeActivitySignal.state == 'active', InstanceRegistry.state == 'active',
                        InstanceRegistry.expires_at > now))
    if exclude_instance_id is not None:
        statement = statement.where(RuntimeActivitySignal.instance_id != exclude_instance_id)
    peers = []
    for signal, _expires in (await session.execute(statement)).all():
        peers.append(ProcessActivity(signal.instance_id, signal.process_role, signal.instance_mode,
                                     signal.foreground_active, signal.last_foreground_at,
                                     signal.ingestion_active, signal.rebuild_active,
                                     tuple(signal.volume_hint_scope_ids or ()),
                                     signal.volume_hint_published_at, signal.published_at,
                                     (now - signal.published_at).total_seconds() > stale_after_s))
    return peers


def collect_peer_volume_hints(peers) -> tuple[int, ...]:
    """Not-yet-evaluated peer hints (one bounded cursor per peer instance)."""
    fresh: list[int] = []
    for peer in peers:
        if not peer.volume_hint_scope_ids or peer.volume_hint_published_at is None:
            continue
        if _PEER_HINT_CURSOR.get(peer.instance_id) == peer.volume_hint_published_at:
            continue
        _PEER_HINT_CURSOR[peer.instance_id] = peer.volume_hint_published_at
        fresh.extend(peer.volume_hint_scope_ids)
    return tuple(sorted(set(fresh)))


def reset_peer_volume_cursor() -> None:
    _PEER_HINT_CURSOR.clear()


def admission_activity_reason(*, own: ActivitySnapshot, peers, now: float | None = None) -> str | None:
    """Reason code blocking automatic admission, or None when provably quiet."""
    if own.foreground_active > 0:
        return REASON_FOREGROUND_ACTIVE
    if own.ingestion_active > 0:
        return REASON_INGESTION_ACTIVE
    if own.rebuild_active > 0:
        return REASON_REBUILD_ACTIVE
    if any(getattr(peer, 'stale', False) for peer in peers):
        # A failed or stale observation is never read as "idle".
        return REASON_STALE
    if any(peer.foreground_active > 0 for peer in peers):
        return REASON_FOREGROUND_ACTIVE
    if any(peer.ingestion_active for peer in peers):
        return REASON_INGESTION_ACTIVE
    if any(peer.rebuild_active for peer in peers):
        return REASON_REBUILD_ACTIVE
    return None
