# IMPL: camera-FPS fix — implementation log

Tracks what was actually changed, per phase, against
`docs/plans/PLAN-spot_ros-camera-fps.md` (v2, principal-signed-off 2026-05-19).
Branch: `fix/camera-fps-rosbag-10hz`.

---

## Phase 0 — Measurement harness — DONE (commit `d2baa25`)

**Changed**
- `spot_driver/spot_driver/image_server.py`: added stdlib imports (`os`, `time`,
  `threading`, `collections.defaultdict`); env-gated `self._fps_debug`
  (`SPOT_IMAGE_SERVER_FPS_DEBUG`, default OFF; window via
  `SPOT_IMAGE_SERVER_FPS_DEBUG_WINDOW`, default 5.0s); send-time capture in
  `update_image_task`; `_fps_record` + `_fps_new_bucket`; windowed per-source
  summary (Hz, avg/max latency ms, MB/s) emitted via the node logger.
- `spot_driver/tests/test_fps_debug_accounting.py`.

**Deviation from plan:** plan said "per-batch" latency; Phase 0 measures
*per-source* (batching arrives in Phase 3). Acceptable — Phase 0's job is the
baseline; per-source is the correct granularity pre-batching.

**Behavior change:** none when disabled (one boolean check on the hot path).

**Tests:** pass-or-skip locally (skips without rclpy/bosdyn); run in ROS env.

**Post-review fix (Codex Medium, commit after `78e10e9`):** the send
timestamp is now recorded *before* the future is created / its callback
registered, eliminating a race where an already-resolved future could run
`_fps_record` before the timestamp was stored (which would drop/bias latency
samples). No publish-path effect. See
`docs/plans/VALIDATION-spot_ros-camera-fps.md`.

**Known limitation (Codex Low, accepted):** on a failed/empty future
`_fps_send_times[source]` is not popped. Bounded (overwritten on the source's
next send); only a source that fails then goes permanently inactive leaves one
stale entry, and failed requests are not counted in metrics. Not fixed to
avoid per-request closure cost on the default-disabled hot path; revisit if
failed-request accounting is needed.

**Remaining:** must be run *on the real robot over WiFi* to produce the
baseline that resolves the Phase 2-vs-3 ordering decision. Latency numbers are
authoritative now that the timestamp race is fixed.

---

## Phase 1 — Request-map split + JPEG/format guard — DONE, review-ready

**Changed — `spot_driver/spot_driver/image_server.py`**
- Replaced the single `self.image_requests` with two maps:
  - `self.publish_requests` — consumed only by periodic timers
    (`update_image_task` → `get_image_async([self.publish_requests[src]])`).
  - `self.service_requests` — consumed by `get_image_callback` (GetImages),
    `broadcast_camera_transforms` (static-TF), and `list_sources_callback`
    (registered-source listing / validation).
- Build loop now constructs **distinct** request objects for each map; both
  `FORMAT_RAW` in Phase 1 (byte-identical request semantics → no behavior
  change). Only `publish_requests`' RGB entry is intended to be retargeted to
  JPEG in Phase 2; `service_requests` must remain RAW.
- `from .ros_helpers import ... UnsupportedImageFormatError`.
- `CameraPub.process_data`: `getImageMsg` wrapped; on
  `UnsupportedImageFormatError` it logs a throttled warn and returns without
  publishing (never ships a partial/corrupt Image).
- `get_image_callback`: added `except UnsupportedImageFormatError`.

**Changed — `spot_driver/spot_driver/ros_helpers.py`**
- Added `UnsupportedImageFormatError`.
- `getImageMsg`: `FORMAT_JPEG` now raises (was: malformed `rgb8` Image with a
  JPEG payload — the historical bug). `FORMAT_RAW` with an unhandled
  `pixel_format` now raises (was: silent fall-through leaving a half-filled
  Image). Replaced the buggy `elif data.shot.image.format ==
  image_pb2.Image.PIXEL_FORMAT_UNKNOWN:` (a `.format` vs *pixel_format* enum
  comparison) with an `else:` that logs (throttled) and raises.

**Deviations from plan:** none. Plan called for "reject … never a partial
message" — implemented via a dedicated exception + caller skip, which keeps the
normal RAW path byte-for-byte unchanged.

**Behavior change:** none for supported formats (RAW + RGB_U8 / DEPTH_U16 /
etc. unchanged). Only previously-corrupt/partial outputs now become an
explicit skip-with-log. Strictly safer.

**Tests**
- `tests/test_phase1_request_map_split.py` — 5 dependency-free AST checks
  (old map gone; both maps declared/built; periodic path uses publish map;
  service/TF/listing use service map; service entries RAW). **Pass.**
- `tests/test_phase1_format_guard.py` — JPEG rejected (not mislabeled),
  unhandled RAW pixel_format rejected, unknown format rejected, RAW RGB_U8 and
  DEPTH_U16 still produce valid Images. Skips without rclpy/bosdyn; runs in ROS.
- `python3 -m py_compile` clean for both modules. Full suite:
  `5 passed, 2 skipped`.

