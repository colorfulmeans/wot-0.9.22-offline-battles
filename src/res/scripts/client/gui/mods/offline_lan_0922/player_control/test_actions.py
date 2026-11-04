"""Bounded foreground observations and native gun-setting transactions.

TestActions(control) exposes preflight/execute/update/cancel/stop/snapshot and
gun_pending. Read-only waiters survive stop, never own movement, and cannot
cross session/round/player identity. Gun cancellation only stops observation;
it cannot undo an already submitted reload or shell selection.

Observation arguments use ``condition``. ammo_ready/ammo_empty/halted take no
extra arguments; active takes bool value; mission_status/mission_phase take a
value and optional command_id; shot_terminal/shot_effect take exactly one of
projectile_id/command_id, with optional non-negative damage_min for shot_effect.
select_shell takes a mounted positive integer compact_descr; reload takes none.
"""
from __future__ import division

import math

from ..gun_mechanics import _field
from .capabilities import ammunition_state
from .commands import INTEGER_TYPES, MISSIONS, STRING_TYPES, TERMINAL


READ_ONLY = frozenset(('wait_state', 'assert_state'))
GUN_ACTIONS = frozenset(('select_shell', 'reload'))
ACTIONS = READ_ONLY | GUN_ACTIONS
MAX_WATCHERS = 32
MAX_SHELLS = 16
MAX_PROJECTILES = 128
MAX_SHOT_DETAILS = 8
MISSION_STATUSES = frozenset(('idle', 'pending', 'running', 'completed', 'failed', 'cancelled'))
MISSION_PHASES = frozenset(('idle', 'attacking', 'travelling', 'capture_travel',
                          'arriving', 'capturing', 'captured', 'defending',
                          'holding', 'failed', 'cancelled'))


def _positive_int(value):
    return isinstance(value, INTEGER_TYPES) and not isinstance(value, bool) and value > 0


def _same_identity(left, right):
    def kind(value):
        return (bool if isinstance(value, bool) else int if isinstance(value, INTEGER_TYPES)
                else str if isinstance(value, STRING_TYPES) else type(value))
    return all(left.get(key) == right.get(key) and kind(left.get(key)) == kind(right.get(key))
               for key in ('session_id', 'round_id', 'player_id'))


