# Native macOS Converter Design

## Overview

This document describes the design for running the converter natively on a Mac Mini while keeping the walker running in Docker on the NAS.

The core requirement is to preserve the current queue-based behavior:

- The walker continues scanning media folders on the NAS and writing file metadata into MongoDB.
- The Mac Mini runs only the converter logic.
- The converter starts automatically at startup or login.
- The converter continuously watches MongoDB for new work in the same way the current Docker backend does.
- The converter uses native macOS ffmpeg with `hevc_videotoolbox` instead of Docker `libx265`.

This design is intentionally additive. Docker support for the existing NAS walker remains intact.

## Current State

The current application already has most of the scheduling and queue orchestration needed for a native service.

### Existing Entry Point

The shared entry point is [src/main.py](../src/main.py), which constructs `TaskScheduler` and calls `run()`.

### Existing Scheduler

The runtime loop is in [src/converter/task_scheduler.py](../src/converter/task_scheduler.py).

Behavior today:

- If `FOLDER_WALKER=TRUE`, the process walks folders and refreshes codec metadata.
- If `FOLDER_WALKER` is not `TRUE`, the process behaves as a converter backend.
- The loop runs continuously with a one second sleep.
- The converter only processes files within the configured conversion window.

### Existing Queue and Coordination

MongoDB is already the shared coordination layer.

Behavior today:

- The walker writes discovered files and codec information into MongoDB.
- The converter atomically claims one pending file by setting `converting=True`.
- Progress, speed, and completion state are written back to MongoDB.
- This model already supports multiple producers and consumers without a redesign.

### Existing Problem Areas

The codebase has several assumptions that are acceptable in Docker but need to be corrected for a native macOS service.

1. [src/converter/config.py](../src/converter/config.py) does not actually parse [src/config.toml](../src/config.toml). It opens the file but then constructs hardcoded values such as `/Media` and `/Conversions`.
2. [src/converter/converter.py](../src/converter/converter.py) hardcodes `libx265` in the ffmpeg command.
3. Notification secret paths are partly hardcoded as `/src/secrets/...`, which is Docker-specific.
4. There is no native launchd service definition, launcher script, or installer.
5. There is no native configuration override path for a Mac-specific deployment.
6. Filenames stored in MongoDB follow the Docker convention rooted at `/Media/...`, but the native Mac mount point is expected to be `/Volumes/Media/...`.

## Target Architecture

The target deployment model is split by role.

### NAS

The NAS keeps the current Docker walker deployment.

Responsibilities:

- Mount and access the media storage directly.
- Run the walker container with `FOLDER_WALKER=TRUE`.
- Scan folders and update MongoDB.

### Mac Mini

The Mac Mini runs the converter natively.

Responsibilities:

- Start automatically using launchd.
- Run the same Python entry point with `FOLDER_WALKER=FALSE`.
- Poll MongoDB for work.
- Copy source files to a local working directory.
- Run ffmpeg using `hevc_videotoolbox`.
- Write progress and final status back to MongoDB.

### Shared Components

Shared across both NAS and Mac:

- MongoDB database and collections.
- `FileData` schema and queue semantics.
- `TaskScheduler` role gating.
- Conversion schedule logic.

## Design Goals

1. Preserve the walker behavior on the NAS.
2. Preserve the MongoDB queue contract.
3. Avoid a queue redesign.
4. Make the native converter deployment reproducible.
5. Make the macOS install idempotent.
6. Keep Docker and native runtime configuration separate where necessary.
7. Add macOS hardware encoding without breaking Linux Docker behavior.
8. Provide simple command-line service controls for start, stop, restart, status, and uninstall.

## Non-Goals

1. Replacing MongoDB.
2. Rewriting the scheduler model.
3. Moving walker responsibilities onto the Mac.
4. Automating NAS share mounting from the Mac installer.
5. Creating native service assets for the walker.

## Runtime Design

### Process Model

Only one native macOS background job is required for this design.

- Job name: converter service
- Role: converter only
- Environment: `FOLDER_WALKER=FALSE`

The current role split remains valid because the NAS walker and Mac converter already coordinate through MongoDB.

### Startup Model

The converter should be installed as a launchd job.

