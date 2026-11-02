"""Build a fixed install plan without changing project-owned configuration."""
import difflib
import hashlib
import json
import shutil

from .config import CONFIG, project_config
from .source import RUNTIME, ASSETS, local_source
from .transaction import (
    InstallError, JOURNAL, LOCK, apply_changes, ensure_ready, json_bytes,
    locked, read, safe_path,
)

MANIFEST = "docs/agents/personal-dev.lock.json"
BEGIN = b"<!-- personal-dev:begin -->"
END = b"<!-- personal-dev:end -->"
IGNORE_BEGIN = b"# personal-dev:begin"
IGNORE_END = b"# personal-dev:end"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def resources(package):
    files = {
        "docs/agents/README.md": (package / "templates/project-guide.md").read_bytes(),
        "docs/agents/personal-dev.dependencies.json": (package / "profiles/core.json").read_bytes(),
        ".cursor/rules/personal-dev.mdc": (package / "adapters/cursor/personal-dev.mdc").read_bytes(),
    }
    for name in RUNTIME:
        files[".agents/skills/personal-dev/" + name] = (package / name).read_bytes()
    source = package / "skills/personal-dev"
    for name in ASSETS:
        files[".agents/skills/personal-dev/" + name] = (source / name).read_bytes()
    for path in sorted(source.rglob("*.md")):
        files[".agents/skills/personal-dev/" + path.relative_to(source).as_posix()] = path.read_bytes()
    if ".agents/skills/personal-dev/SKILL.md" not in files:
        raise InstallError("package has no personal-dev skill")
    return files


def block_parts(data, begin, end):
    if data.count(begin) == data.count(end) == 0:
        return data, None, b""
    if data.count(begin) != 1 or data.count(end) != 1:
        raise InstallError("conflict: invalid managed block markers")
    start, stop = data.index(begin), data.index(end)
    if stop <= start:
        raise InstallError("conflict: reversed managed block markers")
    stop += len(end)
    return data[:start], data[start:stop], data[stop:]


def merge_block(current, desired, old_hash, begin, end):
    prefix, existing, suffix = block_parts(current or b"", begin, end)
    if existing is None:
        if old_hash is not None:
            raise InstallError("conflict: previously managed block removed")
        separator = b"" if not prefix else (b"\n" if prefix.endswith(b"\n") else b"\n\n")
        return prefix + separator + desired + b"\n"
    if old_hash is None or digest(existing) != old_hash:
        raise InstallError("conflict: unmanaged or edited block")
    return prefix + desired + suffix


def plan(root, package, source=None):
    ensure_ready(root)
    safe_path(root, JOURNAL)
    safe_path(root, LOCK)
    config = project_config(root, package)
    previous_bytes = read(root, MANIFEST)
    previous = {"schema_version": 1, "files": {}, "blocks": {}}
    if previous_bytes is not None:
        previous = json.loads(previous_bytes)
        if (not isinstance(previous, dict) or previous.get("schema_version") != 1
                or not isinstance(previous.get("files"), dict)
                or not isinstance(previous.get("blocks"), dict)):
            raise InstallError("invalid ownership manifest")
    desired = resources(package)
    # Version removals need a deliberate migration, never implicit deletion.
    if set(previous["files"]) - set(desired):
        raise InstallError("package removes managed files; manual migration required")
    for name, content in desired.items():
        actual = read(root, name)
        old_hash = previous["files"].get(name)
        if old_hash is not None:
            if actual is None or digest(actual) != old_hash:
                raise InstallError("conflict: edited or missing managed file: " + name)
        elif actual is not None:
            raise InstallError("conflict: existing unowned file: " + name)
    manifest = {
        "schema_version": 1,
        "files": {name: digest(content) for name, content in desired.items()},
        "blocks": {},
        "source": local_source(package) if source is None else source,
    }
    blocks = {
        "AGENTS.md": (BEGIN, END,
            "工程建设、需求开发、Bug 修复、验收反馈或提交/push/合并续聊时，读取 "
            "[个人开发入口](.agents/skills/personal-dev/SKILL.md)，"
            "并按需查阅 [工程配置](docs/agents/README.md)。"
            "业务约束继续遵循目标目录规则；纯咨询无需启动开发流程。"),
        ".gitignore": (IGNORE_BEGIN, IGNORE_END, "/.local/agent/"),
    }
    for name, (begin, end, body) in blocks.items():
        block = begin + b"\n" + body.encode() + b"\n" + end
        manifest["blocks"][name] = digest(block)
        desired[name] = merge_block(
            read(root, name), block, previous["blocks"].get(name), begin, end,
        )
    if read(root, CONFIG) is None:
        desired[CONFIG] = json_bytes(config)
    desired[MANIFEST] = json_bytes(manifest)
    changes = []
    for name, after in desired.items():
        before = read(root, name)
        if before != after:
            changes.append({"path": name, "before": before, "after": after})
    return changes


