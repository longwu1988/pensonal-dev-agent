import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from pda.install import initialize, plan
from pda.transaction import InstallError, JOURNAL, atomic_write, journal, locked, recover


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.temp.cleanup()

    def test_mid_write_failure_has_recoverable_original_state(self):
        original = b"# Existing project rules\n"
        (self.root / "AGENTS.md").write_bytes(original)

        def fail(root, name, content, file_mode=0o644):
            if name == ".cursor/rules/personal-dev.mdc":
                raise OSError("simulated full disk")
            atomic_write(root, name, content, file_mode)

        with patch("pda.transaction.atomic_write", side_effect=fail):
            with self.assertRaisesRegex(InstallError, "write interrupted"):
                initialize(self.root, REPO, True)
        self.assertEqual(journal(self.root)["status"], "prepared")
        with self.assertRaisesRegex(InstallError, "incomplete transaction"):
            initialize(self.root, REPO, True)
        recover(self.root, True)
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), original)
        self.assertFalse((self.root / "docs/agents/README.md").exists())
        initialize(self.root, REPO, True)
        self.assertEqual(journal(self.root)["status"], "committed")

    def test_upgrade_then_recover_restores_previous_version(self):
        initialize(self.root, REPO, True)
        package = Path(self.temp.name) / "package"
        for directory in ("skills", "adapters", "templates", "profiles", "scripts"):
            shutil.copytree(REPO / directory, package / directory)
        source = package / "skills/personal-dev/SKILL.md"
        source.write_text(source.read_text() + "\nNew behavior for a synthetic upgrade.\n")
        installed = self.root / ".agents/skills/personal-dev/SKILL.md"
        old = installed.read_bytes()
        initialize(self.root, package, True)
        self.assertNotEqual(installed.read_bytes(), old)
        recover(self.root, True)
        self.assertEqual(installed.read_bytes(), old)
        self.assertEqual(plan(self.root, REPO), [])

    def test_manifest_allows_repeat_in_fresh_clone_without_local_state(self):
        initialize(self.root, REPO, True)
        clone = Path(self.temp.name) / "clone"
        shutil.copytree(self.root, clone, ignore=shutil.ignore_patterns(".local"))
        self.assertEqual(plan(clone, REPO), [])

    def test_recovery_is_repeatable_after_its_own_write_failure(self):
        initialize(self.root, REPO, True)
        calls = 0

        def fail(root, name, content, file_mode=0o644):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("simulated restore failure")
            atomic_write(root, name, content, file_mode)

        with patch("pda.transaction.atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                recover(self.root, True)
        self.assertEqual(journal(self.root)["status"], "prepared")
        recover(self.root, True)
        self.assertEqual(journal(self.root)["status"], "recovered")
        self.assertFalse((self.root / "AGENTS.md").exists())

    def test_concurrent_installer_lock_is_rejected(self):
        with locked(self.root):
            with self.assertRaisesRegex(InstallError, "another installer"):
                with locked(self.root):
                    self.fail("second writer acquired the lock")

    def test_journal_cannot_restore_outside_managed_paths(self):
        target = self.root / JOURNAL
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({
            "version": 1, "status": "prepared", "entries": [{
                "path": "../outside", "mode": 420, "before": None, "after": None,
            }],
        }))
        with self.assertRaisesRegex(InstallError, "unexpected recovery target"):
            recover(self.root, True)

    def test_user_changed_permissions_are_not_overwritten_by_recovery(self):
        (self.root / "AGENTS.md").write_text("# Rules\n")
        initialize(self.root, REPO, True)
        (self.root / "AGENTS.md").chmod(0o600)
        with self.assertRaisesRegex(InstallError, "permissions changed"):
            recover(self.root, True)

    def test_special_permissions_survive_install_and_recovery(self):
        target = self.root / "AGENTS.md"
        target.write_text("# Rules\n")
        target.chmod(0o1644)
        initialize(self.root, REPO, True)
        self.assertEqual(target.stat().st_mode & 0o7777, 0o1644)
        self.assertEqual(plan(self.root, REPO), [])
        recover(self.root, True)
        self.assertEqual(target.stat().st_mode & 0o7777, 0o1644)


if __name__ == "__main__":
    unittest.main()
