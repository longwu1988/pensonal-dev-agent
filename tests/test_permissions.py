import importlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pda.transaction import InstallError


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('pda.permissions'), 'scoped permissions module is required')
        self.module = importlib.import_module('pda.permissions')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init')
        (self.root / '.gitignore').write_text('.local/\n')
        self.config = self.root / 'project.json'
        self.config.write_bytes(b'{ "permissions": { "push_task_branch": false } }\n')
        self.store = self.module.Permissions(self.root, 'https://example.com/team/repo', 'main', 'A')
        self.path = self.root / '.local/agent/permissions/A.json'
        self.lock = self.path.with_suffix('.lock')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True).stdout.decode()

    def grant(self, **kwargs):
        args = dict(issue=6, allow=['manage_claims', 'update_issue_labels'], deny=[], evidence='User approved issue 6', apply=True)
        args.update(kwargs)
        return self.store.grant(**args)

    def test_scoped_controls_do_not_authorize_business_writes(self):
        self.grant()
        effective = self.store.require({}, 6, ['manage_claims', 'update_issue_labels'])
        for name in ['push_task_branch', 'write_issue', 'close_issue', 'create_pr', 'merge', 'push_tag', 'deploy']:
            self.assertFalse(effective[name])
            with self.assertRaises(InstallError): self.store.require({}, 6, [name])

    def test_project_defaults_are_false_and_allow_only_boolean_values(self):
        self.assertIsNone(self.store.status())
        self.assertTrue(self.store.require({'merge': True}, None, ['merge'])['merge'])
        with self.assertRaises(InstallError): self.store.require({}, None, ['merge'])
        for value in [1, 'true', None, [], {}]:
            with self.subTest(value=value), self.assertRaises(InstallError):
                self.store.require({'merge': value}, 6, ['merge'])

    def test_explicit_deny_overrides_project_true(self):
        self.grant(deny=['merge'])
        with self.assertRaises(InstallError): self.store.require({'merge': True}, 6, ['merge'])

    def test_another_owner_cannot_use_grant(self):
        self.grant()
        other = self.module.Permissions(self.root, self.store.repository, 'main', 'B')
        with self.assertRaises(InstallError): other.require({}, 6, ['manage_claims'])

    def test_wrong_issue_or_no_issue_cannot_fall_back_to_project(self):
        self.grant()
        for issue in [7, None, True, 0, '6']:
            with self.subTest(issue=issue), self.assertRaises(InstallError):
                self.store.require({'manage_claims': True}, issue, ['manage_claims'])

    def test_wrong_repository_branch_or_record_owner_fails_closed(self):
        self.grant()
        for repo, branch in [('https://example.com/team/other', 'main'), (self.store.repository, 'other')]:
            other = self.module.Permissions(self.root, repo, branch, 'A')
            with self.assertRaises(InstallError): other.require({'merge': True}, 6, ['merge'])
        value = self.store.status(); value['owner'] = 'B'
        self.path.write_text(json.dumps(value))
        with self.assertRaises(InstallError): self.store.require({'merge': True}, 6, ['merge'])

    def test_repository_is_canonicalized(self):
        store = self.module.Permissions(self.root, 'git@EXAMPLE.com:team/repo.git', 'main', 'A')
        record = store.grant(6, ['merge'], [], 'Approved', apply=True)
        self.assertEqual(record['repository'], 'https://example.com/team/repo')
        self.assertTrue(self.store.require({}, 6, ['merge'])['merge'])

    def test_preview_and_duplicate_grant_preserve_configuration(self):
        original = self.config.read_bytes()
        preview = self.grant(apply=False)
        self.assertEqual(preview['status'], 'preview')
        self.assertFalse(self.path.parent.exists())
        first = self.grant()
        self.assertEqual(first, preview['record'])
        before = self.path.read_bytes()
        self.assertEqual(self.grant(), first)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.config.read_bytes(), original)

    def test_revoke_preview_and_tombstone_block_project_fallback(self):
        self.grant()
        before = self.path.read_bytes()
        preview = self.store.revoke(6, 'User withdrew permission')
        self.assertTrue(preview['record']['revoked'])
        self.assertEqual(self.path.read_bytes(), before)
        record = self.store.revoke(6, 'User withdrew permission', apply=True)
        self.assertTrue(record['revoked']); self.assertTrue(self.path.exists())
        with self.assertRaises(InstallError): self.store.require({'manage_claims': True}, 6, ['manage_claims'])
        self.assertEqual(self.store.revoke(6, 'User withdrew permission', apply=True), record)
        self.grant()
        self.assertTrue(self.store.require({}, 6, ['manage_claims'])['manage_claims'])

    def test_revoke_without_grant_still_persists_tombstone(self):
        self.store.revoke(6, 'Do not act on this issue', apply=True)
        with self.assertRaises(InstallError): self.store.require({'merge': True}, 6, ['merge'])

    def test_scope_replacement_is_rejected_and_original_preserved(self):
        self.grant()
        before = self.path.read_bytes()
        for apply in [False, True]:
            with self.assertRaises(InstallError): self.grant(issue=7, apply=apply)
            with self.assertRaises(InstallError): self.store.revoke(7, 'Withdraw', apply=apply)
        self.assertEqual(self.path.read_bytes(), before)

    def test_record_and_lock_are_private(self):
        self.grant()
        for path in [self.path, self.lock]: self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_invalid_grant_inputs_write_nothing(self):
        cases = [dict(issue=True), dict(issue=0), dict(issue='6'), dict(allow=['unknown']),
                 dict(allow='merge'), dict(allow=['merge', 'merge']), dict(deny=['merge'], allow=['merge']),
                 dict(deny=[None]), dict(evidence=''), dict(evidence='  '), dict(evidence='x\ny'),
                 dict(evidence='x' * 1001), dict(evidence=None)]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(InstallError): self.grant(**values)
        self.assertFalse(self.path.exists())

    def test_invalid_owner_and_binding_inputs_are_rejected(self):
        for owner in ['', '../B', 'a/b', 'A' * 101, None, 3]:
            with self.subTest(owner=owner), self.assertRaises(InstallError):
                self.module.Permissions(self.root, self.store.repository, 'main', owner)
        for branch in ['', 'bad branch', '-bad', 'refs/heads/../main', None]:
            with self.subTest(branch=branch), self.assertRaises(InstallError):
                self.module.Permissions(self.root, self.store.repository, branch, 'A')

    def test_corrupt_or_malformed_records_fail_closed(self):
        original = self.grant()
        cases = [b'{', b'null', b'[]', b'\xff']
        for key, value in [('version', True), ('version', 2), ('issue', True), ('allow', ['unknown']),
                           ('deny', ['manage_claims']), ('revoked', 1), ('evidence', 'x\ny'), ('owner', '../A')]:
            bad = dict(original); bad[key] = value; cases.append(json.dumps(bad).encode())
        for raw in cases:
            self.path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(InstallError): self.store.require({'merge': True}, 6, ['merge'])
            with self.assertRaises(InstallError): self.grant()

    def test_unignored_record_and_lock_paths_are_rejected_before_writes(self):
        for ignore in ['', '.local/agent/permissions/*.json\n', '.local/agent/permissions/*.lock\n']:
            (self.root / '.gitignore').write_text(ignore)
            with self.subTest(ignore=ignore), self.assertRaises(InstallError): self.grant()
            self.assertFalse(self.path.exists()); self.assertFalse(self.lock.exists())

    def test_tracked_record_or_lock_is_rejected(self):
        self.grant()
        for path in [self.path, self.lock]:
            relative = str(path.relative_to(self.root))
            self.git('add', '-f', relative)
            with self.assertRaises(InstallError): self.grant()
            with self.assertRaises(InstallError): self.store.require({'merge': True}, 6, ['merge'])
            self.git('rm', '--cached', '-f', relative)

    def test_existing_unignored_record_cannot_authorize(self):
        self.grant()
        (self.root / '.gitignore').write_text('')
        with self.assertRaises(InstallError): self.store.require({}, 6, ['manage_claims'])

    def test_symlink_record_lock_or_parent_is_rejected(self):
        self.grant()
        for path in [self.path, self.lock]:
            original = path.read_bytes(); path.unlink()
            outside = self.root / 'outside'; outside.write_bytes(original)
            path.symlink_to(outside)
            with self.assertRaises(InstallError): self.grant()
            with self.assertRaises(InstallError): self.store.status()
            self.assertEqual(outside.read_bytes(), original)
            path.unlink(); path.write_bytes(original)
        self.path.unlink(); self.lock.unlink(); self.path.parent.rmdir()
        self.path.parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(InstallError): self.grant()

    def test_unknown_required_capability_is_rejected(self):
        with self.assertRaises(InstallError): self.store.require({'unknown': True}, 6, ['unknown'])

    def test_concurrent_scope_changes_keep_one_authorization(self):
        barrier = threading.Barrier(2); records = []; errors = []
        def grant(issue):
            barrier.wait()
            try: records.append(self.grant(issue=issue))
            except InstallError as exc: errors.append(exc)
        threads = [threading.Thread(target=grant, args=(issue,)) for issue in [6, 7]]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(records), 1); self.assertEqual(len(errors), 1)
        self.assertEqual(self.store.status(), records[0])


if __name__ == '__main__': unittest.main()
