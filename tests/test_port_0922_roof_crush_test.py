import ast
import importlib.util
import math
import os
from pathlib import Path
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922'
spec = importlib.util.spec_from_file_location('roof_fixture', SOURCE / 'roof_crush_test.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

class RoofCrushEntryTests(unittest.TestCase):
    def test_flag_off_does_not_patch_server(self):
        class Battle: pass
        class Planner: pass
        with mock.patch.dict(os.environ, {fixture.ENV: '0'}):
            fixture.install_server(Battle, Planner)
        self.assertFalse(hasattr(Battle, '_roof_crush_test_installed'))
        self.assertFalse(hasattr(Planner, 'build_orders'))

    def test_server_pins_map_roster_and_hold_orders(self):
        class Battle:
            def __init__(self, **kwargs): self.initial = kwargs
            def request_start(self, player_id, **kwargs): return kwargs
        class Planner:
            revision = 0
            _last_order_signature = None
        with mock.patch.dict(os.environ, {fixture.ENV: '1'}):
            fixture.install_server(Battle, Planner)
            battle = Battle(map_name='01_karelia', team1_size=1)
            self.assertEqual(fixture.MAP, battle.initial['map_name'])
            self.assertEqual(30, len(battle.initial['bot_lineup']))
            self.assertEqual({fixture.VEHICLE}, {v['vehicle'] for v in battle.initial['bot_lineup']})
            self.assertEqual(1, battle._requested_team_for_player(None))
            self.assertEqual(fixture.MAP, battle.request_start(1, requested_map='01_karelia')['requested_map'])
            planner = Planner()
            manifest = [dict(id=1, team=1), dict(id=2, team=2)]
            states = [dict(id=1, x=4, y=-10, z=100), dict(id=2, alive=False)]
            orders = planner.build_orders(manifest, states, [], 1.)
            self.assertEqual(1, len(orders['orders']))
            order = orders['orders'][0]
            self.assertFalse(order['fire_allowed'])
            self.assertIsNone(order['target_id'])
            self.assertEqual(0., order['throttle_override'])
            self.assertEqual(dict(x=4., y=-10., z=100.), order['move_position'])
            self.assertEqual(orders, planner.build_orders(manifest, states, [], 2.))

    def test_fifteen_targets_have_separate_positions(self):
        points = [fixture.enemy_seed(i)[0] for i in range(15)]
        self.assertEqual(15, len(set(points)))
        for i, a in enumerate(points):
            for b in points[i+1:]:
                self.assertGreaterEqual(math.hypot(a[0]-b[0], a[2]-b[2]), 3.49)
        with self.assertRaises(ValueError): fixture.enemy_seed(15)

    def test_target_array_is_tight_and_entirely_on_one_bridge_side(self):
        yaw = fixture.enemy_seed(0)[1]
        import math
        for slot in range(15):
            point, unused = fixture.enemy_seed(slot)
            dx, dz = point[0]-2., point[2]-105.
            lateral = dx*math.cos(yaw)-dz*math.sin(yaw)
            self.assertGreaterEqual(lateral,5.999)
            self.assertLessEqual(lateral,13.001)
        points = [fixture.enemy_seed(i)[0] for i in range(15)]
        self.assertAlmostEqual(3.5,math.hypot(points[5][0]-points[0][0],points[5][2]-points[0][2]))
        self.assertAlmostEqual(6.4,math.hypot(points[1][0]-points[0][0],points[1][2]-points[0][2]))

    def test_hold_does_not_mutate_physical_state_or_input(self):
        incoming = dict(throttle=1., turn=1., fire_allowed=True, target_id=12)
        held = fixture.hold_command(incoming, (1., -5., 3.))
        self.assertEqual(1., incoming['throttle'])
        self.assertEqual(0., held['throttle'])
        self.assertEqual(0., held['turn'])
        self.assertFalse(held['fire_allowed'])
        self.assertIsNone(held['target_id'])
        self.assertNotIn('position_fixed', held)
        self.assertNotIn('y', held)

    def test_actual_formation_method_queries_below_deck_and_caches(self):
        tree = ast.parse((SOURCE / 'battle_runtime.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BattleRuntime')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_formation_pose')
        # Keep the production body, substituting only its relative import.
        method.body[0] = ast.parse('roof_crush_test = fixture').body[0]
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        namespace = dict(fixture=fixture)
        exec(compile(module, 'formation-contract', 'exec'), namespace)
        probe = mock.Mock(return_value=-11.5)
        obj = types.SimpleNamespace(_spawn_cache={}, _ground_y=probe)
        with mock.patch.dict(os.environ, {fixture.ENV: '1'}):
            pose = namespace['_formation_pose'](obj, 2, 0)
            self.assertEqual(-11.5, pose[0][1])
            self.assertEqual(-14., probe.call_args.args[2])
            self.assertEqual(pose, namespace['_formation_pose'](obj, 2, 0))
            self.assertEqual(1, probe.call_count)
            probe.return_value = None
            with self.assertRaises(ValueError): namespace['_formation_pose'](obj, 2, 1)
            self.assertNotIn((2, 1), obj._spawn_cache)

class RuntimeHoldTests(unittest.TestCase):
    def setUp(self):
        import test_port_0922_bot_runtime as support
        self.support = support
        self.host = support.ShovedWreckTests()
        self.host.setUp()
        self.flag = mock.patch.dict(os.environ, {fixture.ENV: '1'})
        self.flag.start()

    def tearDown(self):
        self.flag.stop()
        self.host.tearDown()

    def test_aggressive_adapter_cannot_drive_or_fire(self):
        runtime = self.host._runtime()
        runtime.adapter.command.update(throttle=1., turn=1., fire_allowed=True, target_id=12)
        before = {key: (s['x'], s['z']) for key,s in runtime.states.items()}
        for i in range(20): runtime.update(.04, 1.+i*.04)
        for key,state in runtime.states.items():
            self.assertAlmostEqual(before[key][0], state['x'])
            self.assertAlmostEqual(before[key][1], state['z'])
            self.assertEqual(0, state.get('fire_seq', 0))

    def test_hold_does_not_freeze_airborne_vehicle(self):
        runtime = self.host._runtime()
        state = runtime.states[11]
        state.update(y=10., airborne=True, vertical_speed=-2., grounded_once=True)
        for i in range(10): runtime.update(.04, 1.+i*.04)
        self.assertLess(state['y'], 9.)

if __name__ == '__main__': unittest.main()

