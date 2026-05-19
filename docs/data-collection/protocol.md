# Simple per-episode protocol  (teleop)

The during-recording loop. For *why* and full context see `operator-deck.md`;
for safety/stop conditions see `field-card.md`.

---

## Once per session  (4 commands)

```bash
# 1. env
export SPOT_IMAGE_SERVER_FPS_DEBUG=1                 # MANDATORY
export SPOT_IMAGE_SERVER_RGB_JPEG=1                  # use Phase 2 (comparable episodes)
export SPOT_IMAGE_SERVER_JPEG_QUALITY=75

# 2. launch
ros2 launch spot_bringup bringup.launch.py hostname:=<ROBOT_IP> \
     image_config:=publish_all_images.yaml

# 3. pre-flight (must PASS)
bash docs/data-collection/preflight_check.sh ./bags

# 4. one-time dry run (10 s, all topics) — confirm bag is healthy
ros2 bag record -a -o bags/_dryrun_$(date +%H%M%S)
# Ctrl-C after 10 s, then:  ros2 bag info bags/_dryrun_*
```

If any step fails → fix before any real episode. The dry-run is non-negotiable.

---

## Per episode (the loop)

For **each** `(route, behavior, repeat)` triple:

```
1. POSITION
   Teleop Spot to the route start marker. Match the marker pose exactly.

2. NAME
   EP="bags/<route_id>/<behavior>/rep_<NN>"     # e.g. bags/route_A_corridor/static_arm_scan/rep_01
   mkdir -p "$EP"

3. RECORD (curated topics — use the command preflight_check.sh printed)
   ros2 bag record --storage mcap -o "$EP" <curated_topic_list>
   # Leave running in its own terminal.

4. RUN the behavior  (one primitive, see deck §4-7)
   - base_slow / base_normal / base_fast : drive route at the speed, arm fixed.
   - static_arm_scan : base still; 5 poses ~2s each — center-mid, left-mid,
                       right-mid, center-low, center-high. Same order every time.
   - base_plus_arm_scan : slow base + arm sweep, safe routes only.
   - base_yaw_scan : rotate in place 90/180/360°, arm fixed.

5. STOP the bag  (Ctrl-C — NEVER overwrite a previous rep)

6. METADATA
   cp docs/data-collection/metadata_template.yaml "$EP/metadata.yaml"
   # Fill it NOW (not at end of day). The required-non-skippable field is:
   #   fps_debug_summary: |
   #     # paste 2-3 windows from the spot_image_server log, e.g.
   #     # [fps-debug] 5.0s window | 5.7 MB/s total across 6 active stream(s)
   #     #   hand_color_image      9.8 Hz | lat avg 60 ms max 95 ms | 0.7 MB/s
   #     ...
```

Repeat 1–6 for each variation. Plan **2–3 reps per (route × behavior)** at
minimum; more for `static_arm_scan` (it's the cleanest signal).

---

## STOP conditions  (stop the bag, do not overwrite)

- 🛑 human enters Spot's close zone
- 🛑 arm approaches shelf/wall unexpectedly
- 🛑 foot slip / unstable contact
- 🛑 SLAM/map output visibly broken
- 🛑 you feel uncertain

After a stop: keep the partial bag, set `quarantine: yes` in its
`metadata.yaml`, note cause in `known_anomalies`, advance to `rep_<NN+1>`.

---

## End of session

```bash
df -h ./bags                                   # check disk
find bags -name "metadata.yaml" -newer ...     # confirm every episode has metadata
tar/rsync bags/ to lab storage
```
Done. Send the dataset path + the per-episode `fps_debug_summary` rollup back.
