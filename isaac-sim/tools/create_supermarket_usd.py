from pathlib import Path

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics


OUT_DIR = Path("/root/Documents/supermarket_project")
OUT_PATH = OUT_DIR / "supermarket_poc.usd"

G1_ASSET = (
    "https://omniverse-content-production.s3-us-west-2.amazonaws.com/"
    "Assets/Isaac/5.0/Isaac/Robots/Unitree/G1/g1.usd"
)


def set_transform(prim, translate=(0, 0, 0), scale=(1, 1, 1), rotate=(0, 0, 0)):
    xform = UsdGeom.Xformable(prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(*translate))
    xform.AddRotateXYZOp().Set(Gf.Vec3f(*rotate))
    xform.AddScaleOp().Set(Gf.Vec3f(*scale))


def cube(stage, path, name, translate, scale, color, collision=True):
    prim = UsdGeom.Cube.Define(stage, path).GetPrim()
    prim.GetAttribute("size").Set(1.0)
    set_transform(prim, translate=translate, scale=scale)
    prim.CreateAttribute("displayName", Sdf.ValueTypeNames.String).Set(name)
    UsdGeom.Gprim(prim).CreateDisplayColorAttr([Gf.Vec3f(*color)])
    if collision:
        UsdPhysics.CollisionAPI.Apply(prim)
    return prim


def add_label_marker(stage, path, translate, color):
    return cube(
        stage,
        path,
        path.split("/")[-1],
        translate=translate,
        scale=(0.18, 0.18, 0.18),
        color=color,
        collision=False,
    )


def add_shelf_row(stage, parent, row_id, x, y, length, depth=0.72, height=1.75):
    base_path = f"{parent}/shelf_row_{row_id:02d}"
    cube(
        stage,
        f"{base_path}/body",
        f"Rayon {row_id}",
        translate=(x, y, height / 2),
        scale=(depth, length, height),
        color=(0.42, 0.42, 0.38),
    )
    cube(
        stage,
        f"{base_path}/top_trim",
        "Bandeau rayon",
        translate=(x, y, height + 0.06),
        scale=(depth + 0.04, length + 0.04, 0.08),
        color=(0.12, 0.22, 0.34),
    )
    for product_idx, offset in enumerate((-length * 0.28, 0, length * 0.28), start=1):
        cube(
            stage,
            f"{base_path}/product_block_{product_idx:02d}",
            "Bloc produits",
            translate=(x, y + offset, 1.05),
            scale=(depth + 0.08, 0.55, 0.42),
            color=(0.85, 0.52, 0.20),
        )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(OUT_PATH))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    UsdPhysics.Scene.Define(stage, "/World/physicsScene")

    env = UsdGeom.Xform.Define(stage, "/World/supermarket")
    shelves = UsdGeom.Xform.Define(stage, "/World/supermarket/shelves")
    walls = UsdGeom.Xform.Define(stage, "/World/supermarket/walls")
    props = UsdGeom.Xform.Define(stage, "/World/supermarket/props")

    # Store footprint: 24m x 18m. Aisles are roughly 2.4m wide for safe robot tests.
    cube(
        stage,
        "/World/supermarket/floor",
        "Sol supermarche physique",
        translate=(0, 0, -0.05),
        scale=(24.0, 18.0, 0.10),
        color=(0.52, 0.54, 0.52),
    )

    # Low perimeter walls, static colliders.
    cube(stage, "/World/supermarket/walls/back", "Mur fond", (0, 9.1, 1.1), (24.2, 0.2, 2.2), (0.78, 0.78, 0.74))
    cube(stage, "/World/supermarket/walls/front", "Entree ouverte", (0, -9.1, 1.1), (24.2, 0.2, 2.2), (0.78, 0.78, 0.74))
    cube(stage, "/World/supermarket/walls/left", "Mur gauche", (-12.1, 0, 1.1), (0.2, 18.2, 2.2), (0.78, 0.78, 0.74))
    cube(stage, "/World/supermarket/walls/right", "Mur droit", (12.1, 0, 1.1), (0.2, 18.2, 2.2), (0.78, 0.78, 0.74))

    # Shelves: six long rows, giving five main aisles plus perimeter circulation.
    x_positions = [-7.5, -4.5, -1.5, 1.5, 4.5, 7.5]
    for i, x in enumerate(x_positions, start=1):
        add_shelf_row(stage, "/World/supermarket/shelves", i, x=x, y=0.7, length=12.6)

    # End caps and checkout blocks, still simple cuboids for stable physics.
    for i, x in enumerate(x_positions, start=1):
        cube(
            stage,
            f"/World/supermarket/props/endcap_front_{i:02d}",
            "Tete de gondole avant",
            translate=(x, -6.1, 0.65),
            scale=(0.82, 0.62, 1.30),
            color=(0.70, 0.20, 0.22),
        )
        cube(
            stage,
            f"/World/supermarket/props/endcap_back_{i:02d}",
            "Tete de gondole arriere",
            translate=(x, 7.5, 0.65),
            scale=(0.82, 0.62, 1.30),
            color=(0.20, 0.45, 0.58),
        )

    for i, x in enumerate([-8.5, -5.8, -3.1], start=1):
        cube(
            stage,
            f"/World/supermarket/props/checkout_{i:02d}",
            "Caisse",
            translate=(x, -7.8, 0.45),
            scale=(1.7, 0.65, 0.90),
            color=(0.16, 0.16, 0.18),
        )

    # Spawn and waypoints are non-colliding visual markers.
    add_label_marker(stage, "/World/supermarket/markers/robot_spawn", (0, -7.4, 0.12), (0.1, 0.8, 0.2))
    for idx, pos in enumerate([(0, -4.0, 0.12), (0, 0.0, 0.12), (0, 4.2, 0.12), (6.0, 4.2, 0.12)], start=1):
        add_label_marker(stage, f"/World/supermarket/markers/waypoint_{idx:02d}", pos, (0.1, 0.45, 1.0))

    # Optional G1 reference positioned at the spawn marker. It can be deleted if only the environment is needed.
    robot = UsdGeom.Xform.Define(stage, "/World/g1")
    robot.GetPrim().GetPayloads().AddPayload(G1_ASSET)
    set_transform(robot.GetPrim(), translate=(0, -7.4, 0.92), scale=(1, 1, 1))

    # Basic lighting and overview cameras.
    dome = UsdLux.DomeLight.Define(stage, "/World/lights/dome")
    dome.CreateIntensityAttr(500)

    for i, y in enumerate([-5.5, 0.0, 5.5], start=1):
        light = UsdLux.RectLight.Define(stage, f"/World/lights/ceiling_panel_{i:02d}")
        light.CreateIntensityAttr(450)
        light.CreateWidthAttr(18)
        light.CreateHeightAttr(2.2)
        set_transform(light.GetPrim(), translate=(0, y, 4.0), rotate=(0, 0, 0))

    overview = UsdGeom.Camera.Define(stage, "/World/cameras/overview")
    set_transform(overview.GetPrim(), translate=(0, -16, 11), rotate=(60, 0, 0))
    overview.CreateFocalLengthAttr(20)

    aisle_cam = UsdGeom.Camera.Define(stage, "/World/cameras/aisle_preview")
    set_transform(aisle_cam.GetPrim(), translate=(0, -7.0, 1.45), rotate=(90, 0, 0))
    aisle_cam.CreateFocalLengthAttr(18)

    stage.GetRootLayer().Save()
    print(f"created {OUT_PATH}")


if __name__ == "__main__":
    main()
