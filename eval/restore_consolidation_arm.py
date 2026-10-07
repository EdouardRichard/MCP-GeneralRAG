#!/usr/bin/env python3
"""T097 isolated six-way restoration runner (CLI).

Every ``(round, arm)`` of a record/replay comparison is restored from the same
sealed capsule into its own PostgreSQL database, its own Qdrant server store and
its own private ``data_root``. Nothing is ever restored from another arm or
round, and a target database/Qdrant store is never reused.

Subcommands:

* ``provision``  create an empty isolated database (native ``CREATE DATABASE``);
* ``drop``       tear down identities this runner created (never a capsule);
* ``seal``       seal a capsule from the quiescent isolated source store;
* ``restore``    restore one ``(round, arm)`` identity from a capsule;
* ``verify``     re-verify a restored identity against the capsule;
* ``status``     print the allocated identities of a run.

The runner exits 0 only when the requested restoration is complete and
verified, 1 when a real check failed, and 2 when the required material or tools
are unavailable (never a fabricated pass).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT / 'eval'), str(ROOT / 'backend' / 'src')):
    if path not in sys.path:
        sys.path.insert(0, path)

from consolidation_restore_support import (
    ARMS,
    ROUNDS,
    RestoreError,
    allocate_identities,
    assert_independent,
    create_database,
    database_exists,
    drop_database,
    load_run,
    restore_identity,
    save_run,
    seal_capsule,
    stop_qdrant,
    verify_identity,
)

EXIT_OK, EXIT_FAILED, EXIT_INCOMPLETE = 0, 1, 2


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def command_provision(args: argparse.Namespace) -> int:
    if database_exists(args.database):
        raise RestoreError(f'database {args.database!r} already exists')
    create_database(args.database, template=args.template)
    _print({'status': 'provisioned', 'database': args.database, 'template': args.template,
            'size_bytes': None})
    return EXIT_OK


def command_allocate(args: argparse.Namespace) -> int:
    run = allocate_identities(args.run_id, base=Path(args.base), qdrant_port_base=args.qdrant_port_base)
    proof = assert_independent(run)
    save_run(run, Path(args.output))
    _print({'status': 'allocated', 'run_id': run.run_id, 'proof': proof,
            'identities': [identity.as_record() for identity in run.identities]})
    return EXIT_OK


def command_status(args: argparse.Namespace) -> int:
    run = load_run(Path(args.run))
    _print({'status': 'ok', 'run_id': run.run_id, 'proof': assert_independent(run),
            'identities': [identity.as_record() for identity in run.identities]})
    return EXIT_OK


def command_drop_database(args: argparse.Namespace) -> int:
    dropped = []
    for database in args.database:
        if database_exists(database):
            drop_database(database)
            dropped.append(database)
    _print({'status': 'dropped', 'dropped': dropped})
    return EXIT_OK


def command_drop(args: argparse.Namespace) -> int:
    run = load_run(Path(args.run))
    dropped = []
    for identity in run.identities:
        if database_exists(identity.database):
            drop_database(identity.database)
            dropped.append(identity.database)
        if not args.keep_qdrant:
            stop_qdrant(identity)
    _print({'status': 'dropped', 'run_id': run.run_id, 'dropped': dropped})
    return EXIT_OK


def command_seal(args: argparse.Namespace) -> int:
    scopes = [int(part) for part in args.scopes.replace(',', ' ').split()]
    if not scopes:
        raise RestoreError('--scopes must list at least one numeric scope id')
    report = seal_capsule(source_database=args.source_database,
                          source_data_root=Path(args.source_data_root),
                          capsule_dir=Path(args.capsule_dir), scopes=scopes,
                          capsule_token=args.token, source_qdrant_url=args.source_qdrant_url,
                          collections=args.collections.split(',') if args.collections else None)
    _print(report)
    return EXIT_OK


def _identical(args: argparse.Namespace):
    return load_run(Path(args.run)).get(args.round, args.arm)


def command_restore(args: argparse.Namespace) -> int:
    report = restore_identity(Path(args.capsule_dir), _identical(args))
    _print(report)
    return EXIT_OK


def command_verify(args: argparse.Namespace) -> int:
    report = verify_identity(Path(args.capsule_dir), _identical(args))
    _print({'status': 'verified', **report})
    return EXIT_OK


def command_stop(args: argparse.Namespace) -> int:
    identity = _identical(args)
    stop_qdrant(identity)
    _print({'status': 'stopped', 'label': identity.label, 'qdrant_url': identity.qdrant_url})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    provision = sub.add_parser('provision', help='create an empty isolated database')
    provision.add_argument('--database', required=True)
    provision.add_argument('--template', help='optional isolated template database for a native copy')
    provision.set_defaults(handler=command_provision)

    allocate = sub.add_parser('allocate', help='allocate the six independent identities of a run')
    allocate.add_argument('--run-id', required=True)
    allocate.add_argument('--base', required=True)
    allocate.add_argument('--output', required=True)
    allocate.add_argument('--qdrant-port-base', type=int, default=16400)
    allocate.set_defaults(handler=command_allocate)

    status = sub.add_parser('status', help='print a run identity file')
    status.add_argument('--run', required=True)
    status.set_defaults(handler=command_status)

    drop = sub.add_parser('drop', help='drop the databases of a run')
    drop.add_argument('--run', required=True)
    drop.add_argument('--keep-qdrant', action='store_true')
    drop.set_defaults(handler=command_drop)

    drop_database = sub.add_parser('drop-database', help='drop named isolated databases')
    drop_database.add_argument('--database', action='append', required=True)
    drop_database.set_defaults(handler=command_drop_database)

    seal = sub.add_parser('seal', help='seal a capsule from the quiescent isolated source store')
    seal.add_argument('--source-database', required=True)
    seal.add_argument('--source-data-root', required=True)
    seal.add_argument('--source-qdrant-url', default='http://127.0.0.1:16333')
    seal.add_argument('--capsule-dir', required=True)
    seal.add_argument('--scopes', required=True, help='comma separated frozen scope ids')
    seal.add_argument('--token', required=True, help='alphanumeric capsule token')
    seal.add_argument('--collections', help='comma separated Qdrant collections to seal (default: every collection)')
    seal.set_defaults(handler=command_seal)

    for name, handler, help_text in (('restore', command_restore, 'restore one (round, arm) identity from a capsule'),
                                     ('verify', command_verify, 're-verify a restored identity against the capsule'),
                                     ('stop', command_stop, 'stop the Qdrant server of one identity')):
        sub_parser = sub.add_parser(name, help=help_text)
        sub_parser.add_argument('--capsule-dir', required=True)
        sub_parser.add_argument('--run', required=True)
        sub_parser.add_argument('--round', required=True, choices=ROUNDS)
        sub_parser.add_argument('--arm', required=True, choices=ARMS)
        sub_parser.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.environ.setdefault('PYTHONPATH', os.pathsep.join((str(ROOT / 'backend' / 'src'), str(ROOT / 'eval'))))
    try:
        return args.handler(args)
    except RestoreError as error:
        _print({'status': 'incomplete', 'reason': str(error)})
        return EXIT_INCOMPLETE


if __name__ == '__main__':
    raise SystemExit(main())
