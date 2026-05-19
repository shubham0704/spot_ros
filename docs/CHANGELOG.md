# Changelog

All notable changes for the **camera-FPS-during-rosbag** work.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Branch: `fix/camera-fps-rosbag-10hz` (off `main`).

## [Unreleased]

Plan v2 **signed off by principal** 2026-05-19. Phases land as separate, independently-mergeable commits.

### Added — Phase 0 (measurement, no behavior change) — DONE
- Opt-in instrumentation in `spot_driver/spot_driver/image_server.py`: per-source SDK round-trip latency, achieved Hz, and bytes/s, with a windowed summary log. Pure logging — no request/threading/publish change; disabled path is a single boolean check.
- Enable: `export SPOT_IMAGE_SERVER_FPS_DEBUG=1` (optional `SPOT_IMAGE_SERVER_FPS_DEBUG_WINDOW=<sec>`, default 5.0) before launching the image server. Default OFF.
- Measurement protocol: with it enabled, run `ros2 topic hz <topic>` for one camera, then for all cameras + `rosbag record`, on real robot WiFi; compare the logged per-source Hz / latency / MB/s to classify latency-bound vs bandwidth-bound.
- Tests: `spot_driver/tests/test_fps_debug_accounting.py` (accounting, window flush/reset, missing-send-time, bucket independence).

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
