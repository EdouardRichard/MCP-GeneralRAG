"""Use the pinned local Hub snapshot without a network metadata round trip."""
import os
from pathlib import Path


def resolve_cached_model(model_name: str) -> str:
    if Path(model_name).is_dir():
        return model_name
    home = Path(os.getenv('HF_HOME', str(Path.home() / '.cache/huggingface')))
    hub = Path(os.getenv('HF_HUB_CACHE', str(home / 'hub')))
    cache = hub / ('models--' + model_name.replace('/', '--'))
    ref = cache / 'refs/main'
    if not ref.is_file():
        return model_name
    revision = ref.read_text(encoding='utf-8').strip()
    snapshot = cache / 'snapshots' / revision
    if snapshot.parent.resolve() != (cache / 'snapshots').resolve():
        raise ValueError('invalid cached model revision')
    weights = ('model.safetensors', 'pytorch_model.bin', 'model.safetensors.index.json')
    if (snapshot / 'config.json').is_file() and any((snapshot / name).is_file() for name in weights):
        return str(snapshot)
    return model_name
