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


def settled_carrier(params, ground, pseudo_ground, solved, position, yaw,
                    sample_pitch, sample_roll, hits, trace=None):
    """Match native roof witnesses to contacts used by the admitted solver.

    A model origin is not the track/body contact point. Comparing its height
    to the final arbitrary ray loses tilted carriers and can keep distant ones.
    """
    from . import vehicle_physics as vp
    contacts = vp._suspension_contact_keys(params,solved,ground,pseudo_ground)[0]
    matches = {}
    rows=[]
    if trace is not None:
        trace.update(contact_count=len(contacts),roof_hits=len(hits),points=rows,
            tolerance_y=.03,tolerance_xz=.05,verdict='no_final_contacts' if not contacts else 'no_roof_match')
    for kind,index in sorted(contacts):
        point = params['springs'][index] if kind == 'spring' else params['pseudo_contacts'][index]
        height = ground[index] if kind == 'spring' else pseudo_ground[index]
        ox,unused,oz = vp.suspension_point_offset(point,sample_pitch,sample_roll)
        x = position[0]+math.cos(yaw)*ox+math.sin(yaw)*oz
        z = position[2]-math.sin(yaw)*ox+math.cos(yaw)*oz
        candidates=[]
        for key,state,witness in hits:
            dy=abs(witness[1]-float(height))
            distance=math.hypot(witness[0]-x,witness[2]-z)
            candidates.append((distance+dy,key,distance,dy,witness))
            if dy <= .03 and distance <= .05:
                matches[key] = matches.get(key,0)+1
                break
        if trace is not None:
            nearest=min(candidates,key=lambda row:row[0]) if candidates else None
            rows.append(dict(kind=kind,index=index,point=(x,float(height),z),
                nearest=(dict(carrier=list(nearest[1]),distance_xz=nearest[2],
                    delta_y=nearest[3],witness=nearest[4]) if nearest else None)))
    result=list(max(matches,key=lambda key:(matches[key],key))) if matches else None
    if trace is not None:
        rejected=[]
        rotation=vp._suspension_rotation(solved.get('pitch',0.),solved.get('roll',0.))
        for kind,points,heights in (('spring',params['springs'],ground),
                                   ('pseudo',params.get('pseudo_contacts',()),pseudo_ground)):
            for index,point in enumerate(points):
                if (kind,index) in contacts:
                    continue
                height=heights[index]
                rigid=vp._rigid_point_height(solved,point,rotation)
                ox,unused,oz = vp.suspension_point_offset(point,sample_pitch,sample_roll)
                x=position[0]+math.cos(yaw)*ox+math.sin(yaw)*oz
                z=position[2]-math.sin(yaw)*ox+math.cos(yaw)*oz
                candidates=[(math.hypot(w[0]-x,w[2]-z),abs(w[1]-float(height)),key,w)
                    for key,lower,w in hits] if height is not None else []
                nearest=min(candidates,key=lambda row:row[0]+row[1]) if candidates else None
                rejected.append(dict(kind=kind,index=index,ground=None if height is None else float(height),
                    sampled_xz=(x,z),contact_threshold=0. if kind=='spring' else -vp.CONTACT_PENETRATION,
                    nearest_roof=(dict(distance_xz=nearest[0],delta_y=nearest[1],
                        carrier=list(nearest[2]),witness=nearest[3]) if nearest else None),
                    rigid_height=rigid,compression_or_gap=(None if height is None else
                        float(height)-rigid+(point['static_compression'] if kind=='spring' else 0.)),
                    reason='missing_ground' if height is None else 'not_in_final_contact_set'))
        trace['rejected_points']=rejected
        trace.update(selected=result,matches=[(list(key),count) for key,count in sorted(matches.items())])
        if result is not None:trace['verdict']='matched_final_contact'
    return result




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
