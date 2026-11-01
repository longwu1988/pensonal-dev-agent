import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_queue_cli
from test_issue_workers import WritableTracker, MemoryClaims
from test_issue_queue import Lease, issue
from pda.transaction import InstallError
from pda.issue_workers import WorkerQueue
from pda.worker_dispatch import dispatch
from pda.permissions import Permissions
from pda.issue_watch import dispatch as watch_dispatch


class PermissionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_queue_cli.QueueCLITests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root; self.run_cli=self.fixture.run_cli
        self.tracker=WritableTracker(); self.tracker.items=[issue(6),issue(7)]
        self.claims=MemoryClaims()
        for name,value in [('Tracker',self.tracker),('Claims',self.claims),('GitLease',Lease())]:
            handle=patch('pda.worker_dispatch.'+name,return_value=value)
            handle.start(); self.addCleanup(handle.stop)
    def args(self,action,**changes):
        data=dict(action=action,owner='a',apply=True,issue=None,stage=None,branch=None,worktree=None,
                  commit=None,reason=None,evidence='synthetic user instruction',resource=None,target_owner=None)
        data.update(changes); return SimpleNamespace(**data)
    def grant(self,owner='a'):
        r=self.run_cli('permissions-grant','--owner',owner,'--issue','6','--allow','manage_claims,update_issue_labels',
                       '--deny','push_task_branch,write_issue,close_issue,create_pr,merge','--evidence','synthetic user grants only issue 6 control','--apply')
        self.assertEqual(r.returncode,0,r.stderr)
    def test_single_issue_control_grant_does_not_enable_business_push_or_other_workers(self):
        config=self.root/'docs/agents/project.json'; before=config.read_bytes()
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        result=dispatch(self.root,self.args('queue-claim',issue=6))
        self.assertEqual(result['issue']['number'],6)
        dispatch(self.root,self.args('queue-checkpoint',stage='implementing'))
        for action,changes in [('queue-claim',{'issue':7}),('queue-next',{}),('queue-retry',{'issue':7}),('queue-start',{'owner':'b','issue':6})]:
            with self.subTest(action=action,changes=changes):
                with self.assertRaises(InstallError): dispatch(self.root,self.args(action,**changes))
        r=self.run_cli('permissions-check','--owner','a','--issue','6','--capability','push_task_branch')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(config.read_bytes(),before)
    def test_project_control_permissions_work_with_business_permissions_false(self):
        path=self.root/'docs/agents/project.json'; cfg=json.loads(path.read_text())
        cfg['permissions'].update(manage_claims=True,update_issue_labels=True)
        path.write_text(json.dumps(cfg))
        dispatch(self.root,self.args('queue-start'))
        self.assertEqual(dispatch(self.root,self.args('queue-next'))['issue']['number'],6)
        self.assertFalse(cfg['permissions']['push_task_branch'])
    def test_revoke_blocks_next_guard_and_preserves_claim_and_config(self):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6)); dispatch(self.root,self.args('queue-claim',issue=6))
        r=self.run_cli('permissions-revoke','--owner','a','--issue','6','--evidence','synthetic revoke','--apply')
        self.assertEqual(r.returncode,0,r.stderr)
        for transport in (self.tracker,self.claims):
            with self.assertRaises(InstallError): transport.before_write()
        with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-guard'))
        self.assertEqual(self.claims.get('issues/6')['owner'],'a')
        self.assertEqual(dispatch(self.root,self.args('queue-stop'))['current']['number'],6)
    def test_worker_scope_survives_stop_start_and_refuses_batch(self):
        q=WorkerQueue(self.root,self.tracker,Lease(),'main','a',self.claims)
        q.start(issue=6); q.claim(6); q.stop(); q.start()
        self.assertEqual(q.status()['issue_scope'],6)
        with self.assertRaises(InstallError): q.next()
        with self.assertRaises(InstallError): q.start(issue=7)
    def test_legacy_config_remains_readable_and_bytes_unchanged_without_new_grants(self):
        path=self.root/'docs/agents/project.json'; cfg=json.loads(path.read_text())
        for name in ('manage_claims','update_issue_labels','close_issue'): cfg['permissions'].pop(name,None)
        cfg['permissions'].update(push_task_branch=True,write_issue=True)
        path.write_text(json.dumps(cfg)); before=path.read_bytes()
        r=self.run_cli('init','--apply'); self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(path.read_bytes(),before)
        r=self.run_cli('permissions-check','--owner','a','--issue','6','--capability','manage_claims')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('permission denied: manage_claims',r.stderr)
        self.assertEqual(path.read_bytes(),before)

    def test_scoped_deny_overrides_project_business_permission(self):
        path=self.root/'docs/agents/project.json'; cfg=json.loads(path.read_text())
        cfg['permissions']['push_task_branch']=True; path.write_text(json.dumps(cfg))
        self.grant()
        r=self.run_cli('permissions-check','--owner','a','--issue','6','--capability','push_task_branch')
        self.assertNotEqual(r.returncode,0)
        self.assertIn('permission denied: push_task_branch',r.stderr)

    def test_scoped_grant_cannot_start_watch_or_unscoped_queue(self):
        self.grant()
        with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-start'))
        with self.assertRaises(InstallError):
            watch_dispatch(self.root,self.args('watch-start',thread='synthetic-thread',interval=300))
        self.assertFalse((self.root/'.local/agent/watch/state.json').exists())
        self.assertEqual(self.claims.values,{})

    def test_revocation_after_remote_claim_prevents_label_write(self):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        claim=self.claims.claim
        def revoke_after_claim(*args):
            result=claim(*args)
            Permissions(self.root,self.tracker.repository,'main','a').revoke(6,'synthetic revoke',apply=True)
            return result
        with patch.object(self.claims,'claim',side_effect=revoke_after_claim), \
                patch.object(self.tracker,'set_stage',side_effect=AssertionError('revoked label write')):
            with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-claim',issue=6))
        self.assertEqual(self.claims.get('issues/6')['owner'],'a')
        self.assertTrue(WorkerQueue(self.root,owner='a').status()['current']['pending'])

    def test_transfer_does_not_copy_scoped_authorization(self):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        dispatch(self.root,self.args('queue-claim',issue=6)); dispatch(self.root,self.args('queue-stop'))
        dispatch(self.root,self.args('queue-transfer',target_owner='b'))
        self.assertEqual(self.claims.get('issues/6')['owner'],'b')
        self.assertFalse((self.root/'.local/agent/permissions/b.json').exists())
        with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-start',owner='b',issue=6))
        self.grant('b'); dispatch(self.root,self.args('queue-start',owner='b',issue=6))
        self.assertEqual(dispatch(self.root,self.args('queue-claim',owner='b',issue=6))['issue']['number'],6)

    def test_revocation_during_tracker_read_prevents_following_label_write(self):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        dispatch(self.root,self.args('queue-claim',issue=6))
        self.tracker.items[0]['labels']=[{'name':'ai-ready'}]
        read_issue=self.tracker.issue
        def revoke_during_read(number):
            result=read_issue(number)
            Permissions(self.root,self.tracker.repository,'main','a').revoke(6,'synthetic read-time revoke',apply=True)
            return result
        with patch.object(self.tracker,'issue',side_effect=revoke_during_read), \
                patch.object(self.tracker,'set_stage',wraps=self.tracker.set_stage) as write:
            with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-guard'))
            write.assert_not_called()

    def assert_revocation_during_claim_read(self,action,**changes):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        dispatch(self.root,self.args('queue-claim',issue=6))
        if action=='queue-transfer': dispatch(self.root,self.args('queue-stop'))
        read_claim=self.claims.get
        def revoke_during_read(key):
            result=read_claim(key)
            Permissions(self.root,self.tracker.repository,'main','a').revoke(6,'synthetic read-time revoke',apply=True)
            return result
        with patch.object(self.claims,'get',side_effect=revoke_during_read), \
                patch.object(self.claims,'update',wraps=self.claims.update) as write:
            with self.assertRaises(InstallError): dispatch(self.root,self.args(action,**changes))
            write.assert_not_called()

    def test_revocation_during_claim_read_prevents_resource_write(self):
        self.assert_revocation_during_claim_read('queue-resource-acquire',resource='environment:test')

    def test_revocation_during_claim_read_prevents_transfer_write(self):
        self.assert_revocation_during_claim_read('queue-transfer',target_owner='b')

    def test_revocation_during_retry_read_preserves_blocked_stage(self):
        self.grant(); dispatch(self.root,self.args('queue-start',issue=6))
        dispatch(self.root,self.args('queue-claim',issue=6))
        dispatch(self.root,self.args('queue-block',reason='needs_input'))
        read_issue=self.tracker.issue
        def revoke_during_read(number):
            result=read_issue(number)
            Permissions(self.root,self.tracker.repository,'main','a').revoke(6,'synthetic retry revoke',apply=True)
            return result
        with patch.object(self.tracker,'issue',side_effect=revoke_during_read), \
                patch.object(self.claims,'update',wraps=self.claims.update) as write:
            with self.assertRaises(InstallError): dispatch(self.root,self.args('queue-retry',issue=6))
            write.assert_not_called()
        self.assertEqual(self.claims.get('issues/6')['stage'],'blocked')
