"""Read-only fourth agent. It is deliberately absent from the retrieval graph."""
import hashlib
import json
from importlib.resources import files

from jsonschema import ValidationError

from rag_mcp.agents.base import AgentBase, AgentResult
from rag_mcp.agents.llm_client import safe_failure_code
from rag_mcp.config.domain_profiles import (
    DISTILLER_PROMPT_VERSION,
    DISTILLER_SYSTEM_PROMPT,
    memory_vocabulary_version,
)
from rag_mcp.orchestration.consolidation_pipeline import thaw, validate_contract
from rag_mcp.services.memory_validators import detect_submission, redact_submission


class DistillerFailure(ValueError):
    """Only trusted code supplies these diagnostic codes."""


def canonical(value):
    return json.dumps(thaw(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class MemoryDistiller(AgentBase):
    ROLE = 'memory_distiller'
    NODE_SCHEMA = json.loads(files('rag_mcp.agents').joinpath('distiller-output.schema.json').read_text(encoding='utf-8'))

    def __init__(self, llm_client=None):
        super().__init__(model_and_version=llm_client.model if llm_client else '')
        self._llm_client = llm_client

    def _exception_detail(self, exc):
        return str(exc) if isinstance(exc, DistillerFailure) and safe_failure_code(str(exc)) else 'AGENT_EXECUTION_FAILED'

    def validate_output(self, output):
        try:
            validate_contract(output, self._validator)
        except (ValueError, TypeError, RecursionError, ValidationError):
            return AgentResult(output, False, self.model_and_version, error='MODEL_SCHEMA_INVALID')
        return AgentResult(output, True, self.model_and_version)

    def execute(self, context):
        if self._llm_client is None or not self._llm_client.configured:
            raise DistillerFailure('MODEL_CONFIGURATION_REQUIRED')
        window = context['window']
        untrusted = {}
        for name in ('episodes', 'references'):
            rows = thaw(getattr(window, name))
            if any(row.get('knowledge_scope_id') != window.scope_id for row in rows.values()):
                raise DistillerFailure('SCOPE_MISMATCH')
            clean = redact_submission(rows)
            if detect_submission(clean).status != 'active':
                raise DistillerFailure('INPUT_CONTENT_UNSAFE')
            untrusted['untrusted_' + name] = clean
        payload = {
            'scope_id': window.scope_id,
            'frozen_at': window.frozen_at.isoformat(),
            'versions': {'model': self.model_and_version, 'prompt': DISTILLER_PROMPT_VERSION,
                         'schema': fingerprint(self.NODE_SCHEMA), 'policy': fingerprint(window.policy),
                         'vocabulary': memory_vocabulary_version(thaw(window.vocabulary))},
            'memory_link_vocabulary': thaw(window.vocabulary),
            'policy': thaw(window.policy), 'output_schema': self.NODE_SCHEMA, **untrusted,
        }
        config = window.policy.get('consolidation') or {}
        if len(canonical(untrusted)) > config.get('max_input_chars', 32000):
            raise DistillerFailure('INPUT_BUDGET_EXCEEDED')
        receipt = self._llm_client.chat_json_receipt(
            DISTILLER_SYSTEM_PROMPT, canonical(payload), timeout_s=config.get('llm_timeout_seconds', 30))
        if receipt.reason:
            raise DistillerFailure(receipt.reason)
        return receipt.output

    def fallback(self, context):
        return {'proposals': []}
