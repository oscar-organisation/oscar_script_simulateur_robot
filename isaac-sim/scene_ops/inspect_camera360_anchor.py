"""Read-only check that the Camera360Anchor rig is wired up correctly.

Run after add_camera360_anchor.py and confirm:
- Anchor exists at the expected path
- 6 face cameras with the expected names and orientations
- World position matches the parent + offset
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from pxr import Usd, UsdGeom


PARENT_PRIM = "/World/g1/torso_link"
ANCHOR_NAME = "Camera360Anchor"
EXPECTED_FACES = ["Forward", "Back", "Left", "Right", "Up", "Down"]


def _quat_xyzw(q):
    return (q.imaginary[0], q.imaginary[1], q.imaginary[2], q.real)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", required=True)
    args = p.parse_args()

    stage = Usd.Stage.Open(str(Path(args.stage).resolve()))
    if stage is None:
        raise SystemExit(f"Cannot open {args.stage}")

    anchor_path = f"{PARENT_PRIM}/{ANCHOR_NAME}"
    anchor = stage.GetPrimAtPath(anchor_path)
    if not anchor or not anchor.IsValid():
        print(f"[FAIL] anchor not found at {anchor_path}")
        return 1

    parent = stage.GetPrimAtPath(PARENT_PRIM)
    parent_world = UsdGeom.Xformable(parent).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    anchor_world = UsdGeom.Xformable(anchor).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    pwt = parent_world.ExtractTranslation()
    awt = anchor_world.ExtractTranslation()
    print(f"[ok] anchor {anchor_path}")
    print(f"      parent  world pos = ({pwt[0]:+.4f}, {pwt[1]:+.4f}, {pwt[2]:+.4f})")
    print(f"      anchor  world pos = ({awt[0]:+.4f}, {awt[1]:+.4f}, {awt[2]:+.4f})")
    print(f"      anchor  local offset = ({awt[0]-pwt[0]:+.4f}, {awt[1]-pwt[1]:+.4f}, {awt[2]-pwt[2]:+.4f})")

    # GetAllChildren (not GetChildren) — the latter filters by IsDefined which
    # returns False when running outside Isaac because the G1 payload URL is
    # unreachable from a generic Python env. Inside Isaac the payload resolves
    # and the cameras compose normally.
    found = sorted(
        c.GetName() for c in anchor.GetAllChildren() if c.GetTypeName() == "Camera"
    )
    expected = sorted(f"Face{n}" for n in EXPECTED_FACES)
    missing = set(expected) - set(found)
    extra = set(found) - set(expected)
    if missing or extra:
        print(f"[FAIL] cameras mismatch — missing={sorted(missing)} extra={sorted(extra)}")
        return 1
    print(f"[ok] 6 face cameras present: {found}")

    for child in anchor.GetAllChildren():
        if child.GetTypeName() != "Camera":
            continue
        cam = UsdGeom.Camera(child)
        m = UsdGeom.Xformable(child).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        rot = m.ExtractRotationQuat()
        x, y, z, w = _quat_xyzw(rot)
        fl = cam.GetFocalLengthAttr().Get() or 0.0
        ha = cam.GetHorizontalApertureAttr().Get() or 0.0
        hfov = math.degrees(2 * math.atan((ha / 2) / fl)) if fl > 0 else 0.0
        print(f"  {child.GetName():8s}  world quat(x,y,z,w)=({x:+.3f}, {y:+.3f}, {z:+.3f}, {w:+.3f})  HFOV={hfov:.1f}°")

    custom = anchor.GetCustomData() or {}
    purpose = custom.get("oscar_purpose")
    face_size = custom.get("oscar_faceSize")
    if purpose:
        print(f"[meta] purpose: {purpose}")
    if face_size:
        print(f"[meta] face size: {face_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