Recommended default:

- Use a `LaunchAgent` if the relevant paths and user environment are available after user login.

Possible alternative:

- Use a `LaunchDaemon` only if the media paths, ffmpeg path, Python environment, and writable directories are guaranteed to exist before user login.

The safer initial choice is a `LaunchAgent`, because the converter is running in a user-owned Python environment and is likely to depend on user-accessible paths.

### Working Directory

The launcher script must set the repository root as the working directory before starting Python.

Reason:

- The current code uses relative paths such as `src/config.toml` and `src/secrets/claims.json`.
- launchd does not guarantee the same working directory as an interactive shell.

### Environment Variables

The native converter should continue using the same environment variables as the current backend process wherever practical.

Required variables:

- `FOLDER_WALKER=FALSE`
- `BACKEND_NAME=<mac-backend-name>`
- `DB_URL=<mongo-uri>`
- `DB_NAME=<database-name>`
- `DB_COLLECTION=<collection-name>`
- `PUSH_COLLECTION=<push-collection-name>`

Additional native-only variables should be added where needed:

- `CONVERTER_CONFIG_PATH=<path-to-native-config.toml>`
- `CONVERTER_ENV_PATH=<optional-path-to-env-file>` if a simple env-file loader is added later
- `CONVERTER_PATH_MAP_FROM=/Media`
- `CONVERTER_PATH_MAP_TO=/Volumes/Media`

## Configuration Design

### Problem

The current `Config` class does not use the TOML file contents. That must change before native deployment can be reliable.

### Required Changes

The configuration layer should:

1. Parse TOML instead of constructing hardcoded values.
2. Support an override path via environment variable.
3. Preserve the existing config shape where possible.
4. Add encoder/runtime options required by the native converter.

### Proposed Config Structure

The existing TOML file can be extended rather than replaced.

Example shape:

```toml
[folders]
include = ["/Media/TV", "/Media/Films"]
exclude = ["/Media/Films/VR"]
backup = "/Media/Backup"
conversions = "/Users/steve/Movies/Conversions"

[schedule]
timezone = "Europe/London"
scan_time = 00:00:00
start_conversion_time = 00:05:00
end_conversion_time = 23:59:00

[encoding]
video_codec = "hevc_videotoolbox"
quality_mode = "native"
vt_qv = 50
vt_qv_small_height = 50
vt_small_height_threshold = 600
x265_crf = 28
x265_preset = "medium"

[runtime]
log_directory = "/Users/steve/Library/Logs/convert-to-h265"

[path_map]
from = "/Media"
to = "/Volumes/Media"
```

This keeps a single model while allowing Docker and native config files to differ.

### Config File Strategy

Use two config files:

1. Repository default config for Docker-oriented or shared defaults.
2. Mac-specific config installed outside the repo or generated from a template.

Recommended approach:

- Keep [src/config.toml](../src/config.toml) as the default checked-in config.
- Allow the Mac service to point at a separate installed config file via `CONVERTER_CONFIG_PATH`.

This avoids editing repo files just to change local Mac paths.

## Encoder Design

### Current State

The converter currently constructs ffmpeg output options with:

- `c:v=libx265`
- `crf=<value>`
- `preset=medium`

That is appropriate for software encoding but not for native VideoToolbox.

### Target State

The converter must support encoder profiles.

Required profiles:

1. `libx265`
2. `hevc_videotoolbox`

### Encoder Profile Rules

#### Docker/Linux Profile

Use current x265 behavior:

- `c:v=libx265`
- `crf=<configured value>`
- `preset=<configured value>`

#### macOS Native Profile

Use VideoToolbox behavior:

- `c:v=hevc_videotoolbox`
- Use `-q:v 50` for the native quality target
- Keep audio copy behavior
- Keep subtitle handling behavior

The implementation should not pass incompatible options to the selected encoder.

The native profile should use a consistent `-q:v 50` target.

### Validation

At startup or before first conversion, the converter should log the selected encoder and fail clearly if ffmpeg does not support it.

Validation options:

1. Run `ffmpeg -hide_banner -encoders` from the installer and fail early if `hevc_videotoolbox` is missing.
2. Add startup-time validation in Python and exit with a clear log message.

