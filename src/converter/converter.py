from datetime import datetime, timedelta
from pathlib import Path
import logging
import signal
import sys

from ffmpeg import FFmpeg, FFmpegError
from ffmpeg import Progress as FFmpegProgress

from .models import FileData
from . import media_collection

class Converter:
    def __init__(self):
        self._ffmpeg: FFmpeg | None= None

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig: int, _):
        # Handle SIGINT and SIGTERM signals to ensure the Docker container stops gracefully
        match sig:
            case signal.SIGINT:
                logging.info("Stopping Conversion due to keyboard interrupt...")
                if self._ffmpeg is not None:
                    self._ffmpeg.terminate()
            case signal.SIGTERM:
                logging.info("Stopping Conversion due to SIGTERM...")
                if self._ffmpeg is not None:
                    self._ffmpeg.terminate()

    def convert(self):
        # Get a file that needs to be converted from MongoDB
        db_file = media_collection.find_one({
            "conversion_required": True,
            "converting": False,
            "converted": False,
            "conversion_error": False
        })

        if db_file is not None:
            # Convert db_file into a FileData object
            file_data = FileData(**db_file)

            # Log that we are converting the file
            logging.info(f"Converting {file_data.filename}")

            # Update the file_data object
            file_data.converting = True
            file_data.start_conversion_time = datetime.now()

            # Update the file in MongoDB
            media_collection.update_one({"filename": file_data.filename}, {"$set": file_data.dict()})

            # Turn the filename into a path
            input_file_path = Path(file_data.filename)

            # Create the output file path
            output_file_path = input_file_path.with_suffix(".hevc.mkv")

            # Convert the file
            self._ffmpeg = (
                FFmpeg
                .option(FFmpeg(), 'y')
                .input(input_file_path)
                .output(output_file_path,
                    {
                        'c:v': 'libx265',
                        'c:a': 'copy',
                        'c:s': 'copy',
                        'preset': 'slow',
                    }
                )
            )

            # Update the progress bar when ffmpeg emits a progress event
            @self._ffmpeg.on('progress')
            def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
                # Calculate the percentage complete
                duration = timedelta(seconds=file_data.video_information.format.duration)
                percentage_complete = (ffmpeg_progress.time / duration) * 100

                # Update the file_data object
                file_data.percentage_complete = percentage_complete

                # Update the file in MongoDB
                media_collection.update_one({"filename": file_data.filename}, {"$set": file_data.dict()})

            @self._ffmpeg.on('terminated')
            def _on_terminated() -> None:
                # Log that ffmpeg was terminated and we are cleaning up
                logging.info(f"ffmpeg was terminated for {file_data.filename}. Cleaning up...")
                self._ffmpeg = None

                # Update the file_data object
                file_data.converting = False
                file_data.start_conversion_time = None

                # Update the file in MongoDB
                media_collection.update_one({"filename": file_data.filename}, {"$set": file_data.dict()})

                # Delete the output file
                output_file_path.unlink()

                # Exit the application
                sys.exit(0)

            try:
                # Execute the ffmpeg command
                self._ffmpeg.execute()
            except FFmpegError as e:
                # There was an error executing the ffmpeg command
                logging.error(f"Error executing ffmpeg command for {file_data.filename}")
                logging.error(e)

                # Update the file_data object
                file_data.converting = False
                file_data.start_conversion_time = None

                # Update the file in MongoDB
                media_collection.update_one({"filename": file_data.filename}, {"$set": file_data.dict()})
                return
            else:
                # ffmpeg executed successfully
                logging.info(f"Successfully converted {file_data.filename}")

                # Update the file_data object
                file_data.converting = False
                file_data.converted = True
                file_data.conversion_error = False
                file_data.end_conversion_time = datetime.now()
                file_data.percentage_complete = 100
                file_data.current_size = output_file_path.stat().st_size

                # Update the file in MongoDB
                media_collection.update_one({"filename": file_data.filename}, {"$set": file_data.dict()})
            finally:
                self._ffmpeg = None
