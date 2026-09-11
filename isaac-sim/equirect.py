"""Cubemap → equirectangular projection.

Isaac Sim renders 6 perspective cameras (one per cube face). We assemble them
into a single equirect 2:1 frame matching the LiveKit contract documented in
docs/immersive-video-pipeline.md (`projection=equirect`, `layout=mono`).

Convention — robot frame (REP 103, matches Isaac Sim Z-up worlds):
- +X = forward          → centre of the panorama (col W/2, row H/2)
- +Y = left             → left of panorama centre  (col 1/4 W)
- +Z = up               → top of panorama  (row 0)
- −X = back             → wraps around at the horizontal edges
- −Y = right            → right of panorama centre (col 3/4 W)
- −Z = down             → bottom of panorama  (row H)

The mapping is purely geometric and time-invariant — we precompute a UV lookup
table once at startup, then every frame is a vectorised gather. CuPy on GPU when
available (Isaac Sim runs on a CUDA box), numpy fallback otherwise so the
module is testable from a laptop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

try:
    import cupy as _cp

    _HAS_CUPY = True
except Exception:  # noqa: BLE001
    _cp = None
    _HAS_CUPY = False


# Cube face order. Must match the camera ordering used by IsaacCubemap360Source.
# Indices reflect the robot frame the camera is rotated to look at.
FACE_POS_X = 0  # forward (+X)
FACE_NEG_X = 1  # back    (-X)
FACE_POS_Y = 2  # left    (+Y)
FACE_NEG_Y = 3  # right   (-Y)
FACE_POS_Z = 4  # up      (+Z)
FACE_NEG_Z = 5  # down    (-Z)


@dataclass(frozen=True)
class CubemapLUT:
    """Flat gather indices for an HxW equirect output over a stack of 6 faces."""

    face_idx: np.ndarray   # (H, W) uint8 — which cube face per pixel
    face_u: np.ndarray     # (H, W) int32 — column inside the picked face
    face_v: np.ndarray     # (H, W) int32 — row inside the picked face
    out_height: int
    out_width: int
    face_size: int


def build_cubemap_lut(out_width: int, out_height: int, face_size: int) -> CubemapLUT:
    """Precompute the per-pixel face + UV pick for an equirect output.

    The math: each output pixel (u, v) maps to a direction
    (lon, lat) = ((u/W - 0.5) * 2π, (0.5 - v/H) * π). We pick the face whose
    axis dominates that direction, then project onto its 2D plane.
    """
    if out_width != 2 * out_height:
        raise ValueError(f"equirect must be 2:1 — got {out_width}x{out_height}")

    j = np.arange(out_width, dtype=np.float32)
    i = np.arange(out_height, dtype=np.float32)
    jj, ii = np.meshgrid(j, i)  # (H, W)

    # Centre of panorama (jj=W/2, ii=H/2) → azimuth=0, altitude=0 → +X (forward).
    azimuth  = (jj / out_width  - 0.5) * (2.0 * np.pi)   # +π/2 → looking right
    altitude = (0.5 - ii / out_height) * np.pi           # +π/2 → looking up

    cos_alt = np.cos(altitude)
    x =  cos_alt * np.cos(azimuth)   # +X forward
    y = -cos_alt * np.sin(azimuth)   # +Y left (so azimuth>0 looks right → −Y)
    z =  np.sin(altitude)            # +Z up

    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)

    face_idx = np.empty_like(x, dtype=np.uint8)
    sc = np.empty_like(x)  # face-local horizontal (−1..1) → maps to face column
    tc = np.empty_like(x)  # face-local vertical   (−1..1) → maps to face row

    x_dom = (ax >= ay) & (ax >= az)
    y_dom = (~x_dom) & (ay >= az)
    z_dom = ~(x_dom | y_dom)

    # Each face camera looks at a robot-frame axis. The face's local "up" is
    # always world +Z when possible; for the +Z (up) and -Z (down) faces, the
    # local "up" is +X (forward). sc/tc are derived so the face image stitches
    # seamlessly with its neighbours.

    # +X (forward) — looking toward +X. Right of image = -Y. Top of image = +Z.
    m = x_dom & (x > 0)
    face_idx[m] = FACE_POS_X
    sc[m] = -y[m] / ax[m]
    tc[m] =  z[m] / ax[m]
    # -X (back) — looking toward -X. Right of image = +Y. Top of image = +Z.
    m = x_dom & (x <= 0)
    face_idx[m] = FACE_NEG_X
    sc[m] =  y[m] / ax[m]
    tc[m] =  z[m] / ax[m]

    # +Y (left) — looking toward +Y. Right of image = +X. Top of image = +Z.
    m = y_dom & (y > 0)
    face_idx[m] = FACE_POS_Y
    sc[m] =  x[m] / ay[m]
    tc[m] =  z[m] / ay[m]
    # -Y (right) — looking toward -Y. Right of image = -X. Top of image = +Z.
    m = y_dom & (y <= 0)
    face_idx[m] = FACE_NEG_Y
    sc[m] = -x[m] / ay[m]
    tc[m] =  z[m] / ay[m]

    # +Z (up) — looking toward +Z. Right of image = -Y. Top of image = +X.
    m = z_dom & (z > 0)
    face_idx[m] = FACE_POS_Z
    sc[m] = -y[m] / az[m]
    tc[m] =  x[m] / az[m]
    # -Z (down) — looking toward -Z. Right of image = -Y. Top of image = -X.
    m = z_dom & (z <= 0)
    face_idx[m] = FACE_NEG_Z
    sc[m] = -y[m] / az[m]
    tc[m] = -x[m] / az[m]

    # sc/tc are in math convention (+1 = right / up). Face images are stored
    # row-major with row 0 = top, so the vertical axis must be inverted:
    # tc=+1 (up) → row 0, tc=-1 (down) → last row.
    u = np.clip(((sc + 1.0) * 0.5 * face_size).astype(np.int32), 0, face_size - 1)
    v = np.clip(((1.0 - tc) * 0.5 * face_size).astype(np.int32), 0, face_size - 1)

    return CubemapLUT(
        face_idx=face_idx,
        face_u=u,
        face_v=v,
        out_height=out_height,
        out_width=out_width,
        face_size=face_size,
    )


class EquirectProjector:
    """Stateful gather using a CuPy LUT when CUDA is available."""

    def __init__(self, lut: CubemapLUT, use_gpu: Optional[bool] = None):
        self.lut = lut
        if use_gpu is None:
            use_gpu = _HAS_CUPY
        if use_gpu and not _HAS_CUPY:
            raise RuntimeError("CuPy not available — install cupy-cuda12x or pass use_gpu=False")
        self.use_gpu = use_gpu

        xp = _cp if use_gpu else np
        self._xp = xp
        self._face_idx = xp.asarray(lut.face_idx, dtype=xp.int64)
        self._face_u = xp.asarray(lut.face_u, dtype=xp.int64)
        self._face_v = xp.asarray(lut.face_v, dtype=xp.int64)
        self._flat_idx = (
            self._face_idx * (lut.face_size * lut.face_size)
            + self._face_v * lut.face_size
            + self._face_u
        ).ravel()
        log.info(
            "EquirectProjector ready: %dx%d output, face=%d, backend=%s",
            lut.out_width,
            lut.out_height,
            lut.face_size,
            "cupy" if use_gpu else "numpy",
        )

    def project(self, faces_rgba: np.ndarray) -> np.ndarray:
        """faces_rgba: (6, face, face, 4) uint8. Returns (H, W, 4) uint8."""
        xp = self._xp
        if faces_rgba.shape != (6, self.lut.face_size, self.lut.face_size, 4):
            raise ValueError(
                f"Expected (6, {self.lut.face_size}, {self.lut.face_size}, 4) — got {faces_rgba.shape}"
            )
        src = xp.asarray(faces_rgba)
        flat = src.reshape(-1, 4)
        out = flat[self._flat_idx].reshape(self.lut.out_height, self.lut.out_width, 4)
        if self.use_gpu:
            out = _cp.asnumpy(out)
        if not out.flags["C_CONTIGUOUS"]:
            out = np.ascontiguousarray(out)
        return out
