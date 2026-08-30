from pathlib import Path
import logging

from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect

from .models import FileData, FileInfo
from . import media_collection
from .cover_art_prefetch import ensure_posters_background
from .ffprobe_probe import ProbeError, probe_video_information, summarize_streams
from .unicode_paths import (
    clear_directory_cache,
    find_equivalent_path,
    path_identity_key,
    paths_same_file,
    resolve_filesystem_path,
)


class CodecDetector:
    def __init__(self, files: dict[str, FileInfo]) -> None:
        # List of files to detect the encoding of
        self._files: dict[str, FileInfo] = files

        # Get the old data from MongoDB getting just the filename
        logging.info("Getting old data from MongoDB")
        try:
            data_from_db = media_collection.find(
                {"deleted": False}, {"filename": 1, "_id": 0}
            )

            self._list_from_db: list[FileInfo] = []
            for data in data_from_db:
                filename = data.get("filename")
                if isinstance(filename, str) and filename:
                    self._list_from_db.append(FileInfo(filename=filename))
        except ServerSelectionTimeoutError:
            logging.error("Could not connect to MongoDB")

            # Set the list from the database to an empty list
            self._list_from_db = []

            # Show that the connection was not successful
            self.connection_successful = False
        except NetworkTimeout:
            logging.error("Could not connect to MongoDB")

            # Set the list from the database to an empty list
            self._list_from_db = []

            # Show that the connection was not successful
            self.connection_successful = False
        except AutoReconnect:
            logging.error("Could not connect to MongoDB.")

            # Set the list from the database to an empty list
            self._list_from_db = []

            # Show that the connection was not successful
            self.connection_successful = False
        else:
            # Show that the data was retrieved successfully
            self.connection_successful = True

            # Remove files that have been deleted
            clear_directory_cache()
            self._update_changed_files()

    def _set_filename_in_db(self, old_filename: str, new_filename: str) -> bool:
        try:
            media_collection.update_one(
                {"filename": old_filename},
                {"$set": {"filename": new_filename, "deleted": False}},
            )
        except ServerSelectionTimeoutError:
            logging.error("Could not connect to MongoDB")
            return False
        except NetworkTimeout:
            logging.error("Could not connect to MongoDB")
            return False
        except AutoReconnect:
            logging.error("Could not connect to MongoDB.")
            return False

        logging.info("Updated filename in database from %s to %s", old_filename, new_filename)
        return True

    def _mark_deleted_in_db(self, filename: str) -> bool:
        try:
            media_collection.update_one(
                {"filename": filename}, {"$set": {"deleted": True}}
            )
        except ServerSelectionTimeoutError:
            logging.error("Could not connect to MongoDB")
            return False
        except NetworkTimeout:
            logging.error("Could not connect to MongoDB")
            return False
        except AutoReconnect:
            logging.error("Could not connect to MongoDB.")
            return False
        return True

    def _update_changed_files(self) -> None:
        # Update DB paths that differ from disk only by Unicode spelling or case.
        drive_paths = set(self._files.keys())

        for db_file_info in self._list_from_db:
            if db_file_info.filename in drive_paths:
                continue

            equivalent_path = find_equivalent_path(db_file_info.filename, drive_paths)
            if equivalent_path is not None:
                drive_file_info = self._files[equivalent_path]
                if not paths_same_file(
                    db_file_info.filename, drive_file_info.filename
                ):
                    if self._set_filename_in_db(
                        db_file_info.filename,
                        drive_file_info.filename,
                    ):
                        db_file_info.filename = drive_file_info.filename
                continue

            logging.info("File deleted: %s", db_file_info.filename)
            self._mark_deleted_in_db(db_file_info.filename)

    def get_file_encoding(self) -> None:
        # Only run if the connection to MongoDB was successful
        if not self.connection_successful:
            return

        # List of bulk write operations to run
        bulk_write_operations = []
        # Filenames newly upserted this walk (cover-art prefetch; not renames)
        new_filenames: list[str] = []

        logging.info("Getting file encoding")

        filenames_from_db = {file_info.filename for file_info in self._list_from_db}
        normalized_filenames_from_db = {
            path_identity_key(filename) for filename in filenames_from_db
        }

        for file_info in self._files.values():
            if file_info.filename in filenames_from_db:
                continue
            if path_identity_key(file_info.filename) in normalized_filenames_from_db:
                continue

            probe_path = resolve_filesystem_path(Path(file_info.filename))

            file_stat = probe_path.stat()
            file_size = file_stat.st_size

            conversion_required = True

            try:
                video_information = probe_video_information(probe_path)
            except ProbeError as exc:
                logging.error("ffprobe failed for %s: %s", file_info.filename, exc)
                if exc.stderr:
                    logging.error(exc.stderr)
                continue

            stream_summary = summarize_streams(video_information)

            file_data = FileData(
                filename=file_info.filename,
                deleted=False,
                video_information=video_information,
                conversion_required=conversion_required,
                converting=False,
                converted=False,
                conversion_error=False,
                conversion_error_message=None,
                copying=False,
                percentage_complete=0,
                start_copy_time=None,
                start_conversion_time=None,
                end_conversion_time=None,
                overwrite_in_progress=False,
                temp_output_path=None,
                backup_path=None,
                video_streams=stream_summary.video_streams,
                audio_streams=stream_summary.audio_streams,
                subtitle_streams=stream_summary.subtitle_streams,
                first_video_stream=stream_summary.first_video_stream,
                first_audio_stream=stream_summary.first_audio_stream,
                first_subtitle_stream=stream_summary.first_subtitle_stream,
                pre_conversion_size=file_size,
                current_size=file_size,
                backend_name="None",
            )

            if conversion_required:
                logging.info(f"{file_info.filename}: CONVERT")
            else:
                logging.info(f"{file_info.filename}: OK")

            bulk_write_operations.append(
                UpdateOne(
                    {"filename": file_info.filename},
                    {"$set": file_data.model_dump()},
                    upsert=True,
                )
            )
            new_filenames.append(file_info.filename)

        if bulk_write_operations:
            # There is new data to write to MongoDB
            logging.info("Writing to MongoDB")

            # Write the new data to MongoDB
            try:
                media_collection.bulk_write(bulk_write_operations)
            except ServerSelectionTimeoutError:
                logging.error("Could not connect to MongoDB")
            except NetworkTimeout:
                logging.error("Could not connect to MongoDB")
            except AutoReconnect:
                logging.error("Could not connect to MongoDB.")
            else:
                logging.info("Finished writing to MongoDB")
                # Prefetch cover art off the walk thread (soft-fail inside helper)
                ensure_posters_background(new_filenames)
        else:
            # There is no new data to write to MongoDB
            logging.info("No new data to write to MongoDB")
