"""Community-observed linear fire decay with explicit offline calibration.

Jak_Atackka, Facts and Myths: Burn Damage Part 2 (2020-07-23):
https://www.reddit.com/r/WorldofTanks/comments/hw7wph/
Initial fire damage decreases linearly; Firefighting increases decay, not
initial damage. #1513 supplies the skill factor (0.57 untrained). The missing
server base rate is calibrated to ten seconds untrained, not claimed retail.
Initial damage retains this port's five-percent HP/second calibration.
"""
import math

BASE_SECONDS = 10.0
BASE_FACTOR = 0.57
INITIAL_HP_FRACTION = 0.05


def advance(progress, seconds, decay_factor, maximum_hp):
    """Integrate an interval; progress survives crew changes and slow frames.

    Integer damage uses cumulative integral boundaries so splitting an interval
    does not discard fractional HP on every simulation tick.
    """
    values = tuple(float(v) for v in (progress, seconds, decay_factor, maximum_hp))
    if any(math.isnan(v) or math.isinf(v) for v in values):
        raise ValueError('nonfinite fire model input')
    progress, seconds, decay_factor, maximum_hp = values
    if seconds < 0 or decay_factor <= 0 or maximum_hp < 0:
        raise ValueError('invalid fire model input')
    start = max(0.0, min(BASE_SECONDS, progress))
    speed = decay_factor / BASE_FACTOR
    end = min(BASE_SECONDS, start + seconds * speed)
    def integral(value):
        return maximum_hp * INITIAL_HP_FRACTION * (
            value - value * value / (2.0 * BASE_SECONDS)) / speed
    damage = max(0, int(math.floor(integral(end) + 1.e-7)) -
                 int(math.floor(integral(start) + 1.e-7)))
    return end, damage, (end - start) / speed, end >= BASE_SECONDS - 1.e-7
