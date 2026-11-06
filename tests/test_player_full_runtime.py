"""Complete foreground copy tests with physical-only observation fixtures."""
import copy
import json
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import equipment_mechanics, gun_mechanics, loadout
from gui.mods.offline_lan_0922.player_control import full_runtime
from gui.mods.offline_lan_0922.player_control.copied.ai.planner import build_vehicle_profile
from test_port_0922_bot_runtime import (_combat_descriptor, _flat_open_graph,
                                       _plain_attribute_factors, _effective_params_snapshot)
from test_port_0922_equipment_mechanics import _defaults
from player_native_fixtures import Matrix


def full_scene():
    """A physical flat world; no decision/planner/driver is replaced here."""
    descriptor = _combat_descriptor(clip=(3, .25), max_ammo=40)
    descriptor.type = types.SimpleNamespace(name='ussr:R11_MS-1', tags=('mediumTank',))
    descriptor.turret = types.SimpleNamespace(rotationSpeed=10., circularVisionRadius=445.,
        gunPosition=(0., 0., 0.), hitTester=types.SimpleNamespace(bbox=((-1., 0., -1.), (1., 1., 1.), None)))
    descriptor.gun.shots = (dict(speed=1000., gravity=10., maxDistance=5000.,
        piercingPower=(200., 200.), shell=dict(compactDescr=1234, effectsIndex=0, kind='ARMOR_PIERCING',
            caliber=100., damage=(100., 40.), armorDamage=100.)),)
    descriptor.gun.pitchLimits = dict(absolute=(-.35, .15),
        minPitch=((0., -.35), (2. * math.pi, -.35)),
        maxPitch=((0., .15), (2. * math.pi, .15)))
    graph = _flat_open_graph()
    graph['directions'] = ((-1, -1), (0, -1), (1, -1), (-1, 0),
                           (1, 0), (-1, 1), (0, 1), (1, 1))
    body = Matrix()
    own = types.SimpleNamespace(id=7, typeDescriptor=descriptor, matrix=body,
        position=(0., 0., 0.), isStarted=True, isAlive=lambda: True, health=1000,
        siegeState=0)
    gun = gun_mechanics.GunState(descriptor)
    class Rotator(object):
        def __init__(self):
            self.turretYaw = self.gunPitch = 0.
            self.clientMode = False
            self.dispersionAngle = .03
            self._VehicleGunRotator__shotPointSourceFunctor = None

        @property
        def shotPointSourceFunctor(self):
            return self._VehicleGunRotator__shotPointSourceFunctor

        @shotPointSourceFunctor.setter
        def shotPointSourceFunctor(self, value):
            self._VehicleGunRotator__shotPointSourceFunctor = value

    rotator = Rotator()
    sender = types.SimpleNamespace(forward=0, turn=0, handbrake=False, send_current=mock.Mock())
    record = dict(local=True, ready=True, kind='player', network_id=1, engine_id=7,
        team=1, vehicle='ussr:R11_MS-1', state=dict(id=1,team=1,health=1000,alive=True))
    entities = {7: own}
    battle = types.SimpleNamespace(_start_message=dict(round_id=3,map='01_karelia', bots=[dict(id=1,team=1)],
        bot_skill_mode='elite'), _generation=1,
        client=types.SimpleNamespace(player_id=1), _server=types.SimpleNamespace(vehicle_id=7),
        _server_entity=lambda identity: entities.get(identity), _gun_state=gun,
        _records={'player:1':record}, _navigation_graph=graph, _arena_bounds=graph['bounds'],
        _avatar=types.SimpleNamespace(gunRotator=rotator, autoAim=mock.Mock(), spaceID=1),
        _local_matrix=body, _local_pose_matrix=body, _local_speed=0., _local_turn_speed=0.,
        _local_position=(0.,0.,0.), _local_pitch=0., _local_roll=0.,
        _local_airborne=False, _local_player_burst=None, _local_fire_seq=0,
        _local_support_rise_blocked=False, _overturn_level=0., _local_vertical_speed=0.,
        _local_suspension_pitch_velocity=0., _local_suspension_roll_velocity=0.,
        _local_air_lateral=(0., 0.),
        _last_frame_time=0., _equipment_state=[], _equipment_revision=0,
        _config={}, _destructibles=None, _foliage=None, _remote_factory=None,
        _detached_turret_obstacles=None, _projectile_server_time_ms=0,
        _projectile_server_local_time=0., _sender=sender,
        _native_dispersion_angle=lambda: rotator.dispersionAngle,
        _local_body_pose=lambda: body, local_pose=lambda: (body.translation,body.yaw),
        _support_column=lambda x,z,hint=0.: 0.,
        _mutable_shot_ray=lambda: ((0.,1.6,0.),(0.,0.,1.)), _vector=tuple,
        _resolve_player_descriptor=lambda row: descriptor)
    def angles(desc, matrix, current, point):
        from gui.mods.offline_lan_0922 import ballistics
        roots=ballistics.ballistic_solutions((0.,1.6,0.),point,1000.,10.)
        return math.atan2(point[0], point[2]), roots[0][0]
    battle._runtime=types.SimpleNamespace(math=types.SimpleNamespace(Matrix=Matrix),
        get_shot_angles=angles, bigworld=types.SimpleNamespace(time=lambda: battle._last_frame_time))
    battle.entities=entities
    return battle


class FullRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.patchers = [mock.patch.object(loadout, 'attribute_factors', _plain_attribute_factors)]
        # Only the native boundary is replaced by a measured flat plane.
        queries = dict(
            _navigation_ground=lambda self,x,z,hint_y=0.: 0.,
            _navigation_obstacle=lambda *args,**kwargs: False,
            _navigation_surface_observation=lambda *args,**kwargs: None,
            _navigation_height_columns=lambda *args,**kwargs: (),
            _direction_probe=lambda *args,**kwargs: dict(clear=True,collision=False,slope=0.,water=False),
            _direction_world_receipt=lambda *args,**kwargs: dict(clear=True,collision=False,slope=0.,water=False),
            _probe_bot_local_motion=lambda *args,**kwargs: None,
            _water_depth=lambda *args,**kwargs: -1.,
            _turret_motion_is_clear=lambda *args,**kwargs: True,
            _bot_visibility=lambda *args,**kwargs: True,
            _artillery_arc_probe=lambda *args,**kwargs: True)
        self.patchers += [mock.patch.object(full_runtime._ForegroundGeometry, key, value)
                          for key,value in queries.items()]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.battle=full_scene()
        self.runtime=full_runtime.FullPlayerRuntime(self.battle)

    def test_attach_registers_distinct_local_actor_and_full_planner(self):
        self.assertTrue(self.runtime.attach())
        self.assertEqual(self.runtime.actor_id,1000001)
        self.assertEqual(self.runtime.geometry._records['bot:1000001']['engine_id'],7)
        self.assertNotIn('player:1',self.runtime.geometry._records)
        self.assertIs(self.runtime.engine.__class__._update_once,
                      full_runtime.copied_runtime.BotRuntime._update_once)
        self.assertIsInstance(self.runtime.planner,full_runtime.BotPlanner)
        self.assertIsNotNone(self.runtime.engine.adapter.driver)
        self.assertIsNotNone(self.runtime.engine.navigator)

    def test_real_player_consumable_slot_order_does_not_use_bot_contract(self):
        # A real #1513 player can mount medkit, repairkit, extinguisher in
        # slots 4/5/6; this is not the fixed Bot consumable contract order.
        native_items = _defaults()
        mounted = (native_items[1], native_items[2], native_items[0])
        states = [equipment_mechanics.EquipmentState(
            equipment_mechanics.project_equipment(item)) for item in mounted]
        self.battle._equipment_states = states
        snapshots = [item.trusted_snapshot(0.) for item in states]
        self.battle._records['player:1']['state']['equipment_states'] = snapshots
        original_snapshot = copy.deepcopy(snapshots)
        with mock.patch.object(equipment_mechanics, 'bot_consumable_contracts',
                               wraps=equipment_mechanics.bot_consumable_contracts) as bot_only:
            self.assertTrue(self.runtime.start(('drive', 'fire', 'consumables')))
            bot_only.assert_not_called()
        self.assertTrue(self.runtime.active)
        self.assertEqual(original_snapshot,
                         self.battle._records['player:1']['state']['equipment_states'])
        views = self.runtime.engine._equipment_states[self.runtime.actor_id]
        self.assertEqual(tuple(item.original for item in views), tuple(states))
        self.assertEqual(tuple(item.contract['name'] for item in views),
                         ('largeMedkit', 'largeRepairkit', 'autoExtinguishers'))
        self.battle._last_frame_time = .1
        self.runtime.update(.1, .1)
        self.assertTrue(self.runtime.active)

    def test_real_player_public_wire_is_not_a_bot_restore_checkpoint(self):
        # server/lan_battle_server.py::_public_player sends a human's
        # next_shell_index without the Bot-only ammunition inventory and
        # reload_pending pair. The complete public row also includes live
        # input, equipment and checkpoint fields that are not a Bot manifest.
        row = self.battle._records['player:1']['state']
        row.update(name='Human', vehicle='ussr:R11_MS-1', slot=0,
            world_pose=True, x=12., y=3., z=24., yaw=.8, pitch=.01,
            roll=-.01, aim_yaw=.4, gun_pitch=.03, speed=5.,
            input_seq=5, input_processed_seq=4, siege_state=0,
            siege_time_left_ms=0, fire_seq=11, shell_index=0,
            next_shell_index=0, shell_change_pending=False,
            max_health=1000, stun_end_server_time_ms=0,
            gun_checkpoint_seq=5, gun_checkpoint=dict(reload_time=0.,
                reload_duration=1., clip=3, clip_size=3, dispersion=.03))
        native_items = _defaults()
        mounted = (native_items[1], native_items[2], native_items[0])
        states = [equipment_mechanics.EquipmentState(
            equipment_mechanics.project_equipment(item)) for item in mounted]
        self.battle._equipment_states = states
        row['equipment_states'] = [item.trusted_snapshot(0.) for item in states]
        row['equipment_revision'] = 1
        row['equipment_intent_seq'] = 0
        row['equipment_intent_result'] = dict(intent_seq=0,
            accepted=False, reason='')
        original = copy.deepcopy(row)
        original_restore = full_runtime.copied_runtime._BotAmmoState.restore
        restored_rows = []
        def inspect_bootstrap(state, raw):
            restored_rows.append(dict(raw))
            self.assertFalse(set(raw) & set((
                'ammo_remaining', 'next_shell_index', 'ammo_reload_pending',
                'equipment_states', 'gun_checkpoint', 'gun_checkpoint_seq',
                'shell_change_pending', 'input_seq')))
            return original_restore(state, raw)
        with mock.patch.object(full_runtime.copied_runtime._BotAmmoState,
                               'restore', inspect_bootstrap):
            self.assertTrue(self.runtime.start(('drive', 'fire', 'consumables')))
        self.assertTrue(self.runtime.active)
        self.assertEqual(len(restored_rows), 1)
        self.assertEqual(set(restored_rows[0]), set((
            'id', 'team', 'slot', 'name', 'vehicle', 'x', 'y', 'z', 'yaw',
            'health', 'max_health', 'alive')))
        self.assertEqual(original, row)
        self.assertIsInstance(self.runtime.engine._ammo_states[self.runtime.actor_id],
                              full_runtime._AmmoObservation)
        self.assertEqual(self.runtime.state['ammo_remaining'],
                         list(self.battle._gun_state.ammo))
        self.assertEqual(tuple(item.original for item in
                         self.runtime.engine._equipment_states[self.runtime.actor_id]),
                         tuple(states))
        self.assertEqual(tuple(item['equipment']['name'] for item in
                         self.runtime.state['equipment_states']),
                         ('largeMedkit', 'largeRepairkit', 'autoExtinguishers'))
        self.battle._last_frame_time = .1
        self.runtime.update(.1, .1)
        self.assertTrue(self.runtime.active)

    def test_bootstrap_ignores_every_partial_native_ammunition_checkpoint(self):
        # Human snapshots and native observation have independent lifecycles.
        # None of the following subsets may be interpreted as a persisted Bot
        # inventory, even when they contain valid Bot-shaped values by chance.
        pieces = dict(ammo_remaining=[5], shell_index=0,
            next_shell_index=0, ammo_reload_pending=False)
        for fields in (('next_shell_index',), ('ammo_remaining',),
                       ('ammo_reload_pending',),
                       ('ammo_remaining', 'next_shell_index'),
                       ('ammo_remaining', 'ammo_reload_pending'),
                       ('next_shell_index', 'ammo_reload_pending'),
                       tuple(pieces)):
            with self.subTest(fields=fields):
                battle = full_scene()
                native = battle._records['player:1']['state']
                native.update((name, pieces[name]) for name in fields)
                original = copy.deepcopy(native)
                runtime = full_runtime.FullPlayerRuntime(battle)
                original_restore = full_runtime.copied_runtime._BotAmmoState.restore
                def inspect_bootstrap(state, raw):
                    self.assertFalse(set(raw) & set((
                        'ammo_remaining', 'next_shell_index',
                        'ammo_reload_pending')))
                    return original_restore(state, raw)
                with mock.patch.object(full_runtime.copied_runtime._BotAmmoState,
                                       'restore', inspect_bootstrap):
                    self.assertTrue(runtime.start(('drive', 'fire')))
                self.assertEqual(native, original)
                self.assertIsInstance(runtime.engine._ammo_states[runtime.actor_id],
                                      full_runtime._AmmoObservation)
                self.assertEqual(runtime.state['ammo_remaining'],
                                 list(battle._gun_state.ammo))
                runtime.stop('test')

    def test_complete_live_loop_emits_native_drive_without_duplicating_physics(self):
        self.assertTrue(self.runtime.start(('drive',)))
        body_before=copy.copy(self.battle._local_matrix.__dict__)
        gun_before=copy.copy(self.battle._gun_state.__dict__)
        self.runtime.set_mission('attack',dict(position=(0.,0.,24.)))
        for index in range(3):
            now=.1*(index+1)
            self.battle._last_frame_time=now
            result=self.runtime.update(.1,now)
        self.assertTrue(self.battle._sender.send_current.called)
        self.assertGreater(self.runtime.engine._alive_bot_ticks,0)
        self.assertGreater(self.runtime.planner.revision,0)
        self.assertTrue(result['order'])
        self.assertEqual(body_before,self.battle._local_matrix.__dict__)
        self.assertEqual(gun_before,self.battle._gun_state.__dict__)
        self.assertEqual(tuple(self.runtime.state[k] for k in ('x','y','z')),(0.,0.,0.))

    def test_stop_keeps_physical_trigger_and_restores_only_owned_source(self):
        self.runtime.start(('drive','fire'))
        sentinel=object()
        self.battle._local_player_burst=dict(clock=sentinel,count=3)
        self.runtime.stop('manual')
        self.assertIs(self.battle._local_player_burst['clock'],sentinel)
        self.assertIsNone(self.battle._avatar.gunRotator.shotPointSourceFunctor)
        self.assertFalse(self.battle._avatar.gunRotator.clientMode)
        self.assertEqual(self.battle._sender.forward,0)

    def test_active_external_trigger_does_not_create_nanosecond_spin(self):
        self.runtime.start(('drive',))
        self.battle._local_player_burst=dict(count=3,committed=1)
        self.assertEqual(self.runtime.engine._bounded_burst_step(.1),.1)
        self.runtime.update(.1,.1)
        self.assertLessEqual(self.runtime.engine._last_update_control_steps,2)

    def tick(self, now):
        previous = self.battle._last_frame_time
        self.battle._last_frame_time = now
        return self.runtime.update(now - previous, now)

    def add_peer(self, identity, team, kind='bot', tag='mediumTank', visible=True):
        descriptor = copy.deepcopy(self.battle.entities[7].typeDescriptor)
        descriptor.type.tags = (tag,)
        matrix = Matrix()
        matrix.translation = (float(identity) * 4., 0., 20.)
        entity = types.SimpleNamespace(id=100 + identity, typeDescriptor=descriptor,
            matrix=matrix, position=matrix.translation, isStarted=True, isAlive=lambda: True,
            health=1000, siegeState=0, gun_state=gun_mechanics.GunState(descriptor))
        self.battle.entities[entity.id] = entity
        row = dict(id=identity, team=team, x=matrix.translation[0], y=0., z=20.,
            yaw=0., speed=0., alive=True, health=1000, max_health=1000,
            vehicle='ussr:R11_MS-1', profile=build_vehicle_profile(descriptor),
            clip=3, clip_size=3, ammo_remaining=[40], shell_index=0,
            next_shell_index=0, ammo_reload_pending=False, reload_time=0.)
        if kind == 'player':
            row['effective_params'] = _effective_params_snapshot()
        self.battle._records['%s:%d' % (kind, identity)] = dict(
            kind=kind, network_id=identity, engine_id=entity.id, ready=True,
            team=team, spot_visible=visible, state=row)
        return entity

    def test_mixed_full_observed_roster_has_no_peer_physical_or_weapon_authority(self):
        peers = [self.add_peer(2, 1), self.add_peer(3, 2),
                 self.add_peer(4, 1, tag='SPG'), self.add_peer(5, 2, tag='SPG'),
                 self.add_peer(6, 1, kind='player')]
        before = [(copy.deepcopy(peer.matrix.__dict__),
                   copy.deepcopy(peer.gun_state.__dict__)) for peer in peers]
        self.assertTrue(self.runtime.start(('drive',)))
        self.runtime.set_mission('attack', dict(position=(0., 0., 48.)))
        for index in range(12):
            self.tick((index + 1) * .1)
        self.assertEqual(set((1000001, 2, 3, 4, 5)),
                         set(row['id'] for row in self.runtime.engine._ordered_states()))
        self.assertEqual([6], [row['id'] for row in self.runtime._players])
        self.assertEqual([1000001], [row['id'] for row in self.runtime.engine.controlled_states()])
        for peer, (matrix, gun) in zip(peers, before):
            self.assertEqual(matrix, peer.matrix.__dict__)
            self.assertEqual(gun, peer.gun_state.__dict__)
        self.assertEqual(set((1000001,)), set(self.runtime.engine._gun_states))
        self.assertEqual(12, self.battle._sender.send_current.call_count)

    def test_native_translation_and_rotation_contact_shapes_preserve_full_control(self):
        self.assertTrue(self.runtime.start(('drive',)))
        self.runtime.set_mission('attack', dict(position=(0., 0., 32.)))
        self.tick(.1)
        self.runtime.drive_contact((0., 0., 0.), .2, .1, static=True)
        self.assertEqual(.2, self.runtime._last_navigation['heading'])
        self.runtime.drive_contact((0., 0., 0.), None, .1, static=False)
        self.assertIsNone(self.runtime._last_navigation['heading'])
        self.assertTrue(self.runtime._last_navigation['rotation_refused'])
        self.tick(.2)
        self.assertTrue(self.runtime.active)

    def bases(self):
        self.battle._spawn_planner = types.SimpleNamespace(capture_bases={
            '1': [dict(x=0., z=-40., radius=6.)],
            '2': [dict(x=0., z=40., radius=6.)]})
        self.battle._rules_state = dict(bases={
            '1': dict(points=0, capturing_team=0),
            '2': dict(points=0, capturing_team=0)})

    def native_position(self, point):
        self.battle._local_matrix.translation = tuple(point)
        self.battle._local_position = tuple(point)
        self.battle.entities[7].position = tuple(point)

    def test_return_uses_own_base_and_requires_actual_supported_stopped_arrival(self):
        self.bases()
        self.runtime.start(('drive',))
        self.runtime.set_mission('return_base', {})
        result = self.tick(.1)
        self.assertEqual((0., 0., -40.), result['mission']['destination'])
        self.assertEqual((0., -40.), result['mission']['goal'])
        self.native_position((0., 0., -40.))
        self.battle._local_airborne = True
        for index in range(8):
            self.tick(.2 + index * .1)
            self.assertEqual('running', self.runtime.mission_status()['status'])
        self.battle._local_airborne = False
        for index in range(8):
            result = self.tick(1. + index * .1)
        self.assertEqual('completed', result['mission']['status'])
        self.assertTrue(result['mission']['holding'])
        self.assertEqual((0., 0., -40.), result['order']['move_position'])
        self.assertEqual(0., self.battle._sender.forward)

    def test_actual_capture_progress_never_substitutes_for_authoritative_capture_result(self):
        self.bases()
        self.runtime.start(('drive',))
        self.runtime.set_mission('capture_base', {})
        self.tick(.1)
        self.native_position((0., 0., 40.))
        self.battle._rules_state['bases']['2'].update(points=100, capturing_team=1)
        result = self.tick(.2)
        self.assertEqual('running', result['mission']['status'])
        self.assertEqual('capturing', result['mission']['phase'])
        self.assertEqual(1., result['mission']['progress'])
        self.assertEqual(((0., 40.), 6.), result['order']['capture_pivot_circle'])
        self.battle._battle_result = dict(winner=1, reason='base captured', base_team=2)
        result = self.tick(.3)
        self.assertEqual('completed', result['mission']['status'])
        self.assertEqual('captured', result['mission']['phase'])

    def test_no_ammo_converts_attack_not_explicit_return_or_hold(self):
        self.bases()
        self.runtime.start(('drive',))
        self.battle._gun_state.ammo[:] = [0]
        for kind in ('return_base', 'hold_position', 'defend_base', 'attack'):
            with self.subTest(kind=kind):
                self.runtime.set_mission(kind, {})
                self.tick(self.battle._last_frame_time + .1)
                self.assertEqual('capture_base' if kind == 'attack' else kind,
                                 self.runtime.mission_status()['action'])

    def test_invalid_mission_preflight_has_no_effect_and_restart_drops_retired_hold(self):
        self.runtime.start(('drive',))
        self.runtime.set_mission('attack', dict(position=(0., 0., 32.)))
        self.tick(.1)
        before = copy.deepcopy(self.runtime._mission)
        calls = self.battle._sender.send_current.call_count
        self.assertEqual('invalid_destination',
            self.runtime.mission_preflight('attack', dict(position=(float('nan'), 0., 0.))))
        self.assertEqual('destination_outside_arena',
            self.runtime.mission_preflight('attack', dict(position=(1000., 0., 0.))))
        self.assertEqual(before, self.runtime._mission)
        self.assertEqual(calls, self.battle._sender.send_current.call_count)
        self.runtime.stop()
        self.assertEqual('cancelled', self.runtime.mission_status()['status'])
        self.runtime.start(('drive',))
        self.assertEqual('idle', self.runtime.mission_status()['status'])
        self.tick(.2)
        self.assertTrue(self.runtime.active)

    def test_canonical_capture_observation_maps_only_local_human_into_copied_protection(self):
        from test_port_0922_server_capture import ServerCaptureTests, _player
        canonical = ServerCaptureTests()._state()
        canonical.round_id = self.battle._start_message['round_id']
        canonical.capture_bases = {
            1: [dict(x=0., z=-40., radius=6.)],
            2: [dict(x=0., z=40., radius=6.)]}
        canonical.players[1] = _player(1, 1, 0., 40.)
        canonical.players[8] = _player(8, 1, 0., 40.)
        canonical.players[2] = _player(2, 2, 0., -40.)
        self.assertTrue(canonical._update_capture())
        wire = json.loads(json.dumps(dict(round_id=canonical.round_id,
            rules=canonical.rules_state, defense=canonical._bot_defense_context())))
        self.battle._last_snapshot = wire
        self.native_position((0., 0., 40.))
        self.battle._gun_state.clip = 0
        self.battle._gun_state.reload_time = 30.
        self.battle._local_fire_seq = 1
        self.assertTrue(self.runtime.start(('drive',)))
        result = self.tick(.1)
        defense = self.runtime._defense_context()
        self.assertTrue(defense['contributors_known'])
        self.assertIn(('bot', self.runtime.actor_id),
            self.runtime.planner._defense_contributor_keys(defense, 2))
        self.assertIn(('human', 8), self.runtime.planner._defense_contributor_keys(defense, 2))
        self.assertEqual('human', wire['defense']['contributors']['2'][0]['kind'])
        protection = self.runtime.planner._base_defense[1]['capture_protection']
        self.assertIn(self.runtime.actor_id, protection['protected'])
        self.assertNotIn(self.runtime.actor_id, self.runtime.planner._base_defense[1]['responders'])
        self.assertNotIn(self.runtime.actor_id, self.runtime.planner._retreat_states)
        self.assertEqual(0., self.battle._sender.forward)
        self.assertNotEqual('base_defense', result['order']['combat_mode'])

    def test_stale_or_absent_canonical_contributors_stay_unknown_with_real_rules_fallback(self):
        self.bases()
        self.runtime.start(('drive',))
        fake = dict(contributors={'2': [dict(kind='human', id=1, points=30)]})
        for snapshot in (dict(round_id=2, defense=fake),
                         dict(round_id=3, capture_contributors=fake['contributors'])):
            self.battle._last_snapshot = snapshot
            defense = self.runtime._defense_context()
            self.assertFalse(defense['contributors_known'])
            self.assertFalse(self.runtime.planner._defense_contributor_keys(defense, 2))
            self.assertEqual(self.battle._rules_state['bases'], defense['states'])
        self.battle._spawn_planner.capture_bases = {'1': (0., -40.),
                                                   '2': dict(x=0., z=40., radius=6.)}
        defense = self.runtime._defense_context()
        self.assertEqual(-40., defense['capture_bases']['1'][0]['z'])
        self.assertEqual(6., defense['capture_bases']['2'][0]['radius'])


