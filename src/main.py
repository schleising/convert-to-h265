import logging
import sys
import signal

from pymongo import MongoClient

from converter.task_scheduler import TaskScheduler

def signal_handler(sig: int, _):
    # Handle SIGINT and SIGTERM signals to ensure the Docker container stops gracefully
    match sig:
        case signal.SIGINT:
            logging.info("Stopping due to keyboard interrupt...")
            sys.exit(0)
        case signal.SIGTERM:
            logging.info("Stopping due to SIGTERM...")
            sys.exit(0)

def main() -> None:
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Set logging level and format
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

    # Connect to MongoDB
    client = MongoClient('mongodb://mongodb:27017/')
    logging.debug("Connected to MongoDB")

    try:
        # Get the database and collection
        db = client['media']
        collection = db['conversion_data']

        # Create the task scheduler
        scheduler = TaskScheduler(collection=collection)

        # Run the task scheduler
        scheduler.run()
    finally:
        # Close MongoDB connection
        client.close()
        logging.debug("Closed MongoDB connection")

if __name__ == "__main__":
    # Run the main function
    main()
