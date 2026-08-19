# Backup and Copy-Over Design

## Overview

This document covers post-conversion **backup** and **copy-over**: keeping the original safe, then putting the HEVC file in the library path. It records a failed run on an exFAT USB drive (historical) and defines the **target deployment** on a Mac Mini with an **8 TB APFS SSD**.

The **NAS is retired.** Walker and Converter both run on the Mac Mini in the **same Docker Compose project**, sharing one `/Media` mount and one MongoDB. There is no cross-host `path_map`.

Encoder: **`libx265` only** (Docker on the Mac Mini).

**Filesystem (confirmed):** the 8 TB SSD will be formatted as **APFS**. All design assumptions — hard links, stable inodes, same-volume operations, in-place rewrite, optional `clonefile` — depend on APFS.

---

## Target deployment (Mac Mini + 8 TB APFS SSD)

### Filesystem

The SSD is **APFS** (Apple File System). Fixed requirement, not a recommendation.

| Capability | Required for | APFS |
| --- | --- | --- |
| Hard links (same volume) | Instant backup of staging input | Yes |
| Stable `st_ino` | Walker rename vs delete detection | Yes |
| In-place file rewrite (`"r+b"`) | Plex-safe copy-over (same inode) | Yes |
| Same-volume `rename` / `replace` | Fallback commit only | Yes |
| `clonefile` (optional) | Fast library → staging copy | Yes (COW clone) |

Do **not** use exFAT, FAT32, or NTFS on this disk.

**APFS case sensitivity (confirmed):** **case-sensitive** APFS. Walker and converter paths in MongoDB and [src/config.toml](../src/config.toml) must match on-disk casing exactly.

### Services (Docker Compose)

Walker and Converter run as separate containers in one compose file on the Mac Mini. Both mount the same APFS tree; only `FOLDER_WALKER` differs.

```yaml
services:
  walker-1:
    build: walker
    environment:
      - FOLDER_WALKER=TRUE
      - DB_URL=mongodb://host.docker.internal:27017/   # or mongodb service name
    volumes:
      - ./src:/src:ro
      - /Volumes/<SSD>/Media:/Media:rw   # TODO: set volume name when SSD arrives

  backend-1:
    build: backend
    environment:
      - FOLDER_WALKER=FALSE
      - DB_URL=mongodb://host.docker.internal:27017/
    volumes:
      - ./src:/src:ro
      - /Volumes/<SSD>/Media:/Media:rw   # same mount as walker
```

- **No** `converter_volume` Docker volume.
- **No** NAS, SMB, or `path_map` — filenames in MongoDB are canonical `/Media/...` paths, identical inside both containers.
- MongoDB runs on the Mac Mini (native or container); walker writes metadata, converter claims work.

### Layout

| Host (APFS) | Container | Role |
| --- | --- | --- |
| `/Volumes/<SSD>/Media` | `/Media` | Library, backup, conversions — **one APFS volume** |

> **TODO:** Replace `<SSD>` with the actual volume name under `/Volumes/` once the drive is connected (expected when hardware arrives).

Everything under `/Media` in config:

```toml
[folders]
include = ["/Media/TV", "/Media/Films"]
exclude = ["/Media/Films/VR"]
backup = "/Media/Backup"
conversions = "/Media/Conversions"

[path_map]
from = "/Media"
to = "/Media"
```

Identity mapping — walker and converter both see `/Media` directly.

No separate `/Conversions` volume. Temp input, temp output, backup, and library files share **`st_dev`** on the same APFS volume.

### End-to-end flow

```mermaid
flowchart TD
    lib["Library file\n/Media/Films/.../movie.mkv"]
    stageIn["Staging input\n/Media/Conversions/movie.mkv"]
    stageOut["Staging output\n/Media/Conversions/movie.hevc.mkv"]
    backup["Backup\n/Media/Backup/movie.mkv"]
    encode[ffmpeg libx265]
    clone["clonefile or copy\nlibrary → staging"]
    hl["Hard link staging input → Backup"]
    commit["In-place r+b write staging output → library path"]
    done["Finalize inode, delete Conversions temps"]

    lib --> clone --> stageIn
    stageIn --> encode
    encode --> stageOut
    stageIn --> hl --> backup
    stageOut --> commit --> lib
    commit --> done
```

