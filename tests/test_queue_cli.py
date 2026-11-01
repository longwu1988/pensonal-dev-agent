import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / 'scripts/pda.py'
sys.path.insert(0,str(REPO/'scripts'))

class QueueCLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        subprocess.run(['git','init',str(self.root)],check=True,capture_output=True)
        subprocess.run(['git','-C',str(self.root),'remote','add','origin','https://git.example.invalid/team/project.git'],check=True,capture_output=True)
        config=json.loads((REPO/'templates/project.json').read_text())
        config['project']['tracker']={'kind':'gitea','repository':'https://git.example.invalid/team/project.git'}
        config['project']['integration_branch']='main'
        path=self.root/'docs/agents/project.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(config))
        (self.root/'.gitignore').write_text('/.local/agent/\n')

    def run_cli(self,*args):
        return subprocess.run([sys.executable,str(CLI),*args,'--project',str(self.root)],capture_output=True,text=True,timeout=10)

    def test_status_is_off_and_read_only_without_tracker_config(self):
        (self.root/'docs/agents/project.json').unlink()
        r=self.run_cli('queue-status')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(json.loads(r.stdout)['enabled'])
        self.assertFalse((self.root/'.local').exists())

    def test_start_preview_does_not_create_state_or_call_network(self):
        r=self.run_cli('queue-start','--owner','conversation-1')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'],'preview')
        self.assertFalse((self.root/'.local').exists())

    def test_start_needs_explicit_apply_owner_and_recorded_remote_permissions(self):
        r=self.run_cli('queue-start','--apply')
        self.assertNotEqual(r.returncode,0)
        r=self.run_cli('queue-start','--owner','conversation-1','--apply')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('permission',r.stderr)
        self.assertFalse((self.root/'.local').exists())

    def test_other_push_repository_is_rejected_before_network(self):
        subprocess.run(['git','-C',str(self.root),'remote','set-url','--push','origin','https://git.example.invalid/other/project.git'],check=True,capture_output=True)
        r=self.run_cli('queue-start','--owner','conversation-1')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('origin',r.stderr)

    def test_stop_works_even_with_broken_or_missing_tracker_config(self):
        (self.root/'docs/agents/project.json').write_text('{broken')
        r=self.run_cli('queue-stop')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse(json.loads(r.stdout)['enabled'])

    def test_cleanup_guard_requires_owner_and_never_starts_stopped_queue(self):
        self.assertNotEqual(self.run_cli('queue-cleanup-guard').returncode, 0)
        result = self.run_cli('queue-cleanup-guard', '--owner', 'synthetic')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('queue is stopped', result.stderr)
        self.assertFalse((self.root / '.local').exists())

    def test_complete_requires_evidence_and_merge_commit_flags(self):
        r=self.run_cli('queue-finish','--owner','conversation-1')
        self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.root/'.local').exists())


    def test_delivery_status_is_read_only_and_record_survives_worktree_and_reinstall(self):
        r = self.run_cli('delivery-status')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['tasks'], [])
        self.assertFalse((self.root / '.local').exists())
        sha = 'a'*40
        r = self.run_cli('delivery-record', '--issue', '3', '--commit', sha,
                         '--stage', 'waiting_user', '--evidence', 'synthetic task acceptance pending')
        self.assertEqual(r.returncode, 0, r.stderr)
        state = self.root / '.local/agent/delivery/3.json'
        before = state.read_bytes()
        self.run_cli('delivery-record', '--issue', '3', '--commit', sha,
                     '--stage', 'waiting_user', '--evidence', 'synthetic task acceptance pending')
        self.assertEqual(state.read_bytes(), before)
        for action in [('init', '--apply'), ('init', '--apply')]:
            r = self.run_cli(*action)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(state.read_bytes(), before)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid',
                        'commit','--allow-empty','-m','initial'],check=True,capture_output=True)
        worktree = self.root / '.local/agent/test-worktree'
        subprocess.run(['git','-C',str(self.root),'worktree','add','-b','test',str(worktree)],check=True,capture_output=True)
        cli = self.root / '.agents/skills/personal-dev/scripts/pda.py'
        r = subprocess.run([sys.executable, str(cli), 'delivery-status', '--project', str(worktree), '--issue', '3'],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['record']['commit'], sha)
        self.assertFalse((worktree / '.local').exists())
        self.assertEqual(json.loads(self.run_cli('queue-status').stdout)['enabled'], False)

    def test_delivery_check_rejects_missing_record_and_current_queue_even_when_stopped(self):
        r = self.run_cli('delivery-check', '--issue', '3', '--commit', 'a'*40)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('missing delivery record', r.stderr)
        from pda.issue_queue import Queue
        state = Queue(self.root).status()
        state['current'] = {'number': 3, 'stage': 'ready_to_merge'}
        path = self.root / '.local/agent/queue/state.json'
        path.parent.mkdir(parents=True); path.write_text(json.dumps(state))
        r = self.run_cli('delivery-check', '--issue', '3', '--commit', 'a'*40)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('queue-finish', r.stderr)
        self.assertFalse(json.loads(self.run_cli('queue-status').stdout)['enabled'])

    def test_delivery_checks_actual_record_lock_and_archive_ignore_rules(self):
        args = ('delivery-record', '--issue', '3', '--commit', 'a'*40, '--stage', 'accepted', '--evidence', 'synthetic')
        for rules in ('/.local/agent/delivery/*.json\n!/.local/agent/delivery/3.json\n',
                      '/.local/agent/delivery/*.json\n'):
            with self.subTest(rules=rules):
                (self.root / '.gitignore').write_text(rules)
                r = self.run_cli(*args)
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertFalse((self.root / '.local').exists())
        (self.root / '.gitignore').write_text('/.local/agent/delivery/*.json\n/.local/agent/delivery/write.lock\n')
        r = self.run_cli(*args); self.assertEqual(r.returncode, 0, r.stderr)
        before = (self.root / '.local/agent/delivery/3.json').read_bytes()
        r = self.run_cli('delivery-record', '--issue', '3', '--commit', 'b'*40,
                         '--stage', 'waiting_user', '--evidence', 'new revision pending')
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertFalse((self.root / '.local/agent/delivery/archive').exists())
        self.assertEqual((self.root / '.local/agent/delivery/3.json').read_bytes(), before)

    def test_delivery_rejects_missing_args_tracked_state_and_wrong_remote(self):
        r = self.run_cli('delivery-record', '--issue', '3')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.root / '.local').exists())
        args = ('delivery-record', '--issue', '3', '--commit', 'a'*40, '--stage', 'accepted', '--evidence', 'synthetic')
        r = self.run_cli(*args); self.assertEqual(r.returncode, 0, r.stderr)
        subprocess.run(['git','-C',str(self.root),'add','-f','.local/agent/delivery/3.json'],check=True,capture_output=True)
        r = self.run_cli(*args)
        self.assertNotEqual(r.returncode, 0); self.assertIn('Git-tracked', r.stderr)
        subprocess.run(['git','-C',str(self.root),'remote','set-url','--push','origin',
                        'https://git.example.invalid/other/project'],check=True,capture_output=True)
        r = self.run_cli('delivery-status', '--issue', '3')
        self.assertNotEqual(r.returncode, 0); self.assertIn('origin', r.stderr)

    def test_watch_preview_status_stop_and_required_arguments(self):
        r = self.run_cli('watch-status')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'off')
        r = self.run_cli('watch-start', '--thread', 'synthetic-thread')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'preview')
        self.assertFalse((self.root / '.local').exists())
        r = self.run_cli('watch-start', '--thread', 'synthetic-thread', '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('permission', r.stderr)
        self.assertNotEqual(self.run_cli('watch-tick', '--generation', 'old').returncode, 0)
        (self.root / 'docs/agents/project.json').unlink()
        r = self.run_cli('watch-stop')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)['scheduler_cleanup_required'])

    def test_watch_installed_runtime_and_reinstall_preserve_pending_authorization(self):
        config_path = self.root / 'docs/agents/project.json'
        config = json.loads(config_path.read_text())
        config['permissions'].update(push_task_branch=True, write_issue=True)
        config_path.write_text(json.dumps(config)); config_before = config_path.read_bytes()
        r = self.run_cli('watch-start', '--thread', 'synthetic', '--interval', '0', '--apply')
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.root / '.local').exists())
        r = self.run_cli('watch-start', '--thread', 'synthetic', '--interval', '300', '--apply')
        self.assertEqual(r.returncode, 0, r.stderr)
        pending = json.loads(r.stdout)
        self.assertEqual(pending['status'], 'pending')
        state = self.root / '.local/agent/watch/state.json'; before = state.read_bytes()
        for _ in range(2):
            r = self.run_cli('init', '--apply')
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(config_path.read_bytes(), config_before)
            self.assertEqual(state.read_bytes(), before)
        cli = self.root / '.agents/skills/personal-dev/scripts/pda.py'
        r = subprocess.run([sys.executable, str(cli), 'watch-status', '--project', str(self.root)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['generation'], pending['generation'])
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        r = self.run_cli('watch-bind', '--generation', pending['generation'], '--scheduler', 'synthetic-schedule')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.run_cli('queue-stop')
        r = self.run_cli('watch-tick', '--generation', pending['generation'], '--scheduler', 'synthetic-schedule', '--thread', 'synthetic')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('revoked', r.stderr)

    def checkpoint_fixture(self, stage='ready_to_merge', commit='a'*40):
        from pda.issue_workers import WorkerQueue
        path = self.root / 'docs/agents/project.json'
        config = json.loads(path.read_text())
        config['permissions'].update(push_task_branch=True, write_issue=True)
        path.write_text(json.dumps(config))
        worker = WorkerQueue(self.root, owner='synthetic')
        state = worker.status()
        state.update(enabled=True, repository='https://git.example.invalid/team/project',
                     integration_branch='main', current={'number': 3, 'stage': stage, 'commit': commit})
        worker._save(state)
        return SimpleNamespace(action='queue-checkpoint', owner='synthetic', apply=False,
                               stage='implementing', branch=None, worktree=None, commit='c'*40)

    def test_checkpoint_invalidation_checks_record_lock_and_archive_before_remote(self):
        from pda.worker_dispatch import dispatch
        from pda.transaction import InstallError
        args = self.checkpoint_fixture()
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'b'*40,
                              '--stage', 'accepted', '--evidence', 'synthetic accepted revision')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.root / '.local/agent/delivery/3.json'
        before = state.read_bytes()
        worker_rules = '/.local/agent/workers/\n/.local/agent/queue/\n'
        for rules in ('/.local/agent/delivery/write.lock\n',
                      '/.local/agent/delivery/*.json\n',
                      '/.local/agent/delivery/*.json\n/.local/agent/delivery/write.lock\n'):
            with self.subTest(rules=rules):
                (self.root / '.gitignore').write_text(worker_rules + rules)
                with mock.patch('pda.worker_dispatch.Tracker') as tracker, \
                        mock.patch('pda.issue_workers.WorkerQueue.checkpoint', return_value={}) as checkpoint:
                    with self.assertRaisesRegex(InstallError, 'Git-ignored'):
                        dispatch(self.root, args)
                    tracker.assert_not_called()
                    checkpoint.assert_not_called()
                self.assertEqual(state.read_bytes(), before)
                self.assertFalse((state.parent / 'archive').exists())

    def test_checkpoint_invalidation_rejects_tracked_delivery_data(self):
        from pda.worker_dispatch import dispatch
        from pda.transaction import InstallError
        args = self.checkpoint_fixture(stage='implementing')
        args.stage = 'waiting_user'
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'a'*40,
                              '--stage', 'accepted', '--evidence', 'synthetic')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.root / '.local/agent/delivery/3.json'
        before = state.read_bytes()
        subprocess.run(['git','-C',str(self.root),'add','-f',str(state)],check=True,capture_output=True)
        with mock.patch('pda.worker_dispatch.Tracker') as tracker, \
                mock.patch('pda.issue_workers.WorkerQueue.checkpoint', return_value={}) as checkpoint:
            with self.assertRaisesRegex(InstallError, 'Git-tracked'):
                dispatch(self.root, args)
            tracker.assert_not_called()
            checkpoint.assert_not_called()
        self.assertEqual(state.read_bytes(), before)

    def test_checkpoint_storage_uses_current_commit_not_requested_new_commit(self):
        from pda.worker_dispatch import dispatch
        args = self.checkpoint_fixture()
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'a'*40,
                              '--stage', 'accepted', '--evidence', 'synthetic')
        self.assertEqual(result.returncode, 0, result.stderr)
        # The invalidation writes current.commit (a), not the requested next commit (c).
        (self.root / '.gitignore').write_text('/.local/agent/workers/\n/.local/agent/queue/\n'
            '/.local/agent/delivery/*.json\n/.local/agent/delivery/write.lock\n')
        with mock.patch('pda.worker_dispatch.Tracker'), \
                mock.patch('pda.issue_workers.WorkerQueue._owned', return_value={'number': 3, 'stage': 'ready_to_merge', 'commit': 'a'*40}), \
                mock.patch('pda.issue_workers.WorkerQueue.checkpoint', return_value={'status': 'checkpoint'}) as checkpoint:
            self.assertEqual(dispatch(self.root, args)['status'], 'checkpoint')
            checkpoint.assert_called_once()

    def test_checkpoint_validates_remote_record_after_local_snapshot_becomes_stale(self):
        from pda.worker_dispatch import dispatch
        from pda.transaction import InstallError
        # A prior remote checkpoint succeeded, but label sync failed before local state saved.
        remote = {'number': 3, 'stage': 'ready_to_merge', 'commit': 'b'*40}
        for local_stage, next_stage in (('implementing', 'implementing'),
                                         ('ready_to_merge', 'waiting_user')):
            with self.subTest(local_stage=local_stage, next_stage=next_stage):
                (self.root / '.gitignore').write_text('/.local/agent/\n')
                args = self.checkpoint_fixture(stage=local_stage, commit='a'*40)
                args.stage = next_stage
                result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'a'*40,
                                      '--stage', 'accepted', '--evidence', 'synthetic')
                self.assertEqual(result.returncode, 0, result.stderr)
                state = self.root / '.local/agent/delivery/3.json'
                before = state.read_bytes()
                (self.root / '.gitignore').write_text('/.local/agent/workers/\n/.local/agent/queue/\n'
                    '/.local/agent/delivery/*.json\n/.local/agent/delivery/write.lock\n')
                with mock.patch('pda.worker_dispatch.Tracker'), \
                        mock.patch('pda.issue_workers.WorkerQueue._owned', return_value=remote), \
                        mock.patch('pda.issue_workers.WorkerQueue.checkpoint', return_value={}) as checkpoint:
                    with self.assertRaisesRegex(InstallError, 'Git-ignored'):
                        dispatch(self.root, args)
                    checkpoint.assert_not_called()
                self.assertEqual(state.read_bytes(), before)
                self.assertFalse((state.parent / 'archive').exists())

    def retry_fixture(self):
        from pda.issue_workers import WorkerQueue
        self.checkpoint_fixture()
        worker = WorkerQueue(self.root, owner='synthetic')
        state = worker.status(); state['current'] = None; worker._save(state)
        return SimpleNamespace(action='queue-retry', owner='synthetic', apply=False, issue=3)

    def test_retry_invalidation_requires_ignored_existing_proof_and_lock(self):
        from pda.worker_dispatch import dispatch
        from pda.transaction import InstallError
        args = self.retry_fixture()
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'b'*40,
                              '--stage', 'accepted', '--evidence', 'old completed proof')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.root / '.local/agent/delivery/3.json'; before = state.read_bytes()
        base = '/.local/agent/workers/\n/.local/agent/queue/\n'
        for rules in ('/.local/agent/delivery/write.lock\n', '/.local/agent/delivery/*.json\n'):
            with self.subTest(rules=rules):
                (self.root / '.gitignore').write_text(base + rules)
                with mock.patch('pda.worker_dispatch.Tracker') as tracker, \
                        mock.patch('pda.issue_workers.WorkerQueue.retry', return_value={}) as retry:
                    with self.assertRaisesRegex(InstallError, 'Git-ignored'):
                        dispatch(self.root, args)
                    tracker.assert_not_called(); retry.assert_not_called()
                self.assertEqual(state.read_bytes(), before)

    def test_retry_invalidation_rejects_tracked_proof(self):
        from pda.worker_dispatch import dispatch
        from pda.transaction import InstallError
        args = self.retry_fixture()
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'b'*40,
                              '--stage', 'accepted', '--evidence', 'old completed proof')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.root / '.local/agent/delivery/3.json'; before = state.read_bytes()
        subprocess.run(['git','-C',str(self.root),'add','-f',str(state)],check=True,capture_output=True)
        with mock.patch('pda.worker_dispatch.Tracker') as tracker, \
                mock.patch('pda.issue_workers.WorkerQueue.retry', return_value={}) as retry:
            with self.assertRaisesRegex(InstallError, 'Git-tracked'):
                dispatch(self.root, args)
            tracker.assert_not_called(); retry.assert_not_called()
        self.assertEqual(state.read_bytes(), before)

    def test_retry_uses_existing_proof_commit_without_requiring_archive(self):
        from pda.worker_dispatch import dispatch
        args = self.retry_fixture()
        result = self.run_cli('delivery-record', '--issue', '3', '--commit', 'b'*40,
                              '--stage', 'accepted', '--evidence', 'old completed proof')
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.root / '.gitignore').write_text('/.local/agent/workers/\n/.local/agent/queue/\n'
            '/.local/agent/delivery/*.json\n/.local/agent/delivery/write.lock\n')
        with mock.patch('pda.worker_dispatch.Tracker'), \
                mock.patch('pda.issue_workers.WorkerQueue.retry', return_value={'status': 'retry'}) as retry:
            self.assertEqual(dispatch(self.root, args)['status'], 'retry')
            retry.assert_called_once_with(3)

    def test_transfer_preview_names_source_and_target_and_writes_nothing(self):
        result = self.run_cli('queue-transfer', '--owner', 'source', '--target-owner', 'target',
                              '--evidence', 'user requested transfer')
        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        self.assertEqual(preview['source_owner'], 'source')
        self.assertEqual(preview['target_owner'], 'target')
        self.assertIn('transfer', preview['effect'])
        self.assertFalse((self.root / '.local').exists())

    def test_worker_status_stop_and_direct_claim_arguments(self):
        r=self.run_cli('queue-status','--owner','a')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['owner'],'a')
        r=self.run_cli('queue-stop','--owner','a')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.root/'.local/agent/workers/a/stop').exists())
        self.assertFalse((self.root/'.local/agent/queue/stop').exists())
        self.assertNotEqual(self.run_cli('queue-claim','--issue','1').returncode,0)
        self.assertNotEqual(self.run_cli('queue-resource-acquire','--owner','a').returncode,0)
        r=self.run_cli('queue-stop','--all')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.root/'.local/agent/queue/stop').exists())

if __name__=='__main__': unittest.main()
