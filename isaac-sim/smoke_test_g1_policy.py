"""Headless, read-only smoke test for the G1 joint policy in supermarket.usd."""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "sync_loads": True})

import sys
import os

import numpy as np
import omni.usd
from isaacsim.core.api import World
from isaacsim.core.utils.stage import is_stage_loading, open_stage

sys.path.insert(0, "/root/Documents/sim")

from g1_locomotion import DEFAULT_ANGLES, UnitreeG1PolicyController

SCENE = "/root/Documents/supermarket.usd"
POLICY = "/root/Documents/policies/unitree_g1_29dof_velocity_v0.onnx"

try:
    open_stage(SCENE)
    while is_stage_loading():
        app.update()

    # The production stage embeds an auto-start OmniGraph.  Disable graph
    # prims only in this in-memory test stage so no LiveKit/ROS agents compete
    # with the controller under test.  Nothing is saved to supermarket.usd.
    stage = omni.usd.get_context().get_stage()
    graph_prim = stage.GetPrimAtPath("/World/__graphUsingSchemas")
    if graph_prim.IsValid():
        graph_prim.SetActive(False)
    print("disabled_graph=", graph_prim.IsValid(), flush=True)

    world = World(physics_dt=1.0 / 200.0, rendering_dt=1.0 / 30.0, stage_units_in_meters=1.0)
    world.reset()
    controller = UnitreeG1PolicyController("/World/g1", POLICY)
    controller.initialize()

    start_position, _ = controller._robot.get_world_pose()
    hold_only = os.getenv("G1_SMOKE_HOLD_ONLY") == "1"
    hold_initial = os.getenv("G1_SMOKE_HOLD_INITIAL") == "1"
    command = np.array(
        [
            float(os.getenv("G1_SMOKE_VX", "0")),
            float(os.getenv("G1_SMOKE_VY", "0")),
            float(os.getenv("G1_SMOKE_WZ", "0")),
        ],
        dtype=np.float32,
    )
    for _ in range(800):
        if hold_only or hold_initial:
            controller._policy_joints.apply_action(
                joint_positions=controller._initial_positions if hold_initial else DEFAULT_ANGLES,
                joint_velocities=np.zeros(29, dtype=np.float32),
            )
            if controller._extra_joints is not None:
                controller._extra_joints.apply_action(
                    joint_positions=controller._extra_positions,
                    joint_velocities=np.zeros_like(controller._extra_positions),
                )
        else:
            controller.step(1.0 / 200.0, command)
        world.step(render=False)

    end_position, _ = controller._robot.get_world_pose()
    joints = controller._policy_joints.get_joint_positions()
    if not np.isfinite(end_position).all() or not np.isfinite(joints).all():
        raise RuntimeError("non-finite articulation state")

    print(
        "G1_SMOKE_OK",
        "mode=initial" if hold_initial else ("mode=hold" if hold_only else "mode=policy"),
        "cmd=[%.2f,%.2f,%.2f]" % tuple(command),
        "start_z=%.3f" % float(start_position[2]),
        "end_z=%.3f" % float(end_position[2]),
        "drift_xy=%.3f" % float(np.linalg.norm(end_position[:2] - start_position[:2])),
        "joint_range=[%.3f,%.3f]" % (float(joints.min()), float(joints.max())),
        flush=True,
    )
finally:
    app.close()
