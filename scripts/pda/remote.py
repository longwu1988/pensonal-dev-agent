"""Read one fixed public GitHub source; verify data without executing its code."""
import ast
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .source import CHANNEL, PROTOCOL, REPOSITORY, RUNTIME, STATIC, revision
from .transaction import InstallError

API = 'https://api.github.com/repos/' + REPOSITORY
MAX_FILE = 1024 * 1024
MAX_TOTAL = 12 * MAX_FILE


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in ('api.github.com', 'codeload.github.com'):
            raise InstallError('unexpected download redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self):
        self.deadline = time.monotonic() + 45

    def get(self, path, binary=False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise InstallError('GitHub request deadline exceeded')
        request = urllib.request.Request(API + path, headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'personal-dev-updater',
            'X-GitHub-Api-Version': '2022-11-28'})
        try:
            with urllib.request.build_opener(Redirects()).open(request, timeout=min(8, remaining)) as response:
                chunks, size = [], 0
                while True:
                    if time.monotonic() > self.deadline:
                        raise InstallError('GitHub request deadline exceeded')
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_TOTAL:
                        raise InstallError('GitHub response exceeds size limit')
                    chunks.append(chunk)
                raw = b''.join(chunks)
            return raw if binary else json.loads(raw)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            # Do not echo response bodies, credentials or local proxy details.
            raise InstallError('GitHub unavailable or invalid response (' + type(exc).__name__ + ')') from exc


def latest():
    return revision(Client().get('/git/ref/heads/' + CHANNEL)['object']['sha'])


def compare(base, target):
    base, target = revision(base), revision(target)
    value = Client().get('/compare/' + base + '...' + target + '?per_page=20')
    status = value.get('status')
    if status not in ('ahead', 'behind', 'identical', 'diverged'):
        raise InstallError('invalid GitHub comparison')
    summary = []
    for item in value.get('commits', [])[:20]:
        line = item['commit']['message'].splitlines()[0][:240]
        summary.append(''.join(c for c in line if c.isprintable()))
    return {'status': status, 'summary': summary,
            'url': 'https://github.com/' + REPOSITORY + '/compare/' + base + '...' + target}


def selected(name):
    return name in RUNTIME or name in STATIC or (
        name.startswith('skills/personal-dev/') and name.endswith('.md'))


def validate_path(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or
            any(part in ('', '.', '..') for part in name.split('/'))):
        raise InstallError('invalid package path')


@contextmanager
def download(commit):
    commit = revision(commit)
    client = Client()
    tree = client.get('/git/trees/' + commit + '?recursive=1')
    if tree.get('truncated'):
        raise InstallError('source tree is truncated')
    entries = {}
    for item in tree['tree']:
        name = item['path']
        if name.startswith('scripts/pda/') and name.endswith('.py') and name not in RUNTIME:
            raise InstallError('unsupported runtime layout; use a reviewed full installer')
        if not selected(name):
            continue
        validate_path(name)
        if item.get('mode') not in ('100644', '100755') or item['type'] != 'blob':
            raise InstallError('package contains non-regular files')
        if name in entries or item.get('size', MAX_FILE + 1) > MAX_FILE:
            raise InstallError('invalid package entry or size')
        revision(item['sha'])
        entries[name] = item
    required = set(RUNTIME + STATIC) | {'skills/personal-dev/SKILL.md'}
    if not required.issubset(entries) or len(entries) > 200:
        raise InstallError('source lacks supported updater payload; use a reviewed full installer')
    raw = client.get('/tarball/' + commit, binary=True)
    with tempfile.TemporaryDirectory(prefix='pda-update-') as directory:
        root = Path(directory)
        found, total, archive_total, member_count = set(), 0, 0, 0
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r|gz') as archive:
                for member in archive:
                    archive_total += member.size
                    member_count += 1
                    if member.size < 0 or archive_total > MAX_TOTAL or member_count > 5000:
                        raise InstallError('archive exceeds size limit')
                    if time.monotonic() > client.deadline:
                        raise InstallError('package extraction deadline exceeded')
                    parts = member.name.split('/', 1)
                    if len(parts) != 2 or parts[1] not in entries:
                        continue
                    name = parts[1]
                    validate_path(member.name)
                    item = entries[name]
                    if (name in found or not member.isfile() or member.size != item['size']
                            or member.size > MAX_FILE):
                        raise InstallError('invalid archive entry')
                    total += member.size
                    if total > MAX_TOTAL:
                        raise InstallError('package exceeds size limit')
                    data = archive.extractfile(member).read(MAX_FILE + 1)
                    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                    if digest != item['sha']:
                        raise InstallError('package integrity mismatch')
                    if name.endswith('.py'):
                        ast.parse(data, filename=name)  # Syntax check only; never execute.
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    found.add(name)
            if found != set(entries):
                raise InstallError('incomplete package archive')
            if json.loads((root / 'profiles/update.json').read_bytes()) != {'protocol': PROTOCOL}:
                raise InstallError('unsupported update protocol; use a reviewed full installer')
        except (tarfile.TarError, SyntaxError, UnicodeError, EOFError) as exc:
            raise InstallError('invalid package archive or runtime') from exc
        yield root
