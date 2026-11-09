"""Firing-position arrival and bounded physical movement ownership."""
import math
import json
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_bot_runtime import _load, _flat_open_graph
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state, _contact
from test_port_0922_bot_state_codec import _bot_state, STATIC
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import bot_state_codec


class FiringPositionArrivalTests(unittest.TestCase):
    def setUp(self):
        self.goal = (-148.837, 1.1, 75.174)
        self.enemy = (-255.7, 1.1, -.66)
        self.adapter = BotAdapter('himmelsdorf', 11,
            navigation_target=lambda bot, pos, goal, *unused: goal)
        self.order = dict(combat_mode='gun_angle_adjust', target_id=20,
            move_position=self.goal, aim_position=self.enemy,
            face_position=self.enemy, throttle_override=1.)

    def decide(self, position, order=None):
        yaw = math.atan2(self.enemy[0]-position[0], self.enemy[2]-position[2])
        return self.adapter.decide_with_order(dict(id=14, team=1, slot=13,
            position=position, yaw=yaw, speed=0., dt=.1,
            half_length=3., half_width=1.5, navigation_status='safe'),
            order or self.order, lambda *unused: True)

    def test_report_arrival_does_not_receive_upper_full_throttle(self):
        command = self.decide((-150., 1.1, 74.4))
        self.assertEqual('arrived', command['recovery_mode'])
        self.assertEqual(0., command['throttle'])

    def test_explicit_firing_hold_cannot_restart_completed_position_move(self):
        self.decide((-150., 1.1, 74.4))
        held = dict(self.order, combat_mode='engage', throttle_override=0.)
        for unused in range(120):
            command = self.decide((-150.5, 1.1, 74.14), held)
            self.assertEqual('arrived', command['recovery_mode'])
            self.assertEqual(0., command['throttle'])
            self.assertEqual(20, command['target_id'])
        self.adapter.forget(14)
        self.assertFalse(hasattr(self.adapter, '_flank_arrivals'))

    def test_displacement_and_new_orders_release_arrival(self):
        for replacement, position in ((dict(self.order, move_position=(-140., 1.1, 90.)),
                (-150., 1.1, 74.4)), (self.order, (-155., 1.1, 74.4))):
            self.decide((-150., 1.1, 74.4))
            self.decide(position, replacement)
            self.assertFalse(hasattr(self.adapter, '_flank_arrivals'))

    def test_normal_route_retains_forward_throttle(self):
        command = self.decide((-150., 1.1, 74.4), dict(self.order,
            combat_mode='route', move_position=(-170., 1.1, 60.)))
        self.assertTrue(command['movement_intent'])
        self.assertFalse(hasattr(self.adapter, '_flank_arrivals'))


