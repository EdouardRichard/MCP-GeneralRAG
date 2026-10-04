from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ScopeBindingError(ValueError):
    def __init__(self, code, candidates=None):
        super().__init__(code)
        self.code = code
        self.candidates = candidates or []


@dataclass(frozen=True)
class ScopeResolution:
    scope_id: int
    normalized: str


class ScopeBindingService:
    def __init__(self, bindings):
        self.bindings = list(bindings)

    @staticmethod
    def _normalize_path(value):
        path = Path(value)
        if not path.is_absolute():
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        return os.path.normcase(str(path.resolve(strict=False))).replace("\\", "/").rstrip("/")

    def resolve(self, scope_ref):
        if scope_ref.startswith("path:"):
            value = self._normalize_path(scope_ref[5:])
            candidates = []
            for binding in self.bindings:
                if binding.get("status", "active") != "active" or binding.get("binding_kind") != "workdir_prefix":
                    continue
                prefix = self._normalize_path(binding["binding_value"])
                if value == prefix or value.startswith(prefix + "/"):
                    candidates.append((len(prefix), binding.get("priority", 0), binding["knowledge_scope_id"]))
            if not candidates:
                raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
            best_len = max(item[0] for item in candidates)
            best_priority = max(item[1] for item in candidates if item[0] == best_len)
            chosen = sorted(item[2] for item in candidates if item[0] == best_len and item[1] == best_priority)
            if len(chosen) != 1:
                raise ScopeBindingError("AMBIGUOUS_DOMAIN_REF", chosen)
            return ScopeResolution(chosen[0], value)
        raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")

    def add_binding(self, binding, *, actor):
        if actor != "management":
            raise PermissionError("scope bindings are management-only")
        self.bindings.append({**binding, "status": binding.get("status", "active")})
