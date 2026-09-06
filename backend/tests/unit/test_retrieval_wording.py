"""Wording unit test for domain-neutralized gaps/error copy (009, T022).

FR-015/FR-016/SC-007/SC-008: the domain-generalized gaps suggested_action and the
get_evidence SCOPE_MISMATCH copy are domain-neutral (zero "project" residual as
the generalized knowledge-domain concept), while the project_scope-only legacy
error codes and messages stay byte-identical.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_gaps_suggested_action_is_domain_neutral():
    from rag_mcp.services.retrieval_service import RetrievalService

    gaps = RetrievalService._infer_gaps([], requested_top_k=5)
    assert len(gaps) == 1
    action = gaps[0]["suggested_action"]
    assert "knowledge domain scope" in action
    assert "project scope" not in action


def test_scope_mismatch_wording_is_domain_neutral():
    src = _REPO_ROOT / "backend" / "src" / "rag_mcp" / "services" / "evidence_service.py"
    text = src.read_text(encoding="utf-8")
    assert "requested project scopes" not in text
    assert "requested knowledge domains" in text
    assert "the correct domain" in text


def test_legacy_project_scope_error_copy_unchanged():
    src = _REPO_ROOT / "backend" / "src" / "rag_mcp" / "services" / "retrieval_service.py"
    text = src.read_text(encoding="utf-8")
    # FR-016: legacy project_scope-only error codes + messages stay byte-identical.
    assert "MISSING_PROJECT_SCOPE" in text
    assert "AMBIGUOUS_PROJECT_REF" in text
    assert "No valid project scopes could be resolved." in text
