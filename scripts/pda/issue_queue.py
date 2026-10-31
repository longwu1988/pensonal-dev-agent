"""Session-operated queue control; never executes issue text or business commands."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import uuid

from .transaction import InstallError, atomic_write, json_bytes, read, safe_path

DIRECTORY = '.local/agent/queue'
STATE = DIRECTORY + '/state.json'
STOP = DIRECTORY + '/stop'
LOCK = DIRECTORY + '/write.lock'
REF = 'refs/heads/personal-dev/queue-lock'
STAGES = {'claimed', 'planning', 'implementing', 'testing', 'waiting_user', 'reviewing', 'ready_to_merge'}
REASONS = {'needs_input', 'dependency', 'test_failed', 'auth', 'environment', 'review'}


def git(root, *args, data=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_AUTHOR_NAME='Personal Dev Queue',
               GIT_AUTHOR_EMAIL='queue@example.invalid', GIT_COMMITTER_NAME='Personal Dev Queue',
               GIT_COMMITTER_EMAIL='queue@example.invalid')
    try:
        result = subprocess.run(['git', '-C', str(root), *args], input=data,
                                capture_output=True, text=True, timeout=25, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallError('queue Git unavailable or timed out; inspect ownership before retry') from exc
    if result.returncode:
        raise InstallError('queue Git operation failed; verify authentication, branch and ownership')
    return result.stdout.strip()


class QueueBusy(InstallError):
    pass


class GitLease:
    """Distinct orphan commit plus expected-ref CAS, not an advisory issue comment."""
    def __init__(self, root, repository=None):
        self.root, self.repository = root, repository

    def _validate(self):
        if self.repository: validate_remote(self.root, self.repository)

    def current(self):
        self._validate()
        value = git(self.root, 'ls-remote', '--refs', 'origin', REF)
        if not value: return None
        fields = value.split()
        if len(fields) != 2 or fields[1] != REF or not re.fullmatch('[0-9a-f]{40}', fields[0]):
            raise InstallError('invalid queue ownership response')
        return fields[0]

    def prepare(self, session):
        blob = git(self.root, 'hash-object', '-w', '--stdin', data=json.dumps({'session': session, 'purpose': 'personal-dev-queue'}))
        tree = git(self.root, 'mktree', data='100644 blob ' + blob + '\tqueue.json\n')
        return git(self.root, 'commit-tree', tree, data='Personal dev queue ownership ' + session + '\n')

    def acquire(self, sha):
        self._validate()
        git(self.root, 'push', '--porcelain', '--force-with-lease=' + REF + ':', 'origin', sha + ':' + REF)
        if self.current() != sha:
            raise InstallError('queue ownership acquisition not confirmed')

    def release(self, sha):
        current = self.current()
        if current is None: return
        if current != sha: raise InstallError('queue ownership belongs to another session; do not delete it')
        git(self.root, 'push', '--porcelain', '--force-with-lease=' + REF + ':' + sha, 'origin', ':' + REF)
        if self.current() is not None:
            raise InstallError('queue ownership release not confirmed')

    def contains(self, commit, branch):
        self._validate()
        git(self.root, 'check-ref-format', '--branch', branch)
        if branch.startswith('-'): raise InstallError('invalid integration branch')
        git(self.root, 'fetch', '--no-tags', 'origin', 'refs/heads/' + branch)
        try:
            git(self.root, 'merge-base', '--is-ancestor', commit, 'FETCH_HEAD')
            return True
        except InstallError:
            return False


def main_project(root):
    """Git's first worktree is the common/main checkout; do not scan other projects."""
    records = git(root, 'worktree', 'list', '--porcelain', '-z').split('\0')
    if not records or not records[0].startswith('worktree '):
        raise InstallError('cannot identify main project worktree')
    main = Path(records[0][len('worktree '):]).resolve()
    if not main.is_dir(): raise InstallError('main project worktree is unavailable')
    return main


def labels(item):
    return {x['name'].lower() for x in item.get('labels', []) if isinstance(x, dict) and isinstance(x.get('name'), str)}


