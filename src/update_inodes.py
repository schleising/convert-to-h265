#!/usr/bin/env python3
"""Read current inodes from disk and update media_collection.

Filenames in MongoDB are stored under /Media. On the Mac Mini those files
live under /Volumes/X10/Media. This script maps the database path onto
that local folder, stats each file, and writes st_ino back onto the document.

All documents are processed so unique inode values are preserved, including
deleted rows whose inode would collide with a live file. Two database rows
for the same path with different Unicode normalization (NFC vs NFD) are
treated as one file: the on-disk name is kept and the duplicate is marked
deleted. Use --dry-run to preview changes without writing.

Example:
    python src/update_inodes.py --dry-run
    python src/update_inodes.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from bson import ObjectId
from bson.codec_options import CodecOptions
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    AutoReconnect,
    BulkWriteError,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

DEFAULT_DB_URL = "mongodb://macmini2.home.arpa:27017"
DEFAULT_DB_NAME = "media"
DEFAULT_DB_COLLECTION = "media_collection"
DB_MEDIA_ROOT = Path("/Media")
LOCAL_MEDIA_ROOT = Path("/Volumes/X10/Media")
_directory_entries: dict[Path, tuple[Path, ...]] = {}


@dataclass(frozen=True)
class CliArgs:
    dry_run: bool
    verbose: bool


@dataclass
class Record:
    document_id: ObjectId
    filename: str
    inode: int | None
    local_path: Path | None
    disk_inode: int | None
    deleted: bool = False
    target_inode: int | None = None
    mark_deleted: bool = False
    duplicate_disk_inode: bool = False
    unicode_duplicate: bool = False


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")


def _resolve_local_path(filename: str) -> Path:
    source_path = Path(filename)
    try:
        relative_path = source_path.relative_to(DB_MEDIA_ROOT)
    except ValueError:
        return source_path
    return LOCAL_MEDIA_ROOT / relative_path


def _as_object_id(value: object) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _stat_inode(path: Path) -> int | None:
    try:
        return path.stat().st_ino
    except FileNotFoundError:
        return None
    except OSError as exc:
        logging.error("Could not stat %s: %s", path, exc)
        return None


def _iter_dir(parent: Path) -> tuple[Path, ...]:
    cached = _directory_entries.get(parent)
    if cached is not None:
        return cached
    try:
        entries = tuple(parent.iterdir())
    except OSError as exc:
        logging.error("Could not list %s: %s", parent, exc)
        entries = ()
    _directory_entries[parent] = entries
    return entries


def _filesystem_native_path(path: Path) -> Path:
    target = unicodedata.normalize("NFC", path.name)
    for entry in _iter_dir(path.parent):
        if unicodedata.normalize("NFC", entry.name) == target:
            return entry
    return path


def _native_db_filename(local_path: Path) -> str | None:
    native_local = _filesystem_native_path(local_path)
    try:
        relative_path = native_local.relative_to(LOCAL_MEDIA_ROOT)
    except ValueError:
        return None
    return (DB_MEDIA_ROOT / relative_path).as_posix()


def _locate_file(filename: str) -> tuple[Path | None, int | None]:
    mapped_path = _resolve_local_path(filename)
    disk_inode = _stat_inode(mapped_path)
    if disk_inode is not None:
        return mapped_path, disk_inode
    return None, None


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


def _load_records(collection: Collection[dict[str, object]]) -> list[Record]:
    records: list[Record] = []
    for document in collection.find({}, {"filename": 1, "inode": 1, "deleted": 1}):
        document_id = _as_object_id(document.get("_id"))
        filename = _as_str(document.get("filename"))
        if document_id is None or filename is None:
            logging.error(
                "Skipping document with missing _id or filename: %s", document
            )
            continue

        local_path, disk_inode = _locate_file(filename)
        records.append(
            Record(
                document_id=document_id,
                filename=filename,
                inode=_as_int(document.get("inode")),
                local_path=local_path,
                disk_inode=disk_inode,
                deleted=document.get("deleted") is True,
            )
        )

    return records


def _next_unused_inode(used: set[int], candidate: int) -> int:
    while candidate in used:
        candidate -= 1
    return candidate


def _is_unicode_duplicate(left: str, right: str) -> bool:
    return unicodedata.normalize("NFC", left) == unicodedata.normalize("NFC", right)


def _allocate_target_inodes(records: list[Record]) -> None:
    by_inode: dict[int, list[Record]] = defaultdict(list)
    for record in records:
        if record.disk_inode is not None:
            by_inode[record.disk_inode].append(record)

    used: set[int] = set()
    for disk_inode, group in by_inode.items():
        native_name: str | None = None
        for record in group:
            if record.local_path is not None:
                native_name = _native_db_filename(record.local_path)
                if native_name is not None:
                    break

        group.sort(
            key=lambda item: (
                0 if native_name is not None and item.filename == native_name else 1,
                item.filename,
            )
        )
        keeper = group[0]
        keeper.target_inode = disk_inode
        used.add(disk_inode)

        for record in group[1:]:
            record.duplicate_disk_inode = True
            if _is_unicode_duplicate(keeper.filename, record.filename):
                record.unicode_duplicate = True
                record.mark_deleted = True
                logging.warning(
                    "Unicode duplicate inode %s; keeping on-disk name and marking the other deleted",
                    disk_inode,
                )
            else:
                logging.error("Duplicate disk inode %s", disk_inode)
            logging.warning("  kept:    %s", keeper.filename)
            logging.warning("  skipped: %s", record.filename)

    for record in records:
        if record.target_inode is not None:
            continue
        if record.inode is not None and record.inode not in used:
            record.target_inode = record.inode
            used.add(record.inode)

    next_temp = -1
    for record in records:
        if record.target_inode is not None:
            continue
        next_temp = _next_unused_inode(used, next_temp)
        record.target_inode = next_temp
        used.add(next_temp)
        next_temp -= 1
        if not record.unicode_duplicate:
            logging.warning(
                "Assigned synthetic inode %s to %s",
                record.target_inode,
                record.filename,
            )


def _pending_updates(records: list[Record]) -> list[Record]:
    pending: list[Record] = []
    for record in records:
        if record.target_inode is None:
            continue
        inode_changed = record.inode != record.target_inode
        delete_changed = record.mark_deleted and not record.deleted
        if inode_changed or delete_changed:
            pending.append(record)
    return pending


def _bulk_update(
    collection: Collection[dict[str, object]], operations: list[UpdateOne]
) -> int:
    if not operations:
        return 0

    try:
        result = collection.bulk_write(operations, ordered=True)
    except ServerSelectionTimeoutError:
        logging.error("Could not connect to MongoDB")
        raise
    except NetworkTimeout:
        logging.error("Could not connect to MongoDB")
        raise
    except AutoReconnect:
        logging.error("Could not connect to MongoDB")
        raise
    except BulkWriteError as exc:
        logging.error("Bulk write failed: %s", exc.details)
        raise

    return result.modified_count


def _apply_updates(
    collection: Collection[dict[str, object]],
    records: list[Record],
    pending: list[Record],
) -> int:
    # Two-phase write so unique inode indexes are not violated mid-update
    # (including A/B inode swaps). Temporary values must not collide with
    # inodes that documents outside this batch will keep.
    inode_pending = [
        record
        for record in pending
        if record.target_inode is not None and record.inode != record.target_inode
    ]
    pending_ids = {record.document_id for record in inode_pending}
    used_temps = {
        record.inode
        for record in records
        if record.document_id not in pending_ids and record.inode is not None
    }

    temp_operations: list[UpdateOne] = []
    next_temp = -1

    for record in inode_pending:
        temp_inode = _next_unused_inode(used_temps, next_temp)
        used_temps.add(temp_inode)
        next_temp = temp_inode - 1
        temp_operations.append(
            UpdateOne({"_id": record.document_id}, {"$set": {"inode": temp_inode}})
        )

    _bulk_update(collection, temp_operations)

    final_operations: list[UpdateOne] = []
    for record in pending:
        target_inode = record.target_inode
        if target_inode is None:
            continue
        fields: dict[str, object] = {"inode": target_inode}
        if record.mark_deleted:
            fields["deleted"] = True
        final_operations.append(
            UpdateOne({"_id": record.document_id}, {"$set": fields})
        )
    return _bulk_update(collection, final_operations)


def _parse_args() -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Read file inodes from disk and update media_collection."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview inode changes without writing to MongoDB.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log every inode change.",
    )
    parsed = parser.parse_args()
    return CliArgs(
        dry_run=bool(parsed.dry_run),
        verbose=bool(parsed.verbose),
    )


def main() -> int:
    args = _parse_args()
    _configure_logging(verbose=args.verbose)

    logging.info("Path map: %s -> %s", DB_MEDIA_ROOT, LOCAL_MEDIA_ROOT)

    try:
        collection = _connect_collection()
        records = _load_records(collection)
    except ServerSelectionTimeoutError:
        logging.error("Could not connect to MongoDB")
        return 1
    except NetworkTimeout:
        logging.error("Could not connect to MongoDB")
        return 1
    except AutoReconnect:
        logging.error("Could not connect to MongoDB")
        return 1

    if not records:
        logging.info("No documents found")
        return 0

    _allocate_target_inodes(records)
    pending = _pending_updates(records)

    found = sum(1 for record in records if record.disk_inode is not None)
    missing_records = [record for record in records if record.disk_inode is None]
    missing_deleted = [record for record in missing_records if record.deleted]
    missing_not_deleted = [record for record in missing_records if not record.deleted]
    unchanged = len(records) - len(pending)
    duplicate_disk = sum(1 for record in records if record.duplicate_disk_inode)
    unicode_duplicates = sum(1 for record in records if record.unicode_duplicate)
    synthetic = sum(
        1
        for record in pending
        if record.target_inode is not None
        and record.target_inode < 0
        and not record.unicode_duplicate
    )

    logging.info("Documents: %s", len(records))
    logging.info("Files found on disk: %s", found)
    logging.info("Files missing on disk: %s", len(missing_records))
    logging.info("  already deleted in DB: %s", len(missing_deleted))
    logging.info("  not marked deleted: %s", len(missing_not_deleted))
    logging.info("Unchanged: %s", unchanged)
    logging.info("Inodes to update: %s", len(pending))
    if duplicate_disk:
        logging.warning("Files with duplicate disk inodes: %s", duplicate_disk)
    if unicode_duplicates:
        logging.warning(
            "Unicode duplicate documents to mark deleted: %s", unicode_duplicates
        )
    if synthetic:
        logging.warning("Documents assigned synthetic inodes: %s", synthetic)

    for record in sorted(missing_not_deleted, key=lambda item: item.filename):
        logging.warning("Missing and not deleted: %s", record.filename)

    if args.verbose:
        for record in pending:
            logging.info(
                "%s: %s -> %s (%s)",
                record.filename,
                record.inode,
                record.target_inode,
                record.local_path or "not on disk",
            )

    if args.dry_run:
        logging.info("Dry run; no changes written")
        return 0

    if not pending:
        logging.info("Nothing to update")
        return 0

    modified = _apply_updates(collection, records, pending)
    logging.info("Updated %s document(s)", modified)
    return 0


if __name__ == "__main__":
    sys.exit(main())
