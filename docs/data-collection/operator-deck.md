# Operator deck — Spot+Arm episode collection

Energy-aware mapping data for C-PHAST. **One operator goal:** for each route,
run Spot with different motion styles so we can later compare mapping
quality vs physical cost from comparable starting states. You do not need to
understand C-PHAST. You need to follow these slides.

---

## Slide 1 — Why we are collecting

- Same lab, same robot, **different motion choices** per route.
- We compare four signals across choices: **map gain · energy · stability · safety**.
- No autonomy in Phase 1 — you teleop or scripted-replay each behavior.
- The dataset is only as good as its **metadata** and its **per-episode camera-rate log**. Both are required.

---

## Slide 2 — What counts as one episode

> One episode = **one route + one behavior primitive + one rosbag**.

Naming (this is the bag directory):
```
bags/<route_id>/<behavior>/rep_<NN>/
   ├── *.mcap (or *.db3 + metadata.yaml)   # the bag
   └── metadata.yaml                       # filled per episode (template provided)
```
Examples:
```
bags/route_A_corridor/base_slow/rep_01/
bags/route_A_corridor/base_fast/rep_01/
bags/route_A_corridor/static_arm_scan/rep_01/
bags/route_A_corridor/base_plus_arm_scan/rep_01/
```

---

## Slide 3 — Routes (pick 3–5 families)

| Family | What it tests |
|---|---|
| `route_A_corridor` open | clean baseline mapping |
| `route_B_cluttered` aisle | obstacles, shelves |
| `route_C_doorway` narrow | stability + visibility constraint |
| `route_D_corner_table` | viewpoint planning |
| `route_E_lowtexture` | mapping degradation case |

Mark physical start/stop markers on the floor so every repeat starts from
the same pose. Photograph the floorplan with the markers and store as
`bags/<route_id>/route_map.jpg`.

---

## Slide 4 — Behavior: `base_slow` / `base_normal` / `base_fast`

Run the route at three speeds. Arm and camera **fixed**. 2–3 reps each.

> ⚠️ `base_fast` is the **worst case** for the current camera pipeline
> (high-motion + low frame rate under recording load → motion blur,
> temporally misaligned map data). Treat these episodes as the most likely
> to be artifact-degraded; the per-episode `fps-debug` log will tell you
> which ones to keep.

---

## Slide 5 — Behavior: `static_arm_scan`  *(cleanest data)*

Base stationary at a waypoint. Sweep the arm/camera through 5 poses, pausing
~2 s at each:

1. center-mid  →  2. left-mid  →  3. right-mid  →  4. center-low  →  5. center-high

This is the **highest-confidence** primitive: the base is still and 2 s
pauses let even a 3 Hz camera capture sharp frames. Always use the same
5-pose order, same dwell time.

---

## Slide 6 — Behavior: `base_plus_arm_scan`

Slow base motion **while** the arm sweeps. Only on safe (open) routes
first. Tests whether richer coverage justifies higher coordination cost.
Keep base speed low; avoid near-human / near-obstacle arm motion.

---

## Slide 7 — Behavior: `base_yaw_scan` (rotate-at-waypoint)

Spot stands at a waypoint and rotates in place (90 / 180 / 360°), arm
fixed. **Why this exists separately from arm scans:** it changes viewpoint
*without translation* — energy cost is mostly yaw effort, contact
conditions stay simple, and it's the right primitive near corners,
doorways, shelves, and occluded regions where walking forward is risky but
*looking around* is useful. Optionally repeat with arm scanning during rotation
(label as `base_yaw_plus_arm_scan`).

---

## Slide 8 — Safety / stop conditions

Stop recording (`Ctrl-C` the bag, **do not overwrite**) if:
- human enters Spot's close zone,
- arm approaches shelf / wall unexpectedly,
- foot contact looks unstable / slip,
- SLAM / map output is visibly broken,
- you feel uncertain.

After a stop: leave the partial bag in place, set `quarantine: yes` in its
`metadata.yaml`, write the cause in `known_anomalies`, then start a fresh
`rep_<NN+1>`. Never overwrite.

---

## Slide 9 — Per-episode metadata (mandatory)

Copy `metadata_template.yaml` into every episode dir and fill it
**during/right after** recording. Fields that *must* be present:

```
route_id  behavior  repeat_id  speed_level  arm_scan_pattern
operator  date  battery_start  battery_end
image_transport: raw | jpeg          # which Phase 2 mode
jpeg_quality                          # if jpeg
cameras_enabled: [frontleft, ...]
fps_debug_summary: |                  # paste 2-3 representative [fps-debug] windows
  ...
known_anomalies
quarantine: false                     # set true if stop condition triggered
```

The `fps_debug_summary` is what lets us **filter out bandwidth-degraded
episodes** later. Don't skip it.

---

## Slide 10 — The comparison the dataset enables

From a comparable starting state, candidate motion futures:

| candidate | map gain | energy | stability | risk |
|---|---|---|---|---|
| `base_fast` | high coverage | high | lower | higher |
| `base_slow` | lower coverage | low | high | low |
| `static_arm_scan` | high local detail | low base, arm energy | high | low |
| `base_plus_arm_scan` | richest | highest | medium | medium |
| `base_yaw_scan` | viewpoint-diverse | mostly yaw | high | low |

C-PHAST learns to **choose between these** for a given mapping objective.
Your job is to make them comparable.

---

## Recording reference

**Before any episode** — run pre-flight once per session:
```
bash docs/data-collection/preflight_check.sh ./bags
```
Must PASS. If anything FAILs (topic missing, hz too low, no disk, etc.),
fix it before collecting; do not just record over the warning.

**Start a recording (curated topic list — preferred):** use the command the
pre-flight script prints (it builds the right list from discovered topics
and respects whether Phase 2 JPEG is enabled).

**Always set in the launching shell:**
```
export SPOT_IMAGE_SERVER_FPS_DEBUG=1                    # mandatory, every session
export SPOT_IMAGE_SERVER_RGB_JPEG=1                     # recommended (Phase 2)
export SPOT_IMAGE_SERVER_JPEG_QUALITY=75                # optional, default 75
```
The `[fps-debug]` lines from the `spot_image_server` log are what you paste
into each episode's `metadata.yaml`.

**Dry-run requirement:** the *first* bag of a session must be a 10-second
`ros2 bag record -a` quick recording, inspected with `ros2 bag info` to
confirm all expected topics are present at sane rates. Only then start
planned routes. This prevents collecting dozens of unusable bags.
