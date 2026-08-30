"""Shared ffprobe helpers for walker ingest and post-conversion metadata."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from pathlib import Path

from pydantic import ValidationError

from .models import VideoInformation
from .unicode_paths import resolve_filesystem_path

FFPROBE_BASE_COMMAND = [
    "ffprobe",
    "-v",
    "quiet",
    "-print_format",
    "json",
    "-show_format",
    "-show_streams",
]


class ProbeError(Exception):
    """ffprobe failed or output could not be parsed."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


@dataclass(frozen=True)
class StreamSummary:
    video_streams: int
    audio_streams: int
    subtitle_streams: int
    first_video_stream: int | None
    first_audio_stream: int | None
    first_subtitle_stream: int | None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "video_streams": self.video_streams,
            "audio_streams": self.audio_streams,
            "subtitle_streams": self.subtitle_streams,
            "first_video_stream": self.first_video_stream,
            "first_audio_stream": self.first_audio_stream,
            "first_subtitle_stream": self.first_subtitle_stream,
        }


def probe_video_information(path: Path) -> VideoInformation:
    """Run ffprobe on ``path`` and return parsed ``VideoInformation``."""
    resolved = resolve_filesystem_path(path)
    command = [*FFPROBE_BASE_COMMAND, resolved.as_posix()]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode != 0:
        raise ProbeError(
            f"ffprobe failed for {resolved}",
            stderr=result.stderr.strip(),
        )

    try:
        return VideoInformation.parse_raw(result.stdout)
    except ValidationError as exc:
        raise ProbeError(
            f"Could not parse ffprobe output for {resolved}: {exc}",
            stderr=result.stderr.strip(),
        ) from exc


def summarize_streams(video_information: VideoInformation) -> StreamSummary:
    """Derive stream counts and first-stream indices from ffprobe output."""
    video_stream_count = 0
    audio_stream_count = 0
    subtitle_stream_count = 0
    first_video_stream: int | None = None
    first_audio_stream: int | None = None
    first_eng_audio_stream: int | None = None
    first_und_audio_stream: int | None = None
    first_subtitle_stream: int | None = None

    for stream in video_information.streams:
        if stream.codec_type == "video":
            if first_video_stream is None:
                first_video_stream = stream.index
            video_stream_count += 1
        elif stream.codec_type == "audio":
            if first_audio_stream is None:
                first_audio_stream = stream.index

            if stream.tags:
                if stream.tags.language == "eng" and first_eng_audio_stream is None:
                    first_eng_audio_stream = stream.index
                if stream.tags.language == "und" and first_und_audio_stream is None:
                    first_und_audio_stream = stream.index

            audio_stream_count += 1
        elif stream.codec_type == "subtitle":
            if first_subtitle_stream is None:
                first_subtitle_stream = stream.index
            subtitle_stream_count += 1

    if first_video_stream is None:
        first_video_stream = 0

    if first_eng_audio_stream is not None:
        first_audio_stream = first_eng_audio_stream
    elif first_und_audio_stream is not None:
        first_audio_stream = first_und_audio_stream

    if first_audio_stream is None:
        first_audio_stream = 1

    return StreamSummary(
        video_streams=video_stream_count,
        audio_streams=audio_stream_count,
        subtitle_streams=subtitle_stream_count,
        first_video_stream=first_video_stream,
        first_audio_stream=first_audio_stream,
        first_subtitle_stream=first_subtitle_stream,
    )
