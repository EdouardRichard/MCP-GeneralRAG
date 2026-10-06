import os
from uuid import uuid4

from sqlalchemy.engine import make_url

from rag_mcp.config import get_settings
from rag_mcp.models.domain_profile import DomainProfile
from rag_mcp.models.knowledge_scope import KnowledgeScope
from rag_mcp.utils.snowflake import generate_id


async def create_scope(session, *, enabled=True):
    url = make_url(get_settings().database_url)
    isolated = os.environ.get('CONSOLIDATION_ISOLATED_DATABASE')
    assert isolated and url.database == isolated, '013 writes require the explicitly isolated database'
    key = '013-' + uuid4().hex
    session.add(DomainProfile(domain_key=key, name=key, supported_formats=['markdown'], graph_relations={},
                              default_capabilities={}, is_builtin=False,
                              memory_policy={'consolidation_enabled': enabled, 'consolidation': {}}))
    await session.flush()
    scope = KnowledgeScope(scope_id=generate_id(), scope_type='public', slug=key, name=key, domain_key=key)
    session.add(scope)
    await session.commit()
    return scope.scope_id


class StableEmbedding:
    """No model is needed to test real PG/Qdrant/file publication of window controls."""
    def get_dimension(self):
        return 1024

    async def embed_texts(self, texts):
        from hashlib import sha256
        import math
        vectors = [[(sha256(text.encode()).digest()[index % 32] + 1) / 256 for index in range(1024)] for text in texts]
        return [[value / math.sqrt(sum(item * item for item in vector)) for value in vector] for vector in vectors]


async def recorded_episode(service, scope_id, text, kind='episodic'):
    from datetime import datetime, timezone
    return await service.record({'scope_id': scope_id, 'kind': kind, 'content': text, 'provenance': 'soft',
        'inference_meta': {'source': '013 controlled fixture', 'confidence': .8, 'model_version': 'fixture-v1',
                           'time': datetime.now(timezone.utc).isoformat(), 'supporting_evidence': []}})
