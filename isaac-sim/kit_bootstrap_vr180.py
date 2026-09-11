"""OSCAR bootstrap VR180 — paste once in Window → Script Editor → Run.

Full pipeline in one paste:
  • media    : stereo FISHEYE 180° per eye (VR180-style), track `camera-vr180`
  • commands : Quest mapping + safeties → ROS 2 /cmd_vel   (unchanged)
  • gait     : g1_locomotion consuming /cmd_vel            (unchanged)

The frozen pinhole pipeline stays untouched on disk; this file only ADDS a
fisheye variant. Rollback = stop_oscar_media_publisher_vr180() then run the
frozen kit_bootstrap_command.py (or kit_bootstrap_ros2.py for pinhole+ROS).

Design (NimbRo / ANA Avatar XPRIZE pattern): two wide-FOV cameras at human
IPD, each eye rendered on a spherical cap in the headset. Head rotation is
resolved locally against the wide captured field, so network latency never
fights the vestibular system.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

SIM_DIR = "/root/Documents/sim"
VENDOR_DIR = f"{SIM_DIR}/vendor"
if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)
# Keep Kit's bundled numpy/protobuf ahead of optional OSCAR wheels. The vendor
# folder supplies LiveKit and ONNX Runtime without replacing Isaac's ABI pins.
if VENDOR_DIR not in sys.path:
    sys.path.append(VENDOR_DIR)

import numpy as np  # noqa: E402

from livekit_publisher import LiveKitPublisher, PublisherConfig  # noqa: E402
from frame_sources import IsaacStereoSideBySideSource  # noqa: E402

log = logging.getLogger("oscar.vr180")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

# ─── Tunables ───────────────────────────────────────────────────────────────
FOV_DEG = 180.0          # realistic market-available VR180 fisheye per eye
PER_EYE = 1024           # square per-eye resolution (packed: 2048×1024)
FPS = 30
TRACK_NAME = "camera-vr180"
TOKEN_FILE = "/root/Documents/livekit-isaac-publisher.json"
LEFT_PRIM = "/World/g1/torso_link/stereo_rig/robot_camera_left"
RIGHT_PRIM = "/World/g1/torso_link/stereo_rig/robot_camera_right"
DEBUG_PNG = "/root/Documents/oscar_vr180_check.png"

# Control modes:
#   xform      = fallback POC: move the complete /World/g1 root from Quest input
#   ros-log    = publish /cmd_vel and verify ROS, without moving joints
#   ros-policy = drive the 12 G1 leg joints with Unitree's official policy
CONTROL_MODE = os.getenv("OSCAR_CONTROL_MODE", "ros-policy").strip().lower()
G1_POLICY_PATH = os.getenv(
    "OSCAR_G1_POLICY_PATH",
    "/root/Documents/policies/unitree_g1_29dof_velocity_v0.onnx",
)
VALID_CONTROL_MODES = {"xform", "ros-log", "ros-policy"}


def _validate_control_mode() -> str:
    if CONTROL_MODE not in VALID_CONTROL_MODES:
        raise ValueError(
            f"Unknown OSCAR_CONTROL_MODE={CONTROL_MODE!r}; expected one of "
            f"{sorted(VALID_CONTROL_MODES)}"
        )
    if CONTROL_MODE == "ros-policy":
        if not Path(G1_POLICY_PATH).is_file():
            raise FileNotFoundError("Missing G1 policy file: " + G1_POLICY_PATH)
    return CONTROL_MODE


class VR180PublisherConfig(PublisherConfig):
    """Same transport, richer metadata: projection=fisheye + fovDeg."""

    @property
    def metadata_json(self) -> str:  # type: ignore[override]
        return json.dumps(
            {
                "projection": "fisheye",
                "layout": self.layout,
                "stereo": "left-right",
                "depth": "none",
                "source": self.source_label,
                "fovDeg": FOV_DEG,
                "frame": {"width": self.width, "height": self.height, "fps": self.fps},
            },
            separators=(",", ":"),
        )


class IsaacFisheyeStereoSource(IsaacStereoSideBySideSource):
    """The frozen stereo source with both cameras switched to equidistant
    fisheye. Reuses the existing rig prims — no USD file modification."""

    def __init__(self, fov_deg: float = FOV_DEG, debug_png: Optional[str] = DEBUG_PNG, **kwargs: Any):
        super().__init__(**kwargs)
        self._debug_png = debug_png
        self._debug_saved = False
        for label, cam in (("left", self._left), ("right", self._right)):
            self._make_fisheye(cam, fov_deg, label)

    @staticmethod
    def _make_fisheye(cam, fov_deg: float, label: str) -> None:
        """Isaac Sim 5.0 lens API: OpenCV fisheye with k1..k4 = 0 is a pure
        equidistant model (r = f·θ). f chosen so the image half-width spans
        exactly fov/2: f_px = (W/2) / θmax."""
        import math

        w = float(cam.get_resolution()[0]) if hasattr(cam, "get_resolution") else float(PER_EYE)
        theta_max = math.radians(fov_deg / 2.0)
        f_px = (w / 2.0) / theta_max
        cam.set_opencv_fisheye_properties(
            cx=w / 2.0,
            cy=w / 2.0,
            fx=f_px,
            fy=f_px,
            fisheye=[0.0, 0.0, 0.0, 0.0],
        )
        # The helper does NOT set imageSize; the schema default is (2048,1024),
        # which silently rescales cx/fx when rendering square eyes. Set it to
        # the actual render size or the circle lands off-centre and shrunken.
        from pxr import Gf

        cam.prim.GetAttribute("omni:lensdistortion:opencvFisheye:imageSize").Set(
            Gf.Vec2i(int(w), int(w))
        )
        log.info(
            "%s camera → opencvFisheye equidistant (%.0f°/eye, f=%.1fpx)",
            label, fov_deg, f_px,
        )

    _frames_seen = 0

    async def _produce(self) -> np.ndarray:
        frame = await super()._produce()
        self._frames_seen += 1
        # Save frame #30 (~1 s in) so the renderer has warmed up, even if the
        # image is black — a black PNG is itself a diagnostic.
        if not self._debug_saved and self._debug_png is not None and self._frames_seen >= 30:
            try:
                import cv2

                cv2.imwrite(self._debug_png, cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR))
                log.info(
                    "Saved VR180 check image → %s (mean brightness %.1f)",
                    self._debug_png, float(frame[..., :3].mean()),
                )
                self._debug_saved = True
            except Exception as exc:  # noqa: BLE001
                log.warning("debug png failed: %s", exc)
        return frame


_state: dict[str, Any] = {"task": None, "stop": None}


def start_oscar_media_publisher_vr180(**overrides: Any) -> asyncio.Task:
    if _state.get("task") and not _state["task"].done():
        log.warning("VR180 publisher already running")
        return _state["task"]

    with open(TOKEN_FILE) as fh:
        lk = json.load(fh)["livekit"]

    cfg = VR180PublisherConfig(
        url=lk["serverUrl"],
        token=lk["token"],
        identity=lk.get("identity", "robot-oscar-02"),
        track_name=TRACK_NAME,
        width=PER_EYE * 2,
        height=PER_EYE,
        fps=FPS,
        projection="fisheye",
        layout="stereo-left-right",
        source_label="isaac-sim",
    )

    async def _run() -> None:
        publisher = LiveKitPublisher(cfg)
        source = IsaacFisheyeStereoSource(
            fov_deg=overrides.get("fov_deg", FOV_DEG),
            left_prim_path=LEFT_PRIM,
            right_prim_path=RIGHT_PRIM,
            per_eye_width=PER_EYE,
            per_eye_height=PER_EYE,
            fps=FPS,
        )
        await publisher.connect()
        stop = asyncio.Event()
        _state["stop"] = stop
        log.info("VR180 loop start — %dx%d packed fisheye %d° @ %d fps", PER_EYE * 2, PER_EYE, FOV_DEG, FPS)
        try:
            async for frame in source.frames(stop):
                publisher.push_frame(frame)
        finally:
            await source.aclose()
            await publisher.aclose()
            log.info("VR180 publisher stopped.")

    task = asyncio.ensure_future(_run())
    _state["task"] = task

    def _report_death(t: asyncio.Task) -> None:
        # A task that dies during construction would otherwise vanish silently.
        if t.cancelled():
            log.warning("VR180 publisher task cancelled")
        elif t.exception() is not None:
            log.error("VR180 publisher task DIED: %r", t.exception())

    task.add_done_callback(_report_death)
    log.info("OSCAR VR180 publisher scheduled")
    return task


def stop_oscar_media_publisher_vr180() -> None:
    stop = _state.get("stop")
    if stop is None:
        log.warning("No VR180 publisher running")
        return
    stop.set()
    log.info("Stop requested for VR180 publisher")


# ─── Run everything ─────────────────────────────────────────────────────────
if __name__ == "__main__" or True:  # executed via exec() from Script Editor
    # 1. Best-effort stop of the pinhole stereo publisher if it is running.
    try:
        import kit_bootstrap_360 as _kb360

        _kb360.stop_oscar_media_publisher()
        log.info("Requested stop of pinhole stereo publisher")
    except Exception:  # noqa: BLE001
        pass

    # 2. VR180 media.
    start_oscar_media_publisher_vr180()

    # 3. Commands. ros-policy is the production path; xform remains an explicit
    # fallback only and cannot run beside the articulation controller.
    try:
        from command_agent import start_oscar_command_agent

        control_mode = _validate_control_mode()
        apply_mode = "xform" if control_mode == "xform" else "ros2"
        start_oscar_command_agent(
            apply=apply_mode,
            cmd_vel_topic="/cmd_vel",
            robot_prim="/World/g1",
            token_file="/root/Documents/livekit-command-agent.json",
            topic="oscar.xr.input",
            command_topic="oscar.robot.command",
            watchdog_ms=300,
            control_hz=30,
        )
        if control_mode != "xform":
            from g1_locomotion import start_g1_locomotion

            start_g1_locomotion(
                robot_prim="/World/g1",
                cmd_vel_topic="/cmd_vel",
                policy_path=G1_POLICY_PATH,
                require_policy=control_mode == "ros-policy",
            )
    except Exception as exc:  # noqa: BLE001
        log.error("command/locomotion startup issue: %s", exc)
        raise

    print("[oscar] VR180 pipeline up:")
    print(f"        video    : camera-vr180 fisheye {FOV_DEG:.0f}°/eye, 2048x1024 SBS")
    print(f"        commands : Quest → LiveKit → {control_mode} → /cmd_vel → 29 G1 joints")
    print("        stops    : stop_oscar_media_publisher_vr180() / stop_oscar_command_agent() / stop_g1_locomotion()")
