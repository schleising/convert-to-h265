from datetime import time
import os
from pathlib import Path
import tomllib

from pydantic import BaseModel, ConfigDict, Field


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "src/config.toml"


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path

class Folders(BaseModel):
    include: list[Path]
    exclude: list[Path] = Field(default_factory=list)
    backup: Path
    conversions: Path

class Schedule(BaseModel):
    timezone: str
    scan_time: time
    start_conversion_time: time
    end_conversion_time: time


class Encoding(BaseModel):
    video_codec: str = "libx265"
    small_height_threshold: int = 600
    x265_crf: int = 28
    x265_crf_small_height: int = 23
    x265_preset: str = "medium"
    vt_qv: int = 45
    vt_qv_small_height: int = 50


class Runtime(BaseModel):
    log_directory: Path | None = None
    secrets_dir: Path = Path("src/secrets")


class PathMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source: Path = Field(default=Path("/Media"), alias="from")
    destination: Path = Field(default=Path("/Media"), alias="to")

class ConfigData(BaseModel):
    folders: Folders
    schedule: Schedule
    encoding: Encoding = Field(default_factory=Encoding)
    runtime: Runtime = Field(default_factory=Runtime)
    path_map: PathMap = Field(default_factory=PathMap)

class Config:
    def __init__(self) -> None:
        # Read the config file
        self.read_config()

    def read_config(self) -> None:
        config_path = Path(os.getenv("CONVERTER_CONFIG_PATH", DEFAULT_CONFIG_PATH))

        with config_path.open("rb") as f:
            config_data = ConfigData.model_validate(tomllib.load(f))

        path_map_from = os.getenv("CONVERTER_PATH_MAP_FROM")
        path_map_to = os.getenv("CONVERTER_PATH_MAP_TO")
        if path_map_from is not None:
            config_data.path_map.source = Path(path_map_from)
        if path_map_to is not None:
            config_data.path_map.destination = Path(path_map_to)

        config_data.folders.include = [
            _resolve_path(path) for path in config_data.folders.include
        ]
        config_data.folders.exclude = [
            _resolve_path(path) for path in config_data.folders.exclude
        ]
        config_data.folders.backup = _resolve_path(config_data.folders.backup)
        config_data.folders.conversions = _resolve_path(
            config_data.folders.conversions
        )

        if config_data.runtime.log_directory is not None:
            config_data.runtime.log_directory = _resolve_path(
                config_data.runtime.log_directory
            )
        config_data.runtime.secrets_dir = _resolve_path(
            config_data.runtime.secrets_dir
        )

        self.config_data = config_data
