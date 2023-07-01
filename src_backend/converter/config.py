from datetime import time
from pathlib import Path
import tomllib

from pydantic import BaseModel

class Folders(BaseModel):
    include: list[Path]
    exclude: list[Path] | None
    backup: Path

class Schedule(BaseModel):
    timezone: str
    scan_time: time
    start_conversion_time: time
    end_conversion_time: time

class ConfigData(BaseModel):
    folders: Folders
    schedule: Schedule

class Config:
    def __init__(self) -> None:
        # Read the config file
        self.read_config()

    def read_config(self) -> None:
        # Load the config file
        with open("src/config.toml", "rb") as f:
            # Use tomllib to parse the TOML file
            data = tomllib.load(f)

            # Convert the data to a ConfigData object
            self.config_data = ConfigData(**data)
