import logging
import atexit

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection

from bson.codec_options import CodecOptions

# Type aliases to avoid Pylance errors
AIOMDB = AsyncIOMotorDatabase
AIOMC = AsyncIOMotorCollection

def _close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    _client.close()
    logging.info("Closed MongoDB connection")

# Connect to MongoDB
_client = AsyncIOMotorClient("mongodb://macmini2:27017/")

logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Get the database
_db: AIOMDB = _client["media"]

# Get the media collection
media_collection: AIOMC = _db.get_collection("media_collection", codec_options=CodecOptions(tz_aware=True))

# Create indexes
media_collection.create_index("conversion_required")
media_collection.create_index("converting")
media_collection.create_index("converted")
media_collection.create_index("conversion_error")
media_collection.create_index("start_conversion_time")
media_collection.create_index("end_conversion_time")
media_collection.create_index("pre_conversion_size")
media_collection.create_index("current_size")
