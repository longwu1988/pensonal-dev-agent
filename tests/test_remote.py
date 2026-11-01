import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from pda import remote
from pda.source import RUNTIME, STATIC
from pda.transaction import InstallError


class DownloadTests(unittest.TestCase):
    def payload(self, edits=None):
        files = {name: (REPO / name).read_bytes() for name in RUNTIME + STATIC}
        files['skills/personal-dev/SKILL.md'] = b'# Synthetic skill\n'
        files.update(edits or {})
        tree = {'tree': [{'path': name, 'mode': '100644', 'type': 'blob', 'size': len(data),
                         'sha': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}
                        for name, data in files.items()], 'truncated': False}
        return files, tree

    def archive(self, files, link=None):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for name, data in files.items():
                info = tarfile.TarInfo('synthetic-root/' + name)
                if name == link:
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/tmp/outside'
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        return buffer.getvalue()

    def test_pinned_payload_verified_without_running_remote_python(self):
        marker = 'raise RuntimeError("remote code must not execute")\n'
        files, tree = self.payload({'scripts/pda.py': marker.encode()})
        with patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]) as get:
            with remote.download('a' * 40) as root:
                self.assertEqual((root / 'scripts/pda.py').read_text(), marker)
                self.assertEqual(get.call_args_list[1].args[0], '/tarball/' + 'a' * 40)
            self.assertFalse(root.exists())

    def test_blob_tamper_protocol_and_symlink_rejected(self):
        files, tree = self.payload()
        bad = dict(files, **{'skills/personal-dev/SKILL.md': b'# Tampered skill!\n'})
        for archive in (self.archive(bad), self.archive(files, 'scripts/pda.py')):
            with patch.object(remote.Client, 'get', side_effect=[tree, archive]):
                with self.assertRaises(InstallError):
                    with remote.download('a' * 40):
                        self.fail('unsafe payload accepted')
        files, tree = self.payload({'profiles/update.json': b'{"protocol": 999}'})
        with patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'unsupported update protocol'):
                with remote.download('a' * 40):
                    self.fail('incompatible update accepted')

    def test_unsafe_tree_missing_runtime_and_truncated_tree_rejected(self):
        _, base = self.payload()
        cases = [dict(base, truncated=True), dict(base, tree=base['tree'][1:]),
                 dict(base, tree=base['tree'] + [{'path': 'skills/personal-dev/../../escape.md', 'mode': '100644', 'type': 'blob', 'size': 1, 'sha': 'a' * 40}])]
        for tree in cases:
            with patch.object(remote.Client, 'get', return_value=tree) as get:
                with self.assertRaises(InstallError):
                    with remote.download('a' * 40):
                        self.fail('invalid tree accepted')
                self.assertEqual(get.call_count, 1)

    def test_unknown_runtime_module_requires_protocol_migration(self):
        files, tree = self.payload({'scripts/pda/new_required.py': b'# new runtime module\n'})
        with patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a' * 40):
                    self.fail('partial runtime accepted')

    def test_protocol_one_updater_refuses_queue_layout_and_protocol(self):
        files, tree = self.payload()
        self.assertIn('scripts/pda/issue_queue.py', list(files))
        old_runtime = tuple(name for name in remote.RUNTIME if name not in
                            ('scripts/pda/issue_queue.py', 'scripts/pda/issue_tracker.py'))
        with patch.object(remote, 'RUNTIME', old_runtime), patch.object(remote.Client, 'get', return_value=tree):
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a' * 40): self.fail('old updater accepted partial queue runtime')
        with patch.object(remote, 'PROTOCOL', 1), patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'protocol'):
                with remote.download('a' * 40): self.fail('old protocol accepted')

    def test_protocol_two_refuses_partial_watch_upgrade(self):
        files, tree = self.payload()
        old_runtime = tuple(name for name in remote.RUNTIME if name != 'scripts/pda/issue_watch.py')
        with patch.object(remote, 'RUNTIME', old_runtime), patch.object(remote.Client, 'get', return_value=tree):
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a'*40): self.fail('partial watch runtime accepted')
        with patch.object(remote, 'PROTOCOL', 2), patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'protocol'):
                with remote.download('a'*40): self.fail('old protocol accepted watch')

    def test_large_unselected_member_is_rejected_before_decompression(self):
        files, tree = self.payload()
        # A sparse-looking tar header claims a huge file; no need to allocate it.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            info = tarfile.TarInfo('synthetic-root/irrelevant.bin')
            info.size = remote.MAX_TOTAL + 1
            archive.addfile(info)
        with patch.object(remote.Client, 'get', side_effect=[tree, buffer.getvalue()]):
            with self.assertRaisesRegex(InstallError, 'size limit'):
                with remote.download('a' * 40):
                    self.fail('oversized archive accepted')

    def test_protocol_three_refuses_partial_audio_upgrade(self):
        files, tree = self.payload()
        old_runtime = tuple(n for n in remote.RUNTIME if n != 'scripts/pda/notifications.py')
        old_static = tuple(n for n in remote.STATIC if not n.endswith('.wav'))
        with patch.object(remote, 'RUNTIME', old_runtime), patch.object(remote, 'STATIC', old_static), \
             patch.object(remote.Client, 'get', return_value=tree):
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a' * 40): self.fail('partial audio runtime accepted')
        with patch.object(remote, 'PROTOCOL', 3), \
             patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'protocol'):
                with remote.download('a' * 40): self.fail('old protocol accepted audio update')

    def test_audio_asset_download_integrity_and_presence(self):
        name = 'skills/personal-dev/assets/question-pending.wav'
        files, tree = self.payload()
        with patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with remote.download('a' * 40) as root:
                self.assertEqual((root / name).read_bytes(), files[name])
        bad = dict(files, **{name: b'bad audio'})
        with patch.object(remote.Client, 'get', side_effect=[tree, self.archive(bad)]):
            with self.assertRaises(InstallError):
                with remote.download('a' * 40): self.fail('tampered audio accepted')
        absent = dict(tree, tree=[item for item in tree['tree'] if item['path'] != name])
        with patch.object(remote.Client, 'get', return_value=absent):
            with self.assertRaises(InstallError):
                with remote.download('a' * 40): self.fail('missing audio accepted')


    def test_protocol_four_refuses_partial_worker_upgrade(self):
        files, tree = self.payload()
        added = {'scripts/pda/'+name+'.py' for name in ('issue_claims','issue_workers','worker_dispatch')}
        old_runtime = tuple(name for name in remote.RUNTIME if name not in added)
        with patch.object(remote, 'RUNTIME', old_runtime), patch.object(remote.Client, 'get', return_value=tree):
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a'*40): self.fail('partial worker runtime accepted')
        with patch.object(remote, 'PROTOCOL', 4), patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'protocol'):
                with remote.download('a'*40): self.fail('old protocol accepted worker update')


    def test_protocol_five_refuses_partial_permissions_upgrade(self):
        files, tree = self.payload()
        added = 'scripts/pda/permissions.py'
        self.assertIn(added, files)
        self.assertEqual(json.loads(files['profiles/update.json']), {'protocol': 6})
        old_runtime = tuple(name for name in remote.RUNTIME if name != added)
        with patch.object(remote, 'RUNTIME', old_runtime), patch.object(remote, 'PROTOCOL', 5), \
             patch.object(remote.Client, 'get', return_value=tree) as get:
            with self.assertRaisesRegex(InstallError, 'runtime'):
                with remote.download('a' * 40): self.fail('old updater accepted partial permission runtime')
            self.assertEqual(get.call_count, 1)
        with patch.object(remote, 'PROTOCOL', 5), \
             patch.object(remote.Client, 'get', side_effect=[tree, self.archive(files)]):
            with self.assertRaisesRegex(InstallError, 'protocol'):
                with remote.download('a' * 40): self.fail('old protocol accepted permission update')
        missing = dict(tree, tree=[item for item in tree['tree'] if item['path'] != added])
        with patch.object(remote.Client, 'get', return_value=missing) as get:
            with self.assertRaisesRegex(InstallError, 'lacks supported updater payload'):
                with remote.download('a' * 40): self.fail('new updater accepted missing permission runtime')
            self.assertEqual(get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
