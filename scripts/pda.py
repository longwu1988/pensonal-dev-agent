#!/usr/bin/env python3
"""Project integration and opt-in updates. Only update commands access GitHub."""
import argparse
import json
from pathlib import Path
import sys

from pda.transaction import recover, InstallError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'doctor', 'recover', 'check-update',
                                         'update', 'skip-update', 'remind-later'))
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='apply displayed changes')
    parser.add_argument('--force', action='store_true', help='check again without daily cache')
    parser.add_argument('--revision', help='full commit SHA offered by check-update')
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        parser.error('project must be an existing directory')
    if args.apply and args.action not in ('init', 'recover', 'update'):
        parser.error('--apply is only for init, recover or update')
    if args.force and args.action != 'check-update':
        parser.error('--force only bypasses check-update cache; it never overwrites files')
    needs_revision = args.action in ('update', 'skip-update', 'remind-later')
    if bool(args.revision) != needs_revision:
        parser.error('--revision is required only for update, skip-update and remind-later')
    package = Path(__file__).resolve().parents[1]
    try:
        if args.action == 'recover':
            recover(root, args.apply)
            return 0
        from pda.install import doctor, initialize
        from pda.updates import check_update, choose, update
        if args.action in ('init', 'doctor') and not (package / 'templates/project.json').is_file():
            raise InstallError('init/doctor require a reviewed source checkout; installed runtime supports update and recover')
        if args.action == 'doctor':
            print(json.dumps(doctor(root, package), ensure_ascii=False, indent=2))
        elif args.action == 'init':
            initialize(root, package, args.apply)
        elif args.action == 'update':
            update(root, args.revision, args.apply)
        else:
            result = check_update(root, args.force) if args.action == 'check-update' else choose(
                root, 'skip' if args.action == 'skip-update' else 'later', args.revision)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (InstallError, OSError, ValueError, KeyError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
