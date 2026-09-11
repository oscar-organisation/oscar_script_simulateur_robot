"""OSCAR Media Agent — Isaac Sim cameras → LiveKit room.

Usage examples
--------------

Test the LiveKit leg from a laptop with synthetic frames (no Isaac):

    python -m sim.media_agent --source mock --projection flat \
        --width 1280 --height 720 --fps 30 --track-name camera-front

Replay an MP4 as if it were the robot's 360 camera:

    python -m sim.media_agent --source file --file ~/sample_equirect.mp4 \
        --projection equirect --width 3840 --height 1920 --fps 30 \
        --track-name camera-360

Full 360 inside the Isaac Sim GPU container:

    ./python.sh sim/media_agent.py --source isaac-360 \
        --anchor /World/NovaCarter/chassis_link/Camera360Anchor \
        --face-size 1024 --width 4096 --height 2048 --fps 30 \
        --track-name camera-360 --projection equirect

The publisher identity defaults to `simulateur-robot-isaac-1` — the front
prioritises any `simulateur-robot-*` over the always-on MP4 VPS publisher
(see src/capture/livekitStream.js:73), so launching this script instantly
replaces what the operator sees in the headset.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Make sibling imports work both as `python -m sim.media_agent` and as
# `./python.sh sim/media_agent.py` (Isaac Sim doesn't set up the package).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from livekit_publisher import LiveKitPublisher, PublisherConfig, mint_publisher_token

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # noqa: BLE001
    pass


log = logging.getLogger("oscar.media_agent")


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OSCAR Media Agent — publishes a video track to LiveKit")
    p.add_argument(
        "--source",
        choices=["mock", "file", "isaac-flat", "isaac-stereo", "isaac-360"],
        default=os.getenv("PUBLISHER_SOURCE", "mock"),
    )
    p.add_argument("--file", default=None, help="MP4 path when --source file")
    p.add_argument(
        "--prim",
        default="/World/Oscar/Camera",
        help="Isaac Sim camera prim path (isaac-flat)",
    )
    p.add_argument(
        "--left-prim",
        default=os.getenv("PUBLISHER_LEFT_PRIM", "/World/Oscar/CameraLeft"),
        help="Left-eye camera prim path (isaac-stereo)",
    )
    p.add_argument(
        "--right-prim",
        default=os.getenv("PUBLISHER_RIGHT_PRIM", "/World/Oscar/CameraRight"),
        help="Right-eye camera prim path (isaac-stereo)",
    )
    p.add_argument(
        "--parent-prim",
        default=os.getenv("PUBLISHER_PARENT_PRIM", "/World/g1/torso_link"),
        help="Prim under which the cubemap anchor is created (isaac-360). "
             "Defaults to G1's torso_link so the rig follows the head.",
    )
    p.add_argument(
        "--anchor-name",
        default="Camera360Anchor",
        help="Name of the Xform created under --parent-prim",
    )
    p.add_argument("--offset-x", type=float, default=0.0, help="Local X offset of the anchor (m)")
    p.add_argument("--offset-y", type=float, default=0.0, help="Local Y offset of the anchor (m)")
    p.add_argument(
        "--offset-z", type=float, default=0.25,
        help="Local Z offset of the anchor (m) — eye height above torso_link origin",
    )
    p.add_argument("--face-size", type=int, default=1024, help="Per-face resolution (isaac-360)")
    p.add_argument(
        "--per-eye-width", type=int, default=1280,
        help="Per-eye width for isaac-stereo (packed output = 2x this)",
    )
    p.add_argument("--per-eye-height", type=int, default=720, help="Per-eye height for isaac-stereo")
    p.add_argument(
        "--layout",
        choices=["mono", "stereo-left-right", "stereo-top-bottom"],
        default=os.getenv("PUBLISHER_LAYOUT", "mono"),
    )

    p.add_argument("--width", type=int, default=int(os.getenv("PUBLISHER_WIDTH", "3840")))
    p.add_argument("--height", type=int, default=int(os.getenv("PUBLISHER_HEIGHT", "1920")))
    p.add_argument("--fps", type=int, default=int(os.getenv("PUBLISHER_FPS", "30")))
    p.add_argument(
        "--projection",
        choices=["flat", "equirect"],
        default=os.getenv("PUBLISHER_PROJECTION", "equirect"),
    )
    p.add_argument("--track-name", default=os.getenv("PUBLISHER_TRACK_NAME", "camera-360"))
    p.add_argument("--source-label", default="isaac-sim")

    p.add_argument("--url", default=os.getenv("LIVEKIT_URL"))
    p.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "oscar-lot1-room"))
    p.add_argument(
        "--identity",
        default=os.getenv("LIVEKIT_PUBLISHER_IDENTITY", "simulateur-robot-isaac-1"),
    )
    p.add_argument(
        "--token",
        default=os.getenv("LIVEKIT_TOKEN"),
        help="Pre-signed JWT. If absent, signed locally from LIVEKIT_API_KEY/SECRET.",
    )
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return p


def _resolve_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not api_key or not api_secret:
        raise SystemExit(
            "No --token provided and LIVEKIT_API_KEY/LIVEKIT_API_SECRET are unset. "
            "Run `npm run livekit:tokens` from OSCAR/ and export LIVEKIT_TOKEN, or "
            "set the API secrets in sim/.env."
        )
    return mint_publisher_token(api_key, api_secret, args.room, args.identity)


def _build_source(args: argparse.Namespace):
    if args.source == "mock":
        from frame_sources import MockColorBarsSource

        return MockColorBarsSource(args.width, args.height, args.fps)
    if args.source == "file":
        from frame_sources import MockVideoFileSource

        if not args.file:
            raise SystemExit("--file is required when --source file")
        return MockVideoFileSource(args.file, args.width, args.height, args.fps)
    if args.source == "isaac-flat":
        from frame_sources import IsaacFlatCameraSource

        return IsaacFlatCameraSource(args.prim, args.width, args.height, args.fps)
    if args.source == "isaac-stereo":
        from frame_sources import IsaacStereoSideBySideSource

        return IsaacStereoSideBySideSource(
            left_prim_path=args.left_prim,
            right_prim_path=args.right_prim,
            per_eye_width=args.per_eye_width,
            per_eye_height=args.per_eye_height,
            fps=args.fps,
        )
    if args.source == "isaac-360":
        from frame_sources import IsaacCubemap360Source

        return IsaacCubemap360Source(
            parent_prim_path=args.parent_prim,
            face_size=args.face_size,
            out_width=args.width,
            out_height=args.height,
            fps=args.fps,
            anchor_offset=(args.offset_x, args.offset_y, args.offset_z),
            anchor_name=args.anchor_name,
        )
    raise SystemExit(f"Unknown source {args.source!r}")


async def _run(args: argparse.Namespace) -> int:
    if not args.url:
        raise SystemExit("--url or LIVEKIT_URL is required")

    source = _build_source(args)

    # For isaac-stereo the source dictates the packed size — override the CLI
    # width/height so the publisher matches the actual buffer being pushed.
    width = source.width
    height = source.height
    layout = args.layout
    if args.source == "isaac-stereo" and layout == "mono":
        layout = "stereo-left-right"

    cfg = PublisherConfig(
        url=args.url,
        token=_resolve_token(args),
        identity=args.identity,
        track_name=args.track_name,
        width=width,
        height=height,
        fps=args.fps,
        projection=args.projection,
        layout=layout,
        source_label=args.source_label,
    )

    publisher = LiveKitPublisher(cfg)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows / Isaac embedded — fall back to KeyboardInterrupt.
            pass

    try:
        await publisher.connect()
        log.info("Starting frame loop on source=%s", args.source)
        async for frame in source.frames(stop):
            publisher.push_frame(frame)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        await source.aclose()
        await publisher.aclose()
    return 0


def main() -> int:
    args = _build_argparser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
