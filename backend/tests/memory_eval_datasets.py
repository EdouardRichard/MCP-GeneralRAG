"""Shared 015 dataset loading, schema validation and append-only hashing.

Used by both the contract tests (T010) and the integration suites
(T016/T017/T022-T024/T068/T069/T075) so the eval data files stay the single
source of truth: tests never redefine case content or criteria in code.

Validation uses the contract README's ``$defs`` merge protocol (no new schema
registry): load the schema, load the shared common schema, ``$defs.update`` and
rewrite the relative ``$ref`` strings, then validate with Draft 2020-12.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "specs" / "015-memory-evaluation-governance" / "contracts"
COMMON_SCHEMA = "memory-benchmark-common.schema.json"
EVAL_DIR = REPO_ROOT / "eval"

POISONING_DATASET = "memory_poisoning_eval_dataset.json"
AOEP_DATASET = "memory_aoep_obligation_dataset.json"
CONTINUITY_DATASET = "memory_continuity_eval_dataset.json"
BENEFIT_DATASET = "consolidation_eval_dataset.json"

FORBIDDEN_SCOPE_IDS = ("366084747748704256",)

ASSERTION_NAMES = (
    "write_flagged",
    "write_quarantined",
    "default_recall_absent",
    "consolidation_input_absent",
    "attachment_absent",
    "working_set_absent",
    "control_surface_unchanged",
    "no_inconsistent_marking",
)

AOEP_INVARIANTS = (
    "traceable_rollback",
    "deletion_propagation",
    "authority_monotonicity",
    "provenance_preservation",
    "scope_non_expansion",
)

DELETION_PROJECTIONS = ("relation", "dense", "links", "summary", "file")


def canonical(value) -> str:
    """Canonical JSON used for every content hash in 015."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_dataset(name: str) -> dict:
    return load_json(EVAL_DIR / name)


def load_schema(name: str) -> dict:
    return load_json(CONTRACTS / name)


def merged_schema(name: str) -> dict:
    """Schema with the shared ``$defs`` inlined per contracts/README.md §1."""
    schema = load_schema(name)
    if name == COMMON_SCHEMA:
        return schema
    common = load_schema(COMMON_SCHEMA)
    merged = dict(schema)
    defs = dict(schema.get("$defs", {}))
    defs.update(common.get("$defs", {}))
    merged["$defs"] = defs
    text = json.dumps(merged, ensure_ascii=False)
    text = text.replace(f"./{COMMON_SCHEMA}#/$defs/", "#/$defs/")
    return json.loads(text)


def validate_dataset(document, schema_name: str) -> None:
    """Raise ``jsonschema.ValidationError`` when the document is not schema-legal."""
    from jsonschema import Draft202012Validator

    Draft202012Validator(merged_schema(schema_name)).validate(document)


def case_hashes(document, key: str = "cases") -> dict[str, str]:
    """Per-case canonical hash, keyed by case id (the append-only witness)."""
    return {entry["case_id"]: sha256_text(canonical(entry)) for entry in document[key]}


def frozen_subset_hash(document, key: str = "cases") -> str:
    """sha256 of the canonical frozen case array (poisoning ``snapshot_hash``)."""
    return sha256_text(canonical(document[key]))
