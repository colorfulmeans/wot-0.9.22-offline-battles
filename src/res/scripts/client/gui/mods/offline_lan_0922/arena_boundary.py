"""One chassis OBB boundary policy for planning, recovery and realised motion."""
import math


def valid(bounds):
    return bool(bounds is not None and len(bounds)==4 and bounds[0]<bounds[2] and bounds[1]<bounds[3]
        and all(not math.isnan(v) and not math.isinf(v) for v in bounds))


def overflow(bounds, position, yaw, half_length, half_width):
    if not valid(bounds):
        return (0., 0., 0., 0.)
    sine, cosine = abs(math.sin(yaw)), abs(math.cos(yaw))
    ex = cosine*half_width + sine*half_length
    ez = sine*half_width + cosine*half_length
    x, z = position[0], position[2]
    return (max(0., bounds[0]+ex-x), max(0., x+ex-bounds[2]),
            max(0., bounds[1]+ez-z), max(0., z+ez-bounds[3]))


def progress_clear(bounds, start, start_yaw, end, end_yaw, half_length, half_width):
    before = overflow(bounds, start, start_yaw, half_length, half_width)
    after = overflow(bounds, end, end_yaw, half_length, half_width)
    return all(b <= a+1.e-6 for a,b in zip(before,after))


def rotation_clear(bounds, position, start_yaw, end_yaw, half_length, half_width):
    if not valid(bounds):
        return True
    if any(overflow(bounds,position,start_yaw,half_length,half_width)):
        return progress_clear(bounds,position,start_yaw,position,end_yaw,half_length,half_width)
    # Each chassis corner's X/Z projection is sinusoidal. Check its extrema
    # on the requested shortest arc, as well as both ends; no sampling gap.
    delta = (end_yaw-start_yaw+math.pi)%(2.*math.pi)-math.pi
    low, high = sorted((start_yaw, start_yaw+delta))
    angles = [start_yaw+delta]
    for along in (-half_length, half_length):
        for across in (-half_width, half_width):
            for base in (math.atan2(along, across), math.atan2(-across, along)):
                first = int(math.ceil((low-base)/math.pi))
                last = int(math.floor((high-base)/math.pi))
                angles.extend(base+k*math.pi for k in range(first,last+1))
    return all(progress_clear(bounds,position,start_yaw,position,angle,
                              half_length,half_width) for angle in angles)


def segment_clear(bounds, start, end, half_length, half_width):
    dx, dz = end[0]-start[0], end[2]-start[2]
    if abs(dx)+abs(dz) < 1.e-9:
        return True
    yaw = math.atan2(dx,dz)
    return progress_clear(bounds,start,yaw,end,yaw,half_length,half_width)
