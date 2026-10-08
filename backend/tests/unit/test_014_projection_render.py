"""T040/T046 — consumption-layer rendering and read-only guard (US6).

Pure file-system + pure-function assertions: no database, no vectors. These are
the assertions that must go green in an environment without PostgreSQL, and the
read-only/guard assertions land in the same batch as the materialiser (user
discipline) rather than after it.

Contract: ``specs/014-memory-aware-retrieval/contracts/memory-consumption-projection.md``
§2 (paths), §3 (byte rules), §4 (asymmetric read-only guard).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from rag_mcp.runtime import memory_projection as projection
from rag_mcp.services.memory_reducer import reduce_events

SLUG = "orders-domain"

#: The ten contract keys, in the frozen order (contract §3).
FRONTMATTER_KEYS = [
    "memory_id",
    "kind",
    "provenance",
    "confidence",
    "valid_from",
    "valid_to",
    "session_id",
    "evidence_refs",
    "status",
    "superseded_by",
    "untrusted",
]


def _event(event_id: int, scope_id: int, kind: str, content: str, **extra) -> dict:
    payload = {
        "kind": kind,
        "content_text": content,
        "content_hash": "0" * 64,
        "provenance": extra.pop("provenance", "soft"),
        "inference_meta": {
            "source": "unit fixture",
            "confidence": 0.8,
            "model_version": "fixture-v1",
            "time": "2026-01-01T00:00:00+00:00",
            "supporting_evidence": [],
        },
        **extra,
    }
    return {
        "event_id": event_id,
        "knowledge_scope_id": scope_id,
        "aggregate_id": event_id,
        "event_type": "assert",
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "payload": payload,
    }


CONTENT_ZH = "客户要求：发票抬头必须与合同主体一致。\n时间 2026-01-02，负责人 张三。"
CONTENT_MULTILINE = "line one\nline two\n\nline four"


@pytest.fixture
def state():
    """A sealed reducer state with distinct kinds, statuses and shapes."""
    return reduce_events(
        [
            _event(1, 42, "episodic", CONTENT_ZH, session_id="s-1", evidence_refs=["chunk:9", "chunk:2"]),
            _event(2, 42, "semantic", CONTENT_MULTILINE, evidence_refs=["chunk:1"]),
            _event(3, 42, "procedural", "always confirm the invoice header", provenance="hard",
                   evidence_refs=["chunk:7"]),
        ]
    )


@pytest.fixture
def scoped_state():
    """State including quarantined / archived rows that must not be published."""
    return reduce_events(
        [
            _event(1, 42, "episodic", "active note"),
            _event(2, 42, "episodic", "quarantined note", status="quarantined"),
            _event(3, 42, "episodic", "retired note"),
            {
                "event_id": 4,
                "knowledge_scope_id": 42,
                "aggregate_id": 3,
                "event_type": "retract",
                "occurred_at": "2026-01-03T00:00:00+00:00",
                "payload": {},
            },
        ]
    )


# --------------------------------------------------------------------------
# §3 byte rules — frozen key order, raw body, LF only, exactly one final LF
# --------------------------------------------------------------------------

def test_frontmatter_key_order_is_the_frozen_contract_order(state):
    text = projection.render_memory_file(state["entries"][1], slug=SLUG)
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    keys = [line.split(":", 1)[0] for line in block.splitlines() if line and not line.startswith(" ")]
    assert keys == FRONTMATTER_KEYS


def test_untrusted_marker_is_always_present_and_true(state):
    for row in state["entries"].values():
        text = projection.render_memory_file(row, slug=SLUG)
        assert "\nuntrusted: true\n" in text


def test_body_is_the_raw_content_text_without_rewriting(state):
    text = projection.render_memory_file(state["entries"][1], slug=SLUG)
    body = text.split("---\n", 2)[2]
    assert body == CONTENT_ZH + "\n"
    assert "untrusted" not in body
    assert "不建议" not in body


def test_multiline_body_keeps_lf_and_exactly_one_trailing_newline(state):
    text = projection.render_memory_file(state["entries"][2], slug=SLUG)
    assert "\r\n" not in text
    body = text.split("---\n", 2)[2]
    assert body == CONTENT_MULTILINE + "\n"
    assert not body.endswith("\n\n")


def test_bytes_are_utf8_without_bom(state):
    payload = projection.render_memory_file(state["entries"][1], slug=SLUG).encode("utf-8")
    assert b"\xef\xbb\xbf" not in payload
    assert payload.endswith(b"\n")


def test_repeated_rendering_is_byte_identical(state):
    first = projection.render_memory_file(state["entries"][1], slug=SLUG)
    second = projection.render_memory_file(state["entries"][1], slug=SLUG)
    assert first == second


def test_confidence_is_null_or_shortest_decimal_never_nan(state):
    null_row = state["entries"][3]  # hard: confidence must never be fabricated
    assert "confidence: null" in projection.render_memory_file(null_row, slug=SLUG)
    soft = projection.render_memory_file(state["entries"][2], slug=SLUG)
    assert "confidence:" in soft
    assert "NaN" not in soft and "Infinity" not in soft


def test_no_generation_time_or_clock_field_enters_the_file(state, monkeypatch):
    text = projection.render_memory_file(state["entries"][2], slug=SLUG)
    lines = [line.split(":", 1)[0] for line in text.splitlines() if ":" in line]
    for forbidden in ("generated_at", "refreshed_at", "updated_at", "mtime", "pid", "inode"):
        assert forbidden not in lines


def test_scope_slug_is_normalised_by_ascii_lowercase_only():
    assert projection.normalise_scope_slug("Orders-Domain") == "orders-domain"
    with pytest.raises(ValueError):
        projection.normalise_scope_slug("Orders Domain")
    with pytest.raises(ValueError):
        projection.normalise_scope_slug("../escape")
    with pytest.raises(ValueError):
        projection.normalise_scope_slug("")


# --------------------------------------------------------------------------
# §2 paths and §3 exclusion rules
# --------------------------------------------------------------------------

def test_excluded_statuses_and_retention_stages_produce_no_file(scoped_state):
    files = projection.render_tree(scoped_state, slug=SLUG)
    paths = {relative for _, relative, _ in files}
    assert paths == {"episodic/1.md", "DIGEST.md", "INDEX.md"}
    body = next(text for _, relative, text in files if relative == "episodic/1.md")
    assert "retired note" not in body and "quarantined note" not in body


def test_tree_paths_are_sorted_by_kind_then_memory_id(state):
    files = projection.render_tree(state, slug=SLUG)
    relative = [relative for _, relative, _ in files]
    assert relative == [
        "DIGEST.md",
        "INDEX.md",
        "episodic/1.md",
        "procedural/3.md",
        "semantic/2.md",
    ]


def test_digest_has_fixed_keys_and_an_explicit_empty_consolidation_state(state):
    files = dict((relative, text) for _, relative, text in projection.render_tree(state, slug=SLUG))
    digest = files["DIGEST.md"]
    head = digest.split("sections:", 1)[0]
    keys = [line.split(":", 1)[0] for line in head.splitlines()
            if line and not line.startswith((" ", "-", ">", "#"))]
    assert keys == ["scope_slug", "source_event_id", "counts"]
    assert "sections:" in digest
    assert "included: false" in digest  # consolidation has not run: honest empty state
    assert digest.endswith("\n") and "\r\n" not in digest


def test_index_groups_by_kind_and_lists_memory_ids_ascending(state):
    """Contract §3 group order is episodic -> semantic -> procedural."""
    files = dict((relative, text) for _, relative, text in projection.render_tree(state, slug=SLUG))
    index = files["INDEX.md"]
    assert index.index("## episodic") < index.index("## semantic") < index.index("## procedural")
    assert index.index("episodic/1.md") < index.index("semantic/2.md") < index.index("procedural/3.md")


def test_digest_and_index_headers_carry_the_untrusted_declaration(state):
    files = dict((relative, text) for _, relative, text in projection.render_tree(state, slug=SLUG))
    for name in ("DIGEST.md", "INDEX.md"):
        header = files[name]
        assert "untrusted" in header
        assert "不可信" in header or "untrusted data" in header


def test_tree_fingerprint_is_sha256_over_canonical_relative_path_to_bytes_hash(state):
    files = projection.render_tree(state, slug=SLUG)
    fingerprint = projection.tree_fingerprint(files)
    assert len(fingerprint) == 64 and set(fingerprint) <= set("0123456789abcdef")
    assert fingerprint == projection.tree_fingerprint(projection.render_tree(state, slug=SLUG))
    reduced = [item for item in files if item[1] != "episodic/1.md"]
    assert projection.tree_fingerprint(reduced) != fingerprint


def test_an_empty_state_is_a_rebuildable_explicit_empty_tree(state):
    files = projection.render_tree(reduce_events([]), slug=SLUG)
    assert [relative for _, relative, _ in files] == ["DIGEST.md", "INDEX.md"]


def test_render_tree_requires_a_sealed_reducer_state(state):
    with pytest.raises(TypeError):
        projection.render_tree({"entries": {}}, slug=SLUG)


# --------------------------------------------------------------------------
# §4 normative guard — path confinement (no public write API, AST in T041)
# --------------------------------------------------------------------------

def test_file_relative_path_rejects_non_positive_or_non_decimal_ids():
    for bad in (0, -1, "1/../../escape", "1.md", True, None, 1.5):
        with pytest.raises(ValueError):
            projection.file_relative_path(bad, "episodic")


def test_file_relative_path_rejects_unknown_kind():
    with pytest.raises(ValueError):
        projection.file_relative_path(1, "notes")


def test_guard_write_refuses_a_target_outside_the_consumption_root(tmp_path, state):
    root = (tmp_path / "consumption").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("untouched", encoding="utf-8")

    guard = projection.ConsumptionGuard(root)
    outside_file = (outside / "escape.md").resolve()
    with pytest.raises(projection.ProjectionPathError):
        guard.write_file(outside_file, "escape")
    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "untouched"
    assert not (outside / "escape.md").exists()

    sibling = (tmp_path / "consumption-sibling").resolve()
    with pytest.raises(projection.ProjectionPathError):
        guard.write_file((sibling / "escape.md").resolve(), "escape")
    assert not sibling.exists()

    with pytest.raises(projection.ProjectionPathError):
        guard.write_file(root, "escape")

    ok = guard.write_file(root / SLUG / "episodic" / "1.md", "kept\n")
    assert ok.read_text(encoding="utf-8") == "kept\n"


def test_materialize_into_a_pre_existing_directory_clears_stale_entries(tmp_path, state):
    root = (tmp_path / "consumption").resolve()
    stale = (root / SLUG / "semantic" / "999.md")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale content", encoding="utf-8")

    files = projection.render_tree(state, slug=SLUG)
    guard = projection.ConsumptionGuard(root)
    written = guard.write_tree(root / SLUG, files)

    assert not stale.exists()
    assert sorted(path.name for path in (root / SLUG / "semantic").glob("*.md")) == ["2.md"]
    assert written


# --------------------------------------------------------------------------
# §4 defence in depth + capability boundary: files 0o444, directories 0755
# --------------------------------------------------------------------------

class _FakeSource:
    """A tree source whose only capability is the verified reducer state."""

    def __init__(self, state, event_id, slug=SLUG):
        self._state, self._event_id, self._slug = state, event_id, slug

    async def state(self, scope_id):
        from rag_mcp.runtime.memory_projection import TreeState

        return TreeState(scope_id=scope_id, state=self._state, source_event_id=self._event_id,
                         scope_slug=self._slug)


@pytest.mark.asyncio
async def test_refresh_locks_files_readonly_when_the_guard_is_enabled(tmp_path, state, monkeypatch):
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))

    report = await consumer.apply_tree(42, session=None)
    assert report.status == "complete"
    assert report.tree_fingerprint == projection.tree_fingerprint(projection.render_tree(state, slug=SLUG))

    published = root / SLUG / "episodic" / "1.md"
    assert published.is_file()
    assert st_has_no_write_bit(published)
    assert published.read_text(encoding="utf-8").split("---\n", 2)[2] == CONTENT_ZH + "\n"


@pytest.mark.asyncio
async def test_lock_does_not_stop_an_os_level_rewrite_but_application_guard_does(tmp_path, state, monkeypatch):
    """Capability boundary: OS bits are a tripwire, never a security boundary."""
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))
    await consumer.apply_tree(42, session=None)

    published = root / SLUG / "episodic" / "1.md"
    with pytest.raises(PermissionError):
        published.write_text("host wrote this", encoding="utf-8", newline="\n")
    assert published.read_text(encoding="utf-8").split("---\n", 2)[2] == CONTENT_ZH + "\n"

    # The owner can always clear the bit and write — the OS layer is bypassable,
    # which is exactly why the normative guard is the application layer.
    projection._clear_readonly(published)
    published.write_text("host wrote this", encoding="utf-8", newline="\n")
    assert published.read_text(encoding="utf-8") == "host wrote this"


@pytest.mark.asyncio
async def test_directories_stay_0755_after_refresh(tmp_path, state, monkeypatch):
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))
    await consumer.apply_tree(42, session=None)

    for directory in (root / SLUG, root / SLUG / "episodic", root / SLUG / "semantic",
                      root / SLUG / "procedural"):
        assert directory.is_dir()
        assert directory.stat().st_mode & stat.S_IWUSR, f"{directory} must stay writable (0755)"
        assert directory.stat().st_mode & stat.S_IXUSR


@pytest.mark.asyncio
async def test_rebuild_clears_the_bits_first_and_succeeds(tmp_path, state, monkeypatch):
    """Windows reality: a re-render over read-only files must clear bits first."""
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))
    await consumer.apply_tree(42, session=None)
    assert st_has_no_write_bit(root / SLUG / "episodic" / "1.md")

    changed = reduce_events([
        _event(1, 42, "episodic", CONTENT_ZH, session_id="s-1"),
        _event(2, 42, "semantic", CONTENT_MULTILINE),
        _event(3, 42, "procedural", "always confirm the invoice header", provenance="hard"),
        _event(4, 42, "episodic", "second thought"),
    ])
    consumer.source = _FakeSource(changed, 4)
    report = await consumer.apply_tree(42, session=None)

    assert report.status == "complete"
    published = root / SLUG / "episodic" / "4.md"
    assert published.is_file()
    assert st_has_no_write_bit(published)


@pytest.mark.asyncio
async def test_guard_disabled_leaves_files_writable(tmp_path, state, monkeypatch):
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: False)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))
    report = await consumer.apply_tree(42, session=None)

    published = root / SLUG / "episodic" / "1.md"
    assert report.guard_state == "writable"
    assert published.stat().st_mode & stat.S_IWUSR


# --------------------------------------------------------------------------
# §5 drift detection — bytes only, never repaired on a read path
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_disk_manifest_matches_the_rendered_tree(tmp_path, state, monkeypatch):
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    guard = projection.ConsumptionGuard(root)
    guard.write_tree(root / SLUG, projection.render_tree(state, slug=SLUG))

    expected = projection.tree_manifest(projection.render_tree(state, slug=SLUG))
    actual = guard.manifest(root / SLUG)
    assert actual == expected


@pytest.mark.asyncio
async def test_apply_tree_reports_drift_and_repairs_the_scope_subtree(tmp_path, state, monkeypatch):
    root = (tmp_path / "consumption").resolve()
    monkeypatch.setattr(projection, "_enabled", lambda: True)
    consumer = projection.MemoryProjectionConsumer(root=root, source=_FakeSource(state, 3))
    await consumer.apply_tree(42, session=None)

    projection._clear_readonly(root / SLUG / "episodic" / "1.md")
    (root / SLUG / "episodic" / "1.md").write_text("tampered", encoding="utf-8", newline="\n")
    (root / SLUG / "unexpected.md").write_text("drift", encoding="utf-8", newline="\n")

    report = await consumer.apply_tree(42, session=None)
    assert report.repaired is True
    assert "unexpected.md" in report.unexpected_paths
    assert (root / SLUG / "episodic" / "1.md").read_text(encoding="utf-8").split("---\n", 2)[2] == CONTENT_ZH + "\n"
    assert not (root / SLUG / "unexpected.md").exists()


def st_has_no_write_bit(path: Path) -> bool:
    """True when a host write to this file is refused (POSIX 0o444 / S_IREAD)."""
    return not (path.stat().st_mode & stat.S_IWUSR)


def test_platform_reality_note():
    """Document the measured asymmetry this guard is designed around."""
    probe = Path(os.environ.get("TEMP", ".")) / "dsh-014-probe"
    probe.mkdir(parents=True, exist_ok=True)
    os.chmod(probe, 0o555)
    try:
        created = probe / "created-anyway.txt"
        created.write_text("windows ignores the directory read-only bit", encoding="utf-8")
        created.unlink()
        directory_bits_are_advisory = True
    finally:
        os.chmod(probe, 0o755)
        try:
            os.rmdir(probe)
        except OSError:
            pass
    if os.name == "nt":
        assert directory_bits_are_advisory, "measured: chmod(dir, 0o555) does not stop writes on Windows"
