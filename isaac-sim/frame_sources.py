"""Frame producers fed to the LiveKit publisher.

All sources expose the same async generator contract:

    async for rgba_frame in source.frames(stop_event):
        publisher.push_frame(rgba_frame)

Output is always HxWx4 uint8 RGBA matching the publisher's declared size.

Sources:
- MockColorBarsSource — synthetic gradient, no extra dep beyond numpy.
  Lets you verify the LiveKit→front pipe from a laptop in seconds.
- MockVideoFileSource — replays an MP4 in a loop via OpenCV. Useful to test
  the projection metadata (equirect MP4 published to the front).
- IsaacFlatCameraSource — single `omni.isaac.sensor.Camera` from Isaac Sim.
- IsaacCubemap360Source — 6 perspective cameras stitched to equirect via
  the LUT in equirect.py.

Isaac sources only work inside the Isaac Sim Python environment
(`./python.sh sim/media_agent.py …`). They are import-guarded so the other
sources keep working on a machine without Isaac.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import cv2
import numpy as np

from equirect import (
    EquirectProjector,
    build_cubemap_lut,
    FACE_POS_X, FACE_NEG_X,
    FACE_POS_Y, FACE_NEG_Y,
    FACE_POS_Z, FACE_NEG_Z,
)

log = logging.getLogger(__name__)


class FrameSource(abc.ABC):
    """Async producer of RGBA frames at a fixed cadence."""

    def __init__(self, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self._frame_period = 1.0 / float(fps)

    @abc.abstractmethod
    async def _produce(self) -> np.ndarray:
        """Return one HxWx4 uint8 RGBA frame. May block briefly."""

    async def frames(self, stop: asyncio.Event) -> AsyncIterator[np.ndarray]:
        next_t = time.monotonic()
        while not stop.is_set():
            frame = await self._produce()
            yield frame
            next_t += self._frame_period
            sleep_for = next_t - time.monotonic()
            if sleep_for > 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=sleep_for)
                    return
                except asyncio.TimeoutError:
                    pass
            else:
                # We are behind — drop the deficit instead of accumulating it.
                next_t = time.monotonic()

    async def aclose(self) -> None:  # noqa: B027
        return None


# ────────────────────────────────────────────────────────────────────────────
# Mock sources — work without Isaac Sim, useful to validate the LiveKit leg.
# ────────────────────────────────────────────────────────────────────────────


class MockColorBarsSource(FrameSource):
    """Animated gradient with timecode overlay. Self-contained."""

    def __init__(self, width: int, height: int, fps: int):
        super().__init__(width, height, fps)
        self._t0 = time.monotonic()
        self._x = (np.arange(width, dtype=np.float32) / max(1, width - 1))
        self._y = (np.arange(height, dtype=np.float32) / max(1, height - 1))

    async def _produce(self) -> np.ndarray:
        t = time.monotonic() - self._t0
        r = (np.sin(self._x * 6.28 + t) * 0.5 + 0.5)[None, :]
        g = (np.sin(self._y * 6.28 + t * 0.7) * 0.5 + 0.5)[:, None]
        b = np.full((self.height, self.width), (np.sin(t * 0.4) * 0.5 + 0.5), dtype=np.float32)
        rgba = np.empty((self.height, self.width, 4), dtype=np.uint8)
        rgba[..., 0] = (r * 255).astype(np.uint8)
        rgba[..., 1] = (g * 255).astype(np.uint8)
        rgba[..., 2] = (b * 255).astype(np.uint8)
        rgba[..., 3] = 255
        # Burnt-in timecode so the front operator can see frames advancing.
        cv2.putText(
            rgba,
            f"OSCAR mock {t:7.2f}s {self.width}x{self.height}@{self.fps}",
            (24, 56),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (255, 255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        return rgba


class MockVideoFileSource(FrameSource):
    """Loops an MP4 file. Use this to push a known-good equirect sample."""

    def __init__(self, path: str, width: int, height: int, fps: int):
        super().__init__(width, height, fps)
        self._cap = cv2.VideoCapture(path)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video: {path}")
        self._path = path

    async def _produce(self) -> np.ndarray:
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
            if not ok:
                raise RuntimeError(f"Cannot read frames from {self._path}")
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        return rgba

    async def aclose(self) -> None:
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001
            pass


# ────────────────────────────────────────────────────────────────────────────
# Isaac Sim sources — require the embedded Python environment.
# ────────────────────────────────────────────────────────────────────────────


def _require_isaac():
    """Import Isaac Sim modules lazily so the file imports off-box."""
    try:
        from isaacsim.sensors.camera import Camera  # Isaac Sim 5.1
        from omni.kit.app import get_app
        import omni.replicator.core as rep  # noqa: F401  (needed to init render product)

        return Camera, get_app
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Isaac Sim imports failed — this source must run inside Isaac Sim's "
            "Python (./python.sh sim/media_agent.py …). Original error: " + str(exc)
        ) from exc


class IsaacFlatCameraSource(FrameSource):
    """Wraps a single `Camera` prim and yields its RGBA buffer each tick."""

    def __init__(
        self,
        prim_path: str,
        width: int,
        height: int,
        fps: int,
        translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        orientation_xyzw: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0),
    ):
        super().__init__(width, height, fps)
        Camera, get_app = _require_isaac()
        self._get_app = get_app

        self._camera = Camera(
            prim_path=prim_path,
            translation=np.array(translation),
            frequency=fps,
            resolution=(width, height),
            orientation=np.array(orientation_xyzw),
        )
        self._camera.initialize()
        # Enable the RGBA annotator — flat or equirect both read this buffer.
        self._camera.add_motion_vectors_to_frame()  # cheap safety: ensures render product exists
        log.info("IsaacFlatCameraSource ready on %s (%dx%d)", prim_path, width, height)

    async def _produce(self) -> np.ndarray:
        # Step the Kit app so the renderer produces a fresh frame.
        await self._get_app().next_update_async()
        rgba = self._camera.get_rgba()  # HxWx4 uint8
        if rgba is None or rgba.size == 0:
            # First frames after initialisation can be empty — fill with black.
            return np.zeros((self.height, self.width, 4), dtype=np.uint8)
        if rgba.shape[0] != self.height or rgba.shape[1] != self.width:
            rgba = cv2.resize(rgba, (self.width, self.height), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(rgba)


class IsaacStereoSideBySideSource(FrameSource):
    """Two cameras (left + right) packed into a single side-by-side video.

    Publishes ONE LiveKit track to guarantee perfect left/right sync — a pair
    of separate tracks would drift, even with WebRTC RTP synchronisation, by
    a few frames on lossy networks. The eye textures are split client-side
    using `metadata.layout = "stereo-left-right"`.

    Geometry rules of thumb (validated by the OSCAR doc):
    - IPD: keep both cameras translated horizontally by ~6.3 cm in the robot
      frame. Wider gives a "giant" perspective, narrower flattens depth.
    - FOV: 90–100° horizontal is the comfort limit in the Quest. Beyond that
      the lens distortion at the edges becomes nauseating.

    The combined output is (per_eye_width * 2) x per_eye_height. Pick a 1:1
    per-eye aspect that matches the Quest panel ratio if possible.
    """

    def __init__(
        self,
        left_prim_path: str,
        right_prim_path: str,
        per_eye_width: int,
        per_eye_height: int,
        fps: int,
    ):
        super().__init__(per_eye_width * 2, per_eye_height, fps)
        Camera, get_app = _require_isaac()
        self._get_app = get_app
        self._eye_w = per_eye_width
        self._eye_h = per_eye_height

        self._left = Camera(
            prim_path=left_prim_path,
            frequency=fps,
            resolution=(per_eye_width, per_eye_height),
        )
        self._right = Camera(
            prim_path=right_prim_path,
            frequency=fps,
            resolution=(per_eye_width, per_eye_height),
        )
        self._left.initialize()
        self._right.initialize()
        # Preallocated output buffer — the publisher will see the same address
        # every frame, so libwebrtc never reallocates the wrapping VideoFrame.
        self._packed = np.zeros((per_eye_height, per_eye_width * 2, 4), dtype=np.uint8)
        log.info(
            "IsaacStereoSideBySideSource ready: %s + %s → %dx%d packed",
            left_prim_path, right_prim_path, per_eye_width * 2, per_eye_height,
        )

    async def _produce(self) -> np.ndarray:
        await self._get_app().next_update_async()
        left = self._left.get_rgba()
        right = self._right.get_rgba()
        if left is not None and left.size:
            self._packed[:, : self._eye_w, :] = self._fit(left)
        if right is not None and right.size:
            self._packed[:, self._eye_w :, :] = self._fit(right)
        return self._packed

    def _fit(self, buf: np.ndarray) -> np.ndarray:
        if buf.shape[0] == self._eye_h and buf.shape[1] == self._eye_w:
            return buf
        return cv2.resize(buf, (self._eye_w, self._eye_h), interpolation=cv2.INTER_AREA)


class IsaacCubemap360Source(FrameSource):
    """6 perspective cameras at a single point → equirectangular 360 panorama.

    The 6 cameras share one optical centre (the anchor origin) and each looks at
    one cube face. Stitched into an equirect 2:1 frame, this gives a full sphere
    the VR operator can look around freely — head turns just sample a different
    part of an already-captured panorama (the "cheat": the cameras cover every
    direction at once, no robot neck needed).

    Anchor frame: we reuse the EXACT transform that made the stereo rig look
    forward+upright — translate offset + rotateXYZ(90,0,-90) on torso_link. In
    that anchor-local frame an identity-oriented camera looks robot-forward with
    world-up as image-up. The 6 face orientations are derived relative to that.
    """

    # Face orientations in the anchor-LOCAL frame (identity = forward+upright).
    # Quaternions are (w, x, y, z) scalar-first. Verified so each camera's
    # in-image orientation matches what equirect.py expects for its face index.
    _FACE_SPECS = [
        # (lut_face_index, prim_name, label,  quaternion w, x, y, z)
        (FACE_POS_X, "Forward", "forward", (1.0,    0.0, 0.0,    0.0   )),  # look -Z (identity)
        (FACE_NEG_X, "Back",    "back",    (0.0,    0.0, 1.0,    0.0   )),  # 180° about Y → look +Z
        (FACE_POS_Y, "Left",    "left",    (0.7071, 0.0, 0.7071, 0.0   )),  # +90° about Y → look -X
        (FACE_NEG_Y, "Right",   "right",   (0.7071, 0.0,-0.7071, 0.0   )),  # -90° about Y → look +X
        (FACE_POS_Z, "Up",      "up",      (0.0,    0.0, 0.7071,-0.7071)),  # look +Y, rolled
        (FACE_NEG_Z, "Down",    "down",    (0.0,    0.0, 0.7071, 0.7071)),  # look -Y, rolled
    ]

    def __init__(
        self,
        parent_prim_path: str,
        face_size: int,
        out_width: int,
        out_height: int,
        fps: int,
        anchor_offset: tuple[float, float, float] = (0.10, 0.0, 0.30),
        anchor_name: str = "Camera360Anchor",
        debug_png: str = "/root/Documents/oscar_360_check.png",
    ):
        super().__init__(out_width, out_height, fps)
        Camera, get_app = _require_isaac()
        self._get_app = get_app
        self._debug_png = debug_png
        self._debug_saved = False

        anchor_path = self._build_anchor(parent_prim_path, anchor_name, anchor_offset)
        self._anchor_path = anchor_path

        # Let the isaacsim Camera class create each prim — passing `translation`
        # (not `position`) makes `orientation` LOCAL to the anchor, so the
        # cameras compose under the proven forward-aligned anchor frame. This
        # is the pattern that renders reliably (same as the stereo rig); manual
        # UsdGeom.Camera.Define + wrap raced Hydra and gave invalid render
        # products.
        self._cameras: list = [None] * 6  # type: ignore[var-annotated]
        for face_idx, name, label, quat in self._FACE_SPECS:
            cam = Camera(
                prim_path=f"{anchor_path}/Face{name}",
                translation=np.array([0.0, 0.0, 0.0]),
                orientation=np.array(quat),  # local (w, x, y, z)
                frequency=fps,
                resolution=(face_size, face_size),
            )
            cam.initialize()
            cam.set_focal_length(1.0)
            cam.set_horizontal_aperture(2.0)  # 90° FOV
            cam.set_clipping_range(0.05, 1000.0)
            self._cameras[face_idx] = cam
            log.info("  face %-7s (idx %s) @ %s/Face%s", label, face_idx, anchor_path, name)

        self.face_size = face_size
        self._faces = np.zeros((6, face_size, face_size, 4), dtype=np.uint8)

        lut = build_cubemap_lut(out_width=out_width, out_height=out_height, face_size=face_size)
        # numpy backend — cupy is not installed in Kit Python; out is modest.
        self._projector = EquirectProjector(lut, use_gpu=False)
        log.info(
            "IsaacCubemap360Source ready: 6×%dpx → equirect %dx%d, anchor=%s offset=%s",
            face_size, out_width, out_height, anchor_path, anchor_offset,
        )

    @staticmethod
    def _build_anchor(parent_prim_path, anchor_name, offset) -> str:
        """Create the anchor Xform with the proven forward-aligned frame.

        translate(offset) + rotateXYZ(90,0,-90) — the exact transform that made
        the stereo rig look forward+upright. Cameras parented here with the
        right local orientation cover the 6 cube directions in world space.
        """
        import omni.usd
        from pxr import UsdGeom, Gf, Sdf

        stage = omni.usd.get_context().get_stage()
        parent = stage.GetPrimAtPath(parent_prim_path)
        if not parent or not parent.IsValid():
            raise RuntimeError(
                f"Parent prim {parent_prim_path} not found. Use e.g. /World/g1/torso_link."
            )

        anchor_path = f"{parent_prim_path}/{anchor_name}"
        if stage.GetPrimAtPath(anchor_path):
            stage.RemovePrim(anchor_path)  # refresh on re-run

        anchor = UsdGeom.Xform.Define(stage, Sdf.Path(anchor_path))
        anchor.AddXformOp(UsdGeom.XformOp.TypeTranslate).Set(
            Gf.Vec3d(float(offset[0]), float(offset[1]), float(offset[2]))
        )
        anchor.AddXformOp(UsdGeom.XformOp.TypeRotateXYZ).Set(Gf.Vec3f(90.0, 0.0, -90.0))
        log.info("Built 360 anchor at %s (translate=%s, rotateXYZ=(90,0,-90))", anchor_path, offset)
        return anchor_path

    async def _produce(self) -> np.ndarray:
        await self._get_app().next_update_async()
        for i, cam in enumerate(self._cameras):
            buf = cam.get_rgba()
            if buf is None or buf.size == 0:
                continue
            if buf.shape[0] != self.face_size or buf.shape[1] != self.face_size:
                buf = cv2.resize(buf, (self.face_size, self.face_size), interpolation=cv2.INTER_AREA)
            self._faces[i] = buf
        equirect = self._projector.project(self._faces)

        # Save the first non-empty equirect frame for offline orientation check.
        if not self._debug_saved and self._debug_png and equirect.any():
            try:
                cv2.imwrite(self._debug_png, cv2.cvtColor(equirect, cv2.COLOR_RGBA2BGR))
                log.info("Saved 360 check image → %s", self._debug_png)
                self._debug_saved = True
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not save debug PNG: %s", exc)

        return equirect

    async def aclose(self) -> None:
        # Remove the whole rig (anchor + child cameras + their render products)
        # so a re-run starts clean and doesn't flood the console with
        # "Invalid RenderProduct" from orphaned products.
        try:
            import omni.usd
            stage = omni.usd.get_context().get_stage()
            if stage and self._anchor_path and stage.GetPrimAtPath(self._anchor_path):
                stage.RemovePrim(self._anchor_path)
                log.info("Removed 360 rig %s", self._anchor_path)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not remove 360 rig: %s", exc)
