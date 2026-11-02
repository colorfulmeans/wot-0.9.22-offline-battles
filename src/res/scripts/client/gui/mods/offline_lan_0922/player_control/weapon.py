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