Doing both is preferable.

## File Path Design

### Source Media Paths

The source file paths written by the walker must resolve correctly on the Mac Mini.

This is critical.

In this deployment, filenames are stored in MongoDB using the Docker convention rooted at `/Media/...`. The native Mac installation is expected to access the same files through `/Volumes/Media/...`.

That means path mapping is required by design, not as an optional compatibility fallback.

If the database contains `/Media/Films/example.mkv`, the native Mac converter must resolve that to `/Volumes/Media/Films/example.mkv` before checking file existence or copying the file into the local work directory.

Required behavior:

1. Treat `/Media` as the canonical database path prefix written by the Docker walker.
2. Translate `/Media/...` to `/Volumes/Media/...` on the Mac before accessing the filesystem.
3. Keep the mapping configurable in case the Mac mount point changes later.

Example mapping model:

```toml
[path_map]
from = "/Media"
to = "/Volumes/Media"
```

This is a required part of the native design because the queue currently stores absolute Docker-style filenames.

### Conversion Working Directory

The native converter still needs a local staging directory for:

- temporary copied input file
- temporary encoded output file

Requirements:

- writable by the launchd job user
- enough free disk space for large video files
- stable path across restarts

Recommended location:

- a dedicated directory outside the repo, configured in the Mac config file
- prefer a location under `/tmp` rather than `~/Movies`, because `~/Movies` may not be writable or reliable for a launchd-managed task

Example:

- `/tmp/Movies/convert-to-h265-work`

If `/tmp/Movies/convert-to-h265-work` is not suitable in practice, the fallback should be another launchd-safe writable location such as a dedicated directory under `/private/tmp` or another installer-created writable working directory outside the repo.

### Secrets and Notification Files

Current code mixes repo-relative and Docker-absolute secret paths.

That should be normalized.

Required behavior:

1. Resolve secrets relative to a configured secrets directory.
2. Stop assuming `/src/secrets` exists.
3. Allow the launcher or config to specify the secrets location.

## launchd Design

### Assets to Add

The repo should add macOS-specific assets for the converter only.

Recommended files:

- `scripts/macos/run_converter.sh`
- `scripts/macos/install_converter_service.sh`
- `scripts/macos/uninstall_converter_service.sh`
- `scripts/macos/start_converter`
- `scripts/macos/stop_converter`
- `scripts/macos/restart_converter`
- `scripts/macos/status_converter`
- `scripts/macos/templates/com.schleising.convert-to-h265.converter.plist`

The exact file names can vary, but the separation of concerns should remain.

In addition to living in the repo, the service control scripts should be installed into a directory already on the user's `PATH`, or into a managed directory that the installer adds to the user's shell path.

Preferred outcome:

- `start_converter`
- `stop_converter`
- `restart_converter`
- `status_converter`
- `uninstall_converter`

should be runnable directly from the command line.

### Launcher Script Responsibilities

The launcher script should:

1. Resolve the repo root.
2. Activate or invoke the correct Python environment.
3. Set `PATH` so `ffmpeg` can be found under Homebrew.
4. Set required environment variables.
5. Set the config override path.
6. Set path-mapping environment or ensure mapping config is available.
7. Create log and working directories if needed.
8. Execute the Python entry point from the repo root.

The launcher script is preferable to embedding a large environment block directly in the plist.

### Plist Responsibilities

The plist should:

1. Invoke the launcher script.
2. Use `RunAtLoad=true`.
3. Use `KeepAlive=true`.
4. Write stdout and stderr to predictable log files.
5. Use a stable label such as `com.schleising.convert-to-h265.converter`.

The plist should remain small and declarative.

### Install Script Responsibilities

The install script should be the supported setup mechanism for the Mac converter.

Responsibilities:

1. Validate the platform is macOS.
2. Validate required tools exist, especially Python and ffmpeg.
3. Validate `ffmpeg` supports `hevc_videotoolbox`.
4. Create required local directories.
5. Install or update the plist in the correct launchd location.
6. Install service control scripts into a convenient location on `PATH`.
7. Reload the launchd job safely.
8. Print useful status and next steps.

The script should be idempotent.

That means rerunning it should:

