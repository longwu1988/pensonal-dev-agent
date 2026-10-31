import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / 'scripts/pda.py'

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

    def test_complete_requires_evidence_and_merge_commit_flags(self):
        r=self.run_cli('queue-finish','--owner','conversation-1')
        self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.root/'.local').exists())

if __name__=='__main__': unittest.main()
