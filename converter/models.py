from pydantic import BaseModel

class Disposition(BaseModel):
    default: int | None
    dub: int | None
    original: int | None
    comment: int | None
    lyrics: int | None
    karaoke: int | None
    forced: int | None
    hearing_impaired: int | None
    visual_impaired: int | None
    clean_effects: int | None
    attached_pic: int | None
    timed_thumbnails: int | None
    captions: int | None
    descriptions: int | None
    metadata: int | None
    dependent: int | None
    still_image: int | None

class Tags(BaseModel):
    language: str | None
    handler_name: str | None
    vendor_id: str | None
    encoder: str | None

class Stream(BaseModel):
    index: int | None
    codec_name: str | None
    codec_long_name: str | None
    profile: str | None
    codec_type: str | None
    codec_tag_string: str | None
    codec_tag: str | None
    width: int | None
    height: int | None
    coded_width: int | None
    coded_height: int | None
    closed_captions: int | None
    film_grain: int | None
    has_b_frames: int | None
    pix_fmt: str | None
    level: int | None
    color_range: str | None
    color_space: str | None
    color_transfer: str | None
    color_primaries: str | None
    chroma_location: str | None
    field_order: str | None
    refs: int | None
    is_avc: bool | None
    nal_length_size: str | None
    id: str | None
    r_frame_rate: str | None
    avg_frame_rate: str | None
    time_base: str | None
    start_pts: int | None
    start_time: str | None
    duration_ts: int | None
    duration: float | None
    bit_rate: int | None
    bits_per_raw_sample: int | None
    nb_frames: int | None
    extradata_size: int | None
    disposition: Disposition | None
    tags: Tags | None
    sample_fmt: str | None
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    bits_per_sample: int | None
    initial_padding: int | None

class Tags1(BaseModel):
    major_brand: str | None
    minor_version: str | None
    compatible_brands: str | None
    encoder: str | None

class Format(BaseModel):
    filename: str | None
    nb_streams: int | None
    nb_programs: int | None
    format_name: str | None
    format_long_name: str | None
    start_time: float | None
    duration: float | None
    size: int | None
    bit_rate: int | None
    probe_score: int | None
    tags: Tags1 | None

class VideoInformation(BaseModel):
    streams: list[Stream]
    format: Format
