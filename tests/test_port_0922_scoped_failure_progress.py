"""Scope refusal evidence and keep connector changes out of progress credit."""
import math
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from test_port_0922_server_bot_ai import BotPlanner, _order_signature


class ScopedFailureTests(unittest.TestCase):
    def setUp(self):
        self.driver = LocalDriver()
        self.origin = (0., 0., 0.)
        self.state = self.driver._state(18, 0, self.origin)

    def remember(self, source, distance=0., origin=None, ttl=5.):
        self.driver.remember_failure(18, math.pi, ttl, dict(
            source=source, distance=distance, origin=origin or self.origin))

    def test_far_forecast_allows_fresh_short_proof_but_not_unchecked_motion(self):
        self.remember('motion_forecast', 15.)
        probes = []
        command = self.driver._short_escape(self.state, self.origin, 0., 0., .1,
            .1, 0., [], lambda yaw, distance: probes.append(distance) or distance <= .5,
            3.5, 1.7)
        self.assertEqual(command['recovery_mode'], 'short_reverse_escape')
        self.assertEqual(command['recovery_probe_distance'], .5)
        self.assertEqual(probes, [2., 2., 1., 1., .5])

    def test_real_contact_veto_stays_local_and_expires(self):
        self.remember('realised_motion')
        self.assertTrue(self.driver._short_failure_applies(self.state, self.origin, math.pi, .5))
        self.assertFalse(self.driver._short_failure_applies(self.state, (1., 0., 0.), math.pi, .5))
        self.assertFalse(self.driver._short_failure_applies(self.state, (0., -14., 0.), math.pi, .5))
        self.state['clock'] = 5.
        self.assertFalse(self.driver._short_failure_applies(self.state, self.origin, math.pi, .5))

    def test_forecast_cannot_overwrite_live_actual_contact(self):
        self.remember('realised_motion')
        self.state['clock'] = 1.
        self.remember('motion_forecast', 15., ttl=2.)
        self.assertTrue(self.driver._short_failure_applies(self.state, self.origin, math.pi, .5))
        self.assertEqual(self.state['real_failed_yaws'][self.driver._yaw_key(math.pi)], 5.)
        self.assertTrue(self.state['failure_receipts'][-1]['preserved_contact'])

    def test_failed_fresh_probe_does_not_make_a_short_escape(self):
        self.remember('motion_forecast', 15.)
        self.assertIsNone(self.driver._short_escape(self.state, self.origin, 0., 0.,
            .1, .1, 0., [], lambda *args: False, 3.5, 1.7))

    def test_receipts_are_bounded_and_legacy_contact_remains_protected(self):
        for _ in range(40):
            self.driver.remember_failure(18, math.pi, 5.)
        self.assertEqual(len(self.state['failure_receipts']), 16)
        self.assertTrue(self.driver._short_failure_applies(self.state, self.origin, math.pi, .5))

    def test_runtime_contact_receipt_uses_canonical_xyz_pose_and_source(self):
        from test_port_0922_bot_runtime import _load
        module = _load()
        runtime = types.SimpleNamespace(
            states={18: dict(x=-287., y=1.12, z=-346., yaw=-.93, speed=0.)},
            adapter=types.SimpleNamespace(driver=self.driver),
            _decision_cache={18: object()}, _motion_probe_cache={18: object()})
        module.BotRuntime._invalidate_realised_motion(runtime, 18, math.pi, 'yaw_rebase')
        receipt = self.state['failure_receipts'][-1]
        self.assertEqual(receipt['origin'], (-287., 1.12, -346.))
        self.assertEqual(receipt['source'], 'yaw_rebase')
        self.assertEqual(receipt['hull_yaw'], -.93)
        self.assertEqual(receipt['pitch'], 0.)
        self.assertEqual(runtime._decision_cache, {})
        self.assertEqual(runtime._motion_probe_cache, {})


