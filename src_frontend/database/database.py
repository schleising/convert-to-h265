from .models import FileData

from . import media_collection

class Database:
    def __init__(self) -> None:
        pass

    def get_files_to_convert(self) -> list[str]:
        # Get a file that needs to be converted from MongoDB
        db_file_list = media_collection.find({
            "conversion_required": True,
            "converting": False,
            "converted": False,
            "conversion_error": False
        })

        # Convert the list of FileData objects to a list of file paths
        file_list = [FileData(**data).filename for data in db_file_list]

        return file_list
    
    def get_converted_files(self) -> list[str]:
        # Get a file that needs to be converted from MongoDB
        db_file_list = media_collection.find({
            "conversion_required": False,
            "converting": False,
            "converted": True,
            "conversion_error": False
        })

        # Convert the list of FileData objects to a list of file paths
        file_list = [FileData(**data).filename for data in db_file_list]

        return file_list
    
    def get_converting_file(self) -> FileData | None:
        # Get the file that is being converted from MongoDB
        db_file = media_collection.find_one({
            "converting": True,
        })

        # Convert the list of FileData objects to a list of file paths
        if db_file is not None:
            file_data = FileData(**db_file)

            return file_data

        return None