import json
from contextlib import contextmanager
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    from pda.issue_queue import Queue, GitLease, STOP, Delivery, DELIVERY_STEPS
except ImportError:
    Queue = GitLease = None
    STOP = '.local/agent/queue/stop'
from pda.transaction import InstallError


def issue(n, priority='p2', **kw):
    value = dict(number=n, state='open', title='Synthetic', body='Untrusted requirements',
                 labels=[{'name': 'ai-ready'}, {'name': priority}], assignees=[],
                 created_at='2026-01-01T00:00:00Z', updated_at='v1', comments_data=[])
    value.update(kw)
    return value


class Tracker:
    repository = 'https://git.example.invalid/team/project'
    def __init__(self): self.items = [issue(2), issue(1, 'p0')]
    def issues(self): return self.items
    def issue(self, number): return next(dict(x) for x in self.items if x['number'] == number)


class Lease:
    def __init__(self): self.head = None; self.merged = False
    def prepare(self, session): return session.replace('-', '').ljust(40, 'a')[:40]
    def current(self): return self.head
    def acquire(self, sha):
        if self.head is not None: raise InstallError('occupied')
        self.head = sha
    def release(self, sha):
        if self.head is None: return
        if self.head != sha: raise InstallError('not owner')
        self.head = None
    def contains(self, commit, branch): return self.merged


