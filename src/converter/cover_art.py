"""Resolve Converter cover-art URLs for web push notifications.

Cache keys must match website3 `tools/converter/art/identity.py`.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

QUALITY_TOKENS = re.compile(
    r"\b(bluray|blu-ray|webdl|web-dl|webrip|hdtv|remux|x264|x265|h264|h265|"
    r"hevc|aac|dts|truehd|atmos|hdr|dv|2160p|1080p|720p|480p|proper|repack)\b",
    re.IGNORECASE,
)
YEAR_IN_PARENS = re.compile(r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2})\)$")
YEAR_AT_END = re.compile(r"^(?P<title>.+?)\s+(?P<year>19\d{2}|20\d{2})$")

DEFAULT_ICON = "/icons/tools/converter/android-chrome-192x192-20260504.png"
DEFAULT_BADGE = "/icons/tools/converter/badge-192x192-v2-0-2.png"
# Absolute origin for notification fetches (OS/browser often has no tools-auth cookies).
CONVERTER_PUBLIC_ORIGIN = "https://converter.schleising.net"
ART_PATH_PREFIX = "/tools/converter/art"


def normalize_title(value: str) -> str:
    cleaned = QUALITY_TOKENS.sub(" ", value)
    cleaned = re.sub(r"[._]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _slug_for_cache(value: str) -> str:
    slug = normalize_title(value)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "unknown"


def _strip_quality_and_ext(name: str) -> str:
    stem = Path(name).stem
    cleaned = QUALITY_TOKENS.sub(" ", stem)
    cleaned = re.sub(r"[._]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _parse_title_year(folder_or_name: str) -> tuple[str, int | None]:
    text = folder_or_name.strip()
    year_match = YEAR_IN_PARENS.match(text)
    if year_match is not None:
        return year_match.group("title").strip(), int(year_match.group("year"))

    year_match = YEAR_AT_END.match(text)
    if year_match is not None:
        return year_match.group("title").strip(), int(year_match.group("year"))

    return text, None


def _path_parts(source_path: str) -> list[str]:
    normalized = unquote(source_path.replace("\\", "/")).strip("/")
    return [part for part in normalized.split("/") if part]


def cache_key_for_path(source_path: str) -> str | None:
    """Return the cover_art_cache key for a media path, or None if unknown."""
    parts = _path_parts(source_path)
    lowered = [part.lower() for part in parts]

    if "films" in lowered:
        films_index = lowered.index("films")
        basename = parts[-1] if parts else Path(source_path).name
        folder: str | None = None
        if films_index + 1 < len(parts) - 1:
            folder = parts[films_index + 1]
        if folder:
            title, year = _parse_title_year(folder)
        else:
            title, year = _parse_title_year(_strip_quality_and_ext(basename))
        cache_key = f"film:{_slug_for_cache(title)}"
        if year is not None:
            cache_key = f"{cache_key}:{year}"
        return cache_key

    if "tv" in lowered:
        tv_index = lowered.index("tv")
        show = "Unknown Show"
        if tv_index + 1 < len(parts):
            show = parts[tv_index + 1]
        return f"tvshow:{_slug_for_cache(show)}"

    return None


def absolute_public_url(path_or_url: str) -> str:
    if path_or_url.startswith("https://") or path_or_url.startswith("http://"):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = f"/{path_or_url}"
    return f"{CONVERTER_PUBLIC_ORIGIN}{path_or_url}"


def art_url_for_cache_key(cache_key: str) -> str:
    return absolute_public_url(f"{ART_PATH_PREFIX}/{quote(cache_key, safe='')}")


def _is_public_https_url(url: str) -> bool:
    return url.startswith("https://")


def lookup_ready_art_url(
    cover_art_cache_collection: Any,
    source_path: str | None,
) -> str | None:
    """Return a publicly fetchable poster URL for push notifications.

    Prefer cached ``remote_url`` when it is public HTTPS (typical Arr ``remoteUrl`` /
    TMDB CDN). Same-origin ``/tools/converter/art/...`` requires tools auth and
    usually fails for notification image fetches (no cookies).
    """
    if cover_art_cache_collection is None or not source_path:
        return None

    cache_key = cache_key_for_path(source_path)
    if cache_key is None:
        return None

    try:
        document = cover_art_cache_collection.find_one(
            {"cache_key": cache_key, "status": "ready"},
            projection=["cache_key", "local_path", "status", "remote_url"],
        )
    except Exception as exc:  # noqa: BLE001 — push must not fail on art lookup
        logging.warning("Cover art lookup failed for %s: %s", source_path, exc)
        return None

    if document is None:
        return None

    remote_url = document.get("remote_url")
    if isinstance(remote_url, str) and _is_public_https_url(remote_url.strip()):
        return remote_url.strip()

    logging.debug(
        "No public HTTPS remote_url for %s (provider art may be LAN-only); "
        "skipping push image rather than using auth-gated site URL",
        cache_key,
    )
    return None


def notification_image_fields(
    cover_art_cache_collection: Any,
    source_path: str | None,
) -> dict[str, str]:
    """Build icon/badge/image fields for a Converter web push payload."""
    fields = {
        "icon": absolute_public_url(DEFAULT_ICON),
        "badge": absolute_public_url(DEFAULT_BADGE),
    }
    art_url = lookup_ready_art_url(cover_art_cache_collection, source_path)
    if art_url is not None:
        # Prefer poster as both icon and large image where the OS supports it.
        fields["icon"] = art_url
        fields["image"] = art_url
    return fields
