# File Identity and Rename Detection

## Overview

The walker must tell **renames** from **deletes** and update `filename` in MongoDB without dropping conversion history. Today that relies on filesystem **inode numbers** (`st_ino`), which has proven fragile on the Mac Mini Docker deployment.

**Chosen solution:** identify files by **`file_size` + partial content hash** (`content_fingerprint`), stored in MongoDB at ingest. Rename detection matches on fingerprint, not inode. Inodes become optional legacy metadata; **xattr-based IDs are explicitly rejected** (copy tools and permissions often strip them).

This document records why inode identity failed, what was learned from testing, the chosen fingerprint design, interim workarounds, and implementation plan.

---

## Decision

| Topic | Choice |
| --- | --- |
| **Source of truth for “same file”** | `content_fingerprint` (size + partial SHA-256) |
| **Rename detection** | Path → Unicode path → fingerprint match → delete |
| **Inode** | Legacy field; refresh on match; **not** used for rename logic once implemented |
| **xattr UUID** | **Not used** — unreliable across copy/rsync/tools |
| **Interim (until fingerprint ships)** | **Startup inode resync** on every walker start (~1s); [update_inodes.py](../src/update_inodes.py) CLI for manual runs |

---

## What we are trying to achieve

| Goal | Required? |
| --- | --- |
| Detect when a library file was **renamed** and update `filename` in MongoDB | **Yes** |
| Avoid marking renamed files as `deleted: true` | **Yes** |
| Survive drive move, container rebuild, host vs container stat differences | **Yes** |
| Avoid writing metadata onto media files (xattr) | **Yes** |
| Store APFS or Docker inode numbers for their own sake | **No** |

---

## How rename detection works today (to be replaced)

During each walk, [codec_detector.py](../src/converter/codec_detector.py) calls `_update_changed_files()` **before** scanning for new files.

```text
For each non-deleted DB row:
  1. Exact path on disk?           → nothing to do
  2. Unicode-equivalent path?      → update filename (NFC/NFD fix)
  3. DB inode still on disk?       → treat as rename; update filename
  4. Otherwise                     → mark deleted
```

Step 3 uses `drive_by_inode` built from `file.stat().st_ino` in [folder_walker.py](../src/converter/folder_walker.py). MongoDB updates use `{"inode": inode}` in `_set_filename_in_db`.

**Problems with this approach:**

- Host `st_ino` ≠ container `st_ino` on Mac Docker bind mounts (confirmed by testing — see below).
- Volume migration changes all inodes; requires bulk [update_inodes.py](../src/update_inodes.py).
- Unique index on `inode` forces synthetic negative placeholders and careful multi-phase writes during resync.
- Duplicate inode crashes when DB and walk disagree.

---

## Empirical findings (Mac Mini + Docker)

Tests on *It's Always Sunny in Philadelphia* S18E01/E02 ([inodes.txt](../inodes.txt)):

| Environment | S18E01 | S18E02 |
| --- | --- | --- |
| Walker / converter (same mount) | 363 | 12817 |
| After container rebuild | 363 | 12817 (unchanged) |
| macOS host (`ls -i`) | 5991 | 13926 |

**Conclusions:**

1. Walker and converter **share one inode namespace** inside Docker — consistent and stable across rebuilds.
2. Host APFS inodes are a **different numbering scheme**, not “the same values, different view.”
3. **Never** run `update_inodes.py` on the host for production DB updates while walker runs in Docker.
4. Container inode stability across rebuilds is **observed but not guaranteed** (Docker file-sharing changes could alter behaviour). Fingerprint identity does not depend on this.

---

## Chosen solution: size + partial content hash

### Fingerprint definition

```text
content_fingerprint = SHA-256(
    first 1 MiB of file
    || file_size as little-endian uint64
    || last 1 MiB of file
)
```

For files smaller than 2 MiB, hash the entire file (still include `file_size` in the digest input).

| Property | Rationale |
| --- | --- |
| **Size in digest** | Binds fingerprint to exact byte length; cheap pre-filter before reading |
| **First + last 1 MiB** | Fast on multi-GB MKVs; extremely low collision rate for typical TV/movie libraries |
| **SHA-256** | Standard, available in Python `hashlib` without extra deps |
| **Read-only** | No xattr writes; works through bind mounts; survives copy/rsync if content unchanged |

Store as hex string on the MongoDB document, e.g. `content_fingerprint: "a1b2c3..."`.

### When to compute

| Event | Action |
| --- | --- |
| **New file** (first ffprobe during walk) | Compute fingerprint once; store with `FileData` |
| **Rename match** | Compare stored fingerprint to on-disk fingerprint of unmatched walk paths |
| **Successful conversion** | Recompute fingerprint (content changed); update field with post-convert file |
| **Normal walk** (path unchanged) | Reuse stored fingerprint; recompute only if `current_size` / `pre_conversion_size` no longer matches stat size |

