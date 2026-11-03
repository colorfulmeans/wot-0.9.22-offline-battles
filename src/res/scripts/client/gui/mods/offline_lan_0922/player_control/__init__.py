# -*- coding: utf-8 -*-
"""Foreground-only human automation. No Bot actor, policy or driving imports.

Native physics, weapon mechanics, network authority and immutable map catalogs
remain services; all player decisions live inside this package.
"""
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
        self.navigation = self.weapon = self.ammo_policy = None
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
        from .navigation import PlayerNavigation
        from .weapon import Weapon
        from .ammunition import Ammunition
        from .strategy import Strategy
        from .traffic import TurnClearance
        from ..gun_mechanics import _field
        from ..default_loadouts import descriptor_roles, GOLD_SHELLS
        gun = owner._gun_state
        roles = descriptor_roles(entity.typeDescriptor) or {}
        nation = entity.typeDescriptor.type.name.split(':')[0]
        shells = [dict(index=i, kind=str(_field(_field(shot, 'shell'), 'kind')),
                       premium=nation+':'+str(_field(_field(shot, 'shell'), 'name', '')) in GOLD_SHELLS,
                       name=str(_field(_field(shot, 'shell'), 'name', '')))
                  for i, shot in enumerate(gun.shots)]
        shells.sort(key=lambda row: (('standard', 'premium', 'he').index(roles[row['index']])
                    if row['index'] in roles else row['index']))
        self.ammo_policy = Ammunition(shells, shells[0]['index'], gun.shot_index, gun.clip_size,
                                     artillery='SPG' in entity.typeDescriptor.type.tags)
        if gun.ammo[gun.shot_index] <= 0:
            self.ammo_policy.protected = False
        self.navigation = PlayerNavigation(owner, entity.typeDescriptor) if 'drive' in self.features else None
        self.strategy = Strategy()
        self.turn_clearance = TurnClearance()
        self.next_strategy = 0.
        self.weapon = Weapon(owner)
        if 'fire' in self.features:
            self.weapon.bind()
        self.active = True
        self.last_decision = None
        self.next_decision = 0.0
        self.record('enabled', features=sorted(self.features), inventory=list(gun.ammo), shells=shells)
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
        self.strategy = None
        if self.weapon is not None:
            self.weapon.close()
        self.weapon = None
        owner = self.owner
        if owner._sender is not None and changed:
            owner._sender.forward = owner._sender.turn = 0.0
            owner._sender.handbrake = False
            owner._sender.send_current()
            # Already accepted rounds settle on their original native owner;
            # manual input resumes without cancelling admitted projectiles.
            if not isinstance(getattr(owner, '_local_fire_intent', None), dict):
                owner._cancel_local_player_burst(apply_settings=True)
                owner._defer_cancel_native_shot_wait()
            else:
                self.handover_burst = owner._local_fire_intent.get('player_burst')
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
            from .weapon import Weapon
            accepted = Weapon(self.owner).trigger()
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
                       pitch=float(target.matrix.pitch), roll=float(target.matrix.roll),
                       collision_shape=owner._collision_shape(target.typeDescriptor))
            neighbours.append(row)
            # Actual presentation visibility, not the omniscient LAN roster.
            if team in (1, 2) and team != int(owner.client.team) and row['alive'] and target.isStarted and record.get('spot_visible', False):
                row.update(visible=True)
                contacts.append(row)
                records[target.id] = target
        return contacts, neighbours, records

    def target_point(self, target):
        shape = self.owner._collision_shape(target.typeDescriptor)
        point = tuple(target.position)
        return (point[0], point[1]+max(.5, (shape[2]+shape[3])*.5), point[2])

    def firing_lane(self, target):
        from ..entities.remote_vehicle import collide_vehicle_at_matrix
        from ..projectile_runtime import point_segment_distance_sq
        owner = self.owner
        start, unused = owner._mutable_shot_ray()
        start, end = tuple(start), self.target_point(target)
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

    def direction_clear(self, position, yaw, descriptor, shape, reach=None):
        row = self.owner._direction_probe(position, yaw, self.owner._local_speed,
                                          descriptor, reach, shape[0])
        self.probe_receipt = row
        return isinstance(row, dict) and bool(row.get('clear')) and not any(
            row.get(key) for key in ('collision', 'water', 'cliff', 'blocked')) and (
            abs(float(row.get('slope', 0.))) <= math.tan(math.radians(25.)))

    def shot_committed(self, event, pending):
        self.shot_commits += 1
        if (self.handover_burst is not None and pending.get('player_burst') is self.handover_burst):
            if self.owner._local_player_burst is self.handover_burst:
                self.owner._cancel_local_player_burst()
                self.owner._rescale_current_reload(self.owner._gun_state,pending['reload_factor'])
            self.handover_burst = None
        if self.active and 'fire' in self.features and self.ammo_policy is not None:
            self.ammo_policy.launch(str(event['projectile_id']), int(event['shell_index']),
                                    self.target_engine, self.owner._clock())
            self.weapon.fired = True
            self.weapon.committed += 1
            self.record('shot_committed', projectile=event['projectile_id'], shell=event['shell_index'])

    def shot_hit(self, event):
        if self.ammo_policy is not None:
            self.ammo_policy.hit(event)
            self.record('combat_receipt', projectile=event.get('projectile_id'),
                        damage=event.get('damage'), penetrated=event.get('shot_result') == 2)

    def shot_terminal(self, event):
        if self.ammo_policy is not None:
            self.ammo_policy.terminal(event, self.owner._clock())

    def select_ammo(self, now):
        from ..gun_mechanics import _field
        gun, policy = self.owner._gun_state, self.ammo_policy
        if policy is None:
            return
        for row in policy.settle(gun.ammo, now):
            self.record('shot_result', result=row, failures=policy.failures, desired=policy.desired)
        if policy.protected or self.owner._local_fire_intent is not None:
            return
        selected = policy.choose(gun.ammo)
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
        for item in owner._equipment_state or ():
            kind = item.contract.get('kind')
            if item.contract.get('autoactivate'):
                continue
            selected = repair if kind == 'repairkit' else crew if kind == 'medkit' else None
            needed = selected is not None or (kind == 'extinguisher' and critical.get('fire'))
            if needed and item.ready(now) and now >= self.consumable_pending.get(item.contract['id'], 0):
                # #1513 all-target kits and extinguishers use high word 1.
                # Only single-target kits encode a descriptor extra index.
                # Encoding the damaged track's index for a large kit is
                # rejected by the canonical equipment owner, not a cooldown.
                all_targets = bool(item.contract.get('repairAll'))
                index = (1 if all_targets or kind == 'extinguisher' else
                         owner._critical_extra_index(entity.typeDescriptor, selected))
                activation_code = item.contract['id'] | (index << 16)
                requested = bool(owner._activate_equipment(activation_code))
                self.consumable_pending[item.contract['id']] = now+2.
                self.record('consumable', equipment=item.contract['id'],
                            selected=None if all_targets else selected,
                            needed_target=selected, activation_code=activation_code,
                            requested=requested)

    def update(self, dt, now):
        if not self.live():
            self.stop('battle_not_live')
            return
        self.bind_input()
        self.poll_commands(now)
        owner = self.owner
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
        self.next_decision = now+.1
        position, yaw = owner.local_pose()
        position = tuple(position)
        contacts, neighbours, records = self._contacts(entity)
        shape = owner._collision_shape(entity.typeDescriptor)
        previous_target = self.target_engine
        target = None
        fire_clear = False
        if 'fire' in self.features:
            self.select_ammo(now)
            # Keep a valid current target instead of resetting aim every tick.
            candidates = sorted(records.values(), key=lambda item: (
                item.id != self.target_engine,
                sum((item.position[i]-position[i])**2 for i in (0, 2))))
            target = next((t for t in candidates if self.firing_lane(t)), None)
            fire_clear = target is not None
            if target is None:
                # Clearance is measured from the moving muzzle. Dropping aim
                # on a blocked ray can move it clear, reacquire the same enemy,
                # then block again beside a wreck. Keep a visible live target
                # for aiming only; blocked fire must not pin navigation either.
                target = records.get(previous_target)
        self.aim_receipt = None
        if target is not None:
            from ..gun_mechanics import _field
            from .weapon import barrel_aligned
            self.target_engine = target.id
            point = self.target_point(target)
            self.weapon.aim(target.id, point, now)
            start, direction = owner._mutable_shot_ray()
            distance = math.sqrt(sum((point[i]-start[i])**2 for i in range(3)))
            gun = owner._gun_state
            shot = gun.shots[gun.shot_index]
            aligned = barrel_aligned(start,direction,float(_field(shot,'speed')),
                float(_field(shot,'gravity')),point,max(.3,owner._collision_shape(target.typeDescriptor)[0]*.5))
            base = gun.base_dispersion*owner._local_stat_factor(entity, 'dispersion')
            factor = owner._native_dispersion_angle()/base if base > 0 else float('inf')
            self.aim_receipt = dict(target=target.id, point=point, aligned=aligned, distance=distance,
                                    fire_clear=fire_clear,
                                    client_mode=owner._avatar.gunRotator.clientMode)
            if fire_clear and aligned and gun.can_fire(True) and self.weapon.ready(now, factor):
                accepted = self.weapon.trigger()
                self.record('automatic_fire', target=target.id, accepted=accepted,
                            native=self.weapon.trigger_receipt)
        else:
            self.target_engine = None
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
            peers = [r for r in neighbours if r['team']==int(owner.client.team) or r.get('visible') or not r['alive']]
            traffic = Traffic(body(entity.id,position,yaw,shape,
                getattr(owner,'_local_pitch',0.),getattr(owner,'_local_roll',0.)),peers)
            state = dict(id=owner.client.player_id, position=position, yaw=yaw,
                         speed=owner._local_speed, now=now, half_length=shape[1], half_width=shape[0])
            def clear(angle, reach=None):
                return (traffic.clear(angle, reach or 5.) and
                        self.direction_clear(position, angle, entity.typeDescriptor, shape, reach))
            hold = bool(fire_clear and target is not None and self.aim_receipt['distance'] <= 150.)
            if now>=self.next_strategy:
                self.next_strategy=now+1.
                base=(owner._rules_state.get('bases') or {}).get(str(owner.client.team),{})
                redirect=self.strategy.decide(now,self.navigation.routes,self.navigation.route,
                    contacts,[r for r in peers if r['team']==int(owner.client.team)],
                    base,self.navigation.home,engaged=hold)
                if redirect is not None:
                    self.navigation.retask(redirect)
                    self.record('player_strategy',decision=self.strategy.receipt)
            if self.strategy.mode=='defend' and self.navigation.home is not None:
                home=self.navigation.home
                # A distant incidental target cannot pin the defender on the
                # wrong side of the map. Fire may continue while returning.
                hold=bool(fire_clear and target is not None and math.hypot(
                    target.position[0]-home[0],target.position[2]-home[1])<100. and
                    self.aim_receipt['distance']<=150.)
            order = self.navigation.decide(state, clear, hold=hold)
            self.turn_clearance.apply(order,yaw,traffic,position,clear)
            order['traffic'] = dict(traffic.receipt,peer_count=len(peers),
                wreck_count=sum(not r['alive'] for r in peers),
                blocked_queries=traffic.blocked_queries)
            sender.forward, sender.turn = order['throttle'], order['turn']
            sender.handbrake = order['brake']
            sender.send_current()
        else:
            order = {}
        if 'consumables' in self.features:
            self.consumables(entity)
        if now >= getattr(self, 'next_log', 0.):
            self.next_log = now+1.
            self.record('decision', position=position, yaw=yaw, speed=owner._local_speed,
                        throttle=sender.forward, turn=sender.turn, order=order,
                        entry=self.navigation.receipt if self.navigation else None,
                        aim=self.aim_receipt, probe=getattr(self, 'probe_receipt', None))


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
                    implementation='foreground_independent_v2')
    return _current
