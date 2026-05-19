"""Phase 1 structural test: the shared image-request map is split per consumer.

Pure source/AST analysis — no rclpy/bosdyn/robot needed, so it always runs
(in CI sandboxes too). Guards the Phase 1 invariant that periodic publishing
and the GetImages/static-TF/listing paths use *separate* request maps, so a
later Phase 2 JPEG retarget of the publish map cannot leak into the service
or TF paths (which must stay FORMAT_RAW).

Plan: docs/plans/PLAN-spot_ros-camera-fps.md (Phase 1).
"""
import pathlib
import re

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "spot_driver" / "image_server.py").read_text()


def test_old_shared_map_is_gone():
    assert "self.image_requests" not in _SRC, (
        "self.image_requests must be fully replaced by the split maps")


def test_both_split_maps_are_declared_and_built():
    assert "self.publish_requests: dict" in _SRC
    assert "self.service_requests: dict" in _SRC
    # Each map is populated for both rgb and depth sources.
    assert "self.publish_requests[rgb_source]" in _SRC
    assert "self.publish_requests[depth_source]" in _SRC
    assert "self.service_requests[rgb_source]" in _SRC
    assert "self.service_requests[depth_source]" in _SRC


def test_periodic_publish_uses_publish_map_only():
    # The async periodic request must read publish_requests, never service_requests.
    m = re.search(r"get_image_async\(\[self\.(\w+)\[source_name\]\]\)", _SRC)
    assert m and m.group(1) == "publish_requests", (
        "update_image_task must request from publish_requests")


def test_service_and_tf_paths_use_service_map():
    # GetImages service fetch + validation, static-TF fetch, source listing.
    assert "[self.service_requests[source] for source in req.sources]" in _SRC
    assert "source not in self.service_requests.keys()" in _SRC
    assert "list(self.service_requests.values())" in _SRC          # static-TF
    assert "for name in self.service_requests.keys()" in _SRC       # listing
    # And those paths must NOT read the publish map.
    assert "publish_requests[source]" not in _SRC
    assert "list(self.publish_requests.values())" not in _SRC


def test_service_requests_are_built_raw():
    # The service/TF entries are explicitly FORMAT_RAW (must not change later).
    blk = _SRC.split("self.service_requests[rgb_source]")[1].split("\n")[0]
    assert "FORMAT_RAW" in blk
