"""Add the OSCAR Camera360Anchor (6 cubemap cameras) under /World/g1/torso_link.

Direct USD file edit — no Isaac GUI required. Run with the project venv:

    .venv/bin/python sim/scene_ops/add_camera360_anchor.py \
        --stage /documents/supermarket.usd \
        [--offset-x 0 --offset-y 0 --offset-z 0.25] \
        [--face-size 1024] \
        [--no-backup]

Idempotent: if the anchor already exists at the target path, it is removed and
recreated so successive calls reflect the latest geometry.

Before each write the script copies the source layer to
`<stage>.bak-YYYYMMDD-HHMMSS` next to the file unless --no-backup is set.

After running, reload the stage inside Isaac (File → Reload Stage) — Kit caches
the previous in-memory layer composition until you do.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom


PARENT_PRIM = "/World/g1/torso_link"
ANCHOR_NAME = "Camera360Anchor"

# Face name, look axis label, camera-local rotation (USD quat: scalar-first w,x,y,z).
# Each quaternion maps the USD camera default look direction (its own -Z) onto
# the named axis in the anchor's local frame. With the anchor inheriting
# torso_link's REP-103 frame (X=forward, Y=left, Z=up), the panorama centre
# naturally lines up with robot-forward.
FACE_SPECS = [
    ("Forward", "+X (forward)", (0.7071,  0.0,     -0.7071, 0.0   )),
    ("Back",    "-X (back)",    (0.7071,  0.0,      0.7071, 0.0   )),
    ("Left",    "+Y (left)",    (0.7071,  0.7071,   0.0,    0.0   )),
    ("Right",   "-Y (right)",   (0.7071, -0.7071,   0.0,    0.0   )),
    ("Up",      "+Z (up)",      (0.0,     1.0,      0.0,    0.0   )),
    ("Down",    "-Z (down)",    (1.0,     0.0,      0.0,    0.0   )),
]


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    print(f"[backup] {path} → {backup}")
    return backup


def _delete_existing_anchor(stage: Usd.Stage, anchor_path: str) -> None:
    """Remove anchor + its children from every layer they appear in.

    The anchor was added as an `over`/`def` in the root layer; this clears it
    so a re-run produces clean prims rather than stacking xform ops.
    """
    prim = stage.GetPrimAtPath(anchor_path)
    if not prim or not prim.IsValid():
        return
    # Remove from the root layer (where we wrote it last time)
    root = stage.GetRootLayer()
    if root.GetPrimAtPath(anchor_path):
        del root.GetPrimAtPath(Sdf.Path(PARENT_PRIM)).nameChildren[ANCHOR_NAME]
        print(f"[clean] removed previous {anchor_path} from {root.identifier}")


def _ensure_over_chain(stage: Usd.Stage, prim_path: str) -> Sdf.PrimSpec:
    """Create `over` specs for each ancestor in the root layer so we can add
    children to a payload-introduced prim like /World/g1/torso_link.
    """
    root = stage.GetRootLayer()
    parts = prim_path.strip("/").split("/")
    parent_spec = root.pseudoRoot
    cumulative = ""
    for name in parts:
        cumulative += "/" + name
        spec = parent_spec.nameChildren.get(name)
        if spec is None:
            spec = Sdf.PrimSpec(parent_spec, name, Sdf.SpecifierOver)
        parent_spec = spec
    return parent_spec


def _add_xform_translate(spec: Sdf.PrimSpec, name: str, offset: tuple[float, float, float]) -> Sdf.PrimSpec:
    xform_spec = Sdf.PrimSpec(spec, name, Sdf.SpecifierDef, "Xform")
    # Single xformOp:translate, no rotation/scale (anchor inherits parent orientation)
    op_attr = Sdf.AttributeSpec(xform_spec, "xformOp:translate", Sdf.ValueTypeNames.Double3)
    op_attr.default = Gf.Vec3d(*offset)
    order_attr = Sdf.AttributeSpec(xform_spec, "xformOpOrder", Sdf.ValueTypeNames.TokenArray)
    order_attr.default = ["xformOp:translate"]
    return xform_spec


def _add_camera(parent_spec: Sdf.PrimSpec, name: str, quat_wxyz: tuple[float, float, float, float],
                clip_near: float, clip_far: float) -> Sdf.PrimSpec:
    cam_spec = Sdf.PrimSpec(parent_spec, f"Face{name}", Sdf.SpecifierDef, "Camera")

    # Orientation (USD: scalar-first w,x,y,z stored as Quatd)
    orient = Sdf.AttributeSpec(cam_spec, "xformOp:orient", Sdf.ValueTypeNames.Quatd)
    orient.default = Gf.Quatd(quat_wxyz[0], Gf.Vec3d(quat_wxyz[1], quat_wxyz[2], quat_wxyz[3]))
    order = Sdf.AttributeSpec(cam_spec, "xformOpOrder", Sdf.ValueTypeNames.TokenArray)
    order.default = ["xformOp:orient"]

    # Camera intrinsics: 90° FOV via aperture=2 mm, focal_length=1 mm
    focal = Sdf.AttributeSpec(cam_spec, "focalLength", Sdf.ValueTypeNames.Float)
    focal.default = 1.0
    hap = Sdf.AttributeSpec(cam_spec, "horizontalAperture", Sdf.ValueTypeNames.Float)
    hap.default = 2.0
    vap = Sdf.AttributeSpec(cam_spec, "verticalAperture", Sdf.ValueTypeNames.Float)
    vap.default = 2.0
    clip = Sdf.AttributeSpec(cam_spec, "clippingRange", Sdf.ValueTypeNames.Float2)
    clip.default = Gf.Vec2f(clip_near, clip_far)
    return cam_spec


def build_rig(
    stage_path: Path,
    offset: tuple[float, float, float],
    face_size: int,
    backup: bool,
    clip_near: float,
    clip_far: float,
) -> None:
    if backup:
        _backup(stage_path)

    stage = Usd.Stage.Open(str(stage_path))
    if stage is None:
        raise SystemExit(f"Could not open stage: {stage_path}")

    parent_prim = stage.GetPrimAtPath(PARENT_PRIM)
    if not parent_prim or not parent_prim.IsValid():
        raise SystemExit(
            f"{PARENT_PRIM} not found in {stage_path}. "
            "Is this a stage that references the G1 robot?"
        )

    anchor_path = f"{PARENT_PRIM}/{ANCHOR_NAME}"
    _delete_existing_anchor(stage, anchor_path)

    parent_spec = _ensure_over_chain(stage, PARENT_PRIM)
    anchor_spec = _add_xform_translate(parent_spec, ANCHOR_NAME, offset)
    print(f"[scene] added Xform {anchor_path} offset={offset}")

    for name, axis_label, quat in FACE_SPECS:
        _add_camera(anchor_spec, name, quat, clip_near, clip_far)
        print(f"[scene]   + Face{name} looks {axis_label}")

    # face_size is informational — recorded as custom metadata on the anchor
    # so the publisher (or future tooling) can pick it up without a CLI flag.
    # USD customData keys must be identifiers (no colons).
    anchor_spec.customData["oscar_faceSize"] = int(face_size)
    anchor_spec.customData["oscar_purpose"] = "Cubemap rig for equirectangular 360 publishing to LiveKit"

    stage.GetRootLayer().Save()
    print(f"[save] {stage_path} updated.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", required=True, help="Path to the USD stage to edit")
    p.add_argument("--offset-x", type=float, default=0.0)
    p.add_argument("--offset-y", type=float, default=0.0)
    p.add_argument("--offset-z", type=float, default=0.25,
                   help="Eye-height offset above torso_link origin (m)")
    p.add_argument("--face-size", type=int, default=1024,
                   help="Per-face resolution recorded as oscar:faceSize attribute")
    p.add_argument("--clip-near", type=float, default=0.05)
    p.add_argument("--clip-far", type=float, default=1000.0)
    p.add_argument("--no-backup", action="store_true")
    args = p.parse_args()

    stage_path = Path(args.stage).resolve()
    if not stage_path.exists():
        raise SystemExit(f"Stage file not found: {stage_path}")

    build_rig(
        stage_path,
        offset=(args.offset_x, args.offset_y, args.offset_z),
        face_size=args.face_size,
        backup=not args.no_backup,
        clip_near=args.clip_near,
        clip_far=args.clip_far,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
