"""Helpers for choosing per-stream audio encode vs copy options."""

from __future__ import annotations

from .models import Stream, VideoInformation

# ffprobe codec_name values treated as already-AAC (stream-copy)
_AAC_CODEC_NAMES = frozenset({"aac"})


def is_aac_codec(codec_name: str | None) -> bool:
    if codec_name is None:
        return False
    return codec_name.strip().lower() in _AAC_CODEC_NAMES


def format_audio_bitrate(bit_rate: int | None, fallback: str) -> str:
    """Format ffprobe bit_rate (bits/s) for ffmpeg ``-b:a`` (e.g. ``192k``)."""
    if bit_rate is None or bit_rate <= 0:
        return fallback

    kilobits = max(1, round(bit_rate / 1000))
    return f"{kilobits}k"


def audio_streams(video_information: VideoInformation) -> list[Stream]:
    return [
        stream
        for stream in video_information.streams
        if stream.codec_type == "audio"
    ]


def build_audio_output_options(
    video_information: VideoInformation,
    *,
    preferred_codec: str,
    fallback_bitrate: str,
    audio_filter: str | None,
) -> dict[str, str]:
    """Build ffmpeg audio options: copy AAC; re-encode others at source bitrate.

    When ``preferred_codec`` is ``\"copy\"``, all audio is stream-copied.
    Otherwise each non-AAC track is encoded with ``preferred_codec`` and a
    bitrate matching the input stream (or ``fallback_bitrate`` if unknown).
    """
    streams = audio_streams(video_information)
    if not streams:
        return {}

    if preferred_codec == "copy":
        return {"c:a": "copy"}

    if all(is_aac_codec(stream.codec_name) for stream in streams):
        return {"c:a": "copy"}

    # Mixed or all non-AAC: set per output-audio-stream index (order of 0:a? maps)
    options: dict[str, str] = {}
    for output_index, stream in enumerate(streams):
        if is_aac_codec(stream.codec_name):
            options[f"c:a:{output_index}"] = "copy"
            continue

        options[f"c:a:{output_index}"] = preferred_codec
        options[f"b:a:{output_index}"] = format_audio_bitrate(
            stream.bit_rate, fallback_bitrate
        )
        if audio_filter:
            options[f"filter:a:{output_index}"] = audio_filter

    return options
