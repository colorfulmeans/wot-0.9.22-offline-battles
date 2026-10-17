"""Useful route-owned withdrawal goals and explicitly dated diagnostic evidence."""
import copy
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'src/res/scripts/client')]
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from test_port_0922_server_bot_ai import (
    BotPlanner, _bot, _contact, _route, _state, _weapon_state)
import test_port_0922_server_bot_ai as server_fixture


class WithdrawalGoalTests(unittest.TestCase):
    def order(self, class_tag='AT-SPG', anchor=None, reached=False):
        fixture = server_fixture.ServerBotTacticsTests()
        fixture.setUp()
        fixture.route = _route('lane', [(160, 128, False), (250, 128, False),
                                        (350, 128, False)])
        fixture.manifest[0]['route'] = fixture.route
        fixture.manifest[0]['profile']['class_tag'] = class_tag
        x = 160. if reached else 192.
        fixture.states = [_weapon_state(_state(11, 1, x, 128), reload_time=8.,
                                        reload_pending=True)]
        planner = BotPlanner()
        planner._route_assignments[11] = dict(route=fixture.route, until=0.)
        planner._route_states[11] = dict(route_id='lane', index=1, join_index=1,
            join_anchor=anchor or dict(x=x, y=0., z=128.))
        players = fixture._report(planner, [_contact(2, x, 148, [11])])
        return planner.build_orders(fixture.manifest, fixture.states, players, 1.)['orders'][0]

    def test_rejoining_ranged_vehicles_retreat_to_previous_route_point(self):
        for class_tag in ('AT-SPG', 'mediumTank', 'heavyTank'):
            with self.subTest(class_tag=class_tag):
                order = self.order(class_tag)
                self.assertEqual(order['combat_mode'], 'withdraw')
                self.assertEqual(order['move_position'], dict(x=160., y=0., z=128.))
                self.assertEqual(order['route_anchor'], dict(x=192., y=0., z=128.))
                self.assertEqual(order['target_id'], 2)
                self.assertFalse(order['fire_allowed'])

    def test_useful_existing_join_segment_is_preserved(self):
        anchor = dict(x=175., y=0., z=128.)
        self.assertEqual(self.order(anchor=anchor)['move_position'], anchor)

    def test_reached_retreat_point_uses_existing_engagement_hold(self):
        order = self.order(reached=True)
        self.assertEqual(order['combat_mode'], 'engage')
        self.assertEqual(order['throttle_override'], 0.)
        self.assertEqual(order['move_position'], dict(x=160., y=0., z=128.))
        self.assertEqual(order['target_id'], 2)


class ShortEscapeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.driver = LocalDriver()
        self.state = self.driver._state(25, 0, (0., 0., 0.))
        self.calls = []

    def clear(self, yaw, distance):
        self.calls.append((yaw, distance))
        return True

    def select(self):
        return self.driver._short_escape(self.state, (0., 0., 0.), 0., 0., .1,
            .1, 0., [], self.clear, 3.5, 1.7)

    def test_selection_keeps_original_timestamp_and_is_marked_historical(self):
        self.state['clock'] = 10.
        self.select()
        snapshot = self.driver.short_escape_diagnostics(self.state)
        self.assertFalse(snapshot['selection']['historical'])
        self.assertEqual(self.state['short_escape_probes'][0]['sampled_at'], 10.)
        self.state['clock'] = 13.
        sample = self.driver.short_escape_diagnostics(self.state)['selection']
        self.assertTrue(sample['historical'])
        self.assertEqual(sample['age_seconds'], 3.)
        self.assertEqual(sample['sampled_at'], 10.)
        self.assertEqual(self.calls, [(math.pi, 2.)])

    def test_continuation_proof_has_its_own_time_and_position(self):
        self.state['clock'] = 10.
        self.select()
        self.state['clock'] = 11.
        command = self.driver._retained_short_escape(self.state, (0., 0., -.2),
            0., [], self.clear, 3.5, 1.7)
        snapshot = self.driver.short_escape_diagnostics(self.state)
        self.assertEqual(command['recovery_mode'], 'short_reverse_escape')
        self.assertTrue(snapshot['selection']['historical'])
        self.assertFalse(snapshot['execution_check']['historical'])
        self.assertEqual(snapshot['execution_check']['sampled_at'], 11.)
        self.assertEqual(snapshot['execution_check']['origin'], (0., 0., -.2))
        self.assertEqual(snapshot['execution_check']['result'], 'retained')
        self.assertEqual(len(self.calls), 2)

    def test_release_and_reselection_do_not_relabel_old_results_as_current(self):
        self.select()
        self.state['clock'] = 5.
        self.assertIsNone(self.driver._retained_short_escape(self.state,
            (0., 0., 0.), 0., [], self.clear, 3.5, 1.7))
        snapshot = self.driver.short_escape_diagnostics(self.state)
        self.assertFalse(snapshot['retained_escape_present'])
        self.assertFalse(snapshot['lease_unexpired'])
        self.assertEqual(snapshot['execution_check']['result'], 'released')
        self.assertEqual(len(self.calls), 1)  # Expiry still short-circuits recasting.
        self.select()
        snapshot = self.driver.short_escape_diagnostics(self.state)
        self.assertEqual(snapshot['selection']['sequence'], 2)
        self.assertNotIn('execution_check', snapshot)

    def test_diagnostic_snapshot_does_not_mutate_driver_or_query_world(self):
        self.select()
        self.state['clock'] += 2.
        before = copy.deepcopy(self.state)
        calls = list(self.calls)
        for _ in range(10):
            self.driver.short_escape_diagnostics(self.state)
        self.assertEqual(before, self.state)
        self.assertEqual(calls, self.calls)
        self.state.pop('short_escape_probes')
        self.assertNotIn('selection', self.driver.short_escape_diagnostics(self.state))


class RouteLeaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.planner = BotPlanner()
        source = _route('source', [(-100, 0, False), (-100, 100, False),
                                  (-100, 500, False)], capacity=4)
        target = _route('target', [(100, 0, False), (100, 100, False),
                                  (100, 500, False)], capacity=1)
        manifest = [_bot(41, 1, 0, source, 'mediumTank', {'support': 1.}),
                    _bot(42, 1, 1, source, 'mediumTank', {'support': .9}),
                    _bot(43, 1, 2, target, 'SPG', {'artillery': 1.})]
        self.bots = self.planner._alive_bots(manifest, [
            _state(41, 1, -100, 0), _state(42, 1, -100, 0), _state(43, 1, 100, 0)])
        self.contacts = [dict(position=dict(x=100., y=0., z=250.),
                              health=1000., max_health=1000.)]
        self.planner._rebalance_routes(1, self.bots, self.contacts, 1.)
        self.donor = next(b for b in self.bots if b['id'] in (41, 42) and
            self.planner._route_assignments[b['id']]['route']['id'] == 'target')
        self.planner._route(self.donor, 1.1)
        self.planner._route_states[self.donor['id']]['index'] = 1

    def test_stable_pressure_renews_without_losing_route_cursor(self):
        for now in (5., 9., 13.):
            self.planner._rebalance_routes(1, self.bots, self.contacts, now)
            lease = self.planner._route_assignments[self.donor['id']]
            self.assertEqual(lease['_lease_observation']['outcome'], 'renewed')
            self.assertEqual(lease['until'], now + 6.)
            self.assertEqual(self.planner._route_states[self.donor['id']]['index'], 1)

    def test_different_pressure_target_explains_unrenewed_lease_and_expiry(self):
        # Isolate priority changes from movement-donor eligibility; leave the
        # existing selection/expiry rules untouched.
        self.planner._route_line_contributor = lambda *args: False
        contacts = self.contacts + [dict(position=dict(x=-100., y=0., z=z),
            health=1000., max_health=1000.) for z in (200., 300.)]
        self.planner._rebalance_routes(1, self.bots, contacts, 5.,
                                      protected_ids=[self.donor['id']])
        lease = self.planner._route_assignments[self.donor['id']]
        observation = lease['_lease_observation']
        self.assertEqual(observation['outcome'], 'different_pressure_target')
        self.assertEqual(observation['target_route'], 'source')
        self.assertEqual(observation['own_pressure'], 1.)
        self.assertEqual(lease['until'], 7.)
        self.planner._rebalance_routes(1, self.bots, contacts, 7.,
                                      protected_ids=[self.donor['id']])
        receipt = self.planner._route_assignment_receipts[self.donor['id']]
        self.assertEqual(receipt['reason'], 'lease_expired')
        self.assertEqual(receipt['previous_lease']['observation'], observation)
        self.assertEqual(receipt['previous_lease']['until'], 7.)

    def test_no_pressure_observation_does_not_extend_lease(self):
        self.planner._rebalance_routes(1, self.bots, [], 5.)
        lease = self.planner._route_assignments[self.donor['id']]
        self.assertEqual(lease['_lease_observation']['outcome'], 'no_known_pressure')
        self.assertEqual(lease['until'], 7.)


if __name__ == '__main__':
    unittest.main()
