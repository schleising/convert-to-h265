import logging
import atexit

from pymongo import MongoClient

from .config import Config

def close_mongo_connection() -> None:
    # Close MongoDB connection when the program exits
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

from .task_scheduler import TaskScheduler
