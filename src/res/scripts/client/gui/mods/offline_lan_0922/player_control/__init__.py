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
        self.owner, self.features, self.notify = owner, set(features) & set(('drive', 'fire', 'consumables')), notify
        self.active = self.key_down = False
        self.navigation = self.weapon = self.ammo_policy = None
        self.aiming = None
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
        self.mission_command = self.drive_command = self.fire_command = self.halt_command = None
        self.last_fire_failure = None
        self.ammo_state = dict(state='unknown', empty=False, available=False)
        self.next_status = 0.
        self.observations = {}
        from .capabilities import Governor
        self.governor = Governor()
        self.owned_governor = None
        self.last_order = {}
        self.release_pending = []
        self.next_release = 0.
        self.siege_intent = None
        self.siege_brake = None
        from .wrecks import WreckPush
        self.wreck_push = WreckPush()
        from .commands import CommandGateway, JournalReader
        self.command_reader = JournalReader()
        self.gateway = CommandGateway(self.identity, self.emit_result,
            self.execute_command, self.command_preflight, self.cancel_command)

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
            self.record('result_write_failed', reason=str(error))
            return False

    def publish_status(self, now, force=False, reason=None):
        if not force and now < self.next_status:
            return
        self.next_status = now + 1.
        navigation = self.navigation
        mission = navigation.mission_status() if navigation is not None else None
        pose = None
        if self.live():
            position, yaw = self.owner.local_pose()
            pose = dict(position=tuple(position), yaw=yaw, speed=self.owner._local_speed)
        self.emit_result(dict(self.identity(), type='status', time=now, live=self.live(),
            reason=reason, active=self.active, halted=self.halted,
            features=sorted(self.features), mission=mission, ammo=self.ammo_state,
            pose=pose, aim=self.aim_receipt, last_command=self.gateway.last,
            release_pending=[stage for stage, unused in self.release_pending],
            navigation=(dict(entry=navigation.receipt, artillery=self.last_order.get('artillery'),
                             combat=self.last_order.get('combat')) if navigation is not None else None)))

    def owns_drive(self):
        return self.halted or self.override is not None or (self.active and 'drive' in self.features)

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
        if not self.live() or self.release_pending or not self.features:
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
        from .ammunition import mounted_shells
        gun = owner._gun_state
        shells = mounted_shells(entity.typeDescriptor, gun.shots)
        if not shells:
            return False
        if (self.override is not None or self.halted) and not self.stop('manual_takeover'):
            return False
        self.ammo_policy = Ammunition(shells, shells[0]['index'], gun.shot_index, gun.clip_size,
                                     artillery='SPG' in entity.typeDescriptor.type.tags)
        if gun.ammo[gun.shot_index] <= 0:
            self.ammo_policy.protected = False
        self.navigation = (navigation or PlayerNavigation(owner, entity.typeDescriptor)) if 'drive' in self.features else None
        self.strategy = Strategy()
        self.turn_clearance = TurnClearance()
        self.next_strategy = 0.
        self.weapon = Weapon(owner)
        if 'fire' in self.features:
            self.weapon.bind()
        self.active = True
        self.halted = False
        self.last_fire_failure = None
        from .aiming import Aiming
        self.aiming = Aiming(owner)
        self.last_decision = None
        self.next_decision = 0.0
        self.record('enabled', features=sorted(self.features), inventory=list(gun.ammo), shells=shells)
        self.notify(u'【测试】玩家自动控制已开启。')
        return True

    def stop(self, reason='manual'):
        changed = self.active or self.override is not None or self.halted
        drive_owned = self.owns_drive()
        owner = self.owner
        now = owner._clock() if callable(getattr(owner, '_clock', None)) else 0.
        for command_id in (self.mission_command, self.drive_command, self.fire_command, self.halt_command):
            if command_id is not None:
                self.gateway.finish(command_id, 'cancelled', reason, now)
        self.mission_command = self.drive_command = self.fire_command = self.halt_command = None
        self.active = False
        self.override = None
        self.halted = False
        self.target_engine = self.aim_receipt = self.aim_progress_sample = None
        self.last_order = {}
        callbacks = list(self.release_pending)
        self.release_pending = []
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
        burst = self.owned_burst
        if burst is not None:
            callbacks.append(('burst_release', lambda:self.release_burst(burst)))
        self.owned_burst = None
        if self.siege_brake is not None and owner._local_siege_braking == self.siege_brake:
            owner._local_siege_braking = None
        self.siege_intent = self.siege_brake = None
        from .wrecks import WreckPush
        self.wreck_push = WreckPush()
        if not any(stage == 'governor_release' for stage, unused in callbacks):
            callbacks.append(('governor_release', self.release_governor))
        for stage, callback in callbacks:
            try:
                callback()
            except Exception as error:
                self.release_pending.append((stage, callback))
                self.record('release_failed', resource=stage, reason=str(error))
        self.next_release = now + 1.
        if changed:
            self.record('disabled', reason=reason,
                        pending_release=[stage for stage, unused in self.release_pending])
            if self.live() and not self.release_pending:
                self.notify(u'【测试】玩家自动控制已关闭，恢复手动操作。')
        return not self.release_pending

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
        from .commands import MISSIONS
        action = command['action']
        if action in ('status', 'stop'):
            return None
        if self.release_pending and action != 'halt':
            return 'release_pending'
        if not self.live():
            return 'battle_not_live'
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            return 'player_dead'
        if action in MISSIONS and 'drive' not in self.features:
            return 'drive_disabled'
        if action == 'start' and not self.features:
            return 'no_enabled_features'
        if (action in MISSIONS or action == 'drive') and not command['replace']:
            if self.mission_command is not None or self.override is not None or self.halted:
                return 'movement_busy'
        if action == 'fire':
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
        from .commands import MISSIONS
        action, args, command_id = command['action'], command['args'], command['id']
        self.record('command', command=command)
        if action == 'status':
            self.publish_status(now, force=True)
            return dict(reason='status_published')
        if action == 'stop':
            released = self.stop('command_stop')
            reason = 'manual_control' if released else 'release_pending'
            self.publish_status(now, force=True, reason=reason)
            return dict(status='completed' if released else 'failed', reason=reason)
        if action == 'halt':
            self.stop('command_halt')
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
                self.stop('command_start')
            enabled = self.active or self.toggle()
            return dict(status='completed' if enabled else 'failed',
                        reason='active' if enabled else 'start_failed')
        if action == 'drive':
            # Validation and admission happened before this ownership change.
            self.stop('replaced_by_drive')
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
                        self.record('release_failed', resource='prepared_navigation', reason=str(error))
                return dict(status='failed', reason=receipt.get('reason', 'mission_unavailable'),
                            result=receipt)
            if self.override is not None or self.halted:
                self.stop('replaced_by_mission')
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
        if command['id'] in (self.mission_command, self.drive_command, self.halt_command):
            self.stop(reason)
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
        self.stop('battle_finished')
        self.publish_status(now, force=True, reason='battle_finished')

    def trigger(self, weapon, now, command_id=None):
        owner = self.owner
        if (getattr(owner, '_local_fire_intent', None) is not None or
                getattr(owner, '_local_player_burst', None) is not None):
            self.last_fire_failure = 'gun_busy'
            return False
        self.last_fire_failure = None
        self.trigger_context = dict(command=command_id, target=self.target_engine,
                                    policy=self.ammo_policy, time=now, projectiles=[])
        try:
            accepted = weapon.trigger()
            pending = getattr(owner, '_local_fire_intent', None)
            if accepted and isinstance(pending, dict):
                pending['player_control'] = self.trigger_context
                self.owned_burst = pending.get('player_burst')
            return accepted
        finally:
            self.trigger_context = None

    def fire_rejected(self, reason, projectile_id=None):
        self.last_fire_failure = str(reason)
        now = self.owner._clock()
        context = self.trigger_context
        if context is None and self.owned_burst is not None:
            context = self.owned_burst.get('player_control')
        if (projectile_id is not None and context is not None and
                projectile_id not in context.get('projectiles', ())):
            context = None
        if context and context['command'] is not None:
            self.gateway.finish(context['command'], 'failed', str(reason), now)
            self.fire_command = None
        if projectile_id is not None:
            self.emit_result(dict(self.identity(), type='shot', projectile_id=projectile_id,
                status='rejected', reason=str(reason), time=now))

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
        item = self.owned_governor
        if item is not None:
            # This also cancels our on-intent if its server echo is pending.
            self.owner._activate_equipment(item.contract['id'])
        self.owned_governor = None
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
            row = dict(id=target.id, team=team, position=point,
                       health=target.health, max_health=target.typeDescriptor.maxHealth,
                       alive=target.isAlive(), speed=0.0, yaw=float(target.matrix.yaw),
                       pitch=float(target.matrix.pitch), roll=float(target.matrix.roll),
                       collision_shape=owner._collision_shape(target.typeDescriptor))
            tags = target.typeDescriptor.type.tags
            row['class_tag'] = next((tag for tag in
                ('SPG', 'AT-SPG', 'heavyTank', 'mediumTank', 'lightTank') if tag in tags), 'mediumTank')
            neighbours.append(row)
            # Actual presentation visibility, not the omniscient LAN roster.
            if team in (1, 2) and team != int(owner.client.team) and row['alive'] and target.isStarted and record.get('spot_visible', False):
                row.update(visible=True)
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
                row['speed'] = math.sqrt(sum(v*v for v in velocity))
                self.observations[target.id] = (now, point)
                seen.add(target.id)
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
        if not path or len(path) < 2:
            return False
        segments = tuple(zip(path, path[1:]))
        for record in owner._records.values():
            if record.get('local') or record.get('tombstone') or not record.get('ready'):
                continue
            other = owner._server_entity(record.get('engine_id'))
            if other is None or other.id == target.id or not other.isStarted:
                continue
            state = record.get('state') or {}
            if other.isAlive() and int(state.get('team', 0)) != int(owner.client.team):
                continue
            names = ('chassis', 'hull', 'turret', 'gun') if turret_is_attached(other) else ('chassis', 'hull')
            for name in names:
                component = _component_value(other.typeDescriptor, name)
                tester = _component_value(component, 'hitTester')
                if _blast_bbox_bounds(_component_value(tester, 'bbox')) is None:
                    return False
            if record.get('native_remote'):
                body, chassis = owner._projectile_vehicle_matrices(record, other)
            else:
                body, chassis = other.matrix, None
            bounds = vehicle_target_bounds_at_matrix(
                other, body, owner._runtime.math, chassis_matrix=chassis)
            if bounds is None or any(segment_box_entry_distance(a, b, bounds) is not None
                                     for a, b in segments):
                return False
        debris = getattr(owner, '_detached_turret_obstacles', None)
        if debris is not None and debris.active():
            server_time = owner._turret_server_time_ms()
            if any(debris.target_entry_distance(a, b, server_time) is not None
                   for a, b in segments):
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

    def shot_hit(self, event):
        policies = self.retired_policies + ([self.ammo_policy] if self.ammo_policy is not None else [])
        for policy in policies:
            policy.hit(event)
        if policies:
            self.record('combat_receipt', projectile=event.get('projectile_id'),
                        damage=event.get('damage'), penetrated=event.get('shot_result') == 2)

    def shot_terminal(self, event):
        policies = self.retired_policies + ([self.ammo_policy] if self.ammo_policy is not None else [])
        for policy in policies:
            policy.terminal(event, self.owner._clock())
        if policies:
            self.emit_result(dict(self.identity(), type='shot',
                projectile_id=event.get('projectile_id'), status='terminal',
                hit_vehicle=event.get('hit_vehicle'), time=self.owner._clock()))

    def select_ammo(self, now):
        from ..gun_mechanics import _field
        gun, policy = self.owner._gun_state, self.ammo_policy
        if policy is None:
            return
        for row in policy.settle(gun.ammo, now):
            self.record('shot_result', result=row, failures=policy.failures, desired=policy.desired)
        if self.owner._local_fire_intent is not None:
            return
        selected = policy.choose(gun.ammo)
        if policy.protected:
            return
        if selected != gun.shot_index and selected != gun.pending_index:
            settings = self.owner._runtime.constants.VEHICLE_SETTING
            code = settings.CURRENT_SHELLS if gun.clip_size <= 1 or gun.clip <= 0 else settings.NEXT_SHELLS
            self.owner.change_vehicle_setting(code, _field(_field(gun.shots[selected], 'shell'), 'compactDescr'))
            self.record('ammo_queued', shell=selected)

    def consumables(self, entity):
        # Player-owned activation decisions, actual mounted kits/cooldowns.
        owner = self.owner
        record = owner._records.get('player:%s' % owner.client.player_id) or {}
        critical = record.get('critical_state') or (record.get('state') or {}).get('critical') or {}
        states = dict((r['name'], r['state']) for r in critical.get('devices', ()))
        states.update((name, 'destroyed') for name in critical.get('destroyed', ()))
        priorities = ('gunHealth', 'engineHealth', 'turretRotatorHealth', 'ammoBayHealth',
                      'leftTrackHealth', 'rightTrackHealth', 'surveyingDeviceHealth',
                      'fuelTankHealth', 'radioHealth')
        repair = next((n for n in priorities if states.get(n) in ('destroyed', 'critical')), None)
        crew = next((n for n in ('loader1', 'loader2', 'gunner1', 'gunner2', 'driver',
                    'commander', 'radioman1', 'radioman2') if n in critical.get('crew_ko', ())), None)
        now = owner._clock()
        stun_end = (record.get('state') or {}).get('stun_end_server_time_ms', 0)
        estimated_time = owner._projectile_estimated_server_time(now) if stun_end else None
        stunned = estimated_time is not None and stun_end > estimated_time
        for item in owner._equipment_state or ():
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
                # A governor enabled manually before handover is not ours to
                # disable. Only the instance that sent on may send off.
                owned = self.owned_governor is item
                if (wanted != item.active and (owned or wanted) and
                        now >= self.consumable_pending.get(item.contract['id'], 0)):
                    code = item.contract['id'] | (int(wanted) << 16)
                    requested = bool(owner._activate_equipment(code))
                    if requested:
                        self.owned_governor = item if wanted else None
                    self.consumable_pending[item.contract['id']] = now + 2.
                    self.record('governor', wanted=wanted, requested=requested,
                                pitch=pitch, uphill_since=self.governor.uphill_since)
                continue
            selected = repair if kind == 'repairkit' else crew if kind == 'medkit' else None
            all_targets = bool(item.contract.get('repairAll'))
            needed = (selected is not None or (kind == 'extinguisher' and critical.get('fire')) or
                      (kind == 'medkit' and all_targets and stunned))
            if needed and item.ready(now) and now >= self.consumable_pending.get(item.contract['id'], 0):
                # #1513 all-target kits and extinguishers use high word 1.
                # Only single-target kits encode a descriptor extra index.
                # Encoding the damaged track's index for a large kit is
                # rejected by the canonical equipment owner, not a cooldown.
                index = (1 if all_targets or kind == 'extinguisher' else
                         owner._critical_extra_index(entity.typeDescriptor, selected))
                activation_code = item.contract['id'] | (index << 16)
                requested = bool(owner._activate_equipment(activation_code))
                self.consumable_pending[item.contract['id']] = now+2.
                self.record('consumable', equipment=item.contract['id'],
                            selected=None if all_targets else selected,
                            needed_target=selected, activation_code=activation_code,
                            requested=requested)

    def update_siege(self, entity, order, fire_clear, now):
        """Debounce the player's native travel/siege setting independently."""
        owner = self.owner
        if not getattr(entity.typeDescriptor, 'hasSiegeMode', False):
            return
        if getattr(owner, '_local_player_burst', None) or owner._local_siege_pending is not None:
            return
        states = owner._runtime.constants.VEHICLE_SIEGE_STATE
        current = getattr(entity, 'siegeState', states.DISABLED)
        if current in (states.SWITCHING_ON, states.SWITCHING_OFF):
            return
        mission = order.get('mission') or {}
        desired = bool(fire_clear and
            (order.get('combat_mode') == 'engage' or order.get('holding')) and
            mission.get('status') not in ('failed', 'cancelled'))
        if self.siege_intent is None or self.siege_intent[0] != desired:
            self.siege_intent = (desired, now)
        since = self.siege_intent[1]
        if now - since < (.30 if desired else .80):
            return
        if (current == states.ENABLED) == desired or owner._local_siege_braking is not None:
            return
        setting = owner._runtime.constants.VEHICLE_SETTING.SIEGE_MODE_ENABLED
        if owner.change_vehicle_setting(setting, int(desired)):
            self.siege_brake = owner._local_siege_braking
            self.record('siege_request', enabled=desired, previous=current)

    def update(self, dt, now):
        if not self.live():
            self.stop('battle_not_live')
            self.publish_status(now, reason='battle_not_live')
            return
        self.bind_input()
        self.poll_commands(now)
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            self.stop('player_dead')
            self.publish_status(now, reason='player_dead')
            return
        sender = owner._sender
        if self.release_pending and not self.owns_drive() and now >= self.next_release:
            self.stop('release_retry')
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
            if self.halt_command is not None and abs(owner._local_speed) <= .2:
                self.gateway.finish(self.halt_command, 'completed', 'halted', now)
                self.halt_command = None
            self.publish_status(now)
            return
        if self.override is not None:
            until, forward, turn = self.override
            if now >= until:
                if self.drive_command is not None:
                    self.gateway.finish(self.drive_command, 'completed', 'drive_completed', now)
                    self.drive_command = None
                self.stop('script_completed')
            else:
                sender.forward, sender.turn, sender.handbrake = forward, turn, False
                sender.send_current()
            self.publish_status(now)
            return
        if not self.active or now < self.next_decision:
            self.publish_status(now)
            return
        self.next_decision = now+.1
        position, yaw = owner.local_pose()
        position = tuple(position)
        contacts, neighbours, records = self._contacts(entity)
        shape = owner._collision_shape(entity.typeDescriptor)
        previous_target = self.target_engine
        target = None
        fire_clear = False
        solution = None
        candidates = []
        aim_progress = False
        fire_ready = False
        artillery = 'SPG' in getattr(getattr(entity.typeDescriptor, 'type', None), 'tags', ())
        if 'fire' in self.features and self.ammo_state['available'] and not self.ammo_state['empty']:
            # Keep a valid current target instead of resetting aim every tick.
            candidates = sorted(records.values(), key=lambda item: (
                item.id != self.target_engine,
                sum((item.position[i]-position[i])**2 for i in (0, 2))))
            self.aiming.begin(list(records.values()), now)
            for candidate in candidates:
                trial = self.aiming.update(candidate, now,
                    lambda a, b: self.lane_from(candidate, a, b), artillery=artillery)
                if target is None:
                    target, solution = candidate, trial
                elif trial.get('geometry_clear') and not solution.get('geometry_clear'):
                    target, solution = candidate, trial
                if trial.get('clear') and trial.get('reachable'):
                    target, solution = candidate, trial
                    break
            fire_clear = bool(solution and solution.get('clear') and solution.get('reachable'))
        tactical_clear = bool(solution and solution.get('geometry_clear'))
        if self.ammo_policy is not None:
            self.ammo_policy.context(position, target.id if target is not None else None)
        if 'fire' in self.features and self.ammo_state['available']:
            previous_shell = owner._gun_state.shot_index
            self.select_ammo(now)
            if previous_shell != owner._gun_state.shot_index:
                # Ballistic and armor proofs belong to one mounted shell.
                fire_clear = False
                tactical_clear = False
                self.aiming.reset()
        self.aim_receipt = None
        if target is not None:
            from ..gun_mechanics import _field
            from .weapon import barrel_aligned
            self.target_engine = target.id
            point = solution['point']
            self.weapon.aim_solution(target.id, solution, now)
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
            self.aim_receipt = dict(target=target.id, point=point, aligned=aligned, distance=distance,
                                    fire_clear=fire_clear, reason=solution.get('reason'),
                                    geometry_clear=tactical_clear, needs_hull=solution.get('needs_hull'),
                                    reachable=solution.get('reachable'), arc=solution.get('arc'),
                                    velocity=solution.get('velocity'), progress=aim_progress,
                                    client_mode=owner._avatar.gunRotator.clientMode)
            fire_ready = (fire_clear and aligned and gun.can_fire(True) and
                          self.weapon.ready(now, factor))
        else:
            self.target_engine = None
            self.aim_progress_sample = None
            if 'fire' in self.features and self.weapon is not None:
                self.weapon.forward(position,yaw,max(.5,(shape[2]+shape[3])*.5))
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
            state = dict(id=owner.client.player_id, engine_id=entity.id, position=position, yaw=yaw,
                         speed=owner._local_speed, now=now, half_length=shape[1], half_width=shape[0])
            def clear(angle, reach=None):
                return (traffic.clear(angle, reach or 5.) and
                        self.direction_clear(position, angle, entity.typeDescriptor, shape, reach))
            base = (owner._rules_state.get('bases') or {}).get(str(owner.client.team), {})
            enemy_base = (owner._rules_state.get('bases') or {}).get(str(3 - int(owner.client.team)), {})
            allies = [r for r in peers if r['team'] == int(owner.client.team)]
            allies.append(dict(id=entity.id, alive=True, class_tag=self.navigation.tag,
                               position=position, health=entity.health,
                               max_health=entity.typeDescriptor.maxHealth))
            public_allies = list(allies)
            observed_ids = set(row['id'] for row in allies)
            for record in getattr(owner, '_records', {}).values():
                public = record.get('state') or {}
                identity = record.get('engine_id')
                if int(public.get('team', 0)) != int(owner.client.team) or identity in observed_ids:
                    continue
                # A teammate without a streamed entity remains conservatively
                # alive and unclassified. Missing presentation is not death.
                alive = public.get('alive', True) and public.get('health', 1) > 0
                public_allies.append(dict(id=identity, alive=alive, class_tag=None))
            self.navigation.set_context(dict(empty_ammo=self.ammo_state['empty'],
                target=target, contacts=contacts, allies=public_allies, neighbours=peers,
                base=base, enemy_base=enemy_base,
                allies_complete=getattr(owner, '_bots_ready_reported', True) and
                    not bool(getattr(owner, '_pending_bot_create_order', None)),
                fire_clear=tactical_clear, aligned=bool(self.aim_receipt and self.aim_receipt.get('aligned')
                    and solution and solution.get('reachable')),
                gun_ready=self.ammo_state['can_fire'], fire_seq=self.automatic_commits,
                fire_failure=self.last_fire_failure, aim_progress=aim_progress,
                battle_finished=False, supported=not getattr(owner, '_local_airborne', False)
                    and not getattr(owner, '_local_support_rise_blocked', False),
                overturned=bool(getattr(owner, '_overturn_level', 0))))
            movement = self.navigation.movement_policy(state)
            hold = bool(not self.ammo_state['empty'] and not movement.get('force_move') and
                target is not None and tactical_clear and
                (artillery or self.aim_receipt['distance'] <= movement.get('engage_range', 150.)))
            if now >= self.next_strategy and movement.get('allow_strategy'):
                self.next_strategy=now+1.
                previous_mode = self.strategy.mode
                redirect=self.strategy.decide(now,self.navigation.routes,self.navigation.route,
                    contacts, allies, base, self.navigation.home, engaged=hold,
                    mission=self.navigation.mission_status(), empty_ammo=self.ammo_state['empty'])
                if redirect is not None:
                    reason = ('rejoin_after_defence' if previous_mode == 'defend' and
                              self.strategy.mode != 'defend' else self.strategy.mode)
                    self.navigation.retask(redirect, reason=reason)
                    self.record('player_strategy',decision=self.strategy.receipt)
            automatic_defence = self.strategy.mode == 'defend' and movement.get('allow_strategy')
            if automatic_defence and self.navigation.home is not None:
                home=self.navigation.home
                # A distant incidental target cannot pin the defender on the
                # wrong side of the map. Fire may continue while returning.
                hold=bool(not self.ammo_state['empty'] and not movement.get('force_move') and
                    tactical_clear and target is not None and math.hypot(
                    target.position[0]-home[0],target.position[2]-home[1])<100. and
                    self.aim_receipt['distance']<=150.)
            position_goal = None
            withdrawal = None
            if isinstance(self.navigation, PlayerNavigation):
                if ('fire' in self.features and not self.ammo_state['empty'] and
                        movement.get('allow_withdrawal') and not automatic_defence and
                        (target is not None or self.navigation.cover_move is not None)):
                    withdrawal = self.navigation.withdrawal(
                        state, target, entity, owner._gun_state, clear, owner._tactical_ray_clear)
                else:
                    self.navigation.cover_move = None
                if ('fire' in self.features and not self.ammo_state['empty'] and
                        movement.get('allow_firing_position') and not tactical_clear and candidates and
                        not automatic_defence and withdrawal is None):
                    position_goal = self.navigation.firing_position(
                        state, candidates[0], clear, self.lane_from, owner._mutable_shot_ray()[0])
                if position_goal is None:
                    self.navigation.firing_move = None
            if withdrawal is not None:
                hold = False
                order = dict(withdrawal, recovery_mode=withdrawal['combat_mode'])
            elif position_goal is None:
                order = self.navigation.decide(state, clear, hold=hold)
            else:
                order = self.navigation.drive_to_firing_position(state, clear, position_goal)
            pushing = self.wreck_push.apply(order,state,traffic,
                lambda heading, reach:self.direction_clear(position,heading,entity.typeDescriptor,shape,reach))
            if not pushing:
                self.turn_clearance.apply(order,yaw,traffic,position,clear)
            mission_order = order.get('mission') or {}
            arrival = mission_order.get('arrival') or {}
            facing_allowed = (mission_order.get('status') not in ('failed', 'cancelled') and
                not (order.get('holding') and mission_order and not arrival.get('settled')) and
                not (order.get('holding') and order.get('artillery') and not mission_order and
                     order['artillery'].get('phase') != 'holding'))
            if hold and facing_allowed:
                from .driving import angle
                dx = target.position[0] - position[0]
                dz = target.position[2] - position[2]
                delta = angle(math.atan2(dx, dz) - yaw) if math.hypot(dx, dz) > .1 else 0.
                from .weapon import hull_traverse_error
                traverse = hull_traverse_error(owner, entity.typeDescriptor, point, delta, solution=solution)
                if traverse is not None:
                    delta = traverse
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
            order['traffic'] = dict(traffic.receipt,peer_count=len(peers),
                wreck_count=sum(not r['alive'] for r in peers),
                blocked_queries=traffic.blocked_queries)
            sender.forward, sender.turn = order['throttle'], order['turn']
            sender.handbrake = order['brake']
            sender.send_current()
            self.update_siege(entity, order, tactical_clear, now)
        else:
            order = {}
        self.last_order = order
        self.finish_mission(now)
        mission_order = order.get('mission') or {}
        fire_allowed = mission_order.get('status') not in ('failed', 'cancelled')
        if artillery and order.get('artillery') and not mission_order:
            fire_allowed = fire_allowed and order['artillery'].get('phase') not in (
                'deploying', 'relocating', 'sortie_return')
        if fire_ready and fire_allowed:
            unused_start, direction = owner._mutable_shot_ray()
            if self.aiming.confirm(target, solution, direction, now,
                    owner._tactical_ray_clear,
                    dynamic_clear=lambda path:self.dynamic_path_clear(target, path)):
                accepted = self.trigger(self.weapon, now)
                self.record('automatic_fire', target=target.id, accepted=accepted,
                            native=self.weapon.trigger_receipt)
        if self.aiming is not None and self.aim_receipt is not None:
            self.aim_receipt['budget'] = dict(getattr(self.aiming, 'receipt', {}))
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
    path = os.environ.get('WOT_OFFLINE_TEST_CONTROL_FILE')
    if path and os.path.isfile(path):
        _current.command_offset = os.path.getsize(path)
    _current.record('attached', features=sorted(_current.features), command_file=path,
                    implementation='foreground_independent_v3')
    _current.publish_status(owner._clock(), force=True, reason='attached')
    return _current
