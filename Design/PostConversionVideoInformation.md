# Post-conversion VideoInformation

## Status

**Implemented** (Phases 1–3). New conversions store post-probe metadata automatically; use the backfill script for existing rows.

| Area | Location |
| --- | --- |
| Schema | [src/converter/models.py](../src/converter/models.py) (`converted_video_information`, `effective_video_information()`) |
| Shared ffprobe | [src/converter/ffprobe_probe.py](../src/converter/ffprobe_probe.py) |
| Converter hook | [src/converter/converter.py](../src/converter/converter.py) (`_build_converted_probe_update`, `_finalize_overwrite_success`) |
| Backfill script | [src/backfill_converted_video_information.py](../src/backfill_converted_video_information.py) |
| Unit tests | [tests/test_ffprobe_probe.py](../tests/test_ffprobe_probe.py), [tests/test_backfill_converted_video_information.py](../tests/test_backfill_converted_video_information.py) |
| Ops note | [README.md](../README.md) (Post-conversion metadata) |

---

## Overview

Each document in `media_collection` stores a full ffprobe snapshot as `video_information` when the **walker** first discovers the file ([codec_detector.py](../src/converter/codec_detector.py)). That snapshot describes the **source** file (typically H.264 + DTS/AC3) and is never refreshed after a successful HEVC conversion.

**Goal:** after the converted file is committed to the library path, store a second ffprobe snapshot — **`converted_video_information`** — describing the **on-disk library file** (HEVC + AAC, new bitrates, stream layout).

This enables:

- Comparing pre/post codec, bitrate, and stream counts without re-probing
- Future features (quality reports, re-convert decisions, fingerprint backfill) that need **current** file metadata
- Correct analytics on already-converted rows (today `video_information` still shows the old H.264 probe)

---

## Current behaviour

| When | What is probed | Stored in MongoDB |
| --- | --- | --- |
| Walker scan (new/changed file) | Library path via ffprobe | `video_information`, stream counts, `pre_conversion_size`, `current_size` |
| Converter claims job | Reads existing `video_information` from DB | Used for encode progress, queue sort (`format.bit_rate`), CRF profile |
| Converter finishes successfully | **Nothing re-probed** | `converted=True`, `current_size` updated; **`video_information` unchanged** |

Relevant completion path:

```text
ffmpeg success → backup → commit to library → _complete_successful_conversion
                                              → _finalize_overwrite_success
```

Neither step runs ffprobe on the committed library file today.

---

## Proposed schema

Add to [FileData](../src/converter/models.py):

```python
converted_video_information: VideoInformation | None = None
```

| Field | Meaning |
| --- | --- |
| `video_information` | **Pre-conversion** (walker probe at ingest). **Keep name** — no migration rename. |
| `converted_video_information` | **Post-conversion** (library file after successful commit). `None` until converted. |

### Optional companion fields (recommended)

When writing `converted_video_information`, also refresh derived counters from the **converted** probe so list views stay accurate:

| Field | Update from converted probe? |
| --- | --- |
| `video_streams`, `audio_streams`, `subtitle_streams` | Yes |
| `first_video_stream`, `first_audio_stream`, `first_subtitle_stream` | Yes |
| `current_size` | Already set from stat; verify matches `format.size` |
| `video_information` | **No** — preserve original for history |
| `pre_conversion_size` | **No** |
| `conversion_required` | **No** (stays as-was; row is `converted=True`) |

### Documents without the new field

| Row state | `converted_video_information` |
| --- | --- |
| Not yet converted (`converted=False`) | `null` / absent |
| Converted before this feature | absent — backfill script |
| Converted after this feature | populated at end of conversion |

Pydantic / MongoDB: omitting the key and `null` are both fine; readers use `doc.get("converted_video_information")`.

---

## Converter integration

### When to probe

**After** the library file on disk is the converted output — i.e. after `_commit_converted_to_library` succeeds, inside `_complete_successful_conversion` (before or as part of `_finalize_overwrite_success`).

Do **not** probe:

- Staging temp in `/Media/Conversions` (may be deleted immediately after)
- Before commit (library still has old bytes)
- On conversion failure or “file size not reduced” early exit

### Shared ffprobe helper

Extract probe logic from [codec_detector.py](../src/converter/codec_detector.py) into a reusable module, e.g. [src/converter/ffprobe_probe.py](../src/converter/ffprobe_probe.py):

