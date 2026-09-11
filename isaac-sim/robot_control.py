"""Robot control adapters for OSCAR teleoperation.

The first POC adapter is intentionally conservative: it moves a root Xform in
the live Isaac stage. This proves the end-to-end joystick path without
pretending to solve full humanoid gait control for the Unitree G1.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from teleop_mapping import RobotArmCommand, RobotVelocityCommand, ZERO_ARM_COMMAND


log = logging.getLogger(__name__)


class RobotController:
    """Minimal controller interface used by the LiveKit command agent."""

    def apply(self, command: RobotVelocityCommand, dt: float) -> None:  # noqa: B027
        return None

    def apply_arm(self, command: RobotArmCommand, dt: float) -> None:  # noqa: B027
        return None

    def stop(self) -> None:
        self.apply(
            RobotVelocityCommand(
                vx=0.0,
                vy=0.0,
                wz=0.0,
                deadman=False,
                estop=False,
                active=False,
                source_seq=None,
                source_time_ms=None,
                reason="stop",
            ),
            0.0,
        )
        self.apply_arm(ZERO_ARM_COMMAND, 0.0)


class LogOnlyController(RobotController):
    """Controller used while validating LiveKit input without moving Isaac."""

    def __init__(self, log_every: int = 15):
        self._count = 0
        self._log_every = max(1, log_every)

    def apply(self, command: RobotVelocityCommand, dt: float) -> None:
        self._count += 1
        if self._count % self._log_every == 0 or command.estop:
            log.info(
                "cmd vx=%.3f vy=%.3f wz=%.3f active=%s reason=%s dt=%.3f",
                command.vx,
                command.vy,
                command.wz,
                command.active,
                command.reason,
                dt,
            )


@dataclass
class IsaacXformControllerConfig:
    prim_path: str = "/World/g1"
    lock_z: bool = True
    yaw_offset_rad: float = 0.0


class IsaacXformController(RobotController):
    """Kinematic root mover for Isaac Sim stages.

    It updates `xformOp:translate` and `xformOp:rotateXYZ` on the robot root.
    This is appropriate for the vertical-slice demo and can later be replaced
    by a ROS2 `/cmd_vel` or Unitree gait controller.
    """

    def __init__(self, config: IsaacXformControllerConfig):
        self.config = config
        self._stage = None
        self._xform = None
        self._translate_op = None
        self._rotate_op = None
        self._z = None
        self._yaw = config.yaw_offset_rad
        self._init_isaac()

    def _init_isaac(self) -> None:
        try:
            import omni.usd
            from pxr import Gf, UsdGeom
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("IsaacXformController must run inside Isaac Sim / Kit") from exc

        self._gf = Gf
        self._usd_geom = UsdGeom
        self._stage = omni.usd.get_context().get_stage()
        prim = self._stage.GetPrimAtPath(self.config.prim_path)
        if not prim or not prim.IsValid():
            raise RuntimeError(f"Robot prim not found: {self.config.prim_path}")

        self._xform = UsdGeom.Xformable(prim)
        self._translate_op = self._find_or_add_op("xformOp:translate", self._xform.AddTranslateOp)
        self._rotate_op = self._find_or_add_op("xformOp:rotateXYZ", self._xform.AddRotateXYZOp)
        self._ensure_op_order()

        current_t = self._translate_op.Get()
        if current_t is None:
            current_t = Gf.Vec3d(0.0, 0.0, 0.0)
            self._translate_op.Set(current_t)
        self._z = float(current_t[2])

        current_r = self._rotate_op.Get()
        if current_r is not None:
            self._yaw = math.radians(float(current_r[2]))
        log.info("IsaacXformController ready on %s at z=%.3f yaw=%.1fdeg", self.config.prim_path, self._z, math.degrees(self._yaw))

    def _find_or_add_op(self, op_name: str, add_fn):
        for op in self._xform.GetOrderedXformOps():
            if op.GetOpName() == op_name:
                return op
        return add_fn()

    def _ensure_op_order(self) -> None:
        ops = []
        for wanted in (self._translate_op, self._rotate_op):
            if wanted is not None and wanted not in ops:
                ops.append(wanted)
        self._xform.SetXformOpOrder(ops)

    def apply(self, command: RobotVelocityCommand, dt: float) -> None:
        if dt <= 0.0:
            return

        current_t = self._translate_op.Get() or self._gf.Vec3d(0.0, 0.0, self._z or 0.0)
        x = float(current_t[0])
        y = float(current_t[1])
        z = self._z if self.config.lock_z and self._z is not None else float(current_t[2])

        self._yaw += command.wz * dt
        cos_y = math.cos(self._yaw)
        sin_y = math.sin(self._yaw)

        dx = (command.vx * cos_y - command.vy * sin_y) * dt
        dy = (command.vx * sin_y + command.vy * cos_y) * dt

        self._translate_op.Set(self._gf.Vec3d(x + dx, y + dy, z))
        self._rotate_op.Set(self._gf.Vec3f(0.0, 0.0, math.degrees(self._yaw)))


# ════════════════════════════════════════════════════════════════════════════
# ROS 2 output — replaces the Xform mover without touching the LiveKit side.
# ════════════════════════════════════════════════════════════════════════════

_ROS2_BRIDGE_JAZZY = "/isaac-sim/exts/isaacsim.ros2.bridge/jazzy"


def _bootstrap_rclpy():
    """Make the rclpy bundled with Isaac Sim importable inside Kit.

    Preference order:
    1. rclpy already importable (system ROS sourced, or a prior bootstrap).
    2. Enable the `isaacsim.ros2.bridge` extension — it loads the internal
       ROS 2 (Jazzy) native libraries into the process — then add the bundled
       rclpy package to sys.path and import it.
    """
    import importlib
    import os
    import sys

    try:
        import rclpy  # noqa: F401
        return importlib.import_module("rclpy")
    except Exception:  # noqa: BLE001
        pass

    os.environ.setdefault("ROS_DISTRO", "jazzy")
    os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    lib_dir = f"{_ROS2_BRIDGE_JAZZY}/lib"
    prev = os.environ.get("LD_LIBRARY_PATH", "")
    if lib_dir not in prev:
        os.environ["LD_LIBRARY_PATH"] = f"{lib_dir}:{prev}" if prev else lib_dir

    try:
        import omni.kit.app

        manager = omni.kit.app.get_app().get_extension_manager()
        if not manager.is_extension_enabled("isaacsim.ros2.bridge"):
            manager.set_extension_enabled_immediate("isaacsim.ros2.bridge", True)
            log.info("Enabled isaacsim.ros2.bridge (internal ROS 2 Jazzy libs)")
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not enable ros2 bridge extension: %s", exc)

    rclpy_path = f"{_ROS2_BRIDGE_JAZZY}/rclpy"
    if rclpy_path not in sys.path:
        sys.path.insert(0, rclpy_path)

    try:
        return importlib.import_module("rclpy")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "rclpy import failed even after enabling isaacsim.ros2.bridge. "
            "If Kit was started without the bridge, restart the container with "
            f"LD_LIBRARY_PATH={lib_dir} in the environment. Original: {exc}"
        ) from exc


@dataclass
class Ros2CmdVelControllerConfig:
    topic: str = "/cmd_vel"
    node_name: str = "oscar_teleop_bridge"
    # Safety clamps applied on top of teleop_mapping (belt and braces — the
    # Quest-side mapping already limits, this bounds whatever reaches ROS).
    max_vx: float = 1.0
    max_vy: float = 0.5
    max_wz: float = 1.5


class Ros2CmdVelController(RobotController):
    """Publishes the mapped velocity command as geometry_msgs/Twist on /cmd_vel.

    Drop-in replacement for IsaacXformController: same `apply(command, dt)`
    contract, same watchdog/deadman semantics upstream. When the command is
    inactive (deadman released, watchdog stop, estop) it publishes an explicit
    zero Twist so downstream consumers halt deterministically.
    """

    def __init__(self, config: Ros2CmdVelControllerConfig | None = None):
        self.config = config or Ros2CmdVelControllerConfig()
        self._rclpy = _bootstrap_rclpy()
        from geometry_msgs.msg import Twist  # import after bootstrap

        self._twist_cls = Twist
        if not self._rclpy.ok():
            self._rclpy.init()
        self._node = self._rclpy.create_node(self.config.node_name)
        self._pub = self._node.create_publisher(Twist, self.config.topic, 10)
        self._arm_joint_cls = None
        self._arm_pub = None
        self._arm_angles = [90.0, 120.0, 10.0, 20.0, 90.0, 0.0]
        self._arm_limits = [(0.0, 180.0)] * 4 + [(0.0, 270.0), (0.0, 180.0)]
        self._arm_publish_accumulator = 0.0
        try:
            from arm_msgs.msg import ArmJoint

            self._arm_joint_cls = ArmJoint
            self._arm_pub = self._node.create_publisher(ArmJoint, "/arm_joint", 10)
            log.info("ROSMASTER arm control ready — publishing /arm_joint")
        except Exception as exc:  # noqa: BLE001
            log.info("ROS arm control unavailable in this runtime: %s", exc)
        self._published = 0
        log.info(
            "Ros2CmdVelController ready — publishing %s from node %s",
            self.config.topic,
            self.config.node_name,
        )

    def apply(self, command: RobotVelocityCommand, dt: float) -> None:
        msg = self._twist_cls()
        if command.active and not command.estop:
            c = self.config
            msg.linear.x = max(-c.max_vx, min(c.max_vx, float(command.vx)))
            msg.linear.y = max(-c.max_vy, min(c.max_vy, float(command.vy)))
            msg.angular.z = max(-c.max_wz, min(c.max_wz, float(command.wz)))
        # inactive / estop → all fields stay 0.0: explicit stop for consumers
        self._pub.publish(msg)
        self._published += 1
        if self._published % 150 == 0:  # ~every 5 s at 30 Hz
            log.info(
                "/cmd_vel #%d vx=%.2f vy=%.2f wz=%.2f active=%s reason=%s",
                self._published, msg.linear.x, msg.linear.y, msg.angular.z,
                command.active, command.reason,
            )

    def apply_arm(self, command: RobotArmCommand, dt: float) -> None:
        if self._arm_pub is None or self._arm_joint_cls is None or dt <= 0.0:
            return
        if not command.mode or not command.active:
            self._arm_publish_accumulator = 0.0
            return

        changed: list[int] = []
        for index, rate in enumerate(command.rates_dps):
            if abs(rate) <= 1e-6:
                continue
            lower, upper = self._arm_limits[index]
            target = max(lower, min(upper, self._arm_angles[index] + rate * dt))
            if abs(target - self._arm_angles[index]) > 1e-6:
                self._arm_angles[index] = target
                changed.append(index)

        self._arm_publish_accumulator += dt
        if not changed or self._arm_publish_accumulator < 0.1:
            return
        self._arm_publish_accumulator = 0.0
        for index in changed:
            msg = self._arm_joint_cls()
            msg.id = index + 1
            msg.joint = int(round(self._arm_angles[index]))
            msg.time = 200
            self._arm_pub.publish(msg)
            log.info("/arm_joint id=%d target=%d", msg.id, msg.joint)

    def stop(self) -> None:
        try:
            super().stop()  # publishes one final zero Twist via apply()
        finally:
            try:
                self._node.destroy_node()
            except Exception:  # noqa: BLE001
                pass
        log.info("Ros2CmdVelController stopped (node destroyed)")
