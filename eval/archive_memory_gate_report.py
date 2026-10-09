#!/usr/bin/env python3
"""T059: archive the 014 continuity gate report for one comparison run.

Reads the record and replay reports produced by ``eval/run_memory_comparison.py``
and writes ``eval/runs/<run-id>/memory-gate-report.json`` with the frozen gate
conclusion, the evidence hashes and the archive provenance.  The archiver never
flips a configuration switch and never invents an observation: it copies only
what the two validated reports already measured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def conclusion(replay: dict) -> str:
    gates = replay.get('gates') or {}
    quality = (gates.get('quality') or {}).get('status')
    safety = (gates.get('safety') or {}).get('status')
    regression = (gates.get('regression') or {}).get('status')
    gain = replay.get('relative_gain') or {}
    parts = [f"quality={quality}", f"safety={safety}", f"regression={regression}"]
    if gain.get('zero_baseline'):
        parts.append('relative_gain=BASELINE_ZERO_NOT_COMPUTABLE')
    elif gain.get('value') is not None:
        parts.append(f"relative_gain={gain['value']:.4f}")
    eligible = bool(replay.get('default_enable_eligible'))
    parts.append(f"default_enable_eligible={eligible}")
    parts.append('switches unchanged; the report is evidence only')
    return '; '.join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        print(json.dumps({'status': 'refused', 'reason': f'output already exists: {args.output}'}))
        return 2
    record = json.loads(args.record.read_text(encoding='utf-8'))
    replay = json.loads(args.replay.read_text(encoding='utf-8'))
    payload = {
        'schema_version': replay.get('schema_version'),
        'report_type': '014_memory_continuity_gate_report',
        'run_id': args.output.parent.name,
        'archived_at': datetime.now(UTC).isoformat(),
        'archive': {
            'record': {'path': str(args.record), 'sha256': sha256_file(args.record),
                       'status': record.get('status')},
            'replay': {'path': str(args.replay), 'sha256': sha256_file(args.replay),
                       'status': replay.get('status')},
        },
        'commit': replay.get('commit'),
        'dataset_version': replay.get('dataset_version'),
        'snapshot_hash': replay.get('snapshot_hash'),
        'k': replay.get('k'),
        'queries': replay.get('queries'),
        'aggregates': replay.get('aggregates'),
        'relative_gain': replay.get('relative_gain'),
        'zero_baseline': replay.get('zero_baseline'),
        'criteria': replay.get('criteria'),
        'redundancy': replay.get('redundancy'),
        'reproducibility': replay.get('reproducibility'),
        'hard_metrics': replay.get('hard_metrics'),
        'cache': replay.get('cache'),
        'gates': replay.get('gates'),
        'status': replay.get('status'),
        'default_enable_eligible': replay.get('default_enable_eligible'),
        'default_configuration': replay.get('default_configuration'),
        'evidence_paths': replay.get('evidence_paths'),
        'failed_paths': replay.get('failed_paths'),
        'conclusion': conclusion(replay),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + '\n',
                           encoding='utf-8', newline='')
    print(json.dumps({'status': 'archived', 'output': str(args.output),
                      'gate_status': payload['status'],
                      'default_enable_eligible': payload['default_enable_eligible'],
                      'conclusion': payload['conclusion']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
