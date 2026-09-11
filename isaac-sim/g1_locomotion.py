"""Drive the NVIDIA/Unitree G1 articulation from ROS 2 ``/cmd_vel``.

Command path:
    Quest -> LiveKit -> command_agent -> /cmd_vel -> Unitree 29-DOF policy
    -> joint position targets -> Isaac Sim articulation drives.

The ONNX policy, joint order, gains, posture and 5-frame observation history
match Unitree's official ``unitree_rl_lab`` G1-29dof velocity deployment.  The
robot root transform is never modified by this module.
"""

from __future__ import annotations

import logging
import math
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

import numpy as np

from robot_control import _bootstrap_rclpy

log = logging.getLogger("oscar.g1_locomotion")

CMD_VEL_WATCHDOG_S = 0.5
CONTROL_PERIOD_S = 0.02
SETTLE_DURATION_S = 0.0
PHYSICS_HZ = 200
HISTORY_LENGTH = 5
VENDOR_DIR = "/root/Documents/sim/vendor"

# Isaac Lab's policy order.  It differs from the Unitree SDK motor order and
# from the traversal order of some USD assets, so names are always explicit.
POLICY_JOINT_NAMES = (
    "left_hip_pitch_joint",
    "right_hip_pitch_joint",
    "waist_yaw_joint",
    "left_hip_roll_joint",
    "right_hip_roll_joint",
    "waist_roll_joint",
    "left_hip_yaw_joint",
    "right_hip_yaw_joint",
    "waist_pitch_joint",
    "left_knee_joint",
    "right_knee_joint",
    "left_shoulder_pitch_joint",
    "right_shoulder_pitch_joint",
    "left_ankle_pitch_joint",
    "right_ankle_pitch_joint",
    "left_shoulder_roll_joint",
    "right_shoulder_roll_joint",
    "left_ankle_roll_joint",
    "right_ankle_roll_joint",
    "left_shoulder_yaw_joint",
    "right_shoulder_yaw_joint",
    "left_elbow_joint",
    "right_elbow_joint",
    "left_wrist_roll_joint",
    "right_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "right_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_wrist_yaw_joint",
)

KP = np.array(
    [100, 100, 200, 100, 100, 200, 100, 100, 200, 150, 150, 40, 40, 40, 40,
     40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40, 40],
    dtype=np.float32,
)
KD = np.array(
    [2, 2, 5, 2, 2, 5, 2, 2, 5, 4, 4, 10, 10, 2, 2, 10, 10, 2, 2, 10,
     10, 10, 10, 10, 10, 10, 10, 10, 10],
    dtype=np.float32,
)
DEFAULT_ANGLES = np.array(
    [-0.1, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.3, 0.3, 0.3, 0.3,
     -0.2, -0.2, 0.25, -0.25, 0.0, 0.0, 0.0, 0.0, 0.97, 0.97, 0.15, -0.15,
     0.0, 0.0, 0.0, 0.0],
    dtype=np.float32,
)
EFFORT_LIMITS = np.array(
    [88, 88, 88, 139, 139, 25, 88, 88, 25, 139, 139, 25, 25, 50, 50, 25, 25,
     50, 50, 25, 25, 25, 25, 25, 25, 5, 5, 5, 5],
    dtype=np.float32,
)
ACTION_SCALE = 0.25
ANGULAR_VELOCITY_SCALE = 0.2
JOINT_VELOCITY_SCALE = 0.05
COMMAND_LIMITS = np.array([0.5, 0.3, 0.2], dtype=np.float32)
OBSERVATION_TERM_ORDER = (
    "base_ang_vel",
    "projected_gravity",
    "velocity_commands",
    "joint_pos_rel",
    "joint_vel_rel",
    "last_action",
)


def gravity_in_body_frame(quaternion_wxyz: np.ndarray) -> np.ndarray:
    """Project world gravity into the base frame for scalar-first quaternions."""
    return world_to_body(np.array([0.0, 0.0, -1.0], dtype=np.float32), quaternion_wxyz)


def world_to_body(vector: np.ndarray, quaternion_wxyz: np.ndarray) -> np.ndarray:
    """Rotate a world-frame vector into the robot base frame."""
    q = np.asarray(quaternion_wxyz, dtype=np.float32)
    norm = float(np.linalg.norm(q))
    if norm < 1e-6:
        raise ValueError("invalid zero-length base quaternion")
    w, x, y, z = q / norm
    rotation_body_to_world = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )
    return rotation_body_to_world.T @ np.asarray(vector, dtype=np.float32)


