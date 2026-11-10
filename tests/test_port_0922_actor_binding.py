"""Shared control ownership with real worker weapon/reference state.

Native model/support observations are fixtures, not a claim of BigWorld
Windows acceptance. These tests forbid the worker observer's foreground gun
from being used as a controlled BOT's physical source.
"""
import contextlib
import io
import math
from types import SimpleNamespace
import unittest
from unittest import mock

import test_port_0922_bot_runtime as worker
import test_port_0922_battle_runtime as native


class ActorBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = worker.BotRuntimeTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)
        self.module = self.fixture.module
        descriptor = worker._combat_descriptor(clip=(2, .2), max_ammo=30)
        descriptor.type = SimpleNamespace(tags=('mediumTank',))
        descriptor.gun.shots = tuple(dict(
            shell=dict(kind=kind, effectsIndex=index, caliber=75., damage=(100., 100.)),
            speed=1000., gravity=10., maxDistance=5000., piercingPower=(200., 200.))
            for index, kind in enumerate(('ARMOR_PIERCING', 'ARMOR_PIERCING_CR', 'HIGH_EXPLOSIVE')))
        self.descriptor = descriptor
        self.engine = self.fixture.runtime
        self.engine.descriptor_resolver = lambda unused: descriptor
        self.engine.direct_launch_origin_probe = lambda source, *unused: (
            source['x'], source['y'] + 2., source['z'])
        start = dict(self.fixture.start, bots=[dict(id=11, team=2, slot=0, name='A'),
                                             dict(id=12, team=1, slot=1, name='B')])
        with contextlib.redirect_stdout(io.StringIO()):
            self.engine.battle_start(start)
        self.addCleanup(self.engine.close)
        self.entities, records = {}, {}
        for identity in (11, 12):
            state = self.engine.states[identity]
            state.update(x=float(identity), y=3., z=20., yaw=.1, pitch=.02,
                roll=.01, turret_yaw=.3, aim_yaw=.4, gun_pitch=-.03,
                airborne=False, vertical_speed=0., siege_state=0, gun_aligned=True)
            entity = SimpleNamespace(id=identity + 200, typeDescriptor=descriptor,
                isStarted=True, isAlive=lambda: True, siegeState=0)
            self.entities[entity.id] = entity
            records['bot:%s' % identity] = dict(engine_id=entity.id, kind='bot',
                ready=True, spot_visible=False, state=state)
            self.engine._ammo_states[identity].restore(dict(ammo_remaining=[10, 8, 6],
                shell_index=0, next_shell_index=0, ammo_reload_pending=False))
            self.engine._gun_states[identity].elapsed = 100.
        self.observer_reads = []
        def forbidden(*args, **kwargs):
            self.observer_reads.append((args, kwargs))
            raise AssertionError('BOT read the worker observer foreground source')
        self.battle = SimpleNamespace(_generation=7, _last_frame_time=0.,
            _clock=lambda: 0., _records=records, _server_entity=self.entities.get,
            _avatar=SimpleNamespace(spaceID=4), _config={},
            client=SimpleNamespace(team=1, player_id=1), _vector=native._Vector,
            _mutable_shot_ray=forbidden, _native_dispersion_angle=forbidden,
            _local_stabilised_pose=forbidden, local_pose=forbidden,
            _runtime=SimpleNamespace(math=SimpleNamespace(Matrix=native._RigidMatrix)))
        from gui.mods.offline_lan_0922.vehicle_control.bot_binding import BotControlBinding
        self.binding = BotControlBinding(self.battle, self.engine, 11)
        self.other = BotControlBinding(self.battle, self.engine, 12)
        self.addCleanup(self.binding.close)
        self.addCleanup(self.other.close)

    def test_worker_source_observation_is_own_native_actor_not_observer(self):
        from gui.mods.offline_lan_0922.vehicle_control.actor_observation import observation
        from gui.mods.offline_lan_0922.vehicle_control.attack_policy import native_source_pose
        self.assertIs(self.binding, observation(self.binding))
        self.assertEqual(2, self.binding.actor_team)
        self.assertEqual(211, self.binding.source_entity().id)
        pose = native_source_pose(self.binding)
        self.assertEqual((11., 3., 20.), pose[0])
        self.assertEqual((.1, .02, .01), pose[1])
        self.assertEqual((11., 5., 20.), pose[2])
        self.assertEqual((.3, -.03), pose[3])
        self.assertNotEqual(pose, self.other.source_pose())
        self.assertEqual([], self.observer_reads)

    def test_missing_worker_entity_fails_closed_without_local_fallback(self):
        from gui.mods.offline_lan_0922.vehicle_control.actor_observation import observation
        self.battle._records['bot:11']['ready'] = False
        self.assertIsNone(self.binding.source_entity())
        with self.assertRaises(ValueError):
            self.binding.mutable_shot_ray()
        result = self.binding.refine_order(dict(fire_allowed=True), (), 0.)
        self.assertFalse(result['fire_allowed'])
        self.assertEqual('native_actor_unavailable', result['control_pending'])
        with self.assertRaises(ValueError):
            observation(SimpleNamespace(actor_kind='bot', owner=self.battle))
        self.assertEqual([], self.observer_reads)

    def test_state_is_independent_but_combat_methods_have_one_owner(self):
        from gui.mods.offline_lan_0922.vehicle_control.combat_control import CombatControl
        from gui.mods.offline_lan_0922.vehicle_control.full_runtime import FullPlayerRuntime
        for name in ('_accept_combat_order', 'current_attack_candidate',
                     'prepare_trigger_context', 'point_recovery_probe', '_apply_next_shell',
                     '_siege_fire_ready',
                     '_observe_loading_completion'):
            self.assertIs(getattr(type(self.binding), name), getattr(CombatControl, name))
            self.assertIs(getattr(FullPlayerRuntime, name), getattr(CombatControl, name))
        self.assertIsNot(self.binding.attack_policy, self.other.attack_policy)
        self.assertIsNot(self.binding.combat_stop, self.other.combat_stop)
        self.binding._last_order['test_actor'] = 11
        self.assertNotIn('test_actor', self.other._last_order)

    def test_worker_point_recovery_only_requests_movement_inside_original_gate(self):
        target = dict(kind='bot', id=12, network_id=12, team=1,
                      alive=True, visible=True, health=1000,
                      position=(12., 3., 20.))
        self.assertTrue(self.binding.observe(1., [target]))
        route = dict(combat_mode='route', move_position=(20., 3., 40.),
                     throttle_override=None, target_id=None,
                     initial_target_hint=dict(target_kind='bot', target_id=12))
        self.binding.combat_stop.accept(dict(route, combat_mode='hold',
                                             throttle_override=0.))
        self.assertFalse(self.binding.combat_stop.can_request_movement)
        self.binding.combat_stop.accept(route)
        self.assertTrue(self.binding.combat_stop.can_request_movement)
        self.assertFalse(self.binding.combat_stop.stop_allowed)
        self.assertFalse(self.binding.combat_stop.combat_owned)
        # The shared point probe is available to worker and foreground, but
        # only a checked proposal may acquire an actual movement task.
        self.assertIsNotNone(self.binding.point_recovery_probe)
        self.assertFalse(hasattr(self.binding, 'attack_search_drive_available'))
        self.binding._mission = dict(capture_started=True)
        self.binding.combat_stop.accept(route)
        self.assertFalse(self.binding.combat_stop.can_request_movement)
        self.binding._mission = dict(explicit=True, destination=(20., 0., 20.))
        self.binding.combat_stop.accept(route)
        self.assertFalse(self.binding.combat_stop.can_request_movement)
        self.binding._mission = None
        self.binding.combat_stop.accept(route)
        self.assertTrue(self.binding.combat_stop.can_request_movement)
        self.binding._implicit_retry = dict(at=1.)
        self.assertFalse(self.binding.combat_stop.stop_allowed)

    def test_shared_mode_gate_reads_worker_native_mode_not_observer_echo(self):
        from gui.mods.offline_lan_0922 import siege_mechanics
        self.descriptor.hasSiegeMode = True
        self.binding.source_entity().siegeState = siege_mechanics.DISABLED
        self.binding.state['siege_state'] = siege_mechanics.ENABLED
        self.battle._local_siege_pending = (False, 77)
        self.assertTrue(self.binding._siege_fire_ready())
        self.binding._siege_pending = dict(enabled=False)
        self.assertFalse(self.binding._siege_fire_ready())
        self.binding._siege_pending = None
        for mode in (siege_mechanics.DISABLED, siege_mechanics.SWITCHING_ON,
                     siege_mechanics.SWITCHING_OFF):
            self.binding.state['siege_state'] = mode
            self.assertFalse(self.binding._siege_fire_ready())

    def test_worker_refine_order_dispatches_the_shared_combat_owner(self):
        from gui.mods.offline_lan_0922.vehicle_control.combat_control import CombatControl
        expected = dict(combat_mode='shared', fire_allowed=False)
        with mock.patch.object(CombatControl, '_accept_combat_order',
                               autospec=True, return_value=expected) as shared:
            actual = self.binding.refine_order(dict(combat_mode='advance'), (), 3.)
        self.assertIs(expected, actual)
        shared.assert_called_once_with(self.binding, dict(combat_mode='advance'), 3.)

    def _prepare_spg_cadence_scene(self):
        engine, binding = self.engine, self.binding
        engine.states.pop(12)
        state = engine.states[11]
        state.update(x=0., y=0., z=0., speed=0., yaw=0., pitch=0., roll=0.)
        state['profile']['class_tag'] = 'SPG'
        engine._ammo_states[11].restore(dict(ammo_remaining=[0, 0, 6],
            shell_index=2, next_shell_index=2, ammo_reload_pending=False))
        engine._actor_controls = {11: binding}
        engine._planning_detail_tier = lambda unused: 2
        engine.adapter = worker._FixedAdapter(dict(target_id=None,
            target_yaw=0., throttle=0., turn=0., shell_index=2,
            fire_allowed=False, fire_range=500., combat_mode='route',
            move_position=(0., 0., 0.), aim_position=None))
        contacts = [dict(kind='bot', id=identity, network_id=identity,
            team=1, alive=True, visible=True, position=(float(identity), 0., 100.),
            yaw=0., speed=0.) for identity in range(100, 105)]
        engine._contacts_for = lambda *unused: (
            contacts, dict((row['id'], row) for row in contacts))

    def test_spg_reviews_each_control_refresh_with_same_bounded_frontier(self):
        from gui.mods.offline_lan_0922.vehicle_control.artillery_selection import ArtillerySelection
        self._prepare_spg_cadence_scene()
        reviewed, control_times = [], []
        def review(runtime, frame, target, now):
            reviewed.append((now, target['id']))
            return dict(status='pending', reason='arc_pending')
        # Keep real BotRuntime update, shared order dispatch, source frame and
        # bounded acquisition. Only the asynchronous native arc answer is a
        # pending fixture; no test-only selector drives the loop.
        with mock.patch.object(ArtillerySelection, '_review', side_effect=review), \
                contextlib.redirect_stdout(io.StringIO()):
            for index in range(12):
                control_now = index * .05 + .04
                control_times.append(control_now)
                self.engine._run_update_once(.04, control_now, [], [], True, True)
                self.engine._run_update_once(.01, index * .05 + .05,
                                             [], [], False, True)
        self.assertFalse(self.binding.combat_stop.active)
        self.assertEqual(24, len(reviewed))
        self.assertEqual(set(range(100, 105)), set(row[1] for row in reviewed))
        for now in control_times:
            self.assertEqual(2, sum(row[0] == now for row in reviewed))
        self.assertEqual(2, self.binding.artillery_selection.receipt['reviewed'])

    def test_spg_without_auto_fire_keeps_strategy_cadence(self):
        self._prepare_spg_cadence_scene()
        self.binding.features = frozenset(('drive',))
        with mock.patch.object(self.binding, 'refine_order',
                wraps=self.binding.refine_order) as refine, \
                contextlib.redirect_stdout(io.StringIO()):
            for index in range(1, 13):
                self.engine._run_update_once(.05, index * .05, [], [], True, True)
        self.assertEqual(1, refine.call_count)
        self.assertFalse(hasattr(self.binding, 'artillery_selection'))

    def test_next_shell_is_queued_input_not_early_native_reload_promotion(self):
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        before = (list(ammo.remaining), gun.native.elapsed, gun.clip)
        self.assertTrue(self.binding._shell_setting('NEXT_SHELLS', 1))
        self.assertEqual(1, gun.pending_index)
        self.assertEqual(0, ammo.loaded)
        self.assertEqual(0, ammo.next)
        self.assertEqual(0, self.binding.physical_shell_request())
        for unused in range(3):
            ammo.stage(self.binding.physical_shell_request(), True, full_reload=True)
        self.assertEqual(0, ammo.loaded)
        self.assertEqual(before, (list(ammo.remaining), gun.native.elapsed, gun.clip))
        self.assertEqual(1, self.binding.state['next_shell_index'])

    def test_current_shell_is_native_input_and_never_debits_ammunition(self):
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        before = list(ammo.remaining)
        self.assertTrue(self.binding._shell_setting('CURRENT_SHELLS', 1))
        self.assertEqual(1, ammo.loaded)
        self.assertEqual(1, ammo.next)
        self.assertTrue(ammo.reload_pending)
        self.assertEqual(0, gun.native.elapsed)
        self.assertEqual(0, gun.clip)
        self.assertGreater(gun.reload_time, 0.)
        self.assertEqual(before, ammo.remaining)
        self.assertEqual(0, self.other.gun.shot_index)

    def test_completed_load_can_fire_and_switch_in_next_reload_same_slice(self):
        self.descriptor.gun.clip = (1, .2)
        native_gun = self.module._BotGunState(self.descriptor,
            crew_level=self.engine.bot_crew_level(11))
        self.engine._gun_states[11] = native_gun
        native_gun.elapsed = 100.
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        ammo.restore(dict(ammo_remaining=[10, 1, 6], shell_index=0,
                          next_shell_index=0, ammo_reload_pending=False))
        self.binding.combat_stop.active = True
        self.binding.attack_policy.decision = dict(action='switch_shell',
            reason='current_shell_all_armour_failed', candidate=None, shell_index=1)
        self.binding._apply_shell_intent()
        self.assertEqual(1, gun.shot_index)
        self.assertIs(gun, self.binding._loading_switch)
        self.assertGreater(gun.reload_time, 0.)
        factor = self.binding.reload_factor()
        native_gun.tick(native_gun.duration(factor) + .01)
        self.assertEqual('full', native_gun.complete_reload(factor, 1))
        ammo.stage(1, True, True)
        # This is the real pre-first-edge hook. The end-of-slice observation
        # will only see the *next* reload when readiness and firing coincide.
        self.binding.after_control(dict(throttle=0., turn=0.), None, 1.)
        self.assertIsNone(self.binding._loading_switch)
        self.assertTrue(native_gun.fire(factor))
        self.assertTrue(ammo.consume_loaded())
        self.assertEqual([10, 0, 6], ammo.remaining)
        self.assertGreater(gun.reload_time, 0.)
        self.binding.attack_policy.decision = dict(action='switch_shell',
            reason='current_ammunition_exhausted', candidate=None, shell_index=2)
        self.binding._apply_shell_intent()
        self.assertEqual(2, gun.shot_index)
        self.assertIs(gun, self.binding._loading_switch)
        self.assertEqual([10, 0, 6], ammo.remaining)

    def test_native_ready_observation_clears_switch_without_advancing_weapon(self):
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        gun.native.require_full_reload()
        gun.native.elapsed = 0.
        self.binding._loading_switch = gun
        self.binding.after_native_update(.01)
        self.assertIs(gun, self.binding._loading_switch)
        factor = self.binding.reload_factor()
        gun.native.tick(gun.native.duration(factor) + .01)
        gun.native.complete_reload(factor, ammo.remaining[ammo.loaded])
        ammo.stage(ammo.loaded, True, True)
        before = (list(ammo.remaining), gun.native.elapsed, gun.clip)
        self.binding.after_native_update(.02)
        self.assertIsNone(self.binding._loading_switch)
        self.assertEqual(before, (list(ammo.remaining), gun.native.elapsed, gun.clip))

    def test_final_native_load_edge_promotes_next_without_second_clock(self):
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        self.binding._shell_setting('NEXT_SHELLS', 1)
        self.assertTrue(ammo.consume_loaded())
        gun.native.require_full_reload()
        gun.native.elapsed = .1
        self.binding.shot_committed(dict(fire_seq=1, burst_index=0, burst_count=1))
        self.assertEqual([9, 8, 6], ammo.remaining)
        self.assertEqual(1, ammo.loaded)
        self.assertIsNone(gun.pending_index)
        self.assertEqual(.1, gun.native.elapsed)

    def test_final_native_load_edge_promotes_exhausted_stock_fallback(self):
        gun, ammo = self.binding.gun, self.binding._native_ammo()
        ammo.restore(dict(ammo_remaining=[1, 8, 6], shell_index=0,
                          next_shell_index=0, ammo_reload_pending=False))
        self.assertTrue(ammo.consume_loaded())
        fallback = ammo.next
        gun.native.require_full_reload()
        gun.native.elapsed = .1
        self.binding.shot_committed(dict(fire_seq=1, burst_index=0, burst_count=1))
        self.assertEqual(fallback, ammo.loaded)
        self.assertEqual([0, 8, 6], ammo.remaining)
        self.assertEqual(.1, gun.native.elapsed)

    def test_shared_proof_uses_actor_visibility_and_team_not_observer_team(self):
        target = dict(kind='bot', network_id=12, team=1, engine_id=212,
                      position=(12., 3., 20.), alive=True, visible=True)
        self.binding.observe(0., [target])
        admission = self.binding._admission()
        self.assertIs(self.entities[212], admission._target(dict(target=target)))
        self.binding.observe(0., [])
        self.assertIsNone(admission._target(dict(target=target)))
        self.binding.observe(0., [target])
        self.battle._records['bot:12']['tombstone'] = True
        self.assertIsNone(admission._target(dict(target=target)))

    def test_worker_scatter_is_exact_physical_draw_without_ai_error_layer(self):
        gun, state = self.binding.gun, self.binding.state
        actual = native._Vector((0., 0., 1.))
        def forbidden(*unused):
            raise AssertionError('second random draw was used')
        gun.scatter(actual, perfect_accuracy=True, gauss=forbidden, uniform=forbidden)
        sequence = int(state['fire_seq']) + 1
        yaw, pitch = self.module._dispersed_barrel_angles(11, self.engine.round_id,
            sequence, state['aim_yaw'], state['gun_pitch'],
            self.binding.native_dispersion_angle(), 0, sequence,
            base_direction=self.engine._dispersal_base_direction(state, self.descriptor))
        expected = (math.sin(yaw) * math.cos(pitch), math.sin(pitch),
                    math.cos(yaw) * math.cos(pitch))
        for measured, reference in zip(tuple(actual), expected):
            self.assertAlmostEqual(reference, measured, places=14)
        self.assertEqual((sequence, yaw, pitch), gun.last_scatter)
        self.assertEqual([], self.observer_reads)

    def test_controller_retirement_does_not_abort_native_trigger_tail(self):
        trigger, gun = self.engine._burst_states[11], self.binding.gun.native
        self.assertTrue(trigger.start(1, 2, .1, 0))
        self.assertTrue(gun.begin_burst(2, self.binding.reload_factor()))
        self.binding.close()
        self.assertTrue(trigger.active)
        self.assertEqual(2, gun._burst_remaining)

    def test_terminal_snapshot_retires_actor_controls_and_pending_proofs(self):
        from gui.mods.offline_lan_0922.vehicle_control.artillery_selection import ArtillerySelection
        self.engine._actor_controls = {11: self.binding, 12: self.other}
        self.binding.artillery_selection = ArtillerySelection()
        self.binding.artillery_selection.current = ('bot', 100)
        self.engine._control_launch_proofs[(self.engine.round_id, 11, 1)] = dict(
            fire_seq=1, shell_index=0)
        self.engine.apply_snapshot(dict(battle_result=dict(winner=1), bots=[]))
        self.assertTrue(self.engine.finished)
        self.assertTrue(self.binding.closed)
        self.assertTrue(self.other.closed)
        self.assertFalse(self.engine._actor_controls)
        self.assertFalse(self.engine._control_launch_proofs)
        self.assertIsNone(self.binding.artillery_selection.current)


