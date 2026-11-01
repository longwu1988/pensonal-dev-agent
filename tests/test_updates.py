import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from pda.install import initialize, MANIFEST
from pda.transaction import InstallError, recover


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.package = self.base / 'package'
        for name in ('scripts', 'skills', 'templates', 'profiles', 'adapters'):
            shutil.copytree(REPO / name, self.package / name, ignore=shutil.ignore_patterns('__pycache__'))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('add', '.')
        self.git('commit', '-m', 'initial')
        self.old = self.git('rev-parse', 'HEAD')
        self.out = contextlib.redirect_stdout(io.StringIO())
        self.out.__enter__()
        initialize(self.root, self.package, True)
        self.new = 'b' * 40

    def tearDown(self):
        self.out.__exit__(None, None, None)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.package), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def installed(self):
        return json.loads((self.root / MANIFEST).read_text())

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and '.local' not in p.relative_to(self.root).parts}

    def api(self, status='ahead'):
        from pda.updates import check_update
        with patch('pda.updates.remote.latest', return_value=self.new), patch('pda.updates.remote.compare', return_value={
                'status': status, 'summary': ['Add synthetic rule'], 'url': 'https://github.com/example/compare'}):
            return check_update(self.root, now=100000)

    def test_install_records_source_and_ships_runtime(self):
        self.assertEqual(self.installed()['source']['commit'], self.old)
        self.assertEqual(self.installed()['source']['channel'], 'main')
        cli = self.root / '.agents/skills/personal-dev/scripts/pda.py'
        self.assertTrue(cli.is_file())
        result = subprocess.run([sys.executable, str(cli), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('check-update', result.stdout)

    def test_queue_runtime_is_installed_and_runs_without_source_checkout(self):
        for name in ('issue_queue', 'issue_tracker'):
            self.assertTrue((self.root / ('.agents/skills/personal-dev/scripts/pda/' + name + '.py')).is_file())
        subprocess.run(['git', 'init', str(self.root)], check=True, capture_output=True)
        cli = self.root / '.agents/skills/personal-dev/scripts/pda.py'
        result = subprocess.run([sys.executable, str(cli), 'queue-status', '--project', str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['enabled'])

    def test_worktree_lifecycle_update_preserves_local_registry_and_installs_guard(self):
        registry = self.root / '.local/agent/worktree-registry/synthetic.json'
        registry.parent.mkdir(parents=True)
        registry.write_text('{"version":1,"state":"retained","reason":"synthetic unique config"}')
        before = registry.read_bytes()
        config = (self.root / 'docs/agents/project.json').read_bytes()
        for apply in (False, True, True):
            initialize(self.root, self.package, apply)
            self.assertEqual(registry.read_bytes(), before)
            self.assertEqual((self.root / 'docs/agents/project.json').read_bytes(), config)
        installed = self.root / '.agents/skills/personal-dev'
        self.assertEqual((installed / 'references/worktree-lifecycle.md').read_bytes(),
                         (self.package / 'skills/personal-dev/references/worktree-lifecycle.md').read_bytes())
        result = subprocess.run([sys.executable, str(installed / 'scripts/pda.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('queue-cleanup-guard', result.stdout)

    def test_dirty_source_does_not_claim_clean_commit(self):
        path = self.package / 'skills/personal-dev/SKILL.md'
        path.write_text(path.read_text() + '\nLocal change\n')
        initialize(self.root, self.package, True)
        self.assertIsNone(self.installed()['source']['commit'])

    def test_ignored_payload_or_assume_unchanged_is_not_clean_source(self):
        ignored = self.package / 'skills/personal-dev/ignored.md'
        (self.package / '.git/info/exclude').write_text('ignored.md\n')
        ignored.write_text('untracked payload')
        initialize(self.root, self.package, True)
        self.assertIsNone(self.installed()['source']['commit'])
        ignored.unlink()
        # A second clean project avoids the managed-file removal guard.
        other = self.base / 'other'
        other.mkdir()
        self.git('update-index', '--assume-unchanged', 'skills/personal-dev/SKILL.md')
        path = self.package / 'skills/personal-dev/SKILL.md'
        path.write_text(path.read_text() + '\nhidden modification\n')
        initialize(other, self.package, True)
        self.assertIsNone(json.loads((other / MANIFEST).read_text())['source']['commit'])

    def test_available_check_does_not_modify_managed_files_and_caches(self):
        from pda.updates import check_update
        before = self.snapshot()
        result = self.api()
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['candidate'], self.new)
        self.assertEqual(self.snapshot(), before)
        with patch('pda.updates.remote.latest', side_effect=AssertionError('must not call network')):
            self.assertEqual(check_update(self.root, now=100001)['status'], 'cached')
        self.assertEqual(self.snapshot(), before)

    def test_relations_do_not_offer_downgrade(self):
        from pda.updates import check_update
        for status, expected in [('behind', 'ahead'), ('diverged', 'diverged'), ('identical', 'current')]:
            with patch('pda.updates.remote.latest', return_value=self.new), patch('pda.updates.remote.compare', return_value={'status': status, 'summary': [], 'url': ''}):
                self.assertEqual(check_update(self.root, force=True, now=100000)['status'], expected)

    def test_offline_is_nonblocking_and_throttled(self):
        from pda.updates import check_update
        with patch('pda.updates.remote.latest', side_effect=InstallError('offline')):
            self.assertEqual(check_update(self.root, now=100000)['status'], 'unavailable')
        with patch('pda.updates.remote.latest', side_effect=AssertionError()):
            self.assertEqual(check_update(self.root, now=100001)['status'], 'cached')

    def test_unknown_legacy_source_needs_bootstrap(self):
        from pda.updates import check_update
        manifest = self.installed()
        del manifest['source']
        (self.root / MANIFEST).write_text(json.dumps(manifest))
        with patch('pda.updates.remote.latest', side_effect=AssertionError()):
            self.assertEqual(check_update(self.root)['status'], 'unknown_source')

    def test_skip_applies_to_only_one_version(self):
        from pda.updates import check_update, choose
        self.api()
        choose(self.root, 'skip', self.new, now=100001)
        with patch('pda.updates.remote.latest', return_value=self.new), patch('pda.updates.remote.compare', return_value={'status': 'ahead', 'summary': [], 'url': ''}):
            self.assertEqual(check_update(self.root, force=True, now=100002)['status'], 'skipped')
        self.new = 'c' * 40
        with patch('pda.updates.remote.latest', return_value=self.new), patch('pda.updates.remote.compare', return_value={'status': 'ahead', 'summary': [], 'url': ''}):
            self.assertEqual(check_update(self.root, force=True, now=100003)['status'], 'available')

    def test_remind_later_and_stale_choice(self):
        from pda.updates import check_update, choose
        self.api()
        choose(self.root, 'later', self.new, now=100001)
        with patch('pda.updates.remote.latest', side_effect=AssertionError()):
            self.assertEqual(check_update(self.root, now=100002)['status'], 'deferred')
        with self.assertRaises(InstallError):
            choose(self.root, 'skip', 'c' * 40, now=100003)

    def test_pinned_update_preview_apply_and_recover(self):
        from pda.updates import update
        path = self.package / 'skills/personal-dev/SKILL.md'
        path.write_text(path.read_text() + '\nSynthetic approved change\n')
        self.git('add', '.')
        self.git('commit', '-m', 'new')
        self.new = self.git('rev-parse', 'HEAD')
        self.api()
        before = self.snapshot()
        with patch('pda.updates.remote.download', return_value=contextlib.nullcontext(self.package)) as download:
            update(self.root, self.new)
            self.assertEqual(self.snapshot(), before)
            update(self.root, self.new, apply=True)
            self.assertEqual(download.call_args.args, (self.new,))
        self.assertEqual(self.installed()['source']['commit'], self.new)
        recover(self.root, True)
        self.assertEqual(self.snapshot(), before)

    def test_interrupted_runtime_upgrade_recovers_in_independent_process(self):
        from pda.transaction import atomic_write
        before = self.snapshot()
        install = self.package / 'scripts/pda/install.py'
        install.write_text(install.read_text().replace('import difflib', 'from .source import NEW_CONSTANT\nimport difflib'))
        source = self.package / 'scripts/pda/source.py'
        source.write_text(source.read_text() + '\nNEW_CONSTANT = 1\n')
        def fail(root, name, content, file_mode=0o644):
            if name == '.agents/skills/personal-dev/scripts/pda/source.py':
                raise OSError('simulated interruption before new dependency')
            atomic_write(root, name, content, file_mode)
        for script, extra in [('scripts/pda.py', ['recover']), ('scripts/pda/transaction.py', [])]:
            with patch('pda.transaction.atomic_write', side_effect=fail):
                with self.assertRaisesRegex(InstallError, 'write interrupted'):
                    initialize(self.root, self.package, True)
            cli = self.root / '.agents/skills/personal-dev' / script
            result = subprocess.run([sys.executable, str(cli), *extra, '--project', str(self.root), '--apply'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_protocol_one_migration_interruption_recovers_with_full_new_source(self):
        from pda.transaction import apply_changes, atomic_write
        prefix = '.agents/skills/personal-dev/scripts/pda/'
        trans = prefix + 'transaction.py'
        added = prefix + 'issue_queue.py'
        new_trans = (self.root / trans).read_bytes()
        old_trans = new_trans.replace(b", 'issue_queue', 'issue_tracker'", b'')
        (self.root / trans).write_bytes(old_trans)
        (self.root / added).unlink()
        before = self.snapshot()
        changes = [dict(path=added, before=None, after=b'# synthetic new runtime'),
                   dict(path=trans, before=old_trans, after=new_trans)]
        def fail(root, name, content, file_mode=0o644):
            if name == trans: raise OSError('interrupted before replacing old runtime')
            atomic_write(root, name, content, file_mode)
        with patch('pda.transaction.atomic_write', side_effect=fail):
            with self.assertRaises(InstallError): apply_changes(self.root, changes)
        old_result = subprocess.run([sys.executable, str(self.root / trans), '--project', str(self.root), '--apply'],
                                    capture_output=True, text=True)
        self.assertNotEqual(old_result.returncode, 0)
        self.assertIn('unexpected recovery target', old_result.stderr)
        result = subprocess.run([sys.executable, str(REPO / 'scripts/pda.py'), 'recover',
                                 '--project', str(self.root), '--apply'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        recover(self.root, True)
        self.assertEqual(self.snapshot(), before)

    def test_full_protocol_two_to_three_upgrade_preserves_project_and_progress(self):
        old_package = self.base / 'old-package'
        shutil.copytree(self.package, old_package, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        trans = old_package / 'scripts/pda/transaction.py'
        trans.write_text(trans.read_text().replace(", 'issue_watch'", ''))
        (old_package / 'scripts/pda/issue_watch.py').unlink()
        source = old_package / 'scripts/pda/source.py'
        source.write_text(source.read_text().replace('PROTOCOL = 3', 'PROTOCOL = 2'))
        (old_package / 'profiles/update.json').write_text('{"protocol":2}')
        project = self.base / 'old-project'; project.mkdir()
        result = subprocess.run([sys.executable, str(old_package / 'scripts/pda.py'), 'init',
                                 '--project', str(project), '--apply'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = project / 'docs/agents/project.json'
        before_config = config.read_bytes()
        progress = project / '.local/agent/queue/state.json'; progress.parent.mkdir(parents=True)
        progress.write_text('{"synthetic":"preserve this opaque old progress"}')
        for apply in (False, True, True):
            initialize(project, REPO, apply)
            self.assertEqual(config.read_bytes(), before_config)
            self.assertEqual(progress.read_text(), '{"synthetic":"preserve this opaque old progress"}')
        self.assertTrue((project / '.agents/skills/personal-dev/scripts/pda/issue_watch.py').is_file())
        self.assertFalse((project / '.local/agent/watch').exists())

    def test_protocol_two_watch_migration_recovers_with_full_source(self):
        from pda.transaction import apply_changes, atomic_write
        prefix = '.agents/skills/personal-dev/scripts/pda/'
        trans, added = prefix + 'transaction.py', prefix + 'issue_watch.py'
        new = (self.root / trans).read_bytes()
        old = new.replace(b", 'issue_watch'", b'')
        (self.root / trans).write_bytes(old); (self.root / added).unlink()
        before = self.snapshot()
        changes = [dict(path=added, before=None, after=b'# synthetic watch runtime'),
                   dict(path=trans, before=old, after=new)]
        def fail(root, name, content, file_mode=0o644):
            if name == trans: raise OSError('synthetic interruption')
            atomic_write(root, name, content, file_mode)
        with patch('pda.transaction.atomic_write', side_effect=fail):
            with self.assertRaises(InstallError): apply_changes(self.root, changes)
        result = subprocess.run([sys.executable, str(REPO / 'scripts/pda.py'), 'recover',
                                 '--project', str(self.root), '--apply'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_apply_rechecks_edits_made_after_preview(self):
        from pda.updates import update
        self.api()
        path = self.root / '.agents/skills/personal-dev/SKILL.md'
        def edit_after_preview(changes):
            path.write_text('concurrent user change')
        with patch('pda.updates.remote.download', return_value=contextlib.nullcontext(self.package)), patch('pda.updates.show', side_effect=edit_after_preview):
            with self.assertRaises(InstallError):
                update(self.root, self.new, apply=True)
        self.assertEqual(path.read_text(), 'concurrent user change')
        self.assertEqual(self.installed()['source']['commit'], self.old)

    def test_copied_project_keeps_version_without_local_cache_or_source_checkout(self):
        clone = self.base / 'clone'
        shutil.copytree(self.root, clone, ignore=shutil.ignore_patterns('.local', '__pycache__'))
        self.assertEqual(json.loads((clone / MANIFEST).read_text())['source']['commit'], self.old)
        shutil.rmtree(self.package)
        script = clone / '.agents/skills/personal-dev/scripts/pda.py'
        result = subprocess.run([sys.executable, str(script), 'skip-update', '--project', str(clone), '--revision', 'c' * 40], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('revision was not offered', result.stderr)
        self.assertNotIn('ModuleNotFoundError', result.stderr)

    def test_update_refuses_conflict_and_unseen_revision(self):
        from pda.updates import update
        self.api()
        with self.assertRaises(InstallError):
            update(self.root, 'c' * 40, apply=True)
        path = self.root / '.agents/skills/personal-dev/SKILL.md'
        path.write_text('user-owned edit')
        before = self.snapshot()
        with patch('pda.updates.remote.download', return_value=contextlib.nullcontext(self.package)):
            with self.assertRaises(InstallError):
                update(self.root, self.new, apply=True)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
