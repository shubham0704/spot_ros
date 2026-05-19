# FEEDBACK: Codex review of PLAN-spot_ros-camera-fps

Reviewer: Codex (gpt-5.5, xhigh), RPI Step 3
Date: 2026-05-19
Provenance note: Codex ran from the `spot_ros` project root per the rpi-workflow skill, but `codex exec` defaults to a **read-only sandbox**, so its attempt to create this file was rejected ("patch rejected: writing is blocked by read-only sandbox"). Content below is the verbatim review captured from Codex stdout, transcribed here by Claude (deduplicated — Codex emitted the final message twice). Skill gap recorded: Step 3's documented "Codex writes feedback autonomously" requires a workspace-write sandbox flag, which the skill command omits.

## Overall verdict

Diagnosis is **sound**. Main architectural critique: the plan optimizes RPC scheduling before reducing the payload that causes the latency cliff, and it omits a required request-map split. The "all RAW streams at 10 Hz over WiFi" target is likely bandwidth-impossible.

## Confirmations

- Per-source in-flight gate at `image_server.py:139-146`; single-source periodic RPCs at `image_server.py:145`; malformed JPEG `sensor_msgs/Image` at `ros_helpers.py:300-304` — all confirmed.

## Key findings

1. **Unrealistic success criterion.** `PLAN:55-59` (≥9 Hz for all streams) is unrealistic for default RAW over WiFi. `publish_all_images.yaml:3-24` enables 14 streams @10 Hz; research estimate (`research:21-22`) implies raw bandwidth far beyond WiFi before DDS/rosbag overhead. Success criteria must be bandwidth-aware.

2. **Biggest missed architectural issue — shared request map.** `self.image_requests` is shared by periodic publish (`image_server.py:145`), `GetImages` service (`:177-185`), and static-TF fetch (`:215`), built at `:75-81`. Do **not** mutate it to JPEG. **Split periodic-publish requests from service/static-TF RAW requests first** — this is a prerequisite, not part of Phase 3.

## Answers to the 6 review questions

1. **Batching granularity:** per-rate / *due-source* batching (batch all active *due* sources), not one unconditional all-source batch. Preserves heterogeneous rates from `image_server_parameters.yaml:24-38` while collapsing the all-10 Hz config into one batch.
2. **Phase 2 scheduling:** dedicated acquisition scheduler or a single ROS timer with locked state. Do **not** cancel/recreate rclpy timers from SDK future callbacks — `image_server.py:102-111` + `:145-146` is already concurrency-sensitive.
3. **Compressed vs RAW:** must **coexist**, default RAW. Replacing RAW breaks AprilTag (`spot_apriltag/launch/spot_apriltag.launch.py:38-40`), pointcloud texture (`spot_bringup/launch/camera_pointclouds.launch.py:85-91`), and `spot_utils::CameraClient` (`spot_utils/src/spot_utils/camera_client.cpp:10-12`).
4. **AsyncImageService foundation:** No. Fixed request list, no subscriber gating / rate grouping / transport selection / failure policy (`async_queries.py:119-132`). Don't build Phase 1 on it.
5. **Batching throughput risk:** a slow/failed/oversized source stalls the batch. Check `response.status` per source, publish successful siblings, quarantine repeated failures, consider separate RGB/depth or body/hand failure domains.
6. **Phase reordering (important):** Phase 0 → **JPEG guard + request-map split** → **compressed RGB transport** → **batching** → deadline scheduling → worker queue / executor tuning. Current 0→1→2→3→4 optimizes scheduling before cutting the payload that causes the cliff.

## Additional risks to capture

- Compressed subscriber gating must include `/image/compressed`.
- `hand_tof` must not blindly use RGB JPEG (`image_server.py:120-128`, `:92-94`).
- Depth stays RAW and may still dominate bandwidth even after RGB JPEG.
- `getImageMsg` should **reject** unsupported formats, not return partial messages.
- Queue limits must be **byte-aware**, not message-count based.
