from pathlib import Path
import pytest


def test_cached_hub_revision_resolves_to_local_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('HF_HOME', str(tmp_path))
    cached = tmp_path / 'hub' / 'models--BAAI--bge-m3'
    snapshot = cached / 'snapshots' / 'revision1'
    snapshot.mkdir(parents=True)
    (snapshot / 'config.json').write_text('{}')
    (snapshot / 'model.safetensors').write_bytes(b'weights')
    (cached / 'refs').mkdir()
    (cached / 'refs/main').write_text('revision1')
    from rag_mcp.providers.model_cache import resolve_cached_model
    assert resolve_cached_model('BAAI/bge-m3') == str(snapshot)


def test_incomplete_cache_does_not_masquerade_as_loadable_model(tmp_path, monkeypatch):
    monkeypatch.setenv('HF_HOME', str(tmp_path))
    from rag_mcp.providers.model_cache import resolve_cached_model
    assert resolve_cached_model('BAAI/missing') == 'BAAI/missing'


def test_local_path_is_preserved(tmp_path):
    from rag_mcp.providers.model_cache import resolve_cached_model
    assert resolve_cached_model(str(tmp_path)) == str(tmp_path)


def test_eval_requires_real_model_and_propagates_loading_error(monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'eval'))
    from run_eval import _EvalEmbeddingProvider
    from rag_mcp.providers.local_cpu import LocalCPUEmbeddingProvider
    def fail(_self):
        raise RuntimeError('real weights unavailable')
    monkeypatch.setattr(LocalCPUEmbeddingProvider, 'get_dimension', fail)
    with pytest.raises(RuntimeError, match='real weights unavailable'):
        _EvalEmbeddingProvider('BAAI/bge-m3')
