"""Realised travel budget shared by local recovery owners, never by routes."""
import math


def observe(memory, position, yaw, departure):
    """Sample the previous command's result; rotation earns no travel credit."""
    if memory is None or math.hypot(position[0]-memory['origin'][0],
                                    position[2]-memory['origin'][2]) > departure:
        return dict(origin=tuple(position), previous=tuple(position), yaw=yaw,
                    forward=0., returned=0., throttle=0.)
    previous = memory['previous']
    dx, dz = position[0]-previous[0], position[2]-previous[2]
    along = dx*math.sin(memory['yaw']) + dz*math.cos(memory['yaw'])
    if memory['throttle'] < 0.:
        memory['returned'] += max(0., -along)
    if memory['throttle'] > 0.:
        # A high-water mark prevents returning to the same forward endpoint
        # from manufacturing fresh credit on each oscillation.
        projection = ((position[0]-memory['origin'][0])*math.sin(memory['yaw']) +
                      (position[2]-memory['origin'][2])*math.cos(memory['yaw']))
        memory['forward'] = max(memory['forward'], projection)
    memory['previous'] = tuple(position)
    return memory


def remaining(memory):
    """No forward travel means an independent initial reverse remains legal."""
    if memory['forward'] <= .05:
        return None
    return max(0., .5*memory['forward']-memory['returned'])
