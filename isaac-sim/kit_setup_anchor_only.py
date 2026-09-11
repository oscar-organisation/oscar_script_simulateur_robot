"""Standalone Script Editor snippet — creates the 360 camera rig only.

Paste in Window → Script Editor and click Run. No LiveKit, no asyncio:
just adds /World/g1/torso_link/Camera360Anchor with 6 face cameras as
children. You can then move/zoom around them in the viewport to verify
the placement is right before launching the publisher.

After running this, you should see 6 new camera entries in the Stage panel:
  /World/g1/torso_link/Camera360Anchor/FaceForward    (looks +X = robot front)
  /World/g1/torso_link/Camera360Anchor/FaceBack       (looks -X = robot back)
  /World/g1/torso_link/Camera360Anchor/FaceLeft       (looks +Y = robot left)
  /World/g1/torso_link/Camera360Anchor/FaceRight      (looks -Y = robot right)
  /World/g1/torso_link/Camera360Anchor/FaceUp         (looks +Z = up)
  /World/g1/torso_link/Camera360Anchor/FaceDown       (looks -Z = down)

Switch any of them via the Cameras dropdown in the viewport to verify.

Re-running this snippet refreshes the cameras (it deletes + recreates the rig).
"""

from pxr import UsdGeom, Gf, Sdf
import omni.usd
from isaacsim.sensors.camera import Camera
import numpy as np

PARENT_PRIM = "/World/g1/torso_link"
ANCHOR_NAME = "Camera360Anchor"
ANCHOR_OFFSET = (0.0, 0.0, 0.25)
FACE_SIZE = 1024

# (face_name, axis_label, quaternion w,x,y,z scalar-first)
FACE_SPECS = [
    ("Forward", "+X", (0.7071, 0.0,    -0.7071, 0.0)),
    ("Back",    "-X", (0.7071, 0.0,     0.7071, 0.0)),
    ("Left",    "+Y", (0.7071, 0.7071,  0.0,    0.0)),
    ("Right",   "-Y", (0.7071, -0.7071, 0.0,    0.0)),
    ("Up",      "+Z", (0.0,    1.0,     0.0,    0.0)),
    ("Down",    "-Z", (1.0,    0.0,     0.0,    0.0)),
]

stage = omni.usd.get_context().get_stage()
parent = stage.GetPrimAtPath(PARENT_PRIM)
if not parent or not parent.IsValid():
    raise RuntimeError(
        f"{PARENT_PRIM} not found. Open the supermarket scene with the G1 first."
    )

anchor_path = f"{PARENT_PRIM}/{ANCHOR_NAME}"
# Refresh: delete any previous anchor at this path
if stage.GetPrimAtPath(anchor_path):
    stage.RemovePrim(anchor_path)

anchor = UsdGeom.Xform.Define(stage, Sdf.Path(anchor_path)).GetPrim()
x = UsdGeom.Xformable(anchor)
x.ClearXformOpOrder()
x.AddTranslateOp().Set(Gf.Vec3d(*ANCHOR_OFFSET))
print(f"[oscar] Anchor created: {anchor_path}  offset={ANCHOR_OFFSET}")

for name, axis, quat in FACE_SPECS:
    cam = Camera(
        prim_path=f"{anchor_path}/Face{name}",
        resolution=(FACE_SIZE, FACE_SIZE),
        orientation=np.array(quat),  # w, x, y, z (scalar-first)
    )
    cam.initialize()
    cam.set_horizontal_aperture(2.0)  # 90° FOV at focal_length 1
    cam.set_focal_length(1.0)
    cam.set_clipping_range(0.05, 1000.0)
    print(f"[oscar] Created Face{name} → looks {axis}")

print("[oscar] Done. Switch the viewport to any Face* camera to verify the framing.")
