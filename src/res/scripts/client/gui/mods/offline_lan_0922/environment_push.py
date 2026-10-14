"""Identify a pusher from a proved contact's incoming horizontal velocities."""
import math


def initiator(first_velocity, second_velocity, normal):
    # The solver normal points from the second body toward the first body.
    # Head-on equal approaches are ambiguous, not a one-sided shove.
    nx, nz = normal[:2]
    length = math.hypot(nx, nz)
    if length <= 0.0:
        return None
    nx, nz = nx / length, nz / length
    first = -(first_velocity[0] * nx + first_velocity[1] * nz)
    second = second_velocity[0] * nx + second_velocity[1] * nz
    if first + second <= 0.05:
        return None
    if first > 0.05 and first > max(0.0, second) + 0.05:
        return 0
    if second > 0.05 and second > max(0.0, first) + 0.05:
        return 1
    return None
