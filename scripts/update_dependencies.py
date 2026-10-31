#!/usr/bin/env python3
"""Upgrade every dependency and write pip requirements for each role.

Git sources pinned to a release tag move to the newest ``vMAJOR.MINOR.PATCH``
tag. Every package in the lock then moves to the newest release that satisfies
the project, including packages whose previous pin matched an old lower bound
in ``pyproject.toml``.

Run this on a machine that has uv. Docker and the macOS installer install the
generated requirements with pip and do not need uv.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
_RELEASE_TAG = re.compile(r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")

REQUIREMENTS = {
    "walker": ROOT / "walker" / "requirements.txt",
    "converter": ROOT / "backend" / "requirements.txt",
}


@dataclass(frozen=True)
class GitSource:
    name: str
    url: str
    tag: str | None


def git_sources() -> list[GitSource]:
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

    found: list[GitSource] = []
    for name, source in sources.items():
        if not isinstance(name, str) or not isinstance(source, dict) or "git" not in source:
            continue
        url = source.get("git")
        tag = source.get("tag")
        if not isinstance(url, str):
            continue
        found.append(GitSource(name, url, tag if isinstance(tag, str) else None))
    return found


def release_key(tag: str) -> tuple[int, int, int] | None:
    match = _RELEASE_TAG.fullmatch(tag)
    if match is None:
        return None
    return (int(match.group("major")), int(match.group("minor")), int(match.group("patch")))


def latest_release_tag(url: str) -> str | None:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", url],
        check=True,
        capture_output=True,
        text=True,
    )
    tags: list[tuple[tuple[int, int, int], str]] = []
    for line in result.stdout.splitlines():
        _commit, _separator, ref = line.partition("\t")
        if not ref.startswith("refs/tags/"):
            continue
        name = ref.removeprefix("refs/tags/")
        key = release_key(name)
        if key is not None:
            tags.append((key, name))
    if not tags:
        return None
    return max(tags)[1]


def pin_latest_release(source: GitSource) -> None:
    if source.tag is None:
        print(f"{source.name} has no release tag; refreshing its current git revision")
        return

    latest = latest_release_tag(source.url)
    if latest is None:
        print(f"No release tags found for {source.name}; leaving {source.tag}")
        return

    current_key = release_key(source.tag)
    latest_key = release_key(latest)
    if current_key is not None and latest_key is not None and latest_key <= current_key:
        print(f"{source.name} is already at {source.tag}")
        return

    text = PYPROJECT.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^({re.escape(source.name)}\s*=\s*\{{[^}}]*?tag\s*=\s*\")([^\"]+)(\")",
        re.MULTILINE,
    )
    updated, count = pattern.subn(rf"\g<1>{latest}\g<3>", text, count=1)
    if count != 1:
        print(f"Could not update the tag for {source.name} in {PYPROJECT.name}", file=sys.stderr)
        raise SystemExit(1)
    PYPROJECT.write_text(updated, encoding="utf-8")
    print(f"{source.name}: {source.tag} -> {latest}")


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    except FileNotFoundError:
        print(f"{args[0]} is required on this machine.", file=sys.stderr)
        raise SystemExit(1) from None


def main() -> None:
    sources = git_sources()
    if sources:
        print("Updating git dependencies: " + ", ".join(source.name for source in sources))
        for source in sources:
            pin_latest_release(source)
    else:
        print("No git dependencies to update.")

    print("Upgrading all dependencies to the latest versions")
    run(["uv", "lock", "--upgrade", "--no-managed-python"])
    run(["uv", "sync", "--no-managed-python"])

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
