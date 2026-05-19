"""Phase 2 tests: opt-in RGB JPEG -> sensor_msgs/CompressedImage transport.

Two parts:
- Structural (AST/source) checks that always run: default-OFF safety, hand_tof
  exclusion, service/TF maps untouched, correct message types wired.
- Behavior checks for getCompressedImageMsg (skip without rclpy/bosdyn/sensor).

Plan: docs/plans/PLAN-spot_ros-camera-fps.md (Phase 2).
"""
import pathlib
import types

import pytest

_SRC_DIR = pathlib.Path(__file__).resolve().parents[1] / "spot_driver"
_IMG = (_SRC_DIR / "image_server.py").read_text()
_HLP = (_SRC_DIR / "ros_helpers.py").read_text()


# ---- structural (dependency-free) ----------------------------------------

def test_jpeg_flag_defaults_off():
    # Empty / falsey env must NOT enable JPEG (backward compatible default).
    assert "os.environ.get('SPOT_IMAGE_SERVER_RGB_JPEG', '')" in _IMG
    assert "not in ('', '0', 'false', 'False', 'no', 'off')" in _IMG


def test_hand_tof_excluded_from_jpeg():
    assert "self._rgb_jpeg and image_source != 'hand_tof'" in _IMG


def test_only_publish_rgb_entry_goes_jpeg():
    # JPEG request is built for the rgb publish entry only.
    assert "image_format=image_pb2.Image.FORMAT_JPEG" in _IMG
    # Depth publish + both service entries stay RAW.
    assert "self.publish_requests[depth_source] = build_image_request(depth_source, image_format=image_pb2.Image.FORMAT_RAW)" in _IMG
    assert "self.service_requests[rgb_source] = build_image_request(rgb_source, image_format=image_pb2.Image.FORMAT_RAW" in _IMG
    assert "self.service_requests[depth_source] = build_image_request(depth_source, image_format=image_pb2.Image.FORMAT_RAW)" in _IMG


def test_compressed_camerapub_publishes_compressedimage_not_image():
    assert "self.compressed_pub = parent.create_publisher(CompressedImage, '~/' + namespace + '/image/compressed'" in _IMG
    # When compressed, no raw Image publisher is created.
    assert "self.image_pub = None" in _IMG
    # Compressed path uses the compressed converter.
    assert "getCompressedImageMsg(data, self.lease_manager)" in _IMG


def test_compressed_converter_exists_and_typed():
    assert "def getCompressedImageMsg(" in _HLP
    # Conventional compressed_image_transport format string (Codex P2 medium),
    # NOT a bare "jpeg" which can make republish fall back to bgr8.
    assert 'cimg.format = "rgb8; jpeg compressed bgr8"' in _HLP
    assert "raise UnsupportedImageFormatError(" in _HLP  # rejects non-JPEG


def test_no_direct_image_pub_deref_in_active_paths():
    """Regression for Codex Phase 2 HIGH: image_pub is None in compressed
    mode, so update_image_task / process_data must go through active_pub."""
    assert "@property" in _IMG and "def active_pub(self):" in _IMG
    # The subscriber gate must not dereference .image_pub directly.
    assert ".image_pub.get_subscription_count()" not in _IMG
    assert "cam_pub.active_pub.get_subscription_count()" in _IMG
    assert "img_pub = self.active_pub" in _IMG


def test_startup_warning_names_broken_consumers():
    # JPEG-on must loudly state raw topics vanish and name the consumers.
    assert "image_transport republish compressed raw" in _IMG
    for consumer in ("AprilTag", "camera_pointclouds", "CameraClient"):
        assert consumer in _IMG


def test_jpeg_quality_is_clamped():
    assert "1 <= self._jpeg_quality <= 100" in _IMG
    assert "min(100, max(1, self._jpeg_quality))" in _IMG


# ---- behavior (needs ROS/bosdyn) -----------------------------------------

def _behavior_deps():
    pytest.importorskip("rclpy")
    pytest.importorskip("bosdyn")
    pytest.importorskip("sensor_msgs")


def _data(fmt, nbytes=64):
    intr = types.SimpleNamespace(
        focal_length=types.SimpleNamespace(x=1.0, y=1.0),
        principal_point=types.SimpleNamespace(x=0.0, y=0.0))
    return types.SimpleNamespace(
        source=types.SimpleNamespace(
            name="hand_color_image",
            pinhole=types.SimpleNamespace(intrinsics=intr)),
        shot=types.SimpleNamespace(
            acquisition_time=0, frame_name_image_sensor="cam",
            transforms_snapshot=types.SimpleNamespace(child_to_parent_edge_map={}),
            image=types.SimpleNamespace(format=fmt, rows=8, cols=8,
                                        data=b"\xff\xd8\xff" + b"\x00" * nbytes)),
    )


class _LeaseMgr:
    logger = types.SimpleNamespace(error=lambda *a, **k: None)

    @staticmethod
    def robotToLocalTime(_ts):
        return types.SimpleNamespace(seconds=0, nanos=0)


def test_getCompressedImageMsg_wraps_jpeg_bytes():
    _behavior_deps()
    from bosdyn.api import image_pb2
    from spot_driver.ros_helpers import getCompressedImageMsg
    cimg, info, _tf = getCompressedImageMsg(_data(image_pb2.Image.FORMAT_JPEG), _LeaseMgr())
    assert cimg.format == "jpeg"
    assert bytes(cimg.data).startswith(b"\xff\xd8\xff")  # JPEG SOI, passed through
    assert info.width == 8 and info.height == 8           # intrinsics still set


def test_getCompressedImageMsg_rejects_non_jpeg():
    _behavior_deps()
    from bosdyn.api import image_pb2
    from spot_driver.ros_helpers import getCompressedImageMsg, UnsupportedImageFormatError
    with pytest.raises(UnsupportedImageFormatError):
        getCompressedImageMsg(_data(image_pb2.Image.FORMAT_RAW), _LeaseMgr())
