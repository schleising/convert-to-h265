#!/usr/bin/env python3
"""Backfill converted_video_information for rows converted before post-probe support.

Run on the macOS host (outside Docker) where ffprobe and the media volume are
available. Safe to interrupt with Ctrl+C; rerun the same command to resume.

Example:
    export DB_URL=mongodb://macmini2.home.arpa:27017
    export LOCAL_MEDIA_ROOT=/Volumes/X10/Media
    python3 src/backfill_converted_video_information.py

    pip install tqdm   # optional, for progress bar
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
import tempfile
from typing import Any, Literal

from bson.codec_options import CodecOptions
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    AutoReconnect,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

from converter.ffprobe_probe import ProbeError, probe_video_information, summarize_streams
from converter.unicode_paths import map_db_path_to_local

DEFAULT_DB_URL = "mongodb://macmini2.home.arpa:27017"
DEFAULT_DB_NAME = "media"
DEFAULT_DB_COLLECTION = "media_collection"
DEFAULT_DB_ROOT = "/Media"
DEFAULT_LOCAL_MEDIA_ROOT = "/Volumes/X10/Media"
CHECKPOINT_VERSION = 1
CheckpointStatus = Literal["ok", "missing", "probe_error"]

try:
    from tqdm import tqdm as _tqdm  # type: ignore[import-not-found]
except ImportError:
    _tqdm = None


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def _connect_collection() -> Collection[dict[str, object]]:
    mongo_uri = os.environ.get("DB_URL", DEFAULT_DB_URL)
    mongo_database = os.environ.get("DB_NAME", DEFAULT_DB_NAME)
    mongo_collection = os.environ.get("DB_COLLECTION", DEFAULT_DB_COLLECTION)

    client: MongoClient[dict[str, object]] = MongoClient(
        f"{mongo_uri}?timeoutMS=5000"
    )
    database: Database[dict[str, object]] = client[mongo_database]
    return database.get_collection(
        mongo_collection, codec_options=CodecOptions(tz_aware=True)
    )


def build_backfill_query(*, force: bool, filename: str | None = None) -> dict[str, Any]:
    query: dict[str, Any] = {
        "deleted": {"$ne": True},
        "converted": True,
    }
    if filename is not None:
        query["filename"] = filename
    if not force:
        query["$or"] = [
            {"converted_video_information": {"$exists": False}},
            {"converted_video_information": None},
        ]
    return query


def should_skip_checkpoint_status(
    status: CheckpointStatus,
    *,
    retry_missing: bool,
    retry_errors: bool,
) -> bool:
    if status == "missing" and not retry_missing:
        return True
    if status == "probe_error" and not retry_errors:
        return True
    return False


def should_skip_checkpoint_entry(
    filename: str,
    status: CheckpointStatus | None,
    collection: Collection[dict[str, object]],
    *,
    retry_missing: bool,
    retry_errors: bool,
    force: bool,
) -> bool:
    if status is None:
        return False

    if status == "ok":
        if force:
            return False
        document = collection.find_one(
            {"filename": filename},
            {"converted_video_information": 1},
        )
        if document is None:
            return False
        if document.get("converted_video_information") is None:
            logging.info(
                "Checkpoint ok but MongoDB still missing post-probe for %s; reprocessing",
                filename,
            )
            return False
        return True

    return should_skip_checkpoint_status(
        status,
        retry_missing=retry_missing,
        retry_errors=retry_errors,
    )


@dataclass
class Checkpoint:
    version: int = CHECKPOINT_VERSION
    started_at: str = field(default_factory=lambda: _utc_now_iso())
    updated_at: str = field(default_factory=lambda: _utc_now_iso())
    completed: dict[str, CheckpointStatus] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=int(data.get("version", CHECKPOINT_VERSION)),
            started_at=str(data.get("started_at", _utc_now_iso())),
            updated_at=str(data.get("updated_at", _utc_now_iso())),
            completed={
                str(key): status
                for key, status in dict(data.get("completed", {})).items()
                if status in {"ok", "missing", "probe_error"}
            },
        )

    def save_atomic(self, path: Path) -> None:
        self.updated_at = _utc_now_iso()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "version": self.version,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "completed": self.completed,
            },
            indent=2,
            sort_keys=True,
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(path)

    def mark(self, filename: str, status: CheckpointStatus) -> None:
        self.completed[filename] = status


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BackfillStats:
    ok: int = 0
    missing: int = 0
    probe_error: int = 0
    skipped_checkpoint: int = 0

    def record(self, status: CheckpointStatus) -> None:
        if status == "ok":
            self.ok += 1
        elif status == "missing":
            self.missing += 1
        else:
            self.probe_error += 1


class ShutdownRequested(Exception):
    pass


class _ShutdownState:
    requested = False


def _register_shutdown_handlers(state: _ShutdownState) -> None:
    def _handler(signum: int, _frame: object) -> None:
        logging.warning("Shutdown requested (signal %s); finishing current file", signum)
        state.requested = True

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def iter_work_filenames(
    collection: Collection[dict[str, object]],
    *,
    query: dict[str, Any],
    checkpoint: Checkpoint,
    retry_missing: bool,
    retry_errors: bool,
    force: bool,
    limit: int | None,
) -> Iterator[str]:
    count = 0
    for document in collection.find(query, {"filename": 1, "_id": 0}).sort("filename", 1):
        filename = document.get("filename")
        if not isinstance(filename, str) or not filename:
            continue

        prior_status = checkpoint.completed.get(filename)
        if should_skip_checkpoint_entry(
            filename,
            prior_status,
            collection,
            retry_missing=retry_missing,
            retry_errors=retry_errors,
            force=force,
        ):
            continue

        yield filename
        count += 1
        if limit is not None and count >= limit:
            break


def _default_checkpoint_path() -> Path:
    return Path.home() / ".cache" / "convert-to-h265" / "backfill_converted_video_information.json"


class _SimpleProgress:
    def __init__(self, total: int) -> None:
        self.total = total
        self.n = 0
        self._last_report = 0

    def __enter__(self) -> _SimpleProgress:
        return self

    def __exit__(self, *_args: object) -> None:
        logging.info("Progress: %s/%s complete", self.n, self.total)

    def update(self, n: int = 1) -> None:
        self.n += n
        if self.n == self.total or self.n - self._last_report >= 100:
            logging.info("Progress: %s/%s complete", self.n, self.total)
            self._last_report = self.n

    def set_postfix(self, **_kwargs: object) -> None:
        return


def _make_progress(total: int) -> Any:
    if _tqdm is not None:
        return _tqdm(total=total, desc="Probing converted files", unit="file")
    logging.info(
        "tqdm not installed; logging progress every 100 files. "
        "Install with: pip install tqdm"
    )
    return _SimpleProgress(total)


def run_backfill(
    collection: Collection[dict[str, object]],
    *,
    db_root: Path,
    local_root: Path,
    checkpoint_path: Path,
    dry_run: bool,
    force: bool,
    filename: str | None,
    limit: int | None,
    retry_missing: bool,
    retry_errors: bool,
    reset_checkpoint: bool,
    shutdown_state: _ShutdownState,
    progress_factory: Callable[[int], Any] = _make_progress,
) -> BackfillStats:
    if reset_checkpoint and checkpoint_path.is_file():
        checkpoint_path.unlink()

    checkpoint = Checkpoint.load(checkpoint_path)
    query = build_backfill_query(force=force, filename=filename)
    work = list(
        iter_work_filenames(
            collection,
            query=query,
            checkpoint=checkpoint,
            retry_missing=retry_missing,
            retry_errors=retry_errors,
            force=force,
            limit=limit,
        )
    )
    stats = BackfillStats()

    if not work:
        logging.info("No files to process")
        return stats

    logging.info("Processing %s file(s)", len(work))

    with progress_factory(len(work)) as progress:
        for filename in work:
            if shutdown_state.requested:
                checkpoint.save_atomic(checkpoint_path)
                raise ShutdownRequested

            local_path = map_db_path_to_local(filename, db_root, local_root)
            if not local_path.is_file():
                logging.warning("Missing on disk: %s -> %s", filename, local_path)
                if not dry_run:
                    checkpoint.mark(filename, "missing")
                    checkpoint.save_atomic(checkpoint_path)
                stats.record("missing")
                progress.update(1)
                progress.set_postfix(ok=stats.ok, missing=stats.missing, probe_error=stats.probe_error)
                continue

            try:
                video_information = probe_video_information(local_path)
                stream_summary = summarize_streams(video_information)
            except ProbeError as exc:
                logging.error("ffprobe failed for %s: %s", filename, exc)
                if not dry_run:
                    checkpoint.mark(filename, "probe_error")
                    checkpoint.save_atomic(checkpoint_path)
                stats.record("probe_error")
                progress.update(1)
                progress.set_postfix(ok=stats.ok, missing=stats.missing, probe_error=stats.probe_error)
                continue

            if not dry_run:
                result = collection.update_one(
                    {"filename": filename},
                    {
                        "$set": {
                            "converted_video_information": video_information.model_dump(),
                            **stream_summary.as_dict(),
                        }
                    },
                )
                if result.matched_count == 0:
                    logging.error(
                        "MongoDB update matched no documents for %s",
                        filename,
                    )
                    checkpoint.mark(filename, "probe_error")
                    stats.record("probe_error")
                    progress.update(1)
                    progress.set_postfix(
                        ok=stats.ok,
                        missing=stats.missing,
                        probe_error=stats.probe_error,
                    )
                    checkpoint.save_atomic(checkpoint_path)
                    continue

            if not dry_run:
                checkpoint.mark(filename, "ok")
                checkpoint.save_atomic(checkpoint_path)

            stats.record("ok")
            progress.update(1)
            progress.set_postfix(ok=stats.ok, missing=stats.missing, probe_error=stats.probe_error)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill converted_video_information for converted library files."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe files but do not write to MongoDB.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-probe rows that already have converted_video_information.",
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Process a single MongoDB filename (exact /Media/... path).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N files (for testing).",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Checkpoint file path (default: ~/.cache/convert-to-h265/...).",
    )
    parser.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="Ignore/delete existing checkpoint before starting.",
    )
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="Retry files previously marked missing in the checkpoint.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry files previously marked probe_error in the checkpoint.",
    )
    parser.add_argument(
        "--archive-checkpoint",
        action="store_true",
        help="Rename checkpoint to .done after successful full run.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args()
    _configure_logging(verbose=args.verbose)

    db_root = Path(os.environ.get("DB_ROOT", DEFAULT_DB_ROOT))
    local_root = Path(os.environ.get("LOCAL_MEDIA_ROOT", DEFAULT_LOCAL_MEDIA_ROOT))
    checkpoint_path = args.checkpoint or _default_checkpoint_path()
    shutdown_state = _ShutdownState()
    _register_shutdown_handlers(shutdown_state)

    try:
        collection = _connect_collection()
    except ServerSelectionTimeoutError:
        logging.error("Could not connect to MongoDB")
        return 1
    except NetworkTimeout:
        logging.error("Could not connect to MongoDB")
        return 1
    except AutoReconnect:
        logging.error("Could not connect to MongoDB")
        return 1

    query = build_backfill_query(force=args.force, filename=args.filename)
    total_candidates = collection.count_documents(query)
    logging.info("MongoDB candidates: %s", total_candidates)
    logging.info("DB root: %s", db_root)
    logging.info("Local media root: %s", local_root)
    logging.info("Checkpoint: %s", checkpoint_path)

    try:
        stats = run_backfill(
            collection,
            db_root=db_root,
            local_root=local_root,
            checkpoint_path=checkpoint_path,
            dry_run=args.dry_run,
            force=args.force,
            filename=args.filename,
            limit=args.limit,
            retry_missing=args.retry_missing,
            retry_errors=args.retry_errors,
            reset_checkpoint=args.reset_checkpoint,
            shutdown_state=shutdown_state,
        )
    except ShutdownRequested:
        logging.info(
            "Stopped early; checkpoint saved. Rerun the same command to resume."
        )
        return 130

    logging.info(
        "Done: ok=%s missing=%s probe_error=%s",
        stats.ok,
        stats.missing,
        stats.probe_error,
    )

    if args.archive_checkpoint and checkpoint_path.is_file():
        archived = checkpoint_path.with_suffix(checkpoint_path.suffix + ".done")
        checkpoint_path.replace(archived)
        logging.info("Archived checkpoint to %s", archived)

    return 0


if __name__ == "__main__":
    sys.exit(main())
