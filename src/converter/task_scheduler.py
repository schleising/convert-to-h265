from datetime import datetime, UTC, timedelta
from time import sleep
import logging
from zoneinfo import ZoneInfo

from .folder_walker import FolderWalker
from .codec_detector import CodecDetector
from . import config

class TaskScheduler:
    def __init__(self) -> None:
        # Set the next walk time to now so that the folders are walked immediately on startup
        self.next_walk_time = datetime.now().astimezone(UTC)

        # Get the scan time, start conversion time, and end conversion time from the config
        self.scan_time = config.config_data.schedule.scan_time
        self.start_conversion_time = config.config_data.schedule.start_conversion_time
        self.end_conversion_time = config.config_data.schedule.end_conversion_time

        # Boolean to keep track of whether the conversion is running
        self.conversion_running = False

    def run(self) -> None:
        while True:
            # Get the current time in UTC
            now = datetime.now().astimezone(UTC)

            if now > self.next_walk_time:
                # If the current time is after the next walk time, walk the folders
                logging.info("Walk folders")
                self._walk_folders()

                # Set the next walk time to the next scan time
                self.next_walk_time = (datetime.combine(now.date(), self.scan_time, tzinfo=ZoneInfo(config.config_data.schedule.timezone)) + timedelta(days=1)).astimezone(UTC)
                logging.info(f"Next walk time: {self.next_walk_time}")

            start_conversion_datetime = datetime.combine(now.astimezone(ZoneInfo(config.config_data.schedule.timezone)).date(), self.start_conversion_time, tzinfo=ZoneInfo(config.config_data.schedule.timezone)).astimezone(UTC)
            end_conversion_datetime = datetime.combine(now.astimezone(ZoneInfo(config.config_data.schedule.timezone)).date(), self.end_conversion_time, tzinfo=ZoneInfo(config.config_data.schedule.timezone)).astimezone(UTC)

            if start_conversion_datetime < now < end_conversion_datetime:
                # If the current time is between the start conversion time and the end conversion time, start the conversion
                if not self.conversion_running:
                    # If the conversion is not already running, log a message and start the conversion
                    logging.info("Start conversion")
                    self.conversion_running = True
            else:
                logging.debug(f'Current time: {now}, start conversion time: {self.start_conversion_time}, end conversion time: {self.end_conversion_time}')
                # If the current time is not between the start conversion time and the end conversion time, stop the conversion
                self.conversion_running = False

            # Sleep for 1 second
            sleep(1)

    def _walk_folders(self) -> None:
        # Construct a FolderWalker object
        walker = FolderWalker()

        # Walk the folders
        walker.walk_folders()

        # Construct a CodecDetector object
        detector = CodecDetector(files=walker.files)

        # Get the file encodings
        detector.get_file_encoding()
