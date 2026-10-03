"""Cold spawn registries, continuous Bot tree sweeps and blocked responders.

The report supplies actor positions and the pinned catalog supplies geometry.
Native streaming/destruction are controlled contracts, not Windows acceptance.
"""
import contextlib
import sys
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as runtime_fixture
import test_port_0922_destructibles as destructible_fixture
import test_port_0922_server_bot_ai as server_fixture
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class AirfieldSpawnTests(unittest.TestCase):
    def setUp(self):
        self.cleanup = destructible_fixture.DestructiblesCompatibilityTests()
        self.cleanup.setUp()
        self.addCleanup(self.cleanup.tearDown)
        sensor.xrange = range

    @contextlib.contextmanager
    def tree_scene(self, streamed=True):
        vector = destructible_fixture._Vector
        scene = self.cleanup._tree_motion_fixture((vector(0, 0, 0),), streamed=streamed)
        manager, area, bigworld, math_module, tree_descriptor, authority, destroyed, calls = scene
        battle = runtime_fixture.BattleRuntime(runtime_fixture._runtime())
        battle._worker_mode = True
        battle._avatar = types.SimpleNamespace(spaceID=1)
        battle._destructibles = sensor
        battle._runtime.bigworld = bigworld
        battle._runtime.math = math_module
        states = [dict(id=i, x=0., y=0., z=-2., yaw=0., alive=True,
                       movement_dir=1, rotation_dir=0) for i in (8, 18, 25, 30)]
        battle._bots = types.SimpleNamespace(
            states={s['id']: s for s in states},
            _ordered_states=lambda: states,
            _descriptors={s['id']: tree_descriptor for s in states},
            _turn_speeds={}, motion_world_corridor_reusable=lambda *unused: True)
        battle._records = {'bot:%d' % s['id']: dict(ready=True) for s in states}
        with mock.patch.dict(sys.modules, {'AreaDestructibles': area,
                'BigWorld': bigworld, 'Math': math_module}), \
                mock.patch.object(sensor, '_get_destr_authority', return_value=authority), \
                mock.patch.object(sensor, '_catalog_hull_contact', return_value=False), \
                mock.patch.object(sensor, '_catalog_motion_blocked',
                    return_value={'status': 'clear'}), \
                mock.patch.object(battle, '_report_local_tree_motion'), \
                mock.patch.object(sys, 'stdout', mock.Mock()):
            yield battle, tree_descriptor, manager, calls

    def test_idle_spawn_prewarm_retries_after_streaming_without_destroy(self):
        with self.tree_scene(streamed=False) as (battle, unused_desc, manager, calls):
            first = battle._prewarm_bot_destructible_registries(1.)
            manager.onChunkLoad(22, 1)
            second = battle._prewarm_bot_destructible_registries(1.1)
            self.assertEqual(0, first)
            self.assertEqual(2, second)
            self.assertEqual([], calls)
            self.assertEqual(1, sensor.g_offh_tree_state['chunks'][22]['count'])

    def test_spawn_warming_visits_both_teams_and_does_not_require_speed(self):
        with self.tree_scene() as (battle, unused_desc, unused_mgr, calls):
            with mock.patch.object(sensor, 'prewarm_tree_registry',
                                   return_value={'status': 'ready'}) as warm:
                for unused in range(2):
                    battle._prewarm_bot_destructible_registries(1.)
                self.assertEqual(4, warm.call_count)
            self.assertEqual([], calls)
            self.assertEqual(0, battle._bot_registry_cursor)

    def test_cached_clear_corridor_still_fells_crossed_tree_once(self):
        with self.tree_scene() as (battle, desc, unused_mgr, calls):
            # Neither endpoint contains the tree. A final-pose scanner misses
            # this contact even though the continuous realised hull crosses it.
            first = battle._resolve_bot_motion(8, (0., 0., -2.), 0., 20., desc, .2, 1.)
            second = battle._resolve_bot_motion(8, (0., 0., -2.), 0., 20., desc, .2, 1.1)
            self.assertEqual('crushed', first)
            self.assertEqual('clear', second)
            self.assertEqual(1, len(calls))
            self.assertEqual((1, 22, 0), calls[0][:3])

    def test_candidate_probe_never_fells_tree(self):
        with self.tree_scene() as (battle, desc, unused_mgr, calls):
            self.assertEqual('clear', battle._resolve_bot_motion(
                8, (0., 0., -2.), 0., 20., desc, .2, 1., commit_enabled=False))
            self.assertEqual([], calls)

    def test_unstreamed_tree_registry_holds_softly_and_recovers(self):
        with self.tree_scene(streamed=False) as (battle, desc, manager, calls):
            self.assertEqual('soft', battle._resolve_bot_motion(
                8, (0., 0., -2.), 0., 20., desc, .2, 1.))
            self.assertEqual([], calls)
            manager.onChunkLoad(22, 1)
            self.assertEqual('crushed', battle._resolve_bot_motion(
                8, (0., 0., -2.), 0., 20., desc, .2, 1.1))

    def test_navigation_wait_is_bounded_but_escape_still_checks_walls(self):
        adapter = BotAdapter('31_airfield', 1,
                             navigation_target=lambda bot, pos, *unused: pos)
        state = dict(id=25, slot=9, team=2, position=(-295.6, 0., -176.9),
                     yaw=0., speed=0., dt=.1, neighbours=[], half_length=3.6,
                     half_width=1.8, pose_clear=lambda unused: True)
        order = dict(combat_mode='route', move_position=(-318., 0., -134.),
                     throttle_override=None)
        commands = [adapter.decide_with_order(state, order, lambda *unused: True)
                    for unused in range(120)]
        self.assertTrue(all(c['recovery_mode'] == 'nav_wait' for c in commands[:70]))
        self.assertTrue(any(c['throttle'] != 0. or c['turn'] != 0.
                            for c in commands[85:]))
        for unused in range(30):
            command = adapter.decide_with_order(state, order, lambda *unused: False)
            self.assertEqual(0., command['throttle'])

    def test_bot_pivot_checks_real_static_wall_before_any_structure_breaks(self):
        runtime = runtime_fixture._runtime()
        battle = runtime_fixture.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._bots = types.SimpleNamespace(states={25: {'alive': True}})
        battle._destructibles = types.SimpleNamespace(
            native_replacement_bsp_active=lambda: False,
            _vehicle_body_bbox=lambda unused: (
                (-1.7, -.4, -3.5), (1.7, 1.8, 3.2), None))
        battle._destructible_pose_sweep = mock.Mock(return_value={
            'status': 'clear', 'requires_commit': False})
        with mock.patch('gui.mods.offline_lan_0922.battle_runtime.'
                'world_collision.check_horizontal_collision',
                side_effect=('clear', 'hard')) as native:
            self.assertFalse(battle._resolve_bot_rotation(
                25, (-295.6, 0., -176.9), 0., .04,
                runtime_fixture._Descriptor(), .1, 1., 0.))
        self.assertEqual(2, native.call_count)
        self.assertEqual('world', battle._bot_motion_kinds[25])

    def test_contact_name_budget_serves_touching_prop_before_same_bin_models(self):
        near = (33405, 70)
        distant = [(33405, i) for i in range(4)]
        hull = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)))
        far = ((12., 0., 12.), hull[1], None)
        catalog = dict(has_instance_index=True,
                       baked_shot_bins={(0, 0): set([near] + distant)},
                       baked_instances={near: {'boxes': (hull + (None,),)}})
        catalog['baked_instances'].update({wire: {'boxes': (far,)} for wire in distant})
        visited = []
        with mock.patch.object(sensor, '_destructible_catalog', catalog), \
                mock.patch.object(sensor, '_baked_bin_keys_for_bounds_1513', return_value=[(0, 0)]), \
                mock.patch.object(sensor, '_stream_baked_shot_instance_1513',
                                  side_effect=lambda space, wire: visited.append(wire)), \
                mock.patch.object(sensor, '_confirmed_unresolved_obstacle_1513', return_value=()):
            sensor._stream_baked_motion_instances_1513(1, hull)
        self.assertEqual(near, visited[0])

    def test_blocked_base_responder_is_replaced_while_arrived_one_is_retained(self):
        planner = server_fixture.BotPlanner()
        route = server_fixture._route('field', [(0, -300, False), (0, 100, False)])
        manifest = [server_fixture._bot(i, 1, i-8, route, 'mediumTank') for i in (8, 9)]
        states = [server_fixture._state(8, 1, 0, -55),
                  server_fixture._state(9, 1, 0, -120)]
        defense = dict(bases={'1': [dict(id='1:0', x=0., y=0., z=0.)]},
                       states={'1': dict(invaders=1, time_left=90.)})
        def responders(now):
            orders = planner.build_orders(manifest, states, [], now, defense)['orders']
            return {o['id'] for o in orders if o['combat_mode']=='base_defense'}
        self.assertEqual({8}, responders(1.))
        self.assertEqual({8}, responders(2.))
        self.assertEqual({9}, responders(13.))
        states[1]['z'] = 0.
        self.assertEqual({9}, responders(14.))
        self.assertEqual({9}, responders(50.))


if __name__ == '__main__':
    unittest.main()
