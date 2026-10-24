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
    def test_moving_near_heading_releases_brake_before_recovery_deadline(self):
        driver = LocalDriver(stuck_seconds=100.)
        yaw = 0.
        commands = []
        for frame in range(50):
            target = (3. * math.sin(yaw + .6), 0., 3. * math.cos(yaw + .6))
            command = driver.drive(11, 0, (0., 0., 0.), yaw, 0., .1,
                target, [], lambda *args: True, progress_target=target,
                recovery_goal=(0., 0., 200.), turn_speed_limit=.8,
                stop_at_target=False)
            commands.append(command)
            yaw += command['turn'] * .8 * .1
        self.assertTrue(any(c['throttle'] > 0. and not c['brake'] for c in commands))
        self.assertTrue(all(c['recovery_mode'] == 'drive' for c in commands))

    def test_rotating_near_connectors_cannot_reissue_alignment_credit(self):
        # 033347 T-50/AMX 30: the admitted near point keeps moving around
        # the hull. There is no world refusal, but aligning must not renew
        # the same stationary recovery task once per connector.
        driver = LocalDriver(stuck_seconds=100.)
        modes = []
        for frame in range(300):
            yaw = frame * .08
            target = (2.08 * math.sin(yaw + .6), 0.,
                      2.08 * math.cos(yaw + .6))
            modes.append(driver.drive(11, 0, (0., 0., 0.), yaw, 0., .1,
                target, [], lambda *args: True, progress_target=target,
                recovery_goal=(0., 0., 200.), turn_speed_limit=.8,
                stop_at_target=False)['recovery_mode'])
        self.assertTrue(any(mode in ('reverse_turn', 'pivot_recovery')
                            for mode in modes))

    def test_retained_alignment_controls_heading_not_only_brake(self):
        driver = LocalDriver(stuck_seconds=100.)
        first = self.drive(driver, (-3., 0., 0.), yaw=0.)
        second = driver.drive(11, 0, (0., 0., 0.), 0., 0., .5,
            (-3., 0., 1.5), [], lambda *args: True,
            progress_target=(-3., 0., 1.5), recovery_goal=(0., 0., 200.),
            turn_speed_limit=.15)
        self.assertAlmostEqual(first['target_yaw'], second['target_yaw'])
        self.assertEqual((-3., 0., 0.), driver.states[11]['alignment_target'])

    def test_reaching_new_local_point_cannot_keep_old_alignment_brake(self):
        driver = LocalDriver(stuck_seconds=100.)
        self.drive(driver, (-3., 0., 0.), yaw=0.)
        command = self.drive(driver, (-1.2, 0., 0.), yaw=0.)
        self.assertEqual('arrived', command['recovery_mode'])
        self.assertIsNone(driver.states[11].get('alignment_target'))
        self.assertEqual('current_point_reached',
                         driver.states[11]['alignment_observation']['reason'])

    def test_nearby_point_change_cannot_compare_two_different_distances(self):
        driver=LocalDriver(stuck_seconds=100.)
        self.drive(driver,(0.,0.,10.))
        before=dict(driver.states[11]['objective_progress'])
        self.drive(driver,(0.,0.,8.5))
        progress=driver.states[11]['objective_progress']
        self.assertEqual(before['best'],progress['best'])
        self.assertEqual(before['at'],progress['at'])
        self.assertEqual(10.,progress['measured_distance'])
        self.assertEqual(8.5,progress['steering_distance'])

    def test_translation_does_not_reissue_an_already_earned_alignment(self):
        driver=LocalDriver(stuck_seconds=100.)
        self.drive(driver,(0.,0.,3.))
        progress=driver.states[11]['objective_progress']
        progress.update(alignment_yaw=.7,alignment_best=.1)
        driver.drive(11,0,(0.,0.,.1),math.pi/2,0.,.1,(0.,0.,3.),[],
            lambda *args:True,progress_target=(0.,0.,3.),
            recovery_goal=(0.,0.,200.),turn_speed_limit=.15)
        self.assertEqual(.7,progress['alignment_yaw'])
        self.assertEqual(.1,progress['alignment_best'])
        self.assertEqual('new_order_distance',progress['credit_reason'])

    def test_report_124508_sherman_local_orbit_cannot_renew_progress(self):
        driver = LocalDriver(stuck_seconds=100.)
        modes = []
        # 124508 round 1 bot 22: supported, no world refusal, alternating
        # near points around (-166, 92). Each orbit used to mint a new
        # connector and a new heading/distance progress allowance.
        for frame in range(600):
            angle = frame * .05
            position = (-166. + .8 * math.sin(angle), 0., 92.8 + .5 * math.cos(angle))
            target = (position[0] + 2.1 * math.sin(angle + 1.), 0.,
                      position[2] + 2.1 * math.cos(angle + 1.))
            command = driver.drive(22, 6, position, angle, 1., .1,
                target, [], lambda *args: True, progress_target=target,
                recovery_goal=(-180., 0., 300.), turn_speed_limit=.4,
                stop_at_target=False)
            modes.append(command['recovery_mode'])
        self.assertGreater(driver.states[22]['recovery_count'], 1)
        self.assertTrue(any(mode in ('reverse_turn', 'pivot_recovery') for mode in modes))
        progress = driver.states[22]['objective_progress']
        self.assertLess(progress['travel_best'], 2.)
        self.assertGreater(progress['local_rebases'], 10)

    def test_rebased_turn_does_not_get_a_new_alignment_anchor(self):
        driver = LocalDriver(stuck_seconds=100.)
        self.drive(driver, (0., 0., 3.), yaw=2.)
        progress = driver.states[11]['objective_progress']
        progress.update(alignment_yaw=.7, alignment_best=.1)
        anchor = progress['alignment_yaw']
        best = progress['alignment_best']
        self.drive(driver, (3., 0., 0.), yaw=2.)
        self.assertEqual(anchor, progress.get('alignment_yaw'))
        self.assertEqual(best, progress.get('alignment_best'))

    def test_sherman_report_snapshots_complete_a_recovery(self):
        # Exact rounded 124508 round 1 bot 22 snapshots. This replays the
        # progress owner, not unseen physics between diagnostic samples.
        goals = [(-214.,0.,-314.),(-210.674,0.,-2.353),(-216.619,0.,-81.873)]
        rows = [
            (0.,-165.8419,92.1781,.3859,-166.,94.,0),
            (3.021,-166.1094,92.2427,-1.3247,-167.8912,92.5342,1),
            (8.718,-166.881,93.1136,1.321,-164.8661,92.5972,1),
            (13.341,-165.4168,92.8029,-2.1739,-167.4176,92.2344,1),
            (17.708,-166.7427,93.1857,-.3539,-166.,94.,1),
            (20.917,-166.7738,93.2645,1.3019,-164.9985,92.1808,2),
            (26.287,-166.0208,92.9955,-2.3002,-167.9155,92.1188,2),
            (30.602,-166.966,92.8997,-.201,-166.,94.,2),
            (33.671,-166.966,92.8997,1.3696,-164.8959,92.697,2),
            (37.768,-165.8542,92.8697,-.601,-167.913,93.8021,2),
            (42.306,-166.694,93.3102,-3.0302,-164.7674,92.5263,0),
            (47.868,-165.4617,92.5481,.0009,-166.,94.,0),
            (50.885,-165.6012,93.0249,-1.3819,-167.5847,92.4716,0),
            (55.5,-166.3684,92.8617,2.2368,-164.366,92.0929,0),
            (59.778,-165.3844,92.405,.0067,-166.,94.,0)]
        driver = LocalDriver(stuck_seconds=100.)
        last = -.1
        for now,x,z,yaw,tx,tz,g in rows:
            driver.drive(22,6,(x,0.,z),yaw,0.,now-last,(tx,0.,tz),[],
                lambda *args:True, progress_target=(tx,0.,tz),
                recovery_goal=goals[g],turn_speed_limit=.4,stop_at_target=False)
            last=now
        self.assertGreater(driver.states[22]['recovery_count'],0)

    def test_real_curved_travel_can_return_toward_an_old_pocket(self):
        driver=LocalDriver(stuck_seconds=100.)
        for frame in range(630):
            angle=frame*.01
            position=(20.*math.cos(angle),0.,20.*math.sin(angle))
            yaw=-angle
            target=(position[0]+3.*math.sin(yaw),0.,position[2]+3.*math.cos(yaw))
            driver.drive(22,6,position,yaw,2.,.1,target,[],lambda *args:True,
                progress_target=target,recovery_goal=(0.,0.,400.),
                turn_speed_limit=.4,stop_at_target=False)
            self.assertEqual(0,driver.states[22]['recovery_count'])

    def test_elc_revisiting_connectors_cannot_reissue_distance_and_alignment_credit(self):
        driver = LocalDriver(stuck_seconds=100.)
        modes = []
        # Reduced 011659 ELC pattern: supported, unblocked, small real travel
        # between two near connectors while the order remains far away.
        for frame in range(300):
            phase = frame % 40
            x = (phase if phase < 20 else 40-phase) * .1
            target = ((-2., 0., 3.) if phase < 20 else (4., 0., -3.))
            command = driver.drive(27, 11, (x, 0., 0.), .2*math.sin(frame*.2),
                1., .1, target, [], lambda *args: True,
                progress_target=target, recovery_goal=(0., 0., 400.),
                turn_speed_limit=.3, stop_at_target=False)
            modes.append(command['recovery_mode'])
        self.assertTrue(any(mode in ('reverse_turn', 'pivot_recovery') for mode in modes))
        self.assertLessEqual(len(driver.states[27]['objective_progress']['connectors']), 16)

    def test_revisiting_arrived_connector_does_not_reset_remote_order_clock(self):
        driver = LocalDriver(stuck_seconds=100.)
        modes = []
        for frame in range(200):
            target = (1., 0., 0.) if frame % 20 < 10 else (-2., 0., 0.)
            modes.append(driver.drive(27, 11, (0., 0., 0.), 0., 0., .1,
                target, [], lambda *args: True, progress_target=target,
                recovery_goal=(0., 0., 400.), turn_speed_limit=.3)['recovery_mode'])
        self.assertTrue(any(mode in ('reverse_turn', 'pivot_recovery') for mode in modes))

    def test_arrived_real_destination_and_new_order_still_reset(self):
        driver = LocalDriver(stuck_seconds=100.)
        for frame in range(200):
            command = driver.drive(27, 11, (0., 0., 0.), 0., 0., .1,
                (0., 0., 0.), [], lambda *args: True,
                progress_target=(0., 0., 0.), recovery_goal=(0., 0., 0.))
            self.assertEqual('arrived', command['recovery_mode'])

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

    def test_moving_between_new_connectors_is_not_a_stationary_loop(self):
        driver = LocalDriver(stuck_seconds=100.)
        for frame in range(200):
            position = (0., 0., frame * .2)
            target = ((-10., 0., 10.), (10., 0., 10.))[frame % 2]
            target = (target[0], 0., position[2] + target[2])
            driver.drive(11, 0, position, 0., 2., .1, target, [],
                lambda *args: True, progress_target=target,
                recovery_goal=(0., 0., 200.), turn_speed_limit=.15)
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

    def test_skip_return_then_switch_publishes_current_receipt(self):
        from test_port_0922_wreck_route_switch import WreckRouteSwitchTests
        fixture = WreckRouteSwitchTests()
        fixture.setUp()
        first = fixture.orders(0.)[17]
        skipped = fixture.orders(20.)[17]
        returned = fixture.orders(40.)[17]
        self.assertEqual(first['route_id'], skipped['route_id'])
        self.assertEqual(('banana', 0), (returned['route_id'], returned['route_index']))
        fixture.states[0].update(x=190., z=74.)
        changed = fixture.orders(41.)[17]
        self.assertNotEqual(skipped['route_id'], changed['route_id'])
        self.assertEqual(changed['route_assignment']['reason'], 'recovery_at_start')
        self.assertEqual(changed['route_assignment']['route'], changed['route_id'])
        self.assertEqual(changed['route_assignment']['at'], 41.)

    def test_worker_receives_diagnostics_without_invalidating_control_cache(self):
        from test_port_0922_bot_runtime import _load
        module = _load()
        runtime = module.BotRuntime(1)
        original = dict(id=11, route_id='east', route_index=1,
            move_position=dict(x=0., y=0., z=100.),
            route_attempt=dict(elapsed=1.), route_assignment=dict(sequence=1),
            tactical_evidence=dict(at=1.,selection=dict(outcome='assigned')))
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[original])))
        command = object()
        runtime._decision_cache[11] = command
        runtime._control_refresh_accumulator = 0.
        observed = dict(original, route_attempt=dict(elapsed=2.),
            route_assignment=dict(sequence=2, reason='pressure_rebalance'),
            tactical_evidence=dict(at=2.,selection=dict(outcome='assigned')))
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[observed])))
        self.assertIs(command, runtime._decision_cache[11])
        self.assertEqual(runtime._control_refresh_accumulator, 0.)
        self.assertEqual(runtime._server_orders[11]['route_attempt']['elapsed'], 2.)
        self.assertEqual(runtime._server_orders[11]['route_assignment']['sequence'], 2)
        self.assertEqual(runtime._server_orders[11]['tactical_evidence']['at'], 2.)
        self.assertEqual(_order_signature(original),_order_signature(observed))
        changed = dict(observed, route_id='central')
        self.assertTrue(runtime._apply_orders(dict(bot_order_revision=2, bot_orders=[changed])))
        self.assertNotIn(11, runtime._decision_cache)


if __name__ == '__main__':
    unittest.main()
