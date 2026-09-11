"""Headless integration test: ROS 2 Twist -> G1 29-DOF articulation."""

from isaacsim import SimulationApp

app = SimulationApp({"headless": True, "sync_loads": True})

import sys
import traceback

import numpy as np
import omni.usd
from isaacsim.core.api import World
from isaacsim.core.utils.stage import is_stage_loading, open_stage

sys.path.insert(0, "/root/Documents/sim")

from g1_locomotion import G1Locomotion
from robot_control import _bootstrap_rclpy

SCENE = "/root/Documents/supermarket.usd"
POLICY = "/root/Documents/policies/unitree_g1_29dof_velocity_v0.onnx"

locomotion = None
publisher_node = None
try:
    open_stage(SCENE)
    while is_stage_loading():
        app.update()
    auto_graph = omni.usd.get_context().get_stage().GetPrimAtPath("/World/__graphUsingSchemas")
    if auto_graph.IsValid():
        auto_graph.SetActive(False)
    world = World(physics_dt=1.0 / 200.0, rendering_dt=1.0 / 30.0, stage_units_in_meters=1.0)
    world.reset()

    locomotion = G1Locomotion(
        robot_prim="/World/g1",
        cmd_vel_topic="/cmd_vel",
        policy_path=POLICY,
        require_policy=True,
    )
    rclpy = _bootstrap_rclpy()
    from geometry_msgs.msg import Twist

    publisher_node = rclpy.create_node("oscar_g1_smoke_publisher")
    publisher = publisher_node.create_publisher(Twist, "/cmd_vel", 10)
    message = Twist()
    message.linear.x = 0.2

    # Allow local DDS discovery, then drive for four simulated seconds.
    for _ in range(30):
        publisher.publish(message)
        world.step(render=False)
    start_position, _ = locomotion._policy._robot.get_world_pose()
    for _ in range(800):
        publisher.publish(message)
        world.step(render=False)
    end_position, _ = locomotion._policy._robot.get_world_pose()

    if locomotion._listener.count == 0:
        raise RuntimeError("no ROS 2 Twist reached the locomotion subscriber")
    if end_position[2] < 0.65:
        raise RuntimeError(f"robot lost balance: base z={end_position[2]:.3f}")
    displacement = float(np.linalg.norm(end_position[:2] - start_position[:2]))
    if displacement < 0.1:
        raise RuntimeError(f"robot did not walk: displacement={displacement:.3f}")

    print(
        "G1_ROS2_SMOKE_OK",
        "twists=%d" % locomotion._listener.count,
        "end_z=%.3f" % float(end_position[2]),
        "displacement=%.3f" % displacement,
        flush=True,
    )
except Exception:
    traceback.print_exc()
    raise
finally:
    try:
        if locomotion is not None:
            locomotion.close()
        if publisher_node is not None:
            publisher_node.destroy_node()
    except Exception:
        pass
    app.close()
