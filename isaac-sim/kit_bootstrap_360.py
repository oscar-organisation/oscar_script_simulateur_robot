"""OSCAR stereo VR-passthrough publisher — start/stop helpers for Kit.

Pattern matches command_agent.start_oscar_command_agent: importing this module
does nothing, you call `start_oscar_media_publisher(...)` explicitly. Lets the
unified kit_bootstrap_command.py launch media + commands side by side.

Override any default by keyword argument:

    from kit_bootstrap_360 import start_oscar_media_publisher
    start_oscar_media_publisher(per_eye_width=640, per_eye_height=360)  # lighter
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from livekit_publisher import LiveKitPublisher, PublisherConfig
from frame_sources import IsaacStereoSideBySideSource

log = logging.getLogger("oscar.media_bootstrap")

# Defaults — override via kwargs to start_oscar_media_publisher.
DEFAULTS = dict(
    token_file="/root/Documents/livekit-isaac-publisher.json",
    left_prim="/World/g1/torso_link/stereo_rig/robot_camera_left",
    right_prim="/World/g1/torso_link/stereo_rig/robot_camera_right",
    per_eye_width=1280,
    per_eye_height=720,
    fps=30,
    track_name="camera-stereo",
    identity="simulateur-robot-isaac-1",
    source_label="isaac-sim",
)

_state: dict[str, Any] = {"task": None, "stop": None, "publisher": None, "source": None}


def start_oscar_media_publisher(**overrides: Any) -> asyncio.Task:
    """Start the stereo publisher on Kit's existing asyncio loop."""
    if _state.get("task") and not _state["task"].done():
        log.warning("Media publisher already running")
        return _state["task"]

    params = {**DEFAULTS, **overrides}
    with open(params["token_file"]) as fh:
        lk = json.load(fh)["livekit"]

    cfg = PublisherConfig(
        url=lk["serverUrl"],
        token=lk["token"],
        identity=params["identity"],
        track_name=params["track_name"],
        width=params["per_eye_width"] * 2,
        height=params["per_eye_height"],
        fps=params["fps"],
        projection="flat",
        layout="stereo-left-right",
        source_label=params["source_label"],
    )

    async def _run() -> None:
        publisher = LiveKitPublisher(cfg)
        _state["publisher"] = publisher
        log.info(
            "Wiring stereo source: left=%s right=%s",
            params["left_prim"], params["right_prim"],
        )
        source = IsaacStereoSideBySideSource(
            left_prim_path=params["left_prim"],
            right_prim_path=params["right_prim"],
            per_eye_width=params["per_eye_width"],
            per_eye_height=params["per_eye_height"],
            fps=params["fps"],
        )
        _state["source"] = source

        await publisher.connect()
        stop = asyncio.Event()
        _state["stop"] = stop
        log.info(
            "Frame loop start — %dx%d packed @ %d fps",
            params["per_eye_width"] * 2, params["per_eye_height"], params["fps"],
        )
        try:
            async for frame in source.frames(stop):
                publisher.push_frame(frame)
        finally:
            await source.aclose()
            await publisher.aclose()
            log.info("Media publisher stopped.")

    task = asyncio.ensure_future(_run())
    _state["task"] = task
    log.info("OSCAR media publisher scheduled")
    return task


def stop_oscar_media_publisher() -> None:
    stop = _state.get("stop")
    if stop is None:
        log.warning("No OSCAR media publisher is running")
        return
    stop.set()
    log.info("Stop requested for OSCAR media publisher")


# ───────────────────────────────────────────────────────────────────────────
# 360 equirect variant — 6 cameras at one point → full panorama sphere.
# ───────────────────────────────────────────────────────────────────────────

DEFAULTS_360 = dict(
    token_file="/root/Documents/livekit-isaac-publisher.json",
    parent_prim="/World/g1/torso_link",
    anchor_offset=(0.10, 0.0, 0.30),
    face_size=512,
    out_width=2048,
    out_height=1024,
    fps=20,
    track_name="camera-360",
    identity="simulateur-robot-isaac-1",
    source_label="isaac-sim",
)

_state_360: dict[str, Any] = {"task": None, "stop": None}


def start_oscar_media_publisher_360(**overrides: Any) -> asyncio.Task:
    """Start the 360 equirect publisher on Kit's existing asyncio loop."""
    if _state_360.get("task") and not _state_360["task"].done():
        log.warning("360 publisher already running")
        return _state_360["task"]

    from frame_sources import IsaacCubemap360Source

    params = {**DEFAULTS_360, **overrides}
    with open(params["token_file"]) as fh:
        lk = json.load(fh)["livekit"]

    cfg = PublisherConfig(
        url=lk["serverUrl"],
        token=lk["token"],
        identity=params["identity"],
        track_name=params["track_name"],
        width=params["out_width"],
        height=params["out_height"],
        fps=params["fps"],
        projection="equirect",
        layout="mono",
        source_label=params["source_label"],
    )

    async def _run() -> None:
        publisher = LiveKitPublisher(cfg)
        source = IsaacCubemap360Source(
            parent_prim_path=params["parent_prim"],
            face_size=params["face_size"],
            out_width=params["out_width"],
            out_height=params["out_height"],
            fps=params["fps"],
            anchor_offset=params["anchor_offset"],
        )
        await publisher.connect()
        stop = asyncio.Event()
        _state_360["stop"] = stop
        log.info("360 frame loop start — equirect %dx%d @ %d fps",
                 params["out_width"], params["out_height"], params["fps"])
        try:
            async for frame in source.frames(stop):
                publisher.push_frame(frame)
        finally:
            await source.aclose()
            await publisher.aclose()
            log.info("360 publisher stopped.")

    task = asyncio.ensure_future(_run())
    _state_360["task"] = task
    log.info("OSCAR 360 publisher scheduled")
    return task


def stop_oscar_media_publisher_360() -> None:
    stop = _state_360.get("stop")
    if stop is None:
        log.warning("No OSCAR 360 publisher is running")
        return
    stop.set()
    log.info("Stop requested for OSCAR 360 publisher")
