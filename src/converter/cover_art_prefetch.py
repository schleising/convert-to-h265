"""Background cover-art prefetch for the folder walker.

Constructs a shared :class:`~media_cover_art.CoverArtClient` when
``FOLDER_WALKER=TRUE`` and runs ``ensure_posters`` on a daemon worker so
discovery walks are not blocked by Arr/TMDB latency.

Walker uses hybrid metadata-only mode (no ``cache_dir``): Mongo rows get
``ready`` + ``remote_url``; website3 hydrates local poster bytes later.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from media_cover_art import CoverArtClient

_client: CoverArtClient | None = None
_path_queue: queue.Queue[list[str] | None] = queue.Queue()
_worker: threading.Thread | None = None
_init_lock = threading.Lock()


def init_cover_art_client() -> None:
    """Construct the shared CoverArtClient once for the walker process."""
    global _client, _worker

    if os.getenv("FOLDER_WALKER") != "TRUE":
        return

    with _init_lock:
        if _client is not None:
            return

        try:
            from media_cover_art import CoverArtClient, CoverArtSettings

            from . import cover_art_cache_collection

            # Hybrid Walker: metadata-only. Do not set MEDIA_COVER_ART_CACHE_DIR.
            settings = CoverArtSettings.from_env()
            _client = CoverArtClient(settings, collection=cover_art_cache_collection)
            _worker = threading.Thread(
                target=_ensure_posters_worker,
                name="cover-art-ensure",
                daemon=True,
            )
            _worker.start()
            logging.info(
                "Cover art client initialised for walker prefetch (metadata-only)"
            )
        except Exception as exc:  # noqa: BLE001 — walker must start without art
            logging.exception("Failed to initialise cover art client: %s", exc)
            _client = None


def ensure_posters_background(source_paths: list[str]) -> None:
    """Enqueue newly discovered paths for non-blocking ``ensure_posters``.

    Soft-fails if the client is unavailable. The walk returns immediately;
    Arr/TMDB work happens on the dedicated daemon thread.
    """
    if not source_paths:
        return

    if _client is None:
        init_cover_art_client()
    if _client is None:
        logging.debug(
            "Skipping cover art ensure for %s path(s); client unavailable",
            len(source_paths),
        )
        return

    _path_queue.put(list(source_paths))


def _ensure_posters_worker() -> None:
    while True:
        paths = _path_queue.get()
        try:
            if paths is None:
                return
            if _client is None:
                continue
            logging.info("Ensuring cover art for %s new path(s)", len(paths))
            _ = _client.ensure_posters(paths)
            logging.info("Finished cover art ensure for %s path(s)", len(paths))
        except Exception as exc:  # noqa: BLE001 — discovery must not fail on art
            logging.exception("ensure_posters failed: %s", exc)
        finally:
            _path_queue.task_done()
