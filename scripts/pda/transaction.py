"""File transactions with conservative, repeatable recovery on macOS/Linux."""
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import PurePosixPath
import stat
import tempfile

RUNTIME = ('scripts/pda.py',) + tuple('scripts/pda/' + name + '.py' for name in (
    '__init__', 'config', 'install', 'transaction', 'source', 'remote', 'updates', 'issue_queue', 'issue_tracker', 'issue_watch', 'notifications', 'issue_claims', 'issue_workers', 'worker_dispatch', 'permissions'))
ASSETS = ('assets/question-pending.wav',)

JOURNAL = ".local/agent/install/transaction.json"
LOCK = ".local/agent/install/write.lock"


class InstallError(ValueError):
    pass


def safe_path(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or any(p in (".", "..") for p in parts):
        raise InstallError("unsafe path: " + relative)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise InstallError("symbolic link is not a managed target: " + relative)
        if current.exists():
            if index < len(parts) - 1 and not current.is_dir():
                raise InstallError("parent is not a directory: " + relative)
            if index == len(parts) - 1 and not current.is_file():
                raise InstallError("target is not a regular file: " + relative)
    return current


def read(root, relative):
    path = safe_path(root, relative)
    return path.read_bytes() if path.exists() else None


def mode(root, relative):
    path = safe_path(root, relative)
    return stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644


def atomic_write(root, relative, content, file_mode=0o644):
    path = safe_path(root, relative)
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pda-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, file_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def encode(data):
    return None if data is None else base64.b64encode(data).decode("ascii")


def decode(data):
    return None if data is None else base64.b64decode(data, validate=True)


def journal(root):
    content = read(root, JOURNAL)
    if content is None:
        return None
    value = json.loads(content)
    if not isinstance(value, dict) or value.get("version") != 1:
        raise InstallError("unsupported recovery journal")
    if value.get("status") not in ("prepared", "committed", "recovered"):
        raise InstallError("invalid recovery status")
    if not isinstance(value.get("entries"), list):
        raise InstallError("invalid recovery entries")
    seen = set()
    exact = {"AGENTS.md", ".gitignore", "docs/agents/project.json",
             "docs/agents/README.md", "docs/agents/personal-dev.lock.json",
             "docs/agents/personal-dev.dependencies.json",
             ".cursor/rules/personal-dev.mdc"}
    runtime = {".agents/skills/personal-dev/" + name for name in RUNTIME + ASSETS}
    for entry in value["entries"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise InstallError("invalid recovery entry")
        name = entry["path"]
        if name not in exact and name not in runtime and not (
            name.startswith(".agents/skills/personal-dev/") and name.endswith(".md")
        ):
            raise InstallError("unexpected recovery target: " + name)
        safe_path(root, name)
        if name in seen or type(entry.get("mode")) is not int:
            raise InstallError("duplicate target or invalid permissions")
        if not 0 <= entry["mode"] <= 0o7777:
            raise InstallError("invalid permissions")
        seen.add(name)
        decode(entry.get("before"))
        decode(entry.get("after"))
    return value


@contextmanager
def locked(root):
    path = safe_path(root, LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallError("another installer is writing this project") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_ready(root):
    value = journal(root)
    if value and value["status"] == "prepared":
        raise InstallError("incomplete transaction; run recover before init")


def apply_changes(root, changes):
    """Caller holds lock. Write-ahead journal covers every target before mutation."""
    ensure_ready(root)
    for change in changes:
        if read(root, change["path"]) != change["before"]:
            raise InstallError("conflict: file changed after preview: " + change["path"])
    value = {"version": 1, "status": "prepared", "entries": [
        {"path": c["path"], "before": encode(c["before"]), "after": encode(c["after"]),
         "mode": mode(root, c["path"])} for c in changes
    ]}
    atomic_write(root, JOURNAL, json_bytes(value), 0o600)
    try:
        for entry in value["entries"]:
            atomic_write(root, entry["path"], decode(entry["after"]), entry["mode"])
        value["status"] = "committed"
        atomic_write(root, JOURNAL, json_bytes(value), 0o600)
    except OSError as exc:
        raise InstallError("write interrupted; run recover: " + str(exc)) from exc


def recovery_changes(root, value):
    changes = []
    for entry in value["entries"]:
        current = read(root, entry["path"])
        before, after = decode(entry["before"]), decode(entry["after"])
        if current not in (before, after):
            raise InstallError("conflict: changed since install: " + entry["path"])
        if current is not None and mode(root, entry["path"]) != entry["mode"]:
            raise InstallError("conflict: permissions changed: " + entry["path"])
        if current != before:
            changes.append(entry)
    return changes


def recover(root, apply=False):
    value = journal(root)
    if value is None or value["status"] == "recovered":
        print("No transaction to recover.")
        return
    changes = recovery_changes(root, value)
    for entry in changes:
        print("RESTORE " + entry["path"])
    if not apply:
        print("Preview only. Use recover --apply to restore the last transaction.")
        return
    with locked(root):
        current_value = journal(root)
        if current_value != value:
            raise InstallError("transaction changed after preview; retry recover")
        changes = recovery_changes(root, value)
        # Recovery is itself restartable: both before/after states remain acceptable.
        value["status"] = "prepared"
        atomic_write(root, JOURNAL, json_bytes(value), 0o600)
        for entry in reversed(changes):
            atomic_write(root, entry["path"], decode(entry["before"]), entry["mode"])
        value["status"] = "recovered"
        atomic_write(root, JOURNAL, json_bytes(value), 0o600)
    print("Recovered. Local recovery journal retained; existing directories preserved.")


if __name__ == '__main__':
    # Keep recovery independent of the rest of the self-updating runtime.
    import argparse
    from pathlib import Path
    import sys
    parser = argparse.ArgumentParser(description='Standalone recovery of the last personal-dev install')
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        parser.error('project must be an existing directory')
    try:
        recover(root, args.apply)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
