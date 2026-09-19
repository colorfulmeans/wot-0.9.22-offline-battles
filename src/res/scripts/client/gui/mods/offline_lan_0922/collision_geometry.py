"""Rigid collision geometry shared by motion and contact diagnostics.

Enclosing volumes are candidate filters only. Physical decisions use the
oriented body at an actual pose. Epsilon is numerical convergence precision,
never an added collision skin or a distance reserved around an object.
"""

import math


GEOMETRY_EPSILON = 1.0e-7


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
            a[0]*b[1]-a[1]*b[0])


def pose_axes(yaw, pitch=0.0, roll=0.0):
    sy, cy = math.sin(yaw), math.cos(yaw)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sr, cr = math.sin(roll), math.cos(roll)
    return ((cy*cr+sy*sp*sr, cp*sr, -sy*cr+cy*sp*sr),
            (-cy*sr+sy*sp*cr, cp*cr, sy*sr+cy*sp*cr),
            (sy*cp, -sp, cy*cp))


def body_box(position, yaw, bbox, pitch=0.0, roll=0.0):
    low, high = bbox[:2]
    axes = pose_axes(yaw, pitch, roll)
    center = tuple(position[i] + sum(axes[j][i]*(low[j]+high[j])*0.5
                   for j in range(3)) for i in range(3))
    return center, tuple(tuple(v*(high[j]-low[j])*0.5 for v in axes[j])
                         for j in range(3))


def contact_axes(left, right):
    """Signed SAT depths and outward axes, including every contact feature."""
    a, aa = left[:2]
    b, bb = right[:2]
    delta = tuple(a[i]-b[i] for i in range(3))
    axes = [cross(aa[i], aa[(i+1) % 3]) for i in range(3)]
    axes += [cross(bb[i], bb[(i+1) % 3]) for i in range(3)]
    axes += [cross(x, y) for x in aa for y in bb]
    results = []
    for axis in axes:
        length = math.sqrt(dot(axis, axis))
        if length <= 1.0e-12:
            continue
        axis = tuple(x/length for x in axis)
        distance = dot(delta, axis)
        depth = sum(abs(dot(x, axis)) for x in tuple(aa)+tuple(bb)) - abs(distance)
        results.append((depth, tuple(-v if distance < 0.0 else v for v in axis)))
    return results


def contact(left, right):
    results = contact_axes(left, right)
    return min(results, key=lambda row: row[0]) if results else None


def contact_witness(box, obstacle, normal, depth, position, fraction):
    feature = support_point(obstacle, normal)
    relative = tuple(feature[i]-box[0][i] for i in range(3))
    point = list(box[0])
    for axis in box[1]:
        square = dot(axis, axis)
        amount = max(-1.0, min(1.0, dot(relative, axis)/square)) if square else 0.0
        for i in range(3):
            point[i] += axis[i]*amount
    return {'fraction': fraction, 'point': point, 'normal': normal,
            'depth': depth, 'position': position}


def support_point(box, direction):
    center, axes = box[:2]
    return tuple(center[i] + sum(axis[i] * (
        1.0 if dot(axis, direction) > GEOMETRY_EPSILON else
        -1.0 if dot(axis, direction) < -GEOMETRY_EPSILON else 0.0)
        for axis in axes) for i in range(3))


def projection_range(motion, normal, lower=0.0, upper=1.0):
    """Exact support range of a translated yaw arc on one fixed plane."""
    yaw, delta = motion['yaw'], motion.get('yaw_delta', 0.0)
    start, end = motion['start'], motion['end']
    axes = pose_axes(0.0, motion.get('pitch', 0.0), motion.get('roll', 0.0))
    rate = dot(tuple(end[i]-start[i] for i in range(3)), normal)
    low, high = motion['bbox'][:2]
    values = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                corner = tuple(axes[0][i]*x+axes[1][i]*y+axes[2][i]*z
                               for i in range(3))
                a = normal[0]*corner[0]+normal[2]*corner[2]
                b = normal[0]*corner[2]-normal[2]*corner[0]
                c = dot(start, normal)+normal[1]*corner[1]
                times = [lower, upper]
                radius = math.hypot(a, b)
                if abs(delta)*radius > 1.0e-15:
                    cosine = -rate/(delta*radius)
                    if -1.0 <= cosine <= 1.0:
                        phase = math.atan2(a, b)
                        angles = sorted((yaw+delta*lower, yaw+delta*upper))
                        for root in (math.acos(cosine), -math.acos(cosine)):
                            first = int(math.ceil((angles[0]+phase-root)/(2*math.pi)))
                            last = int(math.floor((angles[1]+phase-root)/(2*math.pi)))
                            for k in range(first, last+1):
                                times.append((root-phase+2*math.pi*k-yaw)/delta)
                values.extend(a*math.cos(yaw+delta*t)+b*math.sin(yaw+delta*t)+c+rate*t
                              for t in times)
    return min(values), max(values)


def motion_envelope(motion):
    """AABB used only to find possible contacts, never to decide overlap."""
    ranges = [projection_range(motion, tuple(1.0 if j == i else 0.0
                                            for j in range(3))) for i in range(3)]
    center = tuple((v[0]+v[1])*0.5 for v in ranges)
    axes = tuple(tuple((ranges[i][1]-ranges[i][0])*0.5 if i == j else 0.0
                       for j in range(3)) for i in range(3))
    return center, axes


