from datetime import datetime, UTC, time, timedelta
from pathlib import Path
from time import sleep
import logging
from zoneinfo import ZoneInfo

from pymongo.collection import Collection

from .folder_walker import FolderWalker
from .codec_detector import CodecDetector

class TaskScheduler:
    def __init__(self, collection: Collection) -> None:
        self.collection = collection
        self.next_walk_time = datetime.now().astimezone(UTC)
        self.start_conversion_time = time(hour=1, minute=0, second=0)
        self.end_conversion_time = time(hour=7, minute=0, second=0)

    def run(self) -> None:
        while True:
            now = datetime.now().astimezone(UTC)

            if now > self.next_walk_time:
                logging.info("Walk folders")

                self._walk_folders()

                self.next_walk_time = datetime(year=now.year, month=now.month, day=now.day, hour=0, minute=0, second=0, tzinfo=ZoneInfo('Europe/London')).astimezone(UTC) + timedelta(days=1)

                logging.info(f"Next walk time: {self.next_walk_time}")

            if self.start_conversion_time < now.time() < self.end_conversion_time:
                logging.info("Start conversion")

            sleep(1)

    def _walk_folders(self) -> None:
        walker = FolderWalker(paths=[
            # Path('/volumes/Media/TV'),
            Path('/Films'),
            # Path('/Volumes/Media/Films'),
            # Path('/volumes/home/Drive/Films'),
        ])

        walker.walk_folders()

        detector = CodecDetector(files=walker.files, collection=self.collection)
        detector.get_file_encoding()
