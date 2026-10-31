#!/usr/bin/env python3
"""Project integration, opt-in updates and user-started issue queues."""
import argparse
import json
from pathlib import Path
import sys

from pda.transaction import recover, InstallError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'doctor', 'recover', 'check-update',
                                         'update', 'skip-update', 'remind-later',
                                         'queue-start', 'queue-stop', 'queue-status', 'queue-next',
                                         'queue-guard', 'queue-checkpoint', 'queue-block', 'queue-retry', 'queue-finish'))
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--apply', action='store_true', help='apply displayed changes')
    parser.add_argument('--force', action='store_true', help='check again without daily cache')
    parser.add_argument('--revision', help='full commit SHA offered by check-update')
    parser.add_argument('--owner', help='unique current conversation ID for queue ownership')
    parser.add_argument('--stage', help='queue checkpoint stage')
    parser.add_argument('--branch', help='task branch checkpoint')
    parser.add_argument('--worktree', help='task worktree checkpoint')
    parser.add_argument('--commit', help='full task or integration commit SHA')
    parser.add_argument('--reason', help='queue blocking reason code')
    parser.add_argument('--issue', type=int, help='explicit queue retry issue number')
    parser.add_argument('--evidence', help='test/review evidence locator; never credential text')
    args = parser.parse_args()
    queue_fields = {'owner': ('queue-start','queue-next','queue-guard','queue-checkpoint','queue-block','queue-retry','queue-finish'),
                    'stage': ('queue-checkpoint',), 'branch': ('queue-checkpoint',),
                    'worktree': ('queue-checkpoint',), 'commit': ('queue-checkpoint','queue-finish'),
                    'reason': ('queue-block',), 'issue': ('queue-retry',), 'evidence': ('queue-finish',)}
    for field, actions in queue_fields.items():
        if getattr(args, field) is not None and args.action not in actions:
            parser.error('--' + field + ' is not valid for this action')
    if args.action in queue_fields['owner'] and not args.owner:
        parser.error('--owner is required for queue work')
    required = {'queue-checkpoint': ('stage',), 'queue-block': ('reason',),
                'queue-retry': ('issue',), 'queue-finish': ('commit','evidence')}
    if any(getattr(args, field) is None for field in required.get(args.action, ())):
        parser.error('missing required queue action arguments')
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        parser.error('project must be an existing directory')
    if args.apply and args.action not in ('init', 'recover', 'update', 'queue-start'):
        parser.error('--apply is only for init, recover, update or queue-start')
    if args.force and args.action != 'check-update':
        parser.error('--force only bypasses check-update cache; it never overwrites files')
    needs_revision = args.action in ('update', 'skip-update', 'remind-later')
    if bool(args.revision) != needs_revision:
        parser.error('--revision is required only for update, skip-update and remind-later')
    package = Path(__file__).resolve().parents[1]
    try:
        if args.action.startswith('queue-'):
            from pda.issue_queue import dispatch
            print(json.dumps(dispatch(root, args), ensure_ascii=False, indent=2))
            return 0
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
