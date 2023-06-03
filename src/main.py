from pathlib import Path
import logging

from pymongo import MongoClient

from converter.folder_walker import FolderWalker
from converter.codec_detector import CodecDetector

if __name__ == "__main__":
    # Connect to MongoDB
    client = MongoClient('mongodb://localhost:27017/')
    db = client['media']
    collection = db['conversion_data']

    try:
        logging.basicConfig(level=logging.DEBUG)
        walker = FolderWalker(paths=[
            # Path('/volumes/Media/TV'),
            Path('/Volumes/media/Films'),
            # Path('/volumes/home/Drive/Films'),
        ])

        walker.walk_folders()

        detector = CodecDetector(files=walker.files, collection=collection)
        detector.get_file_encoding()

        logging.debug(len(walker.files))
    finally:
        # Close MongoDB connection
        client.close()
        logging.debug("Closed MongoDB connection")
