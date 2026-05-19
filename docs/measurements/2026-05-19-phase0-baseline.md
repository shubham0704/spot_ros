# Phase 0 baseline — on-robot measurement (2026-05-19)

> ⚠️ **Re-measure required after the `origin/devel` merge.** All numbers below
> were captured on **BEST_EFFORT** image QoS. devel commit `6e0b838` changes
> image/compressed/info publishers to **RELIABLE, KEEP_LAST depth=1**. RELIABLE
> delivery over a saturated WiFi link can itself change latency/throughput
> (possibly improve subscriber compatibility, possibly add backpressure). The
> single-stream and all-camera baselines, and the Phase 2 success targets,
> must be **re-validated on the merged branch** before drawing conclusions.

Captured on the real robot with `SPOT_IMAGE_SERVER_FPS_DEBUG=1` (branch
`fix/camera-fps-rosbag-10hz` @ `b31edc1`, timestamp-race fix included → latency
numbers authoritative). Resolves the PLAN's deferred Phase 2-vs-3 decision.

## Raw

Single active stream: `hand_color_image` (hand RGB). Configured ~10 Hz.

| Window | Achieved Hz | Lat avg (ms) | Lat max (ms) | MB/s |
|--------|-------------|--------------|--------------|------|
| 1 (startup) | 1.0 | 81 | 115 | 0.9 |
| 2 | 7.3 | 73 | 122 | 6.7 |
| 3 | 7.4 | 81 | 131 | 6.8 |
| 4 | 7.5 | 72 | 112 | 6.9 |
| 5 | 7.5 | 77 | 120 | 6.9 |
| 6 | 7.5 | 71 | 125 | 6.9 |
| 7 | 7.6 | 72 | 131 | 7.0 |
| 8 | 7.4 | 68 | 113 | 6.8 |

Steady state: **~7.5 Hz vs 10 Hz target**, latency avg ~72–81 ms / **max
~112–131 ms**, **~6.9 MB/s for one RGB stream**. (Window 1 is startup warmup —
excluded.)

## Interpretation

- **Quantization cliff confirmed on hardware.** Avg latency < 100 ms but max
  consistently > 100 ms. Per the gate model, frames < 100 ms run at 10 Hz,
  frames 100–200 ms get pushed a tick → 5 Hz; the ~60/40 blend ≈ 7.5 Hz,
  matching `fps ≈ 1/(ceil(latency/0.1s)·0.1s)`.
- **Single stream is latency/variance-bound**, not bandwidth-bound (6.9 MB/s
  alone doesn't saturate WiFi). Even ONE camera cannot hold 10 Hz.
- **All-camera projection:** ~14 streams × ~7 MB/s ≈ 50–100 MB/s ⇒ the real
  rosbag scenario will additionally be hard **bandwidth-bound**.

## Decision (closed)

Phase 2 (JPEG/`CompressedImage`) **first** — it is the only change that fixes
both the latency cliff (≈10–20× smaller RGB ⇒ latency ≪ 100 ms) and the
projected bandwidth wall. Phase 3 (batching) does nothing for the measured
single-stream cliff (1 stream = 1 RPC); it remains the multi-stream
RPC-fan-out fix and follows. Matches Codex's recommendation, now data-backed.

## All-camera run (captured 2026-05-19, same branch)

Multiple cameras enabled. Representative steady-state windows:

| Active streams | Per-stream Hz | Lat avg (ms) | Lat max (ms) | **Total MB/s** |
|---|---|---|---|---|
| 2 | ~2.3–3.0 | ~280–365 | ~360–520 | **~5.0–5.5** |
| 3 | ~0.6–3.3 | ~240–300 | ~280–386 | **~5.7–5.9** |
| 2 (steady) | ~3.0–3.2 | ~240–300 | ~290–460 | **~5.6–6.0** |

(The first `53.9s / 0.0 MB/s / 21 ms` line is a stale startup straggler — the
accepted Codex "Low"; harmless, windows normalize after.)

### Interpretation — hard bandwidth ceiling

- **Aggregate throughput is capped at ~5.5–6.0 MB/s regardless of stream
  count.** More cameras do *not* add throughput — the same ~6 MB/s is split
  across them, so each collapses to ~2.5–3.2 Hz. Classic saturation signature.
- Latency inflates ~4× under contention (~290 ms avg vs ~75 ms single-stream)
  → every stream sits far past the 100 ms tick → hard-quantized.
- Only 2–3 of the configured streams are "active" per window (gate +
  subscriber churn round-robins them); 14 concurrent never happens.
- Effective ceiling ≈ **~6 MB/s aggregate (~48 Mbps)**. RAW 14×10 Hz needs
  ~50–100 MB/s — **~10× over the ceiling**.

### Consequences (locked)

- **Phase 2 (JPEG/compressed) is the ONLY viable fix.** Phase 3 batching alone
  cannot help — you cannot push 50 MB/s through a 6 MB/s pipe by reducing RPC
  count. Phases 4/5 are likely unnecessary once Phase 2 lands.
- **Honest Phase 2 success target:** per-frame RAW ≈ ~0.9 MB. To fit 14
  streams×10 Hz (=140 fps) under ~6 MB/s needs ≤ ~43 KB/frame. JPEG q≤75 on
  Spot fisheye ≈ 30–80 KB → feasible-to-borderline. So the criterion is
  *"compressed brings aggregate under the ~6 MB/s ceiling and per-stream rate
  to ≥ ~8–10 Hz at q≤75, validated on robot"* — NOT a guaranteed flat 10 Hz
  on all 14 until measured. Tune `SPOT_IMAGE_SERVER_JPEG_QUALITY` if needed.

### Two distinct validation cases (Codex Phase 2: low)

Phase 2 compresses **RGB only**; depth stays RAW by design. So the ~6 MB/s
target must be evaluated in two cases, not conflated:

1. **RGB-compressed** (RGB JPEG, depth/rates off or low): the ≤~43 KB/frame /
   ≥~8–10 Hz target above applies directly. This is the Phase 2 success gate.
2. **RGB+depth `publish_all_images.yaml`** (all depth still RAW at 10 Hz):
   depth RAW alone can still saturate the ~6 MB/s pipe regardless of RGB
   compression — the PLAN already flags this. Phase 2 is *not* expected to
   make this case hit 10 Hz; depth-side bandwidth is out of Phase 2 scope
   (future: depth rate limiting / decimation / its own transport).
