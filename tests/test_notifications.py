import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from pda import notifications
from pda.install import initialize
from pda.transaction import InstallError, recover
from pda.source import identity


class NotificationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'SSH_CONNECTION': '', 'SSH_TTY': ''})
        environment.start()
        self.addCleanup(environment.stop)

    def test_offline_fixed_audio_and_player_arguments(self):
        with patch.object(notifications.sys, 'platform', 'darwin'), \
             patch.object(notifications.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            result = notifications.notify(REPO)
        self.assertEqual(result['status'], 'playback_finished')
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/usr/bin/afplay')
        self.assertEqual(Path(command[1]).name, 'question-pending.wav')
        self.assertLessEqual(run.call_args.kwargs['timeout'], 15)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_failures_do_not_stop_confirmation_or_claim_playback(self):
        for side_effect in (OSError('no device'), subprocess.TimeoutExpired('afplay', 12)):
            with self.subTest(error=type(side_effect).__name__), \
                 patch.object(notifications.sys, 'platform', 'darwin'), \
                 patch.object(notifications.subprocess, 'run', side_effect=side_effect):
                self.assertEqual(notifications.notify(REPO)['status'], 'unavailable')
        with patch.object(notifications.sys, 'platform', 'darwin'), \
             patch.object(notifications.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            self.assertEqual(notifications.notify(REPO)['status'], 'unavailable')

    def test_missing_or_tampered_asset_never_plays_or_regenerates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / 'assets/question-pending.wav'
            asset.parent.mkdir()
            for content in (None, b'not the reviewed audio'):
                if content is not None:
                    asset.write_bytes(content)
                with patch.object(notifications.sys, 'platform', 'darwin'), \
                     patch.object(notifications.subprocess, 'run') as run:
                    self.assertEqual(notifications.notify(root)['status'], 'unavailable')
                    run.assert_not_called()

    def test_unsupported_platform_is_explicit_and_does_not_play(self):
        with patch.object(notifications.sys, 'platform', 'linux'), \
             patch.object(notifications.subprocess, 'run') as run:
            result = notifications.notify(REPO)
        self.assertEqual(result['reason'], 'unsupported_platform')
        run.assert_not_called()

    def test_ssh_session_does_not_play_on_the_remote_machine(self):
        with patch.object(notifications.sys, 'platform', 'darwin'), \
             patch.dict(os.environ, {'SSH_CONNECTION': 'synthetic'}), \
             patch.object(notifications.subprocess, 'run') as run:
            result = notifications.notify(REPO)
        self.assertEqual(result['reason'], 'remote_session')
        run.assert_not_called()

    def test_install_preview_repeat_recovery_and_user_audio_conflict(self):
        # Keep the same source identity across preview, install and repeat;
        # otherwise a clean checkout records a distinct metadata transaction.
        with tempfile.TemporaryDirectory() as directory, \
             patch('pda.install.local_source', return_value=identity(None)):
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()), patch.object(notifications.subprocess, 'run') as run:
                initialize(root, REPO, False)
                self.assertFalse((root / '.agents').exists())
                initialize(root, REPO, True)
                run.assert_not_called()
            installed = root / '.agents/skills/personal-dev'
            asset = installed / 'assets/question-pending.wav'
            expected = (REPO / 'skills/personal-dev/assets/question-pending.wav').read_bytes()
            self.assertEqual(asset.read_bytes(), expected)
            with patch.object(notifications.sys, 'platform', 'darwin'), \
                 patch.object(notifications.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                self.assertEqual(notifications.notify(installed)['status'], 'playback_finished')
            config = (root / 'docs/agents/project.json').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                initialize(root, REPO, True)
                self.assertEqual((root / 'docs/agents/project.json').read_bytes(), config)
                asset.write_bytes(b'user audio')
                with self.assertRaises(InstallError): initialize(root, REPO, True)
                asset.write_bytes(expected)
                recover(root, True)
                self.assertFalse(asset.exists())


if __name__ == '__main__':
    unittest.main()
