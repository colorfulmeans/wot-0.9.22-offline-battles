"""Mass and inertia driven detached components, owned by the hidden worker.

This is a compound-box rigid body, not a recovered retail cell implementation.
Component weights and bounds supply mass, centre of mass and inertia. Contacts
are inelastic; scenery uses a dissipative no-slip contact constraint instead
of inventing an unreviewed steel/material friction or restitution coefficient.
Position recovery never becomes velocity, and a side contact never uses a
vertical 'lift to roof' operation.
"""
import copy
import math

from gui.mods.offline_lan_0922 import shot_geometry
from gui.mods.offline_lan_0922 import turret_detachment
from gui.mods.offline_lan_0922.entities import turret_obstacles as geometry

EPSILON = 1.0e-6
STEP = turret_detachment.FLIGHT_STEP_SECONDS / 4.0
SOLVER_PASSES = 8
ZERO = (0.0, 0.0, 0.0)
add = geometry._add
sub = geometry._subtract
scale = geometry._scale
dot = geometry._dot
cross = geometry.destructibles_sensor._vector_cross


def length(v):
    return math.sqrt(dot(v, v))


def unit(v):
    size = length(v)
    return scale(v, 1.0 / size) if size > EPSILON else ZERO


def matrix(attitude):
    columns = [shot_geometry.transform_vehicle_vector(v, *attitude)
               for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    return tuple(columns[j][i] for i in range(3) for j in range(3))


def mul(m, v):
    return tuple(sum(m[3*i+j] * v[j] for j in range(3)) for i in range(3))


def transpose(m):
    return tuple(m[3*j+i] for i in range(3) for j in range(3))


def inverse(m):
    a, b, c, d, e, f, g, h, i = m
    cof = (e*i-f*h, c*h-b*i, b*f-c*e, f*g-d*i, a*i-c*g,
           c*d-a*f, d*h-e*g, b*g-a*h, a*e-b*d)
    det = a*cof[0] + b*cof[3] + c*cof[6]
    if abs(det) < EPSILON:
        raise ValueError('detached component inertia is singular')
    return tuple(v / det for v in cof)


def rotate(m, omega, dt):
    speed = length(omega)
    if speed * dt <= 1e-12:
        return m
    axis = scale(omega, 1.0 / speed)
    angle = speed * dt
    cosine, sine = math.cos(angle), math.sin(angle)
    columns = []
    for j in range(3):
        v = (m[j], m[3+j], m[6+j])
        columns.append(add(add(scale(v, cosine), scale(cross(axis, v), sine)),
                           scale(axis, dot(axis, v) * (1.0-cosine))))
    return tuple(columns[j][i] for i in range(3) for j in range(3))


def angles(m):
    pitch = math.asin(max(-1.0, min(1.0, -m[5])))
    if abs(math.cos(pitch)) > 1e-8:
        return math.atan2(m[2], m[8]), pitch, math.atan2(m[3], m[4])
    return math.atan2(-m[6], m[0]), pitch, 0.0


def properties(components):
    parts = []
    for unused_name, component, offset, bounds in components:
        mass = geometry._finite(getattr(component, 'weight', None))
        if mass <= 0.0:
            raise ValueError('detached component weight must be positive')
        centre = tuple((bounds[0][i]+bounds[1][i])*0.5+offset[i] for i in range(3))
        size = sub(bounds[1], bounds[0])
        parts.append((mass, centre, size))
    mass = sum(p[0] for p in parts)
    centre = tuple(sum(p[0]*p[1][i] for p in parts)/mass for i in range(3))
    inertia = [0.0] * 9
    for part_mass, origin, size in parts:
        r = sub(origin, centre)
        for i in range(3):
            for j in range(3):
                inertia[3*i+j] += part_mass * (
                    (sum(size[k]**2 for k in range(3) if k != i)/12.0 + dot(r, r))
                    if i == j else 0.0) - part_mass*r[i]*r[j]
    return {'mass': mass, 'centre': centre, 'inertia': tuple(inertia),
            'inverse_inertia': inverse(inertia)}


def box_contact(a, b, horizontal=False):
    """SAT normal from B to A, penetration and a face/edge contact point."""
    if any(abs(a[0][i]-b[0][i]) > sum(abs(v[i]) for v in a[1]+b[1])+EPSILON
           for i in range(3)):
        return None
    candidates = list(a[1]) + list(b[1])
    candidates += [cross(x, y) for x in a[1] for y in b[1]]
    if horizontal:
        if box_contact(a, b) is None:
            return None
        candidates = [(v[0], 0.0, v[2]) for v in candidates]
    delta = sub(a[0], b[0])
    best = None
    for axis in candidates:
        if length(axis) <= EPSILON:
            continue
        axis = unit(axis)
        gap = sum(abs(dot(v, axis)) for v in a[1]+b[1]) - abs(dot(delta, axis))
        if gap < -EPSILON:
            return None
        if best is None or gap < best[0]:
            normal = axis if dot(delta, axis) >= 0.0 else scale(axis, -1.0)
            best = max(0.0, gap), normal
    if best is None:
        return None
    depth, normal = best
    # Clip the midpoint into each box's support face. Using an arbitrary
    # corner for a flat face would invent torque in a centred impact.
    middle = scale(add(a[0], b[0]), 0.5)
    def face(box, direction):
        point = box[0]
        for half in box[1]:
            size = length(half)
            if size <= EPSILON:
                continue
            u = scale(half, 1.0/size)
            projection = dot(u, direction)
            distance = (math.copysign(size, projection) if abs(projection) > EPSILON
                        else max(-size, min(size, dot(sub(middle, box[0]), u))))
            point = add(point, scale(u, distance))
        return point
    point = scale(add(face(a, scale(normal, -1.0)), face(b, normal)), 0.5)
    return normal, depth, point


class Body(object):
    def __init__(self, components, frame):
        self.components = components
        self.props = properties(components)
        self.rotation = matrix(frame['attitude'])
        self.com = add(tuple(frame['position']), mul(self.rotation, self.props['centre']))
        self.velocity = tuple(frame.get('velocity', ZERO))
        self.angular = tuple(frame.get('angular_velocity', ZERO))
        self.grounded = bool(frame.get('grounded', False))
        self.sleeping = bool(frame.get('sleeping', False))
        self.impact_serial = int(frame.get('impact_serial', 0))
        self.impact = copy.deepcopy(frame.get('impact'))
        self.acks = copy.deepcopy(frame.get('acks', []))
        self.quiet_time = 0.0
        self.support_points = []
        self._box_cache = None
        self._local_points = tuple(corner
            for unused_name, unused_component, offset, bounds in components
            for corner in geometry._corners(bounds, offset))
        self.radius = max(length(sub(p, self.props['centre'])) for p in self._local_points)

    @property
    def position(self):
        return sub(self.com, mul(self.rotation, self.props['centre']))

    def frame(self):
        return {'position': self.position, 'attitude': angles(self.rotation),
                'centre': self.props['centre'],
                'velocity': self.velocity, 'angular_velocity': self.angular,
                'grounded': self.grounded, 'sleeping': self.sleeping,
                'impact_serial': self.impact_serial, 'impact': self.impact,
                'acks': copy.deepcopy(self.acks)}

    def boxes(self):
        key = (self.com, self.rotation)
        if self._box_cache is not None and self._box_cache[0] == key:
            return self._box_cache[1]
        result = []
        for unused_name, unused_component, offset, bounds in self.components:
            centre = tuple((bounds[0][i]+bounds[1][i])*0.5+offset[i] for i in range(3))
            axes = []
            for i in range(3):
                axis = [0.0]*3
                axis[i] = (bounds[1][i]-bounds[0][i])*0.5
                axes.append(mul(self.rotation, axis))
            result.append((add(self.position, mul(self.rotation, centre)), tuple(axes)))
        self._box_cache = (key, tuple(result))
        return self._box_cache[1]

    def points(self):
        position = self.position
        return tuple(add(position, mul(self.rotation, corner))
                     for corner in self._local_points)

    def inverse_inertia(self, value):
        return mul(self.rotation, mul(self.props['inverse_inertia'],
                                      mul(transpose(self.rotation), value)))

    def point_velocity(self, point):
        return add(self.velocity, cross(self.angular, sub(point, self.com)))

    def denominator(self, point, normal):
        arm = cross(sub(point, self.com), normal)
        return 1.0/self.props['mass'] + dot(arm, self.inverse_inertia(arm))

    def momentum(self, linear, angular):
        self.velocity = add(self.velocity, scale(linear, 1.0/self.props['mass']))
        self.angular = add(self.angular, self.inverse_inertia(angular))
        if length(linear) + length(angular) > EPSILON:
            self.sleeping = False
            self.quiet_time = 0.0

    def impulse(self, impulse, point):
        self.momentum(impulse, cross(sub(point, self.com), impulse))

    def kinetic_energy(self):
        local = mul(transpose(self.rotation), self.angular)
        return (0.5*self.props['mass']*dot(self.velocity, self.velocity) +
                0.5*dot(local, mul(self.props['inertia'], local)))

    def integrate(self, dt):
        self.com = add(self.com, add(scale(self.velocity, dt), (0, -0.5*9.81*dt*dt, 0)))
        self.velocity = add(self.velocity, (0, -9.81*dt, 0))
        self.rotation = rotate(self.rotation, self.angular, dt)


def frame_at(row, elapsed):
    """Read a new body checkpoint or migrate the initial accepted throw."""
    frame = row['flight'].get('body')
    if frame is not None:
        return copy.deepcopy(frame)
    flight = row['flight']
    position, attitude = turret_detachment.pose_at(flight, row['attitude'], row['spin'], elapsed)
    if elapsed >= flight['duration']:
        velocity, spin = ZERO, ZERO
    else:
        segment = flight['segments'][0]
        for candidate in flight['segments']:
            if elapsed >= candidate['start']:
                segment = candidate
        velocity = turret_detachment.flight_velocity(segment['velocity'], elapsed-segment['start'])
        spin = (row['spin'][1], row['spin'][0], row['spin'][2])
    return dict(position=position, attitude=attitude, velocity=velocity,
                angular_velocity=spin, grounded=False, sleeping=False)


def render_pose(frame, elapsed):
    # Extrapolation is bounded to one published motion slice; missed updates
    # cannot launch a remote body through terrain. Physics never uses this.
    dt = 0.0 if frame['sleeping'] else min(turret_detachment.FLIGHT_STEP_SECONDS, max(0.0, elapsed))
    rotation = rotate(matrix(frame['attitude']), frame['angular_velocity'], dt)
    centre = tuple(frame.get('centre', ZERO))
    com = add(tuple(frame['position']), mul(matrix(frame['attitude']), centre))
    position = sub(add(com, scale(tuple(frame['velocity']), dt)), mul(rotation, centre))
    if not frame['grounded']:
        position = add(position, (0, -0.5*9.81*dt*dt, 0))
    return position, angles(rotation)


def revision(row, body, now_ms):
    result = copy.deepcopy(row)
    frame = body.frame()
    position = frame['position']
    impact = frame['impact']
    result['flight'] = {
        'origin': position, 'velocity': frame['velocity'],
        'segments': [{'origin': position, 'velocity': frame['velocity'], 'start': 0.0, 'duration': 0.0}],
        'duration': 0.0, 'rest': position,
        'contact': impact['point'] if impact else (position if body.grounded else None),
        'impact_velocity': impact['velocity'] if impact else ZERO,
        'energy': impact['energy'] if impact else 0.0,
        'landed': bool(impact or body.grounded), 'rest_attitude': frame['attitude'], 'body': frame,
    }
    result.update(attitude=frame['attitude'], spin=ZERO, support_key=None,
                  motion_seq=row.get('motion_seq', 0)+1,
                  motion_time_ms=int(now_ms), created_time_ms=int(now_ms))
    return result


def scenery_step(body, dt, collide):
    """Sweep each component corner against actual scenery points/normals."""
    before = body.points()
    body.integrate(dt)
    after = body.points()
    contacts = []
    for start, end in zip(before, after):
        # The tiny skin only keeps an exact touching surface in the ray. It
        # is numerical tolerance, never a suspension height or upward lift.
        hit = collide(add(start, (0, EPSILON, 0)), sub(end, (0, EPSILON, 0)))
        if hit is None:
            continue
        point, normal = tuple(hit[0]), unit(tuple(hit[1]))
        if length(normal) <= EPSILON:
            continue
        penetration = max(0.0, -dot(sub(end, point), normal))
        if dot(sub(end, start), normal) > EPSILON:
            continue
        contacts.append((point, normal, penetration))
    was_grounded = body.grounded
    body.grounded = any(n[1] > 0.0 for p, n, d in contacts)
    if not contacts:
        body.support_points = []
        return
    initial_velocity = body.velocity
    # Resolve position independently, along the real scenery normal.
    correction = ZERO
    for point, normal, depth in contacts:
        remaining = depth-dot(correction, normal)
        if remaining > 0.0:
            correction = add(correction, scale(normal, remaining))
    body.com = add(body.com, correction)
    for unused in range(SOLVER_PASSES):
        for point, normal, unused_depth in contacts:
            closing = dot(body.point_velocity(point), normal)
            if closing < 0.0:
                body.impulse(scale(normal, -closing/body.denominator(point, normal)), point)
            # Maximum-dissipation, no-slip impact. Each scalar constraint
            # decreases kinetic energy; no bounce/drag constant is guessed.
            tangent = sub(body.point_velocity(point), scale(normal, dot(body.point_velocity(point), normal)))
            if length(tangent) > EPSILON:
                direction = unit(tangent)
                body.impulse(scale(direction, -length(tangent)/body.denominator(point, direction)), point)
    if not was_grounded and body.grounded:
        point, normal, unused_depth = max(contacts, key=lambda c: c[1][1])
        body.impact_serial += 1
        body.impact = {'point': point, 'normal': normal, 'velocity': initial_velocity,
                       'energy': turret_detachment.impact_energy(initial_velocity)}
    body.support_points = list(set(p for p, n, d in contacts if n[1] > 0.0))


def supported_com(body):
    """The COM projection must lie in a genuine support polygon to sleep."""
    points = sorted(set((p[0], p[2]) for p in body.support_points))
    if len(points) < 3:
        return False
    def turn(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for target, source in ((lower, points), (upper, reversed(points))):
        for p in source:
            while len(target) >= 2 and turn(target[-2], target[-1], p) <= EPSILON:
                target.pop()
            target.append(p)
    hull = lower[:-1] + upper[:-1]
    com = (body.com[0], body.com[2])
    return len(hull) >= 3 and all(turn(a, b, com) >= -EPSILON
                                 for a, b in zip(hull, hull[1:]+hull[:1]))


def vehicle_contact(body, boxes, mass, velocity, horizontal=False):
    """Return reciprocal vehicle delta and body momentum at a real contact."""
    boxes = tuple(b for b in boxes if length(sub(body.com, b[0])) <=
                  body.radius+sum(length(v) for v in b[1]))
    if not boxes:
        return None
    # A turret resting below the tracks is struck from the side. Retain
    # that entry face if a late snapshot already has a deeper overlap; the
    # shallow roof axis must not turn geometric recovery into an elevator.
    side = (body.grounded and min(p[1] for p in body.points()) <
            min(b[0][1]-sum(abs(v[1]) for v in b[1]) for b in boxes))
    contacts = [contact for a in body.boxes() for b in boxes
                for contact in [box_contact(a, b, horizontal=side)] if contact is not None]
    if horizontal and not side:
        contacts = [c for c in contacts if abs(c[0][1]) < max(abs(c[0][0]), abs(c[0][2]))]
    if not contacts:
        return None
    # Separate by the least occupied face, rather than the highest roof.
    normal, depth, point = min(contacts, key=lambda c: c[1])
    if horizontal:
        normal = unit((normal[0], 0.0, normal[2]))
        if length(normal) <= EPSILON:
            return None
    inv_vehicle = 1.0/mass
    relative = dot(sub(body.point_velocity(point), velocity), normal)
    impulse = ZERO
    if relative < 0.0:
        impulse = scale(normal, -relative/(body.denominator(point, normal)+inv_vehicle))
    opposite = scale(impulse, -inv_vehicle)
    linear_correction = scale(normal, depth/(1.0/body.props['mass']+inv_vehicle))
    return {'point': point, 'normal': normal, 'momentum': impulse,
            'angular_momentum': cross(sub(point, body.com), impulse),
            'delta': opposite,
            'body_correction': scale(linear_correction, 1.0/body.props['mass']),
            'vehicle_correction': scale(linear_correction, -inv_vehicle)}


def translate(body, displacement, collide):
    """Contact recovery may move debris only through free scenery."""
    fraction = 1.0
    for point in body.points():
        hit = collide(point, add(point, displacement))
        if hit is None or dot(displacement, hit[1]) >= -EPSILON:
            continue
        fraction = min(fraction, turret_detachment._segment_fraction(
            point, add(point, displacement), hit[0]))
    actual = scale(displacement, fraction)
    body.com = add(body.com, actual)
    return actual


def advance(body, dt, vehicles, collide, apply_vehicle=None):
    """Advance elapsed time with substeps and mass-aware vehicle contacts."""
    remaining = max(0.0, dt)
    if body.sleeping:
        # A sleeping body still checks its actual supporting scenery and
        # nearby moving vehicles. Destroyed support cannot leave it airborne.
        support = body.support_points
        stable = len(support) >= 3 and all(collide(add(p, (0, EPSILON, 0)),
                                                  sub(p, (0, EPSILON, 0))) is not None
                                                for p in support)
        touched = any(vehicle_contact(body, v['boxes'], v['mass'], v['velocity']) is not None
                      for v in vehicles)
        if stable and not touched:
            return
        body.sleeping = False
    while remaining > 1e-9:
        step = min(STEP, remaining)
        had_support = body.grounded
        scenery_step(body, step, collide)
        for unused_pass in range(SOLVER_PASSES):
            touched = False
            for vehicle in vehicles:
                hit = vehicle_contact(body, vehicle['boxes'], vehicle['mass'], vehicle['velocity'])
                if hit is None:
                    continue
                if hit['normal'][1] > max(abs(hit['normal'][0]), abs(hit['normal'][2])):
                    if not had_support and not body.grounded:
                        body.impact_serial += 1
                        body.impact = {'point': hit['point'], 'normal': hit['normal'],
                                       'velocity': body.velocity,
                                       'energy': turret_detachment.impact_energy(body.velocity)}
                    body.grounded = True
                # Living human horizontal impulses are consumed exactly once
                # from the visible integrator's cumulative ledger. Vertical
                # support remains worker-owned, as for terrain suspension.
                human_horizontal = (vehicle.get('human') and vehicle.get('alive', True) and
                                    abs(hit['normal'][1]) < max(abs(hit['normal'][0]), abs(hit['normal'][2])))
                if not human_horizontal:
                    body.momentum(hit['momentum'], hit['angular_momentum'])
                    if callable(apply_vehicle) and not vehicle.get('human'):
                        apply_vehicle(vehicle, hit, step)
                correction = hit['body_correction']
                if length(correction) > EPSILON:
                    translate(body, correction, collide)
                    touched = True
            if not touched:
                break
        remaining -= step
    # Gravity over one solver slice bounds the contact integrator's residual
    # energy. Sleep only below that numerical floor and over a support polygon;
    # neither an unsupported corner nor an arbitrary height can freeze a body.
    if (body.grounded and supported_com(body) and
            body.kinetic_energy() < 0.5*body.props['mass']*(9.81*STEP)**2):
        body.velocity, body.angular = ZERO, ZERO
        body.sleeping = True
