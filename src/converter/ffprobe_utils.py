"""Helpers for ffprobe rate/frame metadata used by encode progress."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Stream, VideoInformation


@dataclass(frozen=True)
class FrameEstimate:
    total_frames: int
    source: str  # "nb_frames" | "duration_x_fps"


def parse_ffprobe_rate(rate: str | None) -> float | None:
    """Parse ffprobe frame rates like ``"24000/1001"`` or ``"25/1"``."""
    if rate is None:
        return None

    text = rate.strip()
    if not text or text in {"0/0", "N/A", "nan"}:
        return None

    try:
        if "/" in text:
            numerator_text, denominator_text = text.split("/", 1)
            numerator = float(numerator_text)
            denominator = float(denominator_text)
            if denominator == 0:
                return None
            value = numerator / denominator
        else:
            value = float(text)
    except ValueError:
        return None

    if value <= 0:
        return None
    return value


def estimate_total_video_frames(
    video_information: VideoInformation,
    first_video_stream: int | None,
) -> FrameEstimate | None:
    """Estimate output video frame count for the mapped encode stream.

    Priority:
    1. ``stream.nb_frames`` when present and positive
    2. ``duration × fps`` using stream/container duration and avg/r frame rate
    """
    stream = _mapped_video_stream(video_information, first_video_stream)
    if stream is None:
        return None

    if stream.nb_frames is not None and stream.nb_frames > 0:
        return FrameEstimate(total_frames=stream.nb_frames, source="nb_frames")

    fps = parse_ffprobe_rate(stream.avg_frame_rate) or parse_ffprobe_rate(
        stream.r_frame_rate
    )
    duration = stream.duration
    if duration is None or duration <= 0:
        duration = video_information.format.duration

    if fps is not None and duration is not None and duration > 0:
        return FrameEstimate(
            total_frames=max(1, round(duration * fps)),
            source="duration_x_fps",
        )

    return None


def _mapped_video_stream(
    video_information: VideoInformation,
    first_video_stream: int | None,
) -> Stream | None:
    if first_video_stream is None:
        return None

    for stream in video_information.streams:
        if stream.index == first_video_stream and stream.codec_type == "video":
            return stream

    if 0 <= first_video_stream < len(video_information.streams):
        candidate = video_information.streams[first_video_stream]
        if candidate.codec_type == "video":
            return candidate

    return None
