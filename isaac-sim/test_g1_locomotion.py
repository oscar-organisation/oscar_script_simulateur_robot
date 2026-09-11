"""Pure math/contract checks for the Unitree G1 policy adapter."""

from collections import deque

import numpy as np

from g1_locomotion import (
    HISTORY_LENGTH,
    OBSERVATION_TERM_ORDER,
    flatten_observation_history,
    gravity_in_body_frame,
    world_to_body,
    yaw_from_quaternion_wxyz,
)


def test_identity_orientation_contract():
    quaternion = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    np.testing.assert_allclose(gravity_in_body_frame(quaternion), [0.0, 0.0, -1.0])
    np.testing.assert_allclose(world_to_body([1.0, 2.0, 3.0], quaternion), [1.0, 2.0, 3.0])


def test_observation_is_unitree_480_value_history_contract():
    sizes = dict(base_ang_vel=3, projected_gravity=3, velocity_commands=3,
                 joint_pos_rel=29, joint_vel_rel=29, last_action=29)
    histories = {
        name: deque(
            [np.full(sizes[name], frame, dtype=np.float32) for frame in range(HISTORY_LENGTH)],
            maxlen=HISTORY_LENGTH,
        )
        for name in OBSERVATION_TERM_ORDER
    }
    observation = flatten_observation_history(histories)
    assert observation.shape == (480,)
    assert observation.dtype == np.float32
    np.testing.assert_allclose(observation[:3], np.zeros(3))
    np.testing.assert_allclose(observation[12:15], np.full(3, 4.0))


def test_yaw_extraction_uses_isaac_scalar_first_quaternion():
    half_angle = np.deg2rad(45.0)
    quaternion = np.array([np.cos(half_angle), 0.0, 0.0, np.sin(half_angle)], dtype=np.float32)
    np.testing.assert_allclose(yaw_from_quaternion_wxyz(quaternion), np.deg2rad(90.0), atol=1e-6)
