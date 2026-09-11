"""LiveKit publisher for the OSCAR Isaac Sim media agent.

Pushes RGBA frames produced by a `FrameSource` into a LiveKit room as a single
video track. Uses livekit-rtc's `VideoSource` which hands frames to the native
WebRTC encoder (libwebrtc); a single H.264/VP8 encode happens here, no
intermediate transcode.

The front (`src/capture/livekitStream.js`) picks the active publisher by
identity prefix and reads `metadata.projection` to decide between flat screen
and inside-out sphere rendering — both fields are set here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
if str(VENDOR_DIR) not in sys.path:
    sys.path.append(str(VENDOR_DIR))

import numpy as np
from livekit import rtc

log = logging.getLogger(__name__)


@dataclass
class PublisherConfig:
    url: str
    token: str
    identity: str
    track_name: str
    width: int
    height: int
    fps: int
    projection: str  # "flat" | "equirect"
    layout: str = "mono"  # "mono" | "stereo-left-right" | "stereo-top-bottom"
    source_label: str = "isaac-sim"
    max_bitrate_bps: int | None = None

    @property
    def metadata_json(self) -> str:
        return json.dumps(
            {
                "projection": self.projection,
                "layout": self.layout,
                "stereo": "left-right" if self.layout == "stereo-left-right" else "none",
                "depth": "none",
                "source": self.source_label,
                "frame": {"width": self.width, "height": self.height, "fps": self.fps},
            },
            separators=(",", ":"),
        )


class LiveKitPublisher:
    """Holds the room connection and the single outbound video track.

    Frame pushes are synchronous from the producer's point of view — the
    encoder owns its own thread inside libwebrtc. `push_frame` only copies
    a `VideoFrame` view onto the source's internal queue.
    """

    def __init__(self, cfg: PublisherConfig):
        self.cfg = cfg
        self.room: Optional[rtc.Room] = None
        self.source: Optional[rtc.VideoSource] = None
        self.track: Optional[rtc.LocalVideoTrack] = None
        self._publication: Optional[rtc.LocalTrackPublication] = None
        self._frames_published = 0
        self._last_stats_t = time.monotonic()

    async def connect(self) -> None:
        if self.room is not None:
            return

        self.room = rtc.Room()
        self._wire_room_events()

        # Browsers ship default STUN servers; the Python SDK does not. Without
        # them the publisher only advertises host candidates (the VM's private
        # cloud IP), so an ICE-Lite server hosted on a different cloud has
        # nothing reachable to bind to. These public STUN endpoints let
        # libwebrtc derive a working srflx candidate.
        rtc_cfg = rtc.RtcConfiguration(
            ice_servers=[
                rtc.IceServer(urls=["stun:stun.l.google.com:19302"]),
                rtc.IceServer(urls=["stun:stun.cloudflare.com:3478"]),
            ],
        )

        log.info("Connecting to LiveKit %s as %s", self.cfg.url, self.cfg.identity)
        await self.room.connect(
            self.cfg.url,
            self.cfg.token,
            options=rtc.RoomOptions(auto_subscribe=False, rtc_config=rtc_cfg),
        )
        try:
            sid = await self.room.sid  # awaitable since livekit-rtc 1.x
        except TypeError:
            sid = self.room.sid  # 0.x fallback (sync attribute)
        log.info("Connected. SID=%s participants=%d", sid, len(self.room.remote_participants))

        # The participant identity is fixed by the JWT `sub`. Metadata can still
        # be updated post-connect so the front sees `projection` right away.
        try:
            await self.room.local_participant.set_metadata(self.cfg.metadata_json)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not set participant metadata: %s", exc)

        self.source = rtc.VideoSource(self.cfg.width, self.cfg.height)
        self.track = rtc.LocalVideoTrack.create_video_track(self.cfg.track_name, self.source)

        publish_kwargs = dict(
            source=rtc.TrackSource.SOURCE_CAMERA,
            video_codec=rtc.VideoCodec.H264,
            simulcast=False,
        )
        if self.cfg.max_bitrate_bps:
            publish_kwargs["video_encoding"] = rtc.VideoEncoding(
                max_bitrate=self.cfg.max_bitrate_bps,
                max_framerate=self.cfg.fps,
            )
            publish_kwargs["degradation_preference"] = rtc.DegradationPreference.MAINTAIN_FRAMERATE
        publish_opts = rtc.TrackPublishOptions(**publish_kwargs)
        self._publication = await self.room.local_participant.publish_track(self.track, publish_opts)
        log.info(
            "Published track name=%s sid=%s codec=H264 %dx%d@%d projection=%s max_bitrate=%s",
            self.cfg.track_name,
            self._publication.sid,
            self.cfg.width,
            self.cfg.height,
            self.cfg.fps,
            self.cfg.projection,
            self.cfg.max_bitrate_bps or "auto",
        )

    def _wire_room_events(self) -> None:
        assert self.room is not None

        @self.room.on("disconnected")
        def _on_disconnect(reason):  # noqa: ANN001
            log.warning("Room disconnected: %s", reason)

        @self.room.on("participant_connected")
        def _on_join(p: rtc.RemoteParticipant) -> None:
            log.info("Subscriber joined: %s", p.identity)

        @self.room.on("participant_disconnected")
        def _on_leave(p: rtc.RemoteParticipant) -> None:
            log.info("Subscriber left: %s", p.identity)

    def push_frame(self, image: np.ndarray, timestamp_ns: Optional[int] = None) -> None:
        """Hand one RGB24 or RGBA frame to the encoder.

        `image` must be a contiguous HxWx3/HxWx4 uint8 buffer matching the publisher
        dimensions. Anything else is rejected loudly so a bad upstream is
        surfaced instead of silently dropped.
        """
        if self.source is None:
            raise RuntimeError("Publisher is not connected yet")
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError(
                f"Expected HxWx3/HxWx4 uint8 image, got shape={image.shape} dtype={image.dtype}"
            )
        h, w, channels = image.shape
        if (w, h) != (self.cfg.width, self.cfg.height):
            raise ValueError(
                f"Frame size {w}x{h} does not match publisher {self.cfg.width}x{self.cfg.height}"
            )
        if not image.flags["C_CONTIGUOUS"]:
            image = np.ascontiguousarray(image)

        frame = rtc.VideoFrame(
            width=w,
            height=h,
            type=rtc.VideoBufferType.RGB24 if channels == 3 else rtc.VideoBufferType.RGBA,
            data=image.tobytes(),
        )
        # capture_frame is a non-awaitable native call; the source enqueues
        # the frame on the encoder thread.
        self.source.capture_frame(frame, timestamp_us=(timestamp_ns or time.time_ns()) // 1000)

        self._frames_published += 1
        now = time.monotonic()
        if now - self._last_stats_t >= 5.0:
            fps_avg = self._frames_published / (now - self._last_stats_t)
            log.info("Published ~%.1f fps over last %.1fs", fps_avg, now - self._last_stats_t)
            self._frames_published = 0
            self._last_stats_t = now

    async def aclose(self) -> None:
        if self.room is None:
            return
        log.info("Closing LiveKit room")
        try:
            if self._publication is not None and self.track is not None:
                await self.room.local_participant.unpublish_track(self.track.sid)
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.room.disconnect()
        finally:
            self.room = None
            self.track = None
            self.source = None
            self._publication = None


def mint_publisher_token(
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    ttl_seconds: int = 86400,
) -> str:
    """Sign a publisher JWT locally — same shape as create-livekit-tokens.mjs.

    Useful when iterating from the Isaac Sim box without round-tripping through
    the Node script. Requires `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`.
    """
    import jwt  # local import keeps the dep optional for the read path

    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": identity,
        "name": identity,
        "nbf": now,
        "exp": now + ttl_seconds,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": False,
            "canPublishData": True,
            "canPublishSources": ["camera"],
        },
    }
    return jwt.encode(payload, api_secret, algorithm="HS256")


async def wait_forever(stop: asyncio.Event) -> None:
    await stop.wait()
