"""Resolve Converter cover-art URLs for web push notifications.

Uses ``media_cover_art`` for path→cache-key identity and ready-record lookup
(``get_ready_record`` → public ``remote_url``).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from media_cover_art import (
    CoverArtClient,
    CoverArtSettings,
    cache_key_for_path,
    parse_media_identity,
)

DEFAULT_ICON = "/icons/tools/converter/android-chrome-192x192-20260504.png"
DEFAULT_BADGE = "/icons/tools/converter/badge-192x192-v2-0-2.png"
# Absolute origin for notification fetches (OS/browser often has no tools-auth cookies).
CONVERTER_PUBLIC_ORIGIN = "https://converter.schleising.net"
ART_PATH_PREFIX = "/tools/converter/art"


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

    if parse_media_identity(source_path).kind == "unknown":
        return None

    cache_key = cache_key_for_path(source_path)

    try:
        settings = CoverArtSettings.from_env()
        with CoverArtClient(
            settings, collection=cover_art_cache_collection
        ) as client:
            record = client.get_ready_record(source_path)
    except Exception as exc:  # noqa: BLE001 — push must not fail on art lookup
        logging.warning("Cover art lookup failed for %s: %s", source_path, exc)
        return None

    if record is None or not record.remote_url:
        return None

    remote_url = record.remote_url.strip()
    if _is_public_https_url(remote_url):
        return remote_url

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