- overwrite or refresh existing service files safely
- avoid creating duplicate jobs
- preserve user-provided config where appropriate
- preserve or safely refresh command-line control scripts

### Uninstall Script Responsibilities

The uninstall script should be the inverse of the install script for the native Mac converter.

Responsibilities:

1. Stop and unload the launchd job safely.
2. Remove the installed plist.
3. Remove installed service control scripts.
4. Optionally remove generated logs, working directories, and application-support files after confirmation.
5. Leave the repository checkout untouched unless explicitly asked to remove local generated files inside it.

The uninstall flow should default to safe behavior:

- remove installed service assets
- preserve config and logs unless the user explicitly requests full cleanup

This avoids accidental loss of useful diagnostics or local configuration.

### Service Control Script Responsibilities

The command-line helper scripts should wrap `launchctl` so the service can be managed without remembering plist labels or launchctl syntax.

Required commands:

1. `start_converter`
2. `stop_converter`
3. `restart_converter`
4. `status_converter`
5. `uninstall_converter`

Expected behavior:

- `start_converter` loads or kicks off the launchd job
- `stop_converter` stops or unloads it cleanly
- `restart_converter` performs a safe stop and start sequence
- `status_converter` shows whether the service is loaded and, if practical, where logs are written
- `uninstall_converter` calls the uninstall workflow

These scripts should be thin wrappers around the installed launchd label and local file locations.

### Suggested Install Behavior

Suggested install flow:

1. Determine repo root.
2. Determine install target paths.
3. Check for `.venv` or configured Python path.
4. Check `ffmpeg` availability.
5. Check `hevc_videotoolbox` availability.
6. Create application support directory.
7. Create logs directory.
8. Create working directory.
9. Install start, stop, restart, status, and uninstall helper scripts.
10. Copy or template the plist.
11. Bootstrap or restart the launchd job.

The installer should validate that the configured working directory is writable by the launchd service user before completing installation.

### Suggested macOS Paths

Example locations:

- plist: `~/Library/LaunchAgents/com.schleising.convert-to-h265.converter.plist`
- logs: `~/Library/Logs/convert-to-h265/`
- config: `~/Library/Application Support/convert-to-h265/config.toml`
- work dir: `/tmp/Movies/convert-to-h265-work/`
- helper scripts: `/usr/local/bin/` or another installer-managed directory on `PATH`

These are defaults, not hard requirements.

## Code Changes Required

### 1. Config Loader

File: [src/converter/config.py](../src/converter/config.py)

Required changes:

- parse TOML
- support config override path
- extend schema for encoding/runtime settings
- extend schema for path mapping
- avoid Docker-only hardcoded paths

### 2. Converter Encoder Selection

File: [src/converter/converter.py](../src/converter/converter.py)

Required changes:

- factor ffmpeg output settings into a helper
- select encoder profile from config
- keep existing audio/subtitle behavior
- log selected encoder profile
- apply `-q:v 50` when using `hevc_videotoolbox`
- avoid passing x265-only flags to VideoToolbox

### 3. Path Resolution

File: [src/converter/converter.py](../src/converter/converter.py)

Potential changes:

- add required configurable path mapping from `/Media` to `/Volumes/Media` for the native Mac runtime
- normalize temp and output path generation through config

### 4. Secret Resolution

Files:

- [src/converter/converter.py](../src/converter/converter.py)
- possibly [src/converter/config.py](../src/converter/config.py)

Required changes:

- move secret file paths to config or a single resolver helper
- remove Docker-specific `/src/...` assumptions

### 5. New macOS Service Assets

New files:

- launcher shell script
- installer shell script
- uninstall shell script
- start script
- stop script
- restart script
- status script
- plist template

### 6. Documentation

File: [README.md](../README.md)

Required changes:

- describe split deployment model
- describe Mac prerequisites
- describe install script usage
- describe uninstall script usage
- describe start, stop, restart, and status helper usage
- describe service update flow

## Deployment Flow

### NAS Deployment

No change from current intent:

- deploy walker in Docker on the NAS
- keep media-local access there

### Mac Deployment

Expected flow:

