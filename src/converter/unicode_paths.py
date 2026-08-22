"""Unicode-normalization helpers for filesystem paths (NFC vs NFD)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

_directory_cache: dict[Path, tuple[Path, ...]] = {}


def normalize_path(path: str) -> str:
    return unicodedata.normalize("NFC", path)


def path_identity_key(path: str) -> str:
    """Identity for same-file checks on case-insensitive APFS (NFC + casefold)."""
    return normalize_path(path).casefold()


def paths_equivalent(left: str, right: str) -> bool:
    return normalize_path(left) == normalize_path(right)


def paths_same_file(left: str, right: str) -> bool:
    return path_identity_key(left) == path_identity_key(right)


def find_equivalent_path(name: str, candidates: set[str]) -> str | None:
    target = path_identity_key(name)
    for candidate in candidates:
        if path_identity_key(candidate) == target:
            return candidate
    return None


def clear_directory_cache() -> None:
    _directory_cache.clear()


def _iter_dir_entries(parent: Path) -> tuple[Path, ...]:
    cached = _directory_cache.get(parent)
    if cached is not None:
        return cached
    try:
        entries = tuple(parent.iterdir())
    except OSError:
        entries = ()
    _directory_cache[parent] = entries
    return entries


def _resolve_name_in_directory(parent: Path, name: str) -> Path:
    if not parent.is_dir():
        return parent / name

    direct = parent / name
    if direct.exists():
        return direct

    target = path_identity_key(name)
    for entry in _iter_dir_entries(parent):
        if path_identity_key(entry.name) == target:
            return entry
    return direct


def resolve_filesystem_path(path: Path) -> Path:
    if path.exists():
        return path

    if not path.parts:
        return path

    resolved = Path(path.parts[0])
    for part in path.parts[1:]:
        resolved = _resolve_name_in_directory(resolved, part)
    return resolved


def map_to_db_path(local_path: Path, local_root: Path, db_root: Path) -> str:
    native_path = resolve_filesystem_path(local_path)
    relative_path = native_path.relative_to(local_root)
    return (db_root / relative_path).as_posix()