def rotation_contains_point(motion, point):
    """Exact interval test for a point against an in-place rigid yaw arc.

    Split at every crossing of a body face, including a zero-duration corner
    touch. Conservative advancement alone can step over that point contact.
    """
    if motion['start'] != motion['end']:
        raise ValueError('point rotation query requires a fixed body origin')
    relative = tuple(point[i]-motion['start'][i] for i in range(3))
    axes = pose_axes(0.0, motion.get('pitch', 0.0), motion.get('roll', 0.0))
    yaw, delta = motion['yaw'], motion.get('yaw_delta', 0.0)
    low, high = motion['bbox'][:2]
    coefficients, times = [], [0.0, 1.0]
    for j, axis in enumerate(axes):
        a = axis[0]*relative[0]+axis[2]*relative[2]
        b = axis[2]*relative[0]-axis[0]*relative[2]
        c = axis[1]*relative[1]
        coefficients.append((a,b,c))
        radius = math.hypot(a,b)
        if radius == 0.0 or delta == 0.0:
            continue
        phase = math.atan2(b,a)
        angles = sorted((yaw,yaw+delta))
        for boundary in (low[j],high[j]):
            cosine = (boundary-c)/radius
            if not -1.0 <= cosine <= 1.0:
                continue
            for root in (math.acos(cosine),-math.acos(cosine)):
                first = int(math.ceil((angles[0]-phase-root)/(2*math.pi)))
                last = int(math.floor((angles[1]-phase-root)/(2*math.pi)))
                for k in range(first,last+1):
                    times.append((phase+root+2*math.pi*k-yaw)/delta)
    times = sorted(set(times))
    probes = times+[(a+b)*.5 for a,b in zip(times,times[1:])]
    tolerance = 1.0e-12*max([1.0]+[abs(v) for v in relative])
    for fraction in probes:
        angle = yaw+delta*fraction
        local = [a*math.cos(angle)+b*math.sin(angle)+c for a,b,c in coefficients]
        if all(low[i]-tolerance <= local[i] <= high[i]+tolerance for i in range(3)):
            return True
    return False


def sweep_contact(motion, obstacle):
    """Find contact on a translated/rotated rigid body by conservative advancement.

    A separating-plane distance bounds safe progress using the maximum real
    corner speed. This avoids treating empty corners of a yaw envelope as
    occupied hull. The iteration terminates on separation, contact or floating
    point stagnation; it has no angle-dependent artificial collision margin.
    """
    start, end = motion['start'], motion['end']
    yaw, delta = motion['yaw'], motion.get('yaw_delta', 0.0)
    pitch, roll = motion.get('pitch', 0.0), motion.get('roll', 0.0)
    bbox = motion['bbox']
    travel = tuple(end[i]-start[i] for i in range(3))
    radius = math.sqrt(sum(max(abs(bbox[0][i]), abs(bbox[1][i]))**2
                           for i in range(3)))
    bound = math.sqrt(dot(travel, travel)) + abs(delta)*radius
    fraction = 0.0
    while True:
        position = tuple(start[i]+travel[i]*fraction for i in range(3))
        box = body_box(position, yaw+delta*fraction, bbox, pitch, roll)
        result = contact(box, obstacle)
        if result is None:
            return None
        depth, normal = result
        if depth >= 0.0:
            # Clamp the opposing feature onto the body. Averaging the body's
            # entire support face puts a fence corner at the face centre and
            # incorrectly gives a stationary rotating tank zero closing speed.
            witness = contact_witness(box, obstacle, normal, depth, position, fraction)
            if fraction == 0.0 and depth > 0.0:
                # A shallow vertical overlap is not a horizontal impact
                # normal. Reconstruct the entering face from actual motion,
                # as for an already-overlapping tank pair. No top-speed input.
                features = [contact_witness(box, obstacle, n, d, position, fraction)
                            for d, n in contact_axes(box, obstacle)]
                entering = [(w['depth']/normal_closing_speed(motion, w), w)
                            for w in features if normal_closing_speed(motion, w) > 1.0e-10]
                if entering:
                    return min(entering, key=lambda row: row[0])[1]
                if features:
                    return min(features, key=lambda w: normal_closing_speed(motion, w))
            return witness
        if bound <= 1.0e-12 or fraction >= 1.0:
            return None
        # Prove a whole remaining arc separated before advancing. In
        # particular, arbitrarily close parallel travel completes immediately.
        support = dot(obstacle[0], normal) + sum(abs(dot(a, normal))
                                                for a in obstacle[1])
        if projection_range(motion, normal, fraction)[0] > support:
            return None
        advance = -depth/bound
        next_fraction = min(1.0, fraction+advance)
        if next_fraction <= fraction:
            return None
        # A sub-micrometre final interval is checked at its real endpoint;
        # positive separation is never converted into physical overlap.
        if advance*bound < GEOMETRY_EPSILON:
            next_fraction = min(1.0, fraction+GEOMETRY_EPSILON/bound)
        fraction = next_fraction


def normal_closing_speed(motion, witness):
    dt = float(motion.get('dt', 0.0))
    if dt <= 0.0:
        return 0.0
    center = witness['position']
    point = witness['point']
    omega = float(motion.get('yaw_delta', 0.0))/dt
    velocity = [(motion['end'][i]-motion['start'][i])/dt for i in range(3)]
    velocity[0] += omega*(point[2]-center[2])
    velocity[2] -= omega*(point[0]-center[0])
    return -dot(velocity, witness['normal'])


def contact_speed(motion, witness):
    return max(0.0, normal_closing_speed(motion, witness))
