from __future__ import print_function

"""Install the local structural-armour fallback for tank RAM contacts.

The native #1513 collision callback proves that two tanks physically touched,
but the shell-oriented hit tester can occasionally return no structural plate
for that exact ray (for example at a hull/track seam). Ramming must not turn
that geometry miss into "no collision damage".

The first probe remains battle_runtime's exact contact-normal query. Only
when that query returns None do we retry a small neighbourhood on the same
contact face. Every accepted fallback is still a real native material with a
positive vehicleDamageFactor; no primaryArmor or guessed thickness is used.
"""

import math
import sys


_LOADER_MARKER = '_offline_lan_ram_contact_loader_patch'
_PROBE_MARKER = '_offline_lan_ram_contact_nearby_probe'
_BOOTSTRAP_MARKER = '_offline_lan_ram_contact_bootstrap_patch'

# Metres. These are deliberately local: enough to step off a collision-model
# seam or a track-only strip without wandering to another side of the tank.
_PROBE_RADII = (0.12, 0.30, 0.55)


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _patch_battle_runtime():
    from gui.mods.offline_lan_0922 import battle_runtime

    runtime_class = battle_runtime.BattleRuntime
    current = getattr(runtime_class, '_native_ram_vehicle_armor', None)
    if current is None:
        raise RuntimeError('BattleRuntime RAM armour probe is unavailable')
    if getattr(current, _PROBE_MARKER, False):
        return False
    original = current

    def nearby_structural_armor(self, vehicle, matrix, hit_point,
                                inward_normal, chassis_matrix=None):
        plate = original(
            self, vehicle, matrix, hit_point, inward_normal,
            chassis_matrix=chassis_matrix)
        if plate is not None:
            return plate

        descriptor = getattr(vehicle, 'typeDescriptor', None)
        if descriptor is None or matrix is None:
            return None
        normal = self._validated_ram_contact_normal(inward_normal)
        if normal is None:
            return None
        try:
            hit = battle_runtime._xyz(hit_point)
            center = battle_runtime._xyz(getattr(
                matrix, 'translation', getattr(vehicle, 'position', None)))
            shape = self._collision_shape(descriptor)
            low = float(center[1]) + float(shape[2])
            high = float(center[1]) + float(shape[3])
        except (AttributeError, IndexError, TypeError, ValueError,
                OverflowError):
            return None
        values = (hit[0], hit[1], hit[2], center[1], low, high)
        if any(_finite(value) is None for value in values) or high <= low:
            return None

        # The tangent keeps every retry on the same horizontal contact face.
        tangent = (-normal[1], normal[0])
        margin = min(0.03, max(0.005, (high - low) * 0.01))
        inside_low = low + margin
        inside_high = high - margin
        if inside_high <= inside_low:
            return None

        base_y = min(max(float(hit[1]), inside_low), inside_high)
        center_y = (low + high) * 0.5
        toward_center = 1.0 if center_y >= base_y else -1.0

        candidates = []
        if abs(base_y - float(hit[1])) > 1.0e-6:
            candidates.append((float(hit[0]), base_y, float(hit[2]),
                               'vertical-clamp', abs(base_y - float(hit[1]))))

        for radius in _PROBE_RADII:
            # Prefer a small move toward the chassis centre: a track-only
            # contact commonly has structural side armour immediately inward
            # in height, while this direction cannot wander into the turret.
            candidates.append((
                float(hit[0]),
                base_y + toward_center * radius,
                float(hit[2]),
                'vertical-inward', radius))
            # A vertical plate seam needs a sideways nudge instead. The ray
            # direction itself stays exactly the original contact normal.
            candidates.append((
                float(hit[0]) + tangent[0] * radius,
                base_y,
                float(hit[2]) + tangent[1] * radius,
                'tangent-positive', radius))
            candidates.append((
                float(hit[0]) - tangent[0] * radius,
                base_y,
                float(hit[2]) - tangent[1] * radius,
                'tangent-negative', radius))
            # Keep the opposite vertical search smaller. It is useful when
            # the exact point sits on a horizontal hull seam, but large moves
            # away from the chassis centre could select unrelated geometry.
            if radius <= 0.30:
                candidates.append((
                    float(hit[0]),
                    base_y - toward_center * radius,
                    float(hit[2]),
                    'vertical-outward', radius))

        seen = set()
        for x, y, z, kind, radius in candidates:
            y = min(max(float(y), inside_low), inside_high)
            key = (round(x, 4), round(y, 4), round(z, 4))
            if key in seen:
                continue
            seen.add(key)
            candidate = self._vector((x, y, z))
            plate = original(
                self, vehicle, matrix, candidate, normal,
                chassis_matrix=chassis_matrix)
            if plate is None:
                continue
            try:
                sys.stdout.write(
                    '[Offline LAN 0.9.22] RAM contact armor fallback '
                    'entity=%s kind=%s radius=%.3f armor=%.3f\n' % (
                        getattr(vehicle, 'id', '?'), kind, float(radius),
                        float(plate['armor'])))
            except Exception:
                pass
            return plate
        return None

    setattr(nearby_structural_armor, _PROBE_MARKER, True)
    runtime_class._native_ram_vehicle_armor = nearby_structural_armor
    return True


def _wrap_runtime_loader(module):
    loader = getattr(module, '_load_battle_runtime', None)
    if not callable(loader):
        raise RuntimeError('battle runtime loader is unavailable')
    if getattr(loader, _LOADER_MARKER, False):
        return False

    def load_and_patch(*args, **kwargs):
        result = loader(*args, **kwargs)
        _patch_battle_runtime()
        return result

    setattr(load_and_patch, _LOADER_MARKER, True)
    module._load_battle_runtime = load_and_patch
    return True


def _wrap_bootstrap_install(bootstrap, function_name, module_name):
    current = getattr(bootstrap, function_name, None)
    if not callable(current):
        raise RuntimeError('%s is unavailable' % function_name)
    if getattr(current, _BOOTSTRAP_MARKER, False):
        return False

    def install_session(*args, **kwargs):
        module = __import__(
            module_name, fromlist=['_load_battle_runtime'])
        _wrap_runtime_loader(module)
        return current(*args, **kwargs)

    setattr(install_session, _BOOTSTRAP_MARKER, True)
    setattr(bootstrap, function_name, install_session)
    return True


def install(bootstrap):
    """Patch both visible-client and hidden-worker lazy runtime loaders."""
    changed = False
    changed = _wrap_bootstrap_install(
        bootstrap, '_install_session',
        'gui.mods.offline_lan_0922.lan_session') or changed
    changed = _wrap_bootstrap_install(
        bootstrap, '_install_worker_session',
        'gui.mods.offline_lan_0922.authority_worker') or changed
    return changed
