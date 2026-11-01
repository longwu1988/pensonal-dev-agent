"""Local issue-scoped authorization; evidence records a supplied user decision, not identity proof."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from .issue_tracker import canonical_repository
from .transaction import InstallError, atomic_write, json_bytes, read, safe_path

CAPABILITIES = ('manage_claims', 'update_issue_labels', 'write_issue', 'close_issue',
                'push_task_branch', 'create_pr', 'merge', 'push_tag', 'deploy')
DIRECTORY = '.local/agent/permissions'
FIELDS = {'version', 'repository', 'integration_branch', 'owner', 'issue',
          'allow', 'deny', 'evidence', 'revoked'}


def _git(root, *args):
    """Only local Git metadata checks; never print command output or credentials."""
    try:
        result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        raise InstallError('cannot verify local permission storage') from None
    if result.returncode:
        raise InstallError('permission storage must be ignored and bindings must be valid')
    return result.stdout


def _owner(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise InstallError('valid conversation owner required')


def _issue(value):
    if type(value) is not int or value <= 0:
        raise InstallError('positive issue number required for scoped permission')


def _evidence(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 1000 or not value.strip()
            or not value.isprintable()):
        raise InstallError('single-line user authorization evidence required (1-1000 characters)')


def _capabilities(value):
    if (not isinstance(value, list) or any(not isinstance(item, str) or item not in CAPABILITIES
                                          for item in value) or len(value) != len(set(value))):
        raise InstallError('permission lists require distinct supported capabilities')


class Permissions:
    def __init__(self, root, repository, branch, owner):
        self.root = Path(root)
        _owner(owner)
        self.repository = canonical_repository(repository)
        self._branch(branch)
        self.branch, self.owner = branch, owner
        self.path = DIRECTORY + '/' + owner + '.json'
        self.lock = DIRECTORY + '/' + owner + '.lock'

    def _branch(self, value):
        if not isinstance(value, str) or not value or value.startswith('-'):
            raise InstallError('valid integration branch required')
        _git(self.root, 'check-ref-format', '--branch', value)

    def _protected(self):
        for name in (self.path, self.lock):
            safe_path(self.root, name)
            if _git(self.root, 'ls-files', '--', name):
                raise InstallError('permission record and lock must not be tracked')
            _git(self.root, 'check-ignore', '--quiet', '--', name)

    def _validate(self, value):
        if (not isinstance(value, dict) or set(value) != FIELDS
                or type(value.get('version')) is not int or value['version'] != 1
                or type(value.get('revoked')) is not bool):
            raise InstallError('invalid permission record; preserve it for recovery')
        _owner(value['owner']); _issue(value['issue']); _evidence(value['evidence'])
        _capabilities(value['allow']); _capabilities(value['deny'])
        self._branch(value['integration_branch'])
        if (canonical_repository(value['repository']) != value['repository']
                or set(value['allow']).intersection(value['deny'])):
            raise InstallError('invalid permission binding or overlapping allow/deny')
        if (value['repository'], value['integration_branch'], value['owner']) != (
                self.repository, self.branch, self.owner):
            raise InstallError('permission repository, integration branch or owner does not match')
        return value

    def status(self):
        # Check the lock as well even on reads: an unsafe target never silently authorizes.
        safe_path(self.root, self.lock)
        try:
            raw = read(self.root, self.path)
            if raw is None:
                return None
            self._protected()
            return self._validate(json.loads(raw))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise InstallError('invalid or unreadable permission record; preserve it for recovery') from None

    def _same_scope(self, issue):
        old = self.status()
        if old and old['issue'] != issue:
            raise InstallError('owner already bound to another issue; use a different owner or explicit migration')
        return old

    @contextmanager
    def _locked(self):
        self._protected()
        path = safe_path(self.root, self.lock)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a+b') as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise InstallError('permission lock must be a regular file')
                os.fchmod(handle.fileno(), 0o600)
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise InstallError('another permission command is running for this owner') from None
                try:
                    self._protected()
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            raise InstallError('cannot safely write local permissions') from None

    def _change(self, issue, evidence, allow, deny, revoked, apply):
        _issue(issue); _evidence(evidence)
        _capabilities(allow); _capabilities(deny)
        if type(apply) is not bool:
            raise InstallError('apply must be a boolean')
        value = self._validate(dict(version=1, repository=self.repository, integration_branch=self.branch,
                                    owner=self.owner, issue=issue, allow=list(allow), deny=list(deny),
                                    evidence=evidence, revoked=revoked))
        self._protected()
        old = self._same_scope(issue)
        if revoked and old:
            value.update(allow=old['allow'], deny=old['deny'])
        if not apply:
            return {'status': 'preview', 'record': value}
        with self._locked():
            old = self._same_scope(issue)
            if revoked and old:
                value.update(allow=old['allow'], deny=old['deny'])
            atomic_write(self.root, self.path, json_bytes(value), 0o600)
        return value

    def grant(self, issue, allow, deny, evidence, apply=False):
        return self._change(issue, evidence, allow, deny, False, apply)

    def revoke(self, issue, evidence, apply=False):
        # A tombstone is retained even without a previous local grant, blocking fallback.
        return self._change(issue, evidence, [], [], True, apply)

    def require(self, config_permissions, issue, capabilities):
        if not isinstance(config_permissions, dict):
            raise InstallError('project permissions must be a dictionary')
        effective = {}
        for name in CAPABILITIES:
            value = config_permissions.get(name, False)
            if type(value) is not bool:
                raise InstallError('project permission values must be boolean')
            effective[name] = value
        if issue is not None:
            _issue(issue)
        if isinstance(capabilities, (str, bytes)):
            raise InstallError('required capabilities must be an iterable of names')
        try:
            requested = list(capabilities)
        except TypeError:
            raise InstallError('required capabilities must be an iterable of names') from None
        _capabilities(requested)
        record = self.status()
        if record:
            if record['revoked'] or record['issue'] != issue:
                raise InstallError('scoped permission is revoked or belongs to another issue; no project fallback')
            effective.update((name, True) for name in record['allow'])
            effective.update((name, False) for name in record['deny'])
        if any(not effective[name] for name in requested):
            raise InstallError('permission denied: ' + ', '.join(name for name in requested if not effective[name]))
        return effective
