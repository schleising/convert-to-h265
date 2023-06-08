from pydantic import BaseModel
from enum import Enum

class MessageTypes(str, Enum):
    CONVERTING_FILE = "converting_file"
    FILES_TO_CONVERT = "files_to_convert"
    CONVERTED_FILES = "converted_files"
    STATISTICS = "statistics"

class ConvertingFileMessage(BaseModel):
    filename: str
    progress: float
    time_remaining: str

class FilesToConvertMessage(BaseModel):
    filenames: list[str]

class ConvertedFilesMessage(BaseModel):
    filenames: list[str]

class StatisticsMessage(BaseModel):
    total_files: int
    total_converted: int
    total_to_convert: int
    gigabytes_before_conversion: float
    gigabytes_after_conversion: float
    gigabytes_saved: float
    percentage_saved: int
    total_conversion_time: str

class Message(BaseModel):
    messageType: MessageTypes
    messageBody: ConvertingFileMessage | FilesToConvertMessage | ConvertedFilesMessage | StatisticsMessage | None
