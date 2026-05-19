# VALIDATION: Codex review of Phase 0 + Phase 1 implementation

Reviewer: Codex (gpt-5.5, xhigh), RPI Step 6 (implementation validation)
Date: 2026-05-19
Reviewed diff: `0adeab6..HEAD` (`d2baa25` Phase 0, `78e10e9` Phase 1)
Provenance: Codex ran from the `spot_ros` project root; its write to this file
was blocked by the default read-only sandbox ("patch rejected"). Review below
is transcribed verbatim from Codex stdout by Claude (see
[[feedback-codex-exec-gotchas]]).

## Findings

### Medium — fps-debug timestamp capture can race the future callback — FIXED
`update_image_task` registered the done callback before recording the send
timestamp. If the SDK future was already complete (or completed between
`add_done_callback(...)` and the timestamp write), `publish_image_callback` →
`_fps_record` could run first, pop no timestamp, record the frame with no
latency, and leave a stale timestamp. Impact: **no publish-path behavior
change**, but Phase 0 latency metrics could be missing/underreported/
misattributed (average divides by total frame count, so misses bias it low).
**Resolution:** the send timestamp is now written *before* the future is
created and its callback registered (`image_server.py`, `update_image_task`),
eliminating the race. Latency = callback time − request-initiation time.

### Low — failed/empty futures don't pop `_fps_send_times` — DOCUMENTED (accepted)
If `response_future.result()` raises (or `result()[0]` raises `IndexError`),
`_fps_record` is never called, so the send-time entry isn't removed. Codex
notes this is **bounded, not unbounded** (keyed by source; later sends
overwrite the same key). The only lasting effect is one stale entry for a
source that fails and then goes permanently inactive, plus failed requests
being invisible to metrics. **Decision:** accepted as a known limitation —
fixing it cleanly requires carrying the source name through the callback
(per-request closure), which would add cost/complexity to the
default-disabled hot path that Codex explicitly validated as "only boolean
checks." Recorded in `IMPL-spot_ros-camera-fps.md` and `CHANGELOG.md`.
Revisit if Phase 0 metrics need failed-request accounting.

## Confirmations (no action needed)

- **Phase 0 thread-safety:** sound. Updates + window reset under `_fps_lock`,
  formatting/logging outside the lock — no deadlock risk.
- **"No behavior change when disabled":** true. With the env var unset, the hot
  path adds only boolean checks; request shape, callback model, publishing
  unchanged.
- **Phase 1 request-map split:** all former `self.image_requests` uses
  correctly routed — periodic → `publish_requests`; GetImages
  validation/fetch, source listing, static-TF → `service_requests`. Both maps
  populated for every source before rate checks (matches old behavior for
  disabled-rate sources); both `FORMAT_RAW`; identical `hand_tof` handling. No
  path needs the other map. `broadcast_camera_transforms`,
  `list_sources_callback`, `get_image_callback` behave identically in normal
  RAW operation.
- **Phase 1 format guard:** correct at both call sites
  (`CameraPub.process_data` skips with throttled warn;
  `get_image_callback` returns `success=False`). No false-positive regression
  for configured RAW sources (mono8/rgb8/rgba8/mono16/16UC1 unchanged). JPEG
  rejection unreachable in normal RAW operation. Removing the old
  empty/partial-message path is a deliberate contract improvement.

## Deploy verdict (Codex)

> Safe to deploy and test on the real robot for normal RAW operation. The only
> blocker-quality issue is measurement accuracy when fps-debug is enabled; fix
> the timestamp race before treating latency numbers as authoritative.

The blocker (timestamp race) is now fixed → Phase 0 latency numbers are
authoritative.

## On-robot validation steps (from Codex)

1. Launch with RAW config and fps-debug unset; confirm no new warnings.
2. Subscribe to one RGB and one depth topic; verify `ros2 topic hz`,
   `encoding`, `step`, `height`, `width`.
3. Call `~/list_registered_sources`; compare names with pre-branch output.
4. Call `~/get_images` for body RGB/depth, `hand_rgb`, `hand_tof`; expect
   `success=True`, unchanged encodings.