1. **Stage input** — APFS `clonefile` (or copy) library → `/Media/Conversions/...`.
2. **Encode** — read staging input, write staging output under `/Media/Conversions/`.
3. **Backup** — hard link **staging input** → `/Media/Backup/<name>`.
4. **Copy-over** — `"r+b"` write converted bytes into the **existing library path**, then `truncate` to converted size.
5. **Finalize** — `$set inode` in MongoDB (usually unchanged), delete `/Media/Conversions` temps.

With `libx265`, encode time dominates; SSD I/O is not the bottleneck.

---

## Will hard linking work instead of copying?

**Yes, for backup — not for copy-over.**

| Step | Hard link instead of copy? | Why |
| --- | --- | --- |
| Library → staging input | No | Need a separate path for ffmpeg. Use APFS **clone** or full copy. |
| Staging input → `/Media/Backup` | **Yes** | Same APFS volume. Instant; no duplicate bytes. |
| Staging output → library path | **No** | Different content. Commit rewrites the library file or replaces its directory entry. |

Requirements for backup hard link (all satisfied on this deployment):

- Staging input and backup under `/Media` (same APFS volume).
- Source is the **staging copy**, never the live library path.

**Never hard link Backup to the live library file.** Hard-linked names share one inode; an in-place rewrite of the library would overwrite Backup.

Current code tries hard link first, then copy. On this topology the hard link should **succeed**.

### Will `clonefile` cause the library → backup corruption issue?

**No — if the pipeline order is respected.**

The dangerous pattern is linking **Backup directly to the library file**:

```text
library.mkv  ←—— hard link ——→  Backup/library.mkv   ✗
(in-place r+b on library also changes Backup)
```

The intended pattern separates three independent file identities:

```text
library.mkv          (inode A — live Plex path)
    │
    │  clonefile or copy  (new inode B; COW on APFS)
    ▼
Conversions/movie.mkv  (inode B — staging input)
    │
    │  hard link  (same inode B)
    ▼
Backup/movie.mkv     (inode B — backup of original bytes)
```

| Mechanism | Shares inode with library? | Updated when library gets `"r+b"` HEVC? |
| --- | --- | --- |
| Hard link library → Backup | **Yes** | **Yes — corrupted backup** |
| `clonefile` library → staging, then hard link staging → Backup | **No** | **No — backup safe** |
| Full copy library → staging, then hard link staging → Backup | **No** | **No — backup safe** |

**APFS `clonefile`** creates a **copy-on-write clone**: a new file with its **own inode** and directory entry. It is not a hard link. Clones start by sharing data blocks, but **writes to the library do not change the clone** (APFS copies modified blocks on write). After clone → staging:

- Staging holds the pre-convert bytes at **inode B**.
- Hard link staging → Backup: Backup also points at **inode B**.
- Copy-over rewrites **inode A** (library path only).
- Staging and Backup still hold the original at **inode B** until you delete them.

So `clonefile` does **not** suffer the library-linked-backup problem. That problem applies only to hard links (or `replace` that swaps inodes) tied to the **live library path**.

**Do not** `clonefile` library → staging and also hard link library → Backup. Backup must link **staging only**.

After success, delete `/Media/Conversions` temps; `unlink` staging removes one name from inode B while Backup keeps the original bytes until you delete it manually.

### What about `Path.replace` for copy-over?

Same APFS volume, so `Path.replace` is allowed (`EXDEV`-free). Still **not** preferred:

- Changes the inode at the library path → Plex risk, MongoDB must `$set` new inode.
- **Prefer in-place `"r+b"`** — same inode at library path; Plex sees modify.

Use `replace` only if in-place write fails after backup exists.

---

## Plex and inode

Goals:

1. **Plex** — same library item after convert (watch history, match — not remove + re-add).
2. **Walker** — stable `inode` in MongoDB for rename vs delete ([codec_detector.py](../src/converter/codec_detector.py) `_update_changed_files`).

| Operation | Library path inode | Plex (typical) | MongoDB |
| --- | --- | --- | --- |
| In-place `"r+b"` + truncate | **Unchanged** | Modify on same path | `$set inode` (usually same value) |
| `Path.replace` onto library path | **Changes** | Risk delete + add | **Must** `$set` new inode |
| Unlink library + rename partial | **Changes** | Delete + add | Avoid as default |

**Production commit:** hard link backup (staging → Backup), then in-place `"r+b"` into library path.

Plex on the Mac Mini reads APFS via `/Volumes/<SSD>/Media/...`. FSEvents on in-place rewrite reports an update to an existing file.

### Code still required

The exFAT incident showed **`open("wb")`** truncates the library file to **0 bytes** before writing. Fix regardless of APFS:

