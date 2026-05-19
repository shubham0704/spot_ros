# PLAN: Restore configured camera FPS in spot_ros image server

Version: v2 (post-Codex review)
Status: REFINED — awaiting **principal signoff** (no implementation until signed off)
Branch: `fix/camera-fps-rosbag-10hz` (off `main`; PR to follow after signoff + implementation)
Research: `docs/research/2026-05-19-camera-fps.md`
Review: `docs/plans/FEEDBACK-spot_ros-camera-fps.md`
Changelog: `docs/CHANGELOG.md`

## Goal

Make `spot_image_server` publish at the configured rate during rosbag collection by (a) cutting per-frame payload (the root latency driver), then (b) removing the per-source in-flight cliff and unbatched RPCs — without publishing malformed messages, without breaking existing RAW consumers, and with **honest, bandwidth-aware** rate targets.

## What changed from v1 (Codex-driven)

1. **Phases reordered:** payload reduction (JPEG/compressed) now precedes scheduling/batching — scheduling can't beat a bandwidth-impossible RAW target.
2. **New prerequisite (Phase 1):** split the shared `self.image_requests` map; periodic publishing must not mutate the map used by `GetImages` (`image_server.py:177-185`) and static-TF fetch (`:215`).
3. **Success criteria are now bandwidth-aware** — no blanket "≥9 Hz for all RAW streams" promise.
4. Compressed transport **coexists** with RAW (default RAW); named downstream consumers must keep working.
5. Will **not** build on `AsyncImageService` (no gating/grouping/failure policy).
6. Per-source failure isolation, `hand_tof` guard, byte-aware queues, strict format rejection added.

## Key files

- `image_server.py:139-146` (in-flight gate) · `:75-81/145/177-185/215` (shared request map) · `:84-116` (timers) · `:93-94` (FORMAT_RAW) · `:120-128` (hand_tof) · `:276` (executor)
- `ros_helpers.py:300-304` (broken JPEG branch) · `:267-345` (getImageMsg)
- `spot_driver/config/publish_all_images.yaml`, `image_server_parameters.yaml:24-38`
- Downstream RAW consumers that must not break: `spot_apriltag/launch/spot_apriltag.launch.py:38-40`, `spot_bringup/launch/camera_pointclouds.launch.py:85-91`, `spot_utils/src/spot_utils/camera_client.cpp:10-12`

## Problem

(unchanged — see research doc) 10 Hz is a timer target; RAW over WiFi pushes per-request latency past the 100 ms tick, quantizing to ≤5 Hz; amplified by 140 RPCs/s and GIL byte-copy; naive JPEG flip publishes corrupt images; the configured 14×10 Hz RAW target may exceed WiFi bandwidth regardless of scheduling.

## Phased solution (reordered; each phase independently mergeable)

### Phase 0 — Measurement harness (no behavior change)
Opt-in (default-off) logging of per-batch SDK round-trip latency, achieved Hz/source, and **estimated bytes/s**. Repeatable protocol: `ros2 topic hz` single-camera vs all-camera, on-robot WiFi. Output: a measured bandwidth/latency baseline that classifies the bottleneck (latency-bound vs WiFi-bandwidth-bound) and sets realistic targets for later phases.

### Phase 1 — JPEG guard + request-map split (prerequisite, low risk)
- **Split** `self.image_requests` into `publish_requests` (used by periodic timers) vs `service_requests`/`tf_requests` (RAW, used by `GetImages` `:177-185` and static-TF `:215`). Periodic path never mutates service/TF requests.
- **Guard `ros_helpers.py:300-304`:** for `FORMAT_JPEG`, do not emit an `rgb8` `Image`. `getImageMsg` must **reject unsupported/format-mismatched** inputs (return explicit error / skip with throttled log), never a partial message.

### Phase 2 — Compressed RGB transport (correct, coexisting)
- Config flag (default = current RAW) to request `FORMAT_JPEG` for RGB with `quality_percent`. **`hand_tof` excluded** from RGB JPEG (`image_server.py:120-128`, `:92-94`).
- Publish `sensor_msgs/CompressedImage` (`format="jpeg"`) on `<ns>/image/compressed` **in addition to** RAW topics; RAW remains default so AprilTag / pointcloud-texture / `spot_utils::CameraClient` keep working. Prefer `image_transport` if it cleanly covers the consumers; else manual `CompressedImage` publisher.
- Depth stays RAW (`16UC1`) — note depth may still dominate bandwidth (Phase 0 quantifies).

### Phase 3 — Due-source batched acquisition
- Replace per-source futures with a scheduler that, each tick, batches **all active *due* sources** (subscriber-gated, rate-respecting per `image_server_parameters.yaml:24-38`) into one `get_image_async([...])`. Collapses the all-10 Hz config to one batch; preserves heterogeneous rates.
- **Per-source failure isolation:** check `response.status` per source, publish successful siblings, quarantine repeatedly-failing sources, consider RGB/depth or body/hand failure domains so one bad source can't stall the batch.
- Not built on `AsyncImageService` (lacks gating/grouping/transport/failure policy, `async_queries.py:119-132`).

