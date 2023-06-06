from pathlib import Path
import subprocess
import logging
from pydantic import ValidationError

from pymongo import UpdateOne

from .models import VideoInformation, FileData
from . import media_collection

class CodecDetector:
    def __init__(self, files: list[Path]) -> None:
        # List of files to detect the encoding of
        self.files: list[Path] = files

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
        self.old_data = media_collection.find({})

        # Convert the old data to FileData objects
        self.old_data = [FileData(**data) for data in self.old_data]

        # Convert the list of FileData objects to a dictionary with the file path as the key
        self.old_data = {data.filename: data for data in self.old_data}

    def get_file_encoding(self) -> None:
        # List of bulk write operations to run
        bulk_write_operations = []

        logging.info("Getting file encoding")

        for file in self.files:
            if file.as_posix() not in self.old_data:
                # File is not in the database, so we need to get the encoding
                # First get the file size
                file_size = file.stat().st_size

                # Construct the ffprobe command
                ffprobe_command = list(self.ffprobe_base_command)
                ffprobe_command.append(file.as_posix())

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
                        logging.error(f"Error parsing {file.as_posix()}")
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
                        filename=file.as_posix(),
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
                    bulk_write_operations.append(UpdateOne({"filename": file.as_posix()}, {"$set": file_data.dict()}, upsert=True))
                else:
                    # ffprobe failed
                    logging.error(f"ffprobe failed for {file.as_posix()}")
                    logging.error(ffprobe_output.stderr)

        if bulk_write_operations:
            # There is new data to write to MongoDB
            logging.info("Writing to MongoDB")

            # Write the new data to MongoDB
            media_collection.bulk_write(bulk_write_operations)
        else:
            # There is no new data to write to MongoDB
            logging.info("No new data to write to MongoDB")
