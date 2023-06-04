from datetime import time
from pathlib import Path
import tomllib

from pydantic import BaseModel

class Mongo(BaseModel):
    uri: str
    database: str
    collection: str

class Folders(BaseModel):
    include: list[Path]
    exclude: list[Path] | None

class Schedule(BaseModel):
    timezone: str
    scan_time: time
    start_conversion_time: time
    end_conversion_time: time

class ConfigData(BaseModel):
    mongo: Mongo
    folders: Folders
    schedule: Schedule

class Config:
    def __init__(self) -> None:
        # Load the config file
        with open("src/config.toml", "rb") as f:
            # Use tomllib to parse the TOML file
            data = tomllib.load(f)

            # Convert the data to a ConfigData object
            self.config_data = ConfigData(**data)
