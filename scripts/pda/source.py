"""Fixed distribution identity and auditable local source revisions."""
import re
import hashlib
import subprocess

from .transaction import InstallError, RUNTIME, ASSETS

REPOSITORY = 'longwu1988/pensonal-dev-agent'
CHANNEL = 'main'
PROTOCOL = 4
STATIC = ('templates/project-guide.md', 'templates/project.json',
          'profiles/core.json', 'profiles/update.json', 'adapters/cursor/personal-dev.mdc') + tuple(
              'skills/personal-dev/' + name for name in ASSETS)


def revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise InstallError('expected a full 40-character commit SHA')
    return value


def identity(commit):
    return {'repository': REPOSITORY, 'channel': CHANNEL,
            'commit': revision(commit) if commit is not None else None}


def local_source(package):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(package), *args],
                                       stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    try:
        from pathlib import Path
        package = package.resolve()
        if Path(git('rev-parse', '--show-toplevel')).resolve() != package.resolve():
            return identity(None)
        if git('status', '--porcelain', '--untracked-files=all', '--',
               'skills/personal-dev', *RUNTIME, *STATIC):
            return identity(None)
        commit = git('rev-parse', 'HEAD')
        names = set(RUNTIME + STATIC)
        names.update(p.relative_to(package).as_posix()
                     for p in (package / 'skills/personal-dev').rglob('*.md'))
        tree = {}
        for record in git('ls-tree', '-r', '-z', commit, '--',
                          'skills/personal-dev', *RUNTIME, *STATIC).split('\0'):
            if not record:
                continue
            metadata, name = record.split('\t', 1)
            mode, kind, blob = metadata.split()
            if name in names or (name.startswith('skills/personal-dev/') and name.endswith('.md')):
                tree[name] = (mode, kind, blob)
        if set(tree) != names:
            return identity(None)
        for name, (mode, kind, blob) in tree.items():
            path = package / name
            if mode not in ('100644', '100755') or kind != 'blob' or path.is_symlink():
                return identity(None)
            if any((package / parent).is_symlink() for parent in Path(name).parents):
                return identity(None)
            data = path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if actual != blob:
                return identity(None)
        return identity(commit)
    except (OSError, subprocess.SubprocessError, ValueError):
        return identity(None)