class WorkerFirstEdgeAdmissionTests(unittest.TestCase):
    """The real shared BSP/native-plate proof with a worker source binding."""

    def setUp(self):
        import test_player_fire_admission_complete as scenes
        self.scene = scenes.AutomaticFireScene('runTest')
        with contextlib.redirect_stdout(io.StringIO()):
            self.scene.setUp()
        self.addCleanup(self.scene.doCleanups)
        self.battle = self.scene.battle
        from gui.mods.offline_lan_0922 import bot_runtime
        from gui.mods.offline_lan_0922.vehicle_control.bot_binding import BotControlBinding
        self.module = bot_runtime
        self.descriptor = self.scene.entity.typeDescriptor
        self.engine = bot_runtime.BotRuntime(1,
            descriptor_resolver=lambda unused: self.descriptor,
            adapter_factory=lambda *args, **kwargs: worker._FixedAdapter({}),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=worker._spawn_resolver, baked_graph=worker._graph(),
            direct_launch_origin_probe=lambda source, *unused: (
                source['x'], source['y'] + 2., source['z']))
        with contextlib.redirect_stdout(io.StringIO()):
            self.engine.battle_start(dict(round_id=7, map='01_karelia',
                bot_authority_id=1, bot_skill_mode='brutal',
                bots=[dict(id=11, team=1, slot=0, name='Physical worker actor'),
                      dict(id=12, team=1, slot=1, name='Second worker actor')]))
        self.addCleanup(self.engine.close)
        observed = dict(self.scene.runtime.state)
        self.engine.states[11].update(dict(observed, id=11, team=1,
            x=0., y=0., z=0., yaw=0., pitch=0., roll=0.,
            airborne=False, vertical_speed=0., siege_state=0, gun_aligned=True))
        self.state = self.engine.states[11]
        native_gun = self.engine._gun_states[11]
        native_gun.elapsed = 100.
        native_gun.fully_aimed_dispersion = native_gun.dispersion = 1.e-7
        self.engine._ammo_states[11].restore(dict(ammo_remaining=[20, 10],
            shell_index=0, next_shell_index=0, ammo_reload_pending=False))
        original = self.battle._records.pop('player:1')
        self.addCleanup(self.battle._records.__setitem__, 'player:1', original)
        self.battle._records['bot:11'] = dict(engine_id=self.scene.entity.id,
            ready=True, kind='bot', network_id=11, team=1, state=self.state,
            spot_visible=False)
        self.addCleanup(self.battle._records.pop, 'bot:11', None)
        self.binding = BotControlBinding(self.battle, self.engine, 11)
        self.engine._actor_controls[11] = self.binding
        worker_owner = mock.patch.object(self.battle, '_bots', self.engine)
        worker_owner.start()
        self.addCleanup(worker_owner.stop)
        self.addCleanup(self.binding.close)
        self.target = dict(self.scene.candidate['target'])
        self.binding.observe(self.scene.now, [self.target])
        solution = dict(self.scene.candidate['solution'], source_pose=self.binding.source_pose())
        self.candidate = dict(self.scene.candidate, solution=solution, target=self.target)
        self.binding.combat_stop.active = True
        self.binding.combat_stop.combat_owned = True
        self.binding.combat_stop.stop_allowed = True
        self.binding.combat_stop.targets = (self.target,)
        self.binding.attack_policy._choose('aim', 'observed_native_plate', self.candidate)
        self.binding.weapon.observe(dict(_ballistic_solution=solution), self.target)
        # NEXT selection itself is tested above and by the shared policy
        # suite. The fixture fixes only that unrelated background workload;
        # context admission, native matrices/BSP/plates and scatter are real.
        plan = mock.patch.object(self.binding, '_apply_next_shell', return_value=None)
        plan.start()
        self.addCleanup(plan.stop)
        self.observer_reads = []
        def forbidden(*args, **kwargs):
            self.observer_reads.append((args, kwargs))
            raise AssertionError('worker proof used observer foreground gun')
        for name in ('_mutable_shot_ray', '_native_dispersion_angle', 'local_pose'):
            item = mock.patch.object(self.battle, name, forbidden)
            item.start()
            self.addCleanup(item.stop)
        # Opposite to this BOT: source-scoped team checks must still succeed.
        self.battle.client.team = 2

    def prepare(self, receipt=None):
        verdict = None
        for unused in range(60):
            now = self.scene.now
            self.battle._last_frame_time = now
            verdict = self.binding.prepare_trigger(self.state, self.target,
                self.binding.weapon.solution, receipt, now)
            if verdict['status'] != 'pending' or verdict['reason'] not in (
                    'auto_proof_pending', 'auto_world_changed'):
                break
            self.scene.fixture.now += .06
        return verdict

    def fire(self, binding=None):
        binding = self.binding if binding is None else binding
        for unused in range(60):
            binding.now = self.scene.now
            self.battle._last_frame_time = self.scene.now
            with contextlib.redirect_stdout(io.StringIO()):
                accepted = self.engine._fire(binding.state, binding.gun.native,
                    binding.reload_factor(), binding.source_descriptor(),
                    ammo_state=binding._native_ammo(), launch_time_us=0)
            if accepted or binding._last_fire_failure not in (
                    'auto_proof_pending', 'auto_world_changed'):
                return accepted
            self.scene.fixture.now += .06
        return False

    def second_worker(self):
        from gui.mods.offline_lan_0922 import ballistics
        from gui.mods.offline_lan_0922.vehicle_control.bot_binding import BotControlBinding
        state = self.engine.states[12]
        state.update(dict(self.state, id=12, x=-20., fire_seq=0))
        point = self.candidate['solution']['point']
        origin = (-20., 2., 0.)
        shot = self.descriptor.gun.shots[0]
        pitch, flight = ballistics.ballistic_solutions(origin, point, shot.speed, shot.gravity)[0]
        yaw = math.atan2(point[0] - origin[0], point[2] - origin[2])
        state.update(aim_yaw=yaw, turret_yaw=yaw, gun_pitch=pitch)
        entity = self.scene.vehicle(212, (-20., 0., 0.), 1)
        entity.typeDescriptor = self.descriptor
        record = self.battle._records.pop('bot:212')
        record.update(network_id=12, state=state, spot_visible=False)
        self.battle._records['bot:12'] = record
        self.addCleanup(self.battle._records.pop, 'bot:12', None)
        gun = self.engine._gun_states[12]
        gun.elapsed = 100.
        gun.fully_aimed_dispersion = gun.dispersion = 1.e-7
        self.engine._ammo_states[12].restore(dict(ammo_remaining=[20, 10],
            shell_index=0, next_shell_index=0, ammo_reload_pending=False))
        binding = BotControlBinding(self.battle, self.engine, 12)
        self.engine._actor_controls[12] = binding
        self.addCleanup(binding.close)
        binding.observe(self.scene.now, [self.target])
        solution = dict(self.candidate['solution'], origin=origin, yaw=yaw,
            pitch=pitch, flight_time=flight, source_pose=binding.source_pose())
        candidate = dict(self.candidate, solution=solution)
        binding.combat_stop.active = binding.combat_stop.combat_owned = True
        binding.combat_stop.stop_allowed = True
        binding.combat_stop.targets = (self.target,)
        binding.attack_policy._choose('aim', 'observed_native_plate', candidate)
        binding.weapon.observe(dict(_ballistic_solution=solution), self.target)
        plan = mock.patch.object(binding, '_apply_next_shell', return_value=None)
        plan.start()
        self.addCleanup(plan.stop)
        return binding

    def test_worker_after_control_reports_same_stationary_aim_stall_as_player(self):
        self.state['gun_aligned'] = False
        self.state['_diagnostic_aim_intent'] = dict(
            turret_yaw=self.state['turret_yaw'] + .4,
            gun_pitch=self.state['gun_pitch'])
        command = dict(_ballistic_solution=self.binding.weapon.solution,
                       throttle=0., turn=0., path_clear=True)
        with mock.patch.object(self.binding.attack_policy, 'lay_stalled',
                               wraps=self.binding.attack_policy.lay_stalled) as stalled:
            self.binding.after_control(command, self.target, 1.)
            self.binding.after_control(command, self.target, 6.9)
            stalled.assert_not_called()
            self.binding.after_control(command, self.target, 7.1)
        stalled.assert_called_once_with(self.candidate, 7.1)
        self.assertIs(self.candidate, self.binding.attack_policy._lay_recovery[0])
        self.assertIsNone(self.binding._attack_lay)

    def test_worker_aim_progress_motion_and_alignment_reset_shared_stall_clock(self):
        self.state['gun_aligned'] = False
        self.state['_diagnostic_aim_intent'] = dict(
            turret_yaw=self.state['turret_yaw'] + .4,
            gun_pitch=self.state['gun_pitch'])
        command = dict(_ballistic_solution=self.binding.weapon.solution,
                       throttle=0., turn=0., path_clear=True)
        with mock.patch.object(self.binding.attack_policy, 'lay_stalled',
                               wraps=self.binding.attack_policy.lay_stalled) as stalled:
            self.binding.after_control(command, self.target, 1.)
            self.state['turret_yaw'] += .1
            self.binding.after_control(command, self.target, 5.)
            self.binding.after_control(command, self.target, 7.1)
            self.state['x'] += .5
            self.binding.after_control(command, self.target, 10.)
            self.state['gun_aligned'] = True
            self.binding.after_control(command, self.target, 15.)
            self.assertIsNone(self.binding._attack_lay)
            self.state['gun_aligned'] = False
            self.binding.after_control(command, self.target, 20.)
            self.binding.after_control(command, self.target, 25.9)
            stalled.assert_not_called()
            self.binding.after_control(command, self.target, 26.1)
        stalled.assert_called_once_with(self.candidate, 26.1)

    def test_actual_runtime_first_edge_debits_native_weapon_and_notifies_once(self):
        before = self.binding.gun.clip
        with mock.patch.object(self.binding, 'shot_committed',
                               wraps=self.binding.shot_committed) as committed:
            self.assertTrue(self.fire(), self.binding._admission().receipt)
        committed.assert_called_once()
        self.assertEqual([19, 10], self.binding.gun.ammo)
        self.assertEqual(before - 1, self.binding.gun.clip)
        self.assertEqual(1, self.state['fire_seq'])
        self.assertEqual(1, len(self.engine._pending_launches))
        proof = self.engine._control_launch_proofs[(7, 11, 1)]
        launch = self.engine._pending_launches[0]
        self.assertEqual(proof['origin'], launch['shot_origin'])
        self.assertEqual(proof['shot_yaw'], launch['shot_yaw'])
        self.assertEqual(proof['shot_pitch'], launch['shot_pitch'])
        self.assertEqual('committed', self.binding._admission().receipt['status'])
        self.assertFalse(self.binding.fire_intent_active())

    def test_actual_runtime_rejected_shared_lane_never_debits_or_starts_trigger(self):
        self.scene.vehicle(43, (0., 0., 50.), 1)
        before = (self.binding.gun.clip, self.binding.gun.native.elapsed)
        with mock.patch.object(self.binding, 'shot_committed',
                               wraps=self.binding.shot_committed) as committed:
            self.assertFalse(self.fire())
        committed.assert_not_called()
        self.assertEqual('auto_friendly_lane', self.binding._last_fire_failure)
        self.assertEqual([20, 10], self.binding.gun.ammo)
        self.assertEqual(before, (self.binding.gun.clip, self.binding.gun.native.elapsed))
        self.assertFalse(self.engine._burst_states[11].active)
        self.assertFalse(self.engine._pending_launches)
        self.assertFalse(self.engine._control_launch_proofs)

    def test_actual_runtime_failed_begin_keeps_unspent_weapon_and_can_retry(self):
        with mock.patch.object(self.binding.gun.native, 'begin_burst', return_value=False):
            self.assertFalse(self.fire())
        self.assertEqual('native_gun_not_ready', self.binding._last_fire_failure)
        self.assertFalse(self.engine._burst_states[11].active)
        self.assertFalse(self.engine._pending_launches)
        self.assertFalse(self.engine._control_launch_proofs)
        self.assertEqual([20, 10], self.binding.gun.ammo)
        self.assertIsNone(self.binding._trigger_context)
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        self.assertEqual([19, 10], self.binding.gun.ammo)

    def test_native_begin_reentry_cannot_commit_a_different_source_pose(self):
        begin = self.binding.gun.native.begin_burst
        def reentered(count, factor):
            accepted = begin(count, factor)
            self.state['x'] += .25
            return accepted
        with mock.patch.object(self.binding.gun.native, 'begin_burst', reentered):
            self.assertFalse(self.fire())
        self.assertEqual([20, 10], self.binding.gun.ammo)
        self.assertFalse(self.engine._pending_launches)
        self.assertFalse(self.engine._control_launch_proofs)
        self.assertFalse(self.engine._burst_states[11].active)

    def test_existing_native_tail_survives_later_target_loss_and_fire_refusal(self):
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        self.assertTrue(self.engine._burst_states[11].active)
        self.binding._targets = ()
        self.state['gun_aligned'] = False
        self.assertFalse(self.fire())
        self.assertTrue(self.engine._burst_states[11].active)
        with contextlib.redirect_stdout(io.StringIO()):
            committed = self.engine._advance_active_burst(self.state,
                self.binding.gun.native, self.binding._native_ammo(),
                self.binding.reload_factor(), self.descriptor, None, None, .3, ())
        self.assertEqual(2, committed)
        self.assertEqual([17, 10], self.binding.gun.ammo)
        self.assertEqual(3, len(self.engine._pending_launches))
        self.assertFalse(self.engine._burst_states[11].active)

    def test_actual_last_edge_promotes_next_load_without_changing_frozen_shell(self):
        self.binding.gun.native.clip = 3
        self.assertTrue(self.binding._shell_setting('NEXT_SHELLS', 1))
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        self.assertEqual(0, self.binding.gun.shot_index)
        with mock.patch.object(self.binding.attack_policy, 'load_started',
                               wraps=self.binding.attack_policy.load_started) as loaded:
            with contextlib.redirect_stdout(io.StringIO()):
                self.engine._advance_active_burst(self.state, self.binding.gun.native,
                    self.binding._native_ammo(), self.binding.reload_factor(),
                    self.descriptor, None, None, .3, ())
        self.assertEqual(1, self.binding.gun.shot_index)
        self.assertEqual(0, self.binding.gun.clip)
        self.assertGreater(self.binding.gun.reload_time, 0.)
        self.assertEqual([17, 10], self.binding.gun.ammo)
        self.assertEqual([0, 0, 0], [row['shell_index'] for row in self.engine._pending_launches])
        loaded.assert_called_once_with(1, None)

    def test_two_real_workers_keep_independent_trigger_proofs_and_native_ammo(self):
        second = self.second_worker()
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        self.assertEqual([19, 10], self.binding.gun.ammo)
        self.assertEqual([20, 10], second.gun.ammo)
        self.assertTrue(self.fire(second), second._admission().receipt)
        self.assertEqual([19, 10], second.gun.ammo)
        self.assertEqual([19, 10], self.binding.gun.ammo)
        self.assertIsNot(self.binding._trigger_context, second._trigger_context)
        first = self.engine._control_launch_proofs[(7, 11, 1)]
        other = self.engine._control_launch_proofs[(7, 12, 1)]
        self.assertNotEqual(first['origin'], other['origin'])
        self.assertNotEqual(first['shot_yaw'], other['shot_yaw'])

    def test_bot_publish_freezes_first_edge_and_retries_without_resampling(self):
        from gui.mods.offline_lan_0922 import combat_rules
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        launch = self.engine._pending_launches[0]
        proof = self.engine._control_launch_proofs[(7, 11, 1)]
        with mock.patch.object(self.battle.client, 'send_projectile_launch',
                               side_effect=[None, 1]) as send, \
                mock.patch.object(combat_rules, 'sample_penetration_factor',
                                  side_effect=AssertionError('second physical penetration draw')):
            self.assertFalse(self.battle._launch_bot_projectile(launch, 1))
            frozen = self.battle._bot_launch_payloads[(11, 1)]
            self.assertNotIn((7, 11, 1), self.engine._control_launch_proofs)
            self.assertEqual(list(proof['origin']), frozen[0][4])
            self.assertEqual(list(proof['velocity']), frozen[0][5])
            self.assertEqual(proof['penetration_factor'], frozen[1]['penetration_factor'])
            self.assertEqual(proof['source_shot'], frozen[1]['source_shot'])
            # Publication retries are frozen even after the actual weapon
            # has changed configuration or its source has disappeared.
            self.descriptor.gun.shots[0].speed *= 2.
            self.battle._records['bot:11']['ready'] = False
            self.assertTrue(self.battle._launch_bot_projectile(launch, 1))
        self.assertEqual(send.call_args_list[0], send.call_args_list[1])
        self.assertEqual([19, 10], self.binding.gun.ammo)

    def test_committed_first_edge_survives_source_unload_and_ack_cleans_queues(self):
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        launch = dict(self.engine._pending_launches[0])
        proof = dict(self.engine._control_launch_proofs[(7, 11, 1)])
        ammo = list(self.binding.gun.ammo)
        actor_entity_id = self.binding.source_entity().id
        native_entity = self.battle._server_entity
        def unloaded_source(identity):
            return None if identity == actor_entity_id else native_entity(identity)
        with mock.patch.object(self.battle, '_server_entity', side_effect=unloaded_source), \
                mock.patch.object(self.battle.client, 'send_projectile_launch',
                                  return_value=1) as send, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(self.binding.source_entity())
            self.assertTrue(self.battle._launch_bot_projectile(launch, 1))
            self.assertEqual(list(proof['origin']), send.call_args.args[4])
            self.assertEqual(list(proof['velocity']), send.call_args.args[5])
            self.assertEqual(proof['source_shot'], send.call_args.kwargs['source_shot'])
            self.assertEqual(proof['penetration_factor'],
                             send.call_args.kwargs['penetration_factor'])
            confirmed = dict(shooter_kind='bot', shooter_id=11, shot_seq=1)
            self.assertTrue(self.battle._confirm_bot_projectile_launch(confirmed))
            self.assertTrue(self.battle._confirm_bot_projectile_launch(confirmed))
        self.assertEqual(1, send.call_count)
        self.assertEqual(ammo, self.binding.gun.ammo)
        self.assertFalse(self.engine._control_launch_proofs)
        self.assertFalse(self.engine._pending_launches)
        self.assertFalse(self.engine._pending_launch_keys)
        self.assertFalse(self.engine._pending_launch_by_bot)
        self.assertFalse(self.battle._bot_launch_payloads)

    def test_bot_publish_mismatched_first_edge_is_refused_with_proof_retained(self):
        from gui.mods.offline_lan_0922 import combat_rules
        self.assertTrue(self.fire(), self.binding._admission().receipt)
        launch = self.engine._pending_launches[0]
        changed = (
            dict(launch, shot_yaw=launch['shot_yaw'] + .01),
            dict(launch, shot_origin=(1., 2., 0.)),
            dict(launch, shell_index=1),
        )
        with mock.patch.object(self.battle.client, 'send_projectile_launch', return_value=1) as send, \
                mock.patch.object(combat_rules, 'sample_penetration_factor',
                                  side_effect=AssertionError('unproved replacement sample')):
            for stale in changed:
                self.assertFalse(self.battle._launch_bot_projectile(stale, 1))
                self.assertIn((7, 11, 1), self.engine._control_launch_proofs)
                self.assertNotIn((11, 1), self.battle._bot_launch_payloads)
            send.assert_not_called()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(self.battle._launch_bot_projectile(launch, 1))
        send.assert_called_once()

    def test_complete_worker_proof_preserves_exact_native_draw_and_launch(self):
        proposal = self.prepare()
        self.assertEqual('ready', proposal['status'], proposal)
        self.assertIsNone(self.binding.validate_trigger(proposal, self.scene.now))
        self.assertEqual(1, proposal['fire_seq'])
        self.assertEqual(self.binding.gun.last_scatter[1:],
                         (proposal['shot_yaw'], proposal['shot_pitch']))
        self.assertEqual(proposal['token']['proof']['velocity'], proposal['velocity'])
        self.assertEqual(proposal['token']['penetration_factor'], proposal['penetration_factor'])
        self.assertTrue(self.scene.world_queries)
        self.assertGreater(proposal['target_queries'], 0)
        self.assertEqual([], self.observer_reads)
        self.assertEqual([20, 10], self.binding.gun.ammo)

    def test_native_source_change_after_proof_refuses_first_edge(self):
        proposal = self.prepare()
        self.assertEqual('ready', proposal['status'], proposal)
        self.state['x'] += .25
        self.assertEqual('auto_pose_changed',
                         self.binding.validate_trigger(proposal, self.scene.now))
        self.assertEqual([20, 10], self.binding.gun.ammo)
        self.assertEqual([], self.observer_reads)

    def test_first_edge_failure_drops_context_not_a_running_native_tail(self):
        proposal = self.prepare()
        self.assertEqual('ready', proposal['status'], proposal)
        self.assertTrue(self.binding.trigger_started(proposal))
        self.assertTrue(self.binding.fire_intent_active())
        self.binding.fire_rejected('native_begin_failed')
        self.assertFalse(self.binding.fire_intent_active())
        self.assertIsNone(self.binding._trigger_context)
        self.assertIs(proposal['token'], self.binding._admission().pending)
        self.assertEqual([20, 10], self.binding.gun.ammo)

    def test_actual_worker_friend_hull_blocks_shared_first_edge(self):
        self.scene.vehicle(43, (0., 0., 50.), 1)
        proposal = self.prepare()
        self.assertEqual('pending', proposal['status'])
        self.assertEqual('auto_friendly_lane', proposal['reason'])
        self.assertEqual([20, 10], self.binding.gun.ammo)
        self.assertEqual([], self.observer_reads)

    def high_arc_sample(self):
        from gui.mods.offline_lan_0922 import ballistics
        self.descriptor.type.tags = ('SPG',)
        self.descriptor.gun.pitchLimits.update(absolute=(-1.5, .2),
            minPitch=((0., -1.5), (2.*math.pi, -1.5)),
            maxPitch=((0., .2), (2.*math.pi, .2)))
        shot = self.descriptor.gun.shots[0]
        shot.speed, shot.gravity = 50., 10.
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 3.
        self.scene.pose(self.scene.target, (0., 0., 200.))
        self.target.update(position=(0., 0., 200.), x=0., y=0., z=200.)
        self.scene.world = [((-100., -10., 99.), (100., 60., 101.))]
        self.state['profile'] = dict(self.state['profile'], class_tag='SPG')
        self.state['class_tag'] = 'SPG'
        point = (0., 1., 200.)
        roots = ballistics.ballistic_solutions(self.scene.origin, point, 50., 10.)
        pitch, flight = roots[-1]
        self.assertLess(pitch, -1.)
        self.state.update(aim_yaw=0., turret_yaw=0., gun_pitch=pitch)
        solution = dict(aim_position=point, point=point, yaw=0., pitch=pitch,
            origin=self.scene.origin, speed=50., gravity=10., max_distance=5000.,
            flight_time=flight, arc='high')
        self.engine._artillery_intents[11] = dict(solution=solution)
        self.binding.combat_stop.active = False
        self.binding.attack_policy.decision = dict(action='unchanged', candidate=None)
        self.binding.weapon.observe(dict(_ballistic_solution=solution), self.target)
        self.binding.observe(self.scene.now, [self.target])
        sample = self.engine._direct_launch_preview(
            self.state, self.descriptor, 0, self.binding.gun.native, solution)
        self.assertIsNotNone(sample)
        return sample

    def test_spg_keeps_native_high_arc_and_same_deterministic_launch_sample(self):
        from gui.mods.offline_lan_0922.projectile_wire import round_scalar
        sample = self.high_arc_sample()
        proposal = self.prepare(sample)
        self.assertEqual('ready', proposal['status'], proposal)
        self.assertIs(sample, proposal['artillery_receipt'])
        self.assertEqual(sample['shot_yaw'], proposal['shot_yaw'])
        self.assertEqual(sample['shot_pitch'], proposal['shot_pitch'])
        self.assertEqual(tuple(round_scalar(value) for value in sample['origin']), proposal['origin'])
        self.assertIsNone(self.binding.validate_trigger(proposal, self.scene.now))
        self.assertEqual([], self.observer_reads)

    def test_spg_actual_native_commit_publishes_the_same_proved_high_arc(self):
        from gui.mods.offline_lan_0922 import artillery_controller, combat_rules
        sample = self.high_arc_sample()
        # Use the original exact launch queue against the real fixture BSP,
        # including the ridge. No fabricated successful SPG receipt.
        controller = artillery_controller.ArtilleryController()
        receipt = None
        for unused in range(60):
            ready, receipt = controller.request_launch(self.state, self.target,
                self.descriptor, 0, 1, sample['origin'], sample['shot_yaw'],
                sample['shot_pitch'], sample['flight_time'], self.scene.now)
            if ready:
                break
            self.battle._last_frame_time = self.scene.now
            controller.advance(self.scene.now, 32, self.battle._artillery_arc_probe)
            self.scene.fixture.now += .03
        self.assertIsNotNone(receipt, controller.status(self.state, self.target, 0, self.scene.now))
        for unused in range(60):
            self.binding.now = self.scene.now
            with contextlib.redirect_stdout(io.StringIO()):
                accepted = self.engine._fire(self.state, self.binding.gun.native,
                    self.binding.reload_factor(), self.descriptor,
                    launch_receipt=receipt, ammo_state=self.binding._native_ammo(),
                    launch_time_us=0)
            if accepted or self.binding._last_fire_failure not in (
                    'auto_proof_pending', 'auto_world_changed'):
                break
            self.scene.fixture.now += .06
        self.assertTrue(accepted, self.binding._admission().receipt)
        self.assertEqual([19, 10], self.binding.gun.ammo)
        launch = self.engine._pending_launches[0]
        proof = self.engine._control_launch_proofs[(7, 11, 1)]
        self.assertEqual(receipt['proof_key'], launch['shot_proof_key'])
        self.assertEqual(receipt['velocity'], launch['shot_velocity'])
        self.assertEqual(proof['shot_pitch'], launch['shot_pitch'])
        with mock.patch.object(self.battle.client, 'send_projectile_launch', return_value=1) as send, \
                mock.patch.object(combat_rules, 'sample_penetration_factor',
                                  side_effect=AssertionError('second SPG penetration draw')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(self.battle._launch_bot_projectile(launch, 1))
        self.assertEqual(list(proof['origin']), send.call_args.args[4])
        self.assertEqual(list(proof['velocity']), send.call_args.args[5])
        self.assertEqual(proof['penetration_factor'], send.call_args.kwargs['penetration_factor'])


if __name__ == '__main__':
    unittest.main()
