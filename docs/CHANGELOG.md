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

### Added — Phase 1 (prerequisite, low risk) — DONE (review-ready)
- Split `image_server.py` `self.image_requests` → `self.publish_requests` (periodic timers) + `self.service_requests` (GetImages service, static-TF fetch, source listing). Both FORMAT_RAW in Phase 1 → **no behavior change**; only `publish_requests` is retargeted in Phase 2.
- `ros_helpers.py`: added `UnsupportedImageFormatError`; `getImageMsg` now **raises** for JPEG-on-raw-path, unhandled FORMAT_RAW pixel_format, and any other format (previously emitted a malformed `rgb8` Image or a half-filled/empty Image). Also fixes the latent bug where `.format` was compared to a `pixel_format` enum.
- Both call sites guarded: `CameraPub.process_data` skips the frame (throttled warn) instead of publishing garbage; `get_image_callback` returns failure with a clear log.
- Tests: `spot_driver/tests/test_phase1_request_map_split.py` (5, dependency-free AST), `spot_driver/tests/test_phase1_format_guard.py` (behavior; skips where rclpy/bosdyn absent).
- Detailed implementation notes: `docs/plans/IMPL-spot_ros-camera-fps.md`.

### Fixed — post-Codex-review (Phase 0)
- fps-debug timestamp race (Codex Medium): send time is now captured before the SDK future/callback is created, so latency samples can't be lost to an already-resolved future. No publish-path change. Validation: `docs/plans/VALIDATION-spot_ros-camera-fps.md`.
- Known accepted limitation (Codex Low): failed/empty futures don't pop `_fps_send_times` (bounded; documented in IMPL doc).

### Added
- `docs/plans/VALIDATION-spot_ros-camera-fps.md` — Codex Step 6 review of the Phase 0+1 implementation (verdict: safe to deploy/test on robot for normal RAW operation).
- `docs/measurements/2026-05-19-phase0-baseline.md` — first on-robot Phase 0 baseline (single RGB stream ~7.5 Hz/10, lat max ~120–131 ms, ~6.9 MB/s). Confirms the 100 ms quantization cliff on hardware and **resolves the Phase 2-vs-3 decision → Phase 2 first** (data-backed).

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
