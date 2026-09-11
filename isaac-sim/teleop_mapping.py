"""Map OSCAR XR controller packets to robot velocity commands.

The browser publishes compact packets on the LiveKit topic `oscar.xr.input`.
This module is deliberately independent from Isaac Sim and LiveKit so the
mapping can be tested on a laptop before it drives the simulated robot.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class TeleopMappingConfig:
    """Operator input mapping and safety limits."""

    deadzone: float = 0.12
    max_vx_mps: float = 0.40
    max_vy_mps: float = 0.20
    max_wz_radps: float = 0.80
    left_axes: tuple[int, int] = (0, 1)
    right_axes: tuple[int, int] = (0, 1)
    deadman_buttons: tuple[int, ...] = (1,)
    # Quest button indexes differ between WebXR runtimes. 4/5 produced false
    # emergency stops in the current headset trace, so remote estop stays
    # disabled until the calibration overlay confirms stable indexes. Releasing
    # the grip and the watchdog still stop motion immediately.
    estop_buttons: tuple[int, ...] = ()
    require_deadman: bool = True
    allow_lateral: bool = True
    invert_left_x: bool = False
    invert_left_y: bool = True
    invert_right_x: bool = True


@dataclass(frozen=True)
class ArmTeleopMappingConfig:
    """Desktop gamepad mapping for the ROSMASTER six-axis arm."""

    deadzone: float = 0.18
    arm_mode_button: int = 4  # DualSense L1
    dpad_left_button: int = 14
    dpad_right_button: int = 15
    gripper_open_button: int = 6  # L2
    gripper_close_button: int = 7  # R2
    vr_trigger_button: int = 0
    vr_grip_button: int = 1
    vr_joint5_button: int = 4  # X/A on Quest Touch controllers
    max_joint_rate_dps: float = 20.0
    max_gripper_rate_dps: float = 30.0


@dataclass(frozen=True)
class RobotVelocityCommand:
    """Velocity command in the robot local frame."""

    vx: float
    vy: float
    wz: float
    deadman: bool
    estop: bool
    active: bool
    source_seq: int | None
    source_time_ms: float | None
    reason: str = "ok"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update({"v": 1, "type": "robot-velocity-command"})
        return payload


@dataclass(frozen=True)
class RobotArmCommand:
    """Requested arm joint rates in degrees per second."""

    mode: bool
    rates_dps: tuple[float, float, float, float, float, float]
    active: bool
    source_seq: int | None
    source_time_ms: float | None
    reason: str = "ok"


ZERO_COMMAND = RobotVelocityCommand(
    vx=0.0,
    vy=0.0,
    wz=0.0,
    deadman=False,
    estop=False,
    active=False,
    source_seq=None,
    source_time_ms=None,
    reason="zero",
)

ZERO_ARM_COMMAND = RobotArmCommand(
    mode=False,
    rates_dps=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    active=False,
    source_seq=None,
    source_time_ms=None,
    reason="zero",
)


def map_xr_input_to_velocity(
    payload: Mapping[str, Any],
    config: TeleopMappingConfig | None = None,
) -> RobotVelocityCommand:
    """Convert one `xr-input` payload into a bounded velocity command.

    Mapping used for the POC:
    - left stick Y -> forward/backward (`vx`)
    - left stick X -> lateral (`vy`) when `allow_lateral` is true
    - right stick X -> yaw (`wz`)
    - grip button held -> deadman switch
    - B/Y-style buttons -> emergency stop when present
    """

    cfg = config or TeleopMappingConfig()
    if payload.get("type") != "xr-input":
        return _stopped(payload, False, False, "ignored-packet-type")

    controllers = payload.get("controllers")
    if not isinstance(controllers, Sequence):
        return _stopped(payload, False, False, "missing-controllers")

    left = _find_controller(controllers, "left")
    right = _find_controller(controllers, "right")
    if left is None and right is None:
        return _stopped(payload, False, False, "no-hand-controllers")

    deadman = _any_button_pressed(left, cfg.deadman_buttons) or _any_button_pressed(right, cfg.deadman_buttons)
    estop = _any_button_pressed(left, cfg.estop_buttons) or _any_button_pressed(right, cfg.estop_buttons)

    if estop:
        return _stopped(payload, deadman, True, "estop")
    if cfg.require_deadman and not deadman:
        return _stopped(payload, deadman, False, "deadman-not-held")

    left_x, left_y = _read_axis_pair(left, cfg.left_axes)
    right_x, _right_y = _read_axis_pair(right, cfg.right_axes)

    if cfg.invert_left_y:
        left_y = -left_y
    if cfg.invert_left_x:
        left_x = -left_x
    if cfg.invert_right_x:
        right_x = -right_x

    vx = _apply_deadzone(left_y, cfg.deadzone) * cfg.max_vx_mps
    vy = _apply_deadzone(left_x, cfg.deadzone) * cfg.max_vy_mps if cfg.allow_lateral else 0.0
    wz = _apply_deadzone(right_x, cfg.deadzone) * cfg.max_wz_radps

    active = any(abs(v) > 1e-6 for v in (vx, vy, wz))
    return RobotVelocityCommand(
        vx=round(vx, 4),
        vy=round(vy, 4),
        wz=round(wz, 4),
        deadman=deadman,
        estop=False,
        active=active,
        source_seq=_int_or_none(payload.get("seq")),
        source_time_ms=_float_or_none(payload.get("sentAtMs", payload.get("t"))),
        reason="ok" if active else "deadzone",
    )


def map_xr_input_to_arm(
    payload: Mapping[str, Any],
    config: ArmTeleopMappingConfig | None = None,
) -> RobotArmCommand:
    """Map a desktop DualSense packet to bounded arm joint rates.

    L1 is a dedicated arm-mode hold. While it is held, the caller suppresses
    chassis velocity so one stick movement can never drive both subsystems.
    """

    cfg = config or ArmTeleopMappingConfig()
    if payload.get("type") != "xr-input":
        return ZERO_ARM_COMMAND

    if payload.get("source") == "desktop-gamepad":
        gamepad = _find_desktop_gamepad(payload)
        if gamepad is None:
            return ZERO_ARM_COMMAND

        buttons = gamepad.get("buttons")
        axes = gamepad.get("axes")
        if not isinstance(buttons, Sequence) or not isinstance(axes, Sequence):
            return ZERO_ARM_COMMAND

        mode = _button_value(buttons, cfg.arm_mode_button) >= 0.5
        if not mode:
            return ZERO_ARM_COMMAND

        joint_rate = cfg.max_joint_rate_dps
        rates = (
            _apply_deadzone(_axis(axes, 0), cfg.deadzone) * joint_rate,
            -_apply_deadzone(_axis(axes, 1), cfg.deadzone) * joint_rate,
            _apply_deadzone(_axis(axes, 2), cfg.deadzone) * joint_rate,
            -_apply_deadzone(_axis(axes, 3), cfg.deadzone) * joint_rate,
            (_button_value(buttons, cfg.dpad_right_button) - _button_value(buttons, cfg.dpad_left_button)) * joint_rate,
            (_button_value(buttons, cfg.gripper_close_button) - _button_value(buttons, cfg.gripper_open_button))
            * cfg.max_gripper_rate_dps,
        )
    else:
        controllers = payload.get("controllers")
        if not isinstance(controllers, Sequence):
            return ZERO_ARM_COMMAND
        left = _find_controller(controllers, "left")
        right = _find_controller(controllers, "right")
        if left is None or right is None:
            return ZERO_ARM_COMMAND

        left_grip = _controller_button_value(left, cfg.vr_grip_button)
        right_grip = _controller_button_value(right, cfg.vr_grip_button)
        if left_grip < 0.5 or right_grip < 0.5:
            return ZERO_ARM_COMMAND

        left_x, left_y = _read_axis_pair(left, (0, 1))
        right_x, right_y = _read_axis_pair(right, (0, 1))
        joint_rate = cfg.max_joint_rate_dps
        rates = (
            _apply_deadzone(left_x, cfg.deadzone) * joint_rate,
            -_apply_deadzone(left_y, cfg.deadzone) * joint_rate,
            _apply_deadzone(right_x, cfg.deadzone) * joint_rate,
            -_apply_deadzone(right_y, cfg.deadzone) * joint_rate,
            (
                _controller_button_value(right, cfg.vr_joint5_button)
                - _controller_button_value(left, cfg.vr_joint5_button)
            )
            * joint_rate,
            (
                _controller_button_value(right, cfg.vr_trigger_button)
                - _controller_button_value(left, cfg.vr_trigger_button)
            )
            * cfg.max_gripper_rate_dps,
        )
    rounded = tuple(round(rate, 3) for rate in rates)
    active = any(abs(rate) > 1e-6 for rate in rounded)
    return RobotArmCommand(
        mode=True,
        rates_dps=rounded,
        active=active,
        source_seq=_int_or_none(payload.get("seq")),
        source_time_ms=_float_or_none(payload.get("sentAtMs", payload.get("t"))),
        reason="ok" if active else "arm-deadzone",
    )


def _find_controller(controllers: Sequence[Any], hand: str) -> Mapping[str, Any] | None:
    for controller in controllers:
        if isinstance(controller, Mapping) and controller.get("hand") == hand:
            return controller
    return None


def _find_desktop_gamepad(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    controllers = payload.get("controllers")
    if not isinstance(controllers, Sequence):
        return None
    for controller in controllers:
        if not isinstance(controller, Mapping):
            continue
        gamepad = controller.get("gamepad")
        if isinstance(gamepad, Mapping):
            return gamepad
    return None


def _read_axis_pair(controller: Mapping[str, Any] | None, preferred: tuple[int, int]) -> tuple[float, float]:
    if not controller:
        return 0.0, 0.0
    axes = controller.get("axes")
    if not isinstance(axes, Sequence):
        return 0.0, 0.0

    x = _axis(axes, preferred[0])
    y = _axis(axes, preferred[1])
    if abs(x) > 1e-6 or abs(y) > 1e-6 or len(axes) < 4:
        return x, y

    # Some WebXR runtimes expose thumbsticks as the last pair instead of 0/1.
    return _axis(axes, len(axes) - 2), _axis(axes, len(axes) - 1)


def _axis(axes: Sequence[Any], index: int) -> float:
    if index < 0 or index >= len(axes):
        return 0.0
    try:
        return max(-1.0, min(1.0, float(axes[index])))
    except (TypeError, ValueError):
        return 0.0


def _any_button_pressed(controller: Mapping[str, Any] | None, indexes: Sequence[int]) -> bool:
    if not controller:
        return False
    buttons = controller.get("buttons")
    if not isinstance(buttons, Sequence):
        return False
    for index in indexes:
        if index < 0 or index >= len(buttons):
            continue
        button = buttons[index]
        if isinstance(button, Mapping) and bool(button.get("p")):
            return True
    return False


def _button_value(buttons: Sequence[Any], index: int) -> float:
    if index < 0 or index >= len(buttons):
        return 0.0
    button = buttons[index]
    if not isinstance(button, Mapping):
        return 0.0
    try:
        value = float(button.get("v", 0.0))
    except (TypeError, ValueError):
        value = 0.0
    if bool(button.get("p")):
        value = max(value, 1.0)
    return max(0.0, min(1.0, value))


def _controller_button_value(controller: Mapping[str, Any] | None, index: int) -> float:
    if not controller:
        return 0.0
    buttons = controller.get("buttons")
    if not isinstance(buttons, Sequence):
        return 0.0
    return _button_value(buttons, index)


def _apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) <= deadzone:
        return 0.0
    sign = 1.0 if value >= 0 else -1.0
    scaled = (abs(value) - deadzone) / max(1e-6, 1.0 - deadzone)
    return sign * max(0.0, min(1.0, scaled))


def _stopped(
    payload: Mapping[str, Any],
    deadman: bool,
    estop: bool,
    reason: str,
) -> RobotVelocityCommand:
    return RobotVelocityCommand(
        vx=0.0,
        vy=0.0,
        wz=0.0,
        deadman=deadman,
        estop=estop,
        active=False,
        source_seq=_int_or_none(payload.get("seq")),
        source_time_ms=_float_or_none(payload.get("sentAtMs", payload.get("t"))),
        reason=reason,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
