# Research: Spot ROS 2 camera FPS below configured 10 Hz during rosbag collection

Date: 2026-05-19
Repo: `spot_ros` (UTNuclearRoboticsPublic)
Inputs: Claude analysis + independent Codex investigation (gpt-5.5, xhigh) + Boston Dynamics SDK API inventory (Explore agent). Codex bug claim independently verified by reading source.

## Symptom

`spot_driver/config/publish_all_images.yaml:4-24` sets all 7 sources to 10 Hz RGB + 10 Hz depth. Actual published rate during rosbag recording is materially lower.

## Root causes (ranked, converged across Claude + Codex)

1. **One-request-in-flight gate caps FPS below the timer rate.**
   `image_server.py:139-146` `update_image_task()` issues a new SDK request only if the prior future for that source is absent or `.done()`. No queue, no catch-up. Effective per-stream rate is quantized by the 100 ms timer period:
   `fps ≈ 1 / (ceil(request_latency / 0.1s) · 0.1s)` →
   ≤100 ms ⇒ 10 Hz; 100–200 ms ⇒ 5 Hz; 200–300 ms ⇒ 3.3 Hz; 300–400 ms ⇒ 2.5 Hz. A latency just over 100 ms collapses straight to 5 Hz (cliff, not gradual decay).

2. **Periodic acquisition is unbatched: one gRPC RPC per camera stream.**
   `image_server.py:145` calls `get_image_async([single_request])` per source. 7 sources × (rgb+depth) × 10 Hz ⇒ up to **140 RPCs/s**. The SDK *does* support batching and the codebase already uses it in the service path (`image_server.py:177`) and static-TF fetch (`image_server.py:215`) — just not in periodic publishing. Batching → ~10 RPCs/s.

3. **`FORMAT_RAW` makes per-request latency/bandwidth high (esp. WiFi + bagging).**
   Hardcoded `FORMAT_RAW` at `image_server.py:93-94`; raw bytes copied into ROS `Image.data` at `ros_helpers.py:313/320/334/342`. Large gRPC payloads from robot, then large DDS payloads into rosbag. ≈3.7 MB/RGB frame, ≈2.5 MB/depth frame.

4. **Executor/threading does not give 14 parallel pipelines.**
   14 timers, each its own `MutuallyExclusiveCallbackGroup` (`image_server.py:101/109`), but `MultiThreadedExecutor(num_threads=4)` (`image_server.py:276`). RAW→ROS conversion (`getImageMsg`, `ros_helpers.py:267`) is GIL-bound Python byte-copy; thread count alone won't parallelize it.

5. **Timer ticks are skipped, not caught up.**
   Timers at `1/rate` (`image_server.py:103/111`); if a future is in flight, `image_server.py:140` simply suppresses the request. 10 Hz is an upper bound, never guaranteed.

## Why it manifests during rosbag specifically

Work is gated on subscribers: request gating at `image_server.py:142-143`, conversion/publish gating at `image_server.py:40-45`. Without subscribers nothing is fetched. rosbag subscribing to all topics activates all 14 streams at once → contention appears only under bagging.

## Verified latent bug (blocks the naive JPEG fix)

`ros_helpers.py:300-304`: the `FORMAT_JPEG` branch sets `encoding="rgb8"`, `step=3*cols`, and assigns the raw JPEG bitstream to `image_msg.data` of a `sensor_msgs/Image`. This is malformed — an `rgb8` Image must contain `height*step` decoded bytes, not a JPEG stream. Consumers (rviz/cv_bridge/bag replay) mis-decode. **Consequence:** simply switching `FORMAT_RAW → FORMAT_JPEG` would publish corrupt images. JPEG must be published as `sensor_msgs/CompressedImage` (or via `image_transport`).

## Boston Dynamics SDK surface (answer to "what internal APIs are we using")

The codebase uses **only standard, documented public Spot SDK** (`bosdyn-client`/`bosdyn-api`). No private gRPC stubs, no reverse-engineered or internal endpoints, no token/GUID hacks (auth via `bosdyn.client.util.authenticate`). Full inventory captured separately; FPS-relevant facts:

- `ImageClient` (`image_server.py:70`): `get_image` / `get_image_async` (`:145/177/215`); `build_image_request` (`:93-94`) — public, supports `pixel_format`, **`quality_percent`, `resize_ratio`** (unused here).
- Batched `get_image_async([...])` is public and already exercised at `:177/215`.
- `async_queries.py` already wraps `AsyncPeriodicQuery`/`AsyncImageService` — an existing in-repo pattern for rate-managed polling.
- Only non-default service name is `'velodyne-point-cloud'` (EAP2 lidar, `spot_body_wrapper.py:131`) — vendor payload service, not relevant to camera FPS. No camera-side internal APIs.

Conclusion: no internal-API risk; remediation stays within documented SDK calls.

## Key files

| File | Lines | Role |
|---|---|---|
| `spot_driver/spot_driver/image_server.py` | 139-146 | in-flight gate (primary bottleneck) |
| " | 145 | per-source unbatched async request |
| " | 93-94 | hardcoded `FORMAT_RAW` |
| " | 101/109/276 | callback groups vs 4-thread executor |
| " | 142-143 / 40-45 | subscriber gating (rosbag trigger) |
| `spot_driver/spot_driver/ros_helpers.py` | 300-304 | **broken JPEG→Image branch** |
| " | 267-345 | `getImageMsg` RAW byte copy |
| `spot_driver/config/publish_all_images.yaml` | 4-24 | 10 Hz target config |
| `spot_driver/spot_driver/async_queries.py` | — | existing AsyncPeriodicQuery pattern |
