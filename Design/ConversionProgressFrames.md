# Conversion progress: frame-based percentage

## Overview

Encode progress is shown in MongoDB as `percentage_complete`. Today it is derived from **ffmpeg output time** divided by **ffprobe container duration**. That produces misleading jumps (e.g. 99% → 75%) while encoding is still running—especially after switching from `c:a copy` to AAC + `aresample=async=1`.

**Proposed change:** during the **ffmpeg encode phase only**, compute progress from the **video frame counter** in python-ffmpeg’s `Progress.frame` and an estimated **total output frame count** for the mapped video stream. Post-encode copy/backup/commit progress stays **byte-based** (unchanged).

---

## Current behaviour

```1341:1353:src/converter/converter.py
            @self._ffmpeg.on("progress")
            def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
                if self._file_data is not None:
                    duration = timedelta(
                        seconds=self._file_data.video_information.format.duration
                    )
                    percentage_complete = (ffmpeg_progress.time / duration) * 100

                    self._update_percentage_complete(
                        percentage_complete,
                        speed=ffmpeg_progress.speed,
                    )
```

| Input | Source |
| --- | --- |
| Denominator | `video_information.format.duration` (container, from ffprobe at walk time) |
| Numerator | `ffmpeg_progress.time` (muxer `out_time` from stderr stats) |

### Why time-based progress misbehaves

1. **`out_time` is not monotonic** — the muxer can report timestamps that move backward when A/V is reconciled (common with AAC re-encode + `aresample=async=1`).
2. **Denominator is container duration** — not necessarily the duration of the **video stream being encoded**; audio/filter work can skew the ratio.
3. **No clamp** — `_update_percentage_complete` writes whatever ratio is computed (bounded 0–100 only at write time).

Copy-phase progress (`_copy_file_with_progress`) is separate and byte-based; it is not the cause of mid-encode regressions.

---

## python-ffmpeg progress data

