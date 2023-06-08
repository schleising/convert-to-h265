from datetime import datetime, timedelta
from pathlib import Path
from .models import FileData
from ..messages.messages import StatisticsMessage
from . import media_collection

class Database:
    def __init__(self) -> None:
        pass

    async def get_converted_files(self) -> list[str]:
        # Find files that have been converted in the last week
        db_file_cursor = media_collection.find({
            "conversion_required": True,
            "converting": False,
            "converted": True,
            "conversion_error": False,
            "end_conversion_time": {
                "$gte": datetime.now() - timedelta(days=7)
            }
        })

        # Convert the cursor to a list
        db_file_list = await db_file_cursor.to_list(length=None)

        # Convert the list of FileData objects to a list of file paths
        file_list = [Path(FileData(**data).filename).name for data in db_file_list]

        return file_list
    
    async def get_converting_file(self) -> FileData | None:
        # Get the file that is being converted from MongoDB
        db_file = await media_collection.find_one({
            "converting": True,
        })

        # Convert the list of FileData objects to a list of file paths
        if db_file is not None:
            file_data = FileData(**db_file)

            return file_data

        return None

    async def get_statistics(self) -> StatisticsMessage:
        # Get the total number of files in the database
        total_files = await media_collection.count_documents({})

        # Get the total number of files that have been converted
        total_converted = await media_collection.count_documents({
            "converted": True
        })

        # Get the total number of files that need to be converted
        total_to_convert = await media_collection.count_documents({
            "conversion_required": True,
            "converted": False,
            "converting": False,
            "conversion_error": False
        })

        # Get the total number of files that are currently being converted
        total_converting = await media_collection.count_documents({
            "converting": True
        })

        # Add the number of files that are currently being converted to the total number of files that need to be converted
        total_to_convert += total_converting

        # Get the total number of gigabytes before conversion
        gigabytes_before_conversion_db = await media_collection.aggregate([
            {
                "$match": {
                    "converted": True
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": "$pre_conversion_size"
                    }
                }
            }
        ]).to_list(length=None)

        # Convert the total number of bytes to gigabytes
        if gigabytes_before_conversion_db:
            gigabytes_before_conversion = float(gigabytes_before_conversion_db[0]["total"] / 1000000000)
        else:
            # If there are no files in the database, set the total number of gigabytes to 0
            gigabytes_before_conversion = 0

        # Get the total number of gigabytes after conversion
        gigabytes_after_conversion_db = await media_collection.aggregate([
            {
                "$match": {
                    "converted": True
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total": {
                        "$sum": "$current_size"
                    }
                }
            }
        ]).to_list(length=None)

        # Convert the total number of bytes to gigabytes
        if gigabytes_after_conversion_db:
            gigabytes_after_conversion = float(gigabytes_after_conversion_db[0]["total"] / 1000000000)
        else:
            # If there are no files in the database, set the total number of gigabytes to 0
            gigabytes_after_conversion = gigabytes_before_conversion

        # Get the total number of gigabytes saved
        gigabytes_saved = gigabytes_before_conversion - gigabytes_after_conversion

        # Get the percentage saved
        if gigabytes_before_conversion != 0:
            percentage_saved = gigabytes_saved / gigabytes_before_conversion * 100
        else:
            # If there are no files in the database, set the percentage saved to 0
            percentage_saved = 0

        # Create a StatisticsMessage from the database objects
        statistics_message = StatisticsMessage(
            total_files=total_files,
            total_converted=total_converted,
            total_to_convert=total_to_convert,
            gigabytes_before_conversion=round(gigabytes_before_conversion, 3),
            gigabytes_after_conversion=round(gigabytes_after_conversion, 3),
            gigabytes_saved=round(gigabytes_saved, 3),
            percentage_saved=int(percentage_saved)
        )

        # Return the StatisticsMessage
        return statistics_message