class TestActions(object):
    def __init__(self, control):
        self.control = control
        self.watchers = {}
        self.gun_pending = None
        self.last_observation = None
        self.closed = False

    @property
    def busy(self):
        return self.gun_pending is not None

    def _ammo(self):
        try:
            return ammunition_state(self.control.owner._gun_state)
        except (AttributeError, TypeError, ValueError, RuntimeError, OverflowError):
            return ammunition_state(None)

    def _gun_snapshot(self):
        result = self._ammo()
        gun = getattr(self.control.owner, '_gun_state', None)
        result.update(stock=[], stock_truncated=False, pending_index=None, clip_size=None)
        if not result['available']:
            return result
        pending, size = getattr(gun, 'pending_index', None), getattr(gun, 'clip_size', None)
        result['pending_index'] = (pending if isinstance(pending, INTEGER_TYPES) and
            not isinstance(pending, bool) and 0 <= pending < len(gun.shots) else None)
        result['clip_size'] = size if _positive_int(size) else None
        result['stock_truncated'] = len(gun.shots) > MAX_SHELLS
        for index, shot in enumerate(gun.shots[:MAX_SHELLS]):
            compact = _field(_field(shot, 'shell', {}), 'compactDescr')
            result['stock'].append(dict(index=index, ammo=int(gun.ammo[index]),
                                       compact_descr=compact if _positive_int(compact) else None))
        return result

    def snapshot(self):
        pending = self.gun_pending
        last = self.last_observation or {}
        return dict(watcher_count=len(self.watchers), gun=self._gun_snapshot(),
            gun_pending=(dict(id=pending['command']['id'], action=pending['command']['action'],
                compact_descr=pending['compact_descr'], shell_index=pending['index'],
                phase=pending['phase'])
                if pending is not None else None),
            last_observation=dict((key, last[key]) for key in
                ('condition', 'known', 'matched', 'reason', 'time') if key in last))

    def _fire_pending(self):
        owner = self.control.owner
        return (getattr(owner, '_local_fire_intent', None) is not None or
                getattr(owner, '_local_player_burst', None) is not None)

    def _selection(self, command):
        """Return the mounted target and whether an actual setting is needed."""
        owner = self.control.owner
        gun = getattr(owner, '_gun_state', None)
        ammo = self._ammo()
        if not ammo['available']:
            return None, 'ammunition_unknown'
        current = ammo['shell_index']
        if command['action'] == 'select_shell':
            compact = command['args'].get('compact_descr')
            if not _positive_int(compact):
                return None, 'invalid_compact_descr'
            matches = [index for index, shot in enumerate(gun.shots)
                       if _positive_int(_field(_field(shot, 'shell', {}), 'compactDescr')) and
                       _field(_field(shot, 'shell', {}), 'compactDescr') == compact]
            if len(matches) != 1:
                return None, 'shell_not_mounted' if not matches else 'ambiguous_mounted_shell'
            index = matches[0]
            needed = index != current or getattr(gun, 'pending_index', None) is not None
        else:
            size = getattr(gun, 'clip_size', None)
            if not _positive_int(size):
                return None, 'ammunition_unknown'
            if size <= 1:
                return None, 'reload_not_supported'
            index = current
            # An empty cassette already has a full reload in progress. R must
            # not reset it, including when the user preselected a later shell.
            reloading = ammo['clip'] == 0 and ammo['reload_seconds'] > 0.
            pending = getattr(gun, 'pending_index', None)
            if (not reloading and isinstance(pending, INTEGER_TYPES) and
                    not isinstance(pending, bool) and 0 <= pending < len(gun.ammo) and
                    gun.ammo[pending] > 0):
                index = pending
            needed = not reloading and (ammo['clip'] < size or index != current)
            compact = _field(_field(gun.shots[index], 'shell', {}), 'compactDescr')
        if gun.ammo[index] <= 0 or command['action'] == 'reload' and gun.ammo[current] <= 0:
            return None, 'shell_empty'
        if not _positive_int(compact):
            return None, 'mounted_shell_unavailable'
        try:
            settings = owner._runtime.constants.VEHICLE_SETTING
            setting = (settings.CURRENT_SHELLS if command['action'] == 'select_shell'
                       else settings.RELOAD_PARTIAL_CLIP)
        except AttributeError:
            return None, 'gun_settings_unavailable'
        return dict(gun=gun, index=index, compact_descr=compact, needed=needed,
                    setting=setting), None

    def preflight(self, command):
        action = command['action']
        if action not in ACTIONS:
            return None
        if self.closed or self.control.closed:
            return 'controller_closed'
        if action in READ_ONLY:
            if (action == 'wait_state' and command.get('id') not in self.watchers and
                    len(self.watchers) >= MAX_WATCHERS):
                return 'observation_limit'
            return None
        if not self.control.live():
            return 'battle_not_live'
        if self.gun_pending is not None:
            return 'gun_operation_busy'
        if self.control.active and 'fire' in self.control.features:
            return 'automatic_fire_active'
        if self._fire_pending():
            return 'gun_not_ready'
        selection, reason = self._selection(command)
        if reason:
            return reason
        if command.get('id') is None and (selection['needed'] or not self._ready(selection, command['action'])):
            return 'command_id_required'
        return None

    def _operation(self, command, now):
        return dict(command=dict(command, args=dict(command['args'])),
                    identity=dict(self.control.identity()),
                    deadline=now + command.get('timeout_seconds', 10.))

    def execute(self, command, now):
        action = command['action']
        if action not in ACTIONS:
            raise ValueError('unknown_test_action')
        if action in READ_ONLY:
            observation = self._observe(command['args'], now)
            self.last_observation = observation
            if observation['matched']:
                return dict(reason='condition_observed', result=observation)
            if action == 'assert_state' or observation.get('impossible'):
                return dict(status='failed', reason=observation['reason'], result=observation)
            if command.get('id') is None:
                return dict(status='failed', reason='command_id_required', result=observation)
            self.watchers[command['id']] = self._operation(command, now)
            return None
        selection, reason = self._selection(command)
        if reason:
            return dict(status='failed', reason=reason)
        operation = self._operation(command, now)
        operation.update(selection)
        operation['phase'] = 'submitting' if selection['needed'] else 'observing'
        # Install ownership before native setting/HUD code can re-enter us.
        self.gun_pending = operation
        outcome = None
        if selection['needed']:
            value = selection['compact_descr'] if action == 'select_shell' else 0
            try:
                accepted = self.control.owner.change_vehicle_setting(selection['setting'], value)
                if not accepted:
                    outcome = dict(status='failed', reason='gun_setting_rejected',
                                   result=self._gun_snapshot())
            except Exception as error:
                outcome = dict(status='failed', reason='gun_setting_error',
                               result=dict(error=str(error)[:160], gun=self._gun_snapshot()))
            # Native work may consume the execution deadline or change the
            # owner without re-entering update. Keep its physical effect, but
            # never report it as this operation's success after that boundary.
            now = self.control.owner._clock()
            if not self._current(operation, now):
                return None
            operation['phase'] = 'observing'
        if outcome is None:
            outcome = self._gun_outcome(operation)
        if outcome is not None:
            if selection['needed'] and command.get('id') is not None:
                # Gateway.submit still holds the pre-native admission time.
                self._finish(operation, outcome.get('status', 'completed'),
                             outcome['reason'], now, outcome.get('result'))
                return None
            self.gun_pending = None
            return outcome
        return None

    def _ready(self, operation, action):
        ammo = self._ammo()
        if (not ammo['available'] or ammo['shell_index'] != operation['index'] or
                not ammo['can_fire'] or ammo['reload_seconds'] > 0. or ammo['clip'] <= 0 or
                self._fire_pending()):
            return False
        gun = operation['gun']
        return action != 'reload' or ammo['clip'] >= min(gun.clip_size, gun.ammo[operation['index']])

    def _gun_outcome(self, operation):
        if not self.control.live():
            return dict(status='failed', reason='battle_not_live')
        if self.control.active and 'fire' in self.control.features:
            return dict(status='cancelled', reason='automatic_fire_active')
        gun = getattr(self.control.owner, '_gun_state', None)
        if gun is not operation['gun']:
            return dict(status='failed', reason='gun_changed')
        ammo = self._ammo()
        if not ammo['available']:
            return None
        compact = _field(_field(gun.shots[operation['index']], 'shell', {}), 'compactDescr') if operation['index'] < len(gun.shots) else None
        if compact != operation['compact_descr'] or ammo['shell_index'] != operation['index']:
            return dict(status='failed', reason='shell_changed', result=self._gun_snapshot())
        if gun.ammo[operation['index']] <= 0:
            return dict(status='failed', reason='shell_empty', result=self._gun_snapshot())
        if self._ready(operation, operation['command']['action']):
            return dict(reason='shell_ready' if operation['command']['action'] == 'select_shell'
                        else 'reload_completed', result=self._gun_snapshot())
        return None

    def _fire_rows(self, args):
        ledger = self.control.shot_receipts
        if 'projectile_id' in args:
            row = ledger.get(args['projectile_id'])
            return ([row], None, None) if row is not None else ([], 'shot_not_observed', None)
        command_id = args['command_id']
        entry = self.control.gateway.requests.get(command_id)
        receipt = entry.get('receipt', {}) if entry else {}
        if receipt.get('action') != 'fire' or not _same_identity(receipt, self.control.identity()):
            return [], 'fire_command_not_observed', None
        if receipt.get('status') != 'completed':
            return [], ('fire_command_' + receipt.get('status', 'unknown')), receipt.get('status') in TERMINAL
        # A final normal fire receipt owns the complete actual commit list.
        # Never infer a tail from burst_count or from the rows seen so far.
        identities = (receipt.get('result') or {}).get('projectile_ids')
        if (not isinstance(identities, (list, tuple)) or not identities or
                len(identities) > MAX_PROJECTILES or
                any(not isinstance(value, STRING_TYPES) or not value for value in identities) or
                len(set(identities)) != len(identities)):
            return [], 'committed_projectiles_unavailable', None
        pending = getattr(self.control.owner, '_local_player_burst', None)
        context = (pending.get('player_control') or {}) if isinstance(pending, dict) else {}
        if context.get('command') == command_id and pending.get('committed', 0) < pending.get('count', 1):
            return [], 'fire_command_pending_tail', None
        rows = [ledger.get(identity) for identity in identities]
        if any(row is None or row.get('command_id') != command_id for row in rows):
            return [], 'shot_not_observed', None
        return rows, None, None

    def _shot_observation(self, args, observation):
        rows, reason, impossible = self._fire_rows(args)
        if reason:
            observation.update(known=bool(impossible), reason=reason, impossible=bool(impossible))
            return observation
        details, damage, hits = [], 0., 0
        rejected = 0
        for row in rows:
            value, count = row.get('damage_total'), row.get('hit_count')
            if (not isinstance(value, INTEGER_TYPES + (float,)) or isinstance(value, bool) or
                    math.isnan(value) or math.isinf(value) or value < 0. or
                    not isinstance(count, INTEGER_TYPES) or isinstance(count, bool) or count < 0):
                observation['reason'] = 'shot_observation_unavailable'
                return observation
            if row['flight_status'] == 'rejected':
                rejected += 1
            else:
                damage += value
                hits += count
            if len(details) < MAX_SHOT_DETAILS:
                details.append(dict(projectile_id=row['projectile_id'], flight_status=row['flight_status'],
                    damage_total=row['damage_total'], hit_count=row['hit_count'],
                    terminal_observed=row['terminal_at'] is not None))
        if math.isnan(damage) or math.isinf(damage):
            observation['reason'] = 'shot_observation_unavailable'
            return observation
        observation.update(projectile_count=len(rows), projectiles=details,
            details_truncated=len(rows) > MAX_SHOT_DETAILS, rejected_count=rejected,
            damage_total=damage, hit_count=hits)
        if args['condition'] == 'shot_terminal':
            matched = all(row['flight_status'] == 'terminal' for row in rows)
            observation.update(known=True, matched=matched, value=matched,
                impossible=bool(rejected), reason='shot_rejected' if rejected else
                'condition_observed' if matched else 'flight_pending')
        else:
            matched = hits > 0 and damage >= args.get('damage_min', 0.)
            observation.update(known=bool(hits) or rejected == len(rows), matched=matched,
                value=damage if 'damage_min' in args else bool(hits),
                impossible=rejected == len(rows), reason='shot_rejected' if rejected == len(rows) else
                'condition_observed' if matched else 'damage_below_minimum' if hits else 'combat_not_observed')
        return observation

    def _observe(self, args, now):
        condition = args['condition']
        observation = dict(condition=condition, time=now, known=False, matched=False,
                           reason='observation_unavailable',
                           expected=args.get('value', args.get('damage_min', True)))
        if condition in ('ammo_ready', 'ammo_empty'):
            ammo = self._ammo()
            value = ammo['can_fire'] if condition == 'ammo_ready' else ammo['empty']
            observation.update(known=ammo['available'], value=bool(value), ammo=ammo,
                               matched=bool(ammo['available'] and value))
        elif condition == 'active':
            observation.update(known=True, value=bool(self.control.active),
                               matched=bool(self.control.active) == args['value'])
        elif condition == 'halted':
            # This manager also runs before the controller's halt branch. A
            # previous settled receipt cannot hide motion that began since.
            if self.control.halted:
                self.control.halt_observation.observe(
                    self.control.owner, now, bool(self.control.release_pending))
            halt = dict(self.control.halt_observation.receipt)
            known = not self.control.halted or bool(halt.get('known'))
            value = bool(self.control.halted and halt.get('known') and halt.get('settled'))
            observation.update(known=known, value=value, matched=value, halt=halt)
        elif condition in ('mission_status', 'mission_phase'):
            navigation = self.control.navigation
            mission = navigation.mission_status() if navigation is not None else dict(id=None, status='idle', phase='idle')
            command_id = args.get('command_id')
            observation['source'] = 'current_mission'
            if command_id is not None and mission.get('id') != command_id:
                entry = self.control.gateway.requests.get(command_id)
                receipt = entry.get('receipt', {}) if entry else {}
                result = receipt.get('result')
                mission = None
                observation['source'] = 'mission_not_observed'
                if (receipt.get('action') in MISSIONS and
                        _same_identity(receipt, self.control.identity())):
                    status = receipt.get('status')
                    if status == 'rejected':
                        observation.update(source='command_rejection', impossible=True,
                                           reason='mission_not_admitted')
                        return observation
                    if status in ('completed', 'failed', 'cancelled'):
                        if isinstance(result, dict) and result.get('id') == command_id:
                            mission = result
                            observation['source'] = 'command_result'
                        else:
                            # Stop, timeout and replacement have real terminal
                            # command receipts even after navigation teardown.
                            # They prove task status, never an unobserved phase.
                            mission = dict(id=command_id, action=receipt['action'],
                                           status=status, reason=receipt.get('reason'))
                            observation['source'] = 'command_terminal'
                        if condition == 'mission_phase' and mission.get('phase') not in MISSION_PHASES:
                            observation.update(mission=dict(mission), impossible=True,
                                               reason='mission_phase_unavailable')
                            return observation
            if mission is not None:
                field = 'status' if condition == 'mission_status' else 'phase'
                values = MISSION_STATUSES if field == 'status' else MISSION_PHASES
                known = mission.get(field) in values
                observation.update(known=known, value=mission.get(field), mission=dict(mission),
                                   matched=bool(known and mission[field] == args['value']))
        elif condition in ('shot_terminal', 'shot_effect'):
            return self._shot_observation(args, observation)
        else:
            observation['reason'] = 'unknown_condition'
            return observation
        observation['reason'] = ('condition_observed' if observation['matched'] else
                                 'assertion_failed' if observation['known'] else 'observation_unavailable')
        return observation

    def _remove(self, operation):
        if self.gun_pending is operation:
            self.gun_pending = None
        command_id = operation['command'].get('id')
        if self.watchers.get(command_id) is operation:
            self.watchers.pop(command_id, None)

    def _finish(self, operation, status, reason, now, result=None):
        self._remove(operation)
        self.control.gateway.finish(operation['command']['id'], status, reason, now, result)

    def _current(self, operation, now, identity=None):
        if (operation is not self.gun_pending and
                self.watchers.get(operation['command']['id']) is not operation):
            return False
        identity = self.control.identity() if identity is None else identity
        if self.closed or self.control.closed or not _same_identity(identity, operation['identity']):
            self._finish(operation, 'cancelled', 'controller_closed' if self.closed or self.control.closed else 'identity_changed', now)
            return False
        entry = self.control.gateway.requests.get(operation['command']['id'])
        if entry is not None and entry.get('receipt', {}).get('status') in TERMINAL:
            self._remove(operation)
            return False
        deadline = entry.get('deadline', operation['deadline']) if entry else operation['deadline']
        if now >= deadline:
            self._finish(operation, 'failed', 'command_timeout', now)
            return False
        return True

    def update(self, now):
        operations = list(self.watchers.values()) + ([self.gun_pending] if self.gun_pending is not None else [])
        if not operations:
            return
        identity = self.control.identity()
        for operation in operations:
            if not self._current(operation, now, identity):
                continue
            if operation is self.gun_pending:
                if operation['phase'] == 'submitting':
                    continue
                outcome = self._gun_outcome(operation)
            else:
                observation = self._observe(operation['command']['args'], now)
                self.last_observation = observation
                outcome = (dict(reason='condition_observed', result=observation) if observation['matched'] else
                           dict(status='failed', reason=observation['reason'], result=observation)
                           if observation.get('impossible') else None)
            if outcome is not None:
                self._finish(operation, outcome.get('status', 'completed'), outcome['reason'], now, outcome.get('result'))

    def cancel(self, command, reason):
        if command.get('action') not in ACTIONS:
            return False
        operation = self.watchers.get(command.get('id'))
        if self.gun_pending is not None and self.gun_pending['command'].get('id') == command.get('id'):
            operation = self.gun_pending
        if operation is not None:
            self._finish(operation, 'cancelled', reason, self.control.owner._clock())
        return True

    def stop(self, reason, now):
        if self.gun_pending is not None:
            self._finish(self.gun_pending, 'cancelled', reason, now)
        if reason == 'battle_exit' or self.control.closed:
            self.closed = True
            for operation in list(self.watchers.values()):
                self._finish(operation, 'cancelled', reason, now)
        elif self.watchers:
            identity = self.control.identity()
            for operation in list(self.watchers.values()):
                if not _same_identity(identity, operation['identity']):
                    self._finish(operation, 'cancelled', 'identity_changed', now)

    def close(self, now=None):
        self.stop('battle_exit', self.control.owner._clock() if now is None else now)
