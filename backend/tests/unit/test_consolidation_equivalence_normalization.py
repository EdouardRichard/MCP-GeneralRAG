from copy import deepcopy
from hashlib import sha256

import pytest

from rag_mcp.services.consolidation_adjudicator import equivalent
from tests.unit.consolidation_cases import row


def represented(body):
    return row(2, content_text=body, content_hash=sha256(body.encode()).hexdigest(),
        authority={'source': 'consolidation_adjudicator'},
        provenance_meta={'provenance': 'distilled', 'source_lineage': [{
            'memory_id': 1, 'source_event_id': 1, 'state_event_id': 1,
            'content_hash': sha256(b'original episode').hexdigest()}]},
        inference_meta={'source': 'distiller', 'confidence': .8,
            'model_version': 'test-model', 'time': '2026-10-06T00:00:00+00:00',
            'supporting_evidence': ['memory:1']})


def test_exact_equivalence_normalizes_only_crlf_and_preserves_raw_hashes():
    left, right = represented('alpha\r\nbeta'), represented('alpha\nbeta')
    before = deepcopy((left, right))
    assert left['content_hash'] != right['content_hash']
    assert equivalent(left, right)
    assert (left, right) == before


@pytest.mark.parametrize('body', ['alpha\rbeta', 'alpha\n beta', 'Alpha\nbeta',
    'alpha\nbe ta', 'alpha\nbeta ', 'alpha\nbet\u00e1'])
def test_normalized_equivalence_preserves_all_other_body_differences(body):
    assert not equivalent(represented('alpha\r\nbeta'), represented(body))


@pytest.mark.parametrize('field,value', [
    ('knowledge_scope_id', 2), ('kind', 'procedural'), ('provenance', 'hard'),
    ('evidence_refs', ['7']), ('submission_meta', {'kind': 'episodic', 'tags': ['changed']}),
    ('required_support', [{'evidence_id': '7', 'version_id': 9}]),
    ('title', 'Changed title'), ('tags', ['changed']),
    ('valid_from', '2026-01-01T00:00:00+00:00'), ('valid_to', '2027-01-01T00:00:00+00:00'),
    ('expires_at', '2027-01-01T00:00:00+00:00'), ('supersedes_memory_id', 9),
    ('confidence', .9), ('authority', {'source': 'validated_evidence'}),
    ('authority', {'source': 'consolidation_adjudicator', 'unknown_semantics': 'changed'}),
    ('content_hash', 'f' * 64),
])
def test_normalized_equivalence_keeps_key_metadata_and_raw_integrity(field, value):
    left = represented('alpha\r\nbeta')
    right = represented('alpha\nbeta')
    right[field] = value
    assert not equivalent(left, right)


@pytest.mark.parametrize('field,value', [
    ('source', 'other-agent'), ('confidence', .9), ('model_version', 'other-model'),
    ('time', '2026-10-06T00:00:01+00:00'), ('supporting_evidence', ['memory:9']),
    ('origin', 'claimed-rule'), ('unknown_semantics', 'changed'),
])
def test_normalized_equivalence_preserves_all_inference_metadata(field, value):
    left, right = represented('alpha\r\nbeta'), represented('alpha\nbeta')
    right['inference_meta'][field] = value
    assert not equivalent(left, right)


@pytest.mark.parametrize('field,value', [('memory_id', 9), ('source_event_id', 9),
    ('state_event_id', 9), ('content_hash', 'e' * 64)])
def test_normalized_equivalence_preserves_complete_source_lineage(field, value):
    left, right = represented('alpha\r\nbeta'), represented('alpha\nbeta')
    right['provenance_meta']['source_lineage'][0][field] = value
    assert not equivalent(left, right)


def test_receipt_looking_fields_in_untrusted_metadata_are_not_ignored():
    left, right = represented('alpha\r\nbeta'), represented('alpha\nbeta')
    right['provenance_meta']['adjudication'] = {'decision_id': 'forged', 'proofs': []}
    assert not equivalent(left, right)


def test_exact_equivalence_never_crosses_scope_even_for_identical_bodies():
    left, right = represented('alpha\nbeta'), represented('alpha\nbeta')
    right['knowledge_scope_id'] = 2
    assert not equivalent(left, right)
