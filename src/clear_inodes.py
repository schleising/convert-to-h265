#!/usr/bin/env python3
"""Remove inode fields from media_collection and drop the unique inode index.

Run once after upgrading away from inode-based file identity. Stop walker
and converter first, or run while WALKER_IDLE=TRUE.

Example:
    python src/clear_inodes.py --dry-run
    python src/clear_inodes.py
    docker compose exec walker-1 python3 /src/clear_inodes.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from bson.codec_options import CodecOptions
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    AutoReconnect,
    NetworkTimeout,
    OperationFailure,
    ServerSelectionTimeoutError,
)

DEFAULT_DB_URL = "mongodb://macmini2.home.arpa:27017"
DEFAULT_DB_NAME = "media"
DEFAULT_DB_COLLECTION = "media_collection"


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


def _find_inode_index(collection: Collection[dict[str, object]]) -> str | None:
    for index in collection.list_indexes():
        name = index.get("name")
        key = index.get("key")
        if not isinstance(name, str) or not isinstance(key, dict):
            continue
        if tuple(key.keys()) == ("inode",):
            return name
    return None


def _count_with_inode(collection: Collection[dict[str, object]]) -> int:
    return collection.count_documents({"inode": {"$exists": True}})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unset inode on all documents and drop the unique inode index."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to MongoDB.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args()
    _configure_logging(verbose=args.verbose)

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

    inode_index = _find_inode_index(collection)
    documents_with_inode = _count_with_inode(collection)
    total_documents = collection.count_documents({})

    logging.info("Documents: %s", total_documents)
    logging.info("Documents with inode field: %s", documents_with_inode)
    if inode_index:
        logging.info("Inode index to drop: %s", inode_index)
    else:
        logging.info("No inode index found")

    if args.dry_run:
        logging.info("Dry run; no changes written")
        return 0

    if inode_index:
        try:
            collection.drop_index(inode_index)
        except OperationFailure as exc:
            logging.error("Could not drop inode index %s: %s", inode_index, exc)
            return 1
        logging.info("Dropped index %s", inode_index)

    if documents_with_inode:
        result = collection.update_many({}, {"$unset": {"inode": ""}})
        logging.info("Unset inode on %s document(s)", result.modified_count)
    else:
        logging.info("No inode fields to unset")

    return 0


if __name__ == "__main__":
    sys.exit(main())
