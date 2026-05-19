"""Phase 1 behavior test: getImageMsg rejects bad formats, never emits a
partial/corrupt sensor_msgs/Image, and is unchanged for supported formats.

Uses the real getImageMsg with fake protos. Skips where rclpy/bosdyn/ROS
messages aren't importable (bare CI sandbox); runs in the ROS 2 env.

Plan: docs/plans/PLAN-spot_ros-camera-fps.md (Phase 1).
"""
import types

import pytest

pytest.importorskip("rclpy")
pytest.importorskip("bosdyn")
pytest.importorskip("sensor_msgs")
from bosdyn.api import image_pb2  # noqa: E402
from spot_driver.ros_helpers import (  # noqa: E402
    getImageMsg, UnsupportedImageFormatError)


class _Logger:
    def error(self, *a, **k):
        pass


class _LeaseMgr:
    logger = _Logger()

    @staticmethod
    def robotToLocalTime(_ts):
        return types.SimpleNamespace(seconds=0, nanos=0)


def _data(fmt, pixel_format, rows=2, cols=2, nbytes=12):
    """Minimal ImageResponse stand-in. Empty transform map avoids the
    bosdyn SE3Pose path; only the format dispatch + (on success) intrinsics
    are exercised."""
    intr = types.SimpleNamespace(
        focal_length=types.SimpleNamespace(x=1.0, y=1.0),
        principal_point=types.SimpleNamespace(x=0.0, y=0.0))
    return types.SimpleNamespace(
        source=types.SimpleNamespace(
            name="cam", pinhole=types.SimpleNamespace(intrinsics=intr)),
        shot=types.SimpleNamespace(
            acquisition_time=0,
            frame_name_image_sensor="cam_frame",
            transforms_snapshot=types.SimpleNamespace(
                child_to_parent_edge_map={}),
            image=types.SimpleNamespace(
                format=fmt, pixel_format=pixel_format,
                rows=rows, cols=cols, data=b"\x01" * nbytes)),
    )


def test_jpeg_is_rejected_not_mislabeled():
    """The historical bug: JPEG bytes shipped as an 'rgb8' Image. Must raise."""
    d = _data(image_pb2.Image.FORMAT_JPEG, image_pb2.Image.PIXEL_FORMAT_RGB_U8)
    with pytest.raises(UnsupportedImageFormatError, match="CompressedImage"):
        getImageMsg(d, _LeaseMgr())


def test_raw_with_unhandled_pixel_format_is_rejected():
    d = _data(image_pb2.Image.FORMAT_RAW, 9999)  # no such pixel_format mapping
    with pytest.raises(UnsupportedImageFormatError, match="pixel_format"):
        getImageMsg(d, _LeaseMgr())


def test_unknown_image_format_is_rejected():
    d = _data(9999, image_pb2.Image.PIXEL_FORMAT_RGB_U8)  # bogus .format
    with pytest.raises(UnsupportedImageFormatError, match="unsupported image format"):
        getImageMsg(d, _LeaseMgr())


def test_raw_rgb_u8_still_produces_valid_image():
    """No regression: supported RAW path unchanged (rgb8, step=3*cols)."""
    d = _data(image_pb2.Image.FORMAT_RAW,
              image_pb2.Image.PIXEL_FORMAT_RGB_U8, rows=2, cols=2, nbytes=12)
    img, info, _ = getImageMsg(d, _LeaseMgr())
    assert img.encoding == "rgb8"
    assert img.step == 3 * 2
    assert len(img.data) == 12 and img.height == 2 and img.width == 2
    assert info.width == 2 and info.height == 2


def test_raw_depth_u16_still_produces_valid_image():
    d = _data(image_pb2.Image.FORMAT_RAW,
              image_pb2.Image.PIXEL_FORMAT_DEPTH_U16, rows=2, cols=2, nbytes=8)
    img, _info, _ = getImageMsg(d, _LeaseMgr())
    assert img.encoding == "16UC1"
    assert img.step == 2 * 2
