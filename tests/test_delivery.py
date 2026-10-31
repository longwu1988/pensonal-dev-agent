import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pda.transaction import InstallError
from pda import issue_queue as module
from test_issue_queue import Tracker, Lease

COMMIT = 'a' * 40
STEPS = ('accepted', 'integration_verified', 'remote_synced', 'environment_restored', 'issue_updated')


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tracker, self.lease = Tracker(), Lease()
        self.assertTrue(hasattr(module, 'Delivery'), 'ordinary tasks have no delivery checkpoint/check')
        self.delivery = module.Delivery(self.root, self.tracker.repository, 'main')

    def ready(self):
        for stage in STEPS:
            self.delivery.record(1, COMMIT, stage, 'synthetic evidence for ' + stage)
        self.lease.merged = True
        self.tracker.items[1]['state'] = 'closed'

    def check(self):
        return self.delivery.check(1, COMMIT, self.tracker, self.lease)

    def test_status_without_record_is_read_only_and_not_complete(self):
        result = self.delivery.status(1)
        self.assertEqual(result['status'], 'unrecorded')
        self.assertFalse((self.root / '.local').exists())

    def test_push_without_issue_closure_is_not_complete(self):
        self.ready(); self.tracker.items[1]['state'] = 'open'
        with self.assertRaisesRegex(InstallError, 'closed'): self.check()
        self.assertIsNone(self.delivery.status(1)['record']['last_verified'])

    def test_missing_evidence_and_wrong_commit_block_completion(self):
        self.lease.merged = True; self.tracker.items[1]['state'] = 'closed'
        self.delivery.record(1, COMMIT, 'remote_synced', 'remote evidence')
        with self.assertRaisesRegex(InstallError, 'missing'): self.check()
        self.ready()
        with self.assertRaisesRegex(InstallError, 'commit'):
            self.delivery.check(1, 'b'*40, self.tracker, self.lease)

    def test_verified_is_live_and_repeat_check_reads_remote_again(self):
        self.ready()
        self.assertEqual(self.check()['status'], 'verified')
        self.assertEqual(self.delivery.status(1)['status'], 'recorded')
        self.tracker.items[1]['state'] = 'open'
        with self.assertRaises(InstallError): self.check()
        self.assertIsNone(self.delivery.status(1)['record']['last_verified'])

    def test_remote_failure_or_unreachable_commit_cannot_reuse_verification(self):
        self.ready(); self.check()
        with patch.object(self.tracker, 'issue', side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.check()
        self.assertIsNone(self.delivery.status(1)['record']['last_verified'])
        self.lease.merged = False
        with self.assertRaisesRegex(InstallError, 'reachable'): self.check()

    def test_resume_keeps_progress_and_new_commit_archives_old_evidence(self):
        self.ready()
        resumed = module.Delivery(self.root, self.tracker.repository, 'main')
        self.assertEqual(resumed.status(1)['missing'], [])
        resumed.record(1, 'b'*40, 'waiting_user', 'waiting for new revision')
        self.assertEqual(resumed.status(1)['missing'], list(STEPS))
        archive = self.root / '.local/agent/delivery/archive' / ('1-' + COMMIT + '.json')
        self.assertEqual(json.loads(archive.read_text())['commit'], COMMIT)

    def test_repeated_checkpoint_is_idempotent_but_changed_early_evidence_invalidates_later(self):
        self.ready()
        before = self.delivery.status(1)
        self.delivery.record(1, COMMIT, 'accepted', 'synthetic evidence for accepted')
        self.assertEqual(before, self.delivery.status(1))
        self.delivery.record(1, COMMIT, 'accepted', 'new acceptance')
        self.assertEqual(self.delivery.status(1)['missing'], list(STEPS[1:]))
        self.ready(); self.delivery.record(1, COMMIT, 'waiting_user', 'user reports failure')
        self.assertEqual(self.delivery.status(1)['missing'], list(STEPS))

    def test_binding_corruption_symlink_and_invalid_input_rejected(self):
        self.ready()
        wrong = module.Delivery(self.root, 'https://git.example.invalid/other/repo', 'main')
        with self.assertRaises(InstallError): wrong.status(1)
        with self.assertRaises(InstallError): self.delivery.record(1, COMMIT, 'unknown', 'evidence')
        with self.assertRaises(InstallError): self.delivery.status(True)
        path = self.root / '.local/agent/delivery/1.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        path.write_text('{bad')
        with self.assertRaises(InstallError): self.delivery.status(1)
        path.unlink(); outside = self.root / 'external'; outside.write_text('untouched')
        path.symlink_to(outside)
        with self.assertRaises(InstallError): self.delivery.record(1, COMMIT, 'accepted', 'evidence')
        self.assertEqual(outside.read_text(), 'untouched')

    def test_queue_finish_requires_shared_delivery_evidence(self):
        q = module.Queue(self.root, self.tracker, self.lease, 'main', 'test-owner')
        q.start(); q.next(); self.lease.merged = True; self.tracker.items[1]['state'] = 'closed'
        with self.assertRaises(InstallError): q.finish(COMMIT, 'synthetic evidence')
        self.assertIsNotNone(q.status()['current'])
        self.ready(); q.finish(COMMIT, 'synthetic evidence')
        self.assertEqual(q.status()['completed'], [1])
