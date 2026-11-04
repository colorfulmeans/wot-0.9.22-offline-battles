"""Explicit, held foreground aiming with observed native completion.

An aim receipt completes when the real gun angles and muzzle direction agree
with the requested native point source. It does not assert a clear shot, a
future interception, or a hit. Completion retains the source until release,
replacement, loss of the selected visible target, or controller teardown.
"""
from __future__ import division

import math

from .. import ballistics
from ..gun_mechanics import _field
from .aiming import Aiming, _angle, _direction, _point, mechanical_reach
from .commands import INTEGER_TYPES, TERMINAL
from .test_actions import _same_identity


AIM_ACTIONS = frozenset(('aim_target', 'aim_point'))
ACTIONS = AIM_ACTIONS | frozenset(('release_aim',))
MAX_VISIBLE_TARGETS = 16
RELEASE_STAGE = 'manual_aim_release'
SOURCE_ATTRIBUTE = '_VehicleGunRotator__shotPointSourceFunctor'


def _finite(value):
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        raise ValueError('non-finite aim observation')
    return value


class ManualAim(object):
    """Own only the native aiming source; never drive or submit a shot.

    held includes completed leases and failed release obligations. busy means
    acquisition/release is unfinished, not that a completed hold expired.
    close is an idempotent, raising retry callback for control.release_pending.
    """
    def __init__(self, control):
        self.control = control
        self.operation = None
        self.generation = 0
        self.last = dict(held=False, aligned=False, command_id=None,
                         action=None, phase='idle', reason='idle', target_id=None,
                         point=None, tolerance_deg=None, observed_at=None)

    @property
    def held(self):
        return self.operation is not None

    @property
    def busy(self):
        return self.held and self.operation['phase'] != 'holding'

    @property
    def target_id(self):
        operation = self.operation
        return (operation['command']['args'].get('target_id') if operation is not None
                and operation['phase'] != 'releasing' else None)

    def _entity(self):
        try:
            owner = self.control.owner
            return owner._server_entity(owner._server.vehicle_id)
        except (AttributeError, TypeError, RuntimeError):
            return None

    def _visible(self):
        """Copy presentation-visible IDs without changing control velocities."""
        owner = self.control.owner
        targets = {}
        try:
            if not self.control.live():
                return targets
            own_id, team = owner._server.vehicle_id, int(owner.client.team)
            records = list(owner._records.values())
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return targets
        for record in records:
            try:
                engine_id = record.get('engine_id')
                if (not record.get('ready') or record.get('tombstone') or
                        not record.get('spot_visible', False) or
                        not isinstance(engine_id, INTEGER_TYPES) or isinstance(engine_id, bool) or
                        engine_id <= 0 or engine_id == own_id):
                    continue
                target_team = int((record.get('state') or {}).get('team', 0))
                if target_team not in (1, 2) or target_team == team:
                    continue
                target = owner._server_entity(engine_id)
                if (target is not None and target.id == engine_id and
                        target.isStarted and target.isAlive()):
                    _point(target.position)
                    targets[engine_id] = target
            except (AttributeError, TypeError, ValueError, RuntimeError, IndexError, OverflowError):
                continue
        return targets

    def _row(self, operation):
        return dict(held=True, aligned=bool(operation.get('aligned') and
                    operation['phase'] != 'releasing'),
                    command_id=operation['command'].get('id'),
                    action=operation['command']['action'], phase=operation['phase'],
                    reason=operation['reason'],
                    target_id=operation['command']['args'].get('target_id'),
                    point=list(operation['point']) if operation.get('point') is not None else None,
                    tolerance_deg=operation['tolerance_deg'],
                    observed_at=operation.get('observed_at'))

    def snapshot(self):
        result = self._row(self.operation) if self.operation is not None else dict(self.last)
        targets = self._visible()
        result['visible_targets'] = []
        for identity in sorted(targets)[:MAX_VISIBLE_TARGETS]:
            try:
                result['visible_targets'].append(dict(target_id=identity,
                    position=list(_point(targets[identity].position))))
            except (AttributeError, TypeError, ValueError, RuntimeError, IndexError, OverflowError):
                continue
        result['visible_targets_truncated'] = len(targets) > MAX_VISIBLE_TARGETS
        return result

    def _fire_pending(self):
        owner = self.control.owner
        return (getattr(owner, '_local_fire_intent', None) is not None or
                getattr(owner, '_local_player_burst', None) is not None or
                bool(getattr(owner._avatar, 'isWaitingForShot', False)))

    def preflight(self, command):
        action = command['action']
        if action not in ACTIONS:
            return None
        operation = self.operation
        if action == 'release_aim':
            expected = command['args'].get('command_id')
            if expected is not None and (operation is None or
                    expected != operation['command'].get('id')):
                return 'aim_owner_mismatch'
            return None
        if self.control.closed:
            return 'controller_closed'
        if not self.control.live():
            return 'battle_not_live'
        if command.get('id') is None:
            return 'command_id_required'
        if operation is not None:
            if operation['phase'] == 'releasing':
                return 'aim_release_pending'
            if operation['phase'] == 'installing' or not command.get('replace', True):
                return 'aim_busy'
        if self.control.active and 'fire' in self.control.features:
            return 'automatic_fire_active'
        if self._fire_pending():
            return 'gun_not_ready'
        if action == 'aim_target' and command['args'].get('target_id') not in self._visible():
            return 'aim_target_unavailable'
        try:
            rotator = self.control.owner._avatar.gunRotator
            getattr(rotator, SOURCE_ATTRIBUTE)
            rotator.clientMode
        except (AttributeError, RuntimeError):
            return 'aim_native_unavailable'
        return None

    def _solve(self, command, now):
        owner = self.control.owner
        target_id = command['args'].get('target_id')
        target = self._visible().get(target_id) if command['action'] == 'aim_target' else None
        if command['action'] == 'aim_target' and target is None:
            return None, 'aim_target_unavailable'
        try:
            point = _point(self.control.target_point(target) if target is not None
                           else command['args']['position'])
            # Reuse the reviewed native source solver, but not its automatic
            # target selection, velocity history, armour policy or shot gates.
            planner = Aiming(owner)
            planner.begin([], now)
            entity, gun = self._entity(), owner._gun_state
            own = planner._own()
            dx, dy, dz = (point[i] - own['origin'][i] for i in range(3))
            distance = math.sqrt(dx*dx + dy*dy + dz*dz)
            if distance <= .1:
                return None, 'aim_unreachable'
            if own['gravity'] > .01:
                roots = ballistics.ballistic_solutions(own['origin'], point,
                                                      own['speed'], own['gravity'])
                if not roots:
                    return None, 'aim_unreachable'
            else:
                roots = ((-math.atan2(dy, math.hypot(dx, dz)), distance / own['speed']),)
            reachable = False
            for pitch, flight in roots:
                if flight > ballistics.PROJECTILE_MAX_FLIGHT_SECONDS or own['speed']*flight > own['maximum']:
                    continue
                direction = _direction(math.atan2(dx, dz), pitch)
                reach = mechanical_reach(own['descriptor'], direction, own['body'])
                if not reach['reachable']:
                    continue
                reachable = True
                source = planner._source_point(own, point, reach)
                if source is not None:
                    return dict(point=point, source_point=_point(source), direction=direction,
                        origin=own['origin'], yaw=reach['local_yaw'], pitch=reach['local_pitch'],
                        target=target, entity=entity, gun=gun, shot_key=own['key']), None
            return None, 'aim_native_unavailable' if reachable else 'aim_unreachable'
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError, OverflowError):
            return None, 'aim_observation_unavailable'

    def _fresh(self, solution, command):
        """Reject changes during native reads, rather than certify old geometry."""
        try:
            entity = self._entity()
            if entity is not solution['entity']:
                return 'entity_changed'
            gun = self.control.owner._gun_state
            shot = gun.shots[gun.shot_index]
            key = (gun.shot_index, id(shot), _finite(_field(shot, 'speed')),
                   abs(_finite(_field(shot, 'gravity'))), _finite(_field(shot, 'maxDistance')),
                   id(_field(entity.typeDescriptor, 'gun')))
            if gun is not solution['gun'] or key != solution['shot_key']:
                return 'aim_observation_changed'
            if command['action'] == 'aim_target':
                target = self._visible().get(command['args']['target_id'])
                if target is None or target is not solution['target']:
                    return 'aim_target_unavailable'
                point = _point(self.control.target_point(target))
                if sum((point[i]-solution['point'][i])**2 for i in range(3)) > 1.e-8:
                    return 'aim_observation_changed'
            return None
        except (AttributeError, TypeError, ValueError, RuntimeError, KeyError, IndexError, OverflowError):
            return 'aim_observation_unavailable'

    def _alignment(self, solution, tolerance, shot_ray=None):
        try:
            rotator = self.control.owner._avatar.gunRotator
            yaw, pitch = _finite(rotator.turretYaw), _finite(rotator.gunPitch)
            if (abs(_angle(yaw-solution['yaw'])) > tolerance or
                    abs(pitch-solution['pitch']) > tolerance):
                return False
            rays = [self.control.owner._mutable_shot_ray()]
            if shot_ray is not None:
                rays.append(shot_ray)
            for origin, direction in rays:
                origin, direction = _point(origin), _point(direction)
                length = math.sqrt(sum(value*value for value in direction))
                if length <= 1.e-9:
                    return False
                dot = sum(direction[i]*solution['direction'][i]/length for i in range(3))
                if (sum((origin[i]-solution['origin'][i])**2 for i in range(3)) > 1.e-6 or
                        math.acos(max(-1., min(1., dot))) > tolerance):
                    return False
            return True
        except (AttributeError, TypeError, ValueError, RuntimeError, IndexError, OverflowError):
            return False

    def _finish(self, operation, status, reason, now, result=None):
        self.control.gateway.finish(operation['command']['id'], status, reason, now, result)

    def _queue_release(self, now):
        if not any(stage == RELEASE_STAGE for stage, unused in self.control.release_pending):
            self.control.release_pending.append((RELEASE_STAGE, self.close))
        self.control.next_release = max(getattr(self.control, 'next_release', 0.), now + 1.)

    def _release(self, operation, status, reason, now):
        if self.operation is not operation:
            return True
        if operation['phase'] != 'releasing':
            operation.update(phase='releasing', reason=reason, aligned=False)
        self._finish(operation, status, reason, now)
        if self.operation is not operation:
            return True
        try:
            self.close()
        except Exception:
            self._queue_release(now)
            return False
        return True

    def close(self):
        """Restore only our still-owned source/mode; raise for retry on failure."""
        operation = self.operation
        if operation is None:
            return
        if operation.get('writing'):
            raise RuntimeError('aim_native_inflight')
        operation.update(phase='releasing', aligned=False)
        rotator = operation['rotator']
        operation['writing'] = True
        try:
            current = getattr(rotator, SOURCE_ATTRIBUTE)
            if not operation.get('source_done'):
                if current is operation['source']:
                    try:
                        rotator.shotPointSourceFunctor = operation['saved_source']
                    finally:
                        current = getattr(rotator, SOURCE_ATTRIBUTE)
                        if current is not operation['source']:
                            operation['source_done'] = True
                            # None selects the native default functor. Capture
                            # that result rather than comparing it to None.
                            if (operation['saved_source'] is not None and
                                    current is not operation['saved_source']):
                                operation['mode_done'] = True
                            else:
                                operation['restored_source'] = current
                else:
                    # A newer source owns the channel. Its mode is not ours.
                    operation['source_done'] = True
                    operation['mode_done'] = True
            if not operation.get('mode_done'):
                current = getattr(rotator, SOURCE_ATTRIBUTE)
                if (operation.get('mode_attempted') and
                        current is operation.get('restored_source') and
                        rotator.clientMode is True and operation['saved_mode'] is not True):
                    rotator.clientMode = operation['saved_mode']
                operation['mode_done'] = True
        finally:
            operation['writing'] = False
        if self.operation is operation:
            self.last = self._row(operation)
            self.last.update(held=False, aligned=False, phase='idle')
            self.operation = None
            self.control.release_pending[:] = [item for item in self.control.release_pending
                                               if item[0] != RELEASE_STAGE]

    def _current(self, operation, now):
        if self.operation is not operation or operation['phase'] == 'releasing':
            return False
        reason, status = None, 'cancelled'
        if self.control.closed:
            reason = 'controller_closed'
        elif self.generation != operation['generation']:
            reason = 'aim_owner_changed'
        elif not _same_identity(operation['identity'], self.control.identity()):
            reason = 'identity_changed'
        elif self._entity() is not operation['entity']:
            reason = 'entity_changed'
        elif not self.control.live():
            reason = 'battle_not_live'
        elif now < operation['last_time']:
            reason = 'clock_changed'
        elif self.control.active and 'fire' in self.control.features:
            reason = 'automatic_fire_active'
        else:
            entry = self.control.gateway.requests.get(operation['command']['id'])
            receipt = entry.get('receipt', {}) if entry else {}
            if not operation['completed']:
                if receipt.get('status') in TERMINAL:
                    reason = receipt.get('reason', 'command_cancelled')
                elif now >= (entry.get('deadline', operation['deadline']) if entry else operation['deadline']):
                    reason, status = 'command_timeout', 'failed'
        if reason is not None:
            self._release(operation, status, reason, now)
            return False
        operation['last_time'] = now
        return True

    def _owned(self, operation):
        try:
            return (self.control.owner._avatar.gunRotator is operation['rotator'] and
                    self.generation == operation['generation'] and
                    self._entity() is operation['entity'] and
                    getattr(operation['rotator'], SOURCE_ATTRIBUTE) is operation['source'] and
                    operation['rotator'].clientMode is True)
        except (AttributeError, RuntimeError):
            return False

    def _source(self, operation):
        # Native source reads can be synchronous inside its property setter.
        # Rejected/cancelled leases must never supply a stale round's point.
        if (self.operation is not operation or operation['phase'] == 'releasing' or
                self.generation != operation['generation'] or
                self.control.closed or not self.control.live() or
                self._entity() is not operation['entity'] or
                not _same_identity(operation['identity'], self.control.identity())):
            return None
        if (not operation['completed'] and self.control.owner._clock() >= operation['deadline'] or
                operation['command']['action'] == 'aim_target' and
                operation['command']['args']['target_id'] not in self._visible()):
            return None
        point = operation.get('source_point')
        return self.control.owner._vector(point) if point is not None else None

    def execute(self, command, now):
        generation = self.generation
        if command['action'] not in ACTIONS:
            raise ValueError('unknown_manual_aim_action')
        reason = self.preflight(command)
        if reason is not None:
            return dict(status='failed', reason=reason)
        if generation != self.generation:
            return dict(status='cancelled', reason='aim_owner_changed')
        if command['action'] == 'release_aim':
            operation = self.operation
            released = operation is None or self._release(operation, 'cancelled', 'aim_released', now)
            return dict(status='completed' if released else 'failed',
                        reason='aim_released' if released else 'aim_release_pending',
                        result=self.snapshot())
        previous, identity, started = self.operation, dict(self.control.identity()), now
        solution, reason = self._solve(command, now)
        now = self.control.owner._clock()
        if reason is not None:
            return dict(status='failed', reason=reason)
        if (generation != self.generation or self.operation is not previous or
                not _same_identity(identity, self.control.identity())):
            return dict(status='cancelled', reason='aim_owner_changed')
        reason = self._fresh(solution, command)
        if reason is not None:
            return dict(status='failed', reason=reason)
        # Native proof is admission work, not an extension of the deadline.
        entry = self.control.gateway.requests.get(command['id'])
        deadline = entry.get('deadline') if entry else started + command.get('timeout_seconds', 10.)
        if now >= deadline:
            return dict(status='failed', reason='command_timeout')
        if previous is not None and not self._release(previous, 'cancelled', 'replaced', now):
            return dict(status='failed', reason='aim_release_pending')
        if generation != self.generation or self.operation is not None:
            return dict(status='cancelled', reason='aim_owner_changed')
        reason = self.preflight(command)
        if reason is not None:
            return dict(status='failed', reason=reason)
        if (generation != self.generation or not _same_identity(identity, self.control.identity())):
            return dict(status='cancelled', reason='aim_owner_changed')
        reason = self._fresh(solution, command)
        if reason is not None:
            return dict(status='failed', reason=reason)
        now = self.control.owner._clock()
        if now >= deadline:
            return dict(status='failed', reason='command_timeout')
        rotator = self.control.owner._avatar.gunRotator
        tolerance = float(command['args'].get('tolerance_deg', .5))
        operation = dict(command=dict(command, args=dict(command['args'])), identity=identity,
            deadline=deadline, last_time=now, completed=False, aligned=False,
            phase='installing', reason='aim_acquiring', observed_at=None,
            entity=solution['entity'], generation=generation,
            tolerance_deg=tolerance, tolerance=math.radians(tolerance), rotator=rotator,
            saved_source=getattr(rotator, SOURCE_ATTRIBUTE), saved_mode=rotator.clientMode,
            writing=False, mode_attempted=False, point=solution['point'],
            source_point=solution['source_point'], solution=solution)
        operation['source'] = lambda:self._source(operation)
        self.operation = operation
        error = None
        operation['writing'] = True
        try:
            rotator.shotPointSourceFunctor = operation['source']
            if (self.operation is operation and operation['phase'] == 'installing' and
                    getattr(rotator, SOURCE_ATTRIBUTE) is operation['source']):
                if rotator.clientMode is not True:
                    operation['mode_attempted'] = True
                    rotator.clientMode = True
        except Exception:
            error = 'aim_source_error'
        finally:
            operation['writing'] = False
        now = self.control.owner._clock()
        if operation['phase'] == 'releasing':
            self._release(operation, 'cancelled', operation['reason'], now)
            return None
        if not self._current(operation, now):
            return None
        if error is not None or not self._owned(operation):
            self._release(operation, 'failed', error or 'aim_source_lost', now)
            return None
        operation['phase'] = 'acquiring'
        self.update(now)
        return None

    def update(self, now):
        operation = self.operation
        if operation is None or not self._current(operation, now):
            return
        if operation['phase'] == 'installing':
            return
        if not self._owned(operation):
            self._release(operation, 'cancelled', 'aim_source_lost', now)
            return
        solution, reason = self._solve(operation['command'], now)
        now = self.control.owner._clock()
        if not self._current(operation, now):
            return
        if not self._owned(operation):
            self._release(operation, 'cancelled', 'aim_source_lost', now)
            return
        if reason is not None:
            self._release(operation, 'failed', reason, now)
            return
        aligned = self._alignment(solution, operation['tolerance'])
        fresh_reason = self._fresh(solution, operation['command'])
        now = self.control.owner._clock()
        if not self._current(operation, now):
            return
        if not self._owned(operation):
            self._release(operation, 'cancelled', 'aim_source_lost', now)
            return
        if fresh_reason is not None:
            operation.update(aligned=False, reason=fresh_reason, observed_at=now)
            if fresh_reason == 'aim_target_unavailable':
                self._release(operation, 'failed', fresh_reason, now)
            return
        operation.update(solution=solution, point=solution['point'],
            source_point=solution['source_point'], aligned=aligned, observed_at=now,
            reason='aim_aligned' if aligned else 'aim_tracking' if operation['completed'] else 'aim_acquiring')
        if aligned and not operation['completed']:
            # Mark the lease before emitting a receipt can synchronously stop
            # or replace it. Terminal journal entries do not expire this hold.
            operation.update(completed=True, phase='holding')
            self._finish(operation, 'completed', 'aim_aligned', now, self._row(operation))

    def fire_preflight(self, now=None, shot_ray=None):
        """Fresh read-only alignment gate; never release, steer or fire here."""
        operation = self.operation
        if operation is None:
            return None
        if operation['phase'] == 'releasing':
            return 'aim_release_pending'
        if operation['phase'] == 'installing':
            return 'aim_not_aligned'
        if not _same_identity(operation['identity'], self.control.identity()):
            return 'identity_changed'
        if self._entity() is not operation['entity']:
            return 'entity_changed'
        if self.control.closed or not self.control.live():
            return 'battle_not_live'
        if not self._owned(operation):
            return 'aim_source_lost'
        now = self.control.owner._clock() if now is None else now
        if now < operation['last_time']:
            return 'clock_changed'
        if not operation['completed'] and now >= operation['deadline']:
            return 'command_timeout'
        solution, reason = self._solve(operation['command'], now)
        if reason is not None:
            return reason
        aligned = self._alignment(solution, operation['tolerance'], shot_ray=shot_ray)
        fresh_reason = self._fresh(solution, operation['command'])
        if (self.operation is not operation or operation['phase'] == 'releasing' or not self._owned(operation) or
                not _same_identity(operation['identity'], self.control.identity()) or
                self.control.closed or not self.control.live()):
            return 'aim_source_lost'
        current_time = self.control.owner._clock()
        if current_time < operation['last_time']:
            return 'clock_changed'
        if not operation['completed'] and current_time >= operation['deadline']:
            return 'command_timeout'
        if fresh_reason is not None:
            return fresh_reason
        return None if aligned else 'aim_not_aligned'

    def cancel(self, command, reason):
        if command.get('action') not in ACTIONS:
            return False
        operation = self.operation
        if operation is not None and command.get('id') == operation['command'].get('id'):
            self.generation += 1
            self._release(operation, 'cancelled', reason, self.control.owner._clock())
        return True

    def stop(self, reason, now=None):
        self.generation += 1
        now = self.control.owner._clock() if now is None else now
        operation = self.operation
        return operation is None or self._release(operation, 'cancelled', reason, now)