class FriendlyManoeuvreTests(unittest.TestCase):
    def setUp(self):
        self.module = _load()
        self.runtime = self.module.BotRuntime(1)
        self.state = dict(id=8, team=1, x=0., y=0., z=0., yaw=0.,
            half_length=3., half_width=1.5, shell_index=0, fire_seq=2)
        self.runtime.states[8] = self.state
        self.runtime._gun_yaw_limits[8] = (-.05, .05, True)
        self.command = dict(target_id=18, fire_range=450.)
        self.target = dict(kind='bot', alive=True, position=(0., 0., 100.))
        self.launch = dict(fire_seq=3, shot_yaw=0.)
        self.verdict = dict(blocker_kind='bot', blocker_id=7, blocker_team=1,
            blocker_position=(0., 0., 20.), blocker_radius=3.)

    def mark(self, now):
        with mock.patch.object(self.runtime, '_physics_params_for',
                               return_value=dict(rotSpd=math.radians(20))):
            return self.runtime._mark_friendly_reposition(self.state,
                self.command, self.target, self.launch, self.verdict, now)

    def test_fixed_gun_gets_turn_time_and_keeps_one_destination(self):
        self.assertTrue(self.mark(10.))
        marker = dict(self.runtime._friendly_repositions[8])
        self.assertGreater(marker['deadline'], 16.)
        self.assertLessEqual(marker['deadline'], 26.)
        for now in (11., 14.1, 16.):
            command, expired = self.runtime._friendly_reposition_order(
                self.state, {18: self.target}, now, self.runtime._server_orders.get(8, {}))
            self.assertFalse(expired)
            self.assertEqual(marker['destination'], command['move_position'])
        self.assertTrue(self.state['local_combat_manoeuvre'])

    def test_turreted_vehicle_gets_same_bounded_turn_budget(self):
        self.runtime._gun_yaw_limits[8] = (-math.pi, math.pi, False)
        self.mark(10.)
        marker = self.runtime._friendly_repositions[8]
        self.assertAlmostEqual(20.5, marker['deadline'])
        self.assertEqual('bot', marker['target_kind'])
        self.assertEqual(10.5, marker['time_budget']['granted'])

    def test_repeated_blocked_shot_cannot_extend_active_deadline(self):
        self.mark(10.)
        deadline = self.runtime._friendly_repositions[8]['deadline']
        self.mark(11.)
        self.assertEqual(deadline, self.runtime._friendly_repositions[8]['deadline'])

    def test_new_priority_target_cancels_old_manoeuvre(self):
        self.mark(10.)
        self.runtime._server_orders[8] = dict(target_id=19, target_kind='bot')
        self.assertEqual((None, False), self.runtime._friendly_reposition_order(
            self.state, {18:self.target}, 11., self.runtime._server_orders.get(8, {})))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertEqual('target_changed', self.state['_friendly_reposition_event']['outcome'])

    def test_base_defense_cannot_start_a_new_lane_override(self):
        self.command['combat_mode'] = 'base_defense'
        self.assertFalse(self.mark(10.))
        self.assertNotIn(8, self.runtime._friendly_repositions)

    def test_timeout_clears_owner_and_prevents_identical_immediate_retry(self):
        self.mark(10.)
        marker = dict(self.runtime._friendly_repositions[8])
        end = marker['deadline'] + .01
        self.assertEqual((None, True), self.runtime._friendly_reposition_order(
            self.state, {18: self.target}, end, self.runtime._server_orders.get(8, {})))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertFalse(self.mark(end + .2))
        self.assertEqual('timeout', self.state['_friendly_reposition_last_terminal']['outcome'])
        self.assertEqual(end, self.state['_friendly_reposition_last_terminal']['at'])
        self.assertEqual(end + .2, self.state['_friendly_reposition_retry']['observed_at'])
        self.assertTrue(self.mark(end + 8.1))
        self.assertEqual(-marker['side'], self.runtime._friendly_repositions[8]['side'])

    def test_target_death_and_priority_handoff_release_owner(self):
        for order, target, outcome in (({}, dict(self.target, alive=False), 'target_gone'),
                (dict(combat_mode='base_defense'), self.target, 'priority_handoff')):
            self.runtime._server_orders[8] = order
            self.mark(10.)
            command, expired = self.runtime._friendly_reposition_order(
                self.state, {18:target}, 11., self.runtime._server_orders.get(8, {}))
            self.assertIsNone(command)
            self.assertFalse(expired)
            self.assertFalse(self.state['local_combat_manoeuvre'])
            self.assertEqual(outcome, self.state['_friendly_reposition_event']['outcome'])

    def test_arrival_releases_owner_and_keeps_friendly_shot_gate(self):
        self.mark(10.)
        point = self.runtime._friendly_repositions[8]['destination']
        self.state.update(x=point[0], y=point[1], z=point[2])
        self.assertEqual((None, False), self.runtime._friendly_reposition_order(
            self.state, {18:self.target}, 11., self.runtime._server_orders.get(8, {})))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertEqual('arrived', self.state['_friendly_reposition_event']['outcome'])


