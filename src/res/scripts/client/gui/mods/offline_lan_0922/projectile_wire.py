"""Actor-independent numeric encoding shared by physical projectile owners."""

import math


def round_scalar(value):
    """Round identically on the shipped Python 2.7 and Python 3 server.

    Use the exact binary ratio and half-even six-decimal wire grid. Python's
    built-in round differs between runtimes; signed zero is also preserved.
    This boundary contains no networking, Bot policy or player state.
    """
    number = float(value)
    numerator, denominator = number.as_integer_ratio()
    negative = math.copysign(1.0, number) < 0.0
    scaled = abs(numerator) * 1000000
    quotient, remainder = divmod(scaled, denominator)
    twice_remainder = remainder * 2
    if (twice_remainder > denominator or
            (twice_remainder == denominator and quotient % 2)):
        quotient += 1
    if quotient == 0:
        return -0.0 if negative else 0.0
    if negative:
        quotient = -quotient
    return float(quotient) / 1000000.0
