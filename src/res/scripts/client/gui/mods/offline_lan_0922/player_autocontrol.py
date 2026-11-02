# -*- coding: utf-8 -*-
"""Opt-in player input producer; never a second physics or damage owner."""
from __future__ import print_function
import json
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
        self.owner, self.features, self.notify = owner, set(features), notify
        self.active = self.key_down = False
        self.navigation = None
        self.ammo_policy = None
        self.shots = {}
        self.engagement = None
        self.aim_receipt = None
        self.preserve_first = False
        self.desired_range = 200.
        self.next_decision = 0.0
        self.last_decision = None
        self.command_offset = 0
        self.next_poll = 0.0
        self.override = None
        self.target_engine = None
        self.closed = False
        self.input_binding = None
        self.consumable_pending = {}

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
        from .native_input_diagnostics import write_json_record
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
        return bool(not self.closed and owner.state == 'running' and owner._battle_live and
                    owner._battle_result is None and owner._server is not None and
                    owner._sender is not None and not owner._worker_mode and not owner._replay_mode)

    def toggle(self):
        if self.active:
            self.stop('manual')
            return False
        if not self.live():
            return False
        owner = self.owner
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            return False
        # This uses the same checked authored routes and short-range driver as
        # the Bot adapter. It does not register another simulated vehicle.
        from .player_navigation import PlayerNavigation
        from .ammo_policy import ShotPolicy
        from .ai.planner import build_vehicle_profile, _shell_profiles
        self.navigation = PlayerNavigation(owner, entity.typeDescriptor)
        profile = build_vehicle_profile(entity.typeDescriptor)
        profile['shells'] = _shell_profiles(dict(gun=dict(shots=owner._gun_state.shots)))
        profile.pop('bot_tier', None)  # Never upgrade a player's inventory.
        self.desired_range = float(profile['desired_range'])
        self.ammo_policy = ShotPolicy(profile)
        self.ammo_policy.phase = self.ammo_policy.desired = owner._gun_state.shot_index
        self.preserve_first = True
        self.engagement = None
        self.active = True
        self.last_decision = None
        self.next_decision = 0.0
        self.record('enabled', features=sorted(self.features))
        self.notify(u'【测试】玩家自动控制已开启。')
        return True

    def stop(self, reason='manual'):
        changed = self.active or self.override is not None
        self.active = False
        self.override = None
        if self.navigation is not None:
            self.navigation.close()
        self.navigation = None
        self.ammo_policy = None
        self.shots.clear()
        self.engagement = None
        owner = self.owner
        if owner._sender is not None and changed:
            owner._sender.forward = owner._sender.turn = 0.0
            owner._sender.handbrake = False
            owner._sender.send_current()
            owner._cancel_local_player_burst(apply_settings=True)
            if not isinstance(getattr(owner, '_local_fire_intent', None), dict):
                owner._defer_cancel_native_shot_wait()
        if self.target_engine is not None and owner._avatar is not None:
            owner._avatar.autoAim(None)
        self.target_engine = None
        if changed:
            self.record('disabled', reason=reason)
            if self.live():
                self.notify(u'【测试】玩家自动控制已关闭，恢复手动操作。')

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
        if _current is self:
            _current = None

    def poll_commands(self, now):
        if now < self.next_poll:
            return
        self.next_poll = now + 0.15
        path = os.environ.get('WOT_OFFLINE_TEST_CONTROL_FILE')
        if not path or not os.path.isfile(path):
            return
        with open(path, 'rb') as stream:
            stream.seek(self.command_offset)
            for unused in range(16):
                offset = stream.tell()
                line = stream.readline(4097)
                if not line or not line.endswith(b'\n'):
                    break
                self.command_offset = stream.tell()
                if len(line) > 4096:
                    self.record('command_rejected', reason='oversize', offset=offset)
                    continue
                try:
                    self.command(json.loads(line.decode('utf8')), now)
                except (TypeError, ValueError, KeyError) as error:
                    self.record('command_rejected', reason=str(error))

    def command(self, command, now):
        """Mouse and internal scripts share this bounded real-input contract."""
        if not isinstance(command, dict):
            raise ValueError('player control command must be an object')
        action = command.get('action')
        if not self.live():
            return False
        if action == 'toggle':
            return self.toggle()
        if action == 'stop':
            self.stop('mouse_or_script')
            return True
        if action == 'drive':
            self.stop('script_override')
            seconds = float(command.get('seconds', 1.0))
            forward, turn = float(command.get('forward', 0)), float(command.get('turn', 0))
            if not (0 < seconds <= 10 and -1 <= forward <= 1 and -1 <= turn <= 1):
                raise ValueError('invalid timed drive')
            self.override = (now + seconds, forward, turn)
        elif action == 'fire':
            self.stop('script_fire_override')
            sender = self.owner._sender
            accepted = self.owner.shoot(sender.aim_yaw, sender.gun_pitch)
            self.record('script_fire', accepted=bool(accepted))
            return bool(accepted)
        else:
            raise ValueError('unknown player control action')
        self.record('command', command=command)
        return True

    def _contacts(self, entity):
        owner = self.owner
        contacts, neighbours, records = [], [], {}
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
                       collision_shape=owner._collision_shape(target.typeDescriptor))
            neighbours.append(row)
            # Actual presentation visibility, not the omniscient LAN roster.
            if team in (1, 2) and team != int(owner.client.team) and row['alive'] and target.isStarted and record.get('spot_visible', False):
                row.update(visible=True)
                contacts.append(row)
                records[target.id] = target
        return contacts, neighbours, records

    def firing_lane(self, target):
        """Check the target ray against world, live allies and dead hulls."""
        owner = self.owner
        start, unused = owner._mutable_shot_ray()
        shape = owner._collision_shape(target.typeDescriptor)
        point = tuple(target.position)
        aim = (point[0], point[1] + max(.5, shape[3]*.5), point[2])
        world = bool(owner._tactical_ray_clear(tuple(start), aim))
        rows = owner._bot_lane_rows(None, lambda record, state, vehicle:
            not record.get('local') and vehicle.id != target.id and
            (not vehicle.isAlive() or int(state.get('team', 0)) == int(owner.client.team)))
        contact = owner._bot_lane_row_contact(rows, (tuple(start), aim))
        return world and contact is None

    def shot_committed(self, event, pending):
        if not self.active or 'fire' not in self.features or self.ammo_policy is None:
            return
        policy = self.ammo_policy
        sequence = int(event['shot_seq'])
        group = int(event.get('burst_group_seq', sequence))
        count = int(event.get('burst_count', 1))
        position, unused = self.owner.local_pose()
        policy.launch(sequence, int(event['shell_index']), group, count,
                      dict(x=position[0], z=position[2]), self.target_engine)
        self.shots[str(event['projectile_id'])] = dict(sequence=sequence, hit=False,
                                                     damage=0., penetrated=False)
        if self.preserve_first:
            self.preserve_first = False
            from .ammo_policy import stages
            choices = stages(policy.profile, self.owner._gun_state.ammo)
            if choices:
                policy.desired = int(choices[0]['index'])
        if self.engagement is not None:
            self.engagement['fired'] = True
        self.record('shot_committed', projectile=event['projectile_id'], shell=event['shell_index'])

    def shot_hit(self, event):
        row = self.shots.get(str(event.get('projectile_id')))
        if row is not None:
            row['hit'] = True
            row['damage'] += max(0., float(event.get('damage', 0)))
            row['penetrated'] = row['penetrated'] or event.get('shot_result') == 2

    def shot_terminal(self, event):
        row = self.shots.pop(str(event.get('projectile_id')), None)
        if row is not None and self.ammo_policy is not None:
            row['hit'] = row['hit'] or bool(event.get('hit_vehicle'))
            self.ammo_policy.resolve(row['sequence'], row['hit'], row['damage'], row['penetrated'])
            self.record('shot_terminal', projectile=event['projectile_id'], **row)

    def select_ammo(self):
        from .gun_mechanics import _field
        gun, policy = self.owner._gun_state, self.ammo_policy
        if policy is None or self.preserve_first or self.owner._local_fire_intent is not None:
            return
        selected = policy.choose(dict(ammo_remaining=gun.ammo))
        if selected != gun.shot_index and selected != gun.pending_index:
            settings = self.owner._runtime.constants.VEHICLE_SETTING
            # After the protected loaded round, a single-shot gun can start
            # reloading the policy's next choice now. A live cassette queues
            # it without throwing away its remaining rounds.
            code = settings.CURRENT_SHELLS if gun.clip_size <= 1 or gun.clip <= 0 else settings.NEXT_SHELLS
            self.owner.change_vehicle_setting(code,
                                             _field(_field(gun.shots[selected], 'shell'), 'compactDescr'))
            self.record('ammo_queued', shell=selected)

    def _consumables(self, entity):
        from . import equipment_mechanics
        record = self.owner._records.get('player:%s' % self.owner.client.player_id) or {}
        # Healthy native Vehicle instances do not expose Python shadow fields.
        # Read the existing canonical authority payload, including yellow devices.
        critical = record.get('critical_state') or (record.get('state') or {}).get('critical') or {}
        repair = equipment_mechanics.bot_repair_selection(critical, 'elite')
        crew = equipment_mechanics.bot_crew_selection(critical)
        for item in self.owner._equipment_state or ():
            kind = item.contract.get('kind')
            if item.contract.get('autoactivate'):
                # Native automatic equipment already owns its reaction clock.
                continue
            needed = ((kind == 'extinguisher' and critical.get('fire')) or
                      (kind == 'repairkit' and repair is not None) or
                      (kind == 'medkit' and crew is not None))
            now = self.owner._clock()
            if needed and item.ready(now) and now >= self.consumable_pending.get(item.contract['id'], 0):
                selected = repair if kind == 'repairkit' else crew if kind == 'medkit' else None
                index = self.owner._critical_extra_index(entity.typeDescriptor, selected) if selected else 0
                self.owner._activate_equipment(item.contract['id'] | (index << 16))
                self.consumable_pending[item.contract['id']] = now + 2.0

    def aimed_at(self, target):
        """Use the actual native muzzle direction, never a guessed gun angle."""
        owner = self.owner
        start, direction = owner._mutable_shot_ray()
        point = tuple(target.position)
        shape = owner._collision_shape(target.typeDescriptor)
        aim = (point[0], point[1] + max(0.5, shape[3] * 0.5), point[2])
        delta = tuple(aim[i] - start[i] for i in range(3))
        distance = math.sqrt(sum(value * value for value in delta))
        if distance <= 0.1:
            return False
        cosine = sum(delta[i] * direction[i] for i in range(3)) / distance
        tolerance = math.atan2(max(0.4, shape[0] * 0.6), distance)
        aligned = cosine >= math.cos(tolerance)
        clear = self.firing_lane(target)
        self.aim_receipt = dict(aligned=aligned, world_clear=clear, distance=distance)
        return aligned and clear

    def lock_target(self, target):
        """Avatar.autoAim takes a Vehicle; its cell mailbox takes an integer."""
        locked = getattr(self.owner._avatar, '_PlayerAvatar__autoAimVehID', None)
        if self.target_engine != target.id or locked != target.id:
            self.owner._avatar.autoAim(target)
            self.target_engine = target.id

    def direction_clear(self, position, angle, descriptor, shape, reach=None):
        from .ai.driver import NAVIGATION_MAX_GRADE
        result = self.owner._direction_probe(position, angle, self.owner._local_speed,
                                             descriptor, reach, shape[0])
        # The engine seam returns a receipt dictionary, not a Boolean. A
        # nonempty blocked receipt must never be treated as a clear corridor.
        return isinstance(result, dict) and bool(result.get('clear')) and not any(
            result.get(key) for key in ('collision', 'water', 'cliff', 'blocked')) and (
            abs(float(result.get('slope', 0.))) <= NAVIGATION_MAX_GRADE)

    def update(self, dt, now):
        if not self.live():
            self.stop('battle_not_live')
            return
        owner = self.owner
        self.bind_input()
        self.poll_commands(now)
        entity = owner._server_entity(owner._server.vehicle_id)
        if entity is None or not entity.isAlive():
            self.stop('player_dead')
            return
        sender = owner._sender
        if self.override is not None:
            until, forward, turn = self.override
            if now >= until:
                self.stop('script_completed')
            else:
                sender.forward, sender.turn, sender.handbrake = forward, turn, False
                sender.send_current()
            return
        if not self.active or now < self.next_decision:
            return
        step = min(0.5, max(0.0, now - self.last_decision)) if self.last_decision is not None else 0.1
        self.last_decision, self.next_decision = now, now + 0.1
        position, yaw = owner.local_pose()
        position = tuple(position)
        contacts, neighbours, records = self._contacts(entity)
        shape = owner._collision_shape(entity.typeDescriptor)
        state = dict(id=owner.client.player_id, slot=0, position=position, yaw=yaw,
                     speed=owner._local_speed, dt=step, now=now, health=entity.health,
                     max_health=entity.typeDescriptor.maxHealth, contacts=contacts,
                     neighbours=neighbours, half_width=shape[0], half_length=shape[1], collision_shape=shape,
                     turn_speed_limit=float((owner._local_physics or {}).get('rotSpd', 0.)))
        def clear(angle, reach=None):
            return self.direction_clear(position, angle, entity.typeDescriptor, shape, reach)
        # This planner owns only the human vehicle; no Bot agents are registered.
        shootable = ([target for target in records.values() if self.firing_lane(target)]
                     if 'fire' in self.features else [])
        target = min(shootable, key=lambda item: sum((float(item.position[i])-position[i])**2
                     for i in (0, 2))) if shootable else None
        hold = target is not None and 'fire' in self.features and math.hypot(
            float(target.position[0])-position[0], float(target.position[2])-position[2]) <= self.desired_range
        order = self.navigation.decide(state, clear, hold=hold) if self.navigation else dict(
            throttle=0., turn=0., combat_mode='manual', route_id=None, route_index=None)
        if 'drive' in self.features:
            sender.forward, sender.turn = order['throttle'], order['turn']
            sender.handbrake = bool(order.get('brake'))
            sender.send_current()
        if 'consumables' in self.features:
            self._consumables(entity)
        if 'fire' in self.features and target is not None:
            from . import bot_gunnery
            if self.engagement is None or self.engagement['id'] != target.id:
                self.engagement = dict(id=target.id, at=now, fired=False)
            self.lock_target(target)
            self.select_ammo()
            gun = owner._gun_state
            base = gun.base_dispersion * owner._local_stat_factor(entity, 'dispersion')
            factor = owner._native_dispersion_angle()/base if base > 0 else float('inf')
            elapsed = max(0., now-self.engagement['at'])
            ready = bot_gunnery.may_fire(1., elapsed, elapsed, factor,
                                        opening_shot=not self.engagement['fired'])
            if ready and gun.can_fire(True) and self.aimed_at(target):
                accepted = owner.shoot(sender.aim_yaw, sender.gun_pitch)
                if accepted:
                    self.record('automatic_fire', target=target.id)
        elif self.target_engine is not None:
            owner._avatar.autoAim(None)
            self.target_engine = None
            self.engagement = None
        if now >= getattr(self, 'next_log', 0.0):
            self.next_log = now + 1.0
            self.record('decision', position=position, speed=owner._local_speed,
                        throttle=sender.forward, turn=sender.turn, target=target.id if target else None,
                        route=order.get('combat_mode'), local_target=order.get('local_target'),
                        route_id=order.get('route_id'), route_index=order.get('route_index'),
                        entry=self.navigation.receipt if self.navigation else None,
                        recovery=order.get('recovery_mode'),
                        aim=getattr(self, 'aim_receipt', None),
                        locked_target=getattr(owner._avatar, '_PlayerAvatar__autoAimVehID', None))


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
    _current.record('attached', features=sorted(_current.features), command_file=path)
    return _current