Hash **only** paths that participate in rename matching (missing DB paths + unmatched walk paths), not the full library every scan.

### Rename detection algorithm (target)

```text
For each non-deleted DB row:
  1. Exact path on disk?              → nothing to do
  2. Unicode-equivalent path?         → update filename
  3. Fingerprint match on disk?       → rename; update filename (+ refresh inode if kept)
  4. Otherwise                        → mark deleted

Fingerprint match (step 3):
  missing_from_disk = DB rows whose path is not on this walk
  new_on_disk       = walk paths not matched to any DB row (by path or Unicode)

  For each missing DB row with a stored content_fingerprint:
    candidates = new_on_disk where:
      stat size matches DB pre_conversion_size OR current_size, AND
      partial hash matches content_fingerprint

    exactly one candidate  → rename
    zero candidates        → mark deleted (step 4)
    multiple candidates    → log warning; tie-break by duration, then path similarity; skip if still ambiguous
```

Update MongoDB by **`_id` or `filename`**, not `{"inode": ...}`.

### Tie-breakers (same size + fingerprint collision)

Rare in practice. Order:

1. `format.duration` from cached ffprobe (already in `FileData.video_information`)
2. Longest common path prefix with old filename
3. Log and skip — do not guess

### Schema changes

Add to [FileData](../src/converter/models.py) / MongoDB documents:

```python
content_fingerprint: str | None = None  # hex SHA-256; None until backfilled
```

**Index:** non-unique index on `content_fingerprint` (many deleted rows may share no fingerprint). **Do not** use unique index on fingerprint alone.

**Inode index:** once fingerprint rename is proven in production, consider **dropping the unique index on `inode`** (or keeping `inode` as non-unique). Until then, keep unique index and interim inode sync.

### Why not xattr?

| Approach | Survives rename | Survives drive copy/rsync | Touches media files |
| --- | --- | --- | --- |
| **Partial hash** | Yes | Yes (same bytes) | No (read-only) |
| **xattr UUID** | Yes on APFS | Often **no** | Yes |
| **Inode** | Yes (same stat namespace) | **No** | No |

Sonarr/Radarr, Finder copies, and some migration tools do not preserve arbitrary xattrs. Fingerprint reads content only.

### Trade-offs (accepted)

| Concern | Mitigation |
| --- | --- |
| Two different files, same size, identical first/last MiB | Extraordinarily rare; tie-breakers + log/skip |
| Hash cost on large library | Hash only unmatched paths during rename resolution |
| Post-conversion content change | Expected — recompute fingerprint after convert; old fingerprint matches pre-convert backup only |
| Backfill for existing rows | One-time walk or script: compute fingerprint for all non-deleted docs missing the field |

---

## Interim: startup inode resync (implemented)

Container `st_ino` is **stable for the lifetime of a container** and **across rebuilds** (confirmed in [inodes.txt](../inodes.txt)). It differs from macOS host APFS inodes, but walker and converter agree.

**Chosen interim fix:** on every walker start, run the clear-and-restore inode sync ([inode_sync.py](../src/converter/inode_sync.py)) **before the first folder walk**. Measured cost ~**1 second** for ~10k MongoDB documents (plus one `stat()` per DB row).

### Behaviour

1. Walker starts (`FOLDER_WALKER=TRUE`, `WALKER_IDLE=FALSE`).
2. `TaskScheduler` calls `sync_media_inodes(..., always_apply=True)`.
3. Every document inode cleared to a unique negative placeholder, then rewritten from container `/Media` stat.
4. First folder walk runs with DB inodes matching the walk namespace.

### Why this works

| Scenario | Result |
| --- | --- |
| Accidental host-side `update_inodes.py` | Next walker restart fixes DB |
| Drive move / recopy | Restart walker; inodes refreshed from new volume |
| Container rebuild | Inodes unchanged on disk; sync rewrites same values (~1s) |
| Duplicate-inode walk crash | Sync before walk clears collisions |

### Configuration

```yaml
# docker-compose.yaml
- WALKER_SYNC_INODES_ON_START=TRUE   # default; set FALSE to skip
- WALKER_IDLE=FALSE                   # TRUE skips both sync and walks
```

Manual CLI (optional; same logic):

```bash
docker compose exec walker-1 python3 /src/update_inodes.py --dry-run
docker compose exec walker-1 python3 /src/update_inodes.py --force
```

### Do not

- Run `update_inodes.py` on the **macOS host** while walker uses Docker.
- Rely on host `ls -i` for DB identity.

### Limits

- Does **not** remove dependency on Docker bind-mount inode semantics forever (not a formal guarantee).
- Does **not** replace **fingerprint** identity for rename detection independent of filesystem — still planned long-term.
- Brief window at startup: all inodes negative between clear and restore phases; walks must not run concurrently (sync completes before first walk).