def show(changes):
    if not changes:
        print("No changes.")
    for change in changes:
        name = change["path"]
        print(("CREATE " if change["before"] is None else "UPDATE ") + name)
        try:
            if b'\0' in (change['before'] or b'') or b'\0' in change['after']:
                raise UnicodeError('binary payload')
            before = (change["before"] or b"").decode("utf-8").splitlines(keepends=True)
            after = change["after"].decode("utf-8").splitlines(keepends=True)
        except UnicodeError:
            print('Binary resource: ' + str(len(change['after'])) + ' bytes; SHA256 ' + digest(change['after']))
            continue
        print("".join(difflib.unified_diff(before, after, fromfile=name, tofile=name)), end="")


def show_next_steps(root, *, updated=False):
    """Display the installed guide's quick start without duplicating its prompts."""
    print("\n下一步：在目标工程的新会话中发送任务。")
    if updated:
        print("更新后请在新会话读取规则；已有任务按原进度核对后续接。")
    try:
        guide = (read(root, "docs/agents/README.md") or b"").decode("utf-8")
        heading = "\n## 快速开始\n"
        section = guide.split(heading, 1)[1].split("\n## ", 1)[0].strip() if heading in guide else ""
    except (OSError, UnicodeError, InstallError):
        section = ""
    if section:
        print(section)
    else:
        print("使用案例与注意事项请查看 docs/agents/README.md。")


def initialize(root, package, apply=False):
    previously_installed = read(root, MANIFEST) is not None
    changes = plan(root, package)
    show(changes)
    if not apply:
        print("Preview only. Use init --apply to write.")
    elif changes:
        with locked(root):
            if plan(root, package) != changes:
                raise InstallError("project changed after preview; retry init")
            apply_changes(root, changes)
        print("Installed locally. External dependencies and host behavior remain unverified.")
    if apply:
        if not changes:
            print("接入文件无变化，可继续使用。")
        show_next_steps(root, updated=previously_installed and bool(changes))


def doctor(root, package):
    config = project_config(root, package)
    profile = json.loads((package / "profiles/core.json").read_bytes())
    skills = []
    for source in profile["sources"]:
        for skill in source["skills"]:
            paths = [".agents/skills/" + skill["name"] + "/SKILL.md",
                     ".cursor/skills/" + skill["name"] + "/SKILL.md"]
            matches = []
            for path in paths:
                # Inspection can follow installed upstream symlinks; never writes them.
                local = root / path
                if local.is_file():
                    matches.append({"path": path, "entry_hash_matches": digest(local.read_bytes()) == skill["sha256"]})
            skills.append({"name": skill["name"], "local_entries": matches,
                           "transitive_dependencies": "not_verified"})
    issues = []
    for label, value in (
        ("integration_branch", config["project"]["integration_branch"]),
        ("tracker_repository", config["project"]["tracker"]["repository"]),
        ("tech_stack_decision", config["decisions"]["tech_stack"]),
    ):
        if not value:
            issues.append(label)
    if any(not app["validation"] for app in config["apps"]):
        issues.append("app_validation_commands")
    return {
        "installation": "present" if read(root, MANIFEST) is not None else "absent",
        "config": "present" if read(root, CONFIG) is not None else "not_created",
        "missing_project_inputs": issues, "candidate_skills": skills,
        "openspec_cli_on_path": shutil.which("openspec") is not None,
        "figma_config_files": [p for p in (".mcp.json", ".cursor/mcp.json") if (root / p).is_file()],
        "external_connections": "not_checked", "host_behavior": "not_verified",
        "delivery": {"provider": config["delivery"]["provider"],
                     "trigger": config["delivery"]["trigger"],
                     "status": config["delivery"]["status"], "inspected": False},
        # Legacy output keys remain available; other providers are not Drone.
        "drone_status_from_project": (config["delivery"]["status"]
                                      if config["delivery"]["provider"] == "drone" else None),
        "drone_inspected": False, "nightly_scheduler": "not_implemented",
    }
