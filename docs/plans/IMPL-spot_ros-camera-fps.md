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

**Remaining:** must be run *on the real robot over WiFi* to produce the
baseline that resolves the Phase 2-vs-3 ordering decision.

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

**Remaining (later phases):** Phase 2 retargets `publish_requests` RGB →
`FORMAT_JPEG` + publishes `sensor_msgs/CompressedImage` (coexisting with RAW);
Phases 3–5 per plan. Phase 2-vs-3 ordering still gated on Phase 0 robot data.