class LocalActionFeedbackTests(unittest.TestCase):

    def setUp(self):
        self.module = _load()
        diagnostic = mock.patch.object(self.module, 'detailed_enabled', return_value=True)
        diagnostic.start()
        self.addCleanup(diagnostic.stop)
        self.runtime = self.module.BotRuntime(1)
        graph = json.loads((Path(__file__).resolve().parents[1] /
            'navgraphs/86_himmelsdorf_winter.json').read_text())
        self.nav = TerrainNavigator(lambda *unused: 1.1, baked_graph=graph)
        self.runtime.navigator = self.nav
        self.position = (-256.6, 1.1, -18.8)
        self.goal = (-256.63, 1.1, -21.96)
        self.nav.bot_states[20] = {}
        self.state = dict(id=20)
        self.command = dict(move_position=self.goal, movement_intent=True,
                            recovery_mode='blocked')
        self.proof = dict(kind='local_sweep', action='rotation',
            yaw=math.atan2(self.goal[0]-self.position[0], self.goal[2]-self.position[2]),
            native_sweep=dict(clear=False, proved=True, status='hard',
                source='authoritative_body_sweep'))

    def test_report_wall_refusal_escalates_without_a_motion_commit(self):
        # The report's stopped T-54 supplied no generic direction collision.
        # Repeated exact body refusals must reach the existing private replan.
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, [self.proof])
        self.assertEqual(1, self.nav.bot_states[20]['blocked_step_replans'])
        self.assertTrue(self.nav.bot_failed_edges[20])
        self.assertEqual({}, self.nav.grid._failed_edges)
        self.assertEqual(1, self.state['_planner_blocked_handoff']['hard_body_refusals'])
        event = dict(self.state['_planner_blocked_last_replan'])
        self.runtime._report_blocked_planner(self.position,
            dict(self.command, recovery_mode='drive'), {}, self.state, 11.25, [])
        self.assertEqual(event, self.state['_planner_blocked_last_replan'])
        self.assertEqual(11.25, self.state['_planner_blocked_handoff']['at'])
        self.assertNotEqual(event['at'], self.state['_planner_blocked_handoff']['at'])
        self.assertTrue(self.nav.bot_segment_penalized(20, self.position, self.goal, 11.3))
        self.nav.request_replan(20, self.position, 11.4)
        self.assertTrue(self.nav.bot_segment_penalized(20, self.position, self.goal, 11.5))
        self.assertFalse(self.nav.bot_segment_penalized(21, self.position, self.goal, 11.3))
        self.assertFalse(self.nav.bot_segment_penalized(20, self.position, self.goal, 30.))

    def test_repeated_live_rotation_refusals_reach_private_retry_only(self):
        self.state['_rotation_contact_trace'] = dict(
            reason='solid_lane', sampled_at=9.9, hit=(1., 2., 3.))
        rows = [dict(kind='rotation', clear=False,
                     reason='realized_rotation_rejection') for unused in range(10)]
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, rows)
        self.assertEqual(1, self.nav.bot_states[20]['blocked_step_replans'])
        self.assertEqual({}, self.nav.grid._failed_edges)
        self.assertEqual('realized_rotation_refusal',
                         self.state['_planner_blocked_handoff']['reason'])
        self.assertEqual((1., 2., 3.), self.state[
            '_planner_blocked_handoff']['realized_rotation_contact']['hit'])

    def test_mixed_unknown_rotation_is_not_a_proved_failure(self):
        rows = [dict(kind='rotation', clear=False,
                     reason='realized_rotation_rejection'),
                dict(kind='rotation', clear=None, reason='deferred')]
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, rows)
        self.assertFalse(self.nav.bot_failed_edges)

    def test_unknown_or_old_receipt_cannot_penalise_an_edge(self):
        self.state['_planning_verdicts'] = [self.proof]
        for change in (dict(clear=None), dict(proved=False), dict(status='deferred')):
            row = dict(self.proof, native_sweep=dict(self.proof['native_sweep'], **change))
            for now in (10., 10.3, 10.6, 10.9, 11.2):
                self.runtime._report_blocked_planner(self.position, self.command,
                    {}, self.state, now, [row])
        self.runtime._report_blocked_planner(self.position, self.command,
            {}, self.state, 12., [])
        self.assertFalse(self.nav.bot_failed_edges)

    def test_new_nonblocked_action_does_not_reuse_old_failure_reason(self):
        self.runtime._report_blocked_planner(self.position, self.command,
            {}, self.state, 10., [self.proof])
        command = dict(self.command, recovery_mode='drive')
        self.runtime._report_blocked_planner(self.position, command, {}, self.state, 11., [])
        self.assertEqual('no_blocked_movement', self.state['_planner_blocked_handoff']['reason'])
        self.assertEqual(11., self.state['_planner_blocked_handoff']['at'])

    def test_opposite_rotation_wall_cannot_penalise_forward_goal(self):
        proof = dict(self.proof, yaw=self.proof['yaw'] + math.pi)
        for now in (10., 10.3, 10.6, 10.9, 11.2):
            self.runtime._report_blocked_planner(self.position, self.command,
                {}, self.state, now, [proof])
        self.assertFalse(self.nav.bot_failed_edges)

    def test_same_cell_point_refusal_selects_another_existing_candidate(self):
        nav = TerrainNavigator(lambda *unused: 0., baked_graph=_flat_open_graph())
        start, goal = (0., 0., 0.), (0., 0., 40.)
        first = nav.grid.safe_local_target(start, goal, 10.)
        receipt = {}
        second = nav.grid.safe_local_target(start, goal, 10., diagnostic=receipt,
            excluded_target_points=(first,))
        self.assertIsNotNone(second)
        self.assertGreater(math.hypot(second[0]-first[0],second[2]-first[2]), 1.5)
        self.assertGreater(receipt['proved_point_rejected'], 0)
        self.assertEqual(first, nav.grid.safe_local_target(start, goal, 30.))


