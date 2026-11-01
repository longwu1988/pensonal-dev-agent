"""Play the reviewed local confirmation prompt; never synthesize or fetch speech."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from .transaction import InstallError, safe_path

ASSET = 'assets/question-pending.wav'
SHA256 = '9fe477010873a1155d7d7305a830f812f20f9a5ec8d5878c88b1d5d6aaa516f6'


def notify(package):
    """Best-effort notification. Success means player exit 0, not human receipt."""
    if os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'):
        return {'status': 'unavailable', 'reason': 'remote_session'}
    if sys.platform != 'darwin':
        return {'status': 'unavailable', 'reason': 'unsupported_platform'}
    try:
        package = Path(package)
        # Source checkout and installed runtime have different resource roots.
        root = package / 'skills/personal-dev' if (package / 'templates/project.json').is_file() else package
        path = safe_path(root, ASSET)
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            return {'status': 'unavailable', 'reason': 'missing_or_invalid_audio'}
        if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
            return {'status': 'unavailable', 'reason': 'audio_integrity'}
        result = subprocess.run(['/usr/bin/afplay', str(path)], capture_output=True,
                                timeout=12, check=False)
        if result.returncode:
            return {'status': 'unavailable', 'reason': 'player_failed'}
        return {'status': 'playback_finished', 'receipt': 'not_verified'}
    except (OSError, InstallError, subprocess.TimeoutExpired):
        return {'status': 'unavailable', 'reason': 'player_or_audio_unavailable'}
