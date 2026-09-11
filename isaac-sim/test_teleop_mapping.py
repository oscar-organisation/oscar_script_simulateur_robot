"""Focused regression tests for the Quest teleoperation safety mapping."""

import unittest

from teleop_mapping import TeleopMappingConfig, map_xr_input_to_velocity


def packet(*, grip=False, left_axes=(0.0, 0.0), right_axes=(0.0, 0.0), buttons=None):
    button_values = [{"p": False} for _ in range(6)] if buttons is None else buttons
    button_values[1] = {"p": grip}
    return {
        "type": "xr-input",
        "seq": 7,
        "controllers": [
            {"hand": "left", "axes": list(left_axes), "buttons": button_values},
            {"hand": "right", "axes": list(right_axes), "buttons": button_values},
        ],
    }


class TeleopMappingTests(unittest.TestCase):
    def test_grip_is_required(self):
        command = map_xr_input_to_velocity(packet(left_axes=(0.0, -1.0)))
        self.assertFalse(command.active)
        self.assertEqual(command.reason, "deadman-not-held")

    def test_grip_and_stick_produce_motion(self):
        command = map_xr_input_to_velocity(packet(grip=True, left_axes=(0.0, -1.0)))
        self.assertTrue(command.active)
        self.assertEqual(command.vx, 0.4)

    def test_grip_and_right_stick_produce_turn_in_place(self):
        command = map_xr_input_to_velocity(packet(grip=True, right_axes=(1.0, 0.0)))
        self.assertTrue(command.active)
        self.assertEqual(command.vx, 0.0)
        self.assertEqual(command.vy, 0.0)
        self.assertEqual(command.wz, -0.8)

    def test_physical_robot_can_invert_lateral_axis_only(self):
        command = map_xr_input_to_velocity(
            packet(grip=True, left_axes=(-1.0, 0.0)),
            TeleopMappingConfig(invert_left_x=True),
        )
        self.assertEqual(command.vx, 0.0)
        self.assertEqual(command.vy, 0.2)
        self.assertEqual(command.wz, 0.0)

    def test_meta_buttons_four_and_five_do_not_false_estop(self):
        buttons = [{"p": False} for _ in range(6)]
        buttons[1] = {"p": True}
        buttons[4] = {"p": True}
        buttons[5] = {"p": True}
        command = map_xr_input_to_velocity(
            packet(grip=True, left_axes=(0.0, -1.0), buttons=buttons)
        )
        self.assertFalse(command.estop)
        self.assertTrue(command.active)


if __name__ == "__main__":
    unittest.main()
