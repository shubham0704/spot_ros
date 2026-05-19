# Topics to record  (verified against this branch's source)

Authoritative list extracted from `spot_driver/spot_driver/spot_ros.py`
(node name **`spot_driver`** → topics prefixed `/spot_driver/...`),
`image_server.py` (node **`spot_image_server`**), and the TF broadcasters.
Anything marked CONDITIONAL only appears if the corresponding payload /
launch / SLAM stack is running — `preflight_check.sh` will report whether
each is actually live on the graph.

---

## A. Cameras  (HIGH priority — this is the mapping data)

`<cam>` ∈ `{frontleft, frontright, left, right, back, hand_rgb, hand_tof}`
(the actual source names come from `image_server.py:resolve_source_name`).

**RAW mode** (`SPOT_IMAGE_SERVER_RGB_JPEG` off — default):
```
/spot_image_server/rgb/<cam>/image
/spot_image_server/rgb/<cam>/camera_info
/spot_image_server/depth/<cam>/image
/spot_image_server/depth/<cam>/camera_info
```

**Phase 2 / JPEG mode** (`SPOT_IMAGE_SERVER_RGB_JPEG=1` — recommended):
RGB switches to compressed; depth + camera_info unchanged.
```
/spot_image_server/rgb/<cam>/image/compressed     # <-- replaces the raw /image
/spot_image_server/rgb/<cam>/camera_info
/spot_image_server/depth/<cam>/image
/spot_image_server/depth/<cam>/camera_info
```

> ℹ️ `hand_tof` is excluded from JPEG even when the flag is on (it's ToF /
> depth, not RGB) — it still publishes its raw depth topic normally.

---

## B. Robot state from `spot_driver`  (HIGH priority)

Verified at `spot_driver/spot_driver/spot_ros.py:792-805`. These are the
energy / stability / pose / safety signals.

```
/spot_driver/odometry                       # nav_msgs/Odometry  ← base pose+twist
/spot_driver/odometry/twist                 # TwistWithCovarianceStamped
/spot_driver/joint_states                   # sensor_msgs/JointState  ← effort iff populated
/spot_driver/status/feet                    # FootStateArray  ← contact / slip evidence
/spot_driver/status/battery_states          # BatteryStateArray  ← energy proxy
/spot_driver/status/power_state             # PowerState
/spot_driver/status/estop                   # EStopStateArray
/spot_driver/status/system_faults           # SystemFaultState
/spot_driver/status/behavior_faults         # BehaviorFaultState
/spot_driver/status/mobility_params         # MobilityParams (current locomotion config)
/spot_driver/status/feedback                # Feedback (latched)
/spot_driver/status/dock_state              # latched
/spot_driver/status/wifi                    # latched  ← useful: WiFi quality vs FPS
/spot_driver/status/leases                  # LeaseArray
```

`spot_driver/joint_states` — **verify `effort` is populated** with
`ros2 topic echo /spot_driver/joint_states --once`. If it's empty (common
on Spot), the per-joint physical-cost signal needs another source (motor
current or estimated power); flag in metadata.

---

## C. Teleop command  (HIGH priority — this IS the behavior signal)

`spot_driver` *subscribes* to:
```
/spot_driver/cmd_vel                        # geometry_msgs/Twist  ← what the operator commanded
```
Recording a subscription is valid and captures whatever publisher (joy /
keyboard / external teleop) is sending. C-PHAST needs this aligned with
the resulting motion to learn the policy. **Record it.**

---

## D. Transforms  (HIGH priority)

```
/tf                                         # dynamic transforms
/tf_static                                  # static (incl. camera-frame transforms from spot_image_server)
```

---

## E. Lidar / point clouds  (CONDITIONAL — only if equipped / launched)

EAP2 / Velodyne lidar surfaces via `spot_driver` point cloud publishers
(`spot_ros.py:749`, namespaced under `/spot_driver/`). Exact topic names
depend on the registered point-cloud sources for *your* robot — the
preflight script lists what's actually being published. Typical:
```
/spot_driver/velodyne_points                # PointCloud2  (if EAP2 lidar)
```

Nav filter output (only if `spot_navigation` filter is running):
```
/cloud_out                                  # filtered PointCloud2 (filter_pointcloud.cpp)
```

---

## F. Map / SLAM  (CONDITIONAL — only if a SLAM/Nav2 stack is running)

`spot_ros` itself does **not** publish a map or SLAM pose — those come
from whatever external SLAM you run (Cartographer / SLAM Toolbox / Nav2
AMCL). Names are not stable; discover with `ros2 topic list | grep -Ei "map|slam|amcl|pose"`. Typical:
```
/map  /map_updates  /slam_pose  /amcl_pose  /particle_cloud
```

---

## G. IMU  (NOT published by this driver)

`spot_driver` does **not** publish an IMU topic in this branch (verified
by grep — no `create_publisher(Imu, ...)`). Stability information comes
from `/spot_driver/odometry` twist + `/spot_driver/status/feet`. If you
need raw IMU, source it separately (some Spot integrations expose it
through extra payloads); don't claim an IMU topic that isn't there.

---

## Recording command (curated)

The preflight script prints this filled in for *your* live topic graph.
Template:

```bash
# Replace <ROUTE>/<BEHAVIOR>/rep_<NN> with the actual names.
ros2 bag record \
  --storage mcap \
  -o "bags/<ROUTE>/<BEHAVIOR>/rep_<NN>" \
  \
  /spot_image_server/rgb/{frontleft,frontright,left,right,back,hand_rgb}/image{,/compressed} \
  /spot_image_server/rgb/{frontleft,frontright,left,right,back,hand_rgb}/camera_info \
  /spot_image_server/depth/{frontleft,frontright,left,right,back,hand_rgb,hand_tof}/image \
  /spot_image_server/depth/{frontleft,frontright,left,right,back,hand_rgb,hand_tof}/camera_info \
  \
  /spot_driver/odometry \
  /spot_driver/odometry/twist \
  /spot_driver/joint_states \
  /spot_driver/status/feet \
  /spot_driver/status/battery_states \
  /spot_driver/status/power_state \
  /spot_driver/status/estop \
  /spot_driver/status/system_faults \
  /spot_driver/status/behavior_faults \
  /spot_driver/status/mobility_params \
  /spot_driver/status/feedback \
  /spot_driver/status/wifi \
  \
  /spot_driver/cmd_vel \
  /tf /tf_static
```
(brace-expansion shown for brevity — shell will expand to the explicit list;
verify the resulting list with `ros2 bag info` after the dry-run).

Add point-cloud / SLAM topics only after confirming they're live on the
graph for your robot.

---

## Two things to verify on the robot before bulk collection

1. `ros2 topic echo /spot_driver/joint_states --once` → is the `effort:`
   list populated? If not, the per-joint energy signal is missing — note
   in metadata, and find an alternative (motor current topic if any).
2. `ros2 topic hz /spot_image_server/rgb/<one_cam>/image[/compressed]`
   under your intended record load → confirms per-stream rate isn't
   bandwidth-collapsing (preflight does this; re-check after any topic
   list change).