def eligible(item):
    names = labels(item)
    return (type(item.get('number')) is int and item['number'] > 0 and item.get('state') == 'open'
            and item.get('pull_request') is None and 'ai-ready' in names
            and not names.intersection({'ai-blocked', 'ai-in-progress'})
            and not item.get('assignees') and not item.get('assignee'))


def order(item):
    names = labels(item)
    priority = min((i for i in range(4) if 'p' + str(i) in names), default=4)
    try:
        created = datetime.fromisoformat(item['created_at'].replace('Z', '+00:00'))
        if created.tzinfo is None: raise ValueError()
    except (KeyError, AttributeError, TypeError, ValueError):
        raise InstallError('valid timezone-aware issue creation timestamp required') from None
    return priority, created, item['number']


class Queue:
    def __init__(self, root, tracker=None, lease=None, branch=None, owner=None):
        self.root, self.tracker = Path(root), tracker
        self.lease = lease or GitLease(root)
        self.branch, self.owner = branch, owner

    def _directory(self):
        safe_path(self.root, STATE)
        current = self.root
        for part in DIRECTORY.split('/'):
            current = current / part
            current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)

    @contextmanager
    def _locked(self):
        self._directory()
        path = safe_path(self.root, LOCK)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueBusy('another queue command is running; stop request remains effective') from exc
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)

    def status(self):
        raw = read(self.root, STATE)
        if raw is None:
            state = dict(version=1, enabled=False, session=None, repository=None, integration_branch=None,
                         lease=None, owner=None, current=None, blocked={}, completed=[], release='released', stop_ack=None)
        else:
            try: state = json.loads(raw)
            except (ValueError, UnicodeError) as exc: raise InstallError('invalid queue state; preserve it for recovery') from exc
            if (not isinstance(state, dict) or state.get('version') != 1 or type(state.get('enabled')) is not bool
                    or not isinstance(state.get('blocked'), dict) or not isinstance(state.get('completed'), list)):
                raise InstallError('invalid queue state; preserve it for recovery')
        if self._stopped(state):
            state['enabled'] = False
            if state.get('lease'):
                state['release'] = 'retained_for_resume' if state.get('current') else 'pending'
        return state

    def _stop_token(self):
        raw = read(self.root, STOP)
        return hashlib.sha256(raw).hexdigest() if raw is not None else None

    def _stopped(self, state):
        return self._stop_token() != state.get('stop_ack')

    def _save(self, state):
        if self._stopped(state): state['enabled'] = False
        atomic_write(self.root, STATE, json_bytes(state), 0o600)

    def _transition(self, state):
        # Called while holding the queue lock. Stop latches independently; if it
        # races the replace, restore the previous checkpoint before releasing lock.
        if self._stopped(state): raise InstallError('stop requested; queue transition rejected')
        before = read(self.root, STATE)
        atomic_write(self.root, STATE, json_bytes(state), 0o600)
        if self._stopped(state):
            atomic_write(self.root, STATE, before, 0o600)
            raise InstallError('stop requested; previous task progress retained')

    def _owner(self, state):
        if not self.owner or state.get('owner') != self.owner:
            raise InstallError('queue belongs to a different active conversation')

    def _active(self, state):
        self._owner(state)
        if not state['enabled'] or self._stopped(state):
            raise InstallError('queue is stopped; only explicit user start may resume')
        if (not self.tracker or state['repository'] != self.tracker.repository
                or state['integration_branch'] != self.branch):
            raise InstallError('queue repository or integration branch changed; reconcile saved work first')
        if not state['lease'] or self.lease.current() != state['lease']:
            raise InstallError('queue ownership missing or changed; stop work')
        if self._stopped(state):
            raise InstallError('stop requested; do not advance')

    def start(self):
        acknowledged_stop = self._stop_token()
        with self._locked():
            state = self.status()
            if not self.tracker or not self.branch: raise InstallError('configured tracker and integration branch required')
            if not self.owner or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.owner):
                raise InstallError('explicit conversation owner ID required')
            if state['enabled'] and state.get('owner') != self.owner:
                raise InstallError('another conversation is running; stop it before transferring ownership')
            if state['repository'] is not None and (state['repository'] != self.tracker.repository or state['integration_branch'] != self.branch):
                raise InstallError('queue binding changed; reconcile saved work before starting')
            # Acknowledge only the stop observed on entry; never delete a newer stop.
            state.update(repository=self.tracker.repository, integration_branch=self.branch,
                         enabled=False, stop_ack=acknowledged_stop, owner=self.owner)
            if state['session'] is None: state['session'] = str(uuid.uuid4())
            current = self.lease.current()
            if current is not None and current != state['lease']:
                raise InstallError('repository queue is occupied; do not steal or expire its lock')
            if current is None:
                state['lease'] = self.lease.prepare(state['session'] + '-' + str(uuid.uuid4()))
                state['release'] = 'pending'
                self._save(state)  # Save identity BEFORE an ambiguous push or process exit.
                if self._stopped(state): raise InstallError('stop requested during start')
                self.lease.acquire(state['lease'])
            state.update(enabled=True, release='owned')
            self._save(state)
            return self.status()

    def stop(self):
        self._directory()
        atomic_write(self.root, STOP, (str(uuid.uuid4()) + '\n').encode(), 0o600)  # Does not wait for a long request.
        try:
            with self._locked():
                state = self.status()
                if isinstance(self.lease, GitLease):
                    self.lease.repository = state.get('repository')
                state['enabled'] = False
                if state['current'] is not None:
                    state['release'] = 'retained_for_resume'
                    self._save(state)
                    return state
                return self._release(state)
        except QueueBusy:
            state = self.status()
            state['cleanup_required'] = True
            return state

    def _release(self, state):
        state['enabled'] = False
        self._save(state)
        try:
            if state['lease']: self.lease.release(state['lease'])
        except InstallError:
            state['release'] = 'pending'
        else:
            state.update(lease=None, release='released')
        self._save(state)
        return state

    def next(self):
        # A stopped no-op must not even create a state directory.
        if not self.status()['enabled']: raise InstallError('queue is stopped')
        with self._locked():
            state = self.status(); self._active(state)
            if state['current'] is not None:
                item = self.tracker.issue(state['current']['number'])
                self._active(state)
                if not eligible(item):
                    raise InstallError('current issue closed, withdrawn or assigned; reconcile before continuing')
                return {'status': 'resume', 'issue': item, 'checkpoint': state['current']}
            items = self.tracker.issues()
            self._active(state)
            candidates = sorted((x for x in items if eligible(x) and str(x['number']) not in state['blocked']
                                 and x['number'] not in state['completed']), key=order)
            for candidate in candidates:
                item = self.tracker.issue(candidate['number'])  # Refetch description + comments before claiming.
                self._active(state)
                if not eligible(item): continue
                state['current'] = dict(number=item['number'], stage='claimed', branch=None, worktree=None,
                                        commit=None, updated_at=item.get('updated_at'))
                self._transition(state)
                if not self.status()['enabled']: raise InstallError('stop requested; retain saved task for resume')
                return {'status': 'claimed', 'issue': item, 'checkpoint': state['current']}
            state = self._release(state)
            return {'status': 'empty', 'queue': state}

    def guard(self):
        with self._locked():
            state = self.status()
            self._active(state)
            if not state['current']: raise InstallError('no current queue issue')
            return state

    def checkpoint(self, stage, branch=None, worktree=None, commit=None):
        if stage not in STAGES: raise InstallError('unknown queue stage')
        if commit is not None and not re.fullmatch('[0-9a-f]{40}', commit): raise InstallError('full commit SHA required')
        for value in (branch, worktree):
            if value is not None and (not value or not value.isprintable() or len(value) > 1000):
                raise InstallError('invalid checkpoint locator')
        with self._locked():
            state = self.status()
            if not state['current']: raise InstallError('no current queue issue')
            self._owner(state)
            # Safe bookkeeping remains available after stop, without external actions.
            state['current']['stage'] = stage
            for name, value in (('branch', branch), ('worktree', worktree), ('commit', commit)):
                if value is not None: state['current'][name] = value
            self._save(state)
            return state

    def block(self, reason):
        if reason not in REASONS: raise InstallError('unknown blocking reason')
        with self._locked():
            state = self.status(); self._active(state)
            if not state['current']: raise InstallError('no current queue issue')
            item = self.tracker.issue(state['current']['number'])
            self._active(state)
            if 'ai-blocked' not in labels(item):
                raise InstallError('record reason and ai-blocked on the remote issue before skipping it')
            state['blocked'][str(item['number'])] = dict(state['current'], reason=reason)
            state['current'] = None
            self._transition(state)
            return state

    def retry(self, number):
        if type(number) is not int or number <= 0: raise InstallError('positive issue number required')
        with self._locked():
            state = self.status(); self._active(state)
            if state['current']: raise InstallError('finish or pause the current issue first')
            if str(number) not in state['blocked'] and number not in state['completed']:
                raise InstallError('issue is not a previously blocked or completed queue task')
            item = self.tracker.issue(number)
            self._active(state)
            if not eligible(item): raise InstallError('restore open ai-ready and clear blocking/assignment before retry')
            state['current'] = state['blocked'].pop(str(number), dict(number=number, stage='claimed',
                                     branch=None, worktree=None, commit=None, updated_at=item.get('updated_at')))
            state['current'].pop('reason', None)
            if number in state['completed']: state['completed'].remove(number)
            self._transition(state)
            return state

    def finish(self, commit, evidence):
        if not re.fullmatch('[0-9a-f]{40}', commit or ''): raise InstallError('full merge commit required')
        if not evidence or not evidence.isprintable() or len(evidence) > 1000: raise InstallError('evidence locator required')
        with self._locked():
            state = self.status(); self._active(state)
            if not state['current']: raise InstallError('no current queue issue')
            number = state['current']['number']
            Delivery(self.root, self.tracker.repository, self.branch).check(number, commit, self.tracker, self.lease)
            self._active(state)
            state['completed'].append(number)
            state['last_completion'] = dict(number=number, commit=commit, evidence=evidence)
            state['current'] = None
            self._transition(state)
            return state


