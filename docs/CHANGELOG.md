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

### Added — Phase 2 (compressed RGB transport) — DONE (review-ready)
- `SPOT_IMAGE_SERVER_RGB_JPEG` (default OFF = RAW, backward compatible) + `SPOT_IMAGE_SERVER_JPEG_QUALITY` (default 75). When on, RGB sources (≠ `hand_tof`) request `FORMAT_JPEG` and publish `sensor_msgs/CompressedImage` on `<ns>/image/compressed`; depth/service/static-TF stay RAW.
- `ros_helpers.py`: `getCompressedImageMsg` + extracted shared `_buildTfMsg`/`_buildCameraInfo` (getImageMsg refactored, behavior preserved).
- Raw-when-JPEG-on is the standard `image_transport republish compressed raw` (no extra robot→driver WiFi); driver does not re-request RAW or embed a decoder.
- Tests: `spot_driver/tests/test_phase2_jpeg_transport.py` (5 structural + 2 behavior). Suite `10 passed, 4 skipped`.
- Driven by on-robot data: all-camera run shows a hard ~6 MB/s aggregate WiFi ceiling (`docs/measurements/2026-05-19-phase0-baseline.md`) — compression is the only viable fix.

### Fixed — post-Codex-review (Phase 2)
- **HIGH deploy-blocker:** `update_image_task` dereferenced `image_pub` (None in compressed mode) → JPEG path crashed every tick. Added `CameraPub.active_pub`; used in both gate + publish. Regression test added.
- **MEDIUM:** `CompressedImage.format` → conventional `"rgb8; jpeg compressed bgr8"` (republish preserves rgb8).
- **MEDIUM:** startup warning now names broken raw consumers (AprilTag/pointcloud/`CameraClient`) + republish recipe.
- **LOW:** JPEG quality clamped to [1,100]. **DRY:** `getImageMsg` reuses `_buildCameraInfo`. Measurements doc splits RGB-compressed vs RGB+depth success cases.
- Review + resolutions: `docs/plans/VALIDATION-spot_ros-camera-fps.md` (Phase 2 section). Suite `13 passed, 4 skipped`.

### Planned — Phase 3 (due-source batched acquisition)
- Single batched `get_image_async` over active due sources; per-source `response.status` isolation + failure quarantine. Not built on `AsyncImageService`.

### Planned — Phase 4 (deadline scheduling)
- De-quantize the 100 ms tick cliff; single-batch-in-flight, skip-to-newest; no rclpy timer cancel/recreate from SDK callbacks.

### Planned — Phase 5 (decouple conversion + executor tuning)
- Byte-aware bounded queue + worker pool for `getImageMsg`/publish; re-tune `num_threads` last.

## [Data collection] - 2026-05-19

Operator-facing collection workflow tied to this branch's instrumentation:

### Added
- `docs/data-collection/README.md` — index + workflow summary; explains why per-episode `fps-debug` logging is non-optional.
- `docs/data-collection/operator-deck.md` — 10-slide operator briefing deck grounded in the spot_ros stack (real `/spot_image_server/...` topics, env-var workflow, the 5 motion primitives incl. `base_yaw_scan`).
- `docs/data-collection/field-card.md` — one-page during-recording checklist (env, per-episode steps, stop conditions, primitives cheat-sheet, bag naming).
- `docs/data-collection/metadata_template.yaml` — required per-episode metadata; `fps_debug_summary` and `quarantine` fields make the dataset filterable.
- `docs/data-collection/preflight_check.sh` — verifies node/services/topics/Hz/disk/env, prints a curated `ros2 bag record` command using only discovered topics, fails loudly on critical conditions.

Closes the loop: Phase 0 `fps-debug` becomes the per-episode quality gate; Phase 2 JPEG mode is the recommended collection transport (bandwidth-stable, makes episodes comparable). Non-image topic names (joint_states/odom/battery/tf) are intentionally not hardcoded — `preflight_check.sh` discovers them on the actual robot.

## [Merge] origin/devel - 2026-05-19

Merged `origin/devel` (45 commits ahead of stale `main`; non-destructive merge, no force-push) into `fix/camera-fps-rosbag-10hz`.

- Single conflict (`image_server.py` `CameraPub.__init__`, devel `6e0b838`). Resolved by combining devel's `QoSProfile(RELIABLE, KEEP_LAST, depth=1)` with the Phase 2 compressed publisher + `active_pub` — the RELIABLE depth=1 profile is now applied to **all** image publishers including `compressed_pub`.
- **Behavioral change:** image/compressed/info QoS is now RELIABLE depth=1 (was BEST_EFFORT). **Invalidates the prior Phase 0 baseline** — re-measure on the merged branch (flagged in `docs/measurements/2026-05-19-phase0-baseline.md`).
- Also pulls devel infra unrelated to our files (reentrant callback groups for other sensors, sim, nav TF fix, etc.). Suite `13 passed, 4 skipped`; `py_compile` clean; no conflict markers; no stray `qos_profile_sensor_data` **in `image_server.py`** (note: `spot_ros.py` still legitimately imports/uses it — out of scope, unaffected). Codex merge-sanity: no blockers (see `docs/plans/VALIDATION-spot_ros-camera-fps.md`).

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
