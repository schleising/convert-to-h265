import logging
import atexit

from pymongo import MongoClient

def _close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    _client.close()
    logging.info("Closed MongoDB connection")

# Set logging level and format
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# Connect to MongoDB
_client = MongoClient("mongodb://mongodb:27017/")
logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(_close_mongo_connection)

# Get the database
_db = _client["media"]

# Get the media collection
media_collection = _db["media_collection"]