1. Pull repo updates.
2. Ensure Python environment exists.
3. Ensure ffmpeg with VideoToolbox support exists.
4. Prepare native config.
5. Run installer script.
6. Use `start_converter`, `stop_converter`, `restart_converter`, or `status_converter` as needed for operations.
7. launchd starts or reloads the converter job.
8. Converter reconnects to MongoDB and resumes polling.

## Failure Handling

### Missing MongoDB

Behavior:

- current code logs connection errors during collection operations
- service should stay restartable and keep retrying via launchd or loop behavior

### Missing Encoder Support

Behavior:

- installer should fail
- runtime should log and exit clearly rather than failing mid-conversion later

### Missing Source File

Behavior today already exists:

- converter logs that the file does not exist
- clears `converting`

This remains acceptable, but if path mapping is needed this error becomes the signal that the mapping layer is missing or wrong.

Because `/Media` to `/Volumes/Media` mapping is part of the design, this error should usually indicate a bad mapping configuration or an unavailable `/Volumes/Media` mount.

### Interrupted Conversion

The current signal cleanup logic in [src/converter/converter.py](../src/converter/converter.py) should remain in place.

The launchd service should rely on that cleanup behavior when reloading or stopping the job.

## Testing and Verification Plan

### Functional Verification

1. Confirm walker on NAS continues updating MongoDB.
2. Confirm a filename stored as `/Media/...` in MongoDB resolves to `/Volumes/Media/...` on the Mac before conversion starts.
3. Start converter manually on the Mac and confirm it claims work.
4. Confirm staged files are created in `/tmp/Movies/convert-to-h265-work/` or the configured fallback writable work directory.
5. Confirm ffmpeg uses `hevc_videotoolbox`.
6. Confirm videos use `-q:v 50` with `hevc_videotoolbox`.
7. Confirm progress updates appear in MongoDB.
8. Confirm converted output is handled correctly.

### Service Verification

1. Run installer script.
2. Verify plist exists in launchd destination.
3. Verify helper scripts are installed on `PATH`.
4. Verify job is loaded.
5. Use `stop_converter`, `start_converter`, `restart_converter`, and `status_converter` to confirm they manage the service correctly.
6. Reboot or reload and confirm auto-start.
7. Confirm log files are written.

### Uninstall Verification

1. Run `uninstall_converter` or the uninstall script directly.
2. Verify the launchd job is unloaded.
3. Verify the installed plist is removed.
4. Verify helper scripts are removed.
5. Verify optional retained config and logs match the requested uninstall mode.

### Regression Verification

1. Confirm Docker walker still works unchanged.
2. Confirm Docker converter path can still use `libx265` if retained for testing or fallback.
3. Confirm notification handling still works if configured.

## Open Questions

1. Should the installer place helper scripts in `/usr/local/bin`, or in a user-local bin directory such as `~/bin`?
2. Should the installer manage Python package installation, or only validate an existing virtual environment?
3. Should the Mac service run as a LaunchAgent or a LaunchDaemon in the final deployment?
4. Should a native fallback encoder be supported if `hevc_videotoolbox` is unavailable?

## Recommended Implementation Order

1. Fix config loading.
2. Add required `/Media` to `/Volumes/Media` path mapping.
3. Add encoder profile support.
4. Normalize secret resolution.
5. Add launcher script.
6. Add plist template.
7. Add installer, uninstall, and service control scripts.
8. Update documentation.
9. Test end to end.

## Summary

The existing architecture is already close to what is needed. The NAS walker can remain unchanged in Docker, while the Mac Mini runs only the converter as a native launchd-managed service.

The main work is not in queue logic. It is in deployment correctness:

- configuration must become real instead of Docker-hardcoded
- Docker-style `/Media/...` database paths must be translated to `/Volumes/Media/...` on macOS
- encoder selection must support `hevc_videotoolbox`
- the native working directory must use a launchd-safe writable location such as `/tmp/Movies/convert-to-h265-work`
- the native VideoToolbox profile must use `-q:v 50`
- file paths and secrets must stop assuming container layout
- a proper macOS launcher, plist, installer, uninstaller, and service-control scripts must be added

If those pieces are implemented cleanly, the converter will behave the same way it does today from a scheduling and database perspective, but will run natively on macOS and use hardware-assisted HEVC encoding.