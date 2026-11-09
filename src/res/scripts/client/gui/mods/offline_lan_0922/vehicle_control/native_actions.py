"""Correlated foreground consumable and Siege-setting transactions.

Only the existing native setters enqueue work. Equipment completion observes
the exact canonical intent result; Siege completion observes the submitted
input frontier and an actually presented stable mode. Cancelling observation
never refunds a consumable or reverses an already submitted mode transition.
"""
from __future__ import division

from ..equipment_mechanics import ACTIVATION_CREW_NAMES, ACTIVATION_DEVICE_NAMES
from .. import siege_mechanics
from .commands import INTEGER_TYPES, STRING_TYPES, TERMINAL
from .test_actions import _same_identity


ACTIONS = frozenset(('use_equipment', 'set_siege'))
RELEASE_STAGE = 'native_siege_release'
MAX_SEQUENCE = 2147483647
MAX_EQUIPMENT = 3


def _integer(value, minimum=0, maximum=MAX_SEQUENCE):
    return (isinstance(value, INTEGER_TYPES) and not isinstance(value, bool) and
            minimum <= value <= maximum)


def _same_value(left, right):
    return _same_identity(dict(round_id=left), dict(round_id=right))


def _error_detail(error):
    # Python 2 str(Exception(unicode)) may itself fail while releasing an
    # owned native request. repr keeps Unicode diagnostics escaped/bounded.
    try:
        return repr(error)[:160]
    except Exception:
        return 'native_error_detail_unavailable'


class NativeActions(object):
    def __init__(self, control):
        self.control = control
        self.equipment_pending = None
        self.siege_pending = None
        self.last_equipment = None
        self.last_siege = None
        self.closed = False
        self.generation = 0

    @property
    def busy(self):
        return self.equipment_pending is not None or self.siege_pending is not None

    def _entity(self):
        owner = self.control.owner
        server = getattr(owner, '_server', None)
        resolve = getattr(owner, '_server_entity', None)
        if server is None or not callable(resolve) or not hasattr(server, 'vehicle_id'):
            return None
        try:
            return resolve(server.vehicle_id)
        except (AttributeError, TypeError, ValueError, RuntimeError, OverflowError):
            return None

    def _local_row(self):
        snapshot = getattr(self.control.owner, '_last_snapshot', None)
        identity = self.control.identity()
        if (not isinstance(snapshot, dict) or identity.get('round_id') is None or
                not _same_value(snapshot.get('round_id'), identity['round_id'])):
            return None
        rows = snapshot.get('players')
        if not isinstance(rows, (list, tuple)):
            return None
        matches = [row for row in rows if isinstance(row, dict) and
                   _same_value(row.get('id'), identity.get('player_id'))]
        return matches[0] if len(matches) == 1 else None

    def _equipment_ledger(self):
        owner = self.control.owner
        row = self._local_row()
        if row is None:
            return None
        result = row.get('equipment_intent_result')
        sequence, revision = row.get('equipment_intent_seq'), row.get('equipment_revision')
        states = getattr(owner, '_equipment_state', None)
        if (not _integer(sequence) or not _integer(revision) or
                not _integer(getattr(owner, '_equipment_revision', None)) or
                revision != owner._equipment_revision or
                not isinstance(states, (list, tuple)) or len(states) > MAX_EQUIPMENT or
                not isinstance(result, dict) or
                not _integer(result.get('intent_seq')) or result['intent_seq'] != sequence or
                not isinstance(result.get('accepted'), bool) or
                not isinstance(result.get('reason'), STRING_TYPES) or len(result['reason']) > 64):
            return None
        return dict(revision=revision, intent_seq=sequence, result=dict(result))

    def _target_index(self, name, kind, entity):
        if name not in (ACTIVATION_DEVICE_NAMES if kind == 'repairkit' else ACTIVATION_CREW_NAMES):
            return None
        owner = self.control.owner
        try:
            index = owner._critical_extra_index(entity.typeDescriptor, name)
            # The reviewed activation code is a signed 31-bit wire integer.
            if not _integer(index, 1, 32767):
                return None
            actual = owner._critical_name_from_extra_index(entity.typeDescriptor, index)
            if kind == 'medkit' and isinstance(actual, STRING_TYPES) and actual.endswith('Health'):
                actual = actual[:-6]
            return index if actual == name else None
        except (AttributeError, TypeError, ValueError, RuntimeError, OverflowError):
            return None

    def _equipment_snapshot(self):
        owner = self.control.owner
        ledger = self._equipment_ledger()
        result = dict(available=ledger is not None, revision=None, intent_seq=None, stock=[])
        if ledger is not None:
            result.update(revision=ledger['revision'], intent_seq=ledger['intent_seq'])
        states = getattr(owner, '_equipment_state', None)
        if not isinstance(states, (list, tuple)) or not states:
            return result
        clock = getattr(owner, '_clock', None)
        entity, now = self._entity(), clock() if callable(clock) else None
        for item in states[:MAX_EQUIPMENT]:
            contract = getattr(item, 'contract', {})
            equipment_id, compact = contract.get('id'), contract.get('compactDescr')
            if not _integer(equipment_id, 0, 65535) or not _integer(compact, 1):
                continue
            kind, all_targets = contract.get('kind'), bool(contract.get('repairAll', False))
            names = (ACTIVATION_DEVICE_NAMES if kind == 'repairkit' else
                     ACTIVATION_CREW_NAMES if kind == 'medkit' else ())
            targets = ([name for name in sorted(names) if self._target_index(name, kind, entity) is not None]
                       if not all_targets else [])
            try:
                ready = now is not None and bool(item.ready(now))
            except (AttributeError, TypeError, ValueError, RuntimeError, OverflowError):
                ready = False
            result['stock'].append(dict(equipment_id=equipment_id, compact_descr=compact,
                kind=kind, repair_all=all_targets, ready=ready,
                active=bool(getattr(item, 'active', False)),
                uses_left=getattr(item, 'uses_left', None), targets=targets))
        return result

    def _siege_snapshot(self):
        entity, row = self._entity(), self._local_row()
        result = dict(available=False, enabled=None, state=None, time_left_ms=None,
                      input_seq=None, presented=False)
        if not bool(getattr(getattr(entity, 'typeDescriptor', None), 'hasSiegeMode', False)):
            return result
        if row is None:
            return result
        state, remaining, sequence = (row.get('siege_state'), row.get('siege_time_left_ms'),
                                      row.get('input_seq'))
        if (not _integer(state, 0, 3) or not _integer(remaining) or not _integer(sequence) or
                (state in (siege_mechanics.DISABLED, siege_mechanics.ENABLED)) != (remaining == 0)):
            return result
        record = getattr(self.control.owner, '_records', {}).get(
            'player:%s' % self.control.identity().get('player_id'), {})
        presented = (record.get('presented_siege_state') == state and
                     _integer(record.get('presented_siege_state'), 0, 3) and
                     _integer(getattr(entity, 'siegeState', None), 0, 3) and entity.siegeState == state and
                     getattr(self.control.owner, '_local_siege_applying', None) is None)
        result.update(available=True, enabled=state == siege_mechanics.ENABLED,
                      state=state, time_left_ms=remaining, input_seq=sequence, presented=presented)
        return result

    def snapshot(self):
        equipment, siege = self._equipment_snapshot(), self._siege_snapshot()
        operation = self.equipment_pending
        equipment['pending'] = (dict(id=operation['command'].get('id'),
            equipment_id=operation['equipment_id'], target=operation.get('target'),
            active=operation.get('active'), intent_seq=operation.get('intent_seq'), phase=operation['phase'])
            if operation is not None else None)
        equipment['last'] = dict(self.last_equipment) if self.last_equipment is not None else None
        operation = self.siege_pending
        siege['pending'] = (dict(id=operation['command'].get('id'), enabled=operation['enabled'],
            request_seq=operation.get('request_seq'), phase=operation['phase']) if operation is not None else None)
        siege['last'] = dict(self.last_siege) if self.last_siege is not None else None
        return dict(equipment=equipment, siege=siege)

    def _equipment_selection(self, command):
        owner, args = self.control.owner, command['args']
        equipment_id = args.get('equipment_id')
        if not _integer(equipment_id, 0, 65535):
            return None, 'invalid_equipment_id'
        ledger = self._equipment_ledger()
        if ledger is None:
            return None, 'equipment_state_unavailable'
        local_sequence = getattr(owner.client, '_equipment_intent_seq', None)
        if not _integer(local_sequence) or local_sequence != ledger['intent_seq']:
            return None, 'equipment_native_busy'
        mounted = [item for item in owner._equipment_state if item.contract.get('id') == equipment_id]
        if len(mounted) != 1:
            return None, 'equipment_not_mounted' if not mounted else 'ambiguous_mounted_equipment'
        item, entity = mounted[0], self._entity()
        kind = item.contract.get('kind')
        if kind not in ('repairkit', 'medkit', 'extinguisher', 'rpm_limiter'):
            return None, 'equipment_not_activatable'
        if kind == 'extinguisher' and item.contract.get('autoactivate', False):
            return None, 'automatic_equipment_only'
        if kind != 'rpm_limiter' and 'active' in args:
            return None, 'unexpected_equipment_active'
        all_targets = bool(item.contract.get('repairAll', False))
        index, needed = 1, True
        if kind in ('repairkit', 'medkit') and not all_targets:
            if 'target' not in args:
                return None, 'equipment_target_required'
            index = self._target_index(args['target'], kind, entity)
            if index is None:
                return None, 'equipment_target_unavailable'
        elif 'target' in args:
            return None, 'unexpected_equipment_target'
        if kind == 'rpm_limiter':
            if not isinstance(args.get('active'), bool):
                return None, 'equipment_active_required'
            index, needed = int(args['active']), bool(item.active) != args['active']
        if needed and not item.ready(owner._clock()):
            return None, 'equipment_not_ready'
        if not callable(getattr(owner, '_activate_equipment_intent', None)):
            return None, 'equipment_settings_unavailable'
        compact = item.contract.get('compactDescr')
        if not _integer(compact, 1):
            return None, 'equipment_state_unavailable'
        return dict(entity=entity, equipment_id=equipment_id, compact_descr=compact,
                    target=args.get('target'), active=args.get('active'), needed=needed,
                    activation_code=equipment_id | (index << 16), baseline_seq=ledger['intent_seq'],
                    intent_seq=None), None

    def _siege_selection(self, command):
        owner, enabled = self.control.owner, command['args'].get('enabled')
        if not isinstance(enabled, bool):
            return None, 'invalid_enabled'
        entity = self._entity()
        if not bool(getattr(getattr(entity, 'typeDescriptor', None), 'hasSiegeMode', False)):
            return None, 'siege_not_supported'
        if bool(getattr(entity, 'is_engine_dead', False)):
            return None, 'engine_destroyed'
        observation = self._siege_snapshot()
        if (getattr(owner, '_local_siege_braking', None) is not None or
                getattr(owner, '_local_siege_pending', None) is not None or
                getattr(entity, 'siegeState', None) in
                (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF)):
            return None, 'siege_native_busy'
        if not observation['available'] or not observation['presented']:
            return None, 'siege_state_unavailable'
        if observation['state'] in (siege_mechanics.SWITCHING_ON, siege_mechanics.SWITCHING_OFF):
            return None, 'siege_native_busy'
        if (not callable(getattr(owner, '_request_player_control_siege', None)) or
                not callable(getattr(owner, '_cancel_player_control_siege', None))):
            return None, 'siege_settings_unavailable'
        return dict(entity=entity, enabled=enabled, needed=observation['enabled'] != enabled,
                    baseline_seq=observation['input_seq'], request_seq=None), None

    def _admission_reason(self, command, operation=None):
        action = command['action']
        if self.closed or self.control.closed:
            return 'controller_closed'
        if not self.control.live():
            return 'battle_not_live'
        if action == 'use_equipment':
            if self.equipment_pending is not None and self.equipment_pending is not operation:
                return 'equipment_operation_busy'
            if self.control.active and 'consumables' in self.control.features:
                return 'automatic_consumables_active'
        else:
            if self.siege_pending is not None and self.siege_pending is not operation:
                return 'siege_operation_busy'
            if self.control.override is not None:
                return 'movement_busy'
            if self.control.active and 'drive' in self.control.features:
                return 'automatic_drive_active'
        return None

    def preflight(self, command):
        action = command['action']
        if action not in ACTIONS:
            return None
        owner, generation = self.control.owner, self.generation
        identity, started = dict(self.control.identity()), owner._clock()
        reason = self._admission_reason(command)
        if reason:
            return reason
        selection, reason = (self._equipment_selection(command) if action == 'use_equipment'
                             else self._siege_selection(command))
        # Descriptor access and native entity lookup can synchronously Stop,
        # replace the round or consume the admission budget before execution.
        now = owner._clock()
        if self.control.owner is not owner or not _same_identity(identity, self.control.identity()):
            return 'identity_changed'
        if self.closed or self.control.closed:
            return 'controller_closed'
        if self.generation != generation:
            return 'controller_stopped'
        if now >= started + command.get('timeout_seconds', 30.):
            return 'command_timeout'
        if reason:
            return reason
        if selection['needed'] and command.get('id') is None:
            return 'command_id_required'
        # This internal, JSON-only guard also fences reentry while the gateway
        # publishes acceptance, before execute has installed its own slot.
        server = getattr(owner, '_server', None)
        command['_native_guard'] = dict(generation=generation, owner_id=id(owner), identity=identity,
            server_id=id(server), vehicle_id=getattr(server, 'vehicle_id', None), entity_id=id(selection['entity']))
        return None

    def _operation(self, command, now):
        owner = self.control.owner
        guard = command.get('_native_guard') or {}
        generation = guard.get('generation', self.generation)
        server = getattr(owner, '_server', None)
        entry = self.control.gateway.requests.get(command.get('id'))
        # The gateway captured this identity before preflight/acceptance; do
        # not silently rebind an admitted request to a round entered meanwhile.
        identity = (dict((key, entry['receipt'].get(key)) for key in
                    ('session_id', 'round_id', 'player_id')) if entry is not None
                    else dict(guard.get('identity') or self.control.identity()))
        return dict(command=dict(command, args=dict(command['args'])),
            owner=owner, owner_id=guard.get('owner_id', id(owner)), generation=generation, identity=identity,
            server=server, server_id=guard.get('server_id', id(server)),
            vehicle_id=guard.get('vehicle_id', getattr(server, 'vehicle_id', None)),
            resolver=getattr(owner, '_server_entity', None), admitted_entity_id=guard.get('entity_id'),
            deadline=now + command.get('timeout_seconds', 30.), phase='preparing',
            needed=False, entity=None, equipment_id=command['args'].get('equipment_id'),
            target=command['args'].get('target'), active=command['args'].get('active'),
            enabled=command['args'].get('enabled'), intent_seq=None, request_seq=None)

    def execute(self, command, now):
        action = command['action']
        if action not in ACTIONS:
            raise ValueError('unknown_native_action')
        if action == 'use_equipment' and self.equipment_pending is not None:
            return dict(status='failed', reason='equipment_operation_busy')
        if action == 'set_siege' and self.siege_pending is not None:
            return dict(status='failed', reason='siege_operation_busy')
        operation = self._operation(command, now)
        # Publish a complete minimum operation before any native observation.
        # Stop/cancel and a reentrant heartbeat can now see its real ownership.
        if action == 'use_equipment':
            self.equipment_pending = operation
        else:
            self.siege_pending = operation
            operation['on_submitted'] = lambda sequence, enabled, reason=None: self._siege_submitted(
                operation, sequence, enabled, reason)
        owner = operation['owner']
        if not self._current(operation, owner._clock()):
            return None
        selection, reason = (self._equipment_selection(command) if action == 'use_equipment'
                             else self._siege_selection(command))
        now = owner._clock()
        if not self._current(operation, now):
            return None
        current_entity = self._entity() if reason is None else None
        if reason is None:
            reason = self._admission_reason(command, operation)
        now = owner._clock()
        if not self._current(operation, now):
            return None
        if reason is None and (current_entity is not selection['entity'] or
                operation['admitted_entity_id'] is not None and id(current_entity) != operation['admitted_entity_id']):
            reason = 'vehicle_changed'
        if reason is None and selection['needed'] and command.get('id') is None:
            reason = 'command_id_required'
        if reason:
            outcome = dict(status='failed', reason=reason)
            if command.get('id') is None:
                self._remove(operation)
                self._note(operation, 'failed', reason, now)
                return outcome
            self._finish(operation, 'failed', reason, now)
            return None
        operation.update(selection)
        operation['phase'] = 'submitting' if selection['needed'] else 'observing'
        outcome = None
        if selection['needed']:
            try:
                if action == 'use_equipment':
                    sequence = self.control.owner._activate_equipment_intent(operation['activation_code'])
                    if not _integer(sequence, 1) or sequence <= operation['baseline_seq']:
                        outcome = dict(status='failed', reason='equipment_submission_failed')
                    else:
                        operation['intent_seq'] = sequence
                elif not self.control.owner._request_player_control_siege(
                        operation['enabled'], operation['on_submitted']):
                    outcome = dict(status='failed', reason='siege_submission_failed')
            except Exception as error:
                outcome = dict(status='failed', reason='native_setting_error', result=dict(error=_error_detail(error)))
            now = self.control.owner._clock()
            if not self._current(operation, now):
                return None
            operation['phase'] = ('braking' if action == 'set_siege' and
                                  operation['request_seq'] is None else 'observing')
        if not selection['needed']:
            outcome = dict(reason='equipment_already_set' if action == 'use_equipment' else 'siege_already_set',
                           result=self._equipment_snapshot() if action == 'use_equipment' else self._siege_snapshot())
        elif outcome is None:
            outcome = self._outcome(operation)
        now = owner._clock()
        if not self._current(operation, now):
            return None
        if outcome is not None:
            if command.get('id') is not None:
                self._finish(operation, outcome.get('status', 'completed'), outcome['reason'], now, outcome.get('result'))
                return None
            self._remove(operation)
            self._note(operation, outcome.get('status', 'completed'), outcome['reason'], now)
            return outcome
        return None

    def _siege_submitted(self, operation, sequence, enabled, reason):
        now = self.control.owner._clock()
        if not self._current(operation, now):
            return
        if reason is not None:
            self._finish(operation, 'cancelled' if reason == 'siege_replaced' else 'failed',
                         reason[:64] if isinstance(reason, STRING_TYPES) else _error_detail(reason)[:64], now)
            return
        if (not isinstance(enabled, bool) or enabled != operation['enabled'] or
                not _integer(sequence, 1) or sequence <= operation['baseline_seq'] or
                operation['request_seq'] not in (None, sequence)):
            self._finish(operation, 'failed', 'siege_request_sequence_invalid', now)
            return
        operation['request_seq'] = sequence
        if operation['phase'] != 'submitting':
            operation['phase'] = 'observing'
            self.update(now)

    def _outcome(self, operation):
        if not self.control.live():
            return dict(status='failed', reason='battle_not_live')
        if self._entity() is not operation['entity']:
            return dict(status='failed', reason='vehicle_changed')
        if operation is self.equipment_pending:
            if self.control.active and 'consumables' in self.control.features:
                return dict(status='cancelled', reason='automatic_consumables_active')
            ledger = self._equipment_ledger()
            if ledger is None:
                return None
            mounted = [item for item in self.control.owner._equipment_state
                       if item.contract.get('id') == operation['equipment_id'] and
                       item.contract.get('compactDescr') == operation['compact_descr']]
            if len(mounted) != 1:
                return dict(status='failed', reason='equipment_changed')
            sequence = operation['intent_seq']
            if sequence is None or ledger['intent_seq'] < sequence:
                return None
            result = dict(equipment_id=operation['equipment_id'], intent_seq=sequence,
                          revision=ledger['revision'], canonical_result=ledger['result'])
            if ledger['intent_seq'] > sequence:
                return dict(status='failed', reason='equipment_receipt_superseded', result=result)
            if ledger['result']['accepted']:
                return dict(reason='equipment_applied', result=result)
            return dict(status='failed', reason=ledger['result']['reason'] or 'equipment_rejected', result=result)
        if self.control.override is not None or self.control.active and 'drive' in self.control.features:
            return dict(status='cancelled', reason='movement_replaced')
        observation = self._siege_snapshot()
        sequence = operation['request_seq']
        if (sequence is None or not observation['available'] or observation['input_seq'] < sequence or
                observation['time_left_ms'] != 0 or not observation['presented']):
            return None
        observation['request_seq'] = sequence
        if observation['enabled'] == operation['enabled']:
            return dict(reason='siege_stable', result=observation)
        return dict(status='failed', reason='siege_rejected', result=observation)

    def _remove(self, operation):
        if self.equipment_pending is operation:
            self.equipment_pending = None
        if self.siege_pending is operation:
            if not operation['needed']:
                self.siege_pending = None
                return
            operation['phase'] = 'releasing'
            try:
                self.release_siege()
            except Exception as error:
                if not any(stage == RELEASE_STAGE for stage, unused in self.control.release_pending):
                    self.control.release_pending.append((RELEASE_STAGE, self.release_siege))
                self.control.next_release = max(getattr(self.control, 'next_release', 0.),
                                                self.control.owner._clock() + 1.)
                self.control.record('native_action_cleanup_failed', reason=_error_detail(error))

    def release_siege(self):
        """Retry only our cancellation token; never erase a submitted mode."""
        operation = self.siege_pending
        if operation is None:
            return
        operation['phase'] = 'releasing'
        self.control.owner._cancel_player_control_siege(operation['on_submitted'])
        if self.siege_pending is operation:
            self.siege_pending = None
            self.control.release_pending[:] = [item for item in self.control.release_pending
                                               if item[0] != RELEASE_STAGE]

    def _note(self, operation, status, reason, now):
        result = dict(id=operation['command'].get('id'), status=status, reason=reason, time=now)
        if operation['command']['action'] == 'use_equipment':
            result.update(equipment_id=operation['equipment_id'], intent_seq=operation.get('intent_seq'))
            self.last_equipment = result
        else:
            result.update(enabled=operation['enabled'], request_seq=operation.get('request_seq'))
            self.last_siege = result

    def _finish(self, operation, status, reason, now, result=None):
        if operation is not self.equipment_pending and operation is not self.siege_pending:
            return False
        entry = self.control.gateway.requests.get(operation['command'].get('id'))
        receipt = entry.get('receipt', {}) if entry else {}
        if receipt.get('status') in TERMINAL:
            # Gateway timeout finishes the journal before invoking cancel.
            # Cleanup must not relabel that immutable failure as cancellation.
            status, reason, now = receipt['status'], receipt['reason'], receipt.get('time', now)
        self._remove(operation)
        self._note(operation, status, reason, now)
        self.control.gateway.finish(operation['command']['id'], status, reason, now, result)

    def _current(self, operation, now):
        if (operation['phase'] == 'releasing' or
                operation is not self.equipment_pending and operation is not self.siege_pending):
            return False
        if (self.closed or self.control.closed or self.control.owner is not operation['owner'] or
                id(self.control.owner) != operation['owner_id'] or
                not _same_identity(self.control.identity(), operation['identity'])):
            self._finish(operation, 'cancelled', 'controller_closed' if self.closed or self.control.closed
                         else 'identity_changed', now)
            return False
        if self.generation != operation['generation']:
            self._finish(operation, 'cancelled', 'controller_stopped', now)
            return False
        owner = operation['owner']
        server = getattr(owner, '_server', None)
        if (server is not operation['server'] or id(server) != operation['server_id'] or
                not _same_value(getattr(server, 'vehicle_id', None), operation['vehicle_id']) or
                getattr(owner, '_server_entity', None) != operation['resolver']):
            self._finish(operation, 'failed', 'vehicle_changed', now)
            return False
        entry = self.control.gateway.requests.get(operation['command'].get('id'))
        if entry is not None and entry.get('receipt', {}).get('status') in TERMINAL:
            self._remove(operation)
            receipt = entry['receipt']
            self._note(operation, receipt['status'], receipt['reason'], receipt.get('time', now))
            return False
        deadline = entry.get('deadline', operation['deadline']) if entry else operation['deadline']
        if now >= deadline:
            self._finish(operation, 'failed', 'command_timeout', now)
            return False
        return True

    def update(self, now):
        for operation in (self.equipment_pending, self.siege_pending):
            if (operation is None or not self._current(operation, now) or
                    operation['phase'] in ('preparing', 'submitting')):
                continue
            outcome = self._outcome(operation)
            observed_at = operation['owner']._clock()
            if not self._current(operation, observed_at):
                continue
            if outcome is not None:
                self._finish(operation, outcome.get('status', 'completed'), outcome['reason'], observed_at, outcome.get('result'))

    def cancel(self, command, reason):
        if command.get('action') not in ACTIONS:
            return False
        for operation in (self.equipment_pending, self.siege_pending):
            if (operation is not None and operation['phase'] != 'releasing' and
                    operation['command'].get('id') == command.get('id')):
                self._finish(operation, 'cancelled', reason, self.control.owner._clock())
        return True

    def stop(self, reason, now):
        self.generation += 1
        for operation in (self.equipment_pending, self.siege_pending):
            if operation is not None and operation['phase'] != 'releasing':
                self._finish(operation, 'cancelled', reason, now)
        if reason == 'battle_exit' or self.control.closed:
            self.closed = True

    def close(self, now=None):
        self.stop('battle_exit', self.control.owner._clock() if now is None else now)
