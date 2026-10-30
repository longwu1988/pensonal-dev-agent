#!/usr/bin/env python3
"""Auditable local project integration. No network or shell execution."""
import argparse
import json
from pathlib import Path
import sys

from pda.install import doctor, initialize
from pda.transaction import recover, InstallError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "doctor", "recover"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="apply displayed changes")
    args = parser.parse_args()
    root = args.project.expanduser().resolve()
    if not root.is_dir():
        parser.error("project must be an existing directory")
    package = Path(__file__).resolve().parents[1]
    try:
        if args.action == "doctor":
            if args.apply:
                parser.error("doctor is read-only")
            print(json.dumps(doctor(root, package), ensure_ascii=False, indent=2))
        elif args.action == "init":
            initialize(root, package, args.apply)
        else:
            recover(root, args.apply)
    except (InstallError, OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
