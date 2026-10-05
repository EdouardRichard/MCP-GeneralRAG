from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


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

    @staticmethod
    def normalize_remote(value):
        if "://" not in value:
            match = re.fullmatch(r"([^/@:]+(?::[0-9]+)?)/(.+)", value)
            if match is None:
                match = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", value)
            if not match:
                raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
            host, path = match.groups()
        else:
            try:
                parsed = urlsplit(value)
                port = parsed.port
            except ValueError:
                raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE") from None
            if parsed.scheme not in {"https", "http", "ssh", "git"} or not parsed.hostname or parsed.query or parsed.fragment:
                raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
            host, path = parsed.hostname, parsed.path
            if port and port not in {22, 80, 443}:
                host += ":" + str(port)
        path = path.strip("/").removesuffix(".git")
        if not path or any(part in {".", ".."} for part in path.split("/")):
            raise ScopeBindingError("MISSING_KNOWLEDGE_SCOPE")
        return host.lower() + "/" + path

    def resolve(self, scope_ref):
        if scope_ref.startswith("path:"):
            raw = scope_ref[5:]
            remote = "://" in raw or bool(re.match(r"(?:[^/@:]+@)?[^/:]+:[^\\/].+", raw)) and not re.match(r"^[A-Za-z]:", raw)
            value = self.normalize_remote(raw) if remote else self._normalize_path(raw)
            candidates = []
            for binding in self.bindings:
                if binding.get("status", "active") != "active":
                    continue
                kind = binding.get("binding_kind")
                matched, specificity = False, 0
                if remote and kind == "git_remote":
                    matched = value == self.normalize_remote(binding["binding_value"])
                    specificity = len(value)
                elif not remote and kind == "workdir_prefix":
                    prefix = self._normalize_path(binding["binding_value"])
                    matched = value == prefix or value.startswith(prefix + "/")
                    specificity = len(prefix)
                elif not remote and kind == "dir_name":
                    matched = os.path.normcase(Path(value).name) == os.path.normcase(binding["binding_value"])
                if matched:
                    candidates.append((specificity, binding.get("priority", 0), binding["knowledge_scope_id"]))
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
        raise PermissionError("scope bindings require a management grant event")
