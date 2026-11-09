"""Missing-order recovery uses the real shared planner, not a legacy engine."""
import ast
import contextlib
import io
from pathlib import Path
import unittest
from unittest import mock

import test_port_0922_bot_runtime as physical


class SharedOrderPlanningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = physical.BotRuntimeTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime = self.fixture.runtime
        with contextlib.redirect_stdout(io.StringIO()):
            self.runtime.battle_start(self.fixture.start)

    def test_missing_order_calls_real_shared_planner_and_reuses_its_state(self):
        planner = self.runtime.control_planner
        self.assertEqual('gui.mods.offline_lan_0922.vehicle_control.strategy',
                         type(planner).__module__)
        with mock.patch.object(planner, 'build_orders', wraps=planner.build_orders) as build:
            with mock.patch.object(planner, 'report_contacts', wraps=planner.report_contacts) as report:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.runtime.update(.04, 1.)
                    self.runtime.update(.04, 1.2)
                # Each actor's current observation is retained, but the
                # whole-roster contact cross product is not rebuilt per tick.
                self.assertEqual(1, report.call_count)
            self.assertEqual(1, build.call_count)
            self.assertTrue(build.call_args.args[0])
            self.assertIs(self.runtime.control_manifest, build.call_args.args[0])
            self.assertEqual([11], [row['id'] for row in
                self.runtime._control_plan['orders']])
            self.assertIs(planner, self.runtime.control_planner)
            self.assertTrue(self.fixture.adapters[0].server_orders)
            self.assertTrue(all(row.get('control_order_source') == 'shared_local_replan'
                                for row in self.fixture.adapters[0].server_orders))
            with contextlib.redirect_stdout(io.StringIO()):
                self.runtime.update(.04, 2.1)
            self.assertEqual(2, build.call_count)

    def test_published_order_is_not_replaced_by_a_second_local_strategy(self):
        point = (0., 0., 25.)
        order = dict(id=11, combat_mode='route', move_position=point,
            face_position=point, target_id=None, fire_allowed=False)
        self.runtime._server_orders[11] = order
        with mock.patch.object(self.runtime.control_planner, 'build_orders',
                side_effect=AssertionError('published order was replaced')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.runtime.update(.04, 1.)
        self.assertEqual(point, self.fixture.adapters[0].server_orders[-1]['move_position'])

    def test_missing_manifest_is_explicit_pending_and_never_authorizes_a_shot(self):
        self.runtime.control_manifest = ()
        with contextlib.redirect_stdout(io.StringIO()):
            self.runtime.update(.04, 1.)
        order = self.fixture.adapters[0].server_orders[-1]
        self.assertEqual('shared_order_unavailable', order['control_pending'])
        self.assertIsNone(order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual(0., order['throttle_override'])

    def test_round_change_retires_shared_recovery_state(self):
        old = self.runtime.control_planner
        old._target_assignments[11] = dict(target=('bot', 999))
        self.runtime._control_observers[11] = (1., ())
        self.runtime._control_plan = dict(orders=[dict(id=11)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.runtime.battle_start(dict(self.fixture.start, round_id=6))
        self.assertIsNot(old, self.runtime.control_planner)
        self.assertEqual({}, self.runtime.control_planner._target_assignments)
        self.assertEqual({}, self.runtime._control_observers)
        self.assertIsNone(self.runtime._control_plan)
        self.assertEqual([11], [row['id'] for row in self.runtime.control_manifest])

    def test_native_defense_facts_keep_bases_radius_and_capture_progress(self):
        self.runtime._observe_control_context(dict(
            defense=dict(contributors={'1': [dict(kind='bot', id=11)]}),
            capture_bases={'1': [dict(id='home', x=1., z=2., radius=35.)],
                           '2': [dict(id='away', x=3., z=4., radius=40.)]},
            rules=dict(bases={'1': dict(points=25.)})))
        result = self.runtime.control_defense_context()
        self.assertTrue(result['contributors_known'])
        self.assertEqual(35., result['capture_bases']['1'][0]['radius'])
        self.assertEqual('away', result['capture_bases']['2'][0]['id'])
        self.assertEqual(25., result['states']['1']['points'])
        result['capture_bases']['1'][0]['radius'] = 0.
        self.assertEqual(35., self.runtime.control_defense_context()['capture_bases']['1'][0]['radius'])

    def test_missing_driver_fails_explicitly_instead_of_using_old_engine(self):
        self.runtime.adapter.decide_with_order = None
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'shared_order_driver_unavailable'):
                self.runtime.update(.04, 1.)


class RetiredDirectorTests(unittest.TestCase):
    def test_only_roster_setup_remains_and_cannot_make_runtime_orders(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        from gui.mods.offline_lan_0922.ai import planner
        adapter = BotAdapter('01_karelia', 119)
        self.assertFalse(hasattr(planner, 'BattleDirector'))
        for name in ('director', 'plan_order', 'decide'):
            self.assertFalse(hasattr(adapter, name), name)
        for name in ('contacts', 'order_for', 'update_contact', '_known_contacts',
                     '_choose_contact', '_route_position', '_route_anchor'):
            self.assertFalse(hasattr(adapter.roster, name), name)
        self.assertTrue(callable(adapter.decide_with_order))

    def test_production_call_graph_contains_no_retired_fallback(self):
        root = Path(__file__).resolve().parents[1]
        client = root / 'src/res/scripts/client/gui/mods/offline_lan_0922'
        for path in client.rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ClassDef):
                    self.assertNotEqual('BattleDirector', node.name, str(path))
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ('director', 'plan_order'), str(path))
        source = (client / 'bot_runtime.py').read_text()
        self.assertIn('self._shared_control_order(state, contacts, players, now)', source)
        self.assertIn('worker_control.guard_mission_controls(', source)


if __name__ == '__main__':
    unittest.main()