DELIVERY_DIRECTORY = '.local/agent/delivery'
DELIVERY_STEPS = ('accepted', 'integration_verified', 'remote_synced', 'environment_restored', 'issue_updated')


class Delivery:
    """Local evidence checkpoints plus live completion checks, shared by single issues and queues.

    Checkpoints are Agent assertions, not test execution or external write authorization.
    Only check() reads the remote; it never pushes, comments, closes issues or starts services.
    """
    def __init__(self, root, repository, branch):
        self.root, self.repository, self.branch = Path(root), repository, branch

    def _path(self, number):
        if type(number) is not int or number <= 0:
            raise InstallError('positive issue number required')
        return DELIVERY_DIRECTORY + '/' + str(number) + '.json'

    @contextmanager
    def _locked(self):
        path = safe_path(self.root, DELIVERY_DIRECTORY + '/write.lock')
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise InstallError('another delivery command is running') from exc
            try: yield
            finally: fcntl.flock(handle, fcntl.LOCK_UN)

    def status(self, number):
        raw = read(self.root, self._path(number))
        if raw is None:
            return {'status': 'unrecorded', 'issue': number, 'record': None, 'missing': list(DELIVERY_STEPS)}
        try:
            value = json.loads(raw)
            if (not isinstance(value, dict) or value.get('version') != 1
                    or value.get('issue') != number
                    or value.get('repository') != self.repository
                    or value.get('integration_branch') != self.branch
                    or not isinstance(value.get('commit'), str)
                    or not re.fullmatch('[0-9a-f]{40}', value['commit'])
                    or not isinstance(value.get('steps'), dict)
                    or set(value['steps']) - set(DELIVERY_STEPS)
                    or any(not isinstance(v, str) or not v.strip() or not v.isprintable() or len(v) > 1000
                           for v in value['steps'].values())):
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise InstallError('invalid delivery record or repository/branch binding; preserve it for recovery') from None
        return {'status': 'recorded', 'issue': number, 'record': value,
                'missing': [step for step in DELIVERY_STEPS if step not in value['steps']],
                'requires_live_check': True}

    def _save(self, number, value):
        atomic_write(self.root, self._path(number), json_bytes(value), 0o600)

    def record(self, number, commit, stage, evidence):
        self._path(number)
        if not isinstance(commit, str) or not re.fullmatch('[0-9a-f]{40}', commit):
            raise InstallError('full delivery commit required')
        if stage not in (*DELIVERY_STEPS, 'waiting_user'):
            raise InstallError('unknown delivery stage')
        if not isinstance(evidence, str) or not evidence.strip() or not evidence.isprintable() or len(evidence) > 1000:
            raise InstallError('evidence locator required; never store credentials or issue bodies')
        with self._locked():
            old = self.status(number)['record']
            if old is None or old['commit'] != commit:
                if old:
                    atomic_write(self.root, DELIVERY_DIRECTORY + '/archive/' + str(number) + '-' + old['commit'] + '.json',
                                 json_bytes(old), 0o600)
                value = dict(version=1, repository=self.repository, integration_branch=self.branch,
                             issue=number, commit=commit, steps={}, waiting=None, last_verified=None)
            else:
                value = old
            if stage == 'waiting_user':
                value.update(steps={}, waiting=evidence, last_verified=None)
            elif value['steps'].get(stage) != evidence:
                # New earlier evidence invalidates downstream claims; identical retries are no-ops.
                index = DELIVERY_STEPS.index(stage)
                value['steps'] = {k: v for k, v in value['steps'].items() if DELIVERY_STEPS.index(k) < index}
                value['steps'][stage] = evidence
                value.update(waiting=None, last_verified=None)
            self._save(number, value)
            return self.status(number)

    def check(self, number, commit, tracker, lease):
        with self._locked():
            current = self.status(number)
            value = current['record']
            if value is None:
                raise InstallError('missing delivery record; reconstruct evidence before finishing')
            value['last_verified'] = None
            self._save(number, value)
            if value['commit'] != commit:
                raise InstallError('delivery commit changed; revalidate and record final version')
            if current['missing']:
                raise InstallError('missing delivery evidence: ' + ', '.join(current['missing']))
            if tracker.repository != self.repository:
                raise InstallError('delivery tracker repository mismatch')
            if not lease.contains(commit, self.branch):
                raise InstallError('delivery commit is not reachable from remote integration branch')
            item = tracker.issue(number)
            if item.get('number') != number or item.get('state') != 'closed' or item.get('pull_request') is not None:
                raise InstallError('remote issue must be closed and read back before completing delivery')
            # A snapshot is never a permanent guarantee: later calls always re-read remote state.
            value['last_verified'] = datetime.now().astimezone().isoformat()
            self._save(number, value)
            return {'status': 'verified', 'issue': number, 'repository': self.repository,
                    'integration_branch': self.branch, 'commit': commit, 'issue_state': 'closed',
                    'checked_at': value['last_verified']}


