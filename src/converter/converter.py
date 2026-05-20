from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import logging
import signal
import subprocess
import sys
import shutil
import os
from typing import Any

from pymongo import DESCENDING
from pymongo.errors import ServerSelectionTimeoutError, NetworkTimeout, AutoReconnect

from ffmpeg import FFmpeg, FFmpegError
from ffmpeg import Progress as FFmpegProgress

from pywebpush import webpush, WebPushException

from requests.status_codes import codes

from .models import FileData
from . import media_collection, push_collection, config, NOTIFICATION_TTL


class Converter:
    _validated_encoders: set[str] = set()
    _copy_chunk_size = 8 * 1024 * 1024
    _progress_update_interval_seconds = 1.0

    def __init__(self):
        # Create ffmpeg object and set it to None
        self._ffmpeg: FFmpeg | None = None

        # Create file_data object and set it to None
        self._file_data: FileData | None = None

        # Create the temporary input and output paths and set them to None
        self._temporary_input_path: Path | None = None
        self._temporary_output_path: Path | None = None

        # Create the backup path and set it to None
        self._backup_path: Path | None = None

        # Track the last persisted progress update so copy and conversion progress
        # do not overwhelm MongoDB with writes.
        self._last_progress_update_time: datetime | None = None

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _resolve_source_path(self, filename: str) -> Path:
        source_path = Path(filename)
        source_root = config.config_data.path_map.source
        destination_root = config.config_data.path_map.destination

        try:
            relative_path = source_path.relative_to(source_root)
        except ValueError:
            return source_path

        return destination_root / relative_path

    def _get_first_video_height(self) -> int | None:
        if self._file_data is None:
            return None

        first_video_stream = self._file_data.first_video_stream
        if first_video_stream is None:
            return None

        return self._file_data.video_information.streams[first_video_stream].height

    def _get_subtitle_codec(self) -> str:
        if self._file_data is None or self._file_data.subtitle_streams == 0:
            return "copy"

        if any(
            stream.codec_name == "mov_text"
            for stream in self._file_data.video_information.streams
            if stream.codec_type == "subtitle"
        ):
            return "srt"

        return "copy"

    def _ensure_encoder_available(self, video_codec: str) -> None:
        if video_codec in self._validated_encoders:
            return

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg is not installed or not on PATH")

        encoder_list = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
            errors="ignore",
        )

        if video_codec not in encoder_list.stdout:
            raise RuntimeError(f"ffmpeg encoder '{video_codec}' is not available")

        logging.info(f"Using video encoder {video_codec}")
        self._validated_encoders.add(video_codec)

    def _build_output_options(self, subtitle_codec: str) -> dict[str, Any]:
        encoding = config.config_data.encoding
        video_codec = encoding.video_codec
        video_height = self._get_first_video_height()
        use_small_height_profile = (
            video_height is not None and video_height <= encoding.small_height_threshold
        )

        options = {
            "c:v": video_codec,
            "c:a": "copy",
            "c:s": subtitle_codec,
        }

        if video_codec == "libx265":
            crf = (
                encoding.x265_crf_small_height
                if use_small_height_profile
                else encoding.x265_crf
            )
            options["crf"] = str(crf)
            options["preset"] = encoding.x265_preset
        elif video_codec == "hevc_videotoolbox":
            qv = (
                encoding.vt_qv_small_height
                if use_small_height_profile
                else encoding.vt_qv
            )
            options["q:v"] = str(qv)
            options["g"] = str(encoding.vt_g)
            options["keyint_min"] = str(encoding.vt_keyint_min)
            options["spatial_aq"] = str(encoding.vt_spatial_aq)
            options["realtime"] = str(encoding.vt_realtime)
        else:
            raise RuntimeError(f"Unsupported video codec '{video_codec}'")

        return options

    def _get_secrets_path(self, filename: str) -> Path:
        return config.config_data.runtime.secrets_dir / filename

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _update_percentage_complete(
        self,
        percentage_complete: float,
        *,
        speed: float | None = None,
        force: bool = False,
    ) -> None:
        if self._file_data is None:
            return

        now = self._utc_now()
        bounded_percentage = max(0.0, min(percentage_complete, 100.0))

        if not force and self._last_progress_update_time is not None:
            if (
                now - self._last_progress_update_time
            ).total_seconds() < self._progress_update_interval_seconds:
                return

        self._file_data.percentage_complete = bounded_percentage

        update_fields: dict[str, Any] = {
            "percentage_complete": self._file_data.percentage_complete,
        }

        if speed is not None:
            self._file_data.speed = speed
            update_fields["speed"] = speed

        try:
            media_collection.update_one(
                {"filename": self._file_data.filename},
                {"$set": update_fields},
            )
        except ServerSelectionTimeoutError:
            pass
        except NetworkTimeout:
            pass
        except AutoReconnect:
            pass
        else:
            self._last_progress_update_time = now

    def _copy_file_with_progress(
        self,
        source_path: Path,
        destination_path: Path,
        *,
        base_bytes: int = 0,
        total_bytes: int | None = None,
    ) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_size = source_path.stat().st_size
        total_size = total_bytes if total_bytes is not None else source_size
        bytes_copied = 0

        self._update_percentage_complete(0, force=True)

        try:
            with source_path.open("rb") as source_file, destination_path.open(
                "wb"
            ) as destination_file:
                while True:
                    chunk = source_file.read(self._copy_chunk_size)
                    if not chunk:
                        break

                    destination_file.write(chunk)
                    bytes_copied += len(chunk)

                    if total_size > 0:
                        percentage_complete = (
                            (base_bytes + bytes_copied) / total_size
                        ) * 100
                    else:
                        percentage_complete = 100

                    self._update_percentage_complete(percentage_complete)

            shutil.copystat(source_path, destination_path)
        except OSError:
            destination_path.unlink(missing_ok=True)
            raise

        if total_size > 0:
            final_percentage = ((base_bytes + source_size) / total_size) * 100
        else:
            final_percentage = 100

        self._update_percentage_complete(final_percentage, force=True)

    def _signal_handler(self, sig: int, _):
        # Handle SIGINT and SIGTERM signals to ensure the Docker container stops gracefully
        match sig:
            case signal.SIGINT:
                logging.info("Stopping Conversion due to keyboard interrupt...")
                self._cleanup_and_terminate()
            case signal.SIGTERM:
                logging.info("Stopping Conversion due to SIGTERM...")
                self._cleanup_and_terminate()

    def _delete_temporary_files(self) -> None:
        if self._temporary_input_path is not None:
            try:
                self._temporary_input_path.unlink(missing_ok=True)
            except OSError as e:
                logging.error(f"Error deleting temp input {self._temporary_input_path}")
                logging.error(e)

            self._temporary_input_path = None

        if self._temporary_output_path is not None:
            try:
                self._temporary_output_path.unlink(missing_ok=True)
            except OSError as e:
                logging.error(f"Error deleting temp output {self._temporary_output_path}")
                logging.error(e)

            self._temporary_output_path = None

    def _cleanup_and_terminate(self, conversion_failed: bool = False) -> None:
        if self._file_data is not None:
            # Log that ffmpeg was terminated and we are cleaning up
            logging.info(
                f"ffmpeg terminating for {self._file_data.filename}. Cleaning up..."
            )

            # Update the file_data object
            self._file_data.converting = False
            self._file_data.copying = False
            self._file_data.start_conversion_time = None
            self._file_data.percentage_complete = 0

            if conversion_failed:
                self._file_data.conversion_error = True

                # Send a notification
                self.send_notification(
                    "Conversion Failed", f"{Path(self._file_data.filename).name}"
                )

            try:
                # Update fields converting, start_conversion_time and percentage_complete the in MongoDB
                media_collection.update_one(
                    {"filename": self._file_data.filename},
                    {
                        "$set": {
                            "converting": False,
                            "copying": False,
                            "start_conversion_time": None,
                            "percentage_complete": 0,
                            "conversion_error": self._file_data.conversion_error,
                        }
                    },
                )
            except ServerSelectionTimeoutError:
                logging.error("Could not connect to MongoDB.")
            except NetworkTimeout:
                logging.error("Could not connect to MongoDB.")
            except AutoReconnect:
                logging.error("Could not connect to MongoDB.")

            # Set the file_data object to None
            self._file_data = None

        # Terminate ffmpeg
        if self._ffmpeg is not None:
            try:
                self._ffmpeg.terminate()
            except FFmpegError as e:
                pass

            # Set ffmpeg to None
            self._ffmpeg = None

        # Delete the temporary input and output files
        self._delete_temporary_files()

        # Delete the backup file
        if self._backup_path is not None:
            try:
                self._backup_path.unlink(missing_ok=True)
            except OSError as e:
                logging.error(f"Error deleting backup {self._backup_path}")
                logging.error(e)

            # Set the backup path to None
            self._backup_path = None

        if not conversion_failed:
            # Exit the application
            sys.exit(0)

    # Get the db entry with the highest bit_rate (video_information.format.bit_rate)
    # that has not been converted yet and is not currently being converted
    def _get_highest_bit_rate(self) -> FileData | None:
        # Get the file with the highest bit rate that has not been converted yet and set converting to True in a single atomic operation
        try:
            db_file = media_collection.find_one_and_update(
                {
                    "conversion_required": True,
                    "converting": False,
                    "converted": False,
                    "conversion_error": False,
                    "deleted": False,
                },
                {"$set": {"converting": True}},
                sort=[("video_information.format.bit_rate", DESCENDING)],
            )
        except ServerSelectionTimeoutError:
            logging.error("Could not connect to MongoDB.")
            db_file = None
        except NetworkTimeout:
            logging.error("Could not connect to MongoDB.")
            db_file = None
        except AutoReconnect:
            logging.error("Could not connect to MongoDB.")
            db_file = None

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
        self._file_data = self._get_highest_bit_rate()

        if self._file_data is not None:
            # Map the stored Docker path to the local filesystem path when needed
            input_file_path = self._resolve_source_path(self._file_data.filename)

            if input_file_path != Path(self._file_data.filename):
                logging.info(
                    f"Mapped source path {self._file_data.filename} to {input_file_path}"
                )

            # Check if the file exists
            if not input_file_path.exists():
                # Log that the file does not exist
                logging.error(
                    f"{input_file_path} does not exist, you probably need to mount the folder containing it or check the path mapping."
                )

                # Indicate in the db that this file is not converting anymore
                self._file_data.converting = False

                try:
                    # Update the file in MongoDB
                    media_collection.update_one(
                        {"filename": self._file_data.filename},
                        {
                            "$set": {
                                "converting": self._file_data.converting,
                            }
                        },
                    )
                except ServerSelectionTimeoutError:
                    logging.error("Could not connect to MongoDB.")
                except NetworkTimeout:
                    logging.error("Could not connect to MongoDB.")
                except AutoReconnect:
                    logging.error("Could not connect to MongoDB.")

                # Set the output file path to None and return without converting
                self._file_data = None
                return

            # Log the bitrate of the file we are converting
            logging.info(
                f"Converting {self._file_data.filename} with bitrate {self._file_data.video_information.format.bit_rate}"
            )

            # Update the file_data object
            self._file_data.converting = True
            self._file_data.start_conversion_time = self._utc_now()
            self._file_data.backend_name = os.getenv("BACKEND_NAME", "None")
            self._file_data.speed = 0
            self._file_data.copying = True
            self._file_data.percentage_complete = 0
            self._last_progress_update_time = None

            try:
                # Update the file in MongoDB
                media_collection.update_one(
                    {"filename": self._file_data.filename},
                    {
                        "$set": {
                            "converting": self._file_data.converting,
                            "start_conversion_time": self._file_data.start_conversion_time,
                            "backend_name": self._file_data.backend_name,
                            "speed": 0,
                            "copying": self._file_data.copying,
                            "percentage_complete": self._file_data.percentage_complete,
                        }
                    },
                )
            except ServerSelectionTimeoutError:
                logging.error("Could not connect to MongoDB.")

                # Set the output file path to None and return without converting
                self._file_data = None
                return
            except NetworkTimeout:
                logging.error("Could not connect to MongoDB.")

                # Set the output file path to None and return without converting
                self._file_data = None
                return
            except AutoReconnect:
                logging.error("Could not connect to MongoDB.")

                # Set the output file path to None and return without converting
                self._file_data = None
                return

            # Get filename and extension
            filename = input_file_path.stem
            extension = input_file_path.suffix

            # Ensure the conversion staging directory exists before copying
            config.config_data.folders.conversions.mkdir(parents=True, exist_ok=True)

            # Create temporary input and output paths
            self._temporary_input_path = Path(
                config.config_data.folders.conversions, filename + extension
            )
            self._temporary_output_path = Path(
                config.config_data.folders.conversions, filename + ".hevc.mkv"
            )

            # Copy the file to the temporary input path
            self._copy_file_with_progress(
                input_file_path,
                self._temporary_input_path,
            )

            # Set the start conversion tima and clear the copying flag in the db and the file_data object
            self._file_data.start_conversion_time = self._utc_now()
            self._file_data.copying = False

            try:
                # Update the file in MongoDB
                media_collection.update_one(
                    {"filename": self._file_data.filename},
                    {
                        "$set": {
                            "start_conversion_time": self._file_data.start_conversion_time,
                            "copying": self._file_data.copying,
                        }
                    },
                )
            except ServerSelectionTimeoutError:
                logging.error(
                    "Could not connect to MongoDB, ServerSelectionTimeoutError"
                )

                # Set the output file path to None and return without converting
                self._file_data = None

                # Clean up and terminate
                self._cleanup_and_terminate()

                return
            except NetworkTimeout:
                logging.error("Could not connect to MongoDB, NetworkTimeout")

                # Set the output file path to None and return without converting
                self._file_data = None

                # Clean up and terminate
                self._cleanup_and_terminate()

                return
            except AutoReconnect:
                logging.error("Could not connect to MongoDB, AutoReconnect")

                # Set the output file path to None and return without converting
                self._file_data = None

                # Clean up and terminate
                self._cleanup_and_terminate()

                return

            # Set the subtitles to copy by default
            subtitle_codec = self._get_subtitle_codec()

            mapping: list[str] = []
            first_video_stream = self._file_data.first_video_stream

            # Build map list
            if self._file_data.video_streams > 0:
                mapping.append(f"0:{first_video_stream}")

            if self._file_data.audio_streams > 0:
                mapping.append(f"0:a")

            if self._file_data.subtitle_streams > 0:
                mapping.append("0:s")

            output_options = self._build_output_options(subtitle_codec)

            try:
                self._ensure_encoder_available(output_options["c:v"])
            except (RuntimeError, subprocess.CalledProcessError) as e:
                logging.error(e)
                self._cleanup_and_terminate(conversion_failed=True)
                return

            # Convert the file
            self._ffmpeg = (
                FFmpeg.option(FFmpeg(), "y")
                .input(self._temporary_input_path)
                .output(
                    self._temporary_output_path,
                    output_options,
                    map=mapping,
                )
            )

            # Log the ffmpeg command
            logging.info(f'ffmpeg command: {" ".join(self._ffmpeg.arguments)}')

            # Store the last update time
            self._last_progress_update_time = None

            # Update the progress bar when ffmpeg emits a progress event
            @self._ffmpeg.on("progress")
            def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
                if self._file_data is not None:
                    # Calculate the percentage complete
                    duration = timedelta(
                        seconds=self._file_data.video_information.format.duration
                    )
                    percentage_complete = (ffmpeg_progress.time / duration) * 100

                    self._update_percentage_complete(
                        percentage_complete,
                        speed=ffmpeg_progress.speed,
                    )

                    # Log the progress
                    logging.debug(ffmpeg_progress)

            @self._ffmpeg.on("terminated")
            def _on_terminated() -> None:
                if self._file_data is not None:
                    # Log that ffmpeg was terminated
                    logging.info(
                        f"ffmpeg was terminated successfullty for {self._file_data.filename}"
                    )

            try:
                # Execute the ffmpeg command
                self._ffmpeg.execute()
            except FFmpegError as e:
                # There was an error executing the ffmpeg command
                logging.error(
                    f"FFmpeg Error executing ffmpeg command for {self._file_data.filename}"
                )
                logging.error(e)

                # Clean up and terminate
                self._cleanup_and_terminate(conversion_failed=True)
            except UnicodeDecodeError as e:
                # There was an error executing the ffmpeg command
                logging.error(
                    f"Unicode Decode Error executing ffmpeg command for {self._file_data.filename}"
                )
                logging.error(e)

                # Clean up and terminate
                self._cleanup_and_terminate(conversion_failed=True)
            except ValueError as e:
                # There was an error executing the ffmpeg command
                logging.error(
                    f"Value Error executing ffmpeg command for {self._file_data.filename}"
                )
                logging.error(e)

                # Clean up and terminate
                self._cleanup_and_terminate(conversion_failed=True)
            else:
                # ffmpeg executed successfully
                logging.info(f"Successfully converted {self._file_data.filename}")

                # Check that the file size has been reduced
                file_size_reduced = (
                    self._temporary_output_path.stat().st_size
                    < input_file_path.stat().st_size
                )

                # Update the file_data object
                self._file_data.converting = False
                self._file_data.converted = True
                self._file_data.conversion_error = False
                self._file_data.copying = True if file_size_reduced else False
                self._file_data.end_conversion_time = self._utc_now()
                self._file_data.percentage_complete = 0 if file_size_reduced else 100
                self._file_data.current_size = (
                    self._temporary_output_path.stat().st_size
                    if file_size_reduced
                    else input_file_path.stat().st_size
                )

                # Update the file in MongoDB
                try:
                    media_collection.update_one(
                        {"filename": self._file_data.filename},
                        {
                            "$set": {
                                "converting": self._file_data.converting,
                                "converted": self._file_data.converted,
                                "conversion_error": self._file_data.conversion_error,
                                "copying": self._file_data.copying,
                                "end_conversion_time": self._file_data.end_conversion_time,
                                "percentage_complete": self._file_data.percentage_complete,
                                "current_size": self._file_data.current_size,
                            }
                        },
                    )
                except ServerSelectionTimeoutError:
                    logging.error("Could not connect to MongoDB.")

                    # Clean up and terminate
                    self._cleanup_and_terminate()

                    # Exit without swapping the converted file for the original
                    return
                except NetworkTimeout:
                    logging.error("Could not connect to MongoDB.")

                    # Clean up and terminate
                    self._cleanup_and_terminate()

                    # Exit without swapping the converted file for the original
                    return
                except AutoReconnect:
                    logging.error("Could not connect to MongoDB.")

                    # Clean up and terminate
                    self._cleanup_and_terminate()

                    # Exit without swapping the converted file for the original
                    return

                # Exit without swapping the converted file for the original if the file size was not reduced
                if not file_size_reduced:
                    # Send a notification
                    self.send_notification(
                        "File Size not Reduced",
                        f"{self._temporary_input_path.name}\n{(1 - (self._file_data.current_size / self._file_data.pre_conversion_size)) * 100:.0f}%",
                    )
                    self._delete_temporary_files()
                    return

                # Create a path for the backup file
                self._backup_path = Path(
                    config.config_data.folders.backup, self._temporary_input_path.name
                )
                total_post_copy_bytes = (
                    self._temporary_input_path.stat().st_size
                    + self._temporary_output_path.stat().st_size
                )
                completed_post_copy_bytes = 0

                self._backup_path.parent.mkdir(parents=True, exist_ok=True)

                try:
                    # Log that we are hardlinking the input file to the backup folder
                    logging.info(
                        f"Hardlinking {self._temporary_input_path} to backup folder"
                    )

                    # Hardlink the input file to the backup folder
                    self._backup_path.hardlink_to(self._temporary_input_path)
                except OSError as e:
                    # There was an error creating the hard link, try copying the file instead
                    try:
                        # Log that the hard link failed
                        logging.info(
                            f"Hardlinking {self._temporary_input_path} to backup folder failed, trying to copy instead"
                        )

                        # Copy the file to the backup folder
                        self._copy_file_with_progress(
                            self._temporary_input_path,
                            self._backup_path,
                            base_bytes=completed_post_copy_bytes,
                            total_bytes=total_post_copy_bytes,
                        )
                        completed_post_copy_bytes += self._temporary_input_path.stat().st_size
                    except OSError as e:
                        # There was an error copying the file
                        logging.error(
                            f"Error copying {self._temporary_input_path} to backup folder"
                        )
                        logging.error(e)

                        # Update the file_data object to indicate that there was an error
                        self._file_data.conversion_error = True
                        self._file_data.copying = False

                        try:
                            # Update the file in MongoDB
                            media_collection.update_one(
                                {"filename": self._file_data.filename},
                                {
                                    "$set": {
                                        "conversion_error": self._file_data.conversion_error,
                                        "copying": self._file_data.copying,
                                    }
                                },
                            )
                        except ServerSelectionTimeoutError:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return
                        except NetworkTimeout:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return
                        except AutoReconnect:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return

                        # Send a notification
                        self.send_notification(
                            "Backup Failed", f"{Path(self._file_data.filename).name}"
                        )

                        # Clean up and terminate
                        self._cleanup_and_terminate()
                    else:
                        # Log that the copy was successful
                        logging.info(
                            f"File {self._temporary_input_path} backed up successfully"
                        )
                else:
                    # Log that the hard link was successful
                    logging.info(
                        f"File {self._temporary_input_path} hardlink created successfully"
                    )
                    completed_post_copy_bytes += self._temporary_input_path.stat().st_size
                    if total_post_copy_bytes > 0:
                        backup_percentage = (
                            completed_post_copy_bytes / total_post_copy_bytes
                        ) * 100
                    else:
                        backup_percentage = 100
                    self._update_percentage_complete(backup_percentage, force=True)

                try:
                    # Log that we are replacing the input file with the output file
                    logging.info(
                        f"Replacing {input_file_path} with {self._temporary_output_path}"
                    )

                    # Once the copy is complete, replace the output Path with the input Path (thus overwriting the original)
                    self._temporary_output_path.replace(input_file_path)

                except OSError as e:
                    # If there was an error replacing the file, try copying the file instead
                    try:
                        # Log that the replace failed
                        logging.info(
                            f"Replacing {input_file_path} with {self._temporary_output_path} failed, trying to copy instead"
                        )

                        # Copy the file to the original folder
                        self._copy_file_with_progress(
                            self._temporary_output_path,
                            input_file_path,
                            base_bytes=completed_post_copy_bytes,
                            total_bytes=total_post_copy_bytes,
                        )
                    except OSError as e:
                        # There was an error copying the file
                        logging.error(
                            f"Error copying {self._temporary_output_path} to {input_file_path}"
                        )
                        logging.error(e)

                        # Update the file_data object to indicate that there was an error
                        self._file_data.conversion_error = True
                        self._file_data.copying = False

                        try:
                            # Update the file in MongoDB
                            media_collection.update_one(
                                {"filename": self._file_data.filename},
                                {
                                    "$set": {
                                        "conversion_error": self._file_data.conversion_error,
                                        "copying": self._file_data.copying,
                                    }
                                },
                            )
                        except ServerSelectionTimeoutError:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return
                        except NetworkTimeout:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return
                        except AutoReconnect:
                            logging.error("Could not connect to MongoDB.")

                            # Clean up and terminate
                            self._cleanup_and_terminate()

                            # Exit without swapping the converted file for the original
                            return

                        # Send a notification
                        self.send_notification(
                            "Restore Failed", f"{Path(self._file_data.filename).name}"
                        )

                        # Clean up and terminate
                        self._cleanup_and_terminate()
                    else:
                        # Log that the copy was successful
                        logging.info(
                            f"File {self._temporary_output_path} copied successfully to {input_file_path}"
                        )

                        # Update the file_data object
                        self._file_data.copying = False
                        self._file_data.percentage_complete = 100

                        # Get the new inode of the file
                        new_inode = input_file_path.stat().st_ino

                        # Update the file in MongoDB
                        try:
                            media_collection.update_one(
                                {"filename": self._file_data.filename},
                                {
                                    "$set": {
                                        "copying": self._file_data.copying,
                                        "percentage_complete": self._file_data.percentage_complete,
                                        "inode": new_inode,
                                    }
                                },
                            )
                        except ServerSelectionTimeoutError:
                            logging.error("Could not connect to MongoDB.")

                            # Exit without swapping the converted file for the original
                            return
                        except NetworkTimeout:
                            logging.error("Could not connect to MongoDB.")

                            # Exit without swapping the converted file for the original
                            return
                        except AutoReconnect:
                            logging.error("Could not connect to MongoDB.")

                            # Exit without swapping the converted file for the original
                            return

                        # Send a notification
                        self.send_notification(
                            "Conversion Success",
                            f"{input_file_path.name}\n{(1 - (self._file_data.current_size / self._file_data.pre_conversion_size)) * 100:.0f}%",
                        )
                else:
                    # Log that the copy and replace was successful
                    logging.info(
                        f"File {input_file_path} replaced successfully with {self._temporary_output_path}"
                    )

                    # Update the file_data object
                    self._file_data.copying = False
                    self._file_data.percentage_complete = 100
                    self._update_percentage_complete(100, force=True)

                    # Get the new inode of the file
                    new_inode = input_file_path.stat().st_ino

                    # Update the file in MongoDB
                    try:
                        media_collection.update_one(
                            {"filename": self._file_data.filename},
                            {
                                "$set": {
                                    "copying": self._file_data.copying,
                                        "percentage_complete": self._file_data.percentage_complete,
                                    "inode": new_inode,
                                }
                            },
                        )
                    except ServerSelectionTimeoutError:
                        logging.error("Could not connect to MongoDB.")

                        # Exit without swapping the converted file for the original
                        return
                    except NetworkTimeout:
                        logging.error("Could not connect to MongoDB.")

                        # Exit without swapping the converted file for the original
                        return
                    except AutoReconnect:
                        logging.error("Could not connect to MongoDB.")

                        # Exit without swapping the converted file for the original
                        return

                    # Send a notification
                    self.send_notification(
                        "Conversion Success",
                        f"{input_file_path.name}\n{(1 - (self._file_data.current_size / self._file_data.pre_conversion_size)) * 100:.0f}%",
                    )

                # Delete the temporary input and output files
                if self._temporary_input_path is not None:
                    try:
                        self._temporary_input_path.unlink(missing_ok=True)
                    except OSError as e:
                        logging.error(
                            f"Error deleting temp input {self._temporary_input_path}"
                        )
                        logging.error(e)

                    # Set the output file path to None
                    self._temporary_input_path = None

                if self._temporary_output_path is not None:
                    try:
                        self._temporary_output_path.unlink(missing_ok=True)
                    except OSError as e:
                        logging.error(
                            f"Error deleting temp output {self._temporary_output_path}"
                        )
                        logging.error(e)

                    # Set the output file path to None
                    self._temporary_output_path = None

    # Send a push notification for the file conversion status
    def send_notification(self, title: str, message: str) -> None:
        logging.info(f"Sending notification: {title} - {message}")
        # Get the subscriptions from the database
        if push_collection is not None:
            subscriptions = push_collection.find()

            # Load the claims
            claims_path = self._get_secrets_path("claims.json")
            private_key_path = self._get_secrets_path("private_key.pem")

            try:
                with claims_path.open("r") as file:
                    claims = json.load(file)
            except FileNotFoundError:
                logging.error("Could not find claims.json")
                return

            # Check the private key exists
            if not private_key_path.exists():
                logging.error("Could not find private_key.pem")
                return

            # Send the push notifications
            for subscription in subscriptions:
                logging.debug(f"Sending notification to {subscription}")

                try:
                    webpush(
                        subscription_info=subscription,
                        data=json.dumps(
                            {
                                "title": title,
                                "body": message,
                                "icon": "/icons/tools/converter/android-chrome-192x192-20260504.png",
                                "badge": "/icons/tools/converter/badge-192x192-v2-0-2.png",
                                "url": "/",
                                "requireInteraction": True,
                            }
                        ),
                        headers={"Urgency": "normal"},
                        ttl=NOTIFICATION_TTL,
                        vapid_private_key=str(private_key_path),
                        vapid_claims=claims,
                    )
                except WebPushException as ex:
                    logging.error(f"Error sending notification: {ex}")

                    if ex.response is not None:
                        logging.error(f"Status code: {ex.response.status_code}")
                        logging.error(f"Reason: {ex.response.reason}")
                        logging.error(f"Content: {ex.response.text.strip()}")

                        if ex.response.status_code in [codes.not_found, codes.gone]:
                            logging.error(
                                "Subscription is no longer valid, removing from database"
                            )
                            # Remove the subscription from the database
                            push_collection.delete_one({"_id": subscription["_id"]})
                else:
                    logging.debug("Notification sent successfully")
