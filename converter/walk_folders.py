from pathlib import Path
import subprocess

from rich.console import Console
from rich.table import Table
from rich.progress import track

from .models import VideoInformation

class WalkFolders:
    def __init__(self, path: Path) -> None:
        self.path = path    # path to folder
        self.files: list[Path] = [] # list of files
        self.x264_files: list[Path] = [] # list of x264 files
        self.x265_files: list[Path] = [] # list of x265 files
        self.unknown_files: list[Path] = [] # list of unknown files

        self.ffprobe_base_command = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
        ]

    def walk(self, path = None) -> None:
        if path is None:
            path = self.path

        for file in path.iterdir():
            if file.is_dir():
                print(f"Entering {file.name}")
                self.walk(file)
            elif file.is_file() and file.suffix in [".mkv", ".mp4"]:
                self.files.append(file)

    def get_file_encoding(self) -> None:
        for file in track(self.files, description="Getting file encoding..."):
            ffprobe_command = list(self.ffprobe_base_command)
            ffprobe_command.append(file.as_posix())
            ffprobe_output = subprocess.run(ffprobe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)

            if ffprobe_output.returncode == 0:
                video_information = VideoInformation.parse_raw(ffprobe_output.stdout)
                valid_codec = False

                for stream in video_information.streams:
                    if stream.codec_type == "video":
                        if stream.codec_name == "h264":
                            # print(f"{file.name} is x264")
                            valid_codec = True
                            self.x264_files.append(file)
                            break
                        elif stream.codec_name == "hevc":
                            # print(f"{file.name} is x265")
                            self.x265_files.append(file)
                            valid_codec = True
                            break

                if not valid_codec:
                    print(f"{file.name} is unknown")
                    self.unknown_files.append(file)

    def print_files(self) -> None:
        table = Table(title="Files")
        table.add_column("x264", justify="center")
        table.add_column("x265", justify="center")
        table.add_column("Unknown", justify="center")

        table.add_row(
            str(len(self.x264_files)),
            str(len(self.x265_files)),
            str(len(self.unknown_files)),
        )

        console = Console()
        console.print(table)
