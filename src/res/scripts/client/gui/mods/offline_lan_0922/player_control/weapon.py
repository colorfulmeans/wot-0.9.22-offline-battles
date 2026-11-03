"""Own the native player's aim source and trigger, without a Bot gunner."""
from __future__ import division
import math

# Snapshot of the explicitly requested elite reaction/laying contract. These
# are project tuning values, not retail gun coefficients or a runtime Bot call.
REACTION_SECONDS = .25
PATIENCE_SECONDS = 2.40
CONVERGED_FACTOR = 1.12


def barrel_aligned(start, direction, speed, gravity, point, radius):
    """Check the actual curved shot, not a straight cursor ray."""
    horizontal = direction[0]**2+direction[2]**2
    if speed <= 0 or horizontal <= 1.e-8:
        return False
    seconds = ((point[0]-start[0])*direction[0]+(point[2]-start[2])*direction[2])/(speed*horizontal)
    if seconds <= 0:
        return False
    projected = [start[i]+direction[i]*speed*seconds for i in range(3)]
    projected[1] -= .5*gravity*seconds*seconds
    return sum((projected[i]-point[i])**2 for i in range(3)) <= radius*radius


def artillery_path(start, point, shot, direction=None):
    """Sample a candidate artillery arc, or the actual laid barrel's arc."""
    from .. import ballistics
    from ..gun_mechanics import _field
    speed = float(_field(shot, 'speed'))
    gravity = abs(float(_field(shot, 'gravity')))
    maximum = float(_field(shot, 'maxDistance', float('inf')))
    if speed <= 0. or gravity <= 0.:
        return ()
    dx, dz = point[0] - start[0], point[2] - start[2]
    if direction is None:
        solutions = ballistics.ballistic_solutions(start, point, speed, gravity)
        if not solutions:
            return ()
        pitch, flight = solutions[0]
        yaw = math.atan2(dx, dz)
    else:
        x, y, z = direction
        horizontal = x*x + z*z
        if horizontal <= 1.e-8:
            return ()
        flight = (dx*x + dz*z) / (speed * horizontal)
        yaw = math.atan2(x, z)
        pitch = math.atan2(-y, math.sqrt(horizontal))
    if not 0. < flight <= ballistics.PROJECTILE_MAX_FLIGHT_SECONDS or speed*flight > maximum:
        return ()
    return ballistics.ballistic_path(start, yaw, pitch, speed, gravity, flight)


def hull_traverse_error(owner, descriptor, point, world_error):
    """Return the extra hull rotation needed by the mounted gun."""
    from ..gun_mechanics import _field
    from .driving import angle
    limits = _field(_field(descriptor, 'gun'), 'turretYawLimits')
    if limits is None:
        return None
    minimum, maximum = map(float, limits)
    body = owner._local_stabilised_pose()
    runtime = owner._runtime
    get_angles = getattr(runtime, 'get_shot_angles', None)
    relative = world_error
    if body is not None and callable(get_angles):
        rotator = owner._avatar.gunRotator
        relative, unused = get_angles(descriptor, runtime.math.Matrix(body),
            (float(rotator.turretYaw), float(rotator.gunPitch)), owner._vector(point))
    relative = angle(relative)
    # Lay the gun slightly inside its stop so that a small position
    # change does not toggle between the gun and hull every frame.
    if minimum <= relative <= maximum:
        return 0.
    margin = min(.08, (maximum - minimum) * .5)
    return relative - (minimum + margin if relative < minimum else maximum - margin)


class Weapon(object):
    def __init__(self, owner):
        self.owner = owner
        self.target = None
        self.point = None
        self.acquired = 0.
        self.fired = False
        self.saved = None
        self.triggering = False
        self.committed = 0
        self.bound_source = None

    def bind(self):
        rotator = self.owner._avatar.gunRotator
        if self.saved is None:
            self.owner._avatar.autoAim(None)
            self.saved = (rotator, rotator._VehicleGunRotator__shotPointSourceFunctor,
                          rotator.clientMode)
            origin, direction = self.owner._mutable_shot_ray()
            self.point = tuple(origin[i]+direction[i]*100. for i in range(3))
            self.bound_source = self.shot_point
            rotator.shotPointSourceFunctor = self.bound_source
            rotator.clientMode = True

    def shot_point(self):
        return self.owner._vector(self.point) if self.point is not None else None

    def aim(self, target, point, now):
        self.bind()
        if self.target != target:
            self.target, self.acquired, self.fired = target, now, False
        self.point = tuple(point)

    def ready(self, now, factor):
        elapsed = now-self.acquired
        return (self.target is not None and elapsed >= REACTION_SECONDS and
                (self.fired or factor <= CONVERGED_FACTOR or elapsed >= PATIENCE_SECONDS))

    def trigger(self):
        # Avatar.shoot owns the native waiting token, triggers and muzzle/audio
        # handshake. The player's mailbox admits only this bounded call.
        self.triggering = True
        committed = self.committed
        controller = getattr(self.owner, '_player_control', None)
        player_committed = getattr(controller, 'shot_commits', 0)
        try:
            self.owner._avatar.shoot()
        finally:
            self.triggering = False
        committed_delta = max(self.committed-committed,
            getattr(controller, 'shot_commits', 0)-player_committed)
        self.trigger_receipt = dict(committed_during_call=committed_delta,
            pending=isinstance(self.owner._local_fire_intent, dict),
            waiting=bool(getattr(self.owner._avatar, 'isWaitingForShot', False)))
        return bool(committed_delta) or isinstance(self.owner._local_fire_intent, dict)

    def forward(self, position, yaw, height):
        self.bind()
        self.target = None
        self.point = (position[0]+math.sin(yaw)*100.,position[1]+height,
                      position[2]+math.cos(yaw)*100.)

    def close(self):
        if self.saved is not None:
            rotator, source, mode = self.saved
            if rotator._VehicleGunRotator__shotPointSourceFunctor is self.bound_source:
                rotator.shotPointSourceFunctor = source
                rotator.clientMode = mode
            self.saved = None
        self.target = self.point = None