5. Confirm static camera TFs publish once after startup.
6. Enable `SPOT_IMAGE_SERVER_FPS_DEBUG=1`; run single-camera/all-camera rosbag
   tests; Hz/bytes-per-second and (now) latency are all usable.
7. Verify no `UnsupportedImageFormatError` warnings in normal RAW mode.

## Test notes (Codex)

Ran the dependency-free request-map test: `5 passed`. Phase 0 and
format-guard modules skipped (ROS/bosdyn deps unavailable in that session):
`2 skipped`. Matches local results.

---

# VALIDATION: Codex review of Phase 2 implementation

Reviewer: Codex (gpt-5.5, xhigh)
Date: 2026-05-19
Reviewed diff: `b90065a..29749c7`
Provenance: read-only sandbox blocked Codex's append; transcribed from stdout
by Claude (see [[feedback-codex-exec-gotchas]]). Resolutions appended per item.

## Findings & resolutions

### HIGH — `update_image_task` dereferences `image_pub=None` in compressed mode — FIXED
`CameraPub` sets `self.image_pub = None` for compressed RGB, but
`update_image_task`'s subscriber gate still called
`self.camera_pubs[src].image_pub.get_subscription_count()`
(`image_server.py:233`). With `SPOT_IMAGE_SERVER_RGB_JPEG=1` every JPEG RGB
tick would `AttributeError` before `get_image_async` → Phase 2 entirely
non-functional. The Phase 2 AST test missed it (only checked `process_data`).
**Verified directly.** **Resolution:** added `CameraPub.active_pub` property
(returns `compressed_pub` if compressed else `image_pub`); both
`update_image_task` and `process_data` now use it. Added a structural test
that fails if `update_image_task` dereferences `.image_pub` directly.

### MEDIUM — `CompressedImage.format="jpeg"` too weak for `image_transport republish` — FIXED
ROS convention is `ORIG_PIXFMT; CODEC compressed [COMPRESSED_PIXFMT]`; a bare
`"jpeg"` may make a raw republisher emit `bgr8` instead of the original
`rgb8`. **Resolution:** format set to `"rgb8; jpeg compressed bgr8"` (the
conventional string); on-robot channel-order validation noted as a caveat in
the measurements doc.

### MEDIUM — JPEG-on silently removes raw `<ns>/image`; AprilTag/pointcloud/CameraClient break — MITIGATED
Design (driver requests JPEG; raw via external `image_transport republish`)
confirmed sound for the measured bottleneck. But the startup warning didn't
say raw RGB topics disappear or name affected consumers. **Resolution:**
startup warning strengthened to explicitly state raw `<ns>/image` is NOT
published for RGB sources and to name AprilTag / pointcloud-texture /
`spot_utils::CameraClient`, with the `republish` recipe. Launch-level
auto-republisher recorded as a follow-up (not blocking; default stays off).

### LOW — JPEG quality not range-validated — FIXED
`SPOT_IMAGE_SERVER_JPEG_QUALITY` was parsed but unclamped. **Resolution:**
clamped to [1,100] with a startup warning on out-of-range.

### LOW — success criteria realistic only for compressed RGB, not RGB+depth — FIXED (docs)
Depth stays RAW (correct), so the ~6 MB/s target applies to the RGB-compressed
case, not `publish_all_images.yaml` with all depth at 10 Hz. **Resolution:**
measurements doc split into "RGB compressed" vs "RGB+depth publish_all" cases.

### Confirmation correction — `getImageMsg` still had an inline CameraInfo duplicate — FIXED
Codex noted the IMPL claim that `getImageMsg` reuses `_buildCameraInfo` was
untrue (inline duplicate remained). **Resolution:** `getImageMsg` now actually
calls `_buildCameraInfo` (DRY completed; behavior preserved — Phase 1
format-guard tests cover the RAW encodings/raises).

## Codex confirmations (no action)

- `getImageMsg` RAW behavior preserved (mono8/rgb8/rgba8/mono16/16UC1; JPEG /
  unhandled-pixel-format / unknown still raise). `_buildTfMsg` preserves filter
  + iteration order.
