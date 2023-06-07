import logging
import atexit

from pymongo import MongoClient, ASCENDING

from .config import Config

def _close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    _client.close()
    logging.info("Closed MongoDB connection")

# Load the config
config = Config()

# Set logging level and format
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Connect to MongoDB
_client = MongoClient(config.config_data.mongo.uri)
logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Get the database
_db = _client[config.config_data.mongo.database]

# Get the media collection
media_collection = _db[config.config_data.mongo.media_collection]
media_collection.create_index([("filename", ASCENDING)], unique=True)

# Import TaskScheduler to make it available directly from the converter package
from .task_scheduler import TaskScheduler
