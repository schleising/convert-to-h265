import logging
import atexit
import os

from pymongo import MongoClient, ASCENDING
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
_client = MongoClient(mongo_uri)
logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Are we only converting TV shows
only_tv_shows = os.environ.get("ONLY_TV_SHOWS", "false").lower() == "true"

# Are we only converting films
only_films = os.environ.get("ONLY_FILMS", "false").lower() == "true"

# Are we going for smallest file sizes first
smallest_first = os.environ.get("SMALLEST_FIRST", "false").lower() == "true"

# Get the database
_db = _client[mongo_database]

# Get the media collection
media_collection = _db.get_collection(mongo_collection, codec_options=CodecOptions(tz_aware=True))
media_collection.create_index([("filename", ASCENDING)], unique=True)

# Import TaskScheduler to make it available directly from the converter package
from .task_scheduler import TaskScheduler
