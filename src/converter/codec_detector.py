from pathlib import Path
import subprocess
import logging

from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect

from pydantic import ValidationError

from .models import VideoInformation, FileData, FileInfo
from . import media_collection
from .cover_art_prefetch import ensure_posters_background
from .unicode_paths import (
    clear_directory_cache,
    find_equivalent_path,
    normalize_path,
    paths_equivalent,
    resolve_filesystem_path,
)


class CodecDetector:
    def __init__(self, files: dict[str, FileInfo]) -> None:
        # List of files to detect the encoding of
        self._files: dict[str, FileInfo] = files

        # The base command to run ffprobe
        self._ffprobe_base_command = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
        ]

        # Get the old data from MongoDB getting just the filename
        logging.info("Getting old data from MongoDB")
        try:
            data_from_db = media_collection.find(
                {"deleted": False}, {"filename": 1, "inode": 1, "_id": 0}
            )

            # Convert the list of FileData objects to a dictionary with the file path as the key
            self._list_from_db: list[FileInfo] = [
                FileInfo(**data) for data in data_from_db
            ]
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

    def _set_filename_in_db(
        self, inode: int, old_filename: str, new_filename: str
    ) -> bool:
        try:
            media_collection.update_one(
                {"inode": inode},
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
        # If files have been deleted, check whether the inode is still on disk.
        # If it is, update the filename to the on-disk path (including NFC/NFD fixes).
        drive_paths = set(self._files.keys())
        drive_by_inode = {info.inode: info for info in self._files.values()}
        pending_db_files: list[FileInfo] = []

        for db_file_info in self._list_from_db:
            if db_file_info.filename in drive_paths:
                continue

            equivalent_path = find_equivalent_path(db_file_info.filename, drive_paths)
            if equivalent_path is not None:
                drive_file_info = self._files[equivalent_path]
                if not paths_equivalent(
                    db_file_info.filename, drive_file_info.filename
                ):
                    if self._set_filename_in_db(
                        db_file_info.inode,
                        db_file_info.filename,
                        drive_file_info.filename,
                    ):
                        db_file_info.filename = drive_file_info.filename
                continue

            pending_db_files.append(db_file_info)

        if not pending_db_files:
            return

        logging.info("Updating deleted or renamed files in MongoDB")

        for db_file_info in pending_db_files:
            drive_file_info = drive_by_inode.get(db_file_info.inode)
            if drive_file_info is None:
                logging.info("File deleted: %s", db_file_info.filename)
                self._mark_deleted_in_db(db_file_info.filename)
                continue

            if self._set_filename_in_db(
                db_file_info.inode,
                db_file_info.filename,
                drive_file_info.filename,
            ):
                db_file_info.filename = drive_file_info.filename

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
            normalize_path(filename) for filename in filenames_from_db
        }

        for file_info in self._files.values():
            if file_info.filename in filenames_from_db:
                continue
            if normalize_path(file_info.filename) in normalized_filenames_from_db:
                continue

            probe_path = resolve_filesystem_path(Path(file_info.filename))

            file_stat = probe_path.stat()
            file_size = file_stat.st_size
            file_inode = file_stat.st_ino

            ffprobe_command = list(self._ffprobe_base_command)
            ffprobe_command.append(probe_path.as_posix())

            ffprobe_output = subprocess.run(
                ffprobe_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            conversion_required = True
            video_stream_count = 0
            audio_stream_count = 0
            subtitle_stream_count = 0
            first_video_stream = None
            first_audio_stream = None
            first_eng_audio_stream = None
            first_und_audio_stream = None
            first_subtitle_stream = None

            if ffprobe_output.returncode == 0:
                try:
                    video_information = VideoInformation.parse_raw(
                        ffprobe_output.stdout
                    )
                except ValidationError as e:
                    logging.error(f"Error parsing {file_info.filename}")
                    logging.error(e)
                    continue

                for stream in video_information.streams:
                    if stream.codec_type == "video":
                        if first_video_stream is None:
                            first_video_stream = stream.index
                        video_stream_count += 1

                    elif stream.codec_type == "audio":
                        if first_audio_stream is None:
                            first_audio_stream = stream.index

                        if stream.tags:
                            if stream.tags.language == "eng":
                                if first_eng_audio_stream is None:
                                    first_eng_audio_stream = stream.index

                            if stream.tags.language == "und":
                                if first_und_audio_stream is None:
                                    first_und_audio_stream = stream.index

                        audio_stream_count += 1

                    elif stream.codec_type == "subtitle":
                        if first_subtitle_stream is None:
                            first_subtitle_stream = stream.index
                        subtitle_stream_count += 1

                if first_video_stream is None:
                    first_video_stream = 0

                if first_eng_audio_stream is not None:
                    first_audio_stream = first_eng_audio_stream
                elif first_und_audio_stream is not None:
                    first_audio_stream = first_und_audio_stream

                if first_audio_stream is None:
                    first_audio_stream = 1

                file_data = FileData(
                    filename=file_info.filename,
                    inode=file_inode,
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
                    video_streams=video_stream_count,
                    audio_streams=audio_stream_count,
                    subtitle_streams=subtitle_stream_count,
                    first_video_stream=first_video_stream,
                    first_audio_stream=first_audio_stream,
                    first_subtitle_stream=first_subtitle_stream,
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
            else:
                logging.error(f"ffprobe failed for {file_info.filename}")
                logging.error(ffprobe_output.stderr)

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
