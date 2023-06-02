from pathlib import Path
import subprocess
import logging

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
            self.old_data = self.collection.find({})
            self.old_data = [FileData(**data) for data in self.old_data]
            self.old_data = {data.file_path: data for data in self.old_data}

    def get_file_encoding(self) -> None:
        bulk_write_operations = []

        for file in track(self.files, description="Getting file encoding..."):
            if file.as_posix() not in self.old_data:
                ffprobe_command = list(self.ffprobe_base_command)
                ffprobe_command.append(file.as_posix())
                ffprobe_output = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

                requires_conversion = True

                if ffprobe_output.returncode == 0:
                    video_information = VideoInformation.parse_raw(ffprobe_output.stdout)

                    for stream in video_information.streams:
                        if stream.codec_name == 'hevc':
                            requires_conversion = False
                            break

                    if self.collection is not None:
                        file_data = FileData(
                            file_path=file.as_posix(),
                            video_information=video_information,
                            requires_conversion=requires_conversion,
                        )

                        bulk_write_operations.append(InsertOne(file_data.dict()))

        if bulk_write_operations and self.collection is not None:
            logging.info("Writing to MongoDB")
            self.collection.bulk_write(bulk_write_operations)
