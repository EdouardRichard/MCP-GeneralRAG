import pytest

from tests.integration.test_012_persisted_write_loop import published_payload
from rag_mcp.services.memory_validators import MemoryProvenanceValidator


@pytest.mark.asyncio
async def test_published_evidence_fixture_isolates_each_real_write_trajectory(db_session):
    first = await published_payload(db_session)
    second = await published_payload(db_session)
    assert first["scope_id"] != second["scope_id"], "repeated acceptance runs accumulate memory in the historical evaluation scope"
    assert first["evidence_refs"] != second["evidence_refs"]
    for payload in (first, second):
        checked = await MemoryProvenanceValidator(db_session).validate(payload)
        assert checked["validated"] and checked["attributions"]