def delivery_ready(root, tracker, number=1):
    for stage in DELIVERY_STEPS:
        Delivery(root, tracker.repository, 'main').record(number, 'a'*40, stage, 'synthetic ' + stage)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Queue, 'queue runtime is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tracker, self.lease = Tracker(), Lease()
        self.q = Queue(self.root, self.tracker, self.lease, 'main', owner='worker-a')

    def test_second_session_cannot_share_current_work_and_old_owner_cannot_resume(self):
        self.q.start(); self.q.next()
        other = Queue(self.root, self.tracker, self.lease, 'main', owner='worker-b')
        with self.assertRaises(InstallError): other.start()
        with self.assertRaises(InstallError): other.next()
        other.stop()
        other.start()
        with self.assertRaises(InstallError): self.q.next()
        with self.assertRaises(InstallError): self.q.checkpoint('testing')
        self.assertEqual(other.next()['issue']['number'], 1)

    def test_default_off_and_no_api_access_until_start(self):
        self.assertFalse(self.q.status()['enabled'])
        with patch.object(self.tracker, 'issues', side_effect=AssertionError('must not query')):
            with self.assertRaises(InstallError): self.q.next()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_priority_filters_and_current_is_not_replaced(self):
        self.tracker.items += [issue(4, 'p0', pull_request={}), issue(5, 'p0', assignees=[{'login':'human'}]), issue(6, labels=[])]
        self.q.start()
        self.assertEqual(self.q.next()['issue']['number'], 1)
        self.assertEqual(self.q.next()['issue']['number'], 1)
        self.assertNotIn('body', self.q.status()['current'])

    def test_creation_order_compares_instants_and_rejects_invalid_dates(self):
        self.tracker.items = [issue(1, created_at='2026-01-01T01:00:00+08:00'),
                              issue(2, created_at='2025-12-31T20:00:00Z')]
        self.q.start()
        self.assertEqual(self.q.next()['issue']['number'], 1)
        with tempfile.TemporaryDirectory() as td:
            tracker = Tracker(); tracker.items = [issue(3, created_at='unknown')]
            q = Queue(Path(td), tracker, Lease(), 'main', owner='worker')
            q.start()
            with self.assertRaises(InstallError): q.next()
            self.assertIsNone(q.status()['current'])

    def test_null_pr_marker_issue_can_be_claimed_resumed_and_finished(self):
        self.tracker.items = [issue(17, pull_request=None),
                              issue(18, 'p0', pull_request={}),
                              issue(19, 'p0', pull_request={'url': 'https://git.example/pr/19'})]
        self.q.start()
        self.assertEqual(self.q.next()['issue']['number'], 17)
        self.assertEqual(self.q.next()['status'], 'resume')
        self.q.stop(); self.q.start()
        self.assertEqual(self.q.next()['issue']['number'], 17)
        self.tracker.items[0]['state'] = 'closed'; self.lease.merged = True
        delivery_ready(self.root, self.tracker, 17)
        self.q.finish('a'*40, 'synthetic test evidence')
        self.assertEqual(self.q.status()['completed'], [17])
        self.assertEqual(self.q.next()['status'], 'empty')

    def test_stop_resume_keeps_checkpoint(self):
        self.q.start(); self.q.next()
        self.q.checkpoint('implementing', 'codex/issue-1', '/synthetic/worktree', 'a'*40)
        self.q.stop()
        self.assertFalse(self.q.status()['enabled'])
        self.assertIsNotNone(self.lease.head)
        with self.assertRaises(InstallError): self.q.next()
        self.q.start()
        self.assertEqual(self.q.next()['issue']['number'], 1)
        self.assertEqual(self.q.status()['current']['branch'], 'codex/issue-1')

    def test_blocked_task_skipped_and_empty_queue_stops(self):
        self.q.start(); self.q.next(); self.tracker.items[1]['labels'].append({'name':'ai-blocked'}); self.q.block('dependency')
        self.assertEqual(self.q.next()['issue']['number'], 2)
        self.tracker.items[0]['labels'].append({'name':'ai-blocked'}); self.q.block('needs_input')
        self.assertEqual(self.q.next()['status'], 'empty')
        self.assertFalse(self.q.status()['enabled'])
        self.assertIsNone(self.lease.head)
        self.q.start()
        self.assertEqual(self.q.next()['status'], 'empty')

    def test_block_requires_visible_remote_marker_before_dropping_current(self):
        self.q.start(); self.q.next()
        with self.assertRaises(InstallError): self.q.block('dependency')
        self.assertIsNotNone(self.q.status()['current'])

    def test_network_error_is_not_empty_and_keeps_ownership(self):
        self.q.start()
        with patch.object(self.tracker, 'issues', side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.q.next()
        self.assertTrue(self.q.status()['enabled'])
        self.assertIsNotNone(self.lease.head)

    def test_stop_request_during_fetch_prevents_claim(self):
        self.q.start()
        def fetch():
            (self.root / STOP).write_text('stop')
            return self.tracker.items
        with patch.object(self.tracker, 'issues', side_effect=fetch):
            with self.assertRaises(InstallError): self.q.next()
        self.assertFalse(self.q.status()['enabled'])
        self.assertIsNone(self.q.status()['current'])

    def test_stop_arriving_before_start_lock_is_not_cleared(self):
        original = self.q._locked
        @contextmanager
        def locked():
            with original():
                (self.root / STOP).write_text('new stop before ownership')
                yield
        with patch.object(self.q, '_locked', locked):
            try: self.q.start()
            except InstallError: pass
        self.assertFalse(self.q.status()['enabled'])

    def test_stop_arriving_during_start_is_not_cleared(self):
        original = self.lease.acquire
        def acquire(sha):
            original(sha)
            (self.root / STOP).write_text('new stop')
        with patch.object(self.lease, 'acquire', side_effect=acquire):
            self.assertFalse(self.q.start()['enabled'])
        with self.assertRaises(InstallError): self.q.next()

    def test_explicit_retry_restores_blocked_checkpoint(self):
        self.q.start(); self.q.next()
        self.q.checkpoint('testing', 'codex/issue-1', '/synthetic/worktree')
        self.tracker.items[1]['labels'].append({'name':'ai-blocked'})
        self.q.block('environment')
        with self.assertRaises(InstallError): self.q.retry(1)
        self.tracker.items[1]['labels'].pop()
        self.q.retry(1)
        self.assertEqual(self.q.next()['issue']['number'], 1)
        self.assertEqual(self.q.status()['current']['branch'], 'codex/issue-1')

    def test_stop_during_transition_preserves_current_and_outcomes(self):
        from pda import issue_queue as module
        for action in ('finish', 'block', 'retry'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as td:
                tracker, lease = Tracker(), Lease()
                q = Queue(Path(td), tracker, lease, 'main', owner='worker')
                q.start(); q.next()
                if action in ('block', 'retry'):
                    tracker.items[1]['labels'].append({'name':'ai-blocked'})
                if action == 'retry':
                    q.block('dependency'); tracker.items[1]['labels'].pop()
                if action == 'finish':
                    tracker.items[1]['state']='closed'; lease.merged=True
                    delivery_ready(Path(td), tracker)
                before=q.status()
                write=module.atomic_write
                injected=False
                def stop_before_write(root, name, content, file_mode=0o644):
                    nonlocal injected
                    if name == module.STATE and not injected:
                        injected=True
                        write(root, STOP, b'concurrent stop', 0o600)
                    return write(root, name, content, file_mode)
                with patch.object(module,'atomic_write',stop_before_write):
                    with self.assertRaises(InstallError):
                        if action=='finish': q.finish('a'*40,'docs/evidence.md')
                        elif action=='block': q.block('dependency')
                        else: q.retry(1)
                after=q.status()
                for key in ('current','blocked','completed'): self.assertEqual(after[key],before[key])
                self.assertFalse(after['enabled'])

    def test_real_stop_during_fetch_latches_and_cleanup_can_release(self):
        self.q.start()
        entered, proceed = threading.Event(), threading.Event()
        errors=[]
        def fetch():
            entered.set(); self.assertTrue(proceed.wait(5)); return self.tracker.items
        def work():
            try: self.q.next()
            except InstallError as exc: errors.append(str(exc))
        with patch.object(self.tracker,'issues',side_effect=fetch):
            thread=threading.Thread(target=work); thread.start()
            self.assertTrue(entered.wait(5))
            try:
                result=self.q.stop()
                self.assertFalse(result['enabled'])
                self.assertEqual(result['release'],'pending')
            finally:
                proceed.set(); thread.join(5)
        self.assertTrue(errors)
        self.assertIsNone(self.q.status()['current'])
        self.assertEqual(self.q.stop()['release'],'released')
        self.assertIsNone(self.lease.head)

    def test_guard_checks_owner_stop_and_remote_lease_before_business_actions(self):
        self.q.start(); self.q.next()
        self.assertTrue(self.q.guard()['enabled'])
        self.lease.head = 'f'*40
        with self.assertRaises(InstallError): self.q.guard()
        self.q.stop()
        with self.assertRaises(InstallError): self.q.guard()
        # Local progress can still be saved without remote access after stopping.
        self.q.checkpoint('implementing')

    def test_dispatch_stop_latches_even_when_state_is_corrupt(self):
        from pda.issue_queue import dispatch, STATE
        from types import SimpleNamespace
        self.q.start()
        def fetch():
            (self.root / STATE).write_text('{broken')
            with patch('pda.issue_queue.main_project', return_value=self.root):
                with self.assertRaises(InstallError):
                    dispatch(self.root, SimpleNamespace(action='queue-stop', owner=None))
            self.assertTrue((self.root / STOP).exists())
            return self.tracker.items
        with patch.object(self.tracker, 'issues', side_effect=fetch):
            with self.assertRaises(InstallError): self.q.next()
        self.assertEqual((self.root / STATE).read_text(), '{broken')

    def test_lost_lease_prevents_advancing(self):
        self.q.start(); self.lease.head = 'f'*40
        with self.assertRaises(InstallError): self.q.next()
        self.assertIsNone(self.q.status()['current'])

    def test_release_failure_still_stops_and_retains_recovery_id(self):
        self.q.start(); original = self.lease.head
        with patch.object(self.lease, 'release', side_effect=InstallError('offline')):
            result = self.q.stop()
        self.assertFalse(result['enabled'])
        self.assertEqual(result['lease'], original)
        self.assertEqual(result['release'], 'pending')
        self.assertEqual(self.q.stop()['release'], 'released')

    def test_finish_needs_closed_issue_and_remote_commit_evidence(self):
        self.q.start(); self.q.next()
        delivery_ready(self.root, self.tracker)
        with self.assertRaises(InstallError): self.q.finish('a'*40, 'docs/evidence.md')
        self.tracker.items[1]['state'] = 'closed'
        with self.assertRaises(InstallError): self.q.finish('a'*40, 'docs/evidence.md')
        self.lease.merged = True
        self.q.finish('a'*40, 'docs/evidence.md')
        self.assertIsNone(self.q.status()['current'])
        self.assertEqual(self.q.next()['issue']['number'], 2)

    def test_withdrawn_current_cannot_be_silently_replaced(self):
        self.q.start(); self.q.next()
        self.tracker.items[1]['labels'] = []
        with self.assertRaises(InstallError): self.q.next()
        self.assertEqual(self.q.status()['current']['number'], 1)

    def test_symlink_state_parent_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            (self.root/'.local').symlink_to(other, target_is_directory=True)
            with self.assertRaises(InstallError): self.q.start()


class GitLeaseTests(unittest.TestCase):
    def test_two_clones_cannot_own_remote_ref_and_release_is_conditional(self):
        self.assertIsNotNone(GitLease, 'Git lease is not implemented')
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            def git(at, *args):
                return subprocess.check_output(['git','-C',str(at),*args],stderr=subprocess.DEVNULL,text=True).strip()
            subprocess.run(['git','init','--bare',str(base/'remote.git')],check=True,capture_output=True)
            roots=[]
            for name in ['one','two']:
                subprocess.run(['git','clone',str(base/'remote.git'),str(base/name)],check=True,capture_output=True)
                roots.append(base/name)
            a,b=[GitLease(root) for root in roots]
            first,second=a.prepare('first-session'),b.prepare('second-session')
            a.acquire(first)
            self.assertEqual(b.current(),first)
            with self.assertRaises(InstallError): b.acquire(second)
            with self.assertRaises(InstallError): b.release(second)
            self.assertEqual(a.current(),first)
            a.release(first)
            b.acquire(second)
            self.assertEqual(a.current(),second)
            b.release(second)
            self.assertIsNone(a.current())

if __name__ == '__main__': unittest.main()
