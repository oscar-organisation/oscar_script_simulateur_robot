"""OSCAR LiveKit command agent — Meta Quest joystick → Isaac robot motion.

Run without Isaac to validate the data path:

    python -m sim.command_agent --apply log

Run inside Isaac Sim's Script Editor:

    import sys
    sys.path.insert(0, "/root/Documents/sim")
    from command_agent import start_oscar_command_agent
    start_oscar_command_agent(apply="xform", robot_prim="/World/g1")

Stop from the Script Editor:

    from command_agent import stop_oscar_command_agent
    stop_oscar_command_agent()
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SIM_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SIM_DIR))
if str(SIM_DIR / "vendor") not in sys.path:
    sys.path.append(str(SIM_DIR / "vendor"))

from livekit import rtc

from robot_control import IsaacXformController, IsaacXformControllerConfig, LogOnlyController, RobotController
from teleop_mapping import (
    RobotArmCommand,
    RobotVelocityCommand,
    TeleopMappingConfig,
    ZERO_ARM_COMMAND,
    ZERO_COMMAND,
    map_xr_input_to_arm,
    map_xr_input_to_velocity,
)

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # noqa: BLE001
    pass


log = logging.getLogger("oscar.command_agent")


@dataclass
class CommandAgentConfig:
    url: str
    room: str
    token: str
    identity: str
    topic: str = "oscar.xr.input"
    command_topic: str = "oscar.robot.command"
    watchdog_ms: int = 300
    control_hz: int = 30
    publish_command_echo: bool = True


class LiveKitCommandAgent:
    """Subscribes to XR data packets and applies velocity commands."""

    def __init__(
        self,
        cfg: CommandAgentConfig,
        controller: RobotController,
        mapping: TeleopMappingConfig | None = None,
    ):
        self.cfg = cfg
        self.controller = controller
        self.mapping = mapping or TeleopMappingConfig()
        self.room: rtc.Room | None = None
        self._latest: RobotVelocityCommand = ZERO_COMMAND
        self._latest_arm: RobotArmCommand = ZERO_ARM_COMMAND
        self._latest_received_at = 0.0
        self._last_loop_at = 0.0
        self._latency_samples = 0
        self._latency_total_ms = 0.0
        self._latency_max_ms = 0.0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self.room = rtc.Room()
        self._wire_room_events()

        rtc_cfg = rtc.RtcConfiguration(
            ice_servers=[
                rtc.IceServer(urls=["stun:stun.l.google.com:19302"]),
                rtc.IceServer(urls=["stun:stun.cloudflare.com:3478"]),
            ],
        )
        log.info("Connecting command agent to %s as %s", self.cfg.url, self.cfg.identity)
        await self.room.connect(
            self.cfg.url,
            self.cfg.token,
            options=rtc.RoomOptions(auto_subscribe=False, rtc_config=rtc_cfg),
        )

        try:
            await self.room.local_participant.set_metadata(json.dumps({
                "role": "isaac-command-agent",
                "topic": self.cfg.topic,
                "robot": "unitree-g1",
            }, separators=(",", ":")))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not set metadata: %s", exc)

        log.info("Command agent ready. topic=%s watchdog=%dms", self.cfg.topic, self.cfg.watchdog_ms)
        await self._control_loop()

    def _wire_room_events(self) -> None:
        assert self.room is not None

        @self.room.on("data_received")
        def _on_data_received(*args):  # noqa: ANN001
            event = _decode_data_event(args)
            if event is None:
                return
            topic, raw, identity = event
            if topic and topic != self.cfg.topic:
                return
            try:
                payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
            except Exception as exc:  # noqa: BLE001
                log.warning("Ignoring non-JSON data packet from %s: %s", identity, exc)
                return

            command = map_xr_input_to_velocity(payload, self.mapping)
            arm_command = map_xr_input_to_arm(payload)
            if arm_command.mode:
                command = RobotVelocityCommand(
                    vx=0.0,
                    vy=0.0,
                    wz=0.0,
                    deadman=True,
                    estop=False,
                    active=False,
                    source_seq=command.source_seq,
                    source_time_ms=command.source_time_ms,
                    reason="arm-mode",
                )
            self._latest = command
            self._latest_arm = arm_command
            self._latest_received_at = time.monotonic()
            self._record_transport_latency(payload)
            if command.estop:
                log.warning("Emergency stop from %s seq=%s", identity, command.source_seq)

        @self.room.on("disconnected")
        def _on_disconnected(reason):  # noqa: ANN001
            log.warning("LiveKit disconnected: %s", reason)
            self._stop.set()

    async def _control_loop(self) -> None:
        period = 1.0 / max(1, self.cfg.control_hz)
        self._last_loop_at = time.monotonic()

        while not self._stop.is_set():
            now = time.monotonic()
            dt = min(0.1, max(0.0, now - self._last_loop_at))
            self._last_loop_at = now

            command = self._command_or_watchdog_stop(now)
            arm_command = self._arm_command_or_watchdog_stop(now)
            self.controller.apply(command, dt)
            self.controller.apply_arm(arm_command, dt)
            if self.cfg.publish_command_echo:
                self._publish_command_echo(command)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=period)
            except asyncio.TimeoutError:
                pass

        self.controller.stop()
        if self.room is not None:
            await self.room.disconnect()
            self.room = None

    def _command_or_watchdog_stop(self, now: float) -> RobotVelocityCommand:
        if self._latest_received_at <= 0:
            return ZERO_COMMAND
        age_ms = (now - self._latest_received_at) * 1000
        if age_ms <= self.cfg.watchdog_ms:
            return self._latest
        return RobotVelocityCommand(
            vx=0.0,
            vy=0.0,
            wz=0.0,
            deadman=False,
            estop=False,
            active=False,
            source_seq=self._latest.source_seq,
            source_time_ms=self._latest.source_time_ms,
            reason="watchdog-timeout",
        )

    def _record_transport_latency(self, payload: dict[str, Any]) -> None:
        """Log browser-to-agent delay without adding traffic to the control path."""
        try:
            sent_at_ms = float(payload.get("sentAtMs"))
        except (TypeError, ValueError):
            return
        latency_ms = time.time() * 1000.0 - sent_at_ms
        if latency_ms < 0.0 or latency_ms > 10_000.0:
            return
        self._latency_samples += 1
        self._latency_total_ms += latency_ms
        self._latency_max_ms = max(self._latency_max_ms, latency_ms)
        if self._latency_samples % 150 == 0:
            log.info(
                "LiveKit command transport: avg=%.1fms max=%.1fms over %d packets",
                self._latency_total_ms / self._latency_samples,
                self._latency_max_ms,
                self._latency_samples,
            )

    def _arm_command_or_watchdog_stop(self, now: float) -> RobotArmCommand:
        if self._latest_received_at <= 0:
            return ZERO_ARM_COMMAND
        age_ms = (now - self._latest_received_at) * 1000
        if age_ms <= self.cfg.watchdog_ms:
            return self._latest_arm
        return ZERO_ARM_COMMAND

    def _publish_command_echo(self, command: RobotVelocityCommand) -> None:
        if self.room is None:
            return
        try:
            payload = json.dumps(command.to_payload(), separators=(",", ":")).encode("utf-8")
            result = self.room.local_participant.publish_data(
                payload,
                reliable=False,
                topic=self.cfg.command_topic,
            )
            if inspect.isawaitable(result):
                asyncio.create_task(result)
                return
            if hasattr(result, "add_done_callback"):
                result.add_done_callback(lambda fut: fut.exception())
        except Exception:
            # Echo is diagnostic only; never block motion on telemetry.
            pass

    def stop(self) -> None:
        self._stop.set()


def _decode_data_event(args: tuple[Any, ...]) -> tuple[str | None, Any, str | None] | None:
    """Handle livekit-rtc 1.x DataPacket and older callback shapes."""
    if not args:
        return None
    packet = args[0]
    if hasattr(packet, "data"):
        participant = getattr(packet, "participant", None)
        identity = getattr(participant, "identity", None)
        return getattr(packet, "topic", None), getattr(packet, "data"), identity

    raw = packet
    participant = args[1] if len(args) > 1 else None
    topic = getattr(packet, "topic", None)
    identity = getattr(participant, "identity", None)
    return topic, raw, identity


def mint_command_agent_token(
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    ttl_seconds: int = 86400,
) -> str:
    import jwt

    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": identity,
        "name": identity,
        "nbf": now,
        "exp": now + ttl_seconds,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": False,
            "canSubscribe": True,
            "canPublishData": True,
        },
        "metadata": json.dumps({"role": "isaac-command-agent", "robot": "unitree-g1"}),
    }
    return jwt.encode(payload, api_secret, algorithm="HS256")


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OSCAR command agent — XR input to robot motion")
    p.add_argument("--url", default=os.getenv("LIVEKIT_URL"))
    p.add_argument("--room", default=os.getenv("LIVEKIT_ROOM", "oscar-lot1-room"))
    p.add_argument("--identity", default=os.getenv("LIVEKIT_COMMAND_IDENTITY", "isaac-command-agent"))
    p.add_argument("--token", default=os.getenv("LIVEKIT_COMMAND_TOKEN") or os.getenv("LIVEKIT_TOKEN"))
    p.add_argument(
        "--token-file",
        default=os.getenv("LIVEKIT_COMMAND_TOKEN_FILE", "/root/Documents/livekit-command-agent.json"),
        help="JSON generated by scripts/create-livekit-tokens.mjs for the command agent",
    )
    p.add_argument("--topic", default=os.getenv("LIVEKIT_XR_INPUT_TOPIC", "oscar.xr.input"))
    p.add_argument("--command-topic", default=os.getenv("LIVEKIT_COMMAND_TOPIC", "oscar.robot.command"))
    p.add_argument("--watchdog-ms", type=int, default=int(os.getenv("TELEOP_WATCHDOG_MS", "300")))
    p.add_argument("--control-hz", type=int, default=int(os.getenv("TELEOP_CONTROL_HZ", "30")))
    p.add_argument(
        "--max-vx",
        type=float,
        default=float(os.getenv("OSCAR_MAX_VX_MPS", os.getenv("TELEOP_MAX_VX_MPS", "0.40"))),
    )
    p.add_argument(
        "--max-vy",
        type=float,
        default=float(os.getenv("OSCAR_MAX_VY_MPS", os.getenv("TELEOP_MAX_VY_MPS", "0.20"))),
    )
    p.add_argument(
        "--max-wz",
        type=float,
        default=float(os.getenv("OSCAR_MAX_WZ_RADPS", os.getenv("TELEOP_MAX_WZ_RADPS", "0.80"))),
    )
    p.add_argument("--apply", choices=["log", "xform", "ros2"], default=os.getenv("TELEOP_APPLY", "log"))
    p.add_argument("--robot-prim", default=os.getenv("TELEOP_ROBOT_PRIM", "/World/g1"))
    p.add_argument("--cmd-vel-topic", default=os.getenv("TELEOP_CMD_VEL_TOPIC", "/cmd_vel"))
    p.add_argument(
        "--invert-lateral",
        action="store_true",
        default=os.getenv("TELEOP_INVERT_LATERAL", "false").lower() == "true",
        help="Invert left-stick X for robots whose positive Y axis points right",
    )
    p.add_argument("--no-command-echo", action="store_true")
    p.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return p


def _resolve_token(args: argparse.Namespace) -> str:
    _apply_token_file_defaults(args)
    if args.token:
        return args.token
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")
    if not api_key or not api_secret:
        raise SystemExit(
            "No command token available. Set LIVEKIT_COMMAND_TOKEN, LIVEKIT_TOKEN, "
            "or LIVEKIT_API_KEY/LIVEKIT_API_SECRET."
        )
    ttl = int(os.getenv("LIVEKIT_TOKEN_TTL_SECONDS", "86400"))
    return mint_command_agent_token(api_key, api_secret, args.room, args.identity, ttl)


def _apply_token_file_defaults(args: argparse.Namespace) -> None:
    token_file = getattr(args, "token_file", None)
    if not token_file:
        return
    path = Path(token_file)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
        livekit = data.get("livekit", {})
        args.url = args.url or livekit.get("serverUrl")
        args.room = args.room or livekit.get("roomName")
        args.token = args.token or livekit.get("token")
        args.identity = args.identity or livekit.get("identity")
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read command token file %s: %s", token_file, exc)


def _build_controller(args: argparse.Namespace) -> RobotController:
    if args.apply == "xform":
        return IsaacXformController(IsaacXformControllerConfig(prim_path=args.robot_prim))
    if args.apply == "ros2":
        from robot_control import Ros2CmdVelController, Ros2CmdVelControllerConfig

        return Ros2CmdVelController(
            Ros2CmdVelControllerConfig(
                topic=args.cmd_vel_topic,
                max_vx=args.max_vx,
                max_vy=args.max_vy,
                max_wz=args.max_wz,
            )
        )
    return LogOnlyController()


async def _run(args: argparse.Namespace) -> int:
    _apply_token_file_defaults(args)
    if not args.url:
        raise SystemExit("--url or LIVEKIT_URL is required")

    cfg = CommandAgentConfig(
        url=args.url,
        room=args.room,
        token=_resolve_token(args),
        identity=args.identity,
        topic=args.topic,
        command_topic=args.command_topic,
        watchdog_ms=args.watchdog_ms,
        control_hz=args.control_hz,
        publish_command_echo=not args.no_command_echo,
    )
    mapping = TeleopMappingConfig(
        max_vx_mps=args.max_vx,
        max_vy_mps=args.max_vy,
        max_wz_radps=args.max_wz,
        invert_left_x=args.invert_lateral,
    )
    agent = LiveKitCommandAgent(cfg, _build_controller(args), mapping=mapping)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, agent.stop)
        except NotImplementedError:
            pass
    await agent.run()
    return 0


def main() -> int:
    args = _build_argparser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    return asyncio.run(_run(args))


_embedded_state: dict[str, Any] = {"agent": None, "task": None, "apply": None}


def start_oscar_command_agent(**overrides: Any) -> asyncio.Task:
    """Start the command agent on Kit's existing asyncio loop."""
    if _embedded_state.get("task") and not _embedded_state["task"].done():
        requested_apply = overrides.get("apply", "log")
        running_apply = _embedded_state.get("apply")
        if requested_apply != running_apply:
            raise RuntimeError(
                f"Command agent already running in {running_apply!r} mode; "
                f"stop it before switching to {requested_apply!r}"
            )
        log.warning("Command agent already running (apply=%s)", running_apply)
        return _embedded_state["task"]

    parser = _build_argparser()
    args = parser.parse_args([])
    for key, value in overrides.items():
        setattr(args, key.replace("-", "_"), value)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    async def _embedded_run() -> None:
        _apply_token_file_defaults(args)
        cfg = CommandAgentConfig(
            url=args.url,
            room=args.room,
            token=_resolve_token(args),
            identity=args.identity,
            topic=args.topic,
            command_topic=args.command_topic,
            watchdog_ms=args.watchdog_ms,
            control_hz=args.control_hz,
            publish_command_echo=not args.no_command_echo,
        )
        mapping = TeleopMappingConfig(
            max_vx_mps=args.max_vx,
            max_vy_mps=args.max_vy,
            max_wz_radps=args.max_wz,
            invert_left_x=args.invert_lateral,
        )
        agent = LiveKitCommandAgent(cfg, _build_controller(args), mapping=mapping)
        _embedded_state["agent"] = agent
        await agent.run()

    task = asyncio.ensure_future(_embedded_run())
    _embedded_state["task"] = task
    _embedded_state["apply"] = args.apply

    def _clear_finished(_task: asyncio.Task) -> None:
        if _embedded_state.get("task") is _task:
            _embedded_state.update({"agent": None, "task": None, "apply": None})

    task.add_done_callback(_clear_finished)
    log.info("OSCAR command agent scheduled (apply=%s)", args.apply)
    return task


def stop_oscar_command_agent() -> None:
    agent = _embedded_state.get("agent")
    if agent is None:
        log.warning("No OSCAR command agent is running")
        return
    agent.stop()
    log.info("Stop requested for OSCAR command agent")


if __name__ == "__main__":
    raise SystemExit(main())
