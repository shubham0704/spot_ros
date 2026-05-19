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
