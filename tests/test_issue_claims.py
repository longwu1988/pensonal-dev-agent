import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pda.issue_claims import Claims, ClaimConflict


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        self.stores = []
        for name in ('a', 'b'):
            path = self.root / name
            subprocess.run(['git', 'clone', str(self.remote), str(path)], check=True, capture_output=True)
            self.stores.append(Claims(path))

    def test_only_one_atomic_winner_and_owner_token_required(self):
        for store in self.stores: store.ensure()
        barrier = threading.Barrier(2); results = []; failures = []
        def claim(i):
            try:
                barrier.wait()
                results.append(self.stores[i].claim(1, 'worker-' + str(i), 'token-' + str(i), 'main'))
            except Exception as exc: failures.append(exc)
        threads = [threading.Thread(target=claim, args=(i,)) for i in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(failures, [])
        winner = next(x for x in results if x)
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertIsNone(self.stores[0].claim(1, winner['owner'], 'other-token', 'main'))
        self.assertEqual(self.stores[1].claim(1, winner['owner'], winner['token'], 'main')['token'], winner['token'])

    def test_done_record_and_stale_update_cannot_be_claimed(self):
        store = self.stores[0]; store.ensure()
        first = store.claim(1, 'a', 't', 'main')
        done = store.update(first, stage='done', commit='a'*40)
        with self.assertRaises(ClaimConflict): store.update(first, stage='testing')
        self.assertIsNone(self.stores[1].claim(1, 'b', 'x', 'main'))
        self.assertEqual(store.get('issues/1')['stage'], 'done')
        self.assertEqual(done['commit'], 'a'*40)

    def test_resource_is_exclusive_and_release_requires_token(self):
        a, b = self.stores
        a.ensure(); b.ensure()
        self.assertTrue(a.acquire_resource('integration:main', 'a', 't'))
        self.assertFalse(b.acquire_resource('integration:main', 'b', 'x'))
        with self.assertRaises(ClaimConflict): b.release_resource('integration:main', 'b', 'x')
        a.release_resource('integration:main', 'a', 't')
        self.assertTrue(b.acquire_resource('integration:main', 'b', 'x'))

    def test_legacy_lock_is_not_overwritten(self):
        from pda.issue_queue import GitLease
        lease = GitLease(self.stores[0].root)
        sha = lease.prepare('legacy'); lease.acquire(sha)
        with self.assertRaises(ClaimConflict): self.stores[1].ensure()
        self.assertEqual(lease.current(), sha)

    def test_new_gate_blocks_old_executor(self):
        from pda.issue_queue import GitLease
        self.stores[0].ensure()
        lease = GitLease(self.stores[1].root)
        with self.assertRaises(Exception): lease.acquire(lease.prepare('legacy'))
        self.stores[0].ensure()

    def test_contains_uses_specific_remote_commit_not_shared_fetch_head(self):
        from pda.issue_queue import GitLease
        from unittest.mock import patch
        target='a'*40
        def run(root,*args,**kwargs):
            if args[0]=='ls-remote': return target+'\trefs/heads/main'
            if args[0]=='merge-base':
                self.assertEqual(args[-1],target)
            if args[0]=='fetch': self.assertIn('--no-write-fetch-head',args)
            return ''
        with patch('pda.issue_queue.git',side_effect=run):
            self.assertTrue(GitLease(self.root).contains('b'*40,'main'))


    def assert_revoked_after_read_blocks_push(self, operation):
        from unittest.mock import patch
        from pda import issue_claims
        from pda.transaction import InstallError
        store = self.stores[0]
        actual_git = issue_claims.git
        revoked = False
        pushes = []
        def authorize():
            if revoked: raise InstallError('authorization revoked')
        store.before_write = authorize
        def run(root, *args, **kwargs):
            nonlocal revoked
            if args[0] == 'push': pushes.append(args)
            result = actual_git(root, *args, **kwargs)
            if args[0] in ('ls-remote', 'show'): revoked = True
            return result
        before = actual_git(store.root, 'ls-remote', '--refs', 'origin')
        with patch.object(issue_claims, 'git', side_effect=run):
            with self.assertRaisesRegex(InstallError, 'authorization revoked'): operation(store)
        self.assertEqual(pushes, [])
        self.assertEqual(actual_git(store.root, 'ls-remote', '--refs', 'origin'), before)

    def test_revocation_during_gate_read_prevents_ensure_push(self):
        self.assert_revoked_after_read_blocks_push(lambda store: store.ensure())

    def test_revocation_during_claim_read_prevents_claim_push(self):
        self.assert_revoked_after_read_blocks_push(lambda store: store.claim(6, 'A', 'token', 'main'))

    def test_revocation_after_claim_read_prevents_update_push(self):
        self.stores[0].claim(6, 'A', 'token', 'main')
        self.assert_revoked_after_read_blocks_push(
            lambda store: store.update(store.get('issues/6'), stage='testing'))

    def test_revocation_during_resource_read_prevents_acquire_push(self):
        self.assert_revoked_after_read_blocks_push(
            lambda store: store.acquire_resource('integration:main', 'A', 'token'))

    def test_revocation_during_resource_read_prevents_release_push(self):
        self.stores[0].acquire_resource('integration:main', 'A', 'token')
        self.assert_revoked_after_read_blocks_push(
            lambda store: store.release_resource('integration:main', 'A', 'token'))

    def test_reads_and_idempotent_operations_do_not_call_write_guard(self):
        store = self.stores[0]
        store.ensure()
        store.claim(6, 'A', 'token', 'main')
        store.acquire_resource('integration:main', 'A', 'token')
        def deny(): self.fail('read-only operation called write guard')
        store.before_write = deny
        self.assertIsNotNone(store.get('issues/6'))
        self.assertTrue(store.resource_owned('integration:main', 'A', 'token'))
        store.ensure()
        self.assertIsNotNone(store.claim(6, 'A', 'token', 'main'))
        self.assertTrue(store.acquire_resource('integration:main', 'A', 'token'))
        store.release_resource('unowned', 'A', 'token')

    def test_constructor_accepts_optional_local_write_guard(self):
        from pda.transaction import InstallError
        def deny(): raise InstallError('authorization revoked')
        store = Claims(self.stores[0].root, before_write=deny)
        self.assertIsNone(store.get('issues/6'))
        with self.assertRaisesRegex(InstallError, 'authorization revoked'): store.ensure()