From [python-ffmpeg `Progress`](https://github.com/jonghwanhyeon/python-ffmpeg) / `Statistics.from_line`:

| Field | Meaning |
| --- | --- |
| `frame` | Number of **encoded output video frames** (present when stderr line includes `frame=`) |
| `time` | Current muxer output time |
| `fps`, `speed`, `size`, `bitrate` | Throughput / size (unchanged for UI) |

FFmpeg stderr (video encode) looks like:

```text
frame= 1234 fps= 45 q=28.0 size= ... time=00:00:51.00 bitrate= ... speed=1.2x
```

When stderr lacks `frame=` (some audio-only stat lines), `Statistics.from_line` may not emit a progress event, or `frame` defaults to `0`. Frame-based logic must **ignore zero-frame updates** and never treat them as 0% encode progress.

---

## Proposed design

### Encode phase formula

```text
percentage = min(100, max(last_percentage, (progress.frame / total_frames) * 100))
```

- **`progress.frame`** — from `@self._ffmpeg.on("progress")` callback.
- **`total_frames`** — estimated once per conversion before `execute()` (see below).
- **`last_percentage`** — instance variable on `Converter`, reset to `0` when encode starts; ensures **monotonic** display even if ffmpeg briefly reports a lower frame count (should be rare for `frame=`).

### Estimating `total_frames`

Use the **same video stream** already mapped for encode: `0:{first_video_stream}` ([converter.py](../src/converter/converter.py) mapping).

Priority order:

| Priority | Source | Notes |
| --- | --- | --- |
| 1 | `stream.nb_frames` from ffprobe | Authoritative when present (often missing on MKV) |
| 2 | `duration × fps` | `duration` = stream `duration` or fall back to `format.duration`; `fps` from stream |
| 3 | Time fallback (current) | If no reliable frame estimate, keep `time / format.duration` **with monotonic clamp** |

**FPS selection** (first match):

1. Parse `avg_frame_rate` (e.g. `"24000/1001"` → ~23.976)
2. Else parse `r_frame_rate`
3. Else `25.0` default (log warning)

**Duration selection** (first match):

1. Video stream `duration` (seconds)
2. Container `format.duration`

```python
def _estimate_total_video_frames(self) -> int | None:
    stream = self._get_mapped_video_stream()
    if stream is None:
        return None

    if stream.nb_frames is not None and stream.nb_frames > 0:
        return stream.nb_frames

    fps = _parse_ffprobe_rate(stream.avg_frame_rate) or _parse_ffprobe_rate(stream.r_frame_rate)
    duration = stream.duration or self._file_data.video_information.format.duration
    if fps and duration and duration > 0:
        return max(1, round(duration * fps))

    return None
```

Store result on the converter for the encode callback: `self._encode_total_frames`.

### Progress callback (target)

```python
@self._ffmpeg.on("progress")
def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
    if self._file_data is None:
        return

    if self._encode_total_frames and ffmpeg_progress.frame > 0:
        raw = (ffmpeg_progress.frame / self._encode_total_frames) * 100
    else:
        # Fallback: time-based with monotonic clamp
        duration = timedelta(seconds=self._file_data.video_information.format.duration)
        raw = (ffmpeg_progress.time / duration) * 100

    percentage = min(100.0, max(self._encode_last_percentage, raw))
    self._encode_last_percentage = percentage

    self._update_percentage_complete(percentage, speed=ffmpeg_progress.speed)
```

Reset `_encode_last_percentage = 0` and compute `_encode_total_frames` immediately before `self._ffmpeg.execute()`.

### Copy / backup / commit phase

**No change.** Continue using `_copy_file_with_progress` with `base_bytes` / `total_post_copy_bytes`. Optionally reset `_encode_last_percentage` when entering copy phase so the 0% reset at line 1416 remains intentional.

---

## Comparison

| Aspect | Time-based (today) | Frame-based (proposed) |
| --- | --- | --- |
| Tracks video encode | Indirectly via mux time | Directly via encoded frame count |
| AAC + async resample | Sensitive to timestamp drift | Largely unaffected |
| Monotonic | No | Yes (explicit clamp) |
| Denominator accuracy | Container duration | Stream frames or duration×fps |
| VFR / missing `nb_frames` | Same issues | Estimate via fps×duration; time fallback |

---

## Edge cases

| Case | Handling |
| --- | --- |
| **`nb_frames` missing** (typical MKV) | Estimate `duration × fps`; log at debug |
| **Variable frame rate** | `avg_frame_rate` usually good enough for progress bar; exact count may be ± few % |
| **Multiple video streams** | Only count frames for `first_video_stream` (already the encode target) |
| **Progress line without `frame=`** | Skip update if `frame == 0` and frame-based mode active |
| **`frame` exceeds estimate** | Cap at 100% |
| **Short clips / bad probe** | Fall back to time + monotonic clamp |
| **ffmpeg never reaches 100% frames** | On successful `execute()`, force `percentage_complete = 100` before copy phase (or accept 99.x until copy reset) |

---

## Implementation plan

### Phase 1 — Core (recommended)

1. Add `_parse_ffprobe_rate(rate: str | None) -> float | None` helper (handle `"24000/1001"`).
2. Add `_estimate_total_video_frames() -> int | None` on `Converter`.
3. Add `_encode_total_frames: int | None` and `_encode_last_percentage: float` on `Converter`.
4. Replace `_on_progress` body with frame-first logic + monotonic clamp + time fallback.
5. Reset encode progress state when starting ffmpeg (alongside `_last_progress_update_time = None`).

### Phase 2 — Polish (optional)

- Log chosen `total_frames` source (`nb_frames` vs estimated) at INFO once per job.
- Unit tests for `_parse_ffprobe_rate` and `_estimate_total_video_frames` with fixture ffprobe JSON.
- Document in README / ops notes that progress is approximate (±1–2%) for VFR.

### Files to touch

| File | Change |
| --- | --- |
| [src/converter/converter.py](../src/converter/converter.py) | Helpers + `_on_progress` |
| (optional) [src/converter/ffprobe_utils.py](../src/converter/ffprobe_utils.py) | Rate/frame parsing if we want to keep converter slim |

No config.toml changes required.

---

## Testing

1. **Known CFR file** (23.976 fps TV episode) — progress increases smoothly, no backward jumps through encode.
2. **Film with AAC re-encode** — reproduce prior 99%→75% case; bar should stay monotonic.
3. **MKV without `nb_frames`** — verify estimate logged; progress still moves.
4. **Very short clip** (< 1 s) — does not stick at 0% or divide-by-zero.
5. **Full pipeline** — encode → backup → commit; copy phase still 0% reset then byte progress to 100%.

Compare ffmpeg log `frame=` values manually for one file:

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames,avg_frame_rate,duration -of json input.mkv
```

---

## Summary

| Item | Decision |
| --- | --- |
| **Encode progress** | `Progress.frame / estimated_total_frames`, monotonic clamp |
| **Total frames** | `nb_frames` → `duration × fps` → time fallback |
| **Copy progress** | Unchanged (bytes) |
| **Fixes** | Mid-encode percentage regressions after AAC re-encode |