**Risk notes for reviewers**
- `service_requests` is the canonical registered-source set used by validation
  and listing — confirm no external caller depended on a map literally named
  `image_requests` (none found in-repo; grep clean).
- `process_data` now early-returns on unsupported format; for a misconfigured
  source this means that stream goes silent (by design) with a 5s-throttled
  warn — intended over publishing corrupt frames.

---

## Phase 2 — Compressed RGB transport — DONE, review-ready

**Data that drove it:** on-robot baseline
(`docs/measurements/2026-05-19-phase0-baseline.md`) showed a hard ~6 MB/s
aggregate WiFi ceiling (single stream 7.5 Hz; all-camera collapses to ~3 Hz
each, latency ~290 ms). Bandwidth-bound confirmed → compression is the only
viable fix; Phase 3-vs-2 decision closed in favor of Phase 2.

**Changed — `spot_driver/spot_driver/ros_helpers.py`**
- Extracted `_buildTfMsg` and `_buildCameraInfo`; `getImageMsg` refactored to
  reuse them (behavior preserved — same encodings/raises; Phase 1 format-guard
  tests still pass).
- Added `getCompressedImageMsg(data, lease_manager) -> (CompressedImage,
  CameraInfo, TFMessage)`: builds a proper `sensor_msgs/CompressedImage`
  (`format="jpeg"`, raw JPEG bytes passed through) + shared CameraInfo/TF.
  Raises `UnsupportedImageFormatError` if not FORMAT_JPEG.
- `from sensor_msgs.msg import ... CompressedImage`.

**Changed — `spot_driver/spot_driver/image_server.py`**
- Env flags: `SPOT_IMAGE_SERVER_RGB_JPEG` (default OFF = RAW, fully backward
  compatible) and `SPOT_IMAGE_SERVER_JPEG_QUALITY` (default 75).
- Build loop: `jpeg_for_this = self._rgb_jpeg and image_source != 'hand_tof'`.
  When set, only `publish_requests[rgb_source]` is `FORMAT_JPEG`
  (`quality_percent`). Depth publish + both `service_requests` entries stay
  RAW (Phase 1 split makes this safe and isolated).
- `CameraPub(compressed=…)`: when compressed, creates a `CompressedImage`
  publisher on `<ns>/image/compressed` and **no** raw `Image` publisher;
  `process_data` routes JPEG via `getCompressedImageMsg`. Raw path unchanged.

**Design decision (user-confirmed):** raw + compressed "both available" is
honored the ROS-idiomatic way — driver requests JPEG (fixes the measured
robot→driver WiFi bottleneck), and consumers needing raw run
`ros2 run image_transport republish compressed raw …` (decode in a dedicated
process, no extra WiFi). The driver does **not** re-request RAW (that would
defeat Phase 2) and does **not** embed a decoder (that would fight Phase 5).

**Behavior change:** none with the flag unset (default) — RAW path is
byte-identical, `getImageMsg` refactor is behavior-preserving. With the flag
set, RGB sources switch to CompressedImage on a new topic; everything else
(depth, service, TF, listing) unchanged.

**Tests:** `tests/test_phase2_jpeg_transport.py` — 5 dependency-free
structural checks (default-off safety, hand_tof exclusion, service/TF maps
untouched, correct message types) + 2 behavior checks for
`getCompressedImageMsg`. Full suite: `10 passed, 4 skipped`. `py_compile`
clean.

**Post-review fixes (Codex Phase 2, commit after `29749c7`):**
- **HIGH (deploy-blocker, fixed):** `update_image_task` dereferenced
  `image_pub` which is `None` in compressed mode → every JPEG RGB tick
  `AttributeError`. Added `CameraPub.active_pub` property; both
  `update_image_task` and `process_data` use it. Regression test added.
- **MEDIUM:** `CompressedImage.format` → conventional
  `"rgb8; jpeg compressed bgr8"` so `image_transport republish` preserves the
  rgb8 contract (on-robot channel-order check noted).
- **MEDIUM:** startup warning now states raw `<ns>/image` is NOT published for
  RGB and names AprilTag / camera_pointclouds / `CameraClient` + republish
  recipe.
- **LOW:** JPEG quality clamped to [1,100] with warning.
- **Doc/DRY:** `getImageMsg` now actually calls `_buildCameraInfo` (inline
  duplicate removed — IMPL claim is now true); measurements doc split into
  RGB-compressed vs RGB+depth cases.
Full review + resolutions: `docs/plans/VALIDATION-spot_ros-camera-fps.md`.

**Remaining:** on-robot validation (set `SPOT_IMAGE_SERVER_RGB_JPEG=1`,
re-run the all-camera fps-debug protocol, confirm aggregate < ~6 MB/s ceiling
and per-stream ≥ ~8–10 Hz; tune quality if needed). Phases 3–5 likely
unnecessary given the bandwidth ceiling, but Phase 3 (batching) may still
reduce latency variance — decide after the Phase 2 on-robot numbers.
