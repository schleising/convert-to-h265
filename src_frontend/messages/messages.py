from pydantic import BaseModel
from enum import Enum

class MessageTypes(str, Enum):
    CONVERTING_FILES = "converting_files"
    FILES_TO_CONVERT = "files_to_convert"
    CONVERTED_FILES = "converted_files"
    STATISTICS = "statistics"

class ConvertingFileData(BaseModel):
    filename: str
    progress: float
    time_since_start: str
    time_remaining: str
    backend_name: str

class ConvertingFilesMessage(BaseModel):
    converting_files: list[ConvertingFileData]

class ConvertedFileData(BaseModel):
    filename: str
    percentage_saved: float

class ConvertedFilesMessage(BaseModel):
    converted_files: list[ConvertedFileData]

class StatisticsMessage(BaseModel):
    total_files: int
    total_converted: int
    total_to_convert: int
    gigabytes_before_conversion: float
    gigabytes_after_conversion: float
    gigabytes_saved: float
    percentage_saved: int
    total_conversion_time: str
    total_size_before_conversion_gb: float
    total_size_after_conversion_gb: float

class Message(BaseModel):
    messageType: MessageTypes
    messageBody: ConvertingFilesMessage | ConvertedFilesMessage | StatisticsMessage | None
