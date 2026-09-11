"""OSCAR bootstrap ROS 2 — paste once in Window → Script Editor → Run.

Same pipeline as kit_bootstrap_command.py EXCEPT the command output:
  • media publisher   : UNCHANGED (stereo camera-stereo track)   [frozen]
  • command agent     : Quest mapping + watchdog UNCHANGED, but the output
                        controller is Ros2CmdVelController → /cmd_vel
  • g1 locomotion     : subscribes /cmd_vel and drives the official Unitree
                        G1 29-DOF velocity policy.

Rollback to the frozen pipeline: stop everything below, then run the frozen
/root/Documents/sim/kit_bootstrap_command.py (apply="xform").
"""

import importlib
import logging
import sys

SIM_DIR = "/root/Documents/sim"
ROBOT_PRIM = "/World/g1"
CMD_VEL_TOPIC = "/cmd_vel"

G1_POLICY_PATH = "/root/Documents/policies/unitree_g1_29dof_velocity_v0.onnx"

if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)

# Clear stale failed-import cache (livekit installed after Kit start) and any
# previously loaded copies of our modules so this paste always runs fresh code.
for _m in [x for x in list(sys.modules) if x.split(".")[0] in (
    "livekit", "command_agent", "robot_control", "teleop_mapping",
    "g1_locomotion", "kit_bootstrap_360", "livekit_publisher", "frame_sources",
    "equirect",
)]:
    del sys.modules[_m]
importlib.invalidate_caches()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("oscar.bootstrap_ros2")

# 1. Media publisher — frozen code path, untouched.
from kit_bootstrap_360 import start_oscar_media_publisher, stop_oscar_media_publisher  # noqa: E402,F401

start_oscar_media_publisher()
log.info("Media publisher started (frozen stereo pipeline).")

# 2. Command agent — same mapping/safeties, ROS 2 output.
from command_agent import start_oscar_command_agent, stop_oscar_command_agent  # noqa: E402,F401

start_oscar_command_agent(
    apply="ros2",
    cmd_vel_topic=CMD_VEL_TOPIC,
    robot_prim=ROBOT_PRIM,
    token_file="/root/Documents/livekit-command-agent.json",
    topic="oscar.xr.input",
    command_topic="oscar.robot.command",
    watchdog_ms=300,
    control_hz=30,
)
log.info("Command agent started — output is now ROS 2 %s.", CMD_VEL_TOPIC)

# 3. Locomotion — /cmd_vel consumer (policy or log mode).
from g1_locomotion import start_g1_locomotion, stop_g1_locomotion  # noqa: E402,F401

start_g1_locomotion(
    robot_prim=ROBOT_PRIM,
    cmd_vel_topic=CMD_VEL_TOPIC,
    policy_path=G1_POLICY_PATH,
    require_policy=True,
)

print("[oscar] ROS 2 pipeline up:")
print("        video    : camera-stereo (frozen, untouched)")
print("        commands : Quest → LiveKit → command agent → /cmd_vel")
print("        gait     : official Unitree G1 29-DOF velocity policy")
print("        stops    : stop_oscar_media_publisher() / stop_oscar_command_agent() / stop_g1_locomotion()")
