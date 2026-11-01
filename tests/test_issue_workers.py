import copy
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pda.issue_workers import WorkerQueue
from pda.issue_claims import ClaimConflict
from pda.issue_queue import Delivery, DELIVERY_STEPS
from pda.transaction import InstallError
from test_issue_queue import Tracker, Lease, issue


class MemoryClaims:
    def __init__(self): self.values = {}; self.resources = {}; self.n = 0
    def ensure(self): pass
    def get(self, key): return copy.deepcopy(self.values.get(key))
    def claim(self, number, owner, token, branch):
        key = 'issues/' + str(number)
        if key in self.values:
            old = self.values[key]
            return self.get(key) if (old['owner'], old['token']) == (owner, token) and old['stage'] != 'done' else None
        return self._put(key, dict(number=number, owner=owner, token=token, integration_branch=branch,
                                   stage='claimed', branch=None, worktree=None, commit=None))
    def _put(self, key, data):
        self.n += 1
        self.values[key] = dict(data, key=key, _sha=str(self.n))
        return self.get(key)
    def update(self, record, **kw):
        if self.values[record['key']]['_sha'] != record['_sha']: raise ClaimConflict('stale')
        return self._put(record['key'], dict(record, **kw))
    def acquire_resource(self, resource, owner, token):
        if resource in self.resources: return self.resources[resource] == (owner, token)
        self.resources[resource] = (owner, token); return True
    def release_resource(self, resource, owner, token):
        if resource in self.resources:
            if self.resources[resource] != (owner, token): raise ClaimConflict('not yours')
            del self.resources[resource]
    def resource_owned(self, resource, owner, token):
        return self.resources.get(resource) == (owner, token)


