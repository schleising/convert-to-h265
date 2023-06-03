from pathlib import Path
import subprocess
import logging
from pydantic import ValidationError

from rich.progress import track

from pymongo import InsertOne
from pymongo.collection import Collection

from .models import VideoInformation, FileData

class CodecDetector:
    def __init__(self, files: list[Path], collection: Collection | None = None) -> None:
        self.files: list[Path] = files
        self.collection = collection

        self.ffprobe_base_command = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
        ]

        # Get the old data from MongoDB
        if self.collection is not None:
            logging.info("Getting old data from MongoDB")
            self.old_data = self.collection.find({})
            self.old_data = [FileData(**data) for data in self.old_data]
            self.old_data = {data.file_path: data for data in self.old_data}

    def get_file_encoding(self) -> None:
        bulk_write_operations = []

        logging.info("Getting file encoding")

        for file in track(self.files, description="Getting file encoding..."):
            if file.as_posix() not in self.old_data:
                ffprobe_command = list(self.ffprobe_base_command)
                ffprobe_command.append(file.as_posix())
                ffprobe_output = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

                requires_conversion = True
                video_stream_count = 0
                audio_stream_count = 0
                subtitle_stream_count = 0

                if ffprobe_output.returncode == 0:
                    try:
                        video_information = VideoInformation.parse_raw(ffprobe_output.stdout)
                    except ValidationError as e:
                        logging.error(f"Error parsing {file.as_posix()}")
                        logging.error(e)
                        continue

                    for stream in video_information.streams:
                        if stream.codec_type == 'video':
                            video_stream_count += 1

                            if stream.codec_name == 'hevc':
                                requires_conversion = False

                        elif stream.codec_type == 'audio':
                            audio_stream_count += 1

                        elif stream.codec_type == 'subtitle':
                            subtitle_stream_count += 1

                    if self.collection is not None:
                        file_data = FileData(
                            file_path=file.as_posix(),
                            video_information=video_information,
                            requires_conversion=requires_conversion,
                            video_streams=video_stream_count,
                            audio_streams=audio_stream_count,
                            subtitle_streams=subtitle_stream_count
                        )

                        bulk_write_operations.append(InsertOne(file_data.dict()))

        if bulk_write_operations and self.collection is not None:
            logging.info("Writing to MongoDB")
            self.collection.bulk_write(bulk_write_operations)
        else:
            logging.info("No new data to write to MongoDB")