```python
def probe_video_information(path: Path) -> VideoInformation:
    """Run ffprobe -show_format -show_streams, parse JSON, return VideoInformation."""
```

Also expose stream-index helpers (mirror walker logic for `first_*_stream` and stream counts) so converter and backfill script share one implementation.

### Converter flow (target)

```text
_commit_converted_to_library OK
    → probe_video_information(input_file_path)   # resolved library path
    → build stream summary from VideoInformation
    → _finalize_overwrite_success(..., converted_probe=...)
         $set converted_video_information, video_streams, audio_streams, ...
    → notification, delete temps
```

Probe failure should **not** fail the conversion (file is already committed). Log error, leave `converted_video_information` unset; backfill script can repair later.

### Recovery path

`_recover_interrupted_overwrite` → successful commit should use the same probe + `$set` path as a normal completion.

---

## Backfill script (one-off, host)

A standalone script for existing `converted=True` rows missing `converted_video_information`.

**Path:** [src/backfill_converted_video_information.py](../src/backfill_converted_video_information.py)

**Runs on:** macOS host (outside Docker), same pattern as historical `update_inodes.py`:

- DB paths: `/Media/TV/...`
- Local disk: `/Volumes/X10/Media/TV/...` (configurable)

### Dependencies

- `pymongo` (already in project)
- **`tqdm`** for progress bar (optional; fall back to periodic log lines if not installed)
- Host **`ffprobe`** on `PATH` (not inside container)

No MongoDB or media mount required inside a container.

### Selection query

```python
{
    "deleted": {"$ne": True},
    "converted": True,
    "$or": [
        {"converted_video_information": {"$exists": False}},
        {"converted_video_information": None},
    ],
}
```

Optional flags:

| Flag | Effect |
| --- | --- |
| `--dry-run` | List/count only; no ffprobe writes |
| `--force` | Re-probe even if field already set |
| `--limit N` | Process at most N files (testing) |
| `--reset-checkpoint` | Ignore/delete checkpoint and start fresh |

Environment (same as other scripts):

```bash
export DB_URL=mongodb://macmini2.home.arpa:27017
export DB_NAME=media
export DB_COLLECTION=media_collection
export LOCAL_MEDIA_ROOT=/Volumes/X10/Media   # host path for /Media/...
```

### Progress bar

Use **`tqdm`** over the work queue:

```text
Probing converted files:  42%|████████▌              | 4412/10500 [1:23:45<1:52:10, 1.10file/s]
  ok: 4398  skip: 0  missing: 12  probe_error: 2
```

- **Total** = documents matching query minus checkpoint skips at start
- **Postfix** = running counts (ok / missing on disk / ffprobe errors)
- Update bar on each completed file (success or logged failure)

If `tqdm` is not installed, print every N files (e.g. 100) with the same stats — document in script `--help`.

### Graceful stop and restart

Use a **checkpoint file** on disk (default):

```text
~/.cache/convert-to-h265/backfill_converted_video_information.json
```

Override with `--checkpoint /path/to/file.json`.

#### Checkpoint contents

```json
{
  "version": 1,
  "started_at": "2026-08-30T16:00:00+00:00",
  "updated_at": "2026-08-30T16:45:12+00:00",
  "completed": {
    "/Media/Films/Foo.mkv": "ok",
    "/Media/TV/Show/S01E01.mkv": "missing",
    "/Media/TV/Show/S01E02.mkv": "probe_error"
  }
}
```

| Status | Meaning |
| --- | --- |
| `ok` | ffprobe succeeded and MongoDB `$set` completed |
| `missing` | File not on disk at mapped path — skip on restart |
| `probe_error` | ffprobe failed — skip on restart unless `--retry-errors` |

#### Signal handling

1. Register `SIGINT` / `SIGTERM` handlers at startup.
2. On signal: set `_shutdown_requested = True`.
3. **Do not** interrupt mid-ffprobe if possible; finish current file, write checkpoint, exit with code **130**.
4. Checkpoint write: **atomic** (`write temp → fsync → rename`) after each file (or every K files with fsync on shutdown — **prefer after each file** for safest resume).

#### Restart behaviour

1. Load checkpoint if present (unless `--reset-checkpoint`).
2. Build work list from MongoDB query.
3. Remove filenames already in `completed` with status `ok` (and `missing` unless `--retry-missing`).
4. Continue tqdm from remaining count.
5. On full completion: log summary; optionally `--archive-checkpoint` to `*.json.done` or delete checkpoint.