class WritableTracker(Tracker):
    def set_stage(self, number, label):
        item = next(x for x in self.items if x['number'] == number)
        item['labels'] = [x for x in item['labels'] if not x['name'].startswith('ai-')] + [{'name': label}]
        return item


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.tracker = WritableTracker(); self.claims = MemoryClaims()
        self.lease = Lease(); self.lease.merged = True
        self.a = self.worker('a'); self.b = self.worker('b')
    def worker(self, owner, root=None):
        return WorkerQueue(root or self.root, self.tracker, self.lease, 'main', owner, claims=self.claims)
    def ready(self, q):
        number = q.status()['current']['number']
        for stage in ('accepted', 'integration_verified'):
            Delivery(q.root, self.tracker.repository, 'main').record(number, 'a'*40, stage, 'synthetic '+stage)
        q.checkpoint('ready_to_merge', commit='a'*40)
    def test_two_sessions_and_two_clones_claim_different_issues(self):
        self.a.start(); self.b.start()
        self.assertEqual(self.a.next()['issue']['number'], 1)
        self.assertEqual(self.b.next()['issue']['number'], 2)
        third = self.worker('c', self.root/'clone'); third.start()
        self.assertEqual(third.next()['status'], 'empty')
        self.assertEqual(self.a.next()['status'], 'resume')
    def test_direct_number_cannot_bypass_claim_or_done(self):
        self.a.start(); self.a.claim(1)
        self.b.start()
        with self.assertRaises(ClaimConflict): self.b.claim(1)
        self.assertIsNone(self.b.status()['current'])
    def test_stop_one_does_not_stop_other_or_release_claim(self):
        self.a.start(); self.a.next(); self.b.start(); self.b.next()
        self.a.stop()
        with self.assertRaises(InstallError): self.a.guard()
        self.b.guard()
        self.assertEqual(self.claims.get('issues/1')['owner'], 'a')
        self.a.start(); self.assertEqual(self.a.next()['status'], 'resume')
    def test_stop_all_prevents_restart_with_old_authorization(self):
        self.a.start(); self.a.next(); self.b.start(); self.b.next()
        token=self.a._stop_token()
        self.worker(None).stop()
        for q in (self.a,self.b):
            with self.assertRaises(InstallError): q.guard()
            with self.assertRaises(InstallError): q.start(expected_stop=token)
    def test_label_failure_keeps_claim_and_resumes_without_reimplementation(self):
        self.a.start()
        with patch.object(self.tracker,'set_stage',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.next()
        self.assertEqual(self.a.status()['current']['number'],1)
        self.b.start(); self.assertEqual(self.b.next()['issue']['number'],2)
        self.assertEqual(self.a.next()['status'],'resume')
    def test_waiting_and_closed_issue_resume_only_to_finish(self):
        self.a.start(); self.a.next(); self.a.checkpoint('waiting_user')
        self.assertEqual(self.a.next()['checkpoint']['stage'],'waiting_user')
        self.tracker.items[1]['state']='closed'
        self.assertEqual(self.a.next()['status'],'finishing')
    def test_merge_is_serialized_and_requires_evidence(self):
        self.a.start(); self.a.next(); self.b.start(); self.b.next()
        with self.assertRaises(InstallError): self.a.checkpoint('ready_to_merge',commit='a'*40)
        self.ready(self.a); self.ready(self.b)
        self.a.checkpoint('merging')
        with self.assertRaises(ClaimConflict): self.b.checkpoint('merging')
        self.assertEqual(self.b.status()['current']['stage'],'ready_to_merge')
        self.a.checkpoint('testing')
        self.b.checkpoint('merging')
    def test_environment_lock_does_not_release_other_owner(self):
        self.a.start(); self.a.next(); self.b.start(); self.b.next()
        self.a.resource('environment:local',True)
        with self.assertRaises(ClaimConflict): self.b.resource('environment:local',True)
        with self.assertRaises(ClaimConflict): self.b.resource('environment:local',False)
        self.a.resource('environment:local',False)
        self.b.resource('environment:local',True)
    def test_completed_record_survives_new_clone_and_reopen(self):
        self.a.start(); self.a.next(); self.ready(self.a); self.a.checkpoint('merging')
        for stage in DELIVERY_STEPS:
            Delivery(self.root,self.tracker.repository,'main').record(1,'a'*40,stage,'synthetic '+stage)
        self.tracker.items[1]['state']='closed'
        self.a.finish('a'*40,'synthetic evidence')
        self.assertEqual(self.claims.get('issues/1')['stage'],'done')
        self.tracker.items[1]['state']='open'; self.tracker.set_stage(1,'ai-ready')
        b=self.worker('new',self.root/'clone'); b.start()
        self.assertEqual(b.next()['issue']['number'],2)
    def test_stop_during_claim_retains_intent_and_blocks_work(self):
        self.a.start(); original=self.claims.claim
        def claim(*args):
            value=original(*args); self.a.stop(); return value
        with patch.object(self.claims,'claim',side_effect=claim):
            with self.assertRaises(InstallError): self.a.next()
        self.assertIsNotNone(self.a.status()['current'])
        self.assertFalse(self.a.status()['enabled'])
    def test_legacy_unfinished_state_is_not_migrated(self):
        from pda.issue_queue import Queue
        old=Queue(self.root,self.tracker,Lease(),'main',owner='old'); old.start(); old.next()
        with self.assertRaises(InstallError): self.a.start()

    def test_all_nonready_labels_are_excluded_even_with_ai_ready(self):
        for label in ('ai-testing','ai-waiting-user','ai-ready-to-merge','ai-merging','ai-done'):
            with self.subTest(label=label):
                self.tracker.items=[issue(1,labels=[{'name':'ai-ready'},{'name':label}])]
                q=self.worker('worker-'+label); q.start()
                self.assertEqual(q.next()['status'],'empty')

    def test_pending_intent_recovers_using_same_token(self):
        self.a.start()
        with patch.object(self.claims,'claim',side_effect=InstallError('offline before write')):
            with self.assertRaises(InstallError): self.a.next()
        token=self.a.status()['current']['token']
        self.assertEqual(self.a.next()['status'],'resume')
        self.assertEqual(self.claims.get('issues/1')['token'],token)

    def test_done_cannot_return_to_development_after_label_failure(self):
        self.a.start(); self.a.next(); self.ready(self.a); self.a.checkpoint('merging')
        for stage in DELIVERY_STEPS:
            Delivery(self.root,self.tracker.repository,'main').record(1,'a'*40,stage,'synthetic '+stage)
        self.tracker.items[1]['state']='closed'
        with patch.object(self.tracker,'set_stage',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.finish('a'*40,'evidence')
        with self.assertRaises(InstallError): self.a.checkpoint('implementing')
        self.a.finish('a'*40,'evidence')
        self.assertIsNone(self.a.status()['current'])

    def test_external_assignment_or_block_marker_is_not_overwritten(self):
        self.a.start(); self.a.next()
        self.tracker.items[1]['labels']=[{'name':'ai-blocked'}]
        with self.assertRaises(InstallError): self.a.guard()
        self.assertEqual(self.tracker.items[1]['labels'],[{'name':'ai-blocked'}])

    def test_watch_and_manual_worker_claim_different_issues_and_stop_scope(self):
        from pda.issue_watch import Watch
        self.a.start(); self.a.next()
        queue=self.worker(None)
        watch=Watch(queue,clock=lambda:1000)
        state=watch.start('host-thread'); watch.bind(state['generation'],'schedule')
        result=watch.tick(state['generation'],'schedule','host-thread')
        self.assertEqual(result['issue']['number'],2)
        queue.stop()
        self.a.guard()
        with self.assertRaises(InstallError): watch.tick(state['generation'],'schedule','host-thread')

    def test_watch_restart_keeps_unfinished_claim_owner(self):
        from pda.issue_watch import Watch
        queue=self.worker(None); watch=Watch(queue,clock=lambda:1000)
        state=watch.start('host'); watch.bind(state['generation'],'schedule')
        watch.tick(state['generation'],'schedule','host')
        owner=queue.owner; token=queue.status()['current']['token']; queue.stop()
        state=watch.start('host'); watch.bind(state['generation'],'new-schedule')
        self.assertEqual(watch.tick(state['generation'],'new-schedule','host')['status'],'resume')
        self.assertEqual(queue.owner,owner)
        self.assertEqual(queue.status()['current']['token'],token)

    def test_block_does_not_release_unrestored_environment(self):
        self.a.start(); self.a.next(); self.b.start(); self.b.next()
        self.a.resource('environment:local',True)
        with self.assertRaises(InstallError): self.a.block('environment')
        with self.assertRaises(ClaimConflict): self.b.resource('environment:local',True)
        self.a.resource('environment:local',False); self.a.block('environment')
        self.assertIsNone(self.a.status()['current'])

    def test_waiting_user_invalidates_old_acceptance(self):
        self.a.start(); self.a.next(); self.ready(self.a)
        self.a.checkpoint('waiting_user')
        with self.assertRaises(InstallError): self.a.checkpoint('ready_to_merge')

    def test_transfer_requires_stop_and_preserves_worktree(self):
        self.a.start(); self.a.next(); self.a.checkpoint('implementing',branch='codex/one',worktree='/synthetic/worktree')
        with self.assertRaises(InstallError): self.a.transfer('b','user requested handoff')
        self.a.stop(); self.a.transfer('b','user requested handoff')
        self.b.start(); result=self.b.claim(1)
        self.assertEqual(result['status'],'resume')
        self.assertEqual(result['checkpoint']['worktree'],'/synthetic/worktree')
        self.a.start()
        with self.assertRaises(InstallError): self.a.claim(1)

    def test_explicit_number_without_ready_is_claimed_before_label_write(self):
        self.tracker.items[1]['labels']=[{'name':'bug'}]
        self.a.start()
        result=self.a.claim(1)
        self.assertEqual(result['status'],'claimed')
        self.assertEqual(self.claims.get('issues/1')['owner'],'a')
        self.assertIn({'name':'bug'},self.tracker.items[1]['labels'])

    def test_blocked_merging_resource_can_be_explicitly_released(self):
        self.a.start(); self.a.next(); self.ready(self.a); self.a.checkpoint('merging')
        with self.assertRaises(InstallError): self.a.block('environment')
        self.a.resource('integration:main',False)
        self.a.block('environment')
        self.assertIsNone(self.a.status()['current'])

    def test_checkpoint_label_failure_can_retry_same_stage_or_advance(self):
        self.a.start(); self.a.next()
        with patch.object(self.tracker,'set_stage',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.checkpoint('testing')
        self.a.checkpoint('testing')
        self.assertEqual(self.a.next()['checkpoint']['stage'],'testing')
        with patch.object(self.tracker,'set_stage',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.checkpoint('waiting_user')
        self.a.checkpoint('implementing')
        self.assertEqual(self.a.next()['checkpoint']['stage'],'implementing')

    def test_block_label_failure_can_retry(self):
        self.a.start(); self.a.next()
        with patch.object(self.tracker,'set_stage',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.block('environment')
        self.a.block('environment')
        self.assertIsNone(self.a.status()['current'])

    def test_explicit_retry_reopened_ready_preserves_ownership(self):
        self.a.start(); self.a.next(); self.a.block('environment')
        self.tracker.set_stage(1,'ai-ready')
        self.a.retry(1)
        self.assertEqual(self.a.next()['checkpoint']['stage'],'claimed')

    def test_retry_conflicting_label_does_not_change_remote_record(self):
        self.a.start(); self.a.next(); self.a.block('environment')
        self.tracker.set_stage(1,'ai-testing')
        before=self.claims.get('issues/1')
        with self.assertRaises(InstallError): self.a.retry(1)
        self.assertEqual(before,self.claims.get('issues/1'))
        self.assertIsNone(self.a.status()['current'])

    def test_explicit_retry_invalidates_previous_acceptance(self):
        self.a.start(); self.a.next(); self.ready(self.a)
        self.a.block('test_failed'); self.a.retry(1)
        with self.assertRaises(InstallError): self.a.checkpoint('ready_to_merge',commit='a'*40)

    def test_retry_before_remote_write_can_resume_same_issue(self):
        self.a.start(); self.a.next(); self.a.block('environment')
        with patch.object(self.claims,'update',side_effect=InstallError('offline')):
            with self.assertRaises(InstallError): self.a.retry(1)
        self.a.retry(1)
        self.assertEqual(self.a.next()['checkpoint']['stage'],'claimed')