class ServerManoeuvreOwnershipTests(unittest.TestCase):
    def test_retired_tactical_modes_cannot_reenter_through_movement_leases(self):
        planner = BotPlanner()
        bot = dict(id=14, state=_state(14, 1, -150., 74.4))
        focus = dict(target_kind='bot', id=20)
        for mode in ('flank', 'support_hold', 'take_cover', 'cover_hold', 'cover_peek',
                     'cover_return', 'withdraw', 'low_health_retreat',
                     'magazine_reload_retreat', 'team_turnback'):
            for x in (-150., -160.):
                with self.subTest(mode=mode, x=x):
                    bot['state']['x'] = x
                    previous = dict(id=14, target_kind='bot', target_id=20,
                        combat_mode=mode,
                        move_position=dict(x=-148.837,y=1.1,z=75.174),
                        throttle_override=1.)
                    planner._last_orders = dict(orders=[previous])
                    order = {}
                    self.assertFalse(planner._apply_leased_movement_order(
                        order, bot, focus))
                    self.assertEqual({}, order)

    def test_codec_carries_begin_and_end_without_extra_columns(self):
        state = _bot_state()
        lengths = []
        for active in (False, True, False):
            state['local_combat_manoeuvre'] = active
            row = bot_state_codec.encode_row(state)
            lengths.append(len(row))
            self.assertEqual(active, bot_state_codec.decode_row(row, STATIC)['local_combat_manoeuvre'])
        self.assertEqual(1, len(set(lengths)))

    def test_local_manoeuvre_receipt_cannot_start_an_idle_fire_timer(self):
        planner = BotPlanner()
        route = _route('lane', [(0, -100, False), (0, 100, False)])
        bot = _bot(10, 1, 0, route, 'mediumTank')
        state = _state(10, 1, 0., 0.)
        state['fire_seq'] = 7
        player = dict(id=20, team=2, alive=True)
        for now, active in ((1., True), (8., True), (20., True),
                            (21., False), (30., False)):
            state['local_combat_manoeuvre'] = active
            contact = _contact(20, 50., 80., [10])
            planner.report_contacts([contact],
                planner.known_targets([state], [player]), now)
            command = planner.build_orders(
                [bot], [state], [player], now)['orders'][0]
            self.assertEqual('engage', command['combat_mode'])
            self.assertEqual(dict(x=0., y=0., z=0.), command['move_position'])
            self.assertEqual(0., command['throttle_override'])
            self.assertTrue(command['fire_allowed'])
            self.assertNotIn('firing_hold', command['tactical_evidence'])
        self.assertFalse(hasattr(planner, '_firing_holds'))


class CombatRecoveryHandoffTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('himmelsdorf', 11,
            navigation_target=lambda bot,pos,goal,*unused: goal)
        self.state = dict(id=14, team=1, slot=13, position=(0.,0.,0.),
            yaw=0., speed=0., dt=.1, half_length=3., half_width=1.5,
            navigation_status='safe')
        self.order = dict(combat_mode='engage', target_id=20,
            aim_position=(0.,0.,100.), face_position=(0.,0.,100.),
            move_position=(0.,0.,0.), throttle_override=0., fire_allowed=True)

    def test_engagement_preempts_contact_escape_and_wreck_push(self):
        with mock.patch.object(self.adapter, '_retained_contact_escape') as retained, \
                mock.patch.object(self.adapter, '_wreck_push_plan') as wreck:
            command = self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
        retained.assert_not_called()
        wreck.assert_not_called()
        self.assertEqual('engage',command['combat_mode'])
        self.assertEqual(20,command['target_id'])
        self.assertEqual(0.,command['throttle'])
        self.assertEqual('combat_hold',command['control_trace']['action_owner'])

    def test_stationary_engagement_ends_inflight_driver_recovery(self):
        route = dict(self.order,combat_mode='route',target_id=None,
            move_position=(0.,0.,80.),throttle_override=None)
        self.adapter.decide_with_order(self.state,route,lambda *args: True)
        state = self.adapter.driver.states[14]
        state.update(recovery_time=2.,recovery_side=1.,stuck_time=4.)
        command = self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
        self.assertEqual(0.,state['recovery_time'])
        self.assertEqual(0.,state['stuck_time'])
        self.assertEqual('arrived',command['recovery_mode'])
        self.assertEqual(20,command['target_id'])

    def test_retired_reverse_owner_is_absent_from_adapter(self):
        self.assertFalse(hasattr(self.adapter, '_reverse_withdrawal'))
        self.assertFalse(hasattr(self.adapter, '_withdrawal_attempts'))
        order = dict(self.order,combat_mode='route',throttle_override=None,
                     move_position=(0.,0.,80.))
        with mock.patch.object(self.adapter.driver,'drive',wraps=self.adapter.driver.drive) as drive:
            self.adapter.decide_with_order(self.state,order,lambda *args: True)
        drive.assert_called_once()

    def test_base_defence_keeps_checked_travel_owner(self):
        order = dict(self.order,combat_mode='base_defense',
            move_position=(0.,0.,80.),throttle_override=1.)
        with mock.patch.object(self.adapter,'_retained_contact_escape',return_value=None) as retained:
            command = self.adapter.decide_with_order(self.state,order,lambda *args: True)
        retained.assert_called_once()
        self.assertTrue(command['movement_intent'])
        self.assertFalse(command['control_trace']['combat_hold'])
        self.assertEqual('base_defense',command['control_trace']['action_owner'])

    def test_route_recovery_is_not_disabled_without_enemy(self):
        order = dict(self.order,combat_mode='route',target_id=None,
            move_position=(0.,0.,80.),throttle_override=None)
        with mock.patch.object(self.adapter,'_retained_contact_escape',return_value=None) as retained:
            self.adapter.decide_with_order(self.state,order,lambda *args: True)
        retained.assert_called_once()


if __name__ == '__main__':
    unittest.main()