### Phase 4 — Deadline scheduling (de-quantize)
- Dedicated acquisition scheduler **or** a single ROS timer with locked state driving the next batch by deadline. **Do not** cancel/recreate rclpy timers from SDK future callbacks (reentrancy hazard, `image_server.py:102-111`+`:145-146`). At most one batch in flight; skip-to-newest on overload.

### Phase 5 — Decouple conversion + executor tuning
- SDK callback enqueues responses into a **byte-aware bounded queue** (cap by bytes, not message count); worker pool runs `getImageMsg`+publish; drop-oldest on overload. Re-tune `num_threads` last.

## Success criteria (bandwidth-aware)

- [ ] Phase 0 baseline captured on real robot: per-source Hz, batch latency, bytes/s; bottleneck classified (latency vs bandwidth).
- [ ] With RGB JPEG enabled + rosbag recording, each enabled RGB stream sustains ≥ 9 Hz **OR** the measured bandwidth ceiling is documented with evidence and the achievable rate stated honestly (no overclaiming for RAW).
- [ ] SDK RPC rate reduced ~140/s → ≤ ~20/s (measured).
- [ ] No `sensor_msgs/Image` ever carries a JPEG payload; `CompressedImage` decodes cleanly in rviz + bag replay.
- [ ] RAW topics + AprilTag/pointcloud/`CameraClient` consumers unaffected when JPEG flag off (and still functional when on).
- [ ] `getImageMsg` rejects unsupported formats (no partial messages).
- [ ] Existing tests pass; new tests for request-map split, JPEG→CompressedImage encoding, due-source batching, per-source failure isolation (in `tests/`).

## Risks

1. RAW 14×10 Hz may be WiFi-bandwidth-impossible — Phase 0 must gate expectations before scheduling work.
2. Topic/type changes can break apriltag/rviz/pointcloud/`CameraClient` — coexistence + default-RAW mandatory.
3. Heterogeneous-rate due-source batching grouping correctness.
4. Callback-driven scheduling reentrancy with rclpy executor.
5. Drop-oldest changes rosbag timestamp regularity — document.
6. `getImageMsg` zero-copies `data` by reference; worker decoupling must avoid buffer lifetime bugs.
7. Depth-RAW may remain the dominant bandwidth term even after RGB JPEG.

## Open decision for principal

- **Phase 2 vs Phase 3 first:** Codex recommends compression before batching (cut payload before optimizing scheduling). Plan reflects this. Alternative: do Phase 3 batching first if Phase 0 shows the bottleneck is RPC-count/latency, not raw bandwidth. **Decision deferred to principal after Phase 0 data** — flagged here rather than pre-committed.

## References

### Internal artifacts
- Research: `docs/research/2026-05-19-camera-fps.md` — consolidated root-cause analysis.
- Review: `docs/plans/FEEDBACK-spot_ros-camera-fps.md` — Codex RPI Step 3 architectural review.
- Changelog: `docs/CHANGELOG.md`.

### Source code (spot_ros @ branch `fix/camera-fps-rosbag-10hz`)
- `spot_driver/spot_driver/image_server.py` — in-flight gate `:139-146`; shared request map `:75-81/145/177-185/215`; timers `:84-116`; `FORMAT_RAW` `:93-94`; `hand_tof` `:120-128`; executor `:276`.
- `spot_driver/spot_driver/ros_helpers.py` — malformed JPEG branch `:300-304`; `getImageMsg` `:267-345`.
- `spot_driver/spot_driver/async_queries.py:119-132` — `AsyncImageService` (rejected as Phase 3 base).
- `spot_driver/config/publish_all_images.yaml`, `spot_driver/spot_driver/image_server_parameters.yaml:24-38`.
- Downstream RAW consumers (must not break): `spot_apriltag/launch/spot_apriltag.launch.py:38-40`; `spot_bringup/launch/camera_pointclouds.launch.py:85-91`; `spot_utils/src/spot_utils/camera_client.cpp:10-12`.

### External
- Boston Dynamics Spot SDK (`bosdyn-client` / `bosdyn-api`) — public, documented. Relevant: `ImageClient.get_image[_async]`, `build_image_request(pixel_format, quality_percent, resize_ratio)`. No internal/undocumented APIs used (full SDK inventory in research doc).
- ROS REP-0118 (depth image encodings); `image_transport` / `sensor_msgs/CompressedImage` conventions.
- Reviews produced with Codex CLI v0.130.0 (model gpt-5.5, xhigh), 2026-05-19.

## Document history

| Version | Date | Change |
|---|---|---|
| v1 | 2026-05-19 | Initial PLAN: 5-phase (measure → batch → de-quantize → JPEG → decouple). |
| v2 | 2026-05-19 | Post-Codex: added Phase 1 request-map split prerequisite; reordered (compression before batching); bandwidth-aware success criteria; compressed/RAW coexistence with named consumers; dropped `AsyncImageService` base; per-source failure isolation, `hand_tof` guard, byte-aware queues, strict format rejection; added References + this history; deferred Phase 2/3 ordering to principal pending Phase 0 data. |