#### Idempotency

- Normal run: skip rows that already have `converted_video_information` in MongoDB (unless `--force`).
- Checkpoint + DB can disagree after manual DB edit: **`--force`** re-probes; checkpoint entry overwritten on success.

### Per-file algorithm

```text
for each filename in work_queue:
    if shutdown_requested: break

    local_path = map /Media → LOCAL_MEDIA_ROOT
    if not local_path.is_file():
        mark checkpoint missing; continue

    try:
        info = probe_video_information(local_path)
        stream_summary = summarize_streams(info)
    except Exception:
        mark checkpoint probe_error; continue

    if not dry_run:
        collection.update_one(
            {"filename": filename},
            {"$set": {
                "converted_video_information": info.model_dump(),
                **stream_summary,
            }},
        )

    mark checkpoint ok
    tqdm.update(1)
```

### Estimated runtime

~10k converted files × ~0.5–2 s ffprobe each → **~1.5–6 hours**. Safe to run overnight; restartable if interrupted.

Example:

```bash
python3 src/backfill_converted_video_information.py \
  --checkpoint ~/.cache/convert-to-h265/backfill.json

# Ctrl+C → checkpoint saved; rerun same command to resume
```

---

## Consumers and compatibility

### Code that must keep using pre-conversion probe

| Use | Field |
| --- | --- |
| Encode progress denominator (walker-era file) | `video_information` during **active** convert of that file |
| Queue sort by source bitrate | `video_information.format.bit_rate` for **pending** jobs |
| `pre_conversion_size` / reduction % | unchanged |

### Code that should use post-conversion probe (after implementation)

| Use | Field |
| --- | --- |
| “What codec is in the library now?” | `converted_video_information` if `converted` else `video_information` |
| Reports on converted library | `converted_video_information` |

Add a small helper:

```python
def effective_video_information(file_data: FileData) -> VideoInformation:
    if file_data.converted and file_data.converted_video_information is not None:
        return file_data.converted_video_information
    return file_data.video_information
```

No change required for walker ingest on first scan.

---

## Implementation plan

### Phase 1 — Schema and shared probe

- [x] Add `converted_video_information` to `FileData`
- [x] Add `ffprobe_probe.py` (extract from `codec_detector`)
- [x] Refactor `codec_detector` to call shared probe
- [x] Unit tests: parse sample ffprobe JSON; stream summary helper

### Phase 2 — Converter

- [x] Probe library path in `_complete_successful_conversion` / `_finalize_overwrite_success`
- [x] `$set` converted fields; log on probe failure without failing job
- [x] Same for overwrite recovery success path (via `_finalize_overwrite_success`)
- [ ] Manual test: one conversion; verify MongoDB has both probes

### Phase 3 — Backfill script

- [x] Implement `backfill_converted_video_information.py`
- [x] Checkpoint + signal handling + tqdm (optional)
- [x] `--dry-run`, `--force`, `--reset-checkpoint`, `LOCAL_MEDIA_ROOT`
- [ ] Run on Mac Mini against full converted set

### Phase 4 — Docs

- [x] README note (host backfill command)
- [x] Mark this design **Implemented** when Phases 1–3 ship

---

## Testing

| Test | How |
| --- | --- |
| Converter writes post-probe | Convert one file; inspect MongoDB for `converted_video_information.streams[video].codec_name == hevc` |
| Pre-probe preserved | Same document: `video_information` still shows original codec |
| Probe failure | Mock ffprobe error; conversion still `converted=True`, field absent |
| Backfill resume | Run script on 100 files, interrupt, restart; no duplicate work |
| Backfill missing file | Row `converted=True` but file deleted; checkpoint `missing` |
| Path map | Host script resolves Unicode paths via existing [unicode_paths.py](../src/converter/unicode_paths.py) |

---

## Summary

| Item | Decision |
| --- | --- |
| **New field** | `converted_video_information: VideoInformation \| None` |
| **Pre-conversion field** | Keep `video_information` unchanged |
| **When set (converter)** | After successful library commit |
| **When set (backfill)** | One-off host script for existing `converted=True` rows |
| **Backfill UX** | `tqdm` progress bar, checkpoint file, SIGINT-safe resume |
| **Probe failure** | Non-fatal in converter; retriable via backfill |
