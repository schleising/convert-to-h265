from pathlib import Path
import logging

from . import config
from .models import FileInfo


class FolderWalker:
    def __init__(self) -> None:
        # List of paths to walk
        self._paths: list[Path] = []

        for path in config.config_data.folders.include:
            # Check if the path is a directory
            if not path.is_dir():
                # If it's not a directory, log an error and skip it
                logging.error(f"{path} is not a directory")
            else:
                # If it is a directory, add it to the list of paths to walk
                self._paths.append(path)

        # List of files found
        self._files: list[FileInfo] = []

    def walk_folders(self) -> None:
        # Walk each path
        for path in self._paths:
            self._walk(path)

    def _walk(self, path: Path) -> None:
        for file in path.iterdir():
            # Check if the file is a directory
            if file.is_dir():
                # Check if the file is in the exclude list
                if (
                    config.config_data.folders.exclude
                    and file in config.config_data.folders.exclude
                ):
                    # If it is, log a message and skip it
                    logging.debug(f"Skipping {file.name}")
                else:
                    # If it's not, log a message and walk it
                    logging.debug(f"Entering {file.name}")
                    self._walk(file)
            elif file.is_file() and file.suffix in [
                ".mkv",
                ".mp4",
                ".avi",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
                ".m4v",
                "mpg",
            ]:
                # Create a FileInfo object
                file_info = FileInfo(filename=file.as_posix(), inode=file.stat().st_ino)

                # If it's a file and it's a video file, add it to the list of files to find the encoding of
                self._files.append(file_info)

        # Turn the list of files into a dict with filename as the key
        self.files_dict = {file_info.filename: file_info for file_info in self._files}
