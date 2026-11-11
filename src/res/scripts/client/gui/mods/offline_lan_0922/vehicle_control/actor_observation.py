"""Actor-specific physical observations for the single control algorithm.

This is an input binding, not a strategy or a second physical simulation.
Worker actors must install their own binding and may never read the observer's
foreground vehicle as an implicit source.
"""
from __future__ import division


def _point(value):
    try:
        return tuple(float(value[index]) for index in range(3))
    except (TypeError, IndexError):
        return float(value.x), float(value.y), float(value.z)


def observation(runtime):
    physical = getattr(runtime, 'physical', None)
    if physical is not None:
        return physical
    # Standalone foreground geometry consumers can bind without constructing
    # a whole controller. BOT bindings are always explicit, including tests.
    if getattr(runtime, 'actor_kind', 'human') != 'human':
        raise ValueError('actor_physical_binding_unavailable')
    return PlayerObservation(runtime)


class PlayerObservation(object):
    def __init__(self, runtime):
        self.runtime = runtime
        self.owner = runtime.owner

    @property
    def actor_team(self):
        return int(self.owner.client.team)

    @property
    def own_record_key(self):
        key = getattr(self.runtime, '_local_record_key', None)
        return key if key is not None else 'player:%d' % int(self.owner.client.player_id)

    def owns_record(self, record):
        return bool(record.get('local'))

    def source_entity(self):
        return self.owner._server_entity(self.owner._server.vehicle_id)

    def installed_descriptor(self):
        return getattr(self.owner, '_local_descriptor', None)

    def mutable_shot_ray(self):
        return self.owner._mutable_shot_ray()

    def gun_angles(self):
        rotator = self.owner._avatar.gunRotator
        return float(rotator.turretYaw), float(rotator.gunPitch)

    def source_pose(self, origin=None):
        owner = self.owner
        descriptor = self.source_entity().typeDescriptor
        if origin is None:
            origin = self.mutable_shot_ray()[0]
        matrix = owner._runtime.math.Matrix(owner._local_stabilised_pose())
        body = float(matrix.yaw), float(matrix.pitch), float(matrix.roll)
        return (_point(owner.local_pose()[0]), body, _point(origin),
                self.gun_angles(), id(descriptor), id(descriptor.gun),
                _point(matrix.translation))

    def weapon_identity(self):
        return self.owner._generation, id(self.runtime.gun)

    def physical_motion(self):
        owner, runtime = self.owner, self.runtime
        entity = self.source_entity()
        records = getattr(owner, '_records', {})
        record = records.get(getattr(runtime, '_local_record_key', None))
        if record is None:
            record = next((row for row in records.values() if row.get('local')), None)
        record = record or {}
        critical = next((state for state in (
            record.get('critical_state'), (record.get('state') or {}).get('critical'),
            (runtime.current_source() or {}).get('critical'))
            if isinstance(state, dict) and 'destroyed' in state), None)
        if critical is None:
            # Before the first damage payload the local repair path reads the
            # same live entity set. The set is allocated on first damage.
            destroyed = getattr(entity, '_destroyed_devices', None) or ()
        else:
            destroyed = critical['destroyed']
        airborne = owner._local_airborne
        if not isinstance(airborne, bool):
            raise ValueError('native support state is unavailable')
        return (tuple(sorted(str(name) for name in destroyed)), airborne,
                owner._local_speed, owner._local_turn_speed,
                owner._local_vertical_speed, int(entity.siegeState))

    def physical_params(self):
        return getattr(self.owner, '_local_physics', None)

    def support_plane(self):
        return getattr(self.owner, '_local_ground_plane', None)

    def support_rise_blocked(self):
        return bool(getattr(self.owner, '_local_support_rise_blocked', False))

    def trigger_active(self):
        return getattr(self.owner, '_local_player_burst', None) is not None

    def fire_intent_active(self):
        return getattr(self.owner, '_local_fire_intent', None) is not None

    def native_dispersion_angle(self):
        return float(self.owner._native_dispersion_angle())

    def native_siege_state(self):
        # The foreground's mode is the native Vehicle echo, not an input
        # request which may still be braking or awaiting acknowledgement.
        return int(getattr(self.runtime.entity, 'siegeState', 0))

    def mode_pending(self):
        return (getattr(self.owner, '_local_siege_pending', None) is not None or
                getattr(self.owner, '_local_siege_braking', None) is not None)

    def hydraulic_state(self):
        return dict(flat_matrix=getattr(self.owner, '_local_siege_flat_body_matrix', None),
                    pitch=getattr(self.owner, '_local_siege_aim_pitch', 0.))

    def control_current(self, control):
        return getattr(self.owner, '_player_control', None) is control
