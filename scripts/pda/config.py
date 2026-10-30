"""Project-owned inputs; inferred facts never confer authorization."""
import json
from pathlib import PurePosixPath

from .transaction import InstallError, read

CONFIG = "docs/agents/project.json"


def relative(value, label):
    if not isinstance(value, str) or not value or "\\" in value:
        raise InstallError("invalid project path: " + label)
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise InstallError("path must stay inside project: " + label)


def validate(config, template):
    def shape(value, sample, key):
        if isinstance(sample, dict):
            if not isinstance(value, dict) or value.keys() != sample.keys():
                raise InstallError("invalid config keys: " + key)
            for name in sample:
                shape(value[name], sample[name], key + "." + name)
        elif sample is None:
            if value is not None and not isinstance(value, str):
                raise InstallError("expected string or null: " + key)
        elif type(value) is not type(sample):
            raise InstallError("invalid config type: " + key)
    shape(config, template, "config")
    if config["schema_version"] != 1:
        raise InstallError("unsupported project schema_version")
    if config["project"]["stage"] not in ("discovery", "existing"):
        raise InstallError("invalid project stage")
    if config["knowledge"]["schedule_enabled"]:
        raise InstallError("nightly scheduling is not implemented")
    for key in ("tech_stack", "architecture"):
        if config["decisions"][key] is not None:
            relative(config["decisions"][key], "decisions." + key)
    relative(config["worktree"]["fallback"], "worktree.fallback")
    for key in ("directory", "reports"):
        relative(config["knowledge"][key], "knowledge." + key)
    for app in config["apps"]:
        if not isinstance(app, dict) or set(app) != {"name", "path", "rules", "validation"}:
            raise InstallError("apps require name, path, rules and validation")
        if not isinstance(app["name"], str) or not isinstance(app["validation"], list):
            raise InstallError("invalid app name or validation")
        relative(app["path"], "app.path")
        if app["rules"] is not None:
            relative(app["rules"], "app.rules")
        for check in app["validation"]:
            if (not isinstance(check, dict) or set(check) != {"command", "environment"}
                    or not all(isinstance(v, str) and v for v in check.values())):
                raise InstallError("validation requires command and environment strings")
    if not all(isinstance(ref, str) for ref in config["figma"]["references"]):
        raise InstallError("figma references must be strings")
    return config


def project_config(root, package):
    template = json.loads((package / "templates/project.json").read_bytes())
    existing = read(root, CONFIG)
    if existing is not None:
        return validate(json.loads(existing), template)
    config = template
    config["project"]["name"] = root.name
    for child in sorted(root.iterdir()):
        if child.name.startswith(".") or child.is_symlink() or not child.is_dir():
            continue
        if (child / "AGENTS.md").is_file() and not (child / "AGENTS.md").is_symlink():
            config["apps"].append({
                "name": child.name, "path": child.name,
                "rules": child.name + "/AGENTS.md", "validation": [],
            })
    return validate(config, json.loads((package / "templates/project.json").read_bytes()))
