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
    from ..ballistics import PROJECTILE_MAX_FLIGHT_SECONDS
    if not 0. < seconds <= PROJECTILE_MAX_FLIGHT_SECONDS:
        return False
    projected = [start[i]+direction[i]*speed*seconds for i in range(3)]
    projected[1] -= .5*abs(gravity)*seconds*seconds
    return sum((projected[i]-point[i])**2 for i in range(3)) <= radius*radius


def artillery_path(start, point, shot, direction=None, prefer_high=False):
    """Sample a candidate arc or the actual laid barrel, including zero gravity."""
    from .. import ballistics
    from ..gun_mechanics import _field
    try:
        speed = float(_field(shot, 'speed'))
        gravity = abs(float(_field(shot, 'gravity')))
        maximum = float(_field(shot, 'maxDistance'))
    except (TypeError, ValueError, OverflowError):
        return ()
    if (speed <= 0. or maximum <= 0. or
            any(math.isnan(v) or math.isinf(v)
                for v in (speed, gravity, maximum))):
        return ()
    dx, dy, dz = (point[i] - start[i] for i in range(3))
    if direction is None:
        if gravity == 0.:
            if prefer_high:
                return ()
            flight = math.sqrt(dx*dx+dy*dy+dz*dz) / speed
            pitch = -math.atan2(dy, math.hypot(dx, dz))
        else:
            solutions = ballistics.ballistic_solutions(start, point, speed, gravity)
            if not solutions or (prefer_high and len(solutions) < 2):
                return ()
            pitch, flight = solutions[-1] if prefer_high else solutions[0]
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


def hull_traverse_error(owner, descriptor, point, world_error, solution=None):
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
    if body is not None and solution is not None and solution.get('direction') is not None:
        from ..shot_geometry import world_direction_to_local_gun_angles
        matrix = runtime.math.Matrix(body)
        relative, unused = world_direction_to_local_gun_angles(
            solution['direction'], float(matrix.yaw), float(matrix.pitch), float(matrix.roll))
    elif body is not None and callable(get_angles):
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
        self.source_point = None
        self.solution = None
        self.acquired = 0.
        self.fired = False
        self.saved = None
        self.triggering = False
        self.committed = 0
        self.bound_source = None
        self.release_state = None

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
        point = self.source_point if self.source_point is not None else self.point
        return self.owner._vector(point) if point is not None else None

    def aim(self, target, point, now, solution=None):
        self.bind()
        previous = self.solution or {}
        current = solution or {}
        changed = (previous.get('arc'), previous.get('sample')) != (
            current.get('arc'), current.get('sample'))
        if self.target != target or changed:
            self.target, self.acquired, self.fired = target, now, False
        self.point = tuple(point)
        self.source_point = tuple(current.get('source_point') or point)
        self.solution = solution

    def aim_solution(self, target, solution, now):
        self.aim(target, solution['point'], now, solution=solution)

    def ready(self, now, factor):
        if self.solution is not None and (not self.solution.get('reachable') or
                                         self.solution.get('needs_hydraulic') or
                                         not self.solution.get('source_verified')):
            return False
        elapsed = now-self.acquired
        return (self.target is not None and elapsed >= REACTION_SECONDS and
                (self.fired or factor <= CONVERGED_FACTOR or elapsed >= PATIENCE_SECONDS))

    def trigger(self):
        # Avatar.shoot owns the native waiting token, triggers and muzzle/audio
        # handshake. The player's mailbox admits only this bounded call.
        self.triggering = True
        committed = self.committed
        controller = getattr(self.owner, '_player_control', None)
        player_committed = getattr(controller, 'automatic_commits',
                                   getattr(controller, 'shot_commits', 0))
        previous_intent = self.owner._local_fire_intent
        try:
            self.owner._avatar.shoot()
        finally:
            self.triggering = False
        committed_delta = max(self.committed-committed,
            getattr(controller, 'automatic_commits',
                    getattr(controller, 'shot_commits', 0))-player_committed)
        self.trigger_receipt = dict(committed_during_call=committed_delta,
            pending=isinstance(self.owner._local_fire_intent, dict),
            waiting=bool(getattr(self.owner._avatar, 'isWaitingForShot', False)))
        return bool(committed_delta) or (isinstance(self.owner._local_fire_intent, dict) and
                                         self.owner._local_fire_intent is not previous_intent)

    def forward(self, position, yaw, height):
        self.bind()
        self.target = None
        self.point = (position[0]+math.sin(yaw)*100.,position[1]+height,
                      position[2]+math.cos(yaw)*100.)
        self.source_point = self.point
        self.solution = None

    def close(self):
        if self.saved is not None:
            rotator, source, mode = self.saved
            if self.release_state is None:
                self.release_state = dict(source_done=False, mode_done=False, writing=False)
            state = self.release_state
            if state['writing']:
                raise RuntimeError('automatic_aim_release_pending')
            state['writing'] = True
            try:
                current = rotator._VehicleGunRotator__shotPointSourceFunctor
                if not state['source_done']:
                    if current is self.bound_source:
                        try:
                            rotator.shotPointSourceFunctor = source
                        finally:
                            current = rotator._VehicleGunRotator__shotPointSourceFunctor
                            if current is not self.bound_source:
                                state['source_done'] = True
                                # None selects a native default functor. A
                                # later retry may restore only that exact
                                # observed source, never a newer owner.
                                if source is not None and current is not source:
                                    state['mode_done'] = True
                                else:
                                    state['restored_source'] = current
                    else:
                        state['source_done'] = state['mode_done'] = True
                if not state['mode_done']:
                    current = rotator._VehicleGunRotator__shotPointSourceFunctor
                    if (current is state.get('restored_source') and
                            rotator.clientMode is True and mode is not True):
                        rotator.clientMode = mode
                    state['mode_done'] = True
            finally:
                state['writing'] = False
            self.saved = None
        self.release_state = None
        self.target = self.point = self.source_point = self.solution = None
