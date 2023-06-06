from pathlib import Path
import subprocess
import logging
from pydantic import ValidationError

from pymongo import UpdateOne

from .models import VideoInformation, FileData
from . import media_collection

class CodecDetector:
    def __init__(self, files: dict[str, Path]) -> None:
        # List of files to detect the encoding of
        self.files: dict[str, Path] = files

        # The base command to run ffprobe
        self.ffprobe_base_command = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
        ]

        # Get the old data from MongoDB
        logging.info("Getting old data from MongoDB")
        data_from_db = media_collection.find({})

        # Convert the old data to FileData objects
        list_from_db = [FileData(**data) for data in data_from_db]

        # Convert the list of FileData objects to a dictionary with the file path as the key
        self.dict_from_db = {data.filename: data for data in list_from_db}

        # Remove files that have been deleted
        self._remove_deleted_files()

    def _remove_deleted_files(self) -> None:
        # If files have been deleted, remove them from the database
        deleted_files = set(self.dict_from_db.keys()) - set(self.files.keys())

        if deleted_files:
            for file in deleted_files:
                media_collection.delete_one({"filename": file})
                logging.info(f"Deleted {file} from database")

    def get_file_encoding(self) -> None:
        # List of bulk write operations to run
        bulk_write_operations = []

        logging.info("Getting file encoding")

        for file, path in self.files.items():
            if file not in self.dict_from_db:
                # File is not in the database, so we need to get the encoding
                # First get the file size
                file_size = path.stat().st_size

                # Construct the ffprobe command
                ffprobe_command = list(self.ffprobe_base_command)
                ffprobe_command.append(file)

                # Run ffprobe
                ffprobe_output = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

                # Set the default values
                conversion_required = True
                video_stream_count = 0
                audio_stream_count = 0
                subtitle_stream_count = 0
                first_video_stream = None
                first_audio_stream = None
                first_subtitle_stream = None

                if ffprobe_output.returncode == 0:
                    # ffprobe ran successfully
                    try:
                        # Parse the output from ffprobe
                        video_information = VideoInformation.parse_raw(ffprobe_output.stdout)
                    except ValidationError as e:
                        # There was an error parsing the output from ffprobe
                        logging.error(f"Error parsing {file}")
                        logging.error(e)
                        continue

                    for stream in video_information.streams:
                        # Loop through the streams in the video information
                        if stream.codec_type == 'video':
                            # If the first video stream has not been set, set it to the current stream
                            if first_video_stream is None:
                                first_video_stream = stream.index

                            # Stream is a video stream so increment the video stream count
                            video_stream_count += 1

                            # Check if the video stream is already encoded in hevc
                            if stream.codec_name == 'hevc':
                                # Video stream is already encoded in hevc so we don't need to convert it
                                conversion_required = False

                        elif stream.codec_type == 'audio':
                            # If the first audio stream has not been set, set it to the current stream
                            if first_audio_stream is None:
                                first_audio_stream = stream.index

                            # Stream is an audio stream so increment the audio stream count
                            audio_stream_count += 1

                        elif stream.codec_type == 'subtitle':
                            # If the first subtitle stream has not been set, set it to the current stream
                            if first_subtitle_stream is None:
                                first_subtitle_stream = stream.index

                            # Stream is a subtitle stream so increment the subtitle stream count
                            subtitle_stream_count += 1

                    # Create a FileData object
                    file_data = FileData(
                        filename=file,
                        video_information=video_information,
                        conversion_required=conversion_required,
                        converting=False,
                        converted=False,
                        conversion_error=False,
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
                    )

                    # Append the FileData object to the list of bulk write operations
                    bulk_write_operations.append(UpdateOne({"filename": file}, {"$set": file_data.dict()}, upsert=True))
                else:
                    # ffprobe failed
                    logging.error(f"ffprobe failed for {file}")
                    logging.error(ffprobe_output.stderr)

        if bulk_write_operations:
            # There is new data to write to MongoDB
            logging.info("Writing to MongoDB")

            # Write the new data to MongoDB
            media_collection.bulk_write(bulk_write_operations)
        else:
            # There is no new data to write to MongoDB
            logging.info("No new data to write to MongoDB")
