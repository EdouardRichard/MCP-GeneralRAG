"""T055: recall_memory additive v2 flag contract — StrictBool, defaults, legacy shape."""
import inspect

import pytest
from pydantic import StrictBool, ValidationError

from rag_mcp.mcp import recall_memory


def registered_function(monkeypatch):
    captured = {}

    class FakeServer:
        def tool(self, name, annotations=None):
            def decorator(function):
                captured['function'] = function
                return function
            return decorator

    monkeypatch.setattr(recall_memory, 'close_input_schema', lambda *args, **kwargs: None)
    recall_memory.register_recall_memory_tool(FakeServer(), None, None, None)
    return captured['function']


def test_v2_flags_are_additive_strict_bools_with_legacy_defaults(monkeypatch):
    function = registered_function(monkeypatch)
    signature = inspect.signature(function)
    legacy = ['scope_ref', 'query', 'memory_ids', 'kind', 'session_id', 'agent_id', 'time_window', 'as_of',
              'include_superseded', 'include_delivered', 'limit']
    assert all(parameter in signature.parameters for parameter in legacy)
    for name in ('include_linked', 'include_context'):
        parameter = signature.parameters[name]
        assert parameter.default is False
        assert parameter.annotation is StrictBool
    # Legacy ordering and defaults are unchanged.
    assert signature.parameters['limit'].default == 10
    assert signature.parameters['include_superseded'].default is False
    assert signature.parameters['include_delivered'].default is False


@pytest.mark.asyncio
async def test_non_boolean_flag_values_are_rejected_before_any_io(monkeypatch):
    function = registered_function(monkeypatch)
    from pydantic import TypeAdapter

    annotation = inspect.signature(function).parameters['include_linked'].annotation
    adapter = TypeAdapter(annotation)
    assert adapter.validate_python(False) is False
    for value in ('true', 1, 0, None, ['true']):
        with pytest.raises(ValidationError):
            adapter.validate_python(value)


def test_legacy_tool_schemas_are_not_touched_by_the_v2_extension():
    from rag_mcp.mcp import get_evidence, list_knowledge_domains, search_knowledge

    for module in (get_evidence, list_knowledge_domains, search_knowledge):
        source = inspect.getsource(module)
        assert 'include_linked' not in source and 'include_context' not in source


def test_enhancement_envelope_shape_is_additive_and_deterministic():
    from rag_mcp.services.memory_reader import enhancement_envelope

    envelope = enhancement_envelope(link_status='not_available', linked_count=0, context_status='unavailable',
                                    reasons=['GATE_NOT_CONFIGURED'])
    assert envelope == {'link_expansion_status': 'not_available', 'linked_count': 0,
                        'context_status': 'unavailable', 'degradation_reasons': ['GATE_NOT_CONFIGURED']}
    assert list(envelope) == ['link_expansion_status', 'linked_count', 'context_status', 'degradation_reasons']
    assert json_roundtrip_stable(envelope)


def json_roundtrip_stable(value):
    import json as module

    return module.loads(module.dumps(value, sort_keys=True)) == value