def yaw_from_quaternion_wxyz(quaternion_wxyz: np.ndarray) -> float:
    """Return world-frame yaw in radians for Isaac's scalar-first quaternion."""
    q = np.asarray(quaternion_wxyz, dtype=np.float32)
    norm = float(np.linalg.norm(q))
    if norm < 1e-6:
        raise ValueError("invalid zero-length base quaternion")
    w, x, y, z = q / norm
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def flatten_observation_history(histories: dict[str, deque[np.ndarray]]) -> np.ndarray:
    """Flatten term-by-term, oldest-to-newest, as Unitree's C++ manager does."""
    values = []
    for term in OBSERVATION_TERM_ORDER:
        history = histories[term]
        if len(history) != HISTORY_LENGTH:
            raise ValueError(f"{term} history must contain {HISTORY_LENGTH} frames")
        values.extend(history)
    observation = np.concatenate(values).astype(np.float32, copy=False)
    if observation.shape != (480,):
        raise ValueError(f"Unitree G1 observation must have shape (480,), got {observation.shape}")
    return observation


def configure_physics_rate(hz: int = PHYSICS_HZ) -> None:
    """Set physics frequency in the anonymous session layer (never dirties USD)."""
    import omni.usd
    from pxr import PhysxSchema, Usd, UsdPhysics

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("no USD stage is open")
    scenes = [prim for prim in stage.Traverse() if prim.IsA(UsdPhysics.Scene)]
    if not scenes:
        raise RuntimeError("no PhysicsScene found in the current stage")
    previous_target = stage.GetEditTarget()
    try:
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        for prim in scenes:
            scene_api = PhysxSchema.PhysxSceneAPI.Apply(prim)
            scene_api.CreateTimeStepsPerSecondAttr().Set(int(hz))
    finally:
        stage.SetEditTarget(previous_target)
    log.info("Physics rate set to %d Hz in the session layer", hz)


class _CmdVelListener:
    """Own the ROS node and expose only fresh, bounded velocity commands."""

    def __init__(self, topic: str):
        self._rclpy = _bootstrap_rclpy()
        from geometry_msgs.msg import Twist

        if not self._rclpy.ok():
            self._rclpy.init()
        self.node = self._rclpy.create_node("oscar_g1_locomotion")
        self._latest = np.zeros(3, dtype=np.float32)
        self._received_at = 0.0
        self._count = 0
        self._sub = self.node.create_subscription(Twist, topic, self._on_twist, 10)
        log.info("Subscribed to %s", topic)

    def _on_twist(self, msg) -> None:  # noqa: ANN001
        self._latest = np.clip(
            np.array([msg.linear.x, msg.linear.y, msg.angular.z], dtype=np.float32),
            -COMMAND_LIMITS,
            COMMAND_LIMITS,
        )
        self._received_at = time.monotonic()
        self._count += 1

    def spin_once(self) -> None:
        self._rclpy.spin_once(self.node, timeout_sec=0.0)

    def command(self) -> np.ndarray:
        if time.monotonic() - self._received_at > CMD_VEL_WATCHDOG_S:
            return np.zeros(3, dtype=np.float32)
        return self._latest.copy()

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        try:
            self.node.destroy_node()
        except Exception:  # noqa: BLE001
            pass


