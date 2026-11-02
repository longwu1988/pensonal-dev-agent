import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "scripts/pda.py"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(CLI), *args, "--project", str(self.root)],
            capture_output=True, text=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def test_preview_is_read_only(self):
        result = self.run_cli("init")
        self.assertIn("AGENTS.md", result.stdout)
        self.assertIn("+", result.stdout)
        self.assertNotIn("\n下一步：", result.stdout)
        self.assertEqual(self.snapshot(), {})

    def test_install_repeat_and_recover_preserves_existing_files(self):
        original = b"# Existing rules\r\nKeep all business constraints.\r\n"
        (self.root / "AGENTS.md").write_bytes(original)
        (self.root / "AGENTS.md").chmod(0o640)
        (self.root / ".gitignore").write_bytes(b"build/\n")
        (self.root / ".mcp.json").write_bytes(b'{"keep":"untouched"}')
        before = self.snapshot()
        result = self.run_cli("init", "--apply")
        guide = (self.root / "docs/agents/README.md").read_text()
        quick_start = guide.split("\n## 快速开始\n", 1)[1].split("\n## ", 1)[0].strip()
        self.assertIn("\n下一步：", result.stdout)
        self.assertIn(quick_start, result.stdout)
        self.assertTrue((self.root / "AGENTS.md").read_bytes().startswith(original))
        self.assertEqual((self.root / "AGENTS.md").stat().st_mode & 0o777, 0o640)
        self.assertTrue((self.root / ".agents/skills/personal-dev/SKILL.md").is_file())
        after = self.snapshot()
        repeated = self.run_cli("init", "--apply")
        self.assertIn("接入文件无变化", repeated.stdout)
        self.assertIn(quick_start, repeated.stdout)
        self.assertEqual(self.snapshot(), after)
        self.run_cli("recover", "--apply")
        actual = {p: v for p, v in self.snapshot().items() if not p.startswith(".local/")}
        self.assertEqual(actual, before)

    def test_new_project_does_not_select_drone_or_require_ci(self):
        self.run_cli('init', '--apply')
        value = json.loads((self.root / 'docs/agents/project.json').read_text())
        self.assertIsNone(value['delivery']['provider'])
        self.assertIsNone(value['delivery']['trigger'])
        report = json.loads(self.run_cli('doctor').stdout)
        self.assertIsNone(report['delivery']['provider'])
        self.assertFalse(report['delivery']['inspected'])
        self.assertIsNone(report['drone_status_from_project'])
        self.assertFalse(any('delivery' in item or 'drone' in item or 'ci' == item
                             for item in report['missing_project_inputs']))

    def test_delivery_choices_survive_upgrade_and_doctor_reports_actual_provider(self):
        self.run_cli('init', '--apply')
        path = self.root / 'docs/agents/project.json'
        for provider, trigger, status in [('drone', 'tag', 'user-confirmed'),
                                          ('github-actions', 'manual', 'user-confirmed'),
                                          ('manual', 'manual', 'user-confirmed'),
                                          ('none', None, 'not-applicable')]:
            with self.subTest(provider=provider):
                config = json.loads(path.read_text())
                config['delivery'] = dict(provider=provider, trigger=trigger, status=status, evidence='project decision')
                path.write_text(json.dumps(config))
                before = path.read_bytes()
                self.run_cli('init', '--apply')
                self.assertEqual(path.read_bytes(), before)
                report = json.loads(self.run_cli('doctor').stdout)
                self.assertEqual(report['delivery'],dict(provider=provider,trigger=trigger,status=status,inspected=False))
                self.assertEqual(report['drone_status_from_project'],status if provider=='drone' else None)

    def test_user_config_and_outside_block_edits_survive_repeat(self):
        self.run_cli("init", "--apply")
        config = self.root / "docs/agents/project.json"
        value = json.loads(config.read_text())
        value["project"]["integration_branch"] = "release-current"
        config.write_text(json.dumps(value))
        agents = self.root / "AGENTS.md"
        agents.write_text("My new rules\n" + agents.read_text())
        self.run_cli("init", "--apply")
        self.assertEqual(json.loads(config.read_text()), value)
        self.assertTrue(agents.read_text().startswith("My new rules\n"))

    def test_modified_owned_file_blocks_every_write(self):
        self.run_cli("init", "--apply")
        skill = self.root / ".agents/skills/personal-dev/SKILL.md"
        skill.write_text("user customization")
        before = self.snapshot()
        result = self.run_cli("init", "--apply", ok=False)
        self.assertIn("conflict", result.stderr.lower())
        self.assertNotIn("\n下一步：", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_unowned_collision_is_not_adopted(self):
        target = self.root / ".cursor/rules/personal-dev.mdc"
        target.parent.mkdir(parents=True)
        target.write_text("user rule")
        before = self.snapshot()
        self.run_cli("init", "--apply", ok=False)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_refuses_post_install_edits(self):
        self.run_cli("init", "--apply")
        agents = self.root / "AGENTS.md"
        agents.write_text(agents.read_text() + "\nnew user edit\n")
        before = self.snapshot()
        self.run_cli("recover", "--apply", ok=False)
        self.assertEqual(self.snapshot(), before)

    def test_symlink_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / ".agents").symlink_to(outside, target_is_directory=True)
            self.run_cli("init", "--apply", ok=False)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_malformed_config_and_markers_are_rejected(self):
        path = self.root / "docs/agents/project.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"schema_version":999}')
        before = self.snapshot()
        self.run_cli("init", "--apply", ok=False)
        self.assertEqual(self.snapshot(), before)
        path.unlink()
        (self.root / "AGENTS.md").write_text("<!-- personal-dev:begin -->\nunclosed")
        self.run_cli("init", "--apply", ok=False)

    def test_doctor_is_read_only_and_honest_about_connections(self):
        before = self.snapshot()
        result = self.run_cli("doctor")
        report = json.loads(result.stdout)
        self.assertEqual(report["external_connections"], "not_checked")
        self.assertEqual(report["installation"], "absent")
        self.assertEqual(self.snapshot(), before)
        self.run_cli("init", "--apply")
        report = json.loads(self.run_cli("doctor").stdout)
        self.assertEqual(report["installation"], "present")
        self.assertEqual(report["host_behavior"], "not_verified")

    def test_upgrade_preserves_project_owned_lifecycle_stage(self):
        self.run_cli('init', '--apply')
        path = self.root / 'docs/agents/project.json'
        for stage in ('test-deployed', 'delivered-test'):
            value = json.loads(path.read_text())
            value['project']['stage'] = stage
            path.write_text(json.dumps(value))
            before = path.read_bytes()
            self.run_cli('init', '--apply')
            self.assertEqual(path.read_bytes(), before)

    def test_upgrade_preserves_project_app_shorthand_without_executing_commands(self):
        self.run_cli('init', '--apply')
        path = self.root / 'docs/agents/project.json'
        value = json.loads(path.read_text())
        value['apps'] = [{'name': 'web', 'directory': 'web', 'test': 'echo must-not-run', 'build': 'echo must-not-run'}]
        path.write_text(json.dumps(value))
        before = path.read_bytes()
        result = self.run_cli('init', '--apply')
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('must-not-run', result.stdout)
        self.assertEqual(json.loads(self.run_cli('doctor').stdout)['config'], 'present')
        value['apps'][0]['directory'] = '../outside'
        path.write_text(json.dumps(value))
        self.run_cli('init', '--apply', ok=False)

    def test_invalid_lifecycle_stage_is_rejected(self):
        self.run_cli('init', '--apply')
        path = self.root / 'docs/agents/project.json'
        for stage in ('', 'bad\nstage', True):
            value = json.loads(path.read_text())
            value['project']['stage'] = stage
            path.write_text(json.dumps(value))
            self.run_cli('init', '--apply', ok=False)

    def test_placeholder_readme_is_not_a_confirmed_stack_decision(self):
        (self.root / "README.md").write_text("# New project\n")
        report = json.loads(self.run_cli("doctor").stdout)
        self.assertIn("tech_stack_decision", report["missing_project_inputs"])
        self.run_cli("init", "--apply")
        config = json.loads((self.root / "docs/agents/project.json").read_text())
        self.assertIsNone(config["decisions"]["tech_stack"])
        self.assertEqual(config["project"]["stage"], "discovery")


if __name__ == "__main__":
    unittest.main()
