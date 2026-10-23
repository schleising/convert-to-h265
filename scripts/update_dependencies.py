#!/usr/bin/env python3
"""Refresh git dependencies and write pip requirements for each role.

Run this on a machine that has uv. Docker and the macOS installer install the
generated requirements with pip and do not need uv.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

REQUIREMENTS = {
    "walker": ROOT / "walker" / "requirements.txt",
    "converter": ROOT / "backend" / "requirements.txt",
}


def git_package_names() -> list[str]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = project.get("tool")
    if not isinstance(tool, dict):
        return []
    uv_config = tool.get("uv")
    if not isinstance(uv_config, dict):
        return []
    sources = uv_config.get("sources")
    if not isinstance(sources, dict):
        return []

    names: list[str] = []
    for name, source in sources.items():
        if isinstance(name, str) and isinstance(source, dict) and "git" in source:
            names.append(name)
    return names


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    except FileNotFoundError:
        print(f"{args[0]} is required on this machine.", file=sys.stderr)
        raise SystemExit(1) from None


def main() -> None:
    packages = git_package_names()
    if packages:
        print("Updating git dependencies: " + ", ".join(packages))
        run(["uv", "lock", *(f"--upgrade-package={package}" for package in packages)])
    else:
        print("No git dependencies to update.")

    for group, destination in REQUIREMENTS.items():
        relative_destination = destination.relative_to(ROOT).as_posix()
        run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--no-default-groups",
                "--group",
                group,
                "--no-hashes",
                "--no-emit-project",
                "--output-file",
                relative_destination,
            ]
        )
        print(f"Wrote {relative_destination}")


if __name__ == "__main__":
    main()
