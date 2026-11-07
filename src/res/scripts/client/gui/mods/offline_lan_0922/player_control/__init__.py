# -*- coding: utf-8 -*-
"""Foreground ownership and command journal for the complete player copy.

Automatic navigation, targeting, avoidance and recovery execute in
full_runtime, whose behavior comes from the independent copied package. This
module only arbitrates input ownership, native command transactions, lifecycle
and observations; a test command uses the same live controller as the UI.
"""
from __future__ import print_function
import math
import os

_current = None


def native_message(text):
    from messenger import MessengerEntry
    from messenger import g_settings
    message = g_settings.htmlTemplates.format('battleErrorMessage', ctx={'error': text})
    MessengerEntry.g_instance.gui.addClientMessage(message, isCurrentPlayer=False)


def handle_key(is_down, key, mods=0):
    controller = _current
    if controller is None:
        return False
    import Keys
    if key != Keys.KEY_GRAVE:
        return False
    if not is_down:
        controller.key_down = False
        return True
    if controller.key_down:
        return True
    if mods or not controller.live() or not controller.input_available():
        return False
    controller.key_down = True
    controller.toggle()
    return True


class PlayerControl(object):
    def __init__(self, owner, features, notify=native_message, auto_start=False):
        from .commands import CommandGateway, JournalReader
        from .manual_aim import ManualAim
        from .native_actions import NativeActions
        from .settling import HaltObservation
        from .shot_receipts import ShotReceipts
        from .test_actions import TestActions

        self.owner = owner
        self.features = set(features) & set(('drive', 'fire', 'consumables'))
        self.notify = notify
        self.active = self.key_down = self.closed = self.halted = False
        self._auto_start_pending = bool(auto_start and self.features)
        self._starting = False
        self._release_depth = 0
        self.runtime = None
        self._runtime_binding = None
        self.navigation = None
        self.trigger_admission = None
        self.runtime_status = {}
        self.last_control_failure = None
        self.input_binding = None
        self.control_generation = 0
        self.trigger_sequence = 0
        self.trigger_context = None
        self.native_triggering = False
        # This is receipt lineage only. The battle's physical trigger clock
        # owns execution and is never cancelled by this controller.
        self.owned_burst = None
        self.shot_commits = self.automatic_commits = 0
        self.shot_receipts = ShotReceipts()
        self.last_fire_failure = None
        self.mission_command = self.drive_command = None
        self.fire_command = self.halt_command = None
        self.override = None
        self.target_engine = None
        self.aim_receipt = None
        self.last_order = {}
        self.drive_contact_receipt = None
        self.ammo_state = dict(state='unknown', empty=False, available=False)
        self.halt_observation = HaltObservation()
        self.release_pending = []
        self.next_release = 0.
        self.next_status = self.next_poll = 0.
        self.command_offset = 0
        self.command_reader = JournalReader()
        self.gateway = CommandGateway(self.identity, self.emit_result,
            self.execute_command, self.command_preflight, self.cancel_command)
        self.test_actions = TestActions(self)
        self.manual_aim = ManualAim(self)
        self.native_actions = NativeActions(self)
        self._nonlive_stopped = False

    @property
    def confirmed_facing(self):
        return (getattr(self.runtime, 'confirmed_facing', None)
                if self.runtime is not None else None)

    @property
    def capture_pivot_circle(self):
        return (getattr(self.runtime, 'capture_pivot_circle', None)
                if self.runtime is not None else None)

    def _native_binding(self):
        owner = self.owner
        server = getattr(owner, '_server', None)
        entity_id = getattr(server, 'vehicle_id', None)
        entity = owner._server_entity(entity_id) if entity_id is not None else None
        avatar = getattr(owner, '_avatar', None)
        return (getattr(owner, '_generation', None),
                owner._start_message.get('round_id'),
                getattr(owner.client, 'player_id', None), entity_id, id(entity),
                id(getattr(owner, '_gun_state', None)), id(avatar),
                id(getattr(avatar, 'gunRotator', None)))

    def _ensure_runtime(self):
        generation = self.control_generation
        binding = self._native_binding()
        previous = self.runtime
        if (previous is not None and
                (getattr(previous, 'closed', False) or
                 self._runtime_binding is not None and self._runtime_binding != binding)):
            # A private planner belongs to one native actor/weapon lifetime.
            # Closing its observers never terminates a battle-owned trigger.
            self._run_releases([('full_runtime_close', previous.close)], self.owner._clock())
            if (self.release_pending or self.closed or self.control_generation != generation or
                    self.runtime is not previous):
                raise RuntimeError('full_player_runtime_retirement_pending')
            self.runtime = None
            self._runtime_binding = None
            self.runtime_status = {}
        if self.runtime is None:
            from .full_runtime import FullPlayerRuntime
            runtime = FullPlayerRuntime(self.owner, controller=self)
            # Native attach may re-enter Stop. Install the identity first;
            # the start fence below must still reject that retired request.
            self.runtime = runtime
            self._runtime_binding = binding
            try:
                if runtime.attach() is False:
                    raise RuntimeError('full_player_runtime_attach_failed')
                if (self.closed or self.control_generation != generation or
                        self.runtime is not runtime or self._native_binding() != binding):
                    raise RuntimeError('full_player_runtime_attach_retired')
            except Exception:
                # A native attach can finish constructing resources after a
                # synchronous Stop. Its late objects still need exact cleanup.
                self._run_releases([('full_runtime_close', runtime.close)], self.owner._clock())
                if not self.release_pending and self.runtime is runtime:
                    self.runtime = None
                    self._runtime_binding = None
                raise
        elif self._runtime_binding is None:
            self._runtime_binding = binding
        return self.runtime

    def _runtime_event(self, name, *args):
        runtime = self.runtime
        if runtime is None:
            return None
        try:
            callback = getattr(runtime, name, None)
            if not callable(callback):
                raise RuntimeError('full_player_runtime_event_missing:' + name)
            return callback(*args)
        except Exception as error:
            # A receipt consumer cannot roll back a physical launch or hide
            # its terminal. Stop future controller decisions and expose the
            # failed consumer, while the weapon retains its committed group.
            self.last_control_failure = repr(error)[:160]
            self.record('runtime_event_failed', event=name,
                        reason=self.last_control_failure)
            self.stop('runtime_event_failed')
            return None

    def bot_observation(self, message, now):
        """Forward same-round team evidence without starting a controller."""
        runtime = self.runtime
        generation = self.control_generation
        round_id = self.owner._start_message.get('round_id')
        if (self.closed or runtime is None or getattr(runtime, 'closed', False) or
                not isinstance(message, dict) or round_id is None or
                message.get('round_id') != round_id or
                self._runtime_binding is None or
                self._native_binding() != self._runtime_binding):
            return False
        if (self.closed or self.runtime is not runtime or
                self.control_generation != generation):
            return False
        callback = getattr(runtime, 'observe_team_observation', None)
        if not callable(callback):
            self.record('team_observation_unavailable')
            return False
        try:
            return callback(message, now)
        except Exception as error:
            # A stale or malformed observation cannot revoke another native
            # command or create an implicit activation as a side effect.
            self.record('team_observation_rejected', reason=repr(error)[:160])
            return False

    def identity(self):
        return dict(session_id=os.environ.get('WOT_OFFLINE_TEST_CONTROL_SESSION'),
                    round_id=getattr(self.owner, '_start_message', {}).get('round_id'),
                    player_id=getattr(self.owner.client, 'player_id', None))

    def emit_result(self, row):
        from .commands import append_result
        path = os.environ.get('WOT_OFFLINE_TEST_CONTROL_RESULT_FILE')
        try:
            return append_result(path, row)
        except (IOError, OSError, TypeError, ValueError) as error:
            self.record('result_write_failed', reason=repr(error)[:160])
            return False

    def publish_status(self, now, force=False, reason=None):
        self.test_actions.update(now)
        self.native_actions.update(now)
        if not force and now < self.next_status:
            return
        self.next_status = now + 1.
        navigation = self.navigation
        mission = navigation.mission_status() if navigation is not None else None
        runtime = self.runtime
        if (mission is None and runtime is not None and
                self._runtime_binding is not None and self._native_binding() == self._runtime_binding):
            # Stop retires motion ownership, not the terminal observation.
            # Reading the old frame cache here would falsely publish a still
            # running mission after the real runtime already cancelled it.
            mission = runtime.navigation.mission_status()
        pose = None
        live = self.live()
        if live:
            position, yaw = self.owner.local_pose()
            pose = dict(position=tuple(position), yaw=yaw,
                        speed=self.owner._local_speed)
        burst = getattr(self.owner, '_local_player_burst', None)
        trigger = None
        if isinstance(burst, dict):
            context = burst.get('player_control') or {}
            trigger = dict(group=burst.get('group_seq'),
                count=burst.get('count'), committed=burst.get('committed'),
                controller_detached=bool(context.get('controller_detached')),
                stop_requested=context.get('stop_requested'))
        row = dict(self.identity(), type='status', time=now, live=live,
            reason=reason, active=self.active, halted=self.halted,
            features=sorted(self.features), mission=mission, ammo=self.ammo_state,
            pose=pose, aim=self.aim_receipt, last_command=self.gateway.last,
            halt=self.halt_observation.receipt if self.halted else None,
            testing=self.test_actions.snapshot(),
            manual_aim=self.manual_aim.snapshot(),
            native_actions=self.native_actions.snapshot(),
            shot_results=self.shot_receipts.snapshot(),
            physical_trigger=trigger,
            control_failure=self.last_control_failure,
            implementation='full_independent_behavior_copy',
            release_pending=[stage for stage, unused in self.release_pending],
            navigation=self.runtime_status.get('navigation') if self.active else None)
        import json
        row['shot_snapshot_omitted'] = 0
        while row['shot_results']:
            try:
                size = len(json.dumps(row, ensure_ascii=True, allow_nan=False,
                    separators=(',', ':')).encode('ascii'))
            except (TypeError, ValueError):
                break
            if size <= 15000:
                break
            row['shot_results'].pop(0)
            row['shot_snapshot_omitted'] += 1
        self.emit_result(row)

    def owns_automatic_drive(self):
        return self.active and 'drive' in self.features

    def owns_drive(self):
        return self.halted or self.override is not None or self.owns_automatic_drive()

    def bind_input(self):
        """Wrap the exact #1513 event seam, including strategic camera mode."""
        handler = getattr(self.owner._avatar, 'inputHandler', None)
        if self.input_binding is not None and self.input_binding[0] is not handler:
            previous, original, owned, wrapper = self.input_binding
            if previous.__dict__.get('handleKeyEvent') is wrapper:
                if owned:
                    previous.handleKeyEvent = original
                else:
                    del previous.handleKeyEvent
            self.input_binding = None
        if handler is None or self.input_binding is not None:
            return
        original = handler.handleKeyEvent
        owned = 'handleKeyEvent' in handler.__dict__
        def key_event(event):
            import game
            down, key, mods, repeat = game.convertKeyEvent(event)
            import Keys
            if (self.active and 'fire' in self.features and self.input_available() and
                    key in (Keys.KEY_LEFTMOUSE, Keys.KEY_RIGHTMOUSE)):
                # Consume before native shoot()/autoAim() start their own
                # handshake or cancel the lock. Camera movement is untouched.
                return True
            if not repeat and handle_key(down, key, mods):
                return True
            return original(event)
        handler.handleKeyEvent = key_event
        self.input_binding = handler, original, owned, key_event

    def record(self, stage, **fields):
        from ..native_input_diagnostics import write_json_record
        fields.update(stage=stage, player=self.owner.client.player_id,
                      round=self.owner._start_message.get('round_id'), active=self.active)
        write_json_record('PLAYER CONTROL', fields)

    def input_available(self):
        from messenger import MessengerEntry
        handler = getattr(self.owner._avatar, 'inputHandler', None)
        return bool(handler is not None and handler.isStarted and not handler.isDetached and
                    not MessengerEntry.g_instance.gui.isFocused())

    def live(self):
        owner = self.owner
        ready = bool(not self.closed and owner.state == 'running' and owner._battle_live and
                    owner._battle_result is None and owner._server is not None and
                    owner._sender is not None and not owner._worker_mode and not owner._replay_mode)
        entity = owner._server_entity(owner._server.vehicle_id) if ready else None
        return bool(ready and entity is not None and entity.isAlive())

    def toggle(self, navigation=None):
        self._auto_start_pending = False
        # Native setters may synchronously Stop and try starting again before
        # their delayed source/mode write has returned. That older stack still
        # owns its cleanup; a new owner cannot be admitted inside it.
        if self._starting or self._release_depth:
            return False
        self._starting = True
        try:
            return self._toggle(navigation)
        finally:
            self._starting = False

    def _toggle(self, navigation=None):
        if self.active:
            self.stop('manual')
            return False
        if navigation is not None:
            # Old callers may not inject a second, reduced behavior owner.
            raise ValueError('navigation_is_owned_by_full_player_runtime')
        generation, identity = self.control_generation, self.identity()
        if (not self.live() or self.release_pending or not self.features or
                self.test_actions.gun_pending and 'fire' in self.features or
                self.manual_aim.held and 'fire' in self.features or
                self.native_actions.equipment_pending and 'consumables' in self.features or
                self.native_actions.siege_pending and self.features & set(('drive', 'fire'))):
            return False
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        gun = getattr(owner, '_gun_state', None)
        avatar = getattr(owner, '_avatar', None)
        rotator = getattr(avatar, 'gunRotator', None)
        if (entity is None or not entity.isAlive() or
                self.control_generation != generation or self.identity() != identity):
            return False
        if self.override is not None or self.halted:
            if not self.stop('manual_takeover', preserve_explicit=True):
                return False
            generation = self.control_generation
        features = set(self.features)
        try:
            runtime = self._ensure_runtime()
        except Exception as error:
            self.last_control_failure = repr(error)[:160]
            self.record('start_failed', reason=self.last_control_failure)
            return False
        if (self.control_generation != generation or self.identity() != identity or
                not self.live() or self.release_pending or self.features != features):
            return False
        self.control_generation += 1
        generation = self.control_generation
        self.active = True
        self.last_fire_failure = self.last_control_failure = None

        def current():
            return bool(self.active and not self.closed and
                self.control_generation == generation and self.identity() == identity and
                self.runtime is runtime and self.features == features and
                owner._server is not None and
                owner._server_entity(owner._server.vehicle_id) is entity and
                getattr(owner, '_gun_state', None) is gun and
                getattr(owner, '_avatar', None) is avatar and
                getattr(avatar, 'gunRotator', None) is rotator and self.live())

        try:
            if runtime.start(features) is False or not current():
                raise RuntimeError('full_player_runtime_start_retired')
            self.navigation = runtime.navigation
            self.record('enabled', features=sorted(features),
                        implementation='full_independent_behavior_copy')
            if not current():
                raise RuntimeError('full_player_runtime_start_retired')
            self.notify(u'玩家自动控制已开启。')
            if not current():
                raise RuntimeError('full_player_runtime_start_retired')
            return True
        except Exception as error:
            self.last_control_failure = repr(error)[:160]
            if self.active and self.control_generation == generation:
                self.stop('automatic_start_failed', preserve_explicit=True)
            elif not any(stage == 'full_runtime_release'
                         for stage, unused in self.release_pending):
                self._run_releases([('full_runtime_release',
                    lambda: runtime.stop('automatic_start_retired'))], owner._clock())
            self.record('start_failed', reason=self.last_control_failure)
            return False

    def _command_trigger_context(self, command_id):
        if command_id is None:
            return None
        contexts = [self.trigger_context]
        for burst in (self.owned_burst, getattr(self.owner, '_local_player_burst', None)):
            if isinstance(burst, dict):
                contexts.append(burst.get('player_control'))
        pending = getattr(self.owner, '_local_fire_intent', None)
        if isinstance(pending, dict):
            contexts.append(pending.get('player_control'))
        for context in contexts:
            if isinstance(context, dict) and context.get('command') == command_id:
                return context
        return None

    @staticmethod
    def _trigger_irrevocable(context):
        return bool(context and (context.get('projectiles') or
                                 context.get('submission_in_progress')))

    def stop(self, reason='manual', preserve_explicit=False):
        if reason != 'battle_not_live':
            self._auto_start_pending = False
        owner = self.owner
        now = owner._clock()
        changed = bool(self.active or self.override is not None or self.halted)
        drive_owned = self.owns_drive()
        for command_id in (self.mission_command, self.drive_command, self.halt_command):
            if command_id is not None:
                self.gateway.finish(command_id, 'cancelled', reason, now)
        self.mission_command = self.drive_command = self.halt_command = None
        self.active = False
        self.control_generation += 1
        self.override = None
        self.halted = False
        context = self._command_trigger_context(self.fire_command)
        if preserve_explicit:
            # Movement turnover is independent of a separately admitted
            # explicit trigger, including its uncommitted first launch.
            if context is not None:
                context['generation'] = self.control_generation
        elif self._trigger_irrevocable(context):
            # Stop cannot retract an accepted trigger. Keep its command
            # accepted until every physical shell has committed or a real
            # physical failure supplies its terminal outcome.
            context['controller_detached'] = True
            context['stop_requested'] = reason
        else:
            if self.fire_command is not None:
                self.gateway.finish(self.fire_command, 'cancelled', reason, now)
            self.fire_command = None
        automatic_context = self.trigger_context
        if isinstance(automatic_context, dict) and automatic_context.get('automatic'):
            automatic_context['controller_detached'] = True
            automatic_context['stop_requested'] = reason
        burst = getattr(owner, '_local_player_burst', None)
        if isinstance(burst, dict) and isinstance(burst.get('player_control'), dict):
            burst['player_control']['controller_detached'] = True
            burst['player_control']['stop_requested'] = reason

        if not preserve_explicit:
            changed = changed or self.manual_aim.held or self.native_actions.busy
            self.test_actions.stop(reason, now)
            self.native_actions.stop(reason, now)
        from .settling import HaltObservation
        self.halt_observation = HaltObservation()
        self.target_engine = self.aim_receipt = None
        self.last_order = {}
        self.drive_contact_receipt = None
        callbacks = list(self.release_pending)
        self.release_pending = []
        if not preserve_explicit:
            from .manual_aim import RELEASE_STAGE
            from .native_actions import RELEASE_STAGE as SIEGE_RELEASE_STAGE
            retained_stages = (RELEASE_STAGE, SIEGE_RELEASE_STAGE, 'full_runtime_release')
            self.release_pending = [(stage, callback) for stage, callback in callbacks
                                    if stage in retained_stages]
            callbacks = [(stage, callback) for stage, callback in callbacks
                         if stage not in retained_stages]
            if not any(stage == RELEASE_STAGE for stage, unused in self.release_pending):
                self.manual_aim.stop(reason, now)
        if owner._sender is not None and drive_owned:
            owner._sender.forward = owner._sender.turn = 0.
            owner._sender.handbrake = False
            callbacks.insert(0, ('input_release', owner._sender.send_current))
        runtime = self.runtime
        if runtime is not None:
            if not any(stage == 'full_runtime_release'
                       for stage, unused in callbacks + self.release_pending):
                callbacks.append(('full_runtime_release',
                                  lambda: runtime.stop(reason)))
        self.navigation = None
        if (self.trigger_admission is not None and
                not self._trigger_irrevocable(self.trigger_context)):
            self.trigger_admission.reset()
        self._run_releases(callbacks, now)
        if changed:
            self.record('disabled', reason=reason,
                pending_release=[stage for stage, unused in self.release_pending],
                physical_trigger_continues=bool(getattr(owner, '_local_player_burst', None)))
            if self.live() and not self.release_pending:
                self.notify(u'玩家自动控制已关闭，恢复手动操作。')
        return not self.release_pending

    def close(self):
        global _current
        if self.closed:
            return
        self.stop('battle_exit')
        if self.runtime is not None:
            self._run_releases([('full_runtime_close', self.runtime.close)], self.owner._clock())
        if self.input_binding is not None:
            handler, original, owned, wrapper = self.input_binding
            if handler.__dict__.get('handleKeyEvent') is wrapper:
                if owned:
                    handler.handleKeyEvent = original
                else:
                    del handler.handleKeyEvent
            self.input_binding = None
        self.closed = True
        self.publish_status(self.owner._clock(), force=True, reason='battle_exit')
        if _current is self:
            _current = None

    def _run_releases(self, callbacks, now):
        """Retry retired resources without cancelling the current brake owner."""
        previous_deadline = self.next_release if self.release_pending else None
        for stage, callback in callbacks:
            self._release_depth += 1
            try:
                result = callback()
                if stage == 'input_release' and result is False:
                    raise RuntimeError('input_release_not_submitted')
            except Exception as error:
                self.release_pending.append((stage, callback))
                self.record('release_failed', resource=stage, reason=repr(error)[:160])
            finally:
                self._release_depth -= 1
        # An unrelated successful cleanup must not postpone a retained aim
        # or setting cleanup forever during repeated non-live updates.
        self.next_release = (min(previous_deadline, now + 1.)
                             if self.release_pending and previous_deadline is not None
                             else now + 1.)

    def retry_releases(self, now):
        if self.release_pending and now >= self.next_release:
            callbacks, self.release_pending = self.release_pending, []
            self._run_releases(callbacks, now)

    def poll_commands(self, now):
        if now < self.next_poll:
            return
        self.next_poll = now + 0.15
        def reject(reason, offset):
            self.record('command_rejected', reason=reason, offset=offset)
            self.gateway.rejection({}, reason, now)
        self.command_reader.offset = self.command_offset
        self.command_reader.poll(os.environ.get('WOT_OFFLINE_TEST_CONTROL_FILE'),
            lambda request: self.gateway.submit(request, now), reject)
        self.command_offset = self.command_reader.offset
        self.gateway.tick(now)

    def command(self, command, now):
        """Local callers use the same validated actions without a transport."""
        from .commands import validate_action
        if not isinstance(command, dict):
            raise ValueError('player control command must be an object')
        action = command.get('action')
        if action == 'toggle':
            return self.toggle()
        args = command.get('args', dict((k, v) for k, v in command.items() if k != 'action'))
        args = validate_action(action, args)
        normalized = dict(id=None, action=action, args=args, replace=True, timeout_seconds=600.)
        if self.command_preflight(normalized):
            return False
        result = self.execute_command(normalized, now)
        return result is None or result.get('status', 'completed') == 'completed'

    def command_preflight(self, command):
        generation = self.control_generation
        reason = self._command_preflight(command)
        if reason is not None or command['action'] in (
                'status', 'stop', 'wait_state', 'assert_state', 'release_aim'):
            return reason
        if self.control_generation != generation:
            return 'control_changed'
        # Native liveness/target queries and receipt publication may re-enter
        # Stop before execute has installed an operation-specific owner.
        command['_control_generation'] = generation
        return None

    def _command_preflight(self, command):
        from .commands import MISSIONS
        action = command['action']
        if action in ('status', 'stop'):
            return None
        if action in ('wait_state', 'assert_state'):
            return self.test_actions.preflight(command)
        if action == 'release_aim':
            return self.manual_aim.preflight(command)
        if self.release_pending and action != 'halt':
            return 'release_pending'
        if not self.live():
            return 'battle_not_live'
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            return 'player_dead'
        if self.native_actions.siege_pending is not None and action in (
                'drive', 'fire', 'select_shell', 'reload', 'aim_target', 'aim_point'):
            return 'siege_operation_busy'
        if action == 'set_siege':
            if self.manual_aim.held:
                return 'aim_busy'
            if self.active and 'fire' in self.features:
                return 'automatic_fire_active'
            if (self.test_actions.gun_pending or self.fire_command is not None or
                    getattr(owner, '_local_fire_intent', None) is not None or
                    getattr(owner, '_local_player_burst', None) is not None):
                return 'gun_operation_busy'
        if action in ('start',) + tuple(MISSIONS):
            if self.manual_aim.held and 'fire' in self.features:
                return 'aim_busy'
            if self.native_actions.equipment_pending and 'consumables' in self.features:
                return 'equipment_operation_busy'
            if (self.native_actions.siege_pending and
                    self.features & set(('drive', 'fire'))):
                return 'siege_operation_busy'
        if (self.test_actions.gun_pending and
                (action in ('fire', 'aim_target', 'aim_point') or
                 (action == 'start' or action in MISSIONS) and
                 'fire' in self.features)):
            return 'gun_operation_busy'
        if action in ('aim_target', 'aim_point'):
            return self.manual_aim.preflight(command)
        if action in ('use_equipment', 'set_siege'):
            return self.native_actions.preflight(command)
        if action in ('select_shell', 'reload'):
            return self.test_actions.preflight(command)
        if action in MISSIONS and 'drive' not in self.features:
            return 'drive_disabled'
        if action == 'start' and not self.features:
            return 'no_enabled_features'
        if (action in MISSIONS or action == 'drive') and not command['replace']:
            if self.owns_drive() or self.mission_command is not None:
                return 'movement_busy'
        if action == 'fire':
            reason = self.manual_aim.fire_preflight()
            if reason is not None:
                return reason
            from .capabilities import ammunition_state
            ammo = ammunition_state(owner._gun_state)
            if not ammo['available']:
                return 'ammunition_unknown'
            if ammo['empty']:
                return 'empty_ammo'
            if (not ammo['can_fire'] or getattr(owner, '_local_fire_intent', None) is not None or
                    getattr(owner, '_local_player_burst', None) is not None):
                return 'gun_not_ready'
        return None

    def execute_command(self, command, now):
        from .commands import MISSIONS, same_identity
        if 'identity' in command and not same_identity(command['identity'], self.identity()):
            return dict(status='cancelled', reason='identity_changed')
        if command.get('_control_generation', self.control_generation) != self.control_generation:
            return dict(status='cancelled', reason='control_changed')
        action, args, command_id = command['action'], command['args'], command['id']
        self.record('command', command=command)
        if action in ('wait_state', 'assert_state', 'select_shell', 'reload'):
            return self.test_actions.execute(command, now)
        if action in ('aim_target', 'aim_point', 'release_aim'):
            return self.manual_aim.execute(command, now)
        if action in ('use_equipment', 'set_siege'):
            return self.native_actions.execute(command, now)
        if action == 'status':
            self.publish_status(now, force=True)
            return dict(reason='status_published')
        if action == 'stop':
            released = self.stop('command_stop')
            reason = 'manual_control' if released else 'release_pending'
            self.publish_status(now, force=True, reason=reason)
            return dict(status='completed' if released else 'failed', reason=reason)
        if action == 'halt':
            self.stop('command_halt', preserve_explicit=True)
            self.halted = True
            self.halt_command = command_id
            sender = self.owner._sender
            sender.forward = sender.turn = 0.
            sender.handbrake = True
            sender.send_current()
            self.publish_status(now, force=True)
            return None
        if action == 'start':
            if self.override is not None or self.halted:
                self.stop('command_start', preserve_explicit=True)
            enabled = self.active or self.toggle()
            return dict(status='completed' if enabled else 'failed',
                        reason='active' if enabled else 'start_failed',
                        result=dict(failure=self.last_control_failure) if not enabled else None)
        if action == 'drive':
            if not self.stop('replaced_by_drive', preserve_explicit=True):
                return dict(status='failed', reason='release_pending')
            self.override = (now + args['seconds'], args['forward'], args['turn'])
            self.drive_command = command_id
            return None
        if action == 'fire':
            self.fire_command = command_id
            accepted = self._issue_trigger({}, now, command_id=command_id, automatic=False)
            self.record('script_fire', accepted=bool(accepted))
            if not accepted:
                if self.fire_command == command_id:
                    self.fire_command = None
                return dict(status='failed', reason=self.last_fire_failure or 'trigger_rejected')
            return None
        if action in MISSIONS:
            generation, identity = self.control_generation, self.identity()
            runtime = self._ensure_runtime()
            payload = dict(args, command_id=command_id,
                timeout=command['timeout_seconds'], requested_at=now)
            reason = runtime.mission_preflight(action, payload)
            if (self.control_generation != generation or self.identity() != identity or
                    not self.live()):
                return dict(status='cancelled', reason='control_changed')
            if reason is not None:
                return dict(status='failed', reason=reason)
            if self.override is not None or self.halted:
                if not self.stop('replaced_by_mission', preserve_explicit=True):
                    return dict(status='failed', reason='release_pending')
            generation, identity = self.control_generation, self.identity()
            receipt = runtime.set_mission(action, payload)
            if (self.control_generation != generation or self.identity() != identity or
                    not self.live()):
                return dict(status='cancelled', reason='control_changed')
            if isinstance(receipt, dict) and receipt.get('status') in ('failed', 'rejected'):
                return dict(status='failed', reason=receipt.get('reason', 'mission_unavailable'),
                            result=receipt)
            if not self.active and not self.toggle():
                return dict(status='failed', reason='start_failed',
                            result=dict(failure=self.last_control_failure))
            previous = self.mission_command
            if previous is not None:
                self.gateway.finish(previous, 'cancelled', 'replaced', now)
            self.mission_command = command_id
            self.navigation = runtime.navigation
            self.record('mission_started', mission=receipt)
            self.publish_status(now, force=True)
            return None
        raise ValueError('unknown_action')

    def cancel_command(self, command, reason):
        if self.manual_aim.cancel(command, reason) or self.native_actions.cancel(command, reason):
            return
        if command['action'] in ('wait_state', 'assert_state', 'select_shell', 'reload'):
            self.test_actions.cancel(command, reason)
            return
        if command['id'] in (self.mission_command, self.drive_command, self.halt_command):
            self.stop(reason, preserve_explicit=True)
        elif command['id'] == self.fire_command:
            context = self._command_trigger_context(command['id'])
            if context is not None:
                context['controller_detached'] = True
                context['stop_requested'] = reason
            # Command timeout retires observation, never accepted physical
            # execution; subsequent shell receipts retain the original ID.
            self.fire_command = None

    def finish_mission(self, now):
        if self.navigation is None or self.mission_command is None:
            return
        receipt = self.navigation.mission_status()
        if receipt and receipt.get('status') in ('completed', 'failed', 'cancelled'):
            self.gateway.finish(self.mission_command, receipt['status'],
                receipt.get('reason') or receipt['status'], now, receipt)
            self.mission_command = None

    def battle_finished(self, result):
        now = self.owner._clock()
        if self.navigation is not None:
            finish = getattr(self.navigation, 'finish_battle', None)
            if callable(finish):
                finish(result, now)
            self.finish_mission(now)
            self.test_actions.update(now)
        self.stop('battle_finished')
        self.publish_status(now, force=True, reason='battle_finished')

    @staticmethod
    def _trigger_shell_signature(gun):
        from ..gun_mechanics import _field
        try:
            shot = gun.shots[gun.shot_index]
            return (gun.shot_index, id(shot), _field(shot, 'speed'),
                    _field(shot, 'gravity'), _field(shot, 'maxDistance'))
        except (AttributeError, TypeError, IndexError, KeyError):
            return None

    def authorize_trigger(self, context, entity=None, gun=None, shot_ray=None,
                          player_burst=None, native_attempt=None):
        """Fence a new trigger before its first physical shell is admitted."""
        from .commands import same_identity
        owner = self.owner
        # The physical executor never calls this for a committed tail. This
        # defensive branch also prevents a legacy observer treating Stop as
        # authority to retract already accepted weapon execution.
        if isinstance(player_burst, dict) and player_burst.get('committed', 0) > 0:
            return None
        if not isinstance(context, dict):
            return 'trigger_unavailable'
        if not self.live():
            return 'battle_not_live'

        def current():
            if context is not self.trigger_context:
                return 'trigger_replaced'
            if getattr(owner, '_player_control', None) is not self:
                return 'controller_changed'
            if self.closed or self.control_generation != context.get('generation'):
                return 'trigger_cancelled'
            if not same_identity(context.get('identity', {}), self.identity()):
                return 'identity_changed'
            if (owner._server is not context.get('server') or
                    owner.client is not context.get('client') or
                    getattr(owner._server, 'vehicle_id', None) != context.get('vehicle_id')):
                return 'vehicle_changed'
            if native_attempt is not None and context.get('native_attempt') is not native_attempt:
                return 'trigger_replaced'
            if context.get('automatic'):
                if (not self.active or 'fire' not in self.features or
                        self.runtime is not context.get('runtime') or
                        context.get('controller_detached')):
                    return 'automatic_owner_changed'
            command_id = context.get('command')
            if command_id is not None:
                entry = self.gateway.requests.get(command_id)
                receipt = entry.get('receipt', {}) if entry else {}
                admitted = (entry.get('command', {}).get('identity') or receipt) if entry else {}
                if (self.fire_command != command_id or receipt.get('status') != 'accepted' or
                        not same_identity(context['identity'], admitted)):
                    return 'fire_command_cancelled'
                if owner._clock() >= entry.get('deadline', context['deadline']):
                    return 'command_timeout'
            current_gun = getattr(owner, '_gun_state', None)
            if current_gun is not context.get('gun') or gun is not None and gun is not current_gun:
                return 'gun_changed'
            if self._trigger_shell_signature(current_gun) != context.get('shell_signature'):
                return 'shell_changed'
            if self.manual_aim.operation is not context.get('manual_aim'):
                return 'aim_owner_changed'
            lease = context.get('manual_aim')
            if lease is not None:
                from .manual_aim import SOURCE_ATTRIBUTE
                rotator = getattr(owner._avatar, 'gunRotator', None)
                if (lease['phase'] == 'releasing' or rotator is not lease['rotator'] or
                        getattr(rotator, SOURCE_ATTRIBUTE, None) is not lease['source'] or
                        rotator.clientMode is not True):
                    return 'aim_source_lost'
            return None

        reason = current()
        if reason is not None:
            return reason
        current_entity = owner._server_entity(owner._server.vehicle_id)
        if (current_entity is not context.get('entity') or
                entity is not None and entity is not current_entity):
            return 'vehicle_changed'
        if current_entity is None or not current_entity.isAlive():
            return 'player_dead'
        if context.get('manual_aim') is not None:
            reason = self.manual_aim.fire_preflight(owner._clock(), shot_ray=shot_ray)
            if reason is not None:
                return reason
        if context.get('automatic'):
            reason = self.runtime.authorize_trigger(context, entity=current_entity,
                gun=getattr(owner, '_gun_state', None), shot_ray=shot_ray)
            if reason is not None:
                return reason
        if owner._server_entity(context['vehicle_id']) is not context['entity']:
            return 'vehicle_changed'
        return current()

    def _native_trigger(self):
        """Use stock Avatar.shoot for the real native waiting handshake."""
        before = self.shot_commits
        pending = getattr(self.owner, '_local_fire_intent', None)
        self.native_triggering = True
        try:
            self.owner._avatar.shoot()
        finally:
            self.native_triggering = False
        current = getattr(self.owner, '_local_fire_intent', None)
        return self.shot_commits > before or (isinstance(current, dict) and current is not pending)

    def _issue_trigger(self, supplied, now, command_id=None, automatic=False):
        owner = self.owner
        if (self.trigger_context is not None or
                getattr(owner, '_local_fire_intent', None) is not None or
                getattr(owner, '_local_player_burst', None) is not None):
            self.last_fire_failure = 'gun_busy'
            return False
        self.last_fire_failure = None
        self.trigger_sequence += 1
        entry = self.gateway.requests.get(command_id) if command_id is not None else None
        identity = ((entry.get('command', {}).get('identity') or entry.get('receipt'))
                    if entry is not None else self.identity())
        identity = dict((key, identity.get(key)) for key in ('session_id', 'round_id', 'player_id'))
        entity = owner._server_entity(owner._server.vehicle_id)
        gun = getattr(owner, '_gun_state', None)
        context = dict(supplied or {})
        if not automatic:
            context['target'] = self.manual_aim.target_id if self.manual_aim.held else self.target_engine
        context.update(command=command_id, automatic=bool(automatic),
            runtime=self.runtime, time=now, projectiles=[],
            generation=self.control_generation, identity=identity, entity=entity,
            server=owner._server, client=owner.client, vehicle_id=owner._server.vehicle_id,
            gun=gun, shell_signature=self._trigger_shell_signature(gun),
            manual_aim=self.manual_aim.operation,
            deadline=entry.get('deadline') if entry is not None else None,
            trigger_sequence=self.trigger_sequence, controller_detached=False)
        self.trigger_context = context
        try:
            reason = self.authorize_trigger(context)
            if reason is not None:
                self.last_fire_failure = reason
                return False
            accepted = self._native_trigger()
            pending = getattr(owner, '_local_fire_intent', None)
            if accepted and isinstance(pending, dict):
                pending['player_control'] = context
                burst = pending.get('player_burst')
                if isinstance(burst, dict):
                    burst['player_control'] = context
                    self.owned_burst = burst
            return accepted
        finally:
            if self.trigger_context is context:
                self.trigger_context = None

    def issue_automatic_trigger(self, context, now):
        if not self.active or 'fire' not in self.features or self.manual_aim.held:
            self.last_fire_failure = 'automatic_owner_changed'
            return False
        return self._issue_trigger(context, now, automatic=True)

    def _admission(self):
        if self.trigger_admission is None:
            from .trigger_admission import TriggerAdmission
            self.trigger_admission = TriggerAdmission(self)
        return self.trigger_admission

    def prepare_trigger(self, context, entity, gun, frozen_ray,
                        dispersion_angle, source_shot, now, range_origin=None):
        return self._admission().prepare(context, entity, gun, frozen_ray,
            dispersion_angle, source_shot, now, range_origin=range_origin)

    def validate_trigger(self, token, context, entity, gun, now, launch=None):
        return self._admission().validate(token, context, entity, gun, now, launch=launch)

    def trigger_committed(self, token):
        return self._admission().committed(token)

    def fire_rejected(self, reason, projectile_id=None):
        now = self.owner._clock()
        shot = self.shot_receipts.get(projectile_id)
        context = self.trigger_context
        if context is None and self.owned_burst is not None:
            context = self.owned_burst.get('player_control')
        if (projectile_id is not None and context is not None and
                projectile_id not in context.get('projectiles', ())):
            context = None
        failure_identity = (self.control_generation, self.trigger_sequence)
        current_failure = (projectile_id is None or shot is not None and
                (shot['generation'], shot['trigger_sequence']) == failure_identity)
        if current_failure:
            self.last_fire_failure = str(reason)
        command_id = shot['command_id'] if shot is not None else (context or {}).get('command')
        if command_id is not None:
            self.gateway.finish(command_id, 'failed', str(reason), now)
            if self.fire_command == command_id:
                self.fire_command = None
        if projectile_id is not None:
            self.emit_shot(self.shot_receipts.rejected(projectile_id, reason, now))
        # Historical receipts still settle, but cannot change a later owner's
        # decision state. Receipt publication may itself replace that owner.
        if current_failure and failure_identity == (
                self.control_generation, self.trigger_sequence):
            self._runtime_event('fire_rejected', reason, projectile_id)

    def release_burst(self, burst):
        """Detach a controller observer; never mutate physical trigger state."""
        if not isinstance(burst, dict):
            return
        context = burst.get('player_control')
        if isinstance(context, dict):
            context['controller_detached'] = True
        if self.owned_burst is burst and burst is not getattr(self.owner, '_local_player_burst', None):
            self.owned_burst = None

    def trigger_terminated(self, burst, reason):
        if not isinstance(burst, dict):
            return
        context = burst.get('player_control') or {}
        command_id = context.get('command')
        if command_id is not None:
            self.gateway.finish(command_id, 'failed', str(reason), self.owner._clock(),
                dict(committed=burst.get('committed', 0),
                     trigger_count=burst.get('count'),
                     projectile_ids=list(context.get('projectiles', ()))))
            if self.fire_command == command_id:
                self.fire_command = None
        if self.owned_burst is burst:
            self.owned_burst = None
        self.record('physical_trigger_terminated', group=burst.get('group_seq'),
                    committed=burst.get('committed', 0), reason=reason)

    def burst_cancelled(self, burst):
        # The battle invokes this receipt only for a physical terminal. Its
        # old name is not an API for cancelling execution from a controller.
        reason = (burst or {}).get('terminal_reason', 'physical_trigger_terminated')
        self.trigger_terminated(burst, reason)

    def target_point(self, target):
        shape = self.owner._collision_shape(target.typeDescriptor)
        point = tuple(target.position)
        return (point[0], point[1]+max(.5, (shape[2]+shape[3])*.5), point[2])

    def emit_shot(self, receipt):
        if receipt is not None:
            self.emit_result(dict(self.identity(), **receipt))

    def attacked(self, attacker_engine_id, event=None):
        if self.active and attacker_engine_id is not None:
            return self._runtime_event('attacked', attacker_engine_id, event)

    def drive_contact(self, position, heading, dt, static, contact=None):
        if self.active and 'drive' in self.features:
            self.drive_contact_receipt = dict(contact) if isinstance(contact, dict) else None
            return self._runtime_event('drive_contact', position, heading, dt, static, contact)

    def shot_committed(self, event, pending):
        if self.shot_receipts.get(event.get('projectile_id')) is not None:
            return
        self.shot_commits += 1
        burst = pending.get('player_burst')
        context = pending.get('player_control') or self.trigger_context
        if context is None and isinstance(burst, dict):
            context = burst.get('player_control')
        if isinstance(context, dict):
            target = context.get('target')
            receipt_context = dict(context)
            if isinstance(target, dict):
                receipt_context['target'] = target.get('engine_id', target.get('id'))
            self.emit_shot(self.shot_receipts.committed(event, pending, receipt_context,
                self.owner._clock(), self.control_generation))
            self.automatic_commits += 1
            context.setdefault('projectiles', []).append(event.get('projectile_id'))
            if isinstance(burst, dict):
                burst['player_control'] = context
                if burst is getattr(self.owner, '_local_player_burst', None):
                    self.owned_burst = burst
            self.record('shot_committed', projectile=event['projectile_id'],
                        shell=event['shell_index'], trigger=pending.get('burst_group_seq'))
            finished = burst is None or burst.get('committed', 0) >= burst.get('count', 1)
            command_id = context.get('command')
            if command_id is not None and finished:
                self.gateway.finish(command_id, 'completed', 'shot_committed',
                    self.owner._clock(), dict(projectile_id=event.get('projectile_id'),
                        projectile_ids=list(context['projectiles']),
                        shell_index=event.get('shell_index'),
                        burst_group=pending.get('burst_group_seq'),
                        burst_count=pending.get('burst_count', 1),
                        controller_detached=bool(context.get('controller_detached')),
                        stop_requested=context.get('stop_requested'),
                        stage='local_committed'))
                if self.fire_command == command_id:
                    self.fire_command = None
            if finished and self.owned_burst is burst:
                self.owned_burst = None
        self._runtime_event('shot_committed', event, pending)

    def shot_hit(self, event):
        known = self.shot_receipts.get(event.get('projectile_id')) is not None
        receipt = self.shot_receipts.hit(event, self.owner._clock())
        if known and receipt is None:
            return
        self.emit_shot(receipt)
        self._runtime_event('shot_hit', event)

    def shot_terminal(self, event):
        self.emit_shot(self.shot_receipts.terminal(event, self.owner._clock()))
        self._runtime_event('shot_terminal', event)

    def update(self, dt, now):
        if self.closed:
            return
        if not self.live():
            if not self._nonlive_stopped:
                self.stop('battle_not_live')
                self._nonlive_stopped = True
            self.retry_releases(now)
            self.poll_commands(now)
            self.publish_status(now, reason='battle_not_live')
            return
        self._nonlive_stopped = False
        self.bind_input()
        self.test_actions.update(now)
        self.manual_aim.update(now)
        self.native_actions.update(now)
        self.poll_commands(now)
        if not self.live():
            self.stop('player_dead')
            self.publish_status(now, reason='player_dead')
            return
        self.retry_releases(now)
        if (self._auto_start_pending and not self.release_pending and
                not self.halted and self.override is None and
                getattr(self.owner, '_gun_state', None) is not None):
            try:
                ready = self.input_available()
            except (AttributeError, ImportError):
                ready = False
            if ready:
                self.record('launcher_auto_start')
                self.toggle()
        from .capabilities import ammunition_state
        self.ammo_state = ammunition_state(self.owner._gun_state)
        sender = self.owner._sender
        if self.halted:
            sender.forward = sender.turn = 0.
            sender.handbrake = True
            sender.send_current()
            settled = self.halt_observation.observe(self.owner, now, bool(self.release_pending))
            if self.halt_command is not None and settled:
                self.gateway.finish(self.halt_command, 'completed', 'halted', now,
                                    dict(self.halt_observation.receipt))
                self.halt_command = None
            self.publish_status(now)
            return
        if self.override is not None:
            until, forward, turn = self.override
            if now >= until:
                if self.drive_command is not None:
                    self.gateway.finish(self.drive_command, 'completed', 'drive_completed', now)
                    self.drive_command = None
                self.stop('script_completed', preserve_explicit=True)
            else:
                sender.forward, sender.turn, sender.handbrake = forward, turn, False
                sender.send_current()
            self.publish_status(now)
            return
        if self.active:
            runtime = self.runtime
            generation, identity = self.control_generation, self.identity()
            if runtime is None:
                self.last_control_failure = 'full_player_runtime_missing'
                self.stop('full_player_runtime_missing')
            else:
                try:
                    # The copied loop owns both planning cadence and motion
                    # continuity. There is no second reduced decision loop,
                    # fixed test-only tick, or wrapper-owned tactical policy.
                    if (self._runtime_binding is not None and
                            self._native_binding() != self._runtime_binding):
                        self.stop('native_identity_changed')
                        status = None
                    elif self.active and self.control_generation == generation:
                        status = runtime.update(dt, now)
                    else:
                        status = None
                    if (self.active and self.runtime is runtime and
                            self.control_generation == generation and self.identity() == identity):
                        if not runtime.active:
                            self.stop('full_player_runtime_retired')
                        else:
                            self.runtime_status = status if isinstance(status, dict) else runtime.status()
                            self.navigation = runtime.navigation
                            self.last_order = dict(self.runtime_status.get('order') or {})
                            self.aim_receipt = self.runtime_status.get('aim')
                            target = self.runtime_status.get('target')
                            self.target_engine = (target.get('engine_id', target.get('id'))
                                                  if isinstance(target, dict) else target)
                            self.finish_mission(now)
                except Exception as error:
                    self.last_control_failure = repr(error)[:160]
                    self.record('runtime_update_failed', reason=self.last_control_failure)
                    self.stop('runtime_update_failed')
        self.publish_status(now)


def attach(owner):
    global _current
    raw = os.environ.get('WOT_OFFLINE_PLAYER_AUTOCONTROL', '0')
    if raw == '0' or owner._worker_mode or owner._replay_mode:
        return None
    if _current is not None:
        _current.close()
    _current = PlayerControl(owner, raw.split(','), auto_start=True)
    path = os.environ.get('WOT_OFFLINE_TEST_CONTROL_FILE')
    if path and os.path.isfile(path):
        _current.command_offset = os.path.getsize(path)
    _current.record('attached', features=sorted(_current.features), command_file=path,
                    implementation='full_independent_behavior_copy')
    _current.publish_status(owner._clock(), force=True, reason='attached')
    return _current