- Robot-ignores-JPEG → `getCompressedImageMsg` raises → `process_data` skips
  with 5 s-throttled warn: safe/visible (stream goes silent).
- Request isolation intact: only `publish_requests[rgb]` → JPEG; depth +
  service + static-TF stay RAW; `hand_tof` excluded.
- Flag unset ⇒ behavior equivalent to Phase 1 (RAW path byte-identical).
- Compressed QoS = same BEST_EFFORT sensor profile; validate rosbag2 QoS on
  robot.
- No new thread-safety issue.

## Verdict (Codex)

> Do not deploy Phase 2 as-is: compressed RGB acquisition is blocked by the
> `image_pub=None` dereference in `update_image_task`. After that fix, the
> request-map isolation and raw-default compatibility look correct.

Deploy-blocker (HIGH) is now fixed; all other items resolved or mitigated.

---

# VALIDATION: Merge sanity (origin/devel)

Reviewer: Codex (gpt-5.5), Date: 2026-05-19
Reviewed merge: `341c896` (parents `a9223b3` = pre-merge Phase-2 tip, and
`15f5b78` = origin/devel). Relevant devel commit: `6e0b838`.
Provenance: read-only sandbox blocked Codex's append; transcribed from stdout
by Claude (see [[feedback-codex-exec-gotchas]]).

## Verdict: NO BLOCKERS — safe to build and test on the robot.

## Confirmations
- **Conflict resolution correct.** vs `a9223b3`: `ros_helpers.py` has *no
  diff* (our work untouched by devel); `image_server.py` changes only the
  publisher-QoS integration. `QoSProfile(RELIABLE, KEEP_LAST, depth=1)` now on
  camera_info, raw image, and Phase 2 compressed publishers. Preserves devel
  `6e0b838` intent (RELIABLE-subscriber compatibility, e.g. the
  image→pointcloud path). Applying RELIABLE depth=1 to `CompressedImage` is the
  right choice (RELIABLE pub works with BEST_EFFORT subs; BEST_EFFORT compressed
  would recreate devel's compat problem for republish/rosbag).
- **All Phase 0/1/2 code survived intact** (fps-debug, request-map split,
  `UnsupportedImageFormatError` guard, `getCompressedImageMsg`, `active_pub`,
  JPEG opt-in/hand_tof-exclusion/depth-service-TF-RAW) — line-ref confirmed.
- **Semantic devel interactions clean:** of the 45 devel commits, only
  `6e0b838` touches the real image server. devel's reentrant-callback-group
  change `00c7f7e` is **simulation-only**; the real image server still uses
  per-timer `MutuallyExclusiveCallbackGroup` + `MultiThreadedExecutor(4)`.
  No devel change touched `image_server_parameters.yaml`/`setup.py`. Nav/sim
  commits don't affect camera FPS.
- No conflict markers / unresolved files.

## Low findings & resolutions
1. **RELIABLE depth=1 is a validation hazard, not a merge bug** — can add DDS
   backpressure with slow/remote subscribers; fps-debug times SDK arrival
   (pre-publish). → Already flagged: re-baseline on `341c896` and compare
   fps-debug vs `ros2 topic hz`/rosbag delivery. No action beyond the existing
   re-test requirement.
2. **CHANGELOG wording inaccuracy (Claude-introduced)** — the merge entry said
   "no stray `qos_profile_sensor_data`" globally, but `spot_ros.py:41,811,812`
   legitimately still uses it. → **FIXED**: wording corrected to scope the
   claim to `image_server.py`.

## Note (not a blocker)
`git diff --check 341c896^1 341c896` flags trailing whitespace in unrelated
devel-added sim/nav/docs files (not ours). Irrelevant to camera runtime;
relevant only if CI enforces whitespace — out of scope for this branch.

## Robot revalidation required (unchanged)
1. RAW/default on `341c896`: re-run single + all-camera Phase 0 fps-debug
   under RELIABLE depth=1.
2. `SPOT_IMAGE_SERVER_RGB_JPEG=1`: RGB-compressed throughput/Hz + verify
   `image_transport republish compressed raw`.
3. Keep launch composition comparable (devel nav/sim changes can add unrelated
   load if newly enabled).
