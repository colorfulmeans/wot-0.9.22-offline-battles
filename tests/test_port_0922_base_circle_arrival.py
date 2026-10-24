"""Circle arrival must retire macro travel without bypassing combat/physics."""
import unittest
from unittest import mock

import test_port_0922_terminal_route_handoff as terminal
from test_port_0922_server_bot_ai import BotPlanner, _bot, _state, _route, _contact


class BaseCircleArrivalTests(unittest.TestCase):
    def setUp(self):
        self.helper = terminal.TerminalRouteHandoffTests()

    def test_inside_circle_far_from_terminal_hands_over_with_target(self):
        scene = self.helper.scene((32., -250.))
        order = self.helper.order(scene)
        self.assertEqual('engage', order['combat_mode'])
        self.assertEqual(0., order['throttle_override'])
        self.assertEqual(8, order['target_id'])
        self.assertTrue(order['fire_allowed'])
        self.assertEqual('circle', order['tactical_evidence']['route_terminal']['arrival_kind'])

    def test_capture_stops_at_circle_edge_and_does_not_recenter_after_push(self):
        scene = self.helper.scene((32., -250.))
        first = self.helper.order(scene, contact=False)
        self.assertEqual(0., first['throttle_override'])
        scene[2][0]['x'] = 45.
        second = self.helper.order(scene, 2., contact=False)
        self.assertEqual(0., second['throttle_override'])
        self.assertEqual(first['move_position'], second['move_position'])
        scene[2][0]['x'] = 65.
        third = self.helper.order(scene, 3., contact=False)
        self.assertIsNone(third['throttle_override'])
        self.assertEqual('outside_arrival', third['tactical_evidence']['route_terminal']['outcome'])

    def test_terminal_outside_circle_must_finish_before_capture_and_stays_finished(self):
        scene = self.helper.scene((84.523, -194.48))
        scene[3]['capture_bases']['1'][0].update(x=100., z=-250.)
        first = self.helper.order(scene, contact=False)
        self.assertEqual('route', first['combat_mode'])
        self.assertEqual(2., first['move_position']['x'])
        scene[2][0].update(x=2., z=-250.)
        second = self.helper.order(scene, 2., contact=False)
        self.assertEqual('base_capture', second['combat_mode'])
        self.assertEqual(100., second['move_position']['x'])
        scene[2][0]['x'] = 25.
        third = self.helper.order(scene, 3., contact=False)
        self.assertEqual(100., third['move_position']['x'])
        self.assertEqual('base_capture', third['combat_mode'])
        scene[2][0]['x'] = 60.
        fourth = self.helper.order(scene, 4., contact=False)
        self.assertEqual(0., fourth['throttle_override'])

    def test_enemy_circle_entry_retires_remaining_macro_gates(self):
        scene = self.helper.scene((70., 346.))
        self.helper.order(scene, contact=False)
        scene[2][0].update(x=32., z=-250.)
        scene[0]._route_states[17].update(index=0)
        order = self.helper.order(scene, contact=False)
        self.assertEqual(0.,order['throttle_override'])
        self.assertEqual('base_capture',order['combat_mode'])

    def test_custom_radius_boundary_matches_circle_membership(self):
        for x, arrived in ((22.505, True), (22.515, False)):
            with self.subTest(x=x):
                scene = self.helper.scene((x, -252.6))
                scene[3]['capture_bases']['1'][0]['radius'] = 20.
                order = self.helper.order(scene, contact=False)
                self.assertEqual(arrived, order['throttle_override'] == 0.)
                self.assertEqual(20., order['tactical_evidence']['route_terminal']['circle_radius'])

    def test_invalid_physics_does_not_finish_circle_arrival(self):
        for field in ('airborne', 'route_wreck_blocked'):
            with self.subTest(field=field):
                scene = self.helper.scene((32., -250.))
                scene[2][0][field] = True
                order = self.helper.order(scene)
                self.assertNotEqual(0., order['throttle_override'])
                self.assertEqual('physical_or_capture_not_arrived', order['tactical_evidence']['route_terminal']['outcome'])

    def defense_scene(self, x, class_tag='SPG', radius=50.):
        planner = BotPlanner()
        route = _route('defenders', [(0., 100., False), (0., 200., False)])
        bots = [_bot(11+i, 1, i, route, class_tag) for i in range(3)]
        states = [_state(bot['id'], 1, x+i, 0.) for i, bot in enumerate(bots)]
        defense = dict(bases={'1':[dict(id='1:0', x=0., z=0., radius=radius)]},
            states={'1':dict(invaders=1, time_left=60., points=10)},
            contributors={'1':[dict(kind='human', id=2)]})
        players = [dict(id=2, team=2, alive=True)]
        contact = _contact(2, 0., 10., [], class_tag='mediumTank')
        planner.report_contacts([contact], planner.known_targets(states, players), 1.)
        return planner, bots, states, players, defense

    def test_artillery_defense_only_hands_over_after_circle_entry(self):
        scene = self.defense_scene(51.)
        planner, bots, states, players, defense = scene
        orders = planner.build_orders(bots, states, players, 1., defense)['orders']
        defender = next(o for o in orders if o.get('defense_base_id'))
        self.assertEqual('base_defense', defender['combat_mode'])
        self.assertIsNone(defender['throttle_override'])
        self.assertFalse(defender['fire_allowed'])
        identity = defender['id']
        next(s for s in states if s['id'] == identity)['x'] = 49.
        order = next(o for o in planner.build_orders(bots, states, players, 2., defense)['orders'] if o['id'] == identity)
        self.assertEqual('engage', order['combat_mode'])
        self.assertEqual('1:0', order['defense_base_id'])
        self.assertEqual(0., order['throttle_override'])
        self.assertTrue(order['fire_allowed'])
        # Arrived defense still owns the mission; it cannot return to SPG parking.
        planner.report_contacts([_contact(2, 0., 10., [])], planner.known_targets(states, players), 20.)
        order = next(o for o in planner.build_orders(bots, states, players, 20., defense)['orders'] if o['id'] == identity)
        self.assertEqual('1:0', order['defense_base_id'])
        self.assertEqual('engage', order['combat_mode'])
        self.assertEqual(0., order['throttle_override'])
        next(s for s in states if s['id'] == identity)['x'] = 55.
        order = next(o for o in planner.build_orders(bots, states, players, 21., defense)['orders'] if o['id'] == identity)
        self.assertEqual('base_defense', order['combat_mode'])
        self.assertIsNone(order['throttle_override'])

    def test_normal_defender_preserves_local_lane_and_reload_gates_inside(self):
        planner, bots, states, players, defense = self.defense_scene(19., 'mediumTank', 20.)
        order = next(o for o in planner.build_orders(bots, states, players, 1., defense)['orders'] if o.get('defense_base_id'))
        self.assertEqual(0., order['throttle_override'])
        self.assertFalse(order['fire_allowed'])
        states[0].update(clip=0, reload_time=5.)
        contact = _contact(2, 0., 10., [11])
        planner.report_contacts([contact], planner.known_targets(states, players), 2.)
        order = next(o for o in planner.build_orders(bots, states, players, 2., defense)['orders'] if o['id'] == 11)
        self.assertFalse(order['fire_allowed'])

    def test_base_mission_cannot_be_overwritten_by_authored_spg_parking(self):
        planner, bots, states, players, defense = self.defense_scene(19.)
        order = next(o for o in planner.build_orders(bots, states, players, 1., defense)['orders'] if o.get('defense_base_id'))
        bot = next(b for b in planner._alive_bots(bots, states) if b['id'] == order['id'])
        previous = dict(order)
        with mock.patch('server_bot_ai.bot_tactics.route_config') as config:
            planner._apply_authored_route_order(order, bot, dict(x=999., y=0., z=999.), 2.)
            config.assert_not_called()
        self.assertEqual(previous, order)

    def test_actual_occupants_and_humans_fill_capture_budget(self):
        planner = BotPlanner()
        route = _route('lane', [(0., 100., False), (0., 200., False)])
        bots = [_bot(11+i, 1, i, route, 'mediumTank') for i in range(5)]
        for i, bot in enumerate(bots):
            bot['state'] = _state(bot['id'], 1, 100.+i, 0.)
        target = dict(id='2:0', point=dict(x=0., y=0., z=0.), radius=50.)
        initial = planner._update_base_capture(1, bots, target, set(), 1.)
        self.assertEqual({11,12,13}, initial)
        contributors = {('human', 99), ('bot', 15)}
        bots[-1]['state']['x'] = 30.
        bots[-1]['state']['critical'] = {'destroyed': ['leftTrackHealth']}
        selected = planner._update_base_capture(1, bots, target, set(), 2., contributors=contributors)
        self.assertEqual({11,15}, selected)
        self.assertEqual(selected, planner._update_base_capture(1, bots, target, set(), 3., contributors=contributors))
        self.assertEqual(set(), planner._update_base_capture(1, bots, target, set(), 4.,
            contributors={('human',97),('human',98),('human',99)}))
        restored = planner._update_base_capture(1, bots, target, set(), 5.)
        self.assertEqual(3, len(restored))

    def test_build_orders_counts_authoritative_human_contributors(self):
        scene = self.helper.scene((32., -250.))
        scene[3]['contributors'] = {'1': [dict(kind='human', id=i) for i in (91,92,93)]}
        self.helper.order(scene, contact=False)
        self.assertEqual([], scene[0]._base_capture[2]['bot_ids'])
        self.assertEqual(0, scene[0]._base_capture[2]['allocation']['budget'])
        scene[3]['contributors']['1'].pop()
        self.helper.order(scene, 2., contact=False)
        self.assertEqual([17], scene[0]._base_capture[2]['bot_ids'])

    def test_capture_without_route_still_stops_inside_circle(self):
        scene = self.helper.scene((32., -250.))
        scene[1][0]['route'] = {}
        scene[1][0]['profile']['class_tag'] = 'SPG'
        order = self.helper.order(scene, contact=False)
        self.assertEqual('base_capture', order['combat_mode'])
        self.assertEqual(0., order['throttle_override'])
        self.assertTrue(order['tactical_evidence']['route_terminal']['inside_capture'])

    def test_capture_does_not_consume_explicit_terminal_parking(self):
        from test_port_0922_authored_route_waits import AuthoredRouteWaitTests
        for tag in ('heavyTank', 'SPG'):
            with self.subTest(tag=tag):
                planner, bots = AuthoredRouteWaitTests().setup_route(tag, 0)
                defense = {'capture_bases': {'2': [dict(id='2:0', x=300., z=0., radius=50.)]}}
                planner.build_orders(bots, [_state(11,1,0.,0.)], [], 1., defense)
                for now in (2., 50.):
                    order = planner.build_orders(bots, [_state(11,1,100.,0.)], [], now, defense)['orders'][0]
                    self.assertEqual('waiting', order['parking_phase'])
                    self.assertEqual('hold', order['combat_mode'])
                    self.assertEqual(0., order['throttle_override'])
                    self.assertEqual(100., order['move_position']['x'])

    def test_contact_stall_records_evidence_without_changing_retry_policy(self):
        scene = self.helper.scene((60., -220.))
        self.helper.order(scene)
        self.helper.order(scene, 30.)
        receipt = scene[0]._base_capture[2]['progress'][17]['observation']
        self.assertEqual(1, receipt['known_contacts'])
        self.assertGreater(receipt['seconds_without_progress'], 20.)
        self.assertIn('fire_seq', receipt)
        self.assertEqual([17], scene[0]._base_capture[2]['bot_ids'])


if __name__ == '__main__':
    unittest.main()
