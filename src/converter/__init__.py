import logging
import atexit

from pymongo import MongoClient, ASCENDING

from .config import Config

def close_mongo_connection() -> None:
    # This function will be registered with atexit to close the MongoDB connection when the program exits
    client.close()
    logging.info("Closed MongoDB connection")

# Load the config
config = Config()

# Set logging level and format
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# Connect to MongoDB
client = MongoClient(config.config_data.mongo.uri)
logging.info("Connected to MongoDB")

# Register the close_mongo_connection function to run at exit
atexit.register(close_mongo_connection)

# Get the database and collection
db = client[config.config_data.mongo.database]
collection = db[config.config_data.mongo.collection]
collection.create_index([("file_path", ASCENDING)], unique=True)

# Import TaskScheduler to make it available directly from the converter package
from .task_scheduler import TaskScheduler
