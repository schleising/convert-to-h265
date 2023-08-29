import logging
import atexit
import os

from pymongo import MongoClient, ASCENDING
from pymongo.errors import ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect
from bson.codec_options import CodecOptions

from .config import Config

def _close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    _client.close()
    logging.info("Closed MongoDB connection")

# Load the config
config = Config()

# Set logging level and format
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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
_client = MongoClient(f'{mongo_uri}?timeoutMS=5000')
logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Get the database
_db = _client[mongo_database]

# Get the media collection
media_collection = _db.get_collection(mongo_collection, codec_options=CodecOptions(tz_aware=True))

try:
    media_collection.create_index([("filename", ASCENDING)], unique=True)
except ServerSelectionTimeoutError:
    logging.error("Could not create index on filename")
except NetworkTimeout:
    logging.error("Could not create index on filename")
except AutoReconnect:
    logging.error("Could not create index on filename")

# Import TaskScheduler to make it available directly from the converter package
from .task_scheduler import TaskScheduler
