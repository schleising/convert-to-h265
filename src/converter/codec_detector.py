from pathlib import Path
import subprocess
import logging

from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect

from pydantic import ValidationError

from .models import VideoInformation, FileData, FileInfo
from . import media_collection


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
                {"deleted": {"$ne": True}}, {"filename": 1, "inode": 1, "_id": 0}
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
            self._update_changed_files()

    def _update_changed_files(self) -> None:
        # If files have been deleted, check whether the inode is still in the database
        # If it is not, set the deleted field to True in the database
        # If it is, update the filename to the new filename
        missing_from_drive = (
            file_info.filename for file_info in self._list_from_db
        ) - self._files.keys()

        if missing_from_drive:
            # There are files that have either been deleted or renamed
            logging.info("Updating deleted or renamed files in MongoDB")

            for file in missing_from_drive:
                # Get the inode of the file from the list of FileInfo objects
                db_file_info = None
                for info in self._list_from_db:
                    if info.filename == file:
                        db_file_info = info
                        break

                if db_file_info is None:
                    # Log the error
                    logging.error(f"File info not found for {file}")

                    # Could not find the file info, skip it
                    continue

                drive_file_info = None

                # Check if the inode is in the current list of files
                for info in self._files.values():
                    if info.inode == db_file_info.inode:
                        drive_file_info = info
                        break

                if drive_file_info is None:
                    # The inode is not in the current list of files, so the file has been deleted
                    logging.info(f"File deleted: {file}")

                    # Set the deleted field to True in the database
                    try:
                        media_collection.update_one(
                            {"filename": file}, {"$set": {"deleted": True}}
                        )
                    except ServerSelectionTimeoutError:
                        logging.error("Could not connect to MongoDB")
                        continue
                    except NetworkTimeout:
                        logging.error("Could not connect to MongoDB")
                        continue
                    except AutoReconnect:
                        logging.error("Could not connect to MongoDB.")
                        continue

                    # Move to the next file
                    continue

                # Check if the inode is still in the database
                try:
                    data_from_db = media_collection.find_one(
                        {"inode": db_file_info.inode}, {"filename": 1, "_id": 0}
                    )
                except ServerSelectionTimeoutError:
                    logging.error("Could not connect to MongoDB")
                    continue
                except NetworkTimeout:
                    logging.error("Could not connect to MongoDB")
                    continue
                except AutoReconnect:
                    logging.error("Could not connect to MongoDB.")
                    continue
                else:
                    # Construct a FileInfo object
                    if data_from_db:
                        # The inode is still in the database, so the file has been renamed
                        old_filename = data_from_db["filename"]
                        new_filename = drive_file_info.filename

                        logging.debug(
                            f"File renamed from {old_filename} to {new_filename}"
                        )

                        # Update the filename in the database
                        try:
                            media_collection.update_one(
                                {"inode": db_file_info.inode},
                                {"$set": {"filename": new_filename, "deleted": False}},
                            )

                            # Update the filename in the local list
                            db_file_info.filename = new_filename

                            # Log the update
                            logging.info(
                                f"Updated filename in database from {old_filename} to {new_filename}"
                            )
                        except ServerSelectionTimeoutError:
                            logging.error("Could not connect to MongoDB")
                            continue
                        except NetworkTimeout:
                            logging.error("Could not connect to MongoDB")
                            continue
                        except AutoReconnect:
                            logging.error("Could not connect to MongoDB.")
                            continue

    def get_file_encoding(self) -> None:
        # Only run if the connection to MongoDB was successful
        if not self.connection_successful:
            return

        # List of bulk write operations to run
        bulk_write_operations = []

        logging.info("Getting file encoding")

        filenames_from_db = {file_info.filename for file_info in self._list_from_db}

        for file_info in self._files.values():
            if file_info.filename not in filenames_from_db:
                # File is not in the database, so we need to get the encoding

                # Stat the file
                file_stat = Path(file_info.filename).stat()

                # Get the file size
                file_size = file_stat.st_size

                # Get the file inode
                file_inode = file_stat.st_ino

                # Construct the ffprobe command
                ffprobe_command = list(self._ffprobe_base_command)
                ffprobe_command.append(file_info.filename)

                # Run ffprobe
                ffprobe_output = subprocess.run(
                    ffprobe_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )

                # Set the default values
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
                    # ffprobe ran successfully
                    try:
                        # Parse the output from ffprobe
                        video_information = VideoInformation.parse_raw(
                            ffprobe_output.stdout
                        )
                    except ValidationError as e:
                        # There was an error parsing the output from ffprobe
                        logging.error(f"Error parsing {file_info.filename}")
                        logging.error(e)
                        continue

                    for stream in video_information.streams:
                        # Loop through the streams in the video information
                        if stream.codec_type == "video":
                            # If the first video stream has not been set, set it to the current stream
                            if first_video_stream is None:
                                first_video_stream = stream.index

                            # Stream is a video stream so increment the video stream count
                            video_stream_count += 1

                        elif stream.codec_type == "audio":
                            # If the first audio stream has not been set, set it to the current stream
                            if first_audio_stream is None:
                                first_audio_stream = stream.index

                            # Check if the audio stream in in English
                            if stream.tags:
                                if stream.tags.language == "eng":
                                    # If the first audio stream has not been set, set it to the current stream
                                    if first_eng_audio_stream is None:
                                        first_eng_audio_stream = stream.index

                                # Check if the audio stream is undefined
                                if stream.tags.language == "und":
                                    # If the first audio stream has not been set, set it to the current stream
                                    if first_und_audio_stream is None:
                                        first_und_audio_stream = stream.index

                            # Stream is an audio stream so increment the audio stream count
                            audio_stream_count += 1

                        elif stream.codec_type == "subtitle":
                            # If the first subtitle stream has not been set, set it to the current stream
                            if first_subtitle_stream is None:
                                first_subtitle_stream = stream.index

                            # Stream is a subtitle stream so increment the subtitle stream count
                            subtitle_stream_count += 1

                    # Set the first video and audio stream to safe values if they are None
                    if first_video_stream is None:
                        first_video_stream = 0

                    # Set the first audio stream to the first English audio stream if it exists,
                    # otherwise set it to the first undefined audio stream.
                    # If neither exist, leave it as the first audio stream found
                    if first_eng_audio_stream is not None:
                        first_audio_stream = first_eng_audio_stream
                    elif first_und_audio_stream is not None:
                        first_audio_stream = first_und_audio_stream

                    # If the first audio stream is still None, set it to 1
                    if first_audio_stream is None:
                        first_audio_stream = 1

                    # Create a FileData object
                    file_data = FileData(
                        filename=file_info.filename,
                        inode=file_inode,
                        deleted=False,
                        video_information=video_information,
                        conversion_required=conversion_required,
                        converting=False,
                        converted=False,
                        conversion_error=False,
                        copying=False,
                        percentage_complete=0,
                        start_conversion_time=None,
                        end_conversion_time=None,
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

                    # Log whether the file needs to be converted
                    if conversion_required:
                        logging.info(f"{file_info.filename}: CONVERT")
                    else:
                        logging.info(f"{file_info.filename}: OK")

                    # Append the FileData object to the list of bulk write operations
                    bulk_write_operations.append(
                        UpdateOne(
                            {"filename": file_info.filename},
                            {"$set": file_data.model_dump()},
                            upsert=True,
                        )
                    )
                else:
                    # ffprobe failed
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
        else:
            # There is no new data to write to MongoDB
            logging.info("No new data to write to MongoDB")
