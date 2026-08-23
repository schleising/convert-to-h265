# Conversion progress: frame-based percentage

## Status

**Implemented and verified in production** (Phases 1 and 2). Encode progress no longer jumps backward mid-encode when re-encoding AAC with `aresample=async=1`.

| Area | Location |
| --- | --- |
| Frame estimate helpers | [src/converter/ffprobe_utils.py](../src/converter/ffprobe_utils.py) |
| Encode progress callback | [src/converter/converter.py](../src/converter/converter.py) (`_prepare_encode_progress`, `_encode_percentage_from_progress`) |
| Unit tests | [tests/test_ffprobe_utils.py](../tests/test_ffprobe_utils.py) |
| Ops note | [README.md](../README.md) (Conversion progress) |

---

## Overview

Encode progress is shown in MongoDB as `percentage_complete`. It previously used **ffmpeg output time** divided by **ffprobe container duration**, which produced misleading jumps (e.g. 99% → 75%) while encoding was still running—especially after switching from `c:a copy` to AAC + `aresample=async=1`.

**Solution:** during the **ffmpeg encode phase only**, compute progress from the **video frame counter** in python-ffmpeg’s `Progress.frame` and an estimated **total output frame count** for the mapped video stream. Post-encode copy/backup/commit progress stays **byte-based** (unchanged).

---

## Previous behaviour (time-based)

```python
duration = timedelta(seconds=self._file_data.video_information.format.duration)
percentage_complete = (ffmpeg_progress.time / duration) * 100
```

| Input | Source |
| --- | --- |
| Denominator | `video_information.format.duration` (container, from ffprobe at walk time) |
| Numerator | `ffmpeg_progress.time` (muxer `out_time` from stderr stats) |

### Why time-based progress misbehaved

1. **`out_time` is not monotonic** — the muxer can report timestamps that move backward when A/V is reconciled (common with AAC re-encode + `aresample=async=1`).
2. **Denominator is container duration** — not necessarily the duration of the **video stream being encoded**; audio/filter work can skew the ratio.
3. **No clamp** — `_update_percentage_complete` wrote whatever ratio was computed (bounded 0–100 only at write time).

Copy-phase progress (`_copy_file_with_progress`) is separate and byte-based; it was not the cause of mid-encode regressions.

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

When stderr lacks `frame=` (some audio-only stat lines), `Statistics.from_line` may not emit a progress event, or `frame` defaults to `0`. Frame-based logic **ignores zero-frame updates** and never treats them as 0% encode progress.

---

## Implemented design

### Encode phase formula

```text
percentage = min(100, max(last_percentage, (progress.frame / total_frames) * 100))
```

- **`progress.frame`** — from `@self._ffmpeg.on("progress")` callback.
- **`total_frames`** — estimated once per conversion before `execute()` (see below).
- **`last_percentage`** — `Converter._encode_last_percentage`, reset to `0` when encode starts; ensures **monotonic** display.

On successful `execute()`, progress is forced to **100%** before the copy/backup phase.

### Estimating `total_frames`

Uses the same video stream mapped for encode: `0:{first_video_stream}` ([converter.py](../src/converter/converter.py)). Logic lives in [ffprobe_utils.py](../src/converter/ffprobe_utils.py) (`estimate_total_video_frames`).

| Priority | Source | Notes |
| --- | --- | --- |
| 1 | `stream.nb_frames` from ffprobe | Authoritative when present (often missing on MKV) |
| 2 | `duration × fps` | Stream `duration` or `format.duration`; `avg_frame_rate` then `r_frame_rate` |
| 3 | Time fallback | If no reliable frame estimate, `time / format.duration` **with monotonic clamp** |

Each job logs once at INFO, e.g.:

```text
Encode progress: 123456 frames from duration_x_fps (approximate for VFR)
```

or:

```text
Encode progress: no frame estimate; using time-based fallback (±1–2% possible for VFR)
```

### Progress callback

```python
@self._ffmpeg.on("progress")
def _on_progress(ffmpeg_progress: FFmpegProgress) -> None:
    percentage_complete = self._encode_percentage_from_progress(ffmpeg_progress)
    if percentage_complete is None:
        return  # e.g. frame=0 while frame-based

    self._update_percentage_complete(
        percentage_complete,
        speed=ffmpeg_progress.speed,
    )
```

`_prepare_encode_progress()` resets state and estimates frames immediately before `execute()`.

### Copy / backup / commit phase

**Unchanged.** Still uses `_copy_file_with_progress` with `base_bytes` / `total_post_copy_bytes`. After a successful encode that reduced file size, `percentage_complete` still resets to `0` when entering the copy phase (intentional).

---

## Comparison

| Aspect | Time-based (old) | Frame-based (current) |
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
| **`nb_frames` missing** (typical MKV) | Estimate `duration × fps`; log source at INFO |
| **Variable frame rate** | `avg_frame_rate` usually good enough; exact count may be ±1–2% |
| **Multiple video streams** | Only frames for `first_video_stream` (encode target) |
| **Progress line without `frame=`** | Skip update if `frame == 0` and frame-based mode active |
| **`frame` exceeds estimate** | Cap at 100% |
| **Short clips / bad probe** | Fall back to time + monotonic clamp |
| **ffmpeg never reaches 100% frames** | On successful `execute()`, force `percentage_complete = 100` before copy |

---

## Implementation checklist

### Phase 1 — Core

- [x] `parse_ffprobe_rate` (handles `"24000/1001"`)
- [x] `estimate_total_video_frames` in [ffprobe_utils.py](../src/converter/ffprobe_utils.py)
- [x] `_encode_total_frames` / `_encode_last_percentage` on `Converter`
- [x] Frame-first `_on_progress` + monotonic clamp + time fallback
- [x] Reset encode progress state before `execute()`

### Phase 2 — Polish

- [x] Log `total_frames` source at INFO once per job
- [x] Unit tests in [tests/test_ffprobe_utils.py](../tests/test_ffprobe_utils.py)
- [x] README note on VFR ±1–2%

### Verification

- [x] Production encode with AAC re-encode: progress monotonic; no 99% → 75% regression
- [x] Unit tests pass (`python -m unittest tests.test_ffprobe_utils`)

---

## Summary

| Item | Decision |
| --- | --- |
| **Encode progress** | `Progress.frame / estimated_total_frames`, monotonic clamp |
| **Total frames** | `nb_frames` → `duration × fps` → time fallback |
| **Copy progress** | Unchanged (bytes) |
| **Outcome** | Mid-encode percentage regressions after AAC re-encode are fixed |
