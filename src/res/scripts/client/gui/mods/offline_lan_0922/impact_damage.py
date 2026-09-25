"""Deterministic reconstructed landing damage, not a retail server formula.

The existing hull fall-damage budget is shared by the verified compressive
loads. Only the two external track pools have a contact-to-device mapping.
Crew casualties use that same budget's fraction of full hull HP, quantized
against the actual crew roster; this is an explicit project reconstruction.
"""
import math


TRACK_NAMES = ('leftTrackHealth', 'rightTrackHealth')


def track_loads(value):
    """Validate left/right shares; the unassigned share belongs to the hull."""
    if value is None:
        return (0.0, 0.0)
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('landing track loads must contain two shares')
    result = []
    for share in value:
        if isinstance(share, bool) or not isinstance(share, (int, float)):
            raise ValueError('landing track share is not numeric')
        try:
            share = float(share)
        except (OverflowError, ValueError):
            raise ValueError('landing track share cannot be represented')
        if math.isnan(share) or math.isinf(share) or not 0.0 <= share <= 1.0:
            raise ValueError('landing track share is outside its range')
        result.append(share)
    if sum(result) > 1.000001:
        raise ValueError('landing track shares exceed the contact load')
    # Six-decimal wire rounding must not manufacture extra damage.
    total = max(1.0, sum(result))
    return tuple(share / total for share in result)


def track_losses(budget, loads, maxima):
    """Spend the existing fall budget once, capped by fitted track HP pools."""
    shares = track_loads(loads)
    budget = max(0.0, float(budget))
    result = []
    for name, share in zip(TRACK_NAMES, shares):
        maximum = float(maxima.get(name, 0.0))
        if share > 0.0 and maximum > 0.0 and budget > 0.0:
            result.append((name, min(maximum, budget * share)))
    return result


def crew_casualties(budget, max_health, roster, knocked_out=(), impact_index=0):
    """Quantize one damaging landing's severity into actual injured seats.

    There are no retail crew-impact coefficients in the available client.
    Conservatively round down the already computed hull-damage fraction times
    the number of real crew members. Do not accumulate subthreshold landings,
    borrow projectile saving throws, or invent crew HP. Seat order rotates on
    successive accepted damaging impacts, solely as a deterministic tie-break;
    it is not an assertion that a particular compartment received the impact.
    """
    seats = []
    for name in roster or ():
        if name not in seats:
            seats.append(name)
    maximum = float(max_health)
    budget = float(budget)
    if (not seats or maximum <= 0.0 or budget <= 0.0 or
            math.isnan(maximum) or math.isinf(maximum) or
            math.isnan(budget) or math.isinf(budget)):
        return []
    count = min(len(seats), int(budget * len(seats) / maximum))
    if count <= 0:
        return []
    start = int(impact_index) % len(seats)
    ordered = seats[start:] + seats[:start]
    unavailable = set(knocked_out or ())
    return [name for name in ordered if name not in unavailable][:count]
