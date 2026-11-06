"""Keep ordinary combat destinations in an accepted capture circle.

This constrains tactical destinations, never collision or physical motion.
Selection, aim, reload and final launch checks retain their existing owners.
"""
import math


def position(value):
    if isinstance(value, dict):
        return dict((axis, float(value.get(axis, 0.))) for axis in ('x', 'y', 'z'))
    return dict(zip(('x', 'y', 'z'), (float(v) for v in value)))


def inside(pose, area):
    pose = position(pose)
    center = area['point']
    return math.hypot(pose['x']-center['x'], pose['z']-center['z']) <= area['radius']


def constrain(order, pose):
    area = order.get('capture_area')
    if not area:
        return order
    pose = position(pose)
    result = dict(order)
    if not inside(pose, area):
        # A shove is not a completed capture. Re-enter the real circle,
        # retaining the current target and its existing launch permission.
        result.update(combat_mode='base_capture', move_position=dict(area['point']),
                      route_join=False, throttle_override=None,
                      parking_phase=None, parking_slot=None)
    elif (order.get('combat_mode') in ('route', 'advance', 'base_capture') or
          not inside(order.get('move_position') or pose, area)) and not (
              order.get('throttle_override') == 0. and
              inside(order.get('move_position') or pose, area)):
        result.update(combat_mode='engage' if order.get('target_id') is not None
                      else 'base_capture', move_position=pose,
                      route_join=False, throttle_override=0.,
                      parking_phase=None, parking_slot=None)
    return result
