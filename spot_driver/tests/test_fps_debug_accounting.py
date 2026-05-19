"""Phase 0 (camera-FPS) unit tests: the opt-in fps-debug accounting + window.

These exercise the *real* SpotImageServer._fps_record / _fps_new_bucket logic
via a lightweight fake `self` and fake image responses, so no robot, rclpy
spin, or bosdyn connection is needed. If rclpy/bosdyn are not importable
(e.g. a bare CI sandbox), the whole module skips — it is meant to run inside
the ROS 2 / spot_driver environment.

Plan: docs/plans/PLAN-spot_ros-camera-fps.md (Phase 0).
"""
import threading
import types
from collections import defaultdict

import pytest

# Real code under test. Skip (don't fail) where ROS/bosdyn deps are absent.
pytest.importorskip("rclpy")
pytest.importorskip("bosdyn")
from spot_driver.image_server import SpotImageServer  # noqa: E402


class _FakeLogger:
    def __init__(self):
        self.infos = []
        self.warns = []

    def info(self, msg, *a, **k):
        self.infos.append(msg)

    def warn(self, msg, *a, **k):
        self.warns.append(msg)


def _make_self(window_sec):
    """A minimal stand-in carrying exactly the attributes _fps_record touches."""
    s = types.SimpleNamespace()
    s._fps_lock = threading.Lock()
    s._fps_send_times = {}
    s._fps_new_bucket = SpotImageServer._fps_new_bucket
    s._fps_stats = defaultdict(s._fps_new_bucket)
    s._fps_window_sec = window_sec
    s._logger = _FakeLogger()
    s.get_logger = lambda: s._logger
    return s


def _resp(name, nbytes):
    """Fake ImageResponse: only .source.name and .shot.image.data are read."""
    return types.SimpleNamespace(
        source=types.SimpleNamespace(name=name),
        shot=types.SimpleNamespace(
            image=types.SimpleNamespace(data=b"\x00" * nbytes)),
    )


def test_new_bucket_is_fresh_and_independent():
    a = SpotImageServer._fps_new_bucket()
    b = SpotImageServer._fps_new_bucket()
    assert a == {"count": 0, "bytes": 0, "lat_sum": 0.0, "lat_max": 0.0}
    a["count"] += 1
    assert b["count"] == 0  # buckets must not share state


def test_accumulates_within_window_without_logging(monkeypatch):
    """Before the window elapses, stats accumulate and nothing is logged."""
    s = _make_self(window_sec=999.0)
    t = [1000.0]
    monkeypatch.setattr("spot_driver.image_server.time.monotonic", lambda: t[0])

    s._fps_send_times["cam"] = 1000.0
    t[0] = 1000.150  # 150 ms round-trip
    SpotImageServer._fps_record(s, _resp("cam", 1_000_000))

    assert s._logger.infos == []  # window not elapsed -> no summary
    st = s._fps_stats["cam"]
    assert st["count"] == 1
    assert st["bytes"] == 1_000_000
    assert st["lat_max"] == pytest.approx(0.150, abs=1e-6)
    assert "cam" not in s._fps_send_times  # send time consumed


def test_window_flush_emits_summary_and_resets(monkeypatch):
    s = _make_self(window_sec=5.0)
    t = [0.0]
    monkeypatch.setattr("spot_driver.image_server.time.monotonic", lambda: t[0])

    # 10 frames of 'cam' across a 5s window -> expect ~2 Hz, 2 MB/s @1MB each.
    for i in range(10):
        s._fps_send_times["cam"] = t[0]
        t[0] += 0.5
        SpotImageServer._fps_record(s, _resp("cam", 1_000_000))

    assert len(s._logger.infos) == 1, "exactly one summary per elapsed window"
    summary = s._logger.infos[0]
    assert "[fps-debug]" in summary and "cam" in summary
    assert "MB/s total" in summary
    # Window reset: stats cleared after flush.
    assert dict(s._fps_stats) == {}


def test_missing_send_time_skips_latency_but_counts_bytes(monkeypatch):
    s = _make_self(window_sec=999.0)
    monkeypatch.setattr("spot_driver.image_server.time.monotonic", lambda: 42.0)
    SpotImageServer._fps_record(s, _resp("cam", 512))  # no send time recorded
    st = s._fps_stats["cam"]
    assert st["count"] == 1 and st["bytes"] == 512
    assert st["lat_sum"] == 0.0 and st["lat_max"] == 0.0