def validate_delivery_storage(root, delivery, number, next_commit=None):
    """Check every actual write target, not a representative filename."""
    path = delivery._path(number)
    if git(root, 'ls-files', '--', DELIVERY_DIRECTORY):
        raise InstallError('delivery records must not be Git-tracked')
    paths = [path, DELIVERY_DIRECTORY + '/write.lock']
    old = delivery.status(number)['record']
    if old and next_commit is not None and old['commit'] != next_commit:
        paths.append(DELIVERY_DIRECTORY + '/archive/' + str(number) + '-' + old['commit'] + '.json')
    for target in paths:
        safe_path(root, target)
        try:
            git(root, 'check-ignore', '--quiet', '--', target)
        except InstallError:
            raise InstallError('delivery state, lock and archive targets must be Git-ignored') from None


def validate_remote(root, repository):
    from .issue_tracker import canonical_repository
    for flags in (('--all',), ('--push', '--all')):
        urls = git(root, 'remote', 'get-url', *flags, 'origin').splitlines()
        if len(urls) != 1 or canonical_repository(urls[0]) != repository:
            raise InstallError('origin fetch/push URL must match the configured issue repository')


def dispatch(root, args):
    """CLI boundary: resolve shared root, validate binding, then call a small state transition."""
    root = main_project(root)
    queue = Queue(root, owner=args.owner)
    delivery_action = args.action.startswith('delivery-')
    action = args.action.split('-', 1)[1]
    if action == 'status' and not delivery_action: return queue.status()
    if action == 'stop':
        # Even malformed tracker config cannot prevent the local stop latch.
        return queue.stop()
    if action == 'checkpoint':
        return queue.checkpoint(args.stage, args.branch, args.worktree, args.commit)
    from .issue_tracker import Tracker, canonical_repository
    try:
        config = json.loads(read(root, 'docs/agents/project.json') or b'{}')
        tracker = config['project']['tracker']
        repository = tracker['repository']
        if not isinstance(repository, str) or not repository.startswith('https://'):
            raise ValueError()
        repository = canonical_repository(repository)
        branch = config['project']['integration_branch']
        if not isinstance(branch, str) or branch.startswith('-'): raise ValueError()
        git(root, 'check-ref-format', '--branch', branch)
        if tracker['kind'] not in ('gitea', 'github'): raise ValueError()
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise InstallError('valid tracker repository and integration branch configuration required') from None
    validate_remote(root, repository)
    if delivery_action:
        delivery = Delivery(root, repository, branch)
        if action == 'status':
            if args.issue is not None:
                return delivery.status(args.issue)
            safe_path(root, DELIVERY_DIRECTORY + '/write.lock')
            numbers = sorted(int(p.stem) for p in (root / DELIVERY_DIRECTORY).glob('*.json') if p.stem.isdigit())
            return {'status': 'inventory', 'tasks': [delivery.status(n) for n in numbers]}
        validate_delivery_storage(root, delivery, args.issue, args.commit if action == 'record' else None)
        if action == 'record':
            return delivery.record(args.issue, args.commit, args.stage, args.evidence)
        # A queue task must use its guarded finish operation; standalone checking is not a queue bypass.
        current = queue.status().get('current')
        if current and current.get('number') == args.issue:
            raise InstallError('current queue issue must use queue-finish with its owner')
    permissions = config.get('permissions', {})
    if action == 'start' and not args.apply:
        return {'status': 'preview', 'project': str(root), 'repository': repository,
                'integration_branch': branch, 'label': 'ai-ready', 'lock_ref': REF,
                'effect': 'creates/deletes an orphan control branch; may trigger branch CI; no Tag or deployment',
                'needs': ['explicit user start', 'Git write login', 'issue API access',
                          'recorded push_task_branch and write_issue permissions']}
    if action == 'start':
        if any(permissions.get(key) is not True for key in ('push_task_branch', 'write_issue')):
            raise InstallError('record existing queue permissions for push_task_branch and write_issue before starting')
        git(root, 'check-ignore', '.local/agent/queue/state.json')
        if git(root, 'ls-files', '--', '.local/agent/queue'):
            raise InstallError('queue state must not be Git-tracked')
    credentials = config.get('environment', {}).get('secrets')
    if credentials in (None, '', '.local/secrets/access.json', 'external-controlled-storage'):
        credentials = None
    if not delivery_action and action != 'start' and not queue.status()['enabled']:
        raise InstallError('queue is stopped')
    queue.tracker = Tracker(tracker['kind'], repository, root, credentials_path=credentials)
    queue.lease = GitLease(root, repository=repository)
    queue.branch = branch
    if delivery_action:
        return delivery.check(args.issue, args.commit, queue.tracker, queue.lease)
    if action == 'start': return queue.start()
    if action == 'next': return queue.next()
    if action == 'guard': return queue.guard()
    if action == 'block': return queue.block(args.reason)
    if action == 'retry': return queue.retry(args.issue)
    if action == 'finish':
        current = queue.status().get('current')
        if current:
            validate_delivery_storage(root, Delivery(root, repository, branch), current['number'])
        return queue.finish(args.commit, args.evidence)
    raise InstallError('unknown queue action')