class UnitreeG1PolicyController:
    """Official Unitree 29-DOF velocity policy on an existing Isaac articulation."""

    def __init__(self, prim_path: str, policy_path: str):
        if VENDOR_DIR not in sys.path:
            sys.path.insert(0, VENDOR_DIR)
        import onnxruntime as ort
        from isaacsim.core.prims import SingleArticulation

        self._session = ort.InferenceSession(policy_path, providers=["CPUExecutionProvider"])
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name
        if self._session.get_inputs()[0].shape != [1, 480]:
            raise RuntimeError("unexpected Unitree policy input shape")
        if self._session.get_outputs()[0].shape != [1, 29]:
            raise RuntimeError("unexpected Unitree policy output shape")

        self._robot = SingleArticulation(
            prim_path=prim_path,
            name="oscar_g1_policy_articulation",
            reset_xform_properties=False,
        )
        self._policy_joints = None
        self._extra_joints = None
        self._extra_positions = np.empty(0, dtype=np.float32)
        self._initialized = False
        self._initial_positions = DEFAULT_ANGLES.copy()
        self._target_positions = DEFAULT_ANGLES.copy()
        self._previous_action = np.zeros(29, dtype=np.float32)
        self._histories: dict[str, deque[np.ndarray]] = {}
        self._elapsed_s = 0.0
        self._control_accumulator_s = CONTROL_PERIOD_S

    @property
    def initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> None:
        from isaacsim.core.api.articulations import ArticulationSubset

        self._robot.initialize()
        available = set(self._robot.dof_names)
        missing = [name for name in POLICY_JOINT_NAMES if name not in available]
        if missing:
            raise RuntimeError("G1 policy joints missing from articulation: " + ", ".join(missing))

        self._policy_joints = ArticulationSubset(self._robot, list(POLICY_JOINT_NAMES))
        extra_names = [name for name in self._robot.dof_names if name not in POLICY_JOINT_NAMES]
        self._extra_joints = ArticulationSubset(self._robot, extra_names) if extra_names else None
        self._initial_positions = np.asarray(self._policy_joints.get_joint_positions(), dtype=np.float32)
        if not np.isfinite(self._initial_positions).all():
            raise RuntimeError("G1 returned non-finite initial joint positions")

        controller = self._robot.get_articulation_controller()
        all_kp, all_kd = controller.get_gains()
        all_kp = np.asarray(all_kp, dtype=np.float32).copy()
        all_kd = np.asarray(all_kd, dtype=np.float32).copy()
        indices = np.asarray(self._policy_joints.joint_indices, dtype=np.int64)
        all_kp[indices] = KP
        all_kd[indices] = KD
        controller.set_gains(kps=all_kp, kds=all_kd, save_to_usd=False)
        controller.set_max_efforts(values=EFFORT_LIMITS, joint_indices=indices)

        if self._extra_joints is not None:
            self._extra_positions = np.asarray(
                self._extra_joints.get_joint_positions(), dtype=np.float32
            ).copy()

        # In the physical Unitree state machine this posture is reached while
        # the robot is supported.  Isaac starts unsupported, so seed the joint
        # state atomically before the first simulated policy step.
        self._policy_joints.set_joint_positions(DEFAULT_ANGLES.copy())
        self._policy_joints.set_joint_velocities(np.zeros(29, dtype=np.float32))
        self._target_positions = DEFAULT_ANGLES.copy()
        self._previous_action.fill(0.0)
        self._histories.clear()
        self._elapsed_s = 0.0
        self._control_accumulator_s = CONTROL_PERIOD_S
        self._initialized = True
        log.info(
            "G1 articulation initialized: %d DOF total, 29 policy joints, %d extra joints held",
            self._robot.num_dof,
            len(extra_names),
        )

    def reset(self) -> None:
        self._initialized = False
        self._policy_joints = None
        self._extra_joints = None
        self._extra_positions = np.empty(0, dtype=np.float32)
        self._previous_action.fill(0.0)
        self._histories.clear()
        self._elapsed_s = 0.0
        self._control_accumulator_s = CONTROL_PERIOD_S

    def _current_terms(self, command: np.ndarray) -> dict[str, np.ndarray]:
        if self._policy_joints is None:
            raise RuntimeError("G1 policy joints are not initialized")
        joint_positions = np.asarray(self._policy_joints.get_joint_positions(), dtype=np.float32)
        joint_velocities = np.asarray(self._policy_joints.get_joint_velocities(), dtype=np.float32)
        _, orientation = self._robot.get_world_pose()
        angular_velocity_world = np.asarray(self._robot.get_angular_velocity(), dtype=np.float32)
        return {
            "base_ang_vel": world_to_body(angular_velocity_world, orientation) * ANGULAR_VELOCITY_SCALE,
            "projected_gravity": gravity_in_body_frame(orientation),
            "velocity_commands": np.asarray(command, dtype=np.float32),
            "joint_pos_rel": joint_positions - DEFAULT_ANGLES,
            "joint_vel_rel": joint_velocities * JOINT_VELOCITY_SCALE,
            "last_action": self._previous_action.copy(),
        }

    def _update_observation(self, command: np.ndarray) -> np.ndarray:
        terms = self._current_terms(command)
        if not self._histories:
            self._histories = {
                name: deque([value.copy() for _ in range(HISTORY_LENGTH)], maxlen=HISTORY_LENGTH)
                for name, value in terms.items()
            }
        else:
            for name, value in terms.items():
                self._histories[name].append(value.copy())
        return flatten_observation_history(self._histories)

    def step(self, dt: float, command: np.ndarray) -> None:
        if not self._initialized or self._policy_joints is None:
            raise RuntimeError("G1 policy controller is not initialized")

        step_dt = max(0.0, min(float(dt), 0.1))
        self._elapsed_s += step_dt

        if SETTLE_DURATION_S > 0.0 and self._elapsed_s < SETTLE_DURATION_S:
            blend = min(1.0, self._elapsed_s / SETTLE_DURATION_S)
            smooth = blend * blend * (3.0 - 2.0 * blend)
            self._target_positions = (
                self._initial_positions * (1.0 - smooth) + DEFAULT_ANGLES * smooth
            ).astype(np.float32)
        else:
            self._control_accumulator_s += step_dt
            if self._control_accumulator_s >= CONTROL_PERIOD_S:
                self._control_accumulator_s %= CONTROL_PERIOD_S
                observation = self._update_observation(command)
                action = self._session.run(
                    [self._output_name],
                    {self._input_name: observation.reshape(1, 480)},
                )[0].reshape(-1).astype(np.float32)
                if action.shape != (29,) or not np.isfinite(action).all():
                    raise RuntimeError(f"invalid G1 policy action: shape={action.shape}")
                self._previous_action = np.clip(action, -5.0, 5.0)
                self._target_positions = DEFAULT_ANGLES + self._previous_action * ACTION_SCALE

        self._policy_joints.apply_action(
            joint_positions=self._target_positions,
            joint_velocities=np.zeros(29, dtype=np.float32),
        )
        if self._extra_joints is not None:
            self._extra_joints.apply_action(
                joint_positions=self._extra_positions,
                joint_velocities=np.zeros_like(self._extra_positions),
            )

    def motion_state(self) -> tuple[float, float]:
        """Return measured base yaw and yaw rate for locomotion diagnostics."""
        _, orientation = self._robot.get_world_pose()
        angular_velocity_world = np.asarray(self._robot.get_angular_velocity(), dtype=np.float32)
        angular_velocity_body = world_to_body(angular_velocity_world, orientation)
        return yaw_from_quaternion_wxyz(orientation), float(angular_velocity_body[2])


