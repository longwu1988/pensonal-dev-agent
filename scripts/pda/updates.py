"""Per-project update notifications and explicit, pinned installation."""
import json
import time

from . import remote
from .install import MANIFEST, plan, show, show_next_steps
from .source import CHANNEL, REPOSITORY, identity, revision
from .transaction import (InstallError, apply_changes, atomic_write, ensure_ready,
                          json_bytes, locked, read)

STATE = '.local/agent/updates/state.json'
DAY = 86400


def installed_source(root):
    raw = read(root, MANIFEST)
    if raw is None:
        return None
    value = json.loads(raw).get('source')
    if (not isinstance(value, dict) or value.get('repository') != REPOSITORY
            or value.get('channel') != CHANNEL or value.get('commit') is None):
        return None
    revision(value['commit'])
    return value


def state_for(root, source):
    raw = read(root, STATE)
    if raw is None:
        return {'version': 1, 'source': source}
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('version') != 1:
        raise InstallError('invalid update state')
    if value.get('source') != source:
        return {'version': 1, 'source': source}
    for key in ('checked_at', 'deferred_until'):
        if key in value and (type(value[key]) not in (int, float) or value[key] < 0):
            raise InstallError('invalid update timestamp')
    for key in ('candidate', 'skipped'):
        if value.get(key) is not None:
            revision(value[key])
    return value


def save(root, state):
    atomic_write(root, STATE, json_bytes(state), 0o600)


def check_update(root, force=False, now=None):
    now = time.time() if now is None else now
    with locked(root):
        ensure_ready(root)
        source = installed_source(root)
        if source is None:
            return {'status': 'unknown_source', 'message': 'Use a reviewed clean checkout to init once; keep current rules.'}
        state = state_for(root, source)
        if not force and now < state.get('deferred_until', 0):
            return {'status': 'deferred', 'until': state['deferred_until']}
        elapsed = now - state.get('checked_at', -DAY)
        if not force and 0 <= elapsed < DAY:
            return {'status': 'cached', 'previous_status': state.get('status'), 'message': 'Continue with installed rules.'}
        state.pop('candidate', None)
        state.pop('deferred_until', None)
        result = {'installed': source['commit']}
        try:
            target = remote.latest()
            relation = remote.compare(source['commit'], target) if target != source['commit'] else {'status': 'identical', 'summary': [], 'url': ''}
            status = {'ahead': 'available', 'behind': 'ahead', 'identical': 'current', 'diverged': 'diverged'}[relation['status']]
            if status == 'available':
                state['candidate'] = target
                if state.get('skipped') == target:
                    status = 'skipped'
                result.update(candidate=target, summary=relation['summary'], compare_url=relation['url'])
            result['status'] = status
        except (InstallError, OSError, ValueError, KeyError, TypeError) as exc:
            result.update(status='unavailable', message='Cannot check GitHub; keep installed rules.', error=type(exc).__name__)
        state.update(checked_at=now, status=result['status'])
        save(root, state)
        return result


def pending(root, target):
    revision(target)
    source = installed_source(root)
    if source is None:
        raise InstallError('unknown installed source; bootstrap with a reviewed installer')
    state = state_for(root, source)
    if state.get('candidate') != target:
        raise InstallError('revision was not offered for this installed version; check-update first')
    return source, state


def choose(root, choice, target, now=None):
    now = time.time() if now is None else now
    if choice not in ('skip', 'later'):
        raise InstallError('unknown update choice')
    with locked(root):
        ensure_ready(root)
        source, state = pending(root, target)
        if choice == 'skip':
            state['skipped'] = target
            state.pop('deferred_until', None)
        else:
            state['deferred_until'] = now + DAY
        save(root, state)
    return {'status': 'skipped' if choice == 'skip' else 'deferred', 'candidate': target}


def update(root, target, apply=False):
    source, _ = pending(root, target)
    original_manifest = read(root, MANIFEST)
    with remote.download(target) as package:
        changes = plan(root, package, source=identity(target))
        show(changes)
        if not apply:
            print('Preview only. Use update --revision ' + target + ' --apply after choosing this version.')
            return
        with locked(root):
            current, _ = pending(root, target)
            if (current != source or read(root, MANIFEST) != original_manifest
                    or plan(root, package, source=identity(target)) != changes):
                raise InstallError('project changed after preview; check-update again')
            if changes:
                apply_changes(root, changes)
        print('Updated to ' + target + '. Start a new task to load new rules. recover can restore this transaction.')
        show_next_steps(root, updated=True)
