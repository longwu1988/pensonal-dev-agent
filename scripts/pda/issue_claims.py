"""Remote per-issue ownership and exclusive resources, using Git ref compare-and-swap."""
import hashlib
import json
import re
from datetime import datetime, timezone

from .issue_queue import QueueConflict, git, validate_remote, REF
from .transaction import InstallError


class ClaimConflict(QueueConflict):
    pass


class Claims:
    def __init__(self, root, repository=None, before_write=None):
        self.root, self.repository = root, repository
        self.before_write = before_write

    def _ref(self, key):
        if key == 'gate': return REF
        if not re.fullmatch(r'(issues/[1-9][0-9]*|resources/[0-9a-f]{64})', key):
            raise InstallError('invalid claim key')
        return 'refs/heads/personal-dev/claims/' + key

    def _head(self, key):
        if self.repository: validate_remote(self.root, self.repository)
        ref = self._ref(key)
        raw = git(self.root, 'ls-remote', '--refs', 'origin', ref)
        if not raw: return None
        fields = raw.split()
        if len(fields) != 2 or fields[1] != ref or not re.fullmatch('[0-9a-f]{40}', fields[0]):
            raise InstallError('invalid remote claim ref')
        return fields[0]

    def get(self, key):
        sha = self._head(key)
        if sha is None: return None
        git(self.root, 'fetch', '--no-tags', '--no-write-fetch-head', 'origin', sha)
        try:
            size = int(git(self.root, 'cat-file', '-s', sha + ':claim.json'))
            if size > 65536: raise ValueError()
            value = json.loads(git(self.root, 'show', sha + ':claim.json'))
            if (not isinstance(value, dict) or value.get('version') != 1 or value.get('key') != key
                    or value.get('repository') != self.repository): raise ValueError()
        except (InstallError, ValueError, TypeError):
            raise ClaimConflict('unrecognized remote ownership; reconcile legacy work without deleting its ref') from None
        return dict(value, _sha=sha)

    def _put(self, key, value, expected=None):
        self._ref(key)
        if self.repository: validate_remote(self.root, self.repository)
        data = {k: v for k, v in value.items() if k != '_sha'}
        data.update(version=1, key=key, repository=self.repository)
        blob = git(self.root, 'hash-object', '-w', '--stdin', data=json.dumps(data, sort_keys=True))
        tree = git(self.root, 'mktree', data='100644 blob ' + blob + '\tclaim.json\n')
        parents = ('-p', expected) if expected else ()
        sha = git(self.root, 'commit-tree', tree, *parents, data='Personal dev ownership record\n')
        ref = self._ref(key)
        # A denied local guard is not a push failure and must not enter reconciliation.
        if self.before_write is not None: self.before_write()
        try:
            git(self.root, 'push', '--porcelain', '--force-with-lease=' + ref + ':' + (expected or ''),
                'origin', sha + ':' + ref)
        except InstallError:
            actual = self._head(key)
            if actual != sha:
                if actual != expected: raise ClaimConflict('claim changed concurrently; do not overwrite') from None
                raise
        if self._head(key) != sha: raise ClaimConflict('claim write not confirmed; reconcile before work')
        return dict(data, _sha=sha)

    def ensure(self):
        marker = {'purpose': 'personal-dev-claims-v1'}
        value = self.get('gate')
        if value is None:
            try: value = self._put('gate', marker)
            except ClaimConflict: value = self.get('gate')
        if not value or value.get('purpose') != marker['purpose']:
            raise ClaimConflict('legacy queue still owns repository; finish it before migration')

    def claim(self, number, owner, token, branch):
        if type(number) is not int or number <= 0: raise InstallError('positive issue number required')
        key = 'issues/' + str(number)
        value = self.get(key)
        if value:
            if (value.get('owner'), value.get('token')) == (owner, token) and value.get('stage') != 'done':
                return value
            return None
        try:
            return self._put(key, dict(number=number, owner=owner, token=token, integration_branch=branch,
                                      stage='claimed', branch=None, worktree=None, commit=None,
                                      updated_at=datetime.now(timezone.utc).isoformat()))
        except ClaimConflict:
            # Only a confirmed competing record is skippable; network errors propagate.
            if self.get(key) is not None: return None
            raise

    def update(self, record, **changes):
        value = dict(record, **changes, updated_at=datetime.now(timezone.utc).isoformat())
        return self._put(record['key'], value, record['_sha'])

    def _resource_key(self, resource):
        if not isinstance(resource, str) or not resource or len(resource) > 256 or not resource.isprintable():
            raise InstallError('valid shared resource name required')
        return 'resources/' + hashlib.sha256(resource.encode()).hexdigest()

    def acquire_resource(self, resource, owner, token):
        key = self._resource_key(resource)
        value = self.get(key)
        if value:
            return value.get('owner') == owner and value.get('token') == token
        try:
            self._put(key, dict(resource=resource, owner=owner, token=token))
            return True
        except ClaimConflict:
            if self.get(key) is not None: return False
            raise

    def resource_owned(self, resource, owner, token):
        value = self.get(self._resource_key(resource))
        return bool(value and value.get('owner') == owner and value.get('token') == token)

    def release_resource(self, resource, owner, token):
        key = self._resource_key(resource)
        value = self.get(key)
        if value is None: return
        if value.get('owner') != owner or value.get('token') != token:
            raise ClaimConflict('shared resource belongs to another claim')
        ref = self._ref(key)
        if self.before_write is not None: self.before_write()
        git(self.root, 'push', '--porcelain', '--force-with-lease=' + ref + ':' + value['_sha'], 'origin', ':' + ref)
        if self._head(key) is not None: raise ClaimConflict('resource release not confirmed')
