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

class ConfigData(BaseModel):
    mongo: Mongo
    folders: Folders

class Config:
    def __init__(self) -> None:
        with open("src/config.toml", "rb") as f:
            data = tomllib.load(f)
            self._config_data = ConfigData(**data)

    @property
    def config_data(self) -> ConfigData:
        return self._config_data
