"""Opt-in durable authorization for host-scheduled, same-thread queue ticks.

This module is not a daemon or scheduler. The host adapter verifies its schedule.
A stop token revokes every prior generation, including already queued wakeups.
"""
from contextlib import contextmanager
import fcntl
import json
import os
import re
import time
import uuid

from .issue_queue import QueueBusy, QueueConflict, configuration, git, main_project
from .issue_tracker import TrackerAccessDenied
from .issue_workers import WorkerQueue as Queue
from .transaction import InstallError, atomic_write, json_bytes, read, safe_path

DIRECTORY = '.local/agent/watch'
STATE = DIRECTORY + '/state.json'
LOCK = DIRECTORY + '/write.lock'


def identifier(value):
    if not isinstance(value, str) or not value or not value.isprintable() or len(value) > 200:
        raise InstallError('valid host thread/scheduler identifier required')
    return value


class Watch:
    def __init__(self, queue, clock=time.time):
        self.queue, self.root, self.clock = queue, queue.root, clock

    def status(self):
        raw = read(self.root, STATE)
        if raw is None: return {'version': 1, 'status': 'off', 'scheduler_id': None}
        try:
            state = json.loads(raw)
            if (state['version'] != 1 or state['status'] not in ('pending', 'active', 'suspended')
                    or not isinstance(state['generation'], str)
                    or type(state['interval']) is not int or not 60 <= state['interval'] <= 86400
                    or type(state['next_due']) not in (int, float)
                    or type(state['failures']) is not int):
                raise ValueError()
            for key in ('owner', 'thread', 'repository', 'integration_branch'): identifier(state[key])
            if state['stop_ack'] != self.queue._stop_token(): state['status'] = 'stopped'
            return state
        except (ValueError, UnicodeError, KeyError, TypeError):
            raise InstallError('invalid watch state; preserve for recovery; queue-stop still revokes it') from None

    @contextmanager
    def _locked(self):
        safe_path(self.root, STATE)
        current = self.root
        for part in DIRECTORY.split('/'):
            current /= part
            current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)
        fd = os.open(safe_path(self.root, LOCK), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise QueueBusy('another watch command is running; do not run a parallel tick') from None
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)

    def _save(self, state):
        atomic_write(self.root, STATE, json_bytes(state), 0o600)

    def start(self, thread, interval=300):
        identifier(thread)
        if type(interval) is not int or not 60 <= interval <= 86400:
            raise InstallError('interval must be 60..86400 seconds; host must support chosen cadence')
        acknowledged = self.queue._stop_token()
        with self._locked():
            old = self.status()
            if old['status'] in ('active', 'pending', 'suspended'):
                raise InstallError('stop existing watch and pause its scheduler before starting a new generation')
            queue = self.queue.status()
            if queue['enabled']: raise InstallError('stop active one-shot queue before enabling watch')
            if not self.queue.tracker or not self.queue.branch: raise InstallError('configured queue required')
            if queue['repository'] and (queue['repository'] != self.queue.tracker.repository
                                      or queue['integration_branch'] != self.queue.branch):
                raise InstallError('queue binding changed; reconcile saved work first')
            # A worker's stop token is scoped to its owner even when its queue is empty.
            # Keep that namespace; the fresh generation still revokes every old wakeup.
            owner = queue.get('owner') if queue.get('version') == 2 else None
            owner = owner or 'watch-' + uuid.uuid4().hex
            if queue.get('version') == 2:
                self.queue.owner = owner
            state = dict(version=1, status='pending', generation=uuid.uuid4().hex,
                         thread=thread, owner=owner, scheduler_id=None,
                         repository=self.queue.tracker.repository, integration_branch=self.queue.branch,
                         interval=interval, next_due=0, failures=0, stop_ack=acknowledged)
            self._save(state)
            return self.status()

    def _authorized(self, state, generation):
        if state['status'] not in ('active', 'pending') or state['generation'] != generation:
            raise InstallError('watch authorization absent, revoked, suspended or superseded')
        if (not self.queue.tracker or state['repository'] != self.queue.tracker.repository
                or state['integration_branch'] != self.queue.branch):
            state['status'] = 'suspended'
            self._save(state)
            raise QueueConflict('watch repository or integration branch changed; watch suspended')

    def bind(self, generation, scheduler):
        identifier(scheduler)
        with self._locked():
            state = self.status(); self._authorized(state, generation)
            if state['scheduler_id'] not in (None, scheduler):
                raise InstallError('different scheduler already bound; stop before rebinding')
            state.update(scheduler_id=scheduler, status='active')
            self._save(state)
            return self.status()

    def suspend(self):
        # Called for configuration/permission failures before a tick can be constructed.
        if self.status()['status'] not in ('active', 'pending'): return
        with self._locked():
            state = self.status()
            if state['status'] in ('active', 'pending'):
                state['status'] = 'suspended'
                self._save(state)

    def tick(self, generation, scheduler, thread):
        with self._locked():
            state = self.status(); self._authorized(state, generation)
            if state['status'] != 'active' or state['scheduler_id'] != scheduler or state['thread'] != thread:
                raise InstallError('wake must match the bound active scheduler and thread')
            now = self.clock()
            if now < state['next_due']: return {'status': 'not_due', 'next_due': state['next_due']}
            # Persist cadence before remote calls; a duplicate wake cannot immediately replay it.
            state['next_due'] = now + state['interval']; self._save(state)
            self.queue.owner = state['owner']
            try:
                current = self.queue.status()
                if current['enabled'] and current['owner'] != state['owner']:
                    raise QueueConflict('another queue owner is active; do not take over')
                if not current['enabled']:
                    self.queue.start(expected_stop=state['stop_ack'])
                self._authorized(self.status(), generation)
                current = self.queue.status().get('current')
                if current and current['stage'] == 'waiting_user':
                    self.queue.guard()
                    result = {'status': 'waiting_user', 'checkpoint': current}
                else:
                    result = self.queue.next()
                    if result['status'] == 'empty':
                        if result['queue']['release'] != 'released':
                            raise InstallError('queue lease release pending; reconcile before continuing')
                        result = {'status': 'idle'}
                self._authorized(self.status(), generation)
                state['failures'] = 0
                self._save(state)
                return dict(result, owner=state['owner'], generation=generation, next_due=state['next_due'])
            except (InstallError, OSError) as exc:
                # No raw error/credential content in state. Stop is independently latched.
                state['failures'] += 1
                state['next_due'] = now + min(state['interval'] * (2 ** min(state['failures'], 6)), 86400)
                if isinstance(exc, (QueueConflict, TrackerAccessDenied)) or state['failures'] >= 3: state['status'] = 'suspended'
                self._save(state)
                raise


