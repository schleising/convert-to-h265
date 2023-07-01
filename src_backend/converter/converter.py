from datetime import datetime, timedelta
from pathlib import Path
import logging
import signal
import sys
import shutil
import os

from pymongo import DESCENDING, ASCENDING

from ffmpeg import FFmpeg, FFmpegError
from ffmpeg import Progress as FFmpegProgress

from .models import FileData
from . import media_collection, config, only_tv_shows, smallest_first

class Converter:
    def __init__(self):
        # Create ffmpeg object and set it to None
        self._ffmpeg: FFmpeg | None = None

        # Create file_data object and set it to None
        self._file_data: FileData | None = None

        # Create output file path and set it to None
        self._output_file_path: Path | None = None

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig: int, _):
        # Handle SIGINT and SIGTERM signals to ensure the Docker container stops gracefully
        match sig:
            case signal.SIGINT:
                logging.info("Stopping Conversion due to keyboard interrupt...")
                self._cleanup_and_terminate()
            case signal.SIGTERM:
                logging.info("Stopping Conversion due to SIGTERM...")
                self._cleanup_and_terminate()

    def _cleanup_and_terminate(self, conversion_failed: bool = False) -> None:
        if self._file_data is not None:
            # Log that ffmpeg was terminated and we are cleaning up
            logging.info(f"ffmpeg terminating for {self._file_data.filename}. Cleaning up...")

            # Update the file_data object
            self._file_data.converting = False
            self._file_data.start_conversion_time = None
            self._file_data.percentage_complete = 0

            if conversion_failed:
                self._file_data.conversion_error = True

            # Update the file in MongoDB
            media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})

            # Set the file_data object to None
            self._file_data = None

        # Delete the output file
        if self._output_file_path is not None:
            self._output_file_path.unlink(missing_ok=True)

            # Set the output file path to None
            self._output_file_path = None

        if self._ffmpeg is not None:
            # Terminate ffmpeg
            try:
                self._ffmpeg.terminate()
            except FFmpegError as e:
                pass

            # Set ffmpeg to None
            self._ffmpeg = None

        if not conversion_failed:
            # Exit the application
            sys.exit(0)

    # Get the db entry with the highest bit_rate (video_information.streams[first_video_stream].bit_rate) 
    # that has not been converted yet and is not currently being converted
    def _get_highest_bit_rate(self) -> FileData | None:
        # Get the file with the highest bit rate that has not been converted yet and set converting to True in a single atomic operation
        db_file = media_collection.find_one_and_update({
            "conversion_required": True,
            "converting": False,
            "converted": False,
            "conversion_error": False
        }, {"$set": {"converting": True}}, sort=[("video_information.streams.0.bit_rate", DESCENDING)])

        # Check if there is a file that needs to be converted
        if db_file is not None:
            # Get the file data
            file_data = FileData(**db_file)

            # Return the file data
            return file_data
        else:
            return None

    # Get the db entry with the highest bit_rate (video_information.streams[first_video_stream].bit_rate) 
    # from the TV files that has not been converted yet and is not currently being converted
    def _get_highest_bit_rate_tv(self) -> FileData | None:
        # Get the file with the highest bit rate that has not been converted yet and set converting to True in a single atomic operation
        db_file = media_collection.find_one_and_update({
            "filename": {"$regex": r"\/TV"},
            "conversion_required": True,
            "converting": False,
            "converted": False,
            "conversion_error": False
        }, {"$set": {"converting": True}}, sort=[("video_information.streams.0.bit_rate", DESCENDING)])

        # Check if there is a file that needs to be converted
        if db_file is not None:
            # Get the file data
            file_data = FileData(**db_file)

            # Return the file data
            return file_data
        else:
            return None

    # Get the db entry with the highest bit_rate (video_information.streams[first_video_stream].bit_rate) 
    # that has not been converted yet and is not currently being converted
    def _get_smallest_file(self) -> FileData | None:
        # Get the file with the highest bit rate that has not been converted yet and set converting to True in a single atomic operation
        db_file = media_collection.find_one_and_update({
            "conversion_required": True,
            "converting": False,
            "converted": False,
            "conversion_error": False
        }, {"$set": {"converting": True}}, sort=[("pre_conversion_size", ASCENDING)])

        # Check if there is a file that needs to be converted
        if db_file is not None:
            # Get the file data
            file_data = FileData(**db_file)

            # Return the file data
            return file_data
        else:
            return None

    def convert(self):
        # Get a file that needs to be converted from MongoDB
        if smallest_first:
            self._file_data = self._get_smallest_file()
        elif only_tv_shows:
            self._file_data = self._get_highest_bit_rate_tv()
        else:
            self._file_data = self._get_highest_bit_rate()

        if self._file_data is not None:
            # Log the bitrate of the file we are converting
            if self._file_data.first_video_stream is not None:
                first_video_stream = self._file_data.first_video_stream
            else:
                first_video_stream = 0

            # Log the bitrate of the file we are converting
            logging.info(f"Converting {self._file_data.filename} with bitrate {self._file_data.video_information.streams[first_video_stream].bit_rate}")

            # Update the file_data object
            self._file_data.converting = True
            self._file_data.start_conversion_time = datetime.now()
            self._file_data.backend_name = os.getenv("BACKEND_NAME", "None")

            # Update the file in MongoDB
            media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})

            # Turn the filename into a path
            input_file_path = Path(self._file_data.filename)

            # Create the output file path
            self._output_file_path = (config.config_data.folders.backup / input_file_path.name).with_suffix(".hevc.mkv")

            # Convert the file
            self._ffmpeg = (
                FFmpeg
                .option(FFmpeg(), 'y')
                .input(input_file_path)
                .output(self._output_file_path,
                    {
                        'c:v': 'libx265',
                        'c:a': 'copy',
                        'c:s': 'copy',
                        'crf': 28,
                        'preset': 'medium',
                    }
                )
            )

            # Update the progress bar when ffmpeg emits a progress event
            @self._ffmpeg.on('progress')
            def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
                if self._file_data is not None:
                    # Calculate the percentage complete
                    duration = timedelta(seconds=self._file_data.video_information.format.duration)
                    percentage_complete = (ffmpeg_progress.time / duration) * 100

                    # Update the self._file_data object
                    self._file_data.percentage_complete = percentage_complete

                    # Update the file in MongoDB
                    media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})

            @self._ffmpeg.on('terminated')
            def _on_terminated() -> None:
                if self._file_data is not None:
                    # Log that ffmpeg was terminated
                    logging.info(f"ffmpeg was terminated successfullty for {self._file_data.filename}")

            try:
                # Execute the ffmpeg command
                self._ffmpeg.execute()
            except FFmpegError as e:
                # There was an error executing the ffmpeg command
                logging.error(f"FFmpeg Error executing ffmpeg command for {self._file_data.filename}")
                logging.error(e)

                # Clean up and terminate
                self._cleanup_and_terminate(conversion_failed=True)
            except UnicodeDecodeError as e:
                # There was an error executing the ffmpeg command
                logging.error(f"Unicode Decode Error executing ffmpeg command for {self._file_data.filename}")
                logging.error(e)

                # Clean up and terminate
                self._cleanup_and_terminate(conversion_failed=True)
            else:
                # ffmpeg executed successfully
                logging.info(f"Successfully converted {self._file_data.filename}")

                # Update the file_data object
                self._file_data.converting = False
                self._file_data.converted = True
                self._file_data.conversion_error = False
                self._file_data.end_conversion_time = datetime.now()
                self._file_data.percentage_complete = 100
                self._file_data.current_size = self._output_file_path.stat().st_size

                # Update the file in MongoDB
                media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})

                # Create a path for the backup file
                backup_path = Path(config.config_data.folders.backup, input_file_path.name)

                try:
                    # Log that we are hardlinking the input file to the backup folder
                    logging.info(f'Hardlinking {input_file_path} to backup folder')

                    # Hardlink the input file to the backup folder
                    input_file_path.link_to(backup_path)
                except OSError as e:
                    # There was an error creating the hard link, try copying the file instead
                    try:
                        # Log that the hard link failed
                        logging.info(f'Hardlinking {input_file_path} to backup folder failed, trying to copy instead')

                        # Copy the file to the backup folder
                        shutil.copy2(input_file_path, backup_path)
                    except OSError as e:
                        # There was an error copying the file
                        logging.error(f'Error copying {input_file_path} to backup folder')

                        # Update the file_data object to indicate that there was an error
                        self._file_data.conversion_error = True

                        # Update the file in MongoDB
                        media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})
                    else:
                        # Log that the copy was successful
                        logging.info(f'File {input_file_path} backed up successfully')
                else:
                    # Log that the hard link was successful
                    logging.info(f'File {input_file_path} hardlink created successfully')

                try:
                    # Log that we are replacing the input file with the output file
                    logging.info(f'Replacing {input_file_path} with {self._output_file_path}')

                    # Once the copy is complete, replace the output Path with the input Path (thus overwriting the original)
                    self._output_file_path = self._output_file_path.replace(input_file_path)

                except OSError as e:
                    # If there was an error replacing the file, try copying the file instead
                    try:
                        # Copy the file to the original folder
                        shutil.copy2(self._output_file_path, input_file_path)
                    except OSError as e:
                        # There was an error copying the file
                        logging.error(f'Error copying {self._output_file_path} to {input_file_path}')

                        # Update the file_data object to indicate that there was an error
                        self._file_data.conversion_error = True

                        # Update the file in MongoDB
                        media_collection.update_one({"filename": self._file_data.filename}, {"$set": self._file_data.dict()})
                    else:
                        # Log that the copy was successful
                        logging.info(f'File {self._output_file_path} copied successfully to {input_file_path}')
                else:
                    # Log that the copy and replace was successful
                    logging.info(f'File {input_file_path} replaced successfully with {self._output_file_path}')
