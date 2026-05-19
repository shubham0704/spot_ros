# Spot+Arm collection — FIELD CARD  (one page, print or open)

> Branch: `fix/camera-fps-rosbag-10hz` · ROS 2 Humble · spot_ros (UTNR)

## Once per session  (do not skip)

```
export SPOT_IMAGE_SERVER_FPS_DEBUG=1              # ALWAYS
export SPOT_IMAGE_SERVER_RGB_JPEG=1               # if Phase 2 validated; else unset
export SPOT_IMAGE_SERVER_JPEG_QUALITY=75          # only if RGB_JPEG=1
ros2 launch spot_bringup bringup.launch.py hostname:=<IP> image_config:=publish_all_images.yaml
bash docs/data-collection/preflight_check.sh ./bags    # MUST PASS
# Dry run: ros2 bag record -a -o bags/_dryrun_$(date +%H%M%S) (10 s) → ros2 bag info → confirm
```

## Per episode

| Step | Action |
|---|---|
| 1 | Drive Spot to the **route start marker**, exact pose |
| 2 | Decide `route_id` / `behavior` / `repeat_id`. Make the bag dir |
| 3 | Start the bag with the **command pre-flight printed** (curated topics) |
| 4 | Run the behavior (see back of card → 5 primitives) |
| 5 | Stop the bag (`Ctrl-C` — do **not** overwrite a previous one) |
| 6 | Copy `metadata_template.yaml` into the episode dir, fill **now** |
| 7 | Paste 2-3 `[fps-debug]` window lines from the node log into `fps_debug_summary` |

## STOP recording immediately if…

- 🛑 human enters Spot's close zone
- 🛑 arm unexpectedly approaches shelf/wall
- 🛑 foot slip / unstable contact
- 🛑 SLAM / map visibly broken
- 🛑 you feel uncertain

Then: leave the partial bag, set `quarantine: yes` in metadata, note the
cause in `known_anomalies`, advance `rep_NN`, **never overwrite**.

---

## The 5 primitives (cheat-sheet)

| Behavior | Base | Arm/cam | Notes |
|---|---|---|---|
| `base_slow / base_normal / base_fast` | drive route at speed | **fixed** | `base_fast` = most artifact-prone |
| `static_arm_scan` *(cleanest)* | **still** at waypoint | 5-pose, ~2 s each: center-mid → left-mid → right-mid → center-low → center-high | always same order, same dwell |
| `base_plus_arm_scan` | **slow** along route | sweep during motion | safe routes only; no near-human arm |
| `base_yaw_scan` | rotate in place 90/180/360° | fixed | corners / doorways / occluded regions |
| `base_yaw_plus_arm_scan` | rotate in place | sweep during rotation | optional, after `base_yaw_scan` works |

Repeats per behavior per route: **2–3** minimum, more for `static_arm_scan`.

## Bag naming  (lock this — analysis depends on it)

```
bags/<route_id>/<behavior>/rep_<NN>/
   route_A_corridor   base_slow              rep_01
   route_A_corridor   static_arm_scan        rep_03
   route_B_cluttered  base_plus_arm_scan     rep_02
```

## Per-episode metadata — required fields

```
route_id, behavior, repeat_id, speed_level, arm_scan_pattern
operator, date, battery_start, battery_end
image_transport: raw|jpeg     jpeg_quality
cameras_enabled
fps_debug_summary: |  (paste log windows here — this is the filter signal)
known_anomalies      quarantine: false|true
```

## Quick sanity (run anytime)

```
ros2 topic list | grep spot_image_server      # cameras visible?
ros2 topic hz /spot_image_server/rgb/<cam>/image     # or .../image/compressed if JPEG
ros2 service call /spot_image_server/list_registered_sources std_srvs/srv/Trigger
ros2 bag info <last_bag>                      # topics, message counts, duration
df -h ./bags                                  # disk
```