class G1Locomotion:
    def __init__(
        self,
        robot_prim: str = "/World/g1",
        cmd_vel_topic: str = "/cmd_vel",
        policy_path: Optional[str] = None,
        env_yaml: Optional[str] = None,
        require_policy: bool = True,
    ):
        if env_yaml:
            log.warning("env_yaml is ignored: the official Unitree 29-DOF contract is built in")
        if require_policy and not policy_path:
            raise RuntimeError("G1 articulation control requires a Unitree ONNX policy")
        if policy_path and not Path(policy_path).is_file():
            raise FileNotFoundError(f"Missing G1 policy file: {policy_path}")

        self.mode = "unitree-29dof-policy" if policy_path else "log"
        self._listener = _CmdVelListener(cmd_vel_topic)
        self._policy = UnitreeG1PolicyController(robot_prim, policy_path) if policy_path else None
        self._last_log = 0.0
        self._last_error = ""
        self._physx_sub = None
        self._timeline_sub = None

        import omni.physx
        import omni.timeline

        if self._policy is not None:
            configure_physics_rate()
        self._physx_sub = omni.physx.get_physx_interface().subscribe_physics_step_events(
            self._on_physics_step
        )
        if self._policy is not None:
            timeline = omni.timeline.get_timeline_interface()
            self._timeline_sub = timeline.get_timeline_event_stream().create_subscription_to_pop(
                self._on_timeline_event,
                name="oscar_g1_policy_timeline",
            )
        log.info("G1Locomotion active (mode=%s, robot=%s)", self.mode, robot_prim)

    def _on_timeline_event(self, event) -> None:  # noqa: ANN001
        import omni.timeline

        if self._policy is not None and event.type == int(omni.timeline.TimelineEventType.STOP):
            self._policy.reset()
            log.info("Timeline stopped; G1 policy handles reset")

    def _on_physics_step(self, dt: float) -> None:
        self._listener.spin_once()
        command = self._listener.command()
        if self._policy is None:
            now = time.monotonic()
            if now - self._last_log > 2.0:
                log.info(
                    "cmd_vel log mode: vx=%.2f vy=%.2f wz=%.2f (rx=%d)",
                    command[0], command[1], command[2], self._listener.count,
                )
                self._last_log = now
            return
        try:
            if not self._policy.initialized:
                self._policy.initialize()
            self._policy.step(dt, command)
            now = time.monotonic()
            if now - self._last_log > 2.0:
                yaw, yaw_rate = self._policy.motion_state()
                log.info(
                    "29-DOF joint control: vx=%.2f vy=%.2f wz=%.2f "
                    "measured_yaw=%.1fdeg yaw_rate=%.1fdeg/s (cmd_vel rx=%d)",
                    command[0], command[1], command[2],
                    math.degrees(yaw), math.degrees(yaw_rate), self._listener.count,
                )
                self._last_log = now
                self._last_error = ""
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            message = f"{type(exc).__name__}: {exc}"
            if message != self._last_error or now - self._last_log > 1.0:
                log.error("G1 joint-control step failed: %s", message)
                self._last_error = message
                self._last_log = now

    def close(self) -> None:
        self._physx_sub = None
        self._timeline_sub = None
        self._listener.close()
        if self._policy is not None:
            self._policy.reset()
        log.info("G1Locomotion stopped")


_state: dict[str, Any] = {"node": None}


def start_g1_locomotion(**kwargs: Any) -> G1Locomotion:
    if _state.get("node") is not None:
        log.warning("G1 locomotion already running")
        return _state["node"]
    node = G1Locomotion(**kwargs)
    _state["node"] = node
    return node


def stop_g1_locomotion() -> None:
    node = _state.pop("node", None)
    if node is None:
        log.warning("No G1 locomotion running")
        return
    node.close()
