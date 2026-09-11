"""ROS 2 image topic → LiveKit frame source (physical robots).

Subscribes to a `sensor_msgs/msg/Image` topic (default
`/camera/color/image_raw`), converts each frame to RGB, and exposes the same
async `frames(stop)` contract that `LiveKitPublisher` already consumes for the
Isaac sim. This is what makes the ROSMASTER M3 (or any ROS 2 robot) appear as a
video publisher in the OSCAR fleet — identical transport, different source.

Design notes:
- rclpy spins in a background thread; the async publisher loop forwards each
  newest frame at most once. Slow encoders therefore cannot build a stale queue,
  and a 10 fps camera is not pointlessly submitted as 15 duplicate frames/s.
- No cv_bridge dependency: common encodings (rgb8/bgr8/mono8/rgba8) are decoded
  by hand; anything else falls back to cv2 if present.
- Runs inside the robot's ROS 2 container (which already has rclpy + the camera
  topics); only `livekit` needs to be pip-installed there.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import sys
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger("oscar.ros2_image_source")


def _import_rclpy():
    """Importer rclpy meme si l environnement ROS n a pas ete source.

    L agent est lance par un superviseur dont l environnement n est pas
    garanti : selon le chemin de demarrage, PYTHONPATH peut ne pas contenir
    les paquets ROS, et l import echoue alors avec ModuleNotFoundError. On
    retombe sur les emplacements standards d une installation ROS 2 avant
    d abandonner.
    """
    try:
        import rclpy
        return rclpy
    except ModuleNotFoundError:
        pass

    distro = os.environ.get("ROS_DISTRO", "humble")
    candidats = []
    for racine in (f"/opt/ros/{distro}", "/opt/ros/humble", "/opt/ros/jazzy"):
        candidats += glob.glob(f"{racine}/lib/python3*/site-packages")
        candidats += glob.glob(f"{racine}/local/lib/python3*/dist-packages")
        candidats += glob.glob(f"{racine}/lib/python3*/dist-packages")

    ajoutes = []
    for chemin in candidats:
        if os.path.isdir(chemin) and chemin not in sys.path:
            sys.path.append(chemin)
            ajoutes.append(chemin)

    try:
        import rclpy
        log.warning(
            "rclpy importe via un chemin de secours (ROS non source au lancement) : %s",
            ", ".join(ajoutes) or "aucun ajout",
        )
        return rclpy
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "rclpy introuvable. Lancer l agent avec l environnement ROS source "
            "(source /opt/ros/humble/setup.bash), ou verifier l installation ROS 2. "
            f"Chemins essayes : {candidats}"
        ) from exc


class Ros2ImageSource:
    """Latest-frame ROS 2 image subscriber, published to LiveKit as RGB24."""

    def __init__(
        self,
        topic: str = "/camera/color/image_raw",
        width: int = 640,
        height: int = 480,
        fps: int = 10,
        rotate_180: bool = False,
        node_name: str = "oscar_ros2_image_source",
    ):
        rclpy = _import_rclpy()
        from rclpy.qos import (
            QoSDurabilityPolicy,
            QoSHistoryPolicy,
            QoSProfile,
            QoSReliabilityPolicy,
        )
        from sensor_msgs.msg import Image

        self.width = width
        self.height = height
        self.fps = fps
        self.rotate_180 = rotate_180
        self._topic = topic
        self._rclpy = rclpy
        self._latest: Optional[np.ndarray] = None
        self._latest_seq = 0
        self._lock = threading.Lock()
        self._frames_in = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._frame_event: Optional[asyncio.Event] = None

        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node(node_name)
        # Teleoperation must favor freshness over completeness. A normal sensor
        # profile keeps five frames; at 10 fps that can become 500 ms of stale
        # video when the Nano is busy. Depth 1 drops superseded frames instead.
        teleop_qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        self._sub = self._node.create_subscription(
            Image, topic, self._on_image, teleop_qos
        )
        self._spin = threading.Thread(target=self._spin_loop, daemon=True)
        self._spin.start()
        log.info("Subscribed to %s → publishing %dx%d @ %d fps", topic, width, height, fps)

    def _spin_loop(self) -> None:
        try:
            self._rclpy.spin(self._node)
        except Exception as exc:  # noqa: BLE001
            log.warning("rclpy spin stopped: %s", exc)

    def _on_image(self, msg) -> None:  # noqa: ANN001
        rgb = self._to_rgb(msg)
        if rgb is not None:
            with self._lock:
                self._latest = rgb
                self._latest_seq += 1
            self._frames_in += 1
            if self._loop is not None and self._frame_event is not None:
                self._loop.call_soon_threadsafe(self._frame_event.set)

    def _to_rgb(self, msg) -> Optional[np.ndarray]:  # noqa: ANN001
        h, w, enc = msg.height, msg.width, msg.encoding
        raw = np.frombuffer(msg.data, dtype=np.uint8)
        try:
            if enc == "rgb8":
                rgb = raw.reshape(h, w, 3)
            elif enc == "bgr8":
                rgb = raw.reshape(h, w, 3)[:, :, ::-1]
            elif enc == "rgba8":
                rgb = raw.reshape(h, w, 4)[:, :, :3]
            elif enc == "bgra8":
                b = raw.reshape(h, w, 4)
                rgb = b[:, :, [2, 1, 0]]
            elif enc == "mono8":
                g = raw.reshape(h, w)
                rgb = np.dstack([g, g, g])
            else:
                import cv2  # last-resort decode for exotic encodings
                bgr = raw.reshape(h, w, -1)
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not decode image (encoding=%s): %s", enc, exc)
            return None

        if (w, h) != (self.width, self.height):
            import cv2
            rgb = cv2.resize(rgb, (self.width, self.height), interpolation=cv2.INTER_AREA)
        if self.rotate_180:
            rgb = rgb[::-1, ::-1]
        return np.ascontiguousarray(rgb, dtype=np.uint8)

    async def frames(self, stop: asyncio.Event):
        """Yield only fresh RGB frames, capped at `fps`, until `stop` is set."""
        period = 1.0 / max(1, self.fps)
        blank = np.zeros((self.height, self.width, 3), np.uint8)
        self._loop = asyncio.get_running_loop()
        self._frame_event = asyncio.Event()
        last_seq = -1
        next_allowed = 0.0
        warned_no_frame = False

        while not stop.is_set():
            self._frame_event.clear()
            with self._lock:
                rgb = self._latest
                seq = self._latest_seq

            if seq == last_seq:
                try:
                    await asyncio.wait_for(self._frame_event.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    pass
                continue

            now = time.monotonic()
            if now < next_allowed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=next_allowed - now)
                    return
                except asyncio.TimeoutError:
                    pass
                # Keep only the newest frame that arrived while rate-limiting.
                with self._lock:
                    rgb = self._latest
                    seq = self._latest_seq

            if rgb is None:
                if not warned_no_frame:
                    log.info("Waiting for first frame on %s ...", self._topic)
                    warned_no_frame = True
                yield blank
            else:
                yield rgb

            last_seq = seq
            next_allowed = time.monotonic() + period

    async def aclose(self) -> None:
        try:
            self._node.destroy_node()
        except Exception:  # noqa: BLE001
            pass
        self._loop = None
        self._frame_event = None
        log.info("Ros2ImageSource closed (received %d frames)", self._frames_in)