1. Open library path **`"r+b"`** (no truncate-on-open).
2. Write converted bytes; `flush` + `fsync`; `truncate(converted_size)`.
3. On failure: Backup intact; library never intentionally 0 bytes.
4. **`_finalize_overwrite_success`** — always `stat` and `$set inode` by `filename`.
5. Best-effort `copystat` after full copies.
6. Copy failure: **return**, keep staging files; no `sys.exit` per file.

---

## Historical incident (exFAT USB — superseded)

First conversion on a WD My Book (exFAT) failed after ffmpeg: backup copy succeeded; library file ended up **0 bytes** because copy-over used `"wb"`. Caused by cross-device staging (`converter_volume` vs USB) and exFAT/bind-mount limits. Retired with the NAS and exFAT USB.

---

## Decisions (confirmed)

| Topic | Decision |
| --- | --- |
| Filesystem | **APFS** on 8 TB SSD |
| APFS variant | **Case-sensitive** |
| NAS | **Retired** — walker + converter on Mac Mini only |
| Docker layout | **One compose project**, shared `/Media` mount, no `path_map` |
| APFS volume name | **TODO** — set `/Volumes/<name>/Media` in compose when SSD is connected |
| Backup retention | **Manual deletion** — no automatic prune; user removes `/Media/Backup` files when satisfied |
| Encoder | **`libx265` only** |

---

## Recommended plan

### Infrastructure (Mac Mini)

1. **APFS SSD (confirmed):** case-sensitive APFS; media root at `/Volumes/<SSD>/Media` (volume name TBD).
2. Library tree: `TV`, `Films`, `Backup`, `Conversions`, …
3. **Docker Compose:** `walker-1` + `backend-1`, both `- /Volumes/<SSD>/Media:/Media:rw`; remove `converter_volume`.
4. MongoDB on Mac Mini; both services use same `DB_URL`.
5. Config: `conversions = "/Media/Conversions"`; `path_map` identity `/Media` → `/Media`.

### Code

| Step | Change |
| --- | --- |
| 1 | Copy-over: `"r+b"` + truncate, not `"wb"`. |
| 2 | Best-effort `copystat` after verified copies. |
| 3 | Copy failure: `return`, keep staging files; no `sys.exit` per file. |
| 4 | Hard link backup should succeed on all-`/Media` APFS layout. |
| 5 | Optional: APFS `clonefile` for library → staging (safe with staging → Backup hard link only). |
| 6 | Keep `$set inode` after every successful commit. |

### Suggested order

1. Land code fixes (`"r+b"`, copystat, control flow).
2. Connect SSD, format case-sensitive APFS, update compose volume path (TODO).
3. Deploy walker + converter compose on Mac Mini.
4. Test convert: backup hard link, library inode unchanged, Plex item unchanged.
5. Delete backups manually when verified.

---

## Capacity and I/O (8 TB APFS SSD)

Peak space per title during convert:

- Staging input + staging output + hardlinked backup ≈ **original + converted** bytes (backup shares inode with staging input, not a third full copy).
- After commit and temp cleanup: library holds converted file; Backup holds original until **manual** deletion.

Sequential SSD I/O is far faster than `libx265`. Colocating `/Media/Conversions` on the SSD is appropriate.

---

## What not to change

- Backup **before** overwriting the library path.
- Hard link **staging input** → Backup, never library → Backup.
- `clonefile` library → staging is fine; do not also link Backup to library.
- `_finalize_overwrite_success` updating `inode` by `filename`.
- Prefer inode-preserving `"r+b"` over `replace` for Plex.

---

## Test plan (Mac Mini APFS)

1. **Walker + converter:** both containers see same `/Media` paths in MongoDB; no `path_map` translation.
2. **Hard link backup:** `/Media/Backup/foo.mkv` same inode as `/Media/Conversions/foo.mkv`.
3. **Clone isolation:** after `"r+b"` commit on library, Backup bytes still match pre-convert original.
4. **Inode stable:** library `st_ino` unchanged with `"r+b"` commit; MongoDB matches.
5. **Plex:** same item after scan; no remove/re-add.
6. **Walker rename:** rename on disk; walk updates `filename`, not `deleted`.
7. **Failure:** write error during `"r+b"`; library not 0 bytes; Backup intact.
8. **Same APFS volume:** library, Conversions, Backup — same `st_dev`.

---

## Remaining TODO

- **`/Volumes/<SSD>` name** — update [docker-compose.yaml](../docker-compose.yaml) bind mount once the 8 TB SSD is connected and the volume name is known.