def dispatch(root, args):
    root = main_project(root)
    queue = Queue(root)
    watch = Watch(queue)
    # Resolve the bound worker for stop tokens before any action, including status.
    saved = read(root, STATE)
    if saved is not None:
        try:
            value = json.loads(saved)
            if (not isinstance(value, dict) or not isinstance(value.get('owner'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value['owner'])):
                raise ValueError()
            queue.owner = value['owner']
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise InstallError('invalid watch owner; preserve state and reconcile; queue-stop --all explicitly stops all local workers') from None
    action = args.action.split('-', 1)[1]
    if action == 'status': return watch.status()
    if action == 'stop':
        # No bound watch must never fall back to a global manual-worker stop.
        if saved is None:
            return {'status': 'off', 'scheduler_cleanup_required': True}
        from .worker_dispatch import validate_storage
        validate_storage(root, queue)
        # A valid owner can be stopped even if the rest of watch/config is malformed.
        result = queue.stop()
        return {'status': 'stopped', 'queue': result, 'scheduler_cleanup_required': True}
    try:
        config, tracker, repository, branch = configuration(root)
    except InstallError:
        if action in ('tick', 'bind'): watch.suspend()
        raise
    if action == 'start' and not args.apply:
        return dict(status='preview', repository=repository, integration_branch=branch,
                    interval=300 if args.interval is None else args.interval, label='ai-ready',
                    needs=['explicit continuous authorization', 'same-thread host scheduler',
                           'API/Git access and queue permissions', 'verified scheduler binding'])
    # Continuous mode needs project-wide control permission; never borrow an issue grant.
    if action == 'start' and queue.owner is None:
        queue.owner = 'watch-' + uuid.uuid4().hex
    from .worker_dispatch import validate_storage, bind_authorization, CONTROL_PERMISSIONS
    from .permissions import Permissions
    try:
        Permissions(root, repository, branch, queue.owner).require(config.get('permissions', {}), None, CONTROL_PERMISSIONS)
        if queue.status().get('issue_scope') is not None:
            raise InstallError('single-issue worker cannot start continuous watch')
    except InstallError:
        if action in ('tick', 'bind'): watch.suspend()
        raise
    validate_storage(root, queue)
    for directory in (DIRECTORY, '.local/agent/queue'):
        if git(root, 'ls-files', '--', directory): raise InstallError('watch/queue state must not be Git-tracked')
    for target in (STATE, LOCK, '.local/agent/queue/state.json', '.local/agent/queue/write.lock', '.local/agent/queue/stop'):
        safe_path(root, target)
        git(root, 'check-ignore', '--quiet', '--', target)
    from .issue_tracker import Tracker
    from .issue_queue import GitLease
    credentials = config.get('environment', {}).get('secrets')
    if credentials in (None, '', '.local/secrets/access.json', 'external-controlled-storage'): credentials = None
    try:
        queue.tracker = Tracker(tracker['kind'], repository, root, credentials_path=credentials)
    except InstallError:
        if action in ('tick', 'bind'): watch.suspend()
        raise
    from .issue_claims import Claims
    queue.lease, queue.branch, queue.claims = GitLease(root, repository), branch, Claims(root, repository)
    bind_authorization(queue)
    if action == 'start': return watch.start(args.thread, 300 if args.interval is None else args.interval)
    if action == 'bind': return watch.bind(args.generation, args.scheduler)
    if action == 'tick': return watch.tick(args.generation, args.scheduler, args.thread)
    raise InstallError('unknown watch action')