class NativeAimLoopBoundaryTests(unittest.TestCase):
    def scene(self):
        from test_player_fire_admission_complete import AutomaticFireScene
        scene = AutomaticFireScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        return scene

    def native_tick(self, scene, seconds=.1):
        """Only the observed rotator consumes its installed source here."""
        from gui.mods.offline_lan_0922 import shot_geometry
        scene.fixture.now += seconds
        rotator = scene.battle._avatar.gunRotator
        source = rotator.shotPointSourceFunctor
        if callable(source) and source() is not None:
            yaw, pitch = scene.get_angles(scene.entity.typeDescriptor,
                scene.body, (rotator.turretYaw, rotator.gunPitch), source())
            rotator.turretYaw, rotator.gunPitch = yaw, pitch
            scene.direction = shot_geometry.transform_vehicle_vector(
                (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                 math.cos(yaw) * math.cos(pitch)),
                scene.body.yaw, scene.body.pitch, scene.body.roll)
        scene.battle._last_frame_time = scene.now
        scene.control.update(seconds, scene.now)
        self.assertIsNone(scene.control.last_control_failure)

    def test_new_direct_curved_path_reaches_real_trigger_despite_old_straight_lane_wall(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        gun.shots[0].speed = 100.
        scene.battle.client.effective_params['gun']['shots'][0]['source_shot']['speed'] = 100.
        scene.world = [((-20., -10., 49.), (20., 2.2, 51.))]
        scene.runtime.attack_policy.reset()
        scene.observe()
        proofs, preinstall = [], scene.battle._preinstall_player_projectile
        def record_proof(*args):
            proofs.append(dict(scene.admission.pending['proof']))
            return preinstall(*args)
        scene.battle._preinstall_player_projectile = record_proof
        self.assertFalse(scene.runtime.geometry._bot_firing_lane(
            scene.runtime.state, scene.runtime.visible_targets()[0]))
        before = list(gun.ammo)
        for unused in range(80):
            self.native_tick(scene)
            if scene.launches():
                break
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual(before[0] - 1, gun.ammo[0])
        self.assertTrue(proofs[-1]['done'])
        self.assertEqual('vehicle', proofs[-1]['terminal_kind'])
        self.assertEqual(scene.target.id, proofs[-1]['terminal_vehicle'])

    def test_no_target_copied_hull_forward_rest_replaces_previous_world_enemy_input(self):
        scene = self.scene()
        previous = tuple(scene.runtime.weapon.shot_point())
        scene.battle._records['bot:42']['spot_visible'] = False
        self.native_tick(scene)
        intention = scene.runtime.state['_diagnostic_aim_intent']
        self.assertEqual('hull_forward_rest', intention['owner'])
        rotator = scene.battle._avatar.gunRotator
        source = rotator.shotPointSourceFunctor()
        angles = scene.get_angles(scene.entity.typeDescriptor, scene.body,
                                 (rotator.turretYaw, rotator.gunPitch), source)
        self.assertNotEqual(previous, tuple(source))
        self.assertAlmostEqual(intention['turret_yaw'], angles[0], places=7)
        self.assertAlmostEqual(intention['gun_pitch'], angles[1], places=7)
        self.assertFalse(scene.runtime.state['gun_aligned'])
        self.assertFalse(scene.launches())

    def test_rotated_native_turret_sample_stays_the_same_point_through_real_trigger(self):
        scene = self.scene()
        scene.target.appearance.turretMatrix.setRotateYPR((math.pi * .5, 0., 0.))
        scene.lay(sample_index=6)
        chosen = scene.candidate['solution']
        self.assertAlmostEqual(0., chosen['point'][0], places=7)
        self.assertAlmostEqual(100.5, chosen['point'][2], places=7)
        self.assertIsNone(scene.candidate['target'].get('turret_yaw'))
        proofs, preinstall = [], scene.battle._preinstall_player_projectile
        def record_proof(*args):
            proofs.append(dict(scene.admission.pending['proof']))
            return preinstall(*args)
        scene.battle._preinstall_player_projectile = record_proof
        for unused in range(80):
            self.native_tick(scene)
            candidate = scene.runtime.attack_policy.decision.get('candidate')
            if candidate is not None and scene.runtime.attack_policy.decision['action'] == 'aim':
                actual = scene.runtime.engine._ballistic_solution_cache[scene.runtime.actor_id][2]
                self.assertEqual(candidate['solution']['point'], actual['aim_position'])
                self.assertEqual(candidate['solution']['_aim_token'], actual['_aim_token'])
            if scene.launches():
                break
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual(6, proofs[-1]['solution']['sample'])
        self.assertEqual(chosen['point'], proofs[-1]['solution']['point'])
        self.assertEqual([19, 10], scene.battle._gun_state.ammo)

    def test_stop_inside_native_angle_callback_cannot_resurrect_old_aim_lease(self):
        scene = self.scene()
        actual = scene.battle._runtime.get_shot_angles
        stopped = []
        def callback(*args):
            if not stopped:
                stopped.append(True)
                scene.control.stop('native_angle_callback_stop')
            return actual(*args)
        scene.battle._runtime.get_shot_angles = callback
        scene.runtime.weapon.aim(scene.runtime.state, scene.candidate['target'],
            dict(aim_position=scene.candidate['solution']['point']),
            dict(turret_yaw=0., gun_pitch=scene.battle._avatar.gunRotator.gunPitch))
        self.assertFalse(scene.runtime.active)
        self.assertFalse(scene.runtime.weapon.verified)
        self.assertIsNone(scene.runtime.weapon.bound_source)
        self.assertIsNone(scene.runtime.weapon.source_point)
        self.assertFalse(scene.launches())


class NativeSiegeObservationTests(unittest.TestCase):
    """Native request/echo ownership, not another Siege timer or actuator."""
    scene = NativeAimLoopBoundaryTests.scene
    def siege_scene(self):
        scene = self.scene()
        scene.entity.typeDescriptor.hasSiegeMode = True
        scene.entity.siegeState = 0
        scene.battle._runtime.constants.VEHICLE_SIEGE_STATE = types.SimpleNamespace(
            DISABLED=0, SWITCHING_ON=1, ENABLED=2, SWITCHING_OFF=3)
        scene.battle._local_speed = scene.battle._local_turn_speed = 0.
        return scene

    def echo(self, scene, state, sequence):
        record = scene.battle._records['player:1']
        # This fixture observes an already-presented native enum, allowing the
        # real snapshot consumer to exercise its pending/input-sequence fence
        # without substituting an invented descriptor/suspension transition.
        scene.entity.siegeState = state
        record['presented_siege_state'] = state
        row = dict(record['state'], siege_state=state, input_seq=sequence,
                   siege_time_left_ms=500 if state in (1, 3) else 0)
        record['state'] = row
        scene.battle._apply_siege_state(record, row)
        scene.observe()

    def test_real_siege_echo_releases_only_completed_or_rejected_request_for_next_mode(self):
        for final_state in (0, 2):
            with self.subTest(final_state=final_state):
                scene = self.siege_scene()
                self.assertTrue(scene.runtime._siege_request(True))
                token = scene.runtime._siege_pending
                sequence = token['sequence']
                self.assertEqual((True, sequence), scene.battle._local_siege_pending)
                self.echo(scene, 0, sequence - 1)
                self.assertIs(token, scene.runtime._siege_pending)
                self.echo(scene, 1, sequence)
                self.assertIs(token, scene.runtime._siege_pending)
                self.assertFalse(scene.runtime._siege_request(False))
                self.echo(scene, final_state, sequence)
                self.assertIsNone(scene.battle._local_siege_pending)
                self.assertIsNone(scene.runtime._siege_pending)
                self.assertTrue(scene.runtime._siege_request(final_state == 0))
                self.assertGreater(scene.runtime._siege_pending['sequence'], sequence)

    def test_manual_siege_replacement_keeps_its_native_request_until_its_own_echo(self):
        scene = self.siege_scene()
        self.assertTrue(scene.runtime._siege_request(True))
        self.assertTrue(scene.battle._change_local_siege(False))
        manual = scene.battle._local_siege_pending
        self.assertIsNone(scene.runtime._siege_pending)
        self.assertFalse(scene.runtime._siege_request(True))
        self.assertEqual(manual, scene.battle._local_siege_pending)
        self.echo(scene, 0, manual[1])
        self.assertTrue(scene.runtime._siege_request(True))


if __name__=='__main__':
    unittest.main()
