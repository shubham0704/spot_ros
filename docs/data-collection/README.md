# Spot+Arm data collection (energy-aware mapping / C-PHAST)

Operator-facing collection workflow for this branch.
Every artifact here is **operational**: enough to run a session, no paper-style
prose. Read the deck once; print the field card; run the pre-flight before
each session.

## Files

| File | Purpose | When to use |
|---|---|---|
| `operator-deck.md` | 10-slide deck explaining the experiment | First-time briefing of an operator |
| `protocol.md` | **Simple per-episode loop** (teleop) | The thing the operator follows for every episode |
| `field-card.md` | One-page during-recording checklist | Open / print at the start of every session (reference) |
| `preflight_check.sh` | Verifies topics, rates, services, disk, env | Run **once at session start** + after any robot/launch change |
| `metadata_template.yaml` | Fillable per-episode metadata | Copy into every episode dir; fill *during* recording, not after |

## Workflow at a glance

1. **Robot prep:** launch `spot_bringup` with the image config you intend to
   use; set `SPOT_IMAGE_SERVER_FPS_DEBUG=1` (always, this session — it
   captures whether each episode was bandwidth-degraded).
2. **Pre-flight:** `bash preflight_check.sh </path/to/bag_root>` — must PASS
   before any real episode. Failures usually mean a topic isn't being
   published or rosbag2 can't write.
3. **Dry-run:** one short episode (`-a`, all topics, 10 s). Inspect with
   `ros2 bag info`. Verify expected topics present at sane Hz. Only then
   start the planned routes.
4. **Per episode:** copy `metadata_template.yaml` into the episode dir, run
   the behavior, stop the bag, fill the metadata **immediately** (don't
   trust memory at the end of the day), paste the `[fps-debug]` window lines
   into the metadata.
5. **Stop conditions** (from field card) trigger a `pause / label /
   restart` — never overwrite a partial bag, mark it `quarantine: yes` in
   metadata so analysis can exclude it.

## Why the fps-debug discipline matters (critical)

This branch measured, on this robot, that with default RAW images and an
active rosbag subscriber the per-camera rate collapses to **~3 Hz** with
**~290 ms latency** at a hard **~6 MB/s aggregate WiFi ceiling**. Recording
*causes* the degradation. Without `fps-debug` per episode you cannot tell a
*behavior* difference from a *bandwidth artifact*, and the dataset becomes
untrustworthy.

If Phase 2 (JPEG/CompressedImage) is enabled
(`SPOT_IMAGE_SERVER_RGB_JPEG=1`), per-stream rate should be much higher and
episodes more comparable — that's the recommended collection mode once Phase
2 is robot-validated. Either way, log the fps-debug summary into the bag's
metadata so analysis can filter degraded episodes.

## Cross-references

- Phase 0 instrumentation (the env var, the windowed summary):
  `../plans/IMPL-spot_ros-camera-fps.md`
- Measured baseline (the ~6 MB/s ceiling): `../measurements/2026-05-19-phase0-baseline.md`
- Codex reviews / safety verdict: `../plans/VALIDATION-spot_ros-camera-fps.md`
