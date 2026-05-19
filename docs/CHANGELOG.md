# Changelog

All notable changes for the **camera-FPS-during-rosbag** work.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Branch: `fix/camera-fps-rosbag-10hz` (off `main`).

## [Unreleased]

Implementation is **gated on principal signoff** of `docs/plans/PLAN-spot_ros-camera-fps.md` (v2). Nothing below is implemented yet; phases land as separate, independently-mergeable commits.

### Planned — Phase 0 (measurement, no behavior change)
- Opt-in (default-off) instrumentation: per-batch SDK round-trip latency, achieved Hz/source, estimated bytes/s.

### Planned — Phase 1 (prerequisite, low risk)
- Split shared `image_server.py` `self.image_requests` into separate publish vs `GetImages`/static-TF request maps.
- Guard `ros_helpers.py:300-304`: never emit `rgb8` `Image` for JPEG; `getImageMsg` rejects unsupported formats (no partial messages).

### Planned — Phase 2 (compressed RGB transport, coexisting)
- Config flag (default RAW) to request `FORMAT_JPEG` RGB; publish `sensor_msgs/CompressedImage` on `<ns>/image/compressed` alongside RAW. `hand_tof` excluded. Depth stays RAW.

### Planned — Phase 3 (due-source batched acquisition)
- Single batched `get_image_async` over active due sources; per-source `response.status` isolation + failure quarantine. Not built on `AsyncImageService`.

### Planned — Phase 4 (deadline scheduling)
- De-quantize the 100 ms tick cliff; single-batch-in-flight, skip-to-newest; no rclpy timer cancel/recreate from SDK callbacks.

### Planned — Phase 5 (decouple conversion + executor tuning)
- Byte-aware bounded queue + worker pool for `getImageMsg`/publish; re-tune `num_threads` last.

## [Docs] - 2026-05-19

### Added
- `docs/research/2026-05-19-camera-fps.md` — consolidated root-cause analysis (Claude + independent Codex investigation; verified `ros_helpers.py:300` JPEG-message bug; Boston Dynamics SDK inventory — all public/documented APIs).
- `docs/plans/PLAN-spot_ros-camera-fps.md` v1 — initial 5-phase plan.
- `docs/plans/FEEDBACK-spot_ros-camera-fps.md` — Codex RPI Step 3 architectural review (gpt-5.5, captured from stdout; read-only sandbox blocked autonomous file write — provenance noted in file).
- `docs/plans/PLAN-spot_ros-camera-fps.md` v2 — incorporated Codex feedback (see plan "Document history").
- `docs/camera-fps-explainer.md` — lab-facing teaching document with ASCII diagrams; each fix explained pedagogically.
- `docs/CHANGELOG.md` — this file.

### Process notes
- `codex exec` hangs reading stdin when backgrounded → resolved with `< /dev/null`.
- `codex exec` defaults to read-only sandbox → cannot self-write FEEDBACK file as the rpi-workflow skill assumes; captured from stdout with provenance instead.
