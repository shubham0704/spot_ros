# Phase 0 baseline — on-robot measurement (2026-05-19)

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

## Still-open data (non-blocking)

An all-cameras + `rosbag record` fps-debug window is still wanted to fix the
real bandwidth-saturation number for honest Phase 2 success targets. Phase 2
implementation does not block on it.
