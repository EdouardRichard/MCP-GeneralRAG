import json

import pytest

from rag_mcp.mcp.serialization import memory_error
from rag_mcp.services.scope_binding_service import ScopeBindingError, ScopeBindingService


@pytest.mark.parametrize("code,candidates", [("MISSING_KNOWLEDGE_SCOPE", []), ("AMBIGUOUS_DOMAIN_REF", [7, 9])])
def test_scope_refusal_is_dual_channel_and_preserves_candidate_identity(code, candidates):
    result = memory_error(ScopeBindingError(code, candidates))
    assert result.isError
    assert json.loads(result.content[0].text) == result.structuredContent
    assert result.structuredContent["error"]["code"] == code
    assert result.structuredContent["request_id"]
    if candidates:
        assert result.structuredContent["error"]["candidates"] == candidates
    else:
        assert "candidates" not in result.structuredContent["error"]


@pytest.mark.parametrize("reference", ["path:relative/file", "path:https://example.org:invalid/repo", "path:ssh://["])
def test_path_and_remote_failures_have_the_same_explicit_scope_contract(reference):
    with pytest.raises(ScopeBindingError) as failure:
        ScopeBindingService([]).resolve(reference)
    result = memory_error(failure.value)
    assert result.isError and result.structuredContent["error"]["code"] == "MISSING_KNOWLEDGE_SCOPE"
