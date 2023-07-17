import logging
import atexit
import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection

from bson.codec_options import CodecOptions

# Type aliases to avoid Pylance errors
AIOMDB = AsyncIOMotorDatabase
AIOMC = AsyncIOMotorCollection

def _close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    _client.close()
    logging.info("Closed MongoDB connection")

# Get the database details from the environment variables
try:
    mongo_uri = os.environ["DB_URL"]
except KeyError:
    logging.error("DB_URL environment variable not set")
    exit(1)

try:
    mongo_database = os.environ["DB_NAME"]
except KeyError:
    logging.error("DB_NAME environment variable not set")
    exit(1)

try:
    mongo_collection = os.environ["DB_COLLECTION"]
except KeyError:
    logging.error("DB_COLLECTION environment variable not set")
    exit(1)

# Connect to MongoDB
_client = AsyncIOMotorClient(mongo_uri)

logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Get the database
_db: AIOMDB = _client[mongo_database]

# Get the media collection
media_collection: AIOMC = _db.get_collection(mongo_collection, codec_options=CodecOptions(tz_aware=True))

# Create indexes
media_collection.create_index("conversion_required")
media_collection.create_index("converting")
media_collection.create_index("converted")
media_collection.create_index("conversion_error")
media_collection.create_index("start_conversion_time")
media_collection.create_index("end_conversion_time")
media_collection.create_index("pre_conversion_size")
media_collection.create_index("current_size")
