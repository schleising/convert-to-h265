from pydantic import BaseModel
from enum import Enum

class MessageTypes(str, Enum):
    CONVERTING_FILE = "converting_file"
    FILES_TO_CONVERT = "files_to_convert"
    CONVERTED_FILES = "converted_files"

class ConvertingFileMessage(BaseModel):
    filename: str
    progress: int

class FilesToConvertMessage(BaseModel):
    filenames: list[str]

class ConvertedFilesMessage(BaseModel):
    filenames: list[str]

class Message(BaseModel):
    messageType: MessageTypes
    messageBody: ConvertingFileMessage | FilesToConvertMessage | ConvertedFilesMessage | None
