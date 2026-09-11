"""OSCAR unified bootstrap — paste once in Window → Script Editor → Run.

Starts in parallel on Kit's existing asyncio loop:
  • the LiveKit command agent  (Quest joystick → /World/g1 motion)
  • the LiveKit media publisher (stereo cameras → camera-stereo track)

Both share the same Kit process and the same event loop. The agents stop
independently with `stop_oscar_command_agent()` / `stop_oscar_media_publisher()`.

Auto-launched at sim startup if hooked from the sim launcher.
"""

import importlib
import logging
import sys

SIM_DIR = "/root/Documents/sim"
ROBOT_PRIM = "/World/g1"

if SIM_DIR not in sys.path:
    sys.path.insert(0, SIM_DIR)

# If livekit was pip-installed AFTER Kit started, Kit has cached the failed
# import in sys.modules. Drop those entries and reset the importer so the
# fresh site-packages takes effect without restarting Kit.
for _stale in [m for m in list(sys.modules) if m == "livekit" or m.startswith("livekit.")]:
    del sys.modules[_stale]
importlib.invalidate_caches()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("oscar.bootstrap")

# 1. Command agent — subscribes to oscar.xr.input, drives the G1 root Xform.
from command_agent import start_oscar_command_agent, stop_oscar_command_agent  # noqa: E402,F401

start_oscar_command_agent(
    apply="xform",
    robot_prim=ROBOT_PRIM,
    token_file="/root/Documents/livekit-command-agent.json",
    topic="oscar.xr.input",
    command_topic="oscar.robot.command",
    watchdog_ms=300,
    control_hz=30,
)
log.info("Command agent started — grip + sticks moves the robot.")

# 2. Media publisher — pushes stereo camera-stereo track to the LiveKit room.
from kit_bootstrap_360 import start_oscar_media_publisher, stop_oscar_media_publisher  # noqa: E402,F401

start_oscar_media_publisher()
log.info("Media publisher started — camera-stereo @ 2560x720, 30 fps.")

print("[oscar] OSCAR fully connected:")
print("        • command agent  → stop with stop_oscar_command_agent()")
print("        • media publisher → stop with stop_oscar_media_publisher()")
