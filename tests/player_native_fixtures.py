"""Observed native geometry fixtures with no player or Bot decision imports.

These are the existing descriptor/matrix/angle boundaries used by foreground
tests. They do not replace targeting, navigation, trigger or armour algorithms.
"""
import math
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import ballistics, shot_geometry


class Matrix(object):
    """Only the native Matrix snapshot boundary used by the tested planner."""
    def __init__(self, value=None):
        self.yaw = getattr(value, 'yaw', 0.)
        self.pitch = getattr(value, 'pitch', 0.)
        self.roll = getattr(value, 'roll', 0.)
        self.translation = getattr(value, 'translation', (0., 0., 0.))


class PresentedMatrix(object):
    def __init__(self, target):
        self.target = target
        self.yaw = self.pitch = self.roll = 0.
        self.offset = (0., 0., 0.)

    @property
    def translation(self):
        return tuple(self.target.position[i] + self.offset[i] for i in range(3))


def descriptor(minimum=-1.5, maximum=.5, yaw_limits=None):
    box = lambda lo, hi: types.SimpleNamespace(bbox=(lo, hi))
    return types.SimpleNamespace(
        type=types.SimpleNamespace(tags=(), name='test:tank'),
        chassis=types.SimpleNamespace(hullPosition=(0., 0., 0.)),
        hull=types.SimpleNamespace(turretPositions=((0., 2., 0.),),
            hitTester=box((-1., .5, -2.), (1., 1.5, 2.))),
        turret=types.SimpleNamespace(gunPosition=(0., 0., 0.),
            hitTester=box((-.7, 0., -.7), (.7, 1., .7))),
        gun=types.SimpleNamespace(turretYawLimits=yaw_limits, staticTurretYaw=None,
            pitchLimits=dict(minPitch=((0., minimum), (2.*math.pi, minimum)),
                             maxPitch=((0., maximum), (2.*math.pi, maximum)))))


def aiming_scene(speed=300., gravity=10., distance=100., own_descriptor=None,
                 native='ballistic'):
    own_descriptor = own_descriptor or descriptor()
    shot = dict(speed=speed, gravity=gravity, maxDistance=5000., piercingPower=(150., 150.),
                shell=dict(kind='ARMOR_PIERCING', damage=(100., 0.), caliber=100.))
    origin = (0., 1., 0.)
    body = Matrix()
    own_entity = types.SimpleNamespace(id=1, typeDescriptor=own_descriptor)
    target = types.SimpleNamespace(id=42, position=(0., 0., distance),
        typeDescriptor=descriptor(), matrix=Matrix(), isStarted=True,
        isAlive=lambda: True, appearance=types.SimpleNamespace(turretMatrix=Matrix()))
    target.matrix = PresentedMatrix(target)
    rotator = types.SimpleNamespace(turretYaw=0., gunPitch=0., clientMode=True)
    owner = types.SimpleNamespace(_server=types.SimpleNamespace(vehicle_id=1),
        _server_entity=lambda unused: own_entity,
        _gun_state=types.SimpleNamespace(shots=[shot], shot_index=0),
        _mutable_shot_ray=lambda: (origin, (0., 0., 1.)),
        _local_stabilised_pose=lambda: body,
        _vector=tuple, _collision_shape=lambda unused: (1., 2., .5, 3.),
        _avatar=types.SimpleNamespace(gunRotator=rotator))

    def get_angles(desc, matrix, current, point):
        # This is a physical boundary oracle, not a stored expected answer:
        # the endpoint always selects the LOW ballistic root. High-arc tests
        # therefore require the player's source inversion to do real work.
        dx, dy, dz = (point[i]-origin[i] for i in range(3))
        yaw = math.atan2(dx, dz)
        if native == 'ballistic' and gravity > .01:
            roots = ballistics.ballistic_solutions(origin, point, speed, gravity)
            if not roots:
                raise ValueError('unreachable native source')
            pitch = roots[0][0]
        else:
            pitch = -math.atan2(dy, math.hypot(dx, dz))
        direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch),
                     math.cos(yaw)*math.cos(pitch))
        return shot_geometry.world_direction_to_local_gun_angles(
            direction, matrix.yaw, matrix.pitch, matrix.roll)

    owner._runtime = types.SimpleNamespace(math=types.SimpleNamespace(Matrix=Matrix),
                                           get_shot_angles=get_angles)
    return owner, target, shot, body
