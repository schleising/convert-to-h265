from datetime import datetime
from pathlib import Path

from pydantic import BaseModel


class Disposition(BaseModel):
    default: int | None = None
    dub: int | None = None
    original: int | None = None
    comment: int | None = None
    lyrics: int | None = None
    karaoke: int | None = None
    forced: int | None = None
    hearing_impaired: int | None = None
    visual_impaired: int | None = None
    clean_effects: int | None = None
    attached_pic: int | None = None
    timed_thumbnails: int | None = None
    captions: int | None = None
    descriptions: int | None = None
    metadata: int | None = None
    dependent: int | None = None
    still_image: int | None = None


class Tags(BaseModel):
    language: str | None = None
    handler_name: str | None = None
    vendor_id: str | None = None
    encoder: str | None = None
    title: str | None = None
    creation_time: str | None = None
    duration: str | None = None


class Stream(BaseModel):
    index: int | None = None
    codec_name: str | None = None
    codec_long_name: str | None = None
    profile: str | None = None
    codec_type: str | None = None
    codec_tag_string: str | None = None
    codec_tag: str | None = None
    width: int | None = None
    height: int | None = None
    coded_width: int | None = None
    coded_height: int | None = None
    closed_captions: int | None = None
    film_grain: int | None = None
    has_b_frames: int | None = None
    pix_fmt: str | None = None
    level: int | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    chroma_location: str | None = None
    field_order: str | None = None
    refs: int | None = None
    is_avc: bool | None = None
    nal_length_size: str | None = None
    id: str | None = None
    r_frame_rate: str | None = None
    avg_frame_rate: str | None = None
    time_base: str | None = None
    start_pts: int | None = None
    start_time: str | None = None
    duration_ts: int | None = None
    duration: float | None = None
    bit_rate: int | None = None
    bits_per_raw_sample: int | None = None
    nb_frames: int | None = None
    extradata_size: int | None = None
    disposition: Disposition | None = None
    tags: Tags | None = None
    sample_fmt: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    bits_per_sample: int | None = None
    initial_padding: int | None = None
    display_aspect_ratio: str | None = None
    sample_aspect_ratio: str | None = None
    side_data_list: list[dict] | None = None
    divx_packed: str | None = None
    quarter_sample: str | None = None


class Tags1(BaseModel):
    major_brand: str | None = None
    minor_version: str | None = None
    compatible_brands: str | None = None
    encoder: str | None = None
    creation_time: str | None = None
    title: str | None = None
    comment: str | None = None
    encoder: str | None = None


class Format(BaseModel):
    filename: str | None = None
    nb_streams: int | None = None
    nb_programs: int | None = None
    format_name: str | None = None
    format_long_name: str | None = None
    start_time: float | None = None
    duration: float
    size: int | None = None
    bit_rate: int | None = None
    probe_score: int | None = None
    tags: Tags1 | None = None


class VideoInformation(BaseModel):
    streams: list[Stream]
    format: Format


class FileData(BaseModel):
    filename: str
    inode: int
    deleted: bool
    video_information: VideoInformation
    conversion_required: bool
    converting: bool
    converted: bool
    conversion_error: bool
    copying: bool | None = None
    percentage_complete: float
    start_conversion_time: datetime | None = None
    end_conversion_time: datetime | None = None
    video_streams: int
    audio_streams: int
    subtitle_streams: int
    first_video_stream: int | None = None
    first_audio_stream: int | None = None
    first_subtitle_stream: int | None = None
    pre_conversion_size: int
    current_size: int
    backend_name: str = "None"
    speed: float | None = None


class ConvertedFileDataFromDb(BaseModel):
    filename: str
    pre_conversion_size: int
    current_size: int


class FileInfo:
    def __init__(self, filename: str, inode: int) -> None:
        self.filename = filename
        self.inode = inode