# Why Spot's cameras don't hit 10 Hz during rosbag — explained

A teaching document for the lab. Goal: anyone can read this and explain the
problem and the fix on a whiteboard. Each fix is written as if teaching it.

Companion docs: root-cause detail → `docs/research/2026-05-19-camera-fps.md`;
the engineering plan → `docs/plans/PLAN-spot_ros-camera-fps.md`.

---

## 1. The one-sentence version

> We *ask* for 10 Hz, but the code only requests a new image after the previous
> one fully arrives — and big uncompressed images over WiFi take longer than the
> 100 ms budget, so the real rate collapses to 3–5 Hz.

Everything below explains *why* that sentence is true and *how* we fix it.

---

## 2. The mental model people have (and why it's wrong)

When you set `publish_all_images.yaml` to `10.0`, you *think* this happens:

```
  every 100 ms, exactly:        [img][img][img][img][img]  → 10 Hz, guaranteed
```

What the config actually sets is a **timer that fires every 100 ms**. Firing the
timer is not the same as *getting an image*. The timer only gets to *ask*; whether
an image comes back in time is a separate story.

```
   config "10.0"  ─is really─▶  "wake me up every 100 ms and TRY"
                                  (not "deliver a frame every 100 ms")
```

---

## 3. The system, end to end

```
        SPOT ROBOT                  spot_image_server (Python, ROS 2)            CONSUMERS
   ┌───────────────────┐       ┌────────────────────────────────────────┐   ┌───────────────┐
   │   Image Service   │       │  one 100 ms timer  PER camera stream    │   │  rosbag2      │
   │                   │  gRPC │     │                                   │   │  record       │
   │  7 cameras:       │ ◀───▶ │     ▼                                   │   │               │
   │  frontL  frontR   │  WiFi │  update_image_task(source)              │   │  rviz         │
   │  left    right    │       │     │  get_image_async([ONE source])    │──▶│               │
   │  back             │       │     ▼                                   │DDS│  AprilTag     │
   │  hand_rgb hand_tof│       │  callback: getImageMsg() converts       │   │               │
   │                   │       │     │  → publish Image + CameraInfo     │   │  pointcloud   │
   └───────────────────┘       └────────────────────────────────────────┘   └───────────────┘
        FORMAT_RAW: ~3.7 MB per RGB frame, ~2.5 MB per depth frame (uncompressed)
```

Key fact to remember: **RAW = uncompressed = huge**. A single RGB frame is ~3.7 MB.
Seven cameras, RGB + depth, at 10 Hz, is on the order of **hundreds of MB/s** —
already near or past what robot WiFi can carry, before ROS even touches it.

---

## 4. The core bug: the "one request in flight" gate

This is the heart of it. Teach this slide slowly.

The code (`image_server.py:139-146`) says, in plain English:

> "When the timer fires: **only** ask Spot for a new image if the *previous*
>  request for this camera has already come back. Otherwise, do nothing."

There is **no queue** and **no catch-up**. A skipped tick is gone forever.

Now watch what happens when one image takes 250 ms to arrive (normal for RAW
over WiFi), but the timer fires every 100 ms:

```
  timer ticks:   t0────t1────t2────t3────t4────t5────t6────t7   (every 100 ms)

  t0  prev done?  yes → SEND request #1  ──┐
  t1  prev done?  NO  → skip               │ request #1
  t2  prev done?  NO  → skip               │ takes 250 ms
  t3  prev done?  yes → SEND request #2  ──┘◀ arrived ~here
  t4  skip
  t5  skip
  t6  SEND request #3 ...

  Delivered: 1 frame every ~3 ticks  →  ~3.3 Hz, NOT 10 Hz
```

### The cliff (the part that surprises people)

Because requests only restart on a 100 ms tick boundary, the rate doesn't
degrade smoothly — it **falls off a cliff** in 100 ms steps:

```
   per-frame latency        effective rate
   ───────────────────      ──────────────
   ≤ 100 ms          ───▶   10 Hz
   101 – 200 ms      ───▶    5 Hz      ← 1 ms over budget halves the rate
   201 – 300 ms      ───▶    3.3 Hz
   301 – 400 ms      ───▶    2.5 Hz

   formula:  fps ≈ 1 / ( ceil(latency / 0.1s) · 0.1s )
```

So "we're a little over 100 ms" doesn't cost you a little — it **halves** you.

### Why it only shows up during rosbag

The server is lazy: it does **no work for a camera nobody is listening to**
(`image_server.py:142`). Idle, nothing is requested, everything looks fine.
The moment `rosbag record` subscribes to *all* the image topics, all 14 streams
wake up at once and start competing for the same WiFi — and the cliff appears.

```
   before bag:  2 topics watched  → light load → looks ~fine
   during bag: 14 topics watched  → 14 RAW streams contend → rate collapses
```

---

## 5. The amplifier: 140 requests per second

Each camera stream has its **own** timer making its **own** single-camera
request. That is one network round-trip *per camera per tick*:

```
   7 sources × {rgb, depth} × 10 Hz  =  up to 140 gRPC requests / second

   ┌─ get_image_async([frontleft_rgb])    ┐
   ├─ get_image_async([frontleft_depth])  │
   ├─ get_image_async([frontright_rgb])   │   140 separate
   ├─ get_image_async([right_depth])      ├─  round-trips/s,
   ├─ ... (10 more) ...                   │   each with its own overhead
   └─ get_image_async([hand_depth])       ┘

   THE FIX (Phase 3):  batch them
   └─ get_image_async([ all 14 due sources at once ])  ≈ ~10 round-trips/s
```

The robot's SDK *already supports* asking for many images in one request — the
code even does it elsewhere (the `GetImages` service). The periodic publisher
just never used that capability.

---

## 6. The trap Codex caught: the shared request list

There is one Python dictionary, `self.image_requests`, that says "here is how
to ask for each camera." **Three different code paths read it:**

```
                 self.image_requests   (one dict, all FORMAT_RAW)
                          │
        ┌─────────────────┼────────────────────┐
        ▼                 ▼                     ▼
   periodic publish   GetImages service    static-TF fetch
   (:145)             (:177-185)           (:215)
```

The tempting "quick fix" is: *flip this dict to JPEG so images are smaller.*
**That would silently break the other two paths** — the service and the
transform lookup would start getting JPEG when they expect RAW.

> Lesson: before optimizing a shared resource, **split it** so each consumer
> owns its own copy. That is why **Phase 1 is "split the map first"** — a
> prerequisite, not an afterthought.

---

## 7. The landmine: the JPEG path is already broken

You might think "just request JPEG, the code already has a JPEG branch."
It does — and it's wrong (`ros_helpers.py:300-304`):

```
   if image is JPEG:
        encoding = "rgb8"        ← claims: plain raw RGB pixels
        step     = 3 × width     ← claims: 3 bytes per pixel, raw
        data     = <JPEG bytes>  ← reality: a compressed JPEG stream
```

A `sensor_msgs/Image` with encoding `rgb8` is a **contract**: it must contain
exactly `height × 3 × width` raw bytes. Handing it a JPEG bitstream is like
labeling a ZIP file as a plain `.txt` — every reader (rviz, cv_bridge, bag
replay) mis-decodes it.

> The correct way to ship JPEG in ROS is a **different message type**:
> `sensor_msgs/CompressedImage`. That is what **Phase 2** does, and it keeps
> the RAW topics too so AprilTag / pointcloud / the C++ client don't break.

---

## 8. The target system (after the fixes)

```
     SPOT               spot_image_server  (fixed)                     CONSUMERS
  ┌────────┐  gRPC   ┌──────────────────────────────────────────┐  ┌──────────────┐
  │ Image  │ ◀─────▶ │ deadline scheduler:                      │  │ rosbag2      │
  │ Service│ 1 batch │   batch ALL due sources → 1 request      │  │              │
  │        │ ~10/s   │   restart from completion, not next tick │─▶│ /…/image     │
  │ RGB →  │ JPEG    │            │                              │  │   (RAW, dflt)│
  │ Depth→ │ RAW     │            ▼                              │  │ /…/image/    │
  │        │         │  callback → byte-bounded queue           │  │   compressed │
  │        │         │            ▼  (drop oldest on overload)  │  │   (JPEG, opt)│
  │        │         │  worker pool: getImageMsg + publish      │  │              │
  └────────┘         └──────────────────────────────────────────┘  └──────────────┘

  Net effect:  140 RPC/s → ~10 RPC/s;  no 100 ms cliff;  RGB payload ~10–20× smaller;
               honest rate that matches measured WiFi bandwidth.
```

---

## 9. The fix plan, taught one phase at a time

Think of it as: **measure → make it safe → shrink the data → send smarter →
stop the cliff → parallelize**. Order matters: you can't out-schedule a
network that physically can't carry the bytes, so we shrink the data *before*
we optimize scheduling.

**Phase 0 — Measure first (no behavior change).**
*"Never optimize what you haven't measured."* We add opt-in logging of how long
each request really takes and how many MB/s we're pushing. This tells us whether
we're latency-bound or flat-out bandwidth-bound — which decides everything after.

**Phase 1 — Make the change safe (split the shared list; guard the JPEG path).**
*"Before you touch a shared thing, give each user their own."* Split the request
dictionary so changing the publisher can't break the service or TF. Make the
image converter **refuse** malformed inputs instead of emitting a corrupt frame.

**Phase 2 — Shrink the data (proper compressed RGB).**
*"The cheapest byte is the one you never send."* Optionally request JPEG for RGB
and publish it as a *proper* `CompressedImage` on a new topic — **next to** the
RAW topic, not replacing it, so nothing downstream breaks. Depth stays RAW.

**Phase 3 — Send smarter (one batched request, not 140).**
*"One trip to the store with a list beats 14 trips for one item each."* Replace
14 single-camera requests per tick with one request for all due cameras. If one
camera fails, still publish the others — don't let one bad sensor stall the bag.

**Phase 4 — Kill the cliff (deadline scheduling).**
*"Don't wait for the next clock tick if you're already late."* Start the next
batch the moment the last one finishes (respecting the deadline), instead of
waiting for the next 100 ms boundary. At most one batch in flight.

**Phase 5 — Parallelize the conversion (decouple + tune).**
*"Don't let the slow chore block the fast one."* Hand finished responses to a
worker pool for the CPU-heavy conversion via a size-bounded queue (drop the
oldest frame under overload). Tune thread count *last*, once it can actually help.

---

## 10. The thirty-second whiteboard script

1. "10 Hz is a *timer*, not a *guarantee*."
2. "Code won't ask for the next image until the last one fully arrives — no queue."
3. "RAW images are ~3.7 MB; over WiFi that's >100 ms, so the rate halves — a cliff."
4. "Only shows up during bagging because that's when all 14 streams turn on at once."
5. "Fix: shrink the images (proper JPEG/CompressedImage), ask for all at once
    (batch), and don't wait for the next tick (deadline) — but measure first."

---

*Provenance: root cause from independent Claude + Codex analysis; the shared-map
trap, the broken-JPEG landmine, and the measure-first ordering were Codex's
review contributions. See `docs/plans/FEEDBACK-spot_ros-camera-fps.md`.*
