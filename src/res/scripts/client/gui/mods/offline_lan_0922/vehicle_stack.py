# -*- coding: utf-8 -*-
"""Vertical vehicle contacts, separate from the planar ram law.

Rates are the user-authorized offline approximation of sustained crushing,
not recovered retail coefficients. Native component rays own admission.
"""
import math

PRESSURE_HP_PER_SECOND = 5.0


class CollisionPose(object):
    """Override component aim without mutating a live engine vehicle."""
    def __init__(self, source, appearance):
        self.source = source
        self.appearance = appearance

    def __getattr__(self, name):
        return getattr(self.source, name)


def pressure_rates(upper_mass, lower_mass):
    upper_mass, lower_mass = float(upper_mass), float(lower_mass)
    if upper_mass <= 0.0 or lower_mass <= 0.0:
        raise ValueError('stack contact requires descriptor masses')
    return (PRESSURE_HP_PER_SECOND * lower_mass / upper_mass,
            PRESSURE_HP_PER_SECOND * upper_mass / lower_mass)


def impact_damage(max_health, speed, upper_mass, lower_mass):
    """Use the existing fall curve, scaled by the striking/struck mass ratio."""
    from . import vehicle_physics
    unused, ratio = pressure_rates(upper_mass, lower_mass)
    return int(round(vehicle_physics.fall_damage(max_health, speed) *
                     ratio / PRESSURE_HP_PER_SECOND))


def identity(kind, actor_id):
    if kind not in ('bot', 'player') or isinstance(actor_id, bool):
        raise ValueError('invalid stack actor')
    number = int(actor_id)
    if number <= 0 or number != actor_id:
        raise ValueError('invalid stack actor id')
    return kind, number


def carrier(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('invalid stack carrier')
    return identity(value[0], value[1])


def planar_pair(first, second):
    """A proved roof contact is not a second horizontal penetration."""
    first_key = (first.get('kind', 'bot'), first.get('network_id', first['id']))
    second_key = (second.get('kind', 'bot'), second.get('network_id', second['id']))
    return not (tuple(first.get('stack_carrier') or ()) == second_key or
                tuple(second.get('stack_carrier') or ()) == first_key)


class Ledger(object):
    """Cumulative per-pair work survives state coalescing and exact replay."""
    def __init__(self):
        self.rows = {}

    def advance(self, upper, lower, dt, upper_alive, lower_alive,
                upper_mass, lower_mass):
        key = tuple(upper) + tuple(lower)
        row = self.rows.setdefault(key, dict(upper=list(upper), lower=list(lower),
            upper_total=0.0, lower_total=0.0, lower_environment_total=0.0,
            upper_impact_total=0, contact_seconds=0.0))
        seconds = max(0.0, float(dt))
        if math.isnan(seconds) or math.isinf(seconds):
            raise ValueError('stack elapsed time is not finite')
        if lower_alive:
            up_rate, low_rate = pressure_rates(upper_mass, lower_mass)
            row['contact_seconds'] += seconds
            if upper_alive:
                row['lower_total'] += low_rate * seconds
            else:
                row['lower_environment_total'] += low_rate * seconds
            if upper_alive:
                row['upper_total'] += up_rate * seconds
        return row

    def strike(self, upper, lower, damage, upper_damage=0):
        row = self.advance(upper, lower, 0.0, False, False, 1.0, 1.0)
        row['lower_total'] += max(0, int(damage))
        # Bot HP is already committed by its landing owner. This cumulative
        # witness changes its cause/credit, never spends that HP a second time.
        row['upper_impact_total'] += max(0, int(upper_damage))

    def publication(self):
        return [dict(upper=list(row['upper']), lower=list(row['lower']),
                     upper_total=int(row['upper_total']+1.e-8),
                     lower_total=(int(row['lower_total']+1.e-8)+
                                  int(row['lower_environment_total']+1.e-8)),
                     lower_environment_total=int(row['lower_environment_total']+1.e-8),
                     upper_impact_total=row['upper_impact_total'],
                     contact_seconds=round(row['contact_seconds'], 6))
                for unused, row in sorted(self.rows.items())]
