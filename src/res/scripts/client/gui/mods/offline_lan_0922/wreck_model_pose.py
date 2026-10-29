"""Replace only the suppressed #1513 local corpse refresh angle restore.

The compatibility owner retains two Math matrices and scalar identities, never
an entity, appearance, rotator or callback. Stock deactivation still owns the
display providers. No native filter sync or rotator animator is invoked here.
"""
import math


class _WreckAim(object):
    def __init__(self, math_module, identity, yaw, pitch):
        self.identity = identity
        self.yaw, self.pitch = yaw, pitch
        self.turretMatrix = math_module.Matrix()
        self.turretMatrix.setRotateYPR((yaw, 0.0, 0.0))
        self.gunMatrix = math_module.Matrix()
        self.gunMatrix.setRotateYPR((0.0, pitch, 0.0))


def _record(owner, phase, build):
    try:
        from gui.mods.offline_lan_0922.native_input_diagnostics import (
            detailed_enabled, battle_review_record)
        if detailed_enabled():
            battle_review_record(owner, 'wreck_pose_' + phase,
                getattr(owner, '_battle_player_vehicle_id', 0),
                owner._runtime.bigworld.time(), build,
                interval=0.0, limit=32)
    except Exception:
        pass


def clear(owner, reason, appearance=None):
    aim = getattr(owner, '_local_wreck_aim', None)
    owner._local_wreck_aim = None
    if aim is None:
        return
    try:
        if appearance is None:
            entity = owner._runtime.bigworld.entity(aim.identity[1])
            if id(entity) == aim.identity[2]:
                appearance = getattr(entity, 'appearance', None)
        if id(appearance) == aim.identity[3]:
            # Do not clear another writer installed since our last refresh.
            for name in ('turretMatrix', 'gunMatrix'):
                provider = getattr(appearance, name)
                if provider.target is getattr(aim, name):
                    provider.target = None
    except Exception:
        pass
    _record(owner, 'clear', lambda: dict(reason=reason, identity=list(aim.identity[1:])))


def _current(owner, appearance, context):
    battle, refresh, entity_identity = context
    if (not owner._battle_active or battle is None or
            battle is not getattr(owner, '_wreck_pose_battle', None) or
            refresh is not getattr(owner, '_compound_refresh_token', None) or
            appearance is not owner._compound_refreshing_models):
        return None
    entity = owner._original_compound_getattribute(
        appearance, '_CompoundAppearance__vehicle')
    vehicle_id = getattr(entity, 'id', 0)
    if (entity is None or id(entity) != entity_identity or
            vehicle_id != getattr(owner, '_battle_player_vehicle_id', 0) or
            owner._runtime.bigworld.entity(vehicle_id) is not entity or
            getattr(entity, 'appearance', None) is not appearance or
            getattr(entity, 'health', 1) > 0 or
            getattr(entity, 'isTurretDetached', True) or
            getattr(entity, '_offlineNativeRemote', False)):
        return None
    return (battle, vehicle_id, id(entity), id(appearance))


def restore(owner, appearance, context, yaw, pitch):
    """Called only by the proxy at stock __onModelsRefresh's final sync."""
    previous = None
    candidate = None
    try:
        identity = _current(owner, appearance, context)
        if identity is None:
            # A remote refresh must not release the local corpse's targets.
            aim = getattr(owner, '_local_wreck_aim', None)
            if (aim is not None and aim.identity[3] == id(appearance) and
                    context[0] is getattr(owner, '_wreck_pose_battle', None) and
                    context[1] is getattr(owner, '_compound_refresh_token', None) and
                    context[2] == aim.identity[2] and
                    appearance is owner._compound_refreshing_models):
                clear(owner, 'ineligible_refresh', appearance)
            return False
        yaw, pitch = float(yaw), float(pitch)
        if any(math.isnan(value) or math.isinf(value) for value in (yaw, pitch)):
            raise ValueError('non-finite stock refresh angles')
        retained = getattr(owner, '_local_wreck_aim', None)
        if retained is not None and retained.identity != identity:
            clear(owner, 'owner_changed')
            retained = None
        # Deactivate may have reset the provider again. Never replace an
        # accepted snapshot with that reset pose on a repeated corpse refresh.
        candidate = retained or _WreckAim(owner._runtime.math, identity, yaw, pitch)
        previous = (appearance.turretMatrix.target, appearance.gunMatrix.target)
        _record(owner, 'before', lambda: dict(stock_yaw=yaw, stock_pitch=pitch,
            retained=retained is not None, yaw=candidate.yaw, pitch=candidate.pitch,
            refresh_identity=id(context[1]),
            turret_provider=id(appearance.turretMatrix),
            gun_provider=id(appearance.gunMatrix),
            previous_targets=[id(value) for value in previous]))
        appearance.setupGunMatrixTargets(candidate)
        # Matrix(provider) reads the native display provider, not our input.
        turret = owner._runtime.math.Matrix(appearance.turretMatrix)
        gun = owner._runtime.math.Matrix(appearance.gunMatrix)
        yaw_error = (float(turret.yaw) - candidate.yaw + math.pi) % (2*math.pi) - math.pi
        pitch_error = float(gun.pitch) - candidate.pitch
        if (abs(yaw_error) > 0.0001 or abs(pitch_error) > 0.0001 or
                math.isnan(yaw_error) or math.isnan(pitch_error) or
                _current(owner, appearance, context) != identity):
            raise ValueError('display provider did not retain the corpse pose')
        owner._local_wreck_aim = candidate
        _record(owner, 'bound', lambda: dict(stock_yaw=yaw, stock_pitch=pitch,
            yaw=float(turret.yaw), pitch=float(gun.pitch),
            refresh_identity=id(context[1]),
            turret_target=id(candidate.turretMatrix), gun_target=id(candidate.gunMatrix)))
        return True
    except Exception as error:
        # A partial setup must release only our own targets. Preserve any
        # concurrent owner and the original suppressed native-sync behavior.
        if previous is not None and candidate is not None:
            for index, name in enumerate(('turretMatrix', 'gunMatrix')):
                try:
                    provider = getattr(appearance, name)
                    if provider.target is getattr(candidate, name):
                        prior = previous[index]
                        provider.target = None if prior is getattr(candidate, name) else prior
                except Exception:
                    pass
        if getattr(owner, '_local_wreck_aim', None) is candidate:
            owner._local_wreck_aim = None
        _record(owner, 'refused', lambda: dict(error=type(error).__name__, detail=str(error)))
        return False