class ConnectorProgressTests(unittest.TestCase):
    def drive(self, driver, target, goal=(0., 0., 200.), yaw=math.pi / 2):
        return driver.drive(11, 0, (0., 0., 0.), yaw, 0., .1, target, [],
            lambda *args: True, progress_target=target, recovery_goal=goal,
            turn_speed_limit=.15)

    def test_alternating_connectors_do_not_restart_same_order_clock(self):
        driver = LocalDriver(stuck_seconds=100.)
        targets = ((0., 0., 10.), (10., 0., 0.))
        recovered = False
        for frame in range(100):
            self.drive(driver, targets[(frame // 10) % 2])
            recovered |= driver.states[11]['recovery_time'] > 0.
        self.assertTrue(recovered)
        self.assertGreater(driver.states[11]['objective_progress'].get('local_rebases', 0), 0)

    def test_real_order_change_and_commanded_hold_keep_original_reset(self):
        driver = LocalDriver(stuck_seconds=100.)
        for _ in range(60):
            self.drive(driver, (0., 0., 10.))
        self.drive(driver, (10., 0., 0.), goal=(200., 0., 0.))
        progress = driver.states[11]['objective_progress']
        self.assertEqual(progress['reset_reason'], 'order_changed')
        self.assertAlmostEqual(progress['at'], driver.states[11]['clock'])
        driver.drive(11, 0, (0., 0., 0.), 0., 0., .1, (10., 0., 0.), [],
                     lambda *args: True, movement_intent=False)
        self.assertNotIn('objective_progress', driver.states[11])
        self.assertEqual(driver.states[11]['recovery_time'], 0.)

    def test_assignment_provenance_is_telemetry_not_new_order_revision(self):
        planner = BotPlanner()
        bot = {'id': 11, 'state': dict(x=1., y=2., z=3.)}
        planner._record_route_assignment(bot, 5., 'east', 'central', 'lease_expired')
        receipt = planner._route_assignment_receipts[11]
        self.assertEqual(receipt['previous_route'], 'east')
        self.assertEqual(receipt['position'], dict(x=1., y=2., z=3.))
        self.assertEqual(_order_signature({'route_id': 'central'}),
            _order_signature({'route_id': 'central', 'route_assignment': receipt}))

    def test_original_skip_then_switch_publishes_current_receipt(self):
        from test_port_0922_wreck_route_switch import WreckRouteSwitchTests
        fixture = WreckRouteSwitchTests()
        fixture.setUp()
        first = fixture.orders(0.)[17]
        skipped = fixture.orders(20.)[17]
        changed = fixture.orders(40.)[17]
        self.assertEqual(first['route_id'], skipped['route_id'])
        self.assertNotEqual(skipped['route_id'], changed['route_id'])
        self.assertEqual(changed['route_assignment']['reason'], 'wreck_stall')
        self.assertEqual(changed['route_assignment']['route'], changed['route_id'])
        self.assertEqual(changed['route_assignment']['at'], 40.)

    def test_worker_receives_diagnostics_without_invalidating_control_cache(self):
        from test_port_0922_bot_runtime import _load
        module = _load()
        runtime = module.BotRuntime(1)
        original = dict(id=11, route_id='east', route_index=1,
            move_position=dict(x=0., y=0., z=100.),
            route_attempt=dict(elapsed=1.), route_assignment=dict(sequence=1))
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[original])))
        command = object()
        runtime._decision_cache[11] = command
        runtime._control_refresh_accumulator = 0.
        observed = dict(original, route_attempt=dict(elapsed=2.),
            route_assignment=dict(sequence=2, reason='pressure_rebalance'))
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[observed])))
        self.assertIs(command, runtime._decision_cache[11])
        self.assertEqual(runtime._control_refresh_accumulator, 0.)
        self.assertEqual(runtime._server_orders[11]['route_attempt']['elapsed'], 2.)
        self.assertEqual(runtime._server_orders[11]['route_assignment']['sequence'], 2)
        changed = dict(observed, route_id='central')
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=2, bot_orders=[changed])))
        self.assertNotIn(11, runtime._decision_cache)


if __name__ == '__main__':
    unittest.main()