---

## Rejected / deferred alternatives

| Option | Verdict |
| --- | --- |
| **Inode as permanent identity** | Rejected — host/container split, migration pain, unique-index churn |
| **xattr UUID on files** | Rejected — copy/rsync/tooling fragility |
| **Native walker on macOS** | Deferred — [NativeMacOSDesign.md](./NativeMacOSDesign.md); does not solve identity if converter stays in Docker |
| **Size + duration only (no hash)** | Insufficient — too many same-length episodes in a library |

---

## Implementation plan

### Phase 1 — Startup inode resync (done)

- [x] `inode_sync.py`: clear all inodes to negative placeholders, then write finals
- [x] Walker calls sync on startup (`WALKER_SYNC_INODES_ON_START`, default TRUE)
- [x] `update_inodes.py` CLI wraps `inode_sync` (`--force` for unconditional rewrite)
- [x] `WALKER_IDLE` env to skip sync and walks for manual debugging

### Phase 2 — Fingerprint module

- [ ] Add `content_fingerprint.py`: `compute_partial_hash(path: Path) -> str`
- [ ] Unit tests: empty file, &lt; 2 MiB, large file, size mismatch

### Phase 3 — Walker integration

- [ ] Add `content_fingerprint` to [FileData](../src/converter/models.py)
- [ ] Compute on new file ingest in [codec_detector.py](../src/converter/codec_detector.py)
- [ ] Replace inode step in `_update_changed_files()` with fingerprint matching
- [ ] Change `_set_filename_in_db` to update by `_id` / old `filename`, not `inode`
- [ ] Recompute fingerprint after successful conversion in [converter.py](../src/converter/converter.py)

### Phase 4 — Backfill and cleanup

- [ ] One-shot backfill script or walk pass for documents missing `content_fingerprint`
- [ ] Monitor ambiguous-match warnings for one full scan cycle
- [ ] Drop unique index on `inode` (optional, after confidence period)
- [ ] Deprecate or simplify [update_inodes.py](../src/update_inodes.py) — no longer required after volume move once fingerprint rename works

---

## Operational runbook

### After moving or recopying the media drive

**With startup inode sync (default):**

1. Recreate or restart walker (`docker compose up -d walker-1`).
2. Confirm logs: `Startup inode sync complete`.
3. No manual `update_inodes.py` required unless debugging.

**If sync disabled** (`WALKER_SYNC_INODES_ON_START=FALSE`):

```bash
docker compose exec walker-1 python3 /src/update_inodes.py --force
```

### Verify host vs container inode split (diagnostic only)

```bash
stat -f "%i %N" "/Volumes/X10/Media/TV/Some Show/episode.mkv"
docker compose exec walker-1 stat -c "%i %n" "/Media/TV/Some Show/episode.mkv"
```

Different numbers are expected on Mac Docker. **Do not use either for DB updates** once fingerprint rename is live.

### Manual fingerprint check

```bash
# Container
docker compose exec walker-1 sha256sum "/Media/TV/Some Show/episode.mkv"

# macOS (full file — slow on large MKVs; implementation uses partial hash only)
shasum -a 256 "/Volumes/X10/Media/TV/Some Show/episode.mkv"
```

---

## FAQ

### Do I need inodes at all after fingerprint ships?

**No**, for rename detection. They may remain on documents for debugging or be dropped from the unique index. Plex and the converter key off **path** / **filename**.

### Will container rebuild change fingerprints?

**No.** Fingerprints depend on file **content**, not container instance or inode namespace.

### Will drive migration change fingerprints?

**No**, if files are copied faithfully (same bytes). Rows match by fingerprint even when paths and inodes all change.

### Why synthetic negative inodes during `update_inodes.py`?

Interim only. Negative placeholders avoid unique-index violations while swapping 10k+ inode values. Not needed once rename logic no longer depends on inode uniqueness.

### What about converted files?

Conversion **replaces content** — fingerprint must be recomputed on the new HEVC file. That is correct: it is not a rename, it is an in-place replace (or replace + copy-over) at the same or updated path.

---

## Summary

| Problem | Root cause | Long-term fix |
| --- | --- | --- |
| Renames marked as deletes | Inode mismatch (host vs container, migration) | **Fingerprint rename matching** |
| Synthetic / duplicate inode errors | Unique index + bulk inode resync | Stop using inode as identity |
| xattr fragility | Copy tools strip metadata | **Read-only partial hash** (chosen) |

| When | Action |
| --- | --- |
| **Now (interim)** | Automatic startup inode sync in walker (~1s); rename still inode-based within container |
| **Target** | `content_fingerprint` for rename identity independent of Docker/stat namespace |
| **Explicitly not doing** | xattr IDs; permanent reliance on `st_ino` |
