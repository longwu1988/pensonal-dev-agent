import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / 'scripts/pda.py'
sys.path.insert(0, str(REPO / 'scripts'))


class TaskNextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', str(self.root)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.root), 'remote', 'add', 'origin',
                        'https://git.example.invalid/team/project.git'], check=True, capture_output=True)
        config = json.loads((REPO / 'templates/project.json').read_text())
        config['project']['tracker'] = {'kind': 'gitea', 'repository': 'https://git.example.invalid/team/project.git'}
        config['project']['integration_branch'] = 'main'
        path = self.root / 'docs/agents/project.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(config))
        (self.root / '.gitignore').write_text('/.local/agent/\n')

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args, '--project', str(self.root)],
                              capture_output=True, text=True, timeout=10)

    def test_idle_is_read_only(self):
        result = self.run_cli('task-next')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'idle')
        self.assertFalse(payload['can_merge'])
        self.assertEqual(payload['read'], 'references/issue-claims.md')
        self.assertIn('待你确认', payload['ask'])
        self.assertFalse((self.root / '.local').exists())

    def test_implementing_points_at_one_rule(self):
        from pda.issue_workers import WorkerQueue
        worker = WorkerQueue(self.root, owner='conversation-1')
        state = worker.status()
        state['current'] = {'number': 8, 'stage': 'implementing', 'commit': None}
        worker._save(state)
        result = self.run_cli('task-next', '--owner', 'conversation-1', '--issue', '8')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['read'], 'references/implementation.md')
        self.assertFalse(payload['can_merge'])
        self.assertIn('accepted', payload['missing'])

    def test_merge_requires_unit_test_evidence_for_same_commit(self):
        from pda.issue_queue import Delivery
        from pda.issue_workers import WorkerQueue
        from test_issue_queue import stage_evidence
        sha = 'a' * 40
        Delivery(self.root, 'https://git.example.invalid/team/project', 'main').record(
            8, sha, 'accepted', stage_evidence('accepted'))
        Delivery(self.root, 'https://git.example.invalid/team/project', 'main').record(
            8, sha, 'integration_verified', stage_evidence('integration_verified'))
        worker = WorkerQueue(self.root, owner='conversation-1')
        state = worker.status()
        state['current'] = {'number': 8, 'stage': 'ready_to_merge', 'commit': sha}
        worker._save(state)
        result = self.run_cli('task-next', '--owner', 'conversation-1')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['can_merge'])
        self.assertIn('不是构建验收', payload['merge'])
        self.assertEqual(payload['read'], 'references/local-validation.md')

    def test_two_currents_do_not_pick_one(self):
        from pda.issue_workers import WorkerQueue
        for owner, number in (('one', 1), ('two', 2)):
            worker = WorkerQueue(self.root, owner=owner)
            state = worker.status()
            state['current'] = {'number': number, 'stage': 'implementing', 'commit': None}
            worker._save(state)
        result = self.run_cli('task-next')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'ambiguous')
        self.assertFalse(payload['can_merge'])
        self.assertCountEqual(payload['owners'], ['one', 'two'])
