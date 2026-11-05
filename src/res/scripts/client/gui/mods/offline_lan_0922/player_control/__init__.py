# -*- coding: utf-8 -*-
"""Foreground-only human automation. No Bot actor, policy or driving imports.

Native physics, weapon mechanics, network authority and immutable map catalogs
remain services; all player decisions live inside this package.
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
    def __init__(self, owner, features, notify=native_message):
        from .traffic import PlayerTraffic
        self.player_traffic = PlayerTraffic()
        self.drive_failure = None
        self.drive_contact_receipt = None
        self.blocked_fire_target = None
        self.engagement_hold = None
        self.front_priority = None
        self.blocked_fire_sample = None
        self.no_aim_since = None
        self.last_shell_request = None
        self.aim_detail_sequence = 0
        self.aim_detail_signature = None
        self.next_round_request = None
        self.owner, self.features, self.notify = owner, set(features) & set(('drive', 'fire', 'consumables')), notify
        self.active = self.key_down = False
        self.navigation = self.weapon = self.ammo_policy = None
        self.aiming = None
        self.direct_engagement = None
        from .targeting import TargetSelection
        from .tactics import CombatTactics, ConfirmedFacing
        from .fire_admission import FireAdmission
        self.target_selection = TargetSelection()
        self.combat_tactics = CombatTactics()
        self.confirmed_facing = ConfirmedFacing()
        self.fire_admission = FireAdmission(self)
        self.strategy = None
        self.next_strategy = 0.
        self.handover_burst = None
        self.aim_receipt = None
        self.next_decision = 0.0
        self.last_decision = None
        self.command_offset = 0
        self.next_poll = 0.0
        self.override = None
        self.target_engine = None
        self.closed = False
        self.input_binding = None
        self.consumable_pending = {}
        self.shot_commits = 0
        self.automatic_commits = 0
        self.owned_burst = None
        self.trigger_context = None
        self.retired_policies = []
        self.halted = False
        from .settling import HaltObservation
        from .shot_receipts import ShotReceipts
        self.halt_observation = HaltObservation()
        self.shot_receipts = ShotReceipts()
        self.control_generation = 0
        self.trigger_sequence = 0
        self.mission_command = self.drive_command = self.fire_command = self.halt_command = None
        self.last_fire_failure = None
        self.ammo_state = dict(state='unknown', empty=False, available=False)
        self.next_status = 0.
        self.observations = {}
        from .capabilities import Governor
        self.governor = Governor()
        self.owned_governor = None
        self.governor_request = None
        self.last_order = {}
        self.release_pending = []
        self.next_release = 0.
        self.siege_intent = None
        self.siege_brake = None
        self.siege_observer = None
        from .wrecks import WreckPush
        self.wreck_push = WreckPush()
        from .commands import CommandGateway, JournalReader
        self.command_reader = JournalReader()
        self.gateway = CommandGateway(self.identity, self.emit_result,
            self.execute_command, self.command_preflight, self.cancel_command)
        from .test_actions import TestActions
        self.test_actions = TestActions(self)
        from .manual_aim import ManualAim
        from .native_actions import NativeActions
        self.manual_aim = ManualAim(self)
        self.native_actions = NativeActions(self)

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
        # Read-only tests observe every controller update, including halted and
        # released states; their cadence is not the one-second UI heartbeat.
        self.test_actions.update(now)
        self.native_actions.update(now)
        if not force and now < self.next_status:
            return
        self.next_status = now + 1.
        navigation = self.navigation
        mission = navigation.mission_status() if navigation is not None else None
        pose = None
        if self.live():
            position, yaw = self.owner.local_pose()
            pose = dict(position=tuple(position), yaw=yaw, speed=self.owner._local_speed)
        row = dict(self.identity(), type='status', time=now, live=self.live(),
            reason=reason, active=self.active, halted=self.halted,
            features=sorted(self.features), mission=mission, ammo=self.ammo_state,
            pose=pose, aim=self.aim_receipt, last_command=self.gateway.last,
            halt=self.halt_observation.receipt if self.halted else None,
            testing=self.test_actions.snapshot(),
            manual_aim=self.manual_aim.snapshot(),
            native_actions=self.native_actions.snapshot(),
            shot_results=self.shot_receipts.snapshot(),
            release_pending=[stage for stage, unused in self.release_pending],
            navigation=(dict(entry=navigation.receipt, artillery=self.last_order.get('artillery'),
                             combat=self.last_order.get('combat')) if navigation is not None else None))
        # Match the receiver's bounded line contract. Long legal command IDs
        # and multi-effect shots must not make every heartbeat unreadable.
        # Direct one-shot events remain intact; this is a repair window only.
        import json
        row['shot_snapshot_omitted'] = 0
        while row['shot_results']:
            try:
                size = len(json.dumps(row, ensure_ascii=True, allow_nan=False,
                                      separators=(',', ':')).encode('ascii'))
            except (TypeError, ValueError):
                # The ordinary result writer owns/report serialization errors;
                # diagnostics cannot terminate physical player control.
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

    def record_aim_decision(self, now, pose, command, order, fire_ready, fire_allowed):
        trace = getattr(self.aiming, 'comparison_trace', None)
        engagement = self.direct_engagement
        if trace is None or engagement is None:
            return
        self.aim_detail_sequence += 1
        aim = self.aim_receipt or {}
        scan = engagement.scan
        mode = scan['identity'][2] if scan is not None else None
        stage = engagement.stage
        shell = self.owner._gun_state.shot_index
        signature = (engagement.target, engagement.sample, stage, self.target_engine, shell,
            aim.get('fire_clear'), aim.get('aligned'), bool(fire_ready), bool(fire_allowed), mode,
            command, self.ammo_state.get('state'), order.get('combat_mode'),
            tuple((item['target'], item['mode'], item['shell'], item['sample'],
                item['verdict'], item['reason'], item.get('barrel_verdict')) for item in trace))
        if signature == self.aim_detail_signature:
            return
        self.aim_detail_signature = signature
        from ..native_input_diagnostics import write_json_record
        try:
            write_json_record('PLAYER AIM DECISION', dict(
                player=self.owner.client.player_id, round=self.owner._start_message.get('round_id'),
                decision=self.aim_detail_sequence, battle_time=now, lock=engagement.target,
                target=self.target_engine, sample=engagement.sample, stage=stage, shell=shell,
                position=pose[0], yaw=pose[1], point=aim.get('point'), aligned=aim.get('aligned'),
                ammo_state=self.ammo_state.get('state'), fire_clear=aim.get('fire_clear'),
                fire_ready=bool(fire_ready), fire_allowed=bool(fire_allowed),
                command=command, checking=engagement.checking, scan=mode,
                remaining=len(scan['pending']) if scan is not None else None,
                visible=len(self.aiming.targets), comparisons=trace,
                budget_left=(self.aiming._candidates, self.aiming._segments, self.aiming._angles),
                movement=order.get('combat_mode'), turn=order.get('turn'),
                brake=order.get('brake')))
        except Exception:
            # A diagnostic sink may be closed while gameplay still runs.
            pass

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
        if self.active:
            self.stop('manual')
            return False
        generation, identity = self.control_generation, self.identity()
        if (not self.live() or self.release_pending or not self.features or
                self.test_actions.gun_pending and 'fire' in self.features or
                self.manual_aim.held and 'fire' in self.features or
                self.native_actions.equipment_pending and 'consumables' in self.features or
                self.native_actions.siege_pending and self.features & set(('drive', 'fire'))):
            return False
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            return False
        from .navigation import PlayerNavigation
        from .weapon import Weapon
        from .ammunition import Ammunition
        from .strategy import Strategy
        from .traffic import TurnClearance
        from .aiming import Aiming
        from .ammunition import mounted_shells
        gun = owner._gun_state
        shells = mounted_shells(entity.typeDescriptor, gun.shots)
        if (not shells or generation != self.control_generation or
                identity != self.identity() or self.active):
            return False
        if self.override is not None or self.halted:
            if not self.stop('manual_takeover', preserve_explicit=True):
                return False
            generation += 1
            if (generation != self.control_generation or self.active or
                    identity != self.identity()):
                return False
        features = set(self.features)
        avatar = getattr(owner, '_avatar', None)
        rotator = getattr(avatar, 'gunRotator', None)
        weapon = Weapon(owner)
        original_close = weapon.close
        startup = dict(writing=True, closing=False, deferred=False, attempted=False)

        def release_weapon():
            # A native setter can call Stop before its own write returns.
            # Keep the old lease until that stack unwinds; a new start must
            # not race the old setter's remaining source/clientMode writes.
            if startup['writing'] or startup['closing']:
                startup['deferred'] = True
                raise RuntimeError('automatic_start_release_pending')
            startup['attempted'] = startup['closing'] = True
            self.release_pending.append(('aim_release', release_weapon))
            try:
                original_close()
            except Exception as error:
                raise RuntimeError(repr(error)[:160])
            finally:
                startup['closing'] = False
                self.release_pending = [(stage, callback) for stage, callback in self.release_pending
                                        if callback is not release_weapon]

        weapon.close = release_weapon
        self.ammo_policy = Ammunition(shells, shells[0]['index'], gun.shot_index, gun.clip_size,
                                     artillery='SPG' in entity.typeDescriptor.type.tags)
        if gun.ammo[gun.shot_index] <= 0:
            self.ammo_policy.protected = False
        self.navigation = None
        self.strategy = Strategy()
        self.turn_clearance = TurnClearance()
        from .traffic import PlayerTraffic
        self.player_traffic = PlayerTraffic()
        self.drive_failure = None
        self.drive_contact_receipt = None
        self.target_selection.reset()
        self.combat_tactics.reset()
        self.confirmed_facing.reset()
        self.fire_admission.reset()
        self.blocked_fire_target = None
        self.engagement_hold = None
        self.front_priority = None
        self.blocked_fire_sample = None
        self.no_aim_since = None
        self.last_shell_request = None
        self.aim_detail_signature = None
        self.next_strategy = 0.
        self.weapon = weapon
        self.active = True
        self.control_generation += 1
        generation = self.control_generation
        self.halted = False
        self.last_fire_failure = None
        self.aiming = Aiming(owner)
        if not self.ammo_policy.artillery:
            from .direct_engagement import DirectEngagement
            self.direct_engagement = DirectEngagement(entity.typeDescriptor)
        self.last_decision = None
        self.next_decision = 0.0
        self.release_pending.append(('automatic_start_release', release_weapon))

        def claimed():
            return (self.active and self.weapon is weapon and
                    self.control_generation == generation)

        def current():
            live = self.live()
            current_entity = owner._server_entity(owner._server.vehicle_id) if owner._server else None
            return (live and claimed() and not self.closed and
                    not any(callback is not release_weapon for unused, callback in self.release_pending) and
                    identity == self.identity() and current_entity is entity and
                    owner._gun_state is gun and getattr(owner, '_avatar', None) is avatar and
                    ('fire' not in features or getattr(avatar, 'gunRotator', None) is rotator) and
                    self.features == features)

        started, failure, created_navigation, installed_navigation = False, None, None, False
        try:
            if not current():
                raise RuntimeError('automatic_start_owner_changed')
            if 'drive' in features:
                created_navigation = navigation or PlayerNavigation(owner, entity.typeDescriptor)
                if not current():
                    raise RuntimeError('automatic_start_owner_changed')
                self.navigation = created_navigation
                installed_navigation = True
            if 'fire' in features:
                weapon.bind()
                if (rotator is not None and
                        (rotator._VehicleGunRotator__shotPointSourceFunctor is not weapon.bound_source or
                         rotator.clientMode is not True)):
                    raise RuntimeError('automatic_start_aim_owner_changed')
            if not current():
                raise RuntimeError('automatic_start_owner_changed')
            self.record('enabled', features=sorted(features), inventory=list(gun.ammo), shells=shells)
            if current():
                self.notify(u'【测试】玩家自动控制已开启。')
                started = current()
        except Exception as error:
            failure = repr(error)[:160]
        finally:
            startup['writing'] = False
            self.release_pending = [(stage, callback) for stage, callback in self.release_pending
                                    if stage != 'automatic_start_release' or callback is not release_weapon]
            if not started:
                if claimed():
                    self.stop('automatic_start_failed', preserve_explicit=True)
                # Stop may have retired this weapon while bind was still in
                # progress. Drain just that deferred release, never a newer
                # controller's fields or unrelated failed cleanup callbacks.
                if not startup['attempted']:
                    self.release_pending = [(stage, callback) for stage, callback in self.release_pending
                                            if callback is not release_weapon]
                    self._run_releases([('aim_release', release_weapon)], owner._clock())
                if created_navigation is not None and not installed_navigation:
                    self._run_releases([('navigation_close', created_navigation.close)], owner._clock())
                self.record('start_failed', reason=failure or 'automatic_start_owner_changed')
            weapon.close = original_close
        return started

    def stop(self, reason='manual', preserve_explicit=False):
        changed = self.active or self.override is not None or self.halted
        drive_owned = self.owns_drive()
        owner = self.owner
        now = owner._clock() if callable(getattr(owner, '_clock', None)) else 0.
        commands = (self.mission_command, self.drive_command, self.halt_command)
        if not preserve_explicit:
            changed = changed or self.manual_aim.held or self.native_actions.busy
            commands += (self.fire_command,)
        for command_id in commands:
            if command_id is not None:
                self.gateway.finish(command_id, 'cancelled', reason, now)
        self.mission_command = self.drive_command = self.halt_command = None
        if not preserve_explicit:
            self.fire_command = None
        self.active = False
        self.control_generation += 1
        if self.next_round_request is not None:
            self.queue_next_automatic_round(None)
        self.fire_admission.reset()
        self.target_selection.reset()
        self.combat_tactics.reset()
        self.drive_contact_receipt = None
        if preserve_explicit:
            # Movement turnover does not revoke a separately admitted fire
            # transaction. Its actual token and all other identity/aim/gun
            # fences remain unchanged; full Stop deliberately does revoke it.
            pending = getattr(owner, '_local_fire_intent', None)
            contexts = [self.trigger_context,
                        (self.owned_burst or {}).get('player_control'),
                        pending.get('player_control') if isinstance(pending, dict) else None]
            for context in contexts:
                if isinstance(context, dict) and context.get('command') is not None:
                    context['generation'] = self.control_generation
        self.override = None
        self.halted = False
        if not preserve_explicit:
            self.test_actions.stop(reason, now)
            self.native_actions.stop(reason, now)
        from .settling import HaltObservation
        self.halt_observation = HaltObservation()
        self.target_engine = self.aim_receipt = self.aim_progress_sample = None
        self.last_order = {}
        self.confirmed_facing.reset()
        self.engagement_hold = self.front_priority = None
        callbacks = list(self.release_pending)
        self.release_pending = []
        if not preserve_explicit:
            # A failed native source restore is retried by the existing
            # bounded release loop, not on every post-battle update.
            from .manual_aim import RELEASE_STAGE
            from .native_actions import RELEASE_STAGE as SIEGE_RELEASE_STAGE
            retained_stages = (RELEASE_STAGE, SIEGE_RELEASE_STAGE,
                               'automatic_start_release')
            self.release_pending = [(stage, callback) for stage, callback in callbacks
                                    if stage in retained_stages]
            callbacks = [(stage, callback) for stage, callback in callbacks
                         if stage not in retained_stages]
            if not any(stage == RELEASE_STAGE for stage, unused in self.release_pending):
                self.manual_aim.stop(reason, now)
        # Clear claimed inputs before any native resource teardown can fail.
        # A repeated stop cannot lose this obligation after active became false.
        if owner._sender is not None and drive_owned:
            owner._sender.forward = owner._sender.turn = 0.0
            owner._sender.handbrake = False
            callbacks.insert(0, ('input_release', owner._sender.send_current))
        if self.navigation is not None:
            callbacks.append(('navigation_close', self.navigation.close))
        self.navigation = None
        if self.ammo_policy is not None:
            self.retired_policies.append(self.ammo_policy)
        self.ammo_policy = self.strategy = None
        if self.weapon is not None:
            callbacks.append(('aim_release', self.weapon.close))
        self.weapon = None
        if self.aiming is not None:
            callbacks.append(('aim_cache_reset', self.aiming.reset))
        self.aiming = None
        self.direct_engagement = None
        burst = self.owned_burst
        keep_burst = bool(preserve_explicit and burst is not None and
                          (burst.get('player_control') or {}).get('command') is not None)
        if burst is not None and not keep_burst:
            callbacks.append(('burst_release', lambda:self.release_burst(burst)))
        if not keep_burst:
            self.owned_burst = None
        siege_observer, self.siege_observer = self.siege_observer, None
        self.siege_intent = self.siege_brake = None
        if siege_observer is not None:
            # Cancel only this automatic request's still-unsent brake. A
            # submitted native transition or a newer explicit owner remains.
            callbacks.append(('automatic_siege_release',
                lambda:owner._cancel_player_control_siege(siege_observer)))
        from .wrecks import WreckPush
        self.wreck_push = WreckPush()
        if not any(stage == 'governor_release' for stage, unused in callbacks):
            callbacks.append(('governor_release', self.release_governor))
        self._run_releases(callbacks, now)
        if changed:
            self.record('disabled', reason=reason,
                        pending_release=[stage for stage, unused in self.release_pending])
            if self.live() and not self.release_pending:
                self.notify(u'【测试】玩家自动控制已关闭，恢复手动操作。')
        return not self.release_pending

    def _run_releases(self, callbacks, now):
        """Retry retired resources without cancelling the current brake owner."""
        previous_deadline = self.next_release if self.release_pending else None
        for stage, callback in callbacks:
            try:
                result = callback()
                if stage == 'input_release' and result is False:
                    raise RuntimeError('input_release_not_submitted')
            except Exception as error:
                self.release_pending.append((stage, callback))
                self.record('release_failed', resource=stage, reason=repr(error)[:160])
        # An unrelated successful cleanup must not postpone a retained aim
        # or setting cleanup forever during repeated non-live updates.
        self.next_release = (min(previous_deadline, now + 1.)
                             if self.release_pending and previous_deadline is not None
                             else now + 1.)

    def retry_releases(self, now):
        if self.release_pending and now >= self.next_release:
            callbacks, self.release_pending = self.release_pending, []
            self._run_releases(callbacks, now)

    def close(self):
        global _current
        if self.closed:
            return
        self.stop('battle_exit')
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
                        reason='active' if enabled else 'start_failed')
        if action == 'drive':
            # Validation and admission happened before this ownership change.
            if not self.stop('replaced_by_drive', preserve_explicit=True):
                return dict(status='failed', reason='release_pending')
            self.override = (now + args['seconds'], args['forward'], args['turn'])
            self.drive_command = command_id
            return None
        if action == 'fire':
            from .weapon import Weapon
            self.fire_command = command_id
            weapon = self.weapon if self.active and 'fire' in self.features else Weapon(self.owner)
            accepted = self.trigger(weapon, now, command_id)
            self.record('script_fire', accepted=bool(accepted))
            if not accepted:
                self.fire_command = None
                return dict(status='failed', reason=self.last_fire_failure or 'trigger_rejected')
            # A normal #1513 commit is synchronous. An admitted asynchronous
            # callback is still completed by shot_committed, never by a write.
            return None
        if action in MISSIONS:
            position, yaw = self.owner.local_pose()
            entity = self.owner._server_entity(self.owner._server.vehicle_id)
            shape = self.owner._collision_shape(entity.typeDescriptor)
            state = dict(id=self.owner.client.player_id, engine_id=entity.id, position=tuple(position), yaw=yaw,
                         speed=self.owner._local_speed, now=now,
                         half_length=shape[1], half_width=shape[0])
            from .navigation import PlayerNavigation
            prepared = self.navigation or PlayerNavigation(self.owner, entity.typeDescriptor)
            created = prepared is not self.navigation
            mission_args = dict(args, command_id=command_id, timeout=command['timeout_seconds'])
            receipt = prepared.validate_mission(action, mission_args, state)
            if receipt.get('status') in ('failed', 'rejected'):
                if created:
                    try:
                        prepared.close()
                    except Exception as error:
                        self.release_pending.append(('prepared_navigation_close', prepared.close))
                        self.record('release_failed', resource='prepared_navigation', reason=repr(error)[:160])
                return dict(status='failed', reason=receipt.get('reason', 'mission_unavailable'),
                            result=receipt)
            if self.override is not None or self.halted:
                self.stop('replaced_by_mission', preserve_explicit=True)
            if not self.active and not self.toggle(navigation=prepared):
                if created:
                    prepared.close()
                return dict(status='failed', reason='start_failed')
            receipt = self.navigation.start_mission(action, mission_args, state)
            previous = self.mission_command
            if previous is not None:
                self.gateway.finish(previous, 'cancelled', 'replaced', now)
            self.mission_command = command_id
            self.next_strategy = self.next_decision = 0.
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
            # Releasing future trigger ownership cannot undo committed rounds.
            burst = self.owned_burst
            if burst is not None and (burst.get('player_control') or {}).get('command') == command['id']:
                self.release_burst(burst)
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
            self.navigation.finish_battle(result, now)
            self.finish_mission(now)
            # Capture completion is an observed mission transition. Preserve
            # it for matching watchers before releasing the navigation owner.
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
        """Recheck one uncommitted native round after callbacks may revoke it.

        Ordinary manual shots have no context and never call this gate. The
        same context owns a released trigger's remaining native burst, but a
        cancelled command cannot authorize another round or another vehicle.
        """
        from .test_actions import _same_identity
        owner = self.owner
        if not isinstance(context, dict):
            return 'trigger_unavailable'
        if not self.live():
            return 'battle_not_live'

        def current():
            command_id = context.get('command')
            current_time = owner._clock() if command_id is not None else None
            if context is not self.trigger_context and not (
                    player_burst is not None and player_burst is self.owned_burst and
                    player_burst is getattr(owner, '_local_player_burst', None) and
                    player_burst.get('player_control') is context):
                return 'trigger_replaced'
            if getattr(owner, '_player_control', None) is not self:
                return 'controller_changed'
            if (self.closed or getattr(owner, 'state', 'running') != 'running' or
                    not getattr(owner, '_battle_live', True) or
                    getattr(owner, '_battle_result', None) is not None or
                    self.control_generation != context.get('generation')):
                return 'trigger_cancelled'
            if not _same_identity(context.get('identity', {}), self.identity()):
                return 'identity_changed'
            if (owner._server is not context.get('server') or
                    owner.client is not context.get('client') or
                    getattr(owner._server, 'vehicle_id', None) != context.get('vehicle_id')):
                return 'vehicle_changed'
            if native_attempt is not None and context.get('native_attempt') is not native_attempt:
                return 'trigger_replaced'
            if context.get('automatic'):
                weapon = context.get('weapon')
                if not self.active or 'fire' not in self.features or weapon is not self.weapon:
                    return 'automatic_owner_changed'
                source = getattr(weapon, 'bound_source', None)
                if source is not None:
                    rotator = getattr(owner._avatar, 'gunRotator', None)
                    if (getattr(rotator, '_VehicleGunRotator__shotPointSourceFunctor', None) is not source or
                            getattr(rotator, 'clientMode', False) is not True):
                        return 'aim_source_lost'
            if command_id is not None:
                entry = self.gateway.requests.get(command_id)
                receipt = entry.get('receipt', {}) if entry else {}
                admitted = (entry.get('command', {}).get('identity') or receipt) if entry else {}
                if (self.fire_command != command_id or receipt.get('status') != 'accepted' or
                        not _same_identity(context['identity'], admitted)):
                    return 'fire_command_cancelled'
                if current_time >= entry.get('deadline', context['deadline']):
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
        # Native angle, HUD, entity and clock reads can re-enter Python. End
        # with copied-state fences, never only the earlier alignment receipt.
        if owner._server_entity(context['vehicle_id']) is not context['entity']:
            return 'vehicle_changed'
        return current()

    def trigger(self, weapon, now, command_id=None):
        owner = self.owner
        if (self.trigger_context is not None or
                getattr(owner, '_local_fire_intent', None) is not None or
                getattr(owner, '_local_player_burst', None) is not None):
            self.last_fire_failure = 'gun_busy'
            return False
        self.last_fire_failure = None
        self.trigger_sequence += 1
        target = self.manual_aim.target_id if self.manual_aim.held else self.target_engine
        entry = self.gateway.requests.get(command_id) if command_id is not None else None
        identity = ((entry.get('command', {}).get('identity') or entry.get('receipt'))
                    if entry is not None else self.identity())
        identity = dict((key, identity.get(key)) for key in ('session_id', 'round_id', 'player_id'))
        generation = self.control_generation
        entity = owner._server_entity(owner._server.vehicle_id)
        gun = getattr(owner, '_gun_state', None)
        context = dict(command=command_id, target=target,
                                    automatic=bool(command_id is None and self.active and
                                        self.manual_aim.operation is None and weapon is self.weapon),
                                    weapon=weapon,
                                    policy=self.ammo_policy, time=now, projectiles=[],
                                    generation=generation, identity=identity, entity=entity,
                                    server=owner._server, client=owner.client, vehicle_id=owner._server.vehicle_id,
                                    gun=gun, shell_signature=self._trigger_shell_signature(gun),
                                    manual_aim=self.manual_aim.operation,
                                    deadline=entry.get('deadline') if entry is not None else None,
                                    trigger_sequence=self.trigger_sequence)
        self.trigger_context = context
        try:
            reason = self.authorize_trigger(context)
            if reason is not None:
                self.last_fire_failure = reason
                return False
            accepted = weapon.trigger()
            pending = getattr(owner, '_local_fire_intent', None)
            if accepted and isinstance(pending, dict):
                # Preserve lineage of an admitted round after Stop, without
                # reacquiring its future tail when the native call returns.
                if pending.get('player_control') is None or pending.get('player_control') is context:
                    pending['player_control'] = context
                    if self.authorize_trigger(context) is None:
                        self.owned_burst = pending.get('player_burst')
                    elif pending.get('player_burst') is not None:
                        self.release_burst(pending['player_burst'])
            return accepted
        finally:
            if self.trigger_context is context:
                self.trigger_context = None

    def fire_rejected(self, reason, projectile_id=None):
        now = self.owner._clock()
        shot = self.shot_receipts.get(projectile_id)
        context = self.trigger_context
        if context is None and self.owned_burst is not None:
            context = self.owned_burst.get('player_control')
        if (projectile_id is not None and context is not None and
                projectile_id not in context.get('projectiles', ())):
            context = None
        if (projectile_id is None or
                shot is not None and shot['generation'] == self.control_generation and
                shot['trigger_sequence'] == self.trigger_sequence):
            self.last_fire_failure = str(reason)
        command_id = shot['command_id'] if shot is not None else (context or {}).get('command')
        if command_id is not None:
            self.gateway.finish(command_id, 'failed', str(reason), now)
            if self.fire_command == command_id:
                self.fire_command = None
        if projectile_id is not None:
            policies = self.retired_policies + ([self.ammo_policy] if self.ammo_policy is not None else [])
            for policy in policies:
                policy.reject(projectile_id, now, reason)
            self.emit_shot(self.shot_receipts.rejected(projectile_id, reason, now))

    def release_burst(self, burst):
        owner = self.owner
        pending = getattr(owner, '_local_fire_intent', None)
        if burst is getattr(owner, '_local_player_burst', None):
            if isinstance(pending, dict) and pending.get('player_burst') is burst:
                self.handover_burst = burst
                return
            owner._cancel_local_player_burst(apply_settings=True)
        context = burst.get('player_control') or {}
        if context.get('policy') is not None:
            context['policy'].close_group(burst.get('group_seq'), burst.get('committed', 0))
        if self.owned_burst is burst:
            self.owned_burst = None

    def burst_cancelled(self, burst):
        if burst is None:
            return
        context = burst.get('player_control')
        if context is None:
            return
        if context.get('policy') is not None:
            context['policy'].close_group(burst.get('group_seq'), burst.get('committed', 0))
        if context.get('command') is not None:
            self.gateway.finish(context['command'], 'cancelled', 'native_burst_cancelled',
                self.owner._clock(), dict(committed=burst.get('committed', 0),
                    projectile_ids=list(context.get('projectiles', ()))))
            if self.fire_command == context['command']:
                self.fire_command = None
        if self.owned_burst is burst:
            self.owned_burst = None

    def release_governor(self):
        identity = self.owned_governor
        if identity is not None:
            # This also cancels our on-intent if its server echo is pending.
            if not self.owner._activate_equipment(identity[0]):
                raise RuntimeError('governor_release_not_submitted')
        self.owned_governor = None
        self.governor_request = None
        from .capabilities import Governor
        self.governor = Governor()

    def _contacts(self, entity):
        owner = self.owner
        contacts, neighbours, records = [], [], {}
        now = owner._clock()
        seen = set()
        for record in owner._records.values():
            if not record.get('ready') or record.get('tombstone'):
                continue
            target = owner._server_entity(record.get('engine_id'))
            if target is None or target.id == entity.id:
                continue
            point = tuple(target.position)
            team = int((record.get('state') or {}).get('team', 0))
            row = dict(id=target.id, actor_key=(record.get('kind'), record.get('network_id')),
                       team=team, position=point,
                       health=target.health, max_health=target.typeDescriptor.maxHealth,
                       alive=target.isAlive(), speed=0.0, yaw=float(target.matrix.yaw),
                       pitch=float(target.matrix.pitch), roll=float(target.matrix.roll),
                       collision_shape=owner._collision_shape(target.typeDescriptor))
            tags = target.typeDescriptor.type.tags
            row['class_tag'] = next((tag for tag in
                ('SPG', 'AT-SPG', 'heavyTank', 'mediumTank', 'lightTank') if tag in tags), 'mediumTank')
            # These are received physical input facts, not macro orders from
            # a Bot scheduler. A missing intent stays unknown/absent.
            public = record.get('state') or {}
            throttle = public.get('throttle', public.get('forward'))
            if isinstance(throttle, (int, float)) and not (math.isnan(throttle) or math.isinf(throttle)):
                row['throttle'] = max(-1., min(1., float(throttle)))
                row['movement_intent'] = row['throttle']
            neighbours.append(row)
            # Actual presentation visibility, not the omniscient LAN roster.
            ally = team == int(owner.client.team)
            visible_enemy = team in (1, 2) and not ally and record.get('spot_visible', False)
            if row['alive'] and target.isStarted and (ally or visible_enemy):
                previous = self.observations.get(target.id)
                velocity = (0., 0., 0.)
                if previous is not None and .05 <= now - previous[0] <= 1.:
                    elapsed = now - previous[0]
                    candidate = tuple((point[i] - previous[1][i]) / elapsed for i in range(3))
                    # Reject teleports/first presentation snaps. Observations
                    # are discarded immediately when the enemy leaves vision.
                    if sum(v*v for v in candidate) <= 10000.:
                        velocity = candidate
                row['velocity'] = velocity
                row['speed'] = math.sin(row['yaw'])*velocity[0] + math.cos(row['yaw'])*velocity[2]
                self.observations[target.id] = (now, point)
                seen.add(target.id)
                if visible_enemy:
                    row['visible'] = True
                    contacts.append(row)
                    records[target.id] = target
        for identity in list(self.observations):
            if identity not in seen:
                del self.observations[identity]
        return contacts, neighbours, records

    def target_point(self, target):
        shape = self.owner._collision_shape(target.typeDescriptor)
        point = tuple(target.position)
        return (point[0], point[1]+max(.5, (shape[2]+shape[3])*.5), point[2])

    def firing_lane(self, target):
        start, unused = self.owner._mutable_shot_ray()
        return self.lane_from(target, tuple(start))

    def lane_from(self, target, start, end=None):
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        from ..projectile_runtime import point_segment_distance_sq
        owner = self.owner
        end = self.target_point(target) if end is None else end
        if not owner._tactical_ray_clear(start, end):
            return False
        for record in owner._records.values():
            if record.get('local') or record.get('tombstone') or not record.get('ready'):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or other.id == target.id or not other.isStarted:
                continue
            state = record.get('state') or {}
            if other.isAlive() and int(state.get('team', 0)) != int(owner.client.team):
                continue
            shape = owner._collision_shape(other.typeDescriptor)
            radius = math.hypot(shape[0], shape[1])+abs(shape[3])+1.
            if point_segment_distance_sq(tuple(other.position), start, end) > radius*radius:
                continue
            first, last = owner._vector(start), owner._vector(end)
            if record.get('native_remote'):
                body, chassis = owner._projectile_vehicle_matrices(record, other)
                hits = collide_vehicle_at_matrix(other, body, first, last,
                    owner._runtime.math, chassis_matrix=chassis)
            else:
                hits = other.collideSegmentExt(first, last)
            if hits:
                return False
        return True

    def dynamic_path_clear(self, target, path):
        """Check the entire proposed path against this frame's friendly poses.

        This final gate uses conservative full descriptor boxes, including an
        attached turret/gun, instead of reusing a multi-frame planning proof.
        It performs no native world or component BSP queries. Missing attached
        geometry cannot certify a clear path; landed turret debris is checked
        at the same current server time as the vehicle poses.
        """
        from ..entities.remote_vehicle import (
            _blast_bbox_bounds, _component_value, turret_is_attached,
            vehicle_target_bounds_at_matrix)
        from ..shot_geometry import segment_box_entry_distance
        owner = self.owner
        self.dynamic_blocker = None
        if not path or len(path) < 2:
            self.dynamic_blocker = dict(kind='missing_path')
            return False
        segments = tuple(zip(path, path[1:]))
        for record in owner._records.values():
            if record.get('local') or record.get('tombstone') or not record.get('ready'):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or other.id == target.id or not other.isStarted:
                continue
            state = record.get('state') or {}
            alive = other.isAlive()
            if alive and int(state.get('team', 0)) != int(owner.client.team):
                continue
            blocker = dict(id=other.id, kind='ally' if alive else 'wreck')
            names = ('chassis', 'hull', 'turret', 'gun') if turret_is_attached(other) else ('chassis', 'hull')
            for name in names:
                component = _component_value(other.typeDescriptor, name)
                tester = _component_value(component, 'hitTester')
                if _blast_bbox_bounds(_component_value(tester, 'bbox')) is None:
                    self.dynamic_blocker = dict(blocker, reason='missing_bounds', component=name)
                    return False
            if record.get('native_remote'):
                body, chassis = owner._projectile_vehicle_matrices(record, other)
            else:
                body, chassis = other.matrix, None
            bounds = vehicle_target_bounds_at_matrix(
                other, body, owner._runtime.math, chassis_matrix=chassis)
            if bounds is None:
                self.dynamic_blocker = dict(blocker, reason='missing_bounds')
                return False
            for index, (a, b) in enumerate(segments):
                if segment_box_entry_distance(a, b, bounds) is not None:
                    self.dynamic_blocker = dict(blocker, reason='bounds_intersection', chord=index)
                    return False
        debris = getattr(owner, '_detached_turret_obstacles', None)
        if debris is not None and debris.active():
            server_time = owner._turret_server_time_ms()
            for index, (a, b) in enumerate(segments):
                if debris.target_entry_distance(a, b, server_time) is not None:
                    self.dynamic_blocker = dict(kind='detached_turret', chord=index)
                    return False
        return True

    def artillery_lane(self, target, direction=None):
        from .weapon import artillery_path
        gun = self.owner._gun_state
        start, unused = self.owner._mutable_shot_ray()
        path = artillery_path(tuple(start), self.target_point(target),
                              gun.shots[gun.shot_index], direction)
        return bool(path) and all(self.lane_from(target, a, b)
                                  for a, b in zip(path, path[1:]))

    def attacked(self, attacker_engine_id, event=None):
        # Accepted local damage/hit feedback records an identity, not hidden
        # coordinates. It can only reprioritise a currently visible contact.
        if self.active and attacker_engine_id is not None:
            self.target_selection.attacked(attacker_engine_id, self.owner._clock())

    def drive_contact(self, position, heading, dt, static, contact=None):
        navigation = self.navigation
        if not self.active or 'drive' not in self.features or navigation is None:
            return
        self.drive_failure = (tuple(position), heading)
        if isinstance(contact, dict):
            self.drive_contact_receipt = dict(contact)
        if static:
            navigation.report_drive_blockage(
                self.owner.client.player_id, self.last_order, position, heading,
                self.owner._clock(), dt, realised=True)

    def rotation_clear(self, entity, position, yaw, end_yaw):
        """Read-only native static/body sweep for a proposed wreck-push turn."""
        owner = self.owner
        native = getattr(owner, '_native_world_rotation_is_clear', None)
        boundary = getattr(owner, '_arena_rotation_is_clear', None)
        turrets = getattr(owner, '_turret_pose_is_clear', None)
        catalog = getattr(owner, '_destructible_pose_sweep', None)
        sensor = getattr(owner, '_destructibles', None)
        bbox = getattr(sensor, '_vehicle_body_bbox', None) or getattr(sensor, '_vehicle_hull_bbox', None)
        if not all(callable(value) for value in (native, boundary, turrets, catalog, bbox)):
            return False
        descriptor = entity.typeDescriptor
        shape = bbox(descriptor)
        if not isinstance(shape, (tuple, list)) or len(shape) < 2:
            return False
        pitch, roll = owner._local_pitch, owner._local_roll
        if (not boundary(entity, position, yaw, end_yaw, position) or
                not turrets(position, yaw, position, end_yaw, descriptor, pitch, roll)):
            return False
        proposal = catalog(position, yaw, position, end_yaw, 0., descriptor,
            owner._clock(), .1, commit_enabled=False, pitch=pitch, roll=roll)
        if proposal.get('status') != 'clear' or proposal.get('requires_commit'):
            return False
        return native(position, yaw, end_yaw, descriptor, pitch=pitch, roll=roll,
                      record_local=False, include_static=True)

    def direction_clear(self, position, yaw, descriptor, shape, reach=None):
        # Corridor lanes follow the hull support plane even when the query
        # points backwards or sideways. Travel yaw is not body orientation.
        unused, hull_yaw = self.owner.local_pose()
        pose = (hull_yaw, self.owner._local_pitch, self.owner._local_roll)
        row = self.owner._direction_probe(position, yaw, self.owner._local_speed,
                                          descriptor, reach, shape[0], body_pose=pose)
        self.probe_receipt = row
        return isinstance(row, dict) and bool(row.get('clear')) and not any(
            row.get(key) for key in ('collision', 'water', 'cliff', 'blocked')) and (
            abs(float(row.get('slope', 0.))) <= math.tan(math.radians(25.)))

    def shot_committed(self, event, pending):
        if self.shot_receipts.get(event.get('projectile_id')) is not None:
            return
        self.shot_commits += 1
        handed_over = False
        if (self.handover_burst is not None and pending.get('player_burst') is self.handover_burst):
            if self.owner._local_player_burst is self.handover_burst:
                self.owner._cancel_local_player_burst()
                self.owner._rescale_current_reload(self.owner._gun_state,pending['reload_factor'])
            self.handover_burst = None
            handed_over = True
        burst = pending.get('player_burst')
        context = pending.get('player_control') or self.trigger_context
        if context is None and burst is not None:
            context = burst.get('player_control')
        if context is not None:
            self.emit_shot(self.shot_receipts.committed(event, pending, context,
                self.owner._clock(), self.control_generation))
            self.automatic_commits += 1
            context.setdefault('projectiles', []).append(event.get('projectile_id'))
            if burst is not None:
                burst['player_control'] = context
                self.owned_burst = burst
            policy = context['policy']
            if policy is not None:
                policy.launch(str(event['projectile_id']), int(event['shell_index']),
                    context['target'], self.owner._clock(),
                    position=(pending.get('x'), pending.get('y'), pending.get('z'))
                        if pending.get('x') is not None else tuple(self.owner.local_pose()[0]),
                    group=pending.get('burst_group_seq'), count=pending.get('burst_count', 1),
                    clip_remaining=self.owner._gun_state.clip)
                if burst is not None and (handed_over or burst is not self.owner._local_player_burst):
                    policy.close_group(burst.get('group_seq'), burst.get('committed', 0))
                    self.owned_burst = None
            if self.weapon is not None:
                self.weapon.fired = True
                self.weapon.committed += 1
            self.record('shot_committed', projectile=event['projectile_id'], shell=event['shell_index'])
            finished = burst is None or burst.get('committed', 0) >= burst.get('count', 1)
            if context['command'] is not None and finished:
                self.gateway.finish(context['command'], 'completed', 'shot_committed',
                    self.owner._clock(), dict(projectile_id=event.get('projectile_id'),
                    projectile_ids=list(context['projectiles']), shell_index=event.get('shell_index'),
                    burst_group=pending.get('burst_group_seq'), burst_count=pending.get('burst_count', 1),
                    stage='local_committed'))
                self.fire_command = None

    def emit_shot(self, receipt):
        if receipt is not None:
            self.emit_result(dict(self.identity(), **receipt))

    def shot_hit(self, event):
        known = self.shot_receipts.get(event.get('projectile_id')) is not None
        receipt = self.shot_receipts.hit(event, self.owner._clock())
        if known and receipt is None:
            return
        policies = self.retired_policies + ([self.ammo_policy] if self.ammo_policy is not None else [])
        for policy in policies:
            policy.hit(event)
        if policies:
            self.record('combat_receipt', projectile=event.get('projectile_id'),
                        damage=event.get('damage'), penetrated=event.get('shot_result') == 2)
        self.emit_shot(receipt)

    def shot_terminal(self, event):
        policies = self.retired_policies + ([self.ammo_policy] if self.ammo_policy is not None else [])
        for policy in policies:
            policy.terminal(event, self.owner._clock())
        self.emit_shot(self.shot_receipts.terminal(event, self.owner._clock()))

    def select_ammo(self, now):
        gun, policy = self.owner._gun_state, self.ammo_policy
        if policy is None:
            return
        for row in policy.settle(gun.ammo, now):
            self.record('shot_result', result=row, failures=policy.failures, desired=policy.desired)
        if self.direct_engagement is None:
            selected = policy.choose(gun.ammo)
            if not policy.protected:
                self.queue_automatic_shell(selected)

    def queue_automatic_shell(self, selected):
        from ..gun_mechanics import _field
        owner = self.owner
        gun = owner._gun_state
        if (owner._local_fire_intent is not None or
                (self.direct_engagement is not None and getattr(owner, '_local_player_burst', None))):
            return
        if (selected != gun.shot_index and
                (self.direct_engagement is not None or selected != gun.pending_index)):
            settings = owner._runtime.constants.VEHICLE_SETTING
            # Direct fire can have no legal shot with the current magazine.
            # Request the native immediate reload instead of waiting to empty it.
            code = (settings.CURRENT_SHELLS if self.direct_engagement is not None or
                    gun.clip_size <= 1 or gun.clip <= 0 else settings.NEXT_SHELLS)
            if self.direct_engagement is not None:
                now = owner._clock()
                previous = self.last_shell_request
                if previous is not None and previous[0] is gun and 0. <= now - previous[1] < .35:
                    return
                self.last_shell_request = (gun, now)
            compact = _field(_field(gun.shots[selected], 'shell'), 'compactDescr')
            current = _field(_field(gun.shots[gun.shot_index], 'shell'), 'compactDescr')
            if compact != current:
                owner.change_vehicle_setting(code, compact)
                self.record('ammo_queued', shell=selected)

    def _queue_next_shell(self, gun, selected):
        from ..gun_mechanics import _field
        owner = self.owner
        if (gun.clip <= 0 or gun.ammo[selected] <= 0 or
                getattr(owner, '_local_fire_intent', None) or
                getattr(owner, '_local_player_burst', None)):
            return False
        queued = gun.pending_index if gun.pending_index is not None else gun.shot_index
        if queued == selected:
            return False
        settings = owner._runtime.constants.VEHICLE_SETTING
        compact = _field(_field(gun.shots[selected], 'shell'), 'compactDescr')
        return owner.change_vehicle_setting(settings.NEXT_SHELLS, compact)

    def queue_next_automatic_clip(self, selected):
        gun = self.owner._gun_state
        if gun.clip_size > 1:
            self._queue_next_shell(gun, selected)

    def queue_next_automatic_round(self, selected):
        gun = self.owner._gun_state
        if gun is None or gun.clip_size > 1:
            self.next_round_request = None
            return
        queued = getattr(gun, 'pending_index', None)
        owned = queued is not None and self.next_round_request == (gun, queued)
        if not owned:
            self.next_round_request = None
            if queued is not None:
                # An explicit player's next-shell selection takes precedence.
                return
        if selected is None:
            if owned and self._queue_next_shell(gun, gun.shot_index):
                self.next_round_request = None
            return
        if self._queue_next_shell(gun, selected):
            self.next_round_request = (gun, selected)
            self.record('ammo_next', shell=selected, loaded=gun.shot_index)

    def reload_automatic_clip(self, selected):
        owner, gun = self.owner, self.owner._gun_state
        generation = self.control_generation
        if gun.ammo[selected] <= 0:
            return False
        self.queue_next_automatic_clip(selected)
        if (not self.active or self.control_generation != generation or owner._gun_state is not gun or
                gun.clip <= 0 or getattr(owner, '_local_player_burst', None) or
                getattr(owner, '_local_fire_intent', None)):
            return False
        settings = owner._runtime.constants.VEHICLE_SETTING
        return owner.change_vehicle_setting(settings.RELOAD_PARTIAL_CLIP, 0)

    def consumables(self, entity):
        # Player-owned activation decisions, actual mounted kits/cooldowns.
        from ..equipment_mechanics import BOT_REPAIR_PRIORITY, BOT_CREW_PRIORITY
        owner = self.owner
        generation, control_identity, active = self.control_generation, self.identity(), self.active
        client, server, descriptor = owner.client, owner._server, entity.typeDescriptor
        mounted, features = owner._equipment_state, set(self.features)

        def current():
            # A native activation/extra lookup can synchronously dispatch Stop
            # or replace this vehicle's mounted state. Only the call already
            # admitted may finish; another item cannot inherit its old view.
            return bool(not self.closed and self.owner is owner and self.active == active and
                self.control_generation == generation and self.identity() == control_identity and
                self.features == features and owner.client is client and owner._server is server and
                server is not None and owner._server_entity(server.vehicle_id) is entity and
                entity.typeDescriptor is descriptor and owner._equipment_state is mounted)

        if not current():
            return
        record = owner._records.get('player:%s' % owner.client.player_id) or {}
        critical = record.get('critical_state') or (record.get('state') or {}).get('critical') or {}
        states = dict((r['name'], r['state']) for r in critical.get('devices', ()))
        states.update((name, 'destroyed') for name in critical.get('destroyed', ()))
        # Share the immutable reviewed priorities, never a Bot policy instance.
        repair = next((name for name, severity in BOT_REPAIR_PRIORITY
                       if states.get(name) == severity), None)
        crew = next((name for name in BOT_CREW_PRIORITY
                     if name in critical.get('crew_ko', ())), None)
        now = owner._clock()
        stun_end = (record.get('state') or {}).get('stun_end_server_time_ms', 0)
        estimated_time = owner._projectile_estimated_server_time(now) if stun_end else None
        stunned = estimated_time is not None and stun_end > estimated_time
        for item in mounted or ():
            if not current():
                return
            kind = item.contract.get('kind')
            if item.contract.get('autoactivate'):
                continue
            if kind == 'rpm_limiter':
                from ..vehicle_physics import suspension_drive_pitch
                unused, yaw = owner.local_pose()
                pitch = suspension_drive_pitch(getattr(owner, '_local_ground_plane', None), yaw)
                wanted = self.governor.wanted(now, owner._local_speed, pitch,
                    not owner._local_airborne and not owner._local_support_rise_blocked,
                    states.get('engineHealth') in ('critical', 'destroyed'),
                    self.last_order.get('wreck_push'))
                # Snapshot restoration replaces EquipmentState instances. The
                # controller's round-scoped token follows the mounted item.
                identity = (item.contract['id'], item.contract.get('compactDescr'))
                owned = self.owned_governor == identity
                changed_intent = (owned and self.governor_request is not None and
                                  self.governor_request[1] != wanted)
                if ((wanted != item.active or changed_intent) and (owned or wanted) and
                        (changed_intent or now >= self.consumable_pending.get(item.contract['id'], 0))):
                    code = item.contract['id'] | (int(wanted) << 16)
                    if not current():
                        return
                    previous_owner = self.owned_governor
                    # Publish ownership before the native call. Stop must be
                    # able to cancel even an on-request whose call has not
                    # returned yet; its old stack must not resurrect the lease.
                    if wanted:
                        self.owned_governor = identity
                    self.governor_request = (identity, wanted)
                    self.consumable_pending[item.contract['id']] = now + 2.
                    requested = bool(owner._activate_equipment(code))
                    if not current():
                        return
                    if requested:
                        self.owned_governor = identity if wanted else None
                    else:
                        self.owned_governor = previous_owner
                    self.record('governor', wanted=wanted, requested=requested,
                                pitch=pitch, uphill_since=self.governor.uphill_since)
                continue
            selected = repair if kind == 'repairkit' else crew if kind == 'medkit' else None
            all_targets = bool(item.contract.get('repairAll'))
            needed = (selected is not None or (kind == 'extinguisher' and critical.get('fire')) or
                      (kind == 'medkit' and stunned))
            if needed and item.ready(now) and now >= self.consumable_pending.get(item.contract['id'], 0):
                # #1513 all-target kits and extinguishers use high word 1.
                # Only single-target kits encode a descriptor extra index.
                # Encoding the damaged track's index for a large kit is
                # rejected by the canonical equipment owner, not a cooldown.
                if all_targets or kind == 'extinguisher':
                    index = 1
                elif selected is not None:
                    index = owner._critical_extra_index(entity.typeDescriptor, selected)
                else:
                    # A small kit can clear stun with a healthy, real crew
                    # target. Its high word still needs an installed extra.
                    index = None
                    for name in ('commander',) + tuple(BOT_CREW_PRIORITY):
                        try:
                            index = owner._critical_extra_index(entity.typeDescriptor, name)
                            if not current():
                                return
                            selected = name
                            break
                        except RuntimeError:
                            if not current():
                                return
                    if index is None:
                        self.record('consumable_unavailable', equipment=item.contract['id'],
                                    reason='crew_activation_target_unavailable')
                        self.consumable_pending[item.contract['id']] = now + 2.
                        continue
                activation_code = item.contract['id'] | (index << 16)
                if not current():
                    return
                self.consumable_pending[item.contract['id']] = now+2.
                requested = bool(owner._activate_equipment(activation_code))
                if not current():
                    return
                self.record('consumable', equipment=item.contract['id'],
                            selected=None if all_targets else selected,
                            needed_target=selected, activation_code=activation_code,
                            requested=requested)

    def update_siege(self, entity, order, fire_clear, now):
        """Debounce the player's native travel/siege setting independently."""
        owner = self.owner
        if (getattr(self, '_siege_call_token', None) is not None or
                self.siege_observer is not None):
            return
        if not getattr(entity.typeDescriptor, 'hasSiegeMode', False):
            return
        if getattr(owner, '_local_player_burst', None) or owner._local_siege_pending is not None:
            return
        states = owner._runtime.constants.VEHICLE_SIEGE_STATE
        current = getattr(entity, 'siegeState', states.DISABLED)
        if current in (states.SWITCHING_ON, states.SWITCHING_OFF):
            return
        mission = order.get('mission') or {}
        desired = bool(fire_clear and not order.get('suppress_fire') and
            (order.get('combat_mode') in ('engage', 'support_hold') or order.get('holding')) and
            mission.get('status') not in ('failed', 'cancelled'))
        if self.siege_intent is None or self.siege_intent[0] != desired:
            self.siege_intent = (desired, now)
        since = self.siege_intent[1]
        if now - since < (.30 if desired else .80):
            return
        if (current == states.ENABLED) == desired or owner._local_siege_braking is not None:
            return
        generation, identity, active = self.control_generation, self.identity(), self.active
        client, server, descriptor = owner.client, owner._server, entity.typeDescriptor
        intent, features = self.siege_intent, set(self.features)
        token = object()
        self._siege_call_token = token
        outcome = {}

        def retire():
            if self.siege_observer is observer:
                self.siege_observer = self.siege_brake = None
                self._run_releases([('automatic_siege_release',
                    lambda:owner._cancel_player_control_siege(observer))], now)

        def observer(sequence, enabled, reason=None):
            outcome.update(sequence=sequence, reason=reason)
            # Once submitted, the native pending transition owns its lock.
            # Token-specific cleanup cannot undo it or another request.
            retire()

        # Publish the exact callback before native code can notify the prior
        # observer. A Stop there must revoke this new request before the
        # runtime installs its braking flag, not just after the call returns.
        self.siege_observer = observer
        self.siege_brake = desired
        try:
            requested = owner._request_player_control_siege(desired, observer)
            retained = bool(not self.closed and self.owner is owner and self.active == active and
                self.control_generation == generation and self.identity() == identity and
                owner.client is client and owner._server is server and server is not None and
                owner._server_entity(server.vehicle_id) is entity and
                entity.typeDescriptor is descriptor and self.siege_intent is intent and
                self.features == features)
            if not retained or not requested:
                retire()
                return
            if self.siege_observer is observer:
                self.siege_brake = owner._local_siege_braking
            if self.siege_observer is observer or outcome.get('sequence') is not None:
                self.record('siege_request', enabled=desired, previous=current)
        except Exception:
            retire()
            raise
        finally:
            if self._siege_call_token is token:
                self._siege_call_token = None

    def update(self, dt, now):
        if self.closed:
            return
        if not self.live():
            self.stop('battle_not_live')
            self.retry_releases(now)
            # Lifecycle acknowledgements remain available after death/result.
            # Admission rejects gameplay actions before any native mutation.
            self.poll_commands(now)
            self.publish_status(now, reason='battle_not_live')
            return
        self.bind_input()
        self.test_actions.update(now)
        self.manual_aim.update(now)
        self.native_actions.update(now)
        self.poll_commands(now)
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            self.stop('player_dead')
            self.publish_status(now, reason='player_dead')
            return
        sender = owner._sender
        self.retry_releases(now)
        from .capabilities import ammunition_state
        previous_ammo = self.ammo_state
        self.ammo_state = ammunition_state(owner._gun_state)
        for policy in list(self.retired_policies):
            policy.settle(owner._gun_state.ammo if self.ammo_state['available'] else [], now)
            if policy.idle:
                self.retired_policies.remove(policy)
        if self.ammo_state['state'] != previous_ammo['state']:
            self.record('ammunition_state', previous=previous_ammo, current=self.ammo_state)
            if self.ammo_state['empty']:
                self.target_engine = None
                if self.navigation is not None:
                    self.navigation.cover_move = self.navigation.firing_move = None
                if getattr(self, 'aiming', None) is not None:
                    self.aiming.reset()
            self.next_status = 0.
        if self.halted:
            sender.forward = sender.turn = 0.
            sender.handbrake = True
            sender.send_current()
            settled = self.halt_observation.observe(owner, now, bool(self.release_pending))
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
        if not self.active or now < self.next_decision:
            self.publish_status(now)
            return
        decision_horizon = max(.1, float(dt),
            max(0., now - self.last_decision) if self.last_decision is not None else .1)
        self.last_decision = now
        self.next_decision = now+.1
        if self.direct_engagement is not None:
            self.fire_admission.lane.begin(now)
        decision_generation = self.control_generation
        decision_identity = self.identity()
        decision_navigation, decision_weapon = self.navigation, self.weapon
        decision_aiming, decision_policy = self.aiming, self.ammo_policy
        decision_server, decision_client = owner._server, owner.client
        decision_gun = owner._gun_state
        decision_features = set(self.features)
        decision_mission = self.mission_command

        def decision_current():
            # Every native query/source setter can synchronously dispatch a
            # Stop, a new command, a siege descriptor or another round. Native
            # observations may finish, but the retired decision cannot publish
            # old movement, fire, or equipment intents afterwards.
            if not self.active or self.control_generation != decision_generation or not self.live():
                return False
            server = getattr(owner, '_server', None)
            actual = (owner._server_entity(server.vehicle_id)
                      if server is decision_server and server is not None else None)
            return bool(self.active and not self.closed and self.control_generation == decision_generation and
                self.owner is owner and self.identity() == decision_identity and actual is entity and
                owner._sender is sender and owner.client is decision_client and owner._server is decision_server and
                owner._gun_state is decision_gun and self.features == decision_features and
                self.mission_command == decision_mission and
                self.navigation is decision_navigation and self.weapon is decision_weapon and
                self.aiming is decision_aiming and self.ammo_policy is decision_policy)

        position, yaw = owner.local_pose()
        position = tuple(position)
        contacts, neighbours, records = self._contacts(entity)
        shape = owner._collision_shape(entity.typeDescriptor)
        if not decision_current():
            return
        previous_target = self.target_engine
        target = None
        fire_clear = False
        solution = None
        candidates = []
        aim_progress = False
        fire_ready = False
        artillery = 'SPG' in getattr(getattr(entity.typeDescriptor, 'type', None), 'tags', ())
        if 'fire' in self.features and self.ammo_state['available'] and not self.ammo_state['empty']:
            base = (owner._rules_state.get('bases') or {}).get(str(owner.client.team), {})
            mission = self.navigation.mission_status() if self.navigation is not None else None
            home = self.navigation.home if self.navigation is not None else None
            direct = self.direct_engagement
            if (direct is not None and self.fire_admission.front_contact is not None and
                    not getattr(owner, '_local_player_burst', None) and
                    not getattr(owner, '_local_fire_intent', None)):
                rear, front_id, rejected, at = self.fire_admission.front_contact
                self.fire_admission.front_contact = None
                front = records.get(front_id)
                if (direct.target == rear.id and records.get(rear.id) is rear
                        and front is not None and 0. <= now-at <= 1.):
                    self.engagement_hold = None
                    self.aiming.defer_front_point(rear, front, rejected)
                    direct.adopt(front_id)
                    self.front_priority = front_id
            locked = direct.target if direct is not None else self.target_engine
            if self.front_priority != locked or locked not in records:
                self.front_priority = None
            ranked, preempt = self.target_selection.rank(contacts, position, locked,
                now, home=home, base=base, mission=mission)
            priorities = dict((identity, index) for index, identity in enumerate(ranked))
            candidates = sorted(records.values(), key=lambda item: (
                priorities.get(item.id, len(priorities)), item.id != locked,
                sum((item.position[i]-position[i])**2 for i in (0, 2))))
            if (preempt and self.front_priority is None and candidates and self.direct_engagement is not None and
                    not getattr(owner, '_local_player_burst', None) and
                    not getattr(owner, '_local_fire_intent', None)):
                if self.direct_engagement.search_since is None:
                    self.direct_engagement.adopt(candidates[0].id)
            self.aiming.begin(list(records.values()), now)
            if not decision_current():
                return
            if self.direct_engagement is not None:
                generation = self.control_generation
                target, solution, fire_clear = self.direct_engagement.update(self, candidates, now)
                if generation != self.control_generation or not decision_current():
                    return
            else:
                for candidate in candidates:
                    trial = self.aiming.update(candidate, now,
                        lambda a, b: self.lane_from(candidate, a, b), artillery=artillery)
                    if not decision_current():
                        return
                    if target is None:
                        target, solution = candidate, trial
                    elif trial.get('geometry_clear') and not solution.get('geometry_clear'):
                        target, solution = candidate, trial
                    if trial.get('clear') and trial.get('reachable'):
                        target, solution = candidate, trial
                        break
                fire_clear = bool(solution and solution.get('clear') and solution.get('reachable'))
        engagement = self.direct_engagement
        settling_aim = bool(engagement is not None and
            (getattr(engagement, 'checking', False) or getattr(engagement, 'laying_until', None)
             is not None or solution and solution.get('laying') or
             self.fire_admission.receipt.get('reason') in (
                 'auto_lane_pending', 'auto_lane_geometry_unavailable')
             and target is not None and target.id == engagement.target)
            and not getattr(engagement, 'seek', False) and not getattr(engagement, 'retreat', False))
        tactical_clear = bool(solution and solution.get('geometry_clear'))
        if self.ammo_policy is not None:
            self.ammo_policy.context(position, self.direct_engagement.target
                if self.direct_engagement is not None else target.id if target is not None else None)
        if 'fire' in self.features and self.ammo_state['available']:
            previous_shell = owner._gun_state.shot_index
            self.select_ammo(now)
            if not decision_current():
                return
            if previous_shell != owner._gun_state.shot_index:
                # Ballistic and armor proofs belong to one mounted shell.
                fire_clear = False
                tactical_clear = False
                self.aiming.reset()
        self.aim_receipt = None
        aim_command = 'unchanged'
        from ..gun_mechanics import _field
        if target is not None:
            self.no_aim_since = None
            from .weapon import barrel_aligned
            self.target_engine = target.id
            point = solution['point']
            if (not getattr(engagement, 'locked_wait', False) and
                    (engagement is None or fire_clear or solution.get('laying'))):
                self.weapon.aim_solution(target.id, solution, now)
                aim_command = 'track'
                if not decision_current():
                    return
            start, direction = owner._mutable_shot_ray()
            distance = math.sqrt(sum((point[i]-start[i])**2 for i in range(3)))
            gun = owner._gun_state
            shot = gun.shots[gun.shot_index]
            aligned = barrel_aligned(start,direction,float(_field(shot,'speed')),
                float(_field(shot,'gravity')),point,max(.3,owner._collision_shape(target.typeDescriptor)[0]*.5))
            base = gun.base_dispersion*owner._local_stat_factor(entity, 'dispersion')
            factor = owner._native_dispersion_angle()/base if base > 0 else float('inf')
            previous_aim = getattr(self, 'aim_progress_sample', None)
            ray = solution.get('direction') or tuple(point[i] - start[i] for i in range(3))
            length = math.sqrt(sum(v*v for v in ray))
            error = (math.acos(max(-1., min(1., sum(ray[i]*direction[i] for i in range(3))/length)))
                     if length > 0. else 0.)
            aim_progress = (previous_aim is None or previous_aim[0] != target.id or
                            error < previous_aim[1] - .002 or factor < previous_aim[2] - .02)
            self.aim_progress_sample = (target.id, error, factor)
            if not decision_current():
                return
            self.aim_receipt = dict(target=target.id, point=point, aligned=aligned, distance=distance,
                                    fire_clear=fire_clear, reason=solution.get('reason'),
                                    geometry_clear=tactical_clear, needs_hull=solution.get('needs_hull'),
                                    reachable=solution.get('reachable'), arc=solution.get('arc'),
                                    velocity=solution.get('velocity'), progress=aim_progress,
                                    needs_hydraulic=solution.get('needs_hydraulic'),
                                    selection=self.target_selection.receipt,
                                    client_mode=owner._avatar.gunRotator.clientMode)
            fire_ready = (fire_clear and aligned and gun.can_fire(True) and
                          self.weapon.ready(now, factor))
        else:
            self.target_engine = None
            self.aim_progress_sample = None
            if self.no_aim_since is None:
                self.no_aim_since = now
            aim_idle = (self.direct_engagement is None or
                        self.direct_engagement.target is None or now - self.no_aim_since >= 1.5)
            if ('fire' in self.features and self.weapon is not None and aim_idle and not settling_aim and
                    not getattr(owner, '_local_fire_intent', None) and
                    not getattr(owner, '_local_player_burst', None)):
                self.weapon.forward(position,yaw,max(.5,(shape[2]+shape[3])*.5))
                aim_command = 'forward'
                if not decision_current():
                    return
                self.aim_receipt = dict(mode='forward',point=self.weapon.point,
                    client_mode=owner._avatar.gunRotator.clientMode)
        if previous_target != self.target_engine:
            self.record('aim_transition', previous=previous_target,
                        target=self.target_engine,
                        reason=('clear_lane_selected' if self.target_engine is not None else
                                'previous_not_visible_alive' if previous_target not in records else
                                'no_clear_firing_lane'),
                        position=position, yaw=yaw, aim=self.aim_receipt)
        if 'drive' in self.features and self.navigation is not None:
            from .traffic import Traffic, body
            from .navigation import PlayerNavigation
            peers = [r for r in neighbours if r['team']==int(owner.client.team) or r.get('visible') or not r['alive']]
            traffic = Traffic(body(entity.id,position,yaw,shape,
                getattr(owner,'_local_pitch',0.),getattr(owner,'_local_roll',0.)),peers)
            state = dict(id=owner.client.player_id, engine_id=entity.id,
                         actor_key=('player', int(owner.client.player_id)), position=position, yaw=yaw,
                         speed=owner._local_speed, now=now, half_length=shape[1], half_width=shape[0],
                         health=entity.health, max_health=entity.typeDescriptor.maxHealth,
                         collision_shape=shape, pitch=getattr(owner, '_local_pitch', 0.),
                         roll=getattr(owner, '_local_roll', 0.),
                         decision_horizon=decision_horizon,
                         burst_active=bool(getattr(owner, '_local_player_burst', None)))
            from .traffic_laws import traffic_stopping_distance
            def stopping_distance(turn=False):
                params = getattr(owner, '_local_physics', None)
                if params is None:
                    return 0.
                return traffic_stopping_distance(params, state['speed'],
                    getattr(owner, '_local_smooth_drive_pitch', getattr(owner, '_local_pitch', 0.)),
                    bool(turn))
            state['stopping_distance'] = stopping_distance()
            blocked_corridors = []
            def clear(angle, reach=None):
                if not traffic.clear(angle, reach or 5.):
                    return False
                if self.direction_clear(position, angle, entity.typeDescriptor, shape, reach):
                    return True
                probe = self.probe_receipt or {}
                if any(probe.get(key) for key in ('collision', 'water', 'cliff')):
                    blocked_corridors.append(angle)
                return False
            base = (owner._rules_state.get('bases') or {}).get(str(owner.client.team), {})
            enemy_base = (owner._rules_state.get('bases') or {}).get(str(3 - int(owner.client.team)), {})
            allies = [r for r in peers if r['team'] == int(owner.client.team)]
            allies.append(dict(id=entity.id, actor_key=state['actor_key'],
                               alive=True, class_tag=self.navigation.tag,
                               position=position, health=entity.health,
                               max_health=entity.typeDescriptor.maxHealth))
            from .observations import public_allies
            roster, roster_complete = public_allies(owner, allies)
            turret_reader = getattr(owner, '_turret_navigation_hulls', None)
            turret_hulls = tuple(turret_reader()) if callable(turret_reader) else ()
            blocked_target = records.get(self.blocked_fire_target) if not artillery else None
            if target is not None and blocked_target is not target:
                blocked_target = None
            elif target is None and (self.direct_engagement is None or
                    self.direct_engagement.target != self.blocked_fire_target):
                blocked_target = None
            final_blocked = blocked_target is not None
            seeking = bool(getattr(engagement, 'seek', False))
            gun = owner._gun_state
            direct_reload = (engagement is not None and gun.clip_size > 1 and
                             gun.clip <= 0 and gun.reload_time > 0.)
            facing_target = records.get(engagement.target) if engagement is not None else None
            facing_key = None
            if (facing_target is not None and getattr(engagement, 'sample', None) is not None
                    and not (seeking or getattr(engagement, 'retreat', False) or direct_reload or
                             self.ammo_state['empty'])):
                facing_key = (facing_target.id, engagement.sample, gun.shot_index)
            if final_blocked and self.confirmed_facing.owns_hold(facing_key):
                engagement.interrupt_pivot(gun.shot_index, engagement.sample, 'unavailable')
                self.blocked_fire_target = self.blocked_fire_sample = None
                facing_key = None
                fire_clear = tactical_clear = fire_ready = False
            elif final_blocked:
                facing_key = None
            pivot_hold = (self.confirmed_facing.owns_hold(facing_key) or
                          getattr(engagement, 'pivot_search', None) is not None)
            locked_wait = (getattr(engagement, 'locked_wait', False) and not final_blocked
                and not self.ammo_state['empty'] and self.last_order.get('holding')
                and self.last_order.get('combat_mode') in ('engage', 'support_hold', 'base_capture'))
            protected_hold = pivot_hold or locked_wait
            established = self.engagement_hold
            retain_hold = bool(established is not None and engagement is not None and
                records.get(engagement.target) is established[0] and
                (target is None or target is established[0]) and now < established[1] and
                settling_aim and not final_blocked and not self.ammo_state['empty'])
            context = dict(empty_ammo=self.ammo_state['empty'],
                target=target, contacts=contacts, allies=roster, neighbours=peers,
                base=base, enemy_base=enemy_base,
                allies_complete=roster_complete, turret_hulls=turret_hulls,
                burst_active=state['burst_active'],
                fire_clear=tactical_clear and not (final_blocked or seeking),
                aligned=bool(self.aim_receipt and self.aim_receipt.get('aligned')
                    and solution and solution.get('reachable')),
                pivot_hold=protected_hold,
                gun_ready=self.ammo_state['can_fire'], fire_seq=self.automatic_commits,
                fire_failure=self.last_fire_failure, aim_progress=aim_progress,
                battle_finished=False, supported=not getattr(owner, '_local_airborne', False)
                    and not getattr(owner, '_local_support_rise_blocked', False),
                overturned=bool(getattr(owner, '_overturn_level', 0)))
            self.navigation.set_context(context)
            movement = self.navigation.movement_policy(state)
            if not decision_current():
                return
            hold = bool(not self.ammo_state['empty'] and not movement.get('force_move') and
                target is not None and tactical_clear and not (final_blocked or seeking) and
                (artillery or movement.get('combat_hold',
                    self.aim_receipt['distance'] <= movement.get('engage_range', 150.))))
            retain_hold = bool((retain_hold or protected_hold) and not movement.get('force_move') and
                               movement.get('allow_firing_position', True))
            hold = hold or retain_hold
            if not protected_hold and now >= self.next_strategy and movement.get('allow_strategy'):
                self.next_strategy=now+1.
                previous_mode = self.strategy.mode
                redirect=self.strategy.decide(now,self.navigation.routes,self.navigation.route,
                    contacts, allies, base, self.navigation.home, engaged=hold,
                    mission=self.navigation.mission_status(), empty_ammo=self.ammo_state['empty'], state=state)
                if redirect is not None:
                    reason = ('rejoin_after_defence' if previous_mode == 'defend' and
                              self.strategy.mode != 'defend' else self.strategy.mode)
                    self.navigation.retask(redirect, reason=reason)
                    if not decision_current():
                        return
                    self.record('player_strategy',decision=self.strategy.receipt)
            automatic_defence = self.strategy.mode == 'defend' and movement.get('allow_strategy')
            if automatic_defence and self.navigation.home is not None:
                retain_hold = False
                home=self.navigation.home
                # A distant incidental target cannot pin the defender on the
                # wrong side of the map. Fire may continue while returning.
                hold=bool(not self.ammo_state['empty'] and not movement.get('force_move') and
                    tactical_clear and not (final_blocked or seeking) and target is not None and math.hypot(
                    target.position[0]-home[0],target.position[2]-home[1])<100. and
                    self.aim_receipt['distance']<=150.)
            position_goal = None
            withdrawal = None
            manoeuvre = None
            if isinstance(self.navigation, PlayerNavigation):
                if (self.direct_engagement is not None and movement.get('allow_withdrawal') and
                        (self.direct_engagement.retreat or direct_reload)):
                    reason = 'magazine_reload' if direct_reload else 'no_he'
                    withdrawal = self.navigation.ammo_withdrawal(
                        state, clear, contacts, owner._tactical_ray_clear, reason)
                    if not decision_current():
                        return
                elif ('fire' in self.features and not self.ammo_state['empty'] and
                        movement.get('allow_withdrawal') and not automatic_defence and not retain_hold and
                        (target is not None or self.navigation.cover_move is not None or
                         self.navigation.reload_route is not None)):
                    withdrawal = self.navigation.withdrawal(
                        state, target or (candidates[0] if candidates else None), entity, owner._gun_state, clear, owner._tactical_ray_clear)
                    if not decision_current():
                        return
                else:
                    self.navigation.cover_move = None
                    self.navigation.reload_route = None
                    cover_search = getattr(self.navigation, 'cover_search', None)
                    if cover_search is not None:
                        cover_search.reset()
                if self.direct_engagement is not None and not (self.direct_engagement.retreat or direct_reload):
                    self.navigation.ammo_retreat = None
                if ('fire' in self.features and not self.ammo_state['empty'] and
                        movement.get('allow_firing_position') and (not tactical_clear or final_blocked or seeking)
                        and (final_blocked or candidates) and not automatic_defence and not retain_hold
                        and withdrawal is None):
                    def firing_lane_from(candidate, start):
                        end = point if final_blocked and target is not None else self.target_point(candidate)
                        return (self.lane_from(candidate, start, end) and
                                (not final_blocked or self.direct_engagement is not None or
                                 self.dynamic_path_clear(candidate, (start, end))))
                    position_goal = self.navigation.firing_position(
                        state, blocked_target if final_blocked else records.get(
                            getattr(self.direct_engagement, 'target', None), candidates[0]), clear,
                        firing_lane_from, owner._mutable_shot_ray()[0])
                    if not decision_current():
                        return
                if position_goal is None:
                    self.navigation.firing_move = None
                manoeuvre = self.combat_tactics.movement(state, context, entity.typeDescriptor,
                    allowed=bool(movement.get('allow_firing_position') and not automatic_defence and
                        not retain_hold and withdrawal is None and position_goal is None),
                    height=self.navigation._height, clear=clear)
                if not decision_current():
                    return
            if withdrawal is not None:
                hold = False
                order = dict(withdrawal)
                order.setdefault('recovery_mode', withdrawal['combat_mode'])
            elif manoeuvre is not None:
                hold = False
                order = self.navigation.drive_combat_goal(state, clear, manoeuvre['goal'],
                    mode=manoeuvre['phase'], key=('player_flank', manoeuvre['target']))
            elif position_goal is None:
                if retain_hold and isinstance(self.navigation, PlayerNavigation):
                    self.navigation.context['retain_engagement_hold'] = True
                order = self.navigation.decide(state, clear, hold=hold)
            else:
                hold = False
                order = self.navigation.drive_to_firing_position(state, clear, position_goal)
            if not decision_current():
                return
            reverse_only = bool(order.get('reverse_only'))
            if protected_hold and order.get('holding') and order.get('combat_mode') in (
                    'engage', 'support_hold', 'base_capture'):
                order['traffic_hold_protected'] = True
                if engagement.pivot_search is not None:
                    order['pivot_point_search'] = True
            pushing = not reverse_only and self.wreck_push.apply(order,state,traffic,
                lambda heading, reach:self.direction_clear(position,heading,entity.typeDescriptor,shape,reach),
                pose_clear=lambda end_yaw:self.rotation_clear(entity,position,yaw,end_yaw))
            if not decision_current():
                return
            if not pushing:
                if not reverse_only:
                    self.turn_clearance.apply(order,yaw,traffic,position,clear)
                if not decision_current():
                    return
            mission_order = order.get('mission') or {}
            arrival = mission_order.get('arrival') or {}
            facing_allowed = (mission_order.get('status') not in ('failed', 'cancelled') and
                not (order.get('holding') and mission_order and not arrival.get('settled')) and
                not (order.get('holding') and order.get('artillery') and not mission_order and
                     order['artillery'].get('phase') != 'holding'))
            full_turret = (engagement is not None and not artillery and
                _field(_field(entity.typeDescriptor, 'gun'), 'turretYawLimits') is None)
            if not full_turret and hold and facing_allowed and target is not None:
                from .driving import angle
                dx = target.position[0] - position[0]
                dz = target.position[2] - position[2]
                delta = angle(math.atan2(dx, dz) - yaw) if math.hypot(dx, dz) > .1 else 0.
                from .weapon import hull_traverse_error
                traverse = hull_traverse_error(owner, entity.typeDescriptor, point, delta, solution=solution)
                if traverse is not None:
                    delta = traverse
                elif settling_aim or self.direct_engagement is not None and (
                        fire_clear or solution.get('reachable')):
                    delta = 0.
                else:
                    angled = self.combat_tactics.facing(state, target, entity.typeDescriptor)
                    if angled is not None:
                        delta = angled
                order['combat_facing'] = dict(target=target.id, error=delta, state='aligned',
                                              limited_traverse=traverse is not None)
                if abs(delta) > (.02 if traverse is not None else .20):
                    facing = order['combat_facing']
                    facing['state'] = 'braking'
                    if abs(state['speed']) <= 1.5:
                        turn = max(-1., min(1., delta / .5))
                        if (traffic.can_turn(turn) and self.direction_clear(
                                position, yaw + turn * .15, entity.typeDescriptor, shape, shape[1])):
                            order.update(turn=turn, throttle=0., brake=False,
                                         recovery_mode='combat_facing')
                            facing['state'] = 'turning'
                        else:
                            facing['state'] = 'blocked'
            order['wreck_push'] = self.wreck_push.receipt
            order['tactics'] = dict(self.combat_tactics.receipt)
            order['traffic'] = dict(traffic.receipt,peer_count=len(peers),
                wreck_count=sum(not r['alive'] for r in peers),
                blocked_queries=traffic.blocked_queries)
            if not pushing:
                if isinstance(self.navigation, PlayerNavigation):
                    failure, self.drive_failure = self.drive_failure, None
                    contact, self.drive_contact_receipt = self.drive_contact_receipt, None
                    if (order.get('travel_intent') and yaw in blocked_corridors and
                            (order['recovery_mode'] == 'blocked' or self.navigation.driver.replan)):
                        self.navigation.report_drive_blockage(
                            state['id'], order, position, yaw, now, dt)
                        if not decision_current():
                            return
                    self.player_traffic.apply(order, state, traffic, int(owner.client.team),
                        clear, lambda:stopping_distance(order['turn']), 1. / 30.,
                        not reverse_only and (self.navigation.driver.replan or failure is not None),
                        failure if not reverse_only else None, contact=contact if not reverse_only else None)
                    if not decision_current():
                        return
                if (order['throttle'] and order['turn'] and
                        not traffic.can_steer(order['throttle'], order['turn'], state['speed'])):
                    order.update(throttle=0., turn=0., brake=True, recovery_mode='traffic_yield')
            else:
                self.drive_failure = None
            parked_capture = (order.get('combat_mode') == 'base_capture' and
                order.get('holding') and arrival.get('inside') and
                mission_order.get('status') == 'running')
            if full_turret and parked_capture:
                order['capture_pivot_circle'] = (mission_order['goal'], mission_order['radius'])
            if (full_turret and facing_allowed and order.get('holding') and
                    not (pushing or reverse_only or order['throttle'] or order['turn']) and
                    context['supported'] and not context['overturned'] and
                    (parked_capture or order.get('combat_mode') in ('engage', 'support_hold'))):
                if facing_key is not None:
                    from .driving import angle
                    dx, dz = facing_target.position[0]-position[0], facing_target.position[2]-position[2]
                    delta = angle(math.atan2(dx, dz)-yaw) if math.hypot(dx, dz) > .1 else 0.
                    self.confirmed_facing.apply(order, state, facing_key, delta,
                        getattr(owner, '_local_turn_speed', 0.),
                        getattr(engagement, 'confirmed', None) == facing_key,
                        getattr(engagement, 'checking', False),
                        can_turn=not getattr(engagement, 'locked_wait', False))
                else:
                    self.confirmed_facing.reset()
            else:
                self.confirmed_facing.reset()
            if reverse_only and (order['throttle'] > 0. or order['turn']):
                order.update(throttle=0., turn=0., brake=True)
            if (not order.get('holding') and (order['throttle'] or order['turn']) and
                    getattr(entity.typeDescriptor, 'hasSiegeMode', False) and
                    entity.siegeState == owner._runtime.constants.VEHICLE_SIEGE_STATE.ENABLED):
                # A brief loss of the firing lane can select the route while
                # siege exit is still being debounced. Keep the tracks still
                # until travel mode owns movement.
                order.update(throttle=0., turn=0., brake=True,
                             recovery_mode='siege_wait_travel')
            if not decision_current():
                return
            self.last_order = order
            sender.forward, sender.turn = order['throttle'], order['turn']
            sender.handbrake = order['brake']
            sender.send_current()
            if not decision_current():
                return
            self.update_siege(entity, order, tactical_clear, now)
            if not decision_current():
                return
        else:
            order = {}
        if settling_aim and self.aim_receipt is not None:
            self.aim_receipt['settling'] = True
        if engagement is not None and order.get('holding') and order.get('combat_mode') in (
                'engage', 'support_hold'):
            if target is not None and fire_clear:
                self.engagement_hold = (target, now + 4.)
            elif not retain_hold:
                self.engagement_hold = None
        else:
            self.engagement_hold = None
        self.last_order = order
        self.finish_mission(now)
        if not decision_current():
            return
        mission_order = order.get('mission') or {}
        fire_allowed = (mission_order.get('status') not in ('failed', 'cancelled') and
                        not order.get('suppress_fire') and order.get('fire_allowed', True))
        if artillery and order.get('artillery') and not mission_order:
            fire_allowed = fire_allowed and order['artillery'].get('phase') not in (
                'deploying', 'relocating', 'sortie_return')
        if (self.blocked_fire_target not in records or
                target is not None and target.id != self.blocked_fire_target):
            self.blocked_fire_target = self.blocked_fire_sample = None
        if fire_ready and fire_allowed:
            # The physical trigger (including each native burst tail) now
            # owns the final current-barrel + frozen-scatter admission. A
            # second complete centre-ray proof here would reset its bounded
            # work and reintroduce the old 0.5-second trigger-only gate.
            if engagement is not None and owner._gun_state.clip_size <= 1:
                self.queue_next_automatic_round(getattr(engagement, 'next_shell', None))
                if not decision_current():
                    if self.next_round_request is not None:
                        self.queue_next_automatic_round(None)
                    return
            accepted = self.trigger(self.weapon, now)
            if not decision_current():
                return
            if not accepted and self.next_round_request is not None:
                self.queue_next_automatic_round(None)
                if not decision_current():
                    return
            admission = self.fire_admission.receipt
            if not artillery and admission.get('reason') in (
                    'auto_friendly_lane', 'auto_world_blocked', 'auto_friendly_splash'):
                if (self.blocked_fire_target != target.id and self.navigation is not None
                        and 'drive' in self.features):
                    self.navigation.firing_retry_at = 0.
                self.blocked_fire_target = target.id
                key = (target.id, owner._gun_state.shot_index, solution.get('key'))
                previous = self.blocked_fire_sample
                if previous is None or previous[0] != key or now - previous[2] > 1.5:
                    previous = (key, now, now)
                self.blocked_fire_sample = (key, previous[1], now)
                if (self.direct_engagement is not None and now - previous[1] >= .6 and
                        not getattr(owner, '_local_player_burst', None) and
                        not getattr(owner, '_local_fire_intent', None)):
                    self.aiming.defer_ordered_point(target, owner._gun_state.shot_index,
                        solution, now)
                    self.direct_engagement.last_solution = None
                    self.blocked_fire_sample = None
            elif accepted:
                self.blocked_fire_target = self.blocked_fire_sample = None
            self.record('automatic_fire', target=target.id, accepted=accepted,
                        admission=admission, native=self.weapon.trigger_receipt)
            if not decision_current():
                return
        if self.aiming is not None and self.aim_receipt is not None:
            self.aim_receipt['budget'] = dict(getattr(self.aiming, 'receipt', {}))
            self.aim_receipt['admission'] = dict(self.fire_admission.receipt)
            if isinstance(getattr(self.direct_engagement, 'stage', None), tuple):
                self.aim_receipt['engagement'] = dict(stage=self.direct_engagement.stage,
                    search_since=self.direct_engagement.search_since,
                    fallback=self.direct_engagement.fallback, retreat=self.direct_engagement.retreat)
        self.record_aim_decision(now, (position, yaw), aim_command, order, fire_ready, fire_allowed)
        if 'consumables' in self.features:
            self.consumables(entity)
        if now >= getattr(self, 'next_log', 0.):
            self.next_log = now+1.
            self.record('decision', position=position, yaw=yaw, speed=owner._local_speed,
                        throttle=sender.forward, turn=sender.turn, order=order,
                        entry=self.navigation.receipt if self.navigation else None,
                        aim=self.aim_receipt, probe=getattr(self, 'probe_receipt', None))
        self.publish_status(now)


def attach(owner):
    global _current
    raw = os.environ.get('WOT_OFFLINE_PLAYER_AUTOCONTROL', '0')
    if raw == '0' or owner._worker_mode or owner._replay_mode:
        return None
    if _current is not None:
        _current.close()
    _current = PlayerControl(owner, raw.split(','))
    if not owner._worker_mode and callable(getattr(owner, 'local_pose', None)):
        _current.opening_origin = tuple(owner.local_pose()[0])
    path = os.environ.get('WOT_OFFLINE_TEST_CONTROL_FILE')
    if path and os.path.isfile(path):
        _current.command_offset = os.path.getsize(path)
    _current.record('attached', features=sorted(_current.features), command_file=path,
                    implementation='foreground_independent_v3')
    _current.publish_status(owner._clock(), force=True, reason='attached')
    return _current
