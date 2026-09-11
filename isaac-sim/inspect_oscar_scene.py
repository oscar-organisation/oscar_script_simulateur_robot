"""Inspect the live OSCAR Isaac Sim scene.

Paste this into the Script Editor of the running Isaac Sim session
(Window → Script Editor) and click Run. The output goes to the bottom log
panel; copy it back to share scene details (camera positions, FOV, IPD).

Read-only: no prim is added, removed or modified.
"""

from pxr import UsdGeom, Usd, Gf, UsdLux
import omni.usd


def _quat_to_xyzw(q):
    # USD stores quaternions as (w, x, y, z); LiveKit/three.js convention is (x, y, z, w).
    return (q.imaginary[0], q.imaginary[1], q.imaginary[2], q.real)


def _horizontal_fov_deg(cam: UsdGeom.Camera) -> float:
    """Horizontal FOV in degrees from the camera's intrinsics."""
    fl = cam.GetFocalLengthAttr().Get() or 0.0
    ap = cam.GetHorizontalApertureAttr().Get() or 0.0
    import math
    if fl <= 0.0 or ap <= 0.0:
        return float("nan")
    return math.degrees(2.0 * math.atan((ap / 2.0) / fl))


def _vertical_fov_deg(cam: UsdGeom.Camera) -> float:
    fl = cam.GetFocalLengthAttr().Get() or 0.0
    ap = cam.GetVerticalApertureAttr().Get() or 0.0
    import math
    if fl <= 0.0 or ap <= 0.0:
        return float("nan")
    return math.degrees(2.0 * math.atan((ap / 2.0) / fl))


stage = omni.usd.get_context().get_stage()
if stage is None:
    print("[oscar] No active stage. Open the OSCAR scene first.")
else:
    print("\n========== OSCAR scene inspection ==========")
    print(f"Stage root layer: {stage.GetRootLayer().identifier}")
    print(f"Default prim   : {stage.GetDefaultPrim()}")
    print(f"Time code range: {stage.GetStartTimeCode()} → {stage.GetEndTimeCode()}\n")

    cams = []
    for prim in stage.TraverseAll():
        if not prim.IsA(UsdGeom.Camera):
            continue
        cam = UsdGeom.Camera(prim)
        m = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos = m.ExtractTranslation()
        rot = m.ExtractRotationQuat()  # Gf.Quatd
        cams.append({
            "name": prim.GetName(),
            "path": str(prim.GetPath()),
            "pos": (float(pos[0]), float(pos[1]), float(pos[2])),
            "orient_xyzw": _quat_to_xyzw(rot),
            "focal_length_mm": cam.GetFocalLengthAttr().Get(),
            "h_aperture_mm": cam.GetHorizontalApertureAttr().Get(),
            "v_aperture_mm": cam.GetVerticalApertureAttr().Get(),
            "h_fov_deg": _horizontal_fov_deg(cam),
            "v_fov_deg": _vertical_fov_deg(cam),
            "clipping": tuple(cam.GetClippingRangeAttr().Get() or (0, 0)),
        })

    print(f"Found {len(cams)} camera(s):\n")
    for c in cams:
        print(f"  - {c['name']}  ({c['path']})")
        print(f"      world pos       : ({c['pos'][0]:+.4f}, {c['pos'][1]:+.4f}, {c['pos'][2]:+.4f})  [stage units]")
        print(f"      orient (x,y,z,w): ({c['orient_xyzw'][0]:+.4f}, {c['orient_xyzw'][1]:+.4f}, {c['orient_xyzw'][2]:+.4f}, {c['orient_xyzw'][3]:+.4f})")
        print(f"      focal/aperture  : f={c['focal_length_mm']} mm, hap={c['h_aperture_mm']} mm, vap={c['v_aperture_mm']} mm")
        print(f"      FOV             : H={c['h_fov_deg']:.1f}°  V={c['v_fov_deg']:.1f}°")
        print(f"      clipping        : near={c['clipping'][0]}  far={c['clipping'][1]}")
        print()

    # Pairwise distances — useful to spot the stereo pair and read the IPD.
    if len(cams) >= 2:
        print("Pairwise distances between cameras (stage units):")
        for i, a in enumerate(cams):
            for b in cams[i + 1:]:
                dx = a["pos"][0] - b["pos"][0]
                dy = a["pos"][1] - b["pos"][1]
                dz = a["pos"][2] - b["pos"][2]
                d = (dx * dx + dy * dy + dz * dz) ** 0.5
                print(f"  |{a['name']} − {b['name']}| = {d:.4f}  (Δ = {dx:+.4f}, {dy:+.4f}, {dz:+.4f})")
        print()

    # Stage units → metres conversion factor (default USD is cm in Omniverse).
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    print(f"metersPerUnit = {mpu}  → 1 stage unit = {mpu} m")

    # Look for the robot root and render products to help pick the publisher prims.
    print("\nProbable robot roots (Xform prims at depth 2):")
    default = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    for child in default.GetChildren():
        if child.IsA(UsdGeom.Xform):
            print(f"  - {child.GetPath()}  ({child.GetTypeName()})")

    print("\n========== End inspection ==========\n")
