"""OSCAR physical-robot media publisher — ROS 2 camera → LiveKit.

Runs inside the robot's ROS 2 container. Subscribes to the camera image topic
and publishes it as a LiveKit video track, so the physical ROSMASTER appears in
the OSCAR front exactly like the Isaac sim publisher does.

    python oscar_robot_media.py \
        --token-file /root/livekit-robot.json \
        --topic /camera/color/image_raw --width 640 --height 480 --fps 10

Config priority: CLI flag > env (OSCAR_LIVEKIT_* / LIVEKIT_*) > token JSON file.
The token JSON has the same shape as livekit-isaac-publisher.json:
    { "livekit": { "serverUrl": ..., "roomName": ..., "identity": ..., "token": ... } }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from livekit_publisher import LiveKitPublisher, PublisherConfig
from ros2_image_source import Ros2ImageSource

log = logging.getLogger("oscar.robot_media")


def _resolve_conn(args: argparse.Namespace) -> dict:
    """Merge connection settings from token file + env + CLI (CLI wins)."""
    conn = {"url": None, "room": None, "identity": None, "token": None}

    if args.token_file and Path(args.token_file).exists():
        try:
            lk = json.loads(Path(args.token_file).read_text()).get("livekit", {})
            conn.update(
                url=lk.get("serverUrl"),
                room=lk.get("roomName"),
                identity=lk.get("identity"),
                token=lk.get("token"),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not read token file %s: %s", args.token_file, exc)

    # env overrides file
    conn["url"] = os.getenv("OSCAR_LIVEKIT_URL") or os.getenv("LIVEKIT_URL") or conn["url"]
    conn["room"] = os.getenv("OSCAR_LIVEKIT_ROOM") or os.getenv("LIVEKIT_ROOM") or conn["room"]
    conn["identity"] = os.getenv("OSCAR_ROBOT_IDENTITY") or conn["identity"]
    conn["token"] = os.getenv("OSCAR_LIVEKIT_TOKEN") or os.getenv("LIVEKIT_TOKEN") or conn["token"]

    # CLI overrides everything
    conn["url"] = args.url or conn["url"]
    conn["identity"] = args.identity or conn["identity"]
    conn["token"] = args.token or conn["token"]

    if not conn["url"] or not conn["token"]:
        raise SystemExit(
            "Missing LiveKit url/token. Provide --token-file, or OSCAR_LIVEKIT_URL + "
            "OSCAR_LIVEKIT_TOKEN, or --url/--token."
        )
    return conn


async def _run(args: argparse.Namespace) -> int:
    conn = _resolve_conn(args)

    cfg = PublisherConfig(
        url=conn["url"],
        token=conn["token"],
        identity=conn["identity"] or "robot-oscar-03",
        track_name=args.track_name,
        width=args.width,
        height=args.height,
        fps=args.fps,
        projection="flat",
        layout="mono",
        source_label="rosmaster-m3",
        max_bitrate_bps=args.max_bitrate,
    )

    publisher = LiveKitPublisher(cfg)
    source = Ros2ImageSource(
        topic=args.topic,
        width=args.width,
        height=args.height,
        fps=args.fps,
        rotate_180=args.rotate_180,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await publisher.connect()
        log.info("Publishing %s → track '%s' as %s", args.topic, cfg.track_name, cfg.identity)
        async for frame in source.frames(stop):
            publisher.push_frame(frame)
    finally:
        await source.aclose()
        await publisher.aclose()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="OSCAR ROSMASTER camera → LiveKit")
    p.add_argument("--token-file", default=os.getenv("OSCAR_TOKEN_FILE", "/root/livekit-robot.json"))
    p.add_argument("--url", default=None)
    p.add_argument("--identity", default=None)
    p.add_argument("--token", default=None)
    p.add_argument("--topic", default=os.getenv("OSCAR_CAMERA_TOPIC", "/camera/color/image_raw"))
    p.add_argument("--track-name", default="camera-front")
    p.add_argument("--width", type=int, default=int(os.getenv("OSCAR_CAMERA_WIDTH", "640")))
    p.add_argument("--height", type=int, default=int(os.getenv("OSCAR_CAMERA_HEIGHT", "480")))
    p.add_argument("--fps", type=int, default=int(os.getenv("OSCAR_CAMERA_FPS", "10")))
    p.add_argument(
        "--max-bitrate",
        type=int,
        default=int(os.getenv("OSCAR_CAMERA_MAX_BITRATE", "1200000")),
        help="Maximum WebRTC video bitrate in bits/s",
    )
    p.add_argument(
        "--rotate-180",
        action="store_true",
        default=os.getenv("OSCAR_CAMERA_ROTATE_180", "false").lower() == "true",
        help="Rotate frames for an upside-down physical camera mount",
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
