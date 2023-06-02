from pathlib import Path
import logging

class FolderWalker:
    def __init__(self, paths: list[Path]) -> None:
        self.paths: list[Path] = []

        for path in paths:
            if not path.is_dir():
                logging.error(f"{path} is not a directory")
            else:
                self.paths.append(path)

        self.files: list[Path] = [] # list of files

    def walk_folders(self) -> None:
        for path in self.paths:
            self._walk(path)

    def _walk(self, path: Path) -> None:
        for file in path.iterdir():
            if file.is_dir():
                logging.info(f"Entering {file.name}")
                self._walk(file)
            elif file.is_file() and file.suffix in [".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", "mpg"]:
                self.files.append(file)
