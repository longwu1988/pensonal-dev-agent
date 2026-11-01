"""Continuous authorization must survive empty queues, never a user stop."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from test_issue_queue import Queue, Tracker, Lease, issue
from pda.transaction import InstallError
try:
    from pda.issue_watch import Watch
except ImportError:
    Watch = None


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Watch, 'continuous issue watch is not implemented')
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.tracker, self.lease = Tracker(), Lease()
        self.q = Queue(self.root, self.tracker, self.lease, 'main')
        self.now = 1000
        self.watch = Watch(self.q, clock=lambda: self.now)

    def enable(self):
        state = self.watch.start('thread-a', 300)
        self.generation = state['generation']
        self.watch.bind(self.generation, 'schedule-a')

    def tick(self, **kw):
        return self.watch.tick(kw.get('generation', self.generation), kw.get('scheduler', 'schedule-a'), 'thread-a')

    def test_default_off_read_only_and_pending_cannot_run(self):
        self.assertEqual(self.watch.status()['status'], 'off')
        self.assertFalse((self.root / '.local').exists())
        state = self.watch.start('thread-a', 300)
        with self.assertRaises(InstallError): self.watch.tick(state['generation'], 'schedule-a', 'thread-a')
        self.assertIsNone(self.lease.head)

    def test_empty_then_future_issue_and_duplicate_tick(self):
        self.enable(); self.tracker.items = []
        self.assertEqual(self.tick()['status'], 'idle')
        self.assertIsNone(self.lease.head)
        self.assertEqual(self.watch.status()['status'], 'active')
        self.tracker.items = [issue(8, pull_request=None)]
        self.assertEqual(self.tick()['status'], 'not_due')
        self.now += 300
        self.assertEqual(self.tick()['issue']['number'], 8)
        self.assertEqual(self.tick()['status'], 'not_due')
        self.now += 300
        self.assertEqual(self.tick()['status'], 'resume')
        self.assertEqual(self.q.status()['current']['number'], 8)

    def test_stop_revokes_old_wake_even_after_manual_queue_start(self):
        self.enable(); self.tick(); self.q.stop()
        with self.assertRaises(InstallError): self.tick()
        self.q.start()
        with self.assertRaises(InstallError): self.tick()
        self.assertEqual(self.watch.status()['status'], 'stopped')

    def test_restart_rotates_generation_and_worker_identity(self):
        self.enable(); old = self.generation; self.tick(); owner = self.q.owner
        self.q.stop(); self.enable()
        self.assertNotEqual(old, self.generation)
        with self.assertRaises(InstallError): self.tick(generation=old)
        self.assertEqual(self.tick()['status'], 'resume')
        self.assertNotEqual(owner, self.q.owner)
        other = Queue(self.root, self.tracker, self.lease, 'main', owner=owner)
        with self.assertRaises(InstallError): other.guard()

    def test_binding_and_active_queue_cannot_be_hijacked(self):
        self.enable()
        with self.assertRaises(InstallError): self.watch.start('other', 300)
        with self.assertRaises(InstallError): self.tick(scheduler='other')
        with self.assertRaises(InstallError): self.watch.tick(self.generation, 'schedule-a', 'other-thread')
        self.q.branch = 'other'
        with self.assertRaises(InstallError): self.tick()
        self.assertIsNone(self.lease.head)
        self.assertEqual(self.watch.status()['status'], 'suspended')
        self.q.branch = 'main'
        with self.assertRaises(InstallError): self.tick()

    def test_waiting_for_user_never_claims_or_assumes_acceptance(self):
        self.enable(); self.tick(); self.q.checkpoint('waiting_user')
        self.now += 300
        with patch.object(self.tracker, 'issues', side_effect=AssertionError('no fetch')):
            self.assertEqual(self.tick()['status'], 'waiting_user')
        self.assertEqual(self.q.status()['current']['stage'], 'waiting_user')

    def test_stop_between_authorization_and_queue_start_is_not_acknowledged(self):
        self.enable()
        start = self.q.start
        def race(*args, **kw):
            self.q.stop()
            return start(*args, **kw)
        with patch.object(self.q, 'start', side_effect=race):
            with self.assertRaises(InstallError): self.tick()
        self.assertFalse(self.q.status()['enabled'])
        self.assertIsNone(self.lease.head)

    def test_network_failures_backoff_and_suspend_without_losing_checkpoint(self):
        self.enable(); self.tick(); self.now += 300
        with patch.object(self.tracker, 'issue', side_effect=InstallError('synthetic offline')):
            for failures in range(1, 4):
                with self.assertRaises(InstallError): self.tick()
                self.assertEqual(self.watch.status()['failures'], failures)
                self.now = self.watch.status()['next_due']
        self.assertEqual(self.watch.status()['status'], 'suspended')
        self.assertEqual(self.q.status()['current']['number'], 1)
        with self.assertRaises(InstallError): self.tick()

    def test_foreign_remote_lease_is_never_stolen(self):
        self.enable(); self.lease.head = 'f'*40
        with self.assertRaises(InstallError): self.tick()
        self.assertEqual(self.lease.head, 'f'*40)
        self.assertIsNone(self.q.status()['current'])
        self.assertEqual(self.watch.status()['status'], 'suspended')
        self.lease.head = None; self.now += 3600
        with self.assertRaises(InstallError): self.tick()

    def test_overlapping_ticks_and_stop_during_fetch(self):
        self.enable()
        entered, proceed = threading.Event(), threading.Event()
        errors = []
        def fetch():
            entered.set(); self.assertTrue(proceed.wait(5)); return self.tracker.items
        def work():
            try: self.tick()
            except InstallError as exc: errors.append(str(exc))
        with patch.object(self.tracker, 'issues', side_effect=fetch):
            thread = threading.Thread(target=work); thread.start()
            self.assertTrue(entered.wait(5))
            try:
                from pda.issue_queue import QueueBusy
                with self.assertRaises(QueueBusy): self.tick()
                result = self.q.stop()
                self.assertFalse(result['enabled'])
            finally:
                proceed.set(); thread.join(5)
        self.assertTrue(errors)
        self.assertIsNone(self.q.status()['current'])
        self.q.stop()
        self.assertIsNone(self.lease.head)
        with self.assertRaises(InstallError): self.tick()

    def test_explicit_tracker_access_denied_suspends_without_retry(self):
        from pda.issue_tracker import TrackerAccessDenied
        self.enable()
        with patch.object(self.tracker, 'issues', side_effect=TrackerAccessDenied('denied')):
            with self.assertRaises(InstallError): self.tick()
        self.assertEqual(self.watch.status()['status'], 'suspended')
        self.now += 3600
        with self.assertRaises(InstallError): self.tick()

    def test_invalid_interval_or_corrupt_state_fails_closed(self):
        for interval in (0, True, 59, 90000):
            with self.assertRaises(InstallError): self.watch.start('thread-a', interval)
        self.enable()
        from pda.issue_watch import STATE
        (self.root / STATE).write_text('{broken')
        with self.assertRaises(InstallError): self.tick()
        self.q.stop()
        self.assertFalse(self.q.status()['enabled'])

if __name__ == '__main__': unittest.main()
