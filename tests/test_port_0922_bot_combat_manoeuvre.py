"""Windows401 report 172753: completed flanks and bounded local ownership."""
import math
import json
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_bot_runtime import _load, _flat_open_graph
from test_port_0922_server_bot_ai import BotPlanner, _state
from test_port_0922_bot_state_codec import _bot_state, STATIC
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import bot_state_codec


class FlankArrivalTests(unittest.TestCase):
    def setUp(self):
        self.goal = (-148.837, 1.1, 75.174)
        self.enemy = (-255.7, 1.1, -.66)
        self.adapter = BotAdapter('himmelsdorf', 11,
            navigation_target=lambda bot, pos, goal, *unused: goal)
        self.order = dict(combat_mode='flank', target_id=20,
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

    def test_track_pivot_cannot_restart_completed_flank(self):
        self.decide((-150., 1.1, 74.4))
        for unused in range(120):
            command = self.decide((-150.5, 1.1, 74.14))
            self.assertEqual('arrived', command['recovery_mode'])
            self.assertEqual(0., command['throttle'])
            self.assertEqual(20, command['target_id'])
        self.adapter.forget(14)
        self.assertNotIn(14, self.adapter._flank_arrivals)

    def test_displacement_and_new_orders_release_arrival(self):
        for replacement, position in ((dict(self.order, move_position=(-140., 1.1, 90.)),
                (-150., 1.1, 74.4)), (self.order, (-155., 1.1, 74.4))):
            self.decide((-150., 1.1, 74.4))
            self.decide(position, replacement)
            self.assertNotIn(14, self.adapter._flank_arrivals)

    def test_normal_route_retains_forward_throttle(self):
        command = self.decide((-150., 1.1, 74.4), dict(self.order,
            combat_mode='route', move_position=(-170., 1.1, 60.)))
        self.assertTrue(command['movement_intent'])
        self.assertNotIn(14, self.adapter._flank_arrivals)


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
                self.state, {18: self.target}, now)
            self.assertFalse(expired)
            self.assertEqual(marker['destination'], command['move_position'])
        self.assertTrue(self.state['local_combat_manoeuvre'])

    def test_turreted_vehicle_keeps_original_four_second_budget(self):
        self.runtime._gun_yaw_limits[8] = (-math.pi, math.pi, False)
        self.mark(10.)
        self.assertEqual(14., self.runtime._friendly_repositions[8]['deadline'])

    def test_repeated_blocked_shot_cannot_extend_active_deadline(self):
        self.mark(10.)
        deadline = self.runtime._friendly_repositions[8]['deadline']
        self.mark(11.)
        self.assertEqual(deadline, self.runtime._friendly_repositions[8]['deadline'])

    def test_new_priority_target_cancels_old_manoeuvre(self):
        self.mark(10.)
        self.runtime._server_orders[8] = dict(target_id=19, target_kind='bot')
        self.assertEqual((None, False), self.runtime._friendly_reposition_order(
            self.state, {18:self.target}, 11.))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertEqual('target_changed', self.state['_friendly_reposition_event']['outcome'])

    def test_retreat_cannot_start_a_new_lane_override(self):
        self.command['combat_mode'] = 'low_health_retreat'
        self.assertFalse(self.mark(10.))
        self.assertNotIn(8, self.runtime._friendly_repositions)

    def test_timeout_clears_owner_and_prevents_identical_immediate_retry(self):
        self.mark(10.)
        marker = dict(self.runtime._friendly_repositions[8])
        end = marker['deadline'] + .01
        self.assertEqual((None, True), self.runtime._friendly_reposition_order(
            self.state, {18: self.target}, end))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertFalse(self.mark(end + .2))
        self.assertTrue(self.mark(end + 8.1))
        self.assertEqual(-marker['side'], self.runtime._friendly_repositions[8]['side'])

    def test_target_death_and_priority_handoff_release_owner(self):
        for order, target, outcome in (({}, dict(self.target, alive=False), 'target_gone'),
                (dict(combat_mode='low_health_retreat'), self.target, 'priority_handoff'),
                (dict(combat_mode='base_defense'), self.target, 'priority_handoff')):
            self.runtime._server_orders[8] = order
            self.mark(10.)
            command, expired = self.runtime._friendly_reposition_order(self.state, {18:target}, 11.)
            self.assertIsNone(command)
            self.assertFalse(expired)
            self.assertFalse(self.state['local_combat_manoeuvre'])
            self.assertEqual(outcome, self.state['_friendly_reposition_event']['outcome'])

    def test_arrival_releases_owner_and_keeps_friendly_shot_gate(self):
        self.mark(10.)
        point = self.runtime._friendly_repositions[8]['destination']
        self.state.update(x=point[0], y=point[1], z=point[2])
        self.assertEqual((None, False), self.runtime._friendly_reposition_order(
            self.state, {18:self.target}, 11.))
        self.assertFalse(self.state['local_combat_manoeuvre'])
        self.assertEqual('arrived', self.state['_friendly_reposition_event']['outcome'])


class LocalActionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.runtime = _load().BotRuntime(1)
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
    def test_completed_flank_without_lane_yields_to_existing_route_branch(self):
        planner = BotPlanner()
        bot = dict(id=14, state=_state(14, 1, -150., 74.4))
        focus = dict(target_kind='bot', id=20)
        previous = dict(id=14, target_kind='bot', target_id=20,
            combat_mode='flank', move_position=dict(x=-148.837,y=1.1,z=75.174),
            throttle_override=1.)
        planner._last_orders = dict(orders=[previous])
        order = {}
        self.assertFalse(planner._apply_leased_movement_order(order, bot, focus))
        self.assertEqual('completed_flank_without_lane',
            order['tactical_evidence']['flank_handoff']['reason'])
        bot['state'].update(x=-160.)
        self.assertTrue(planner._apply_leased_movement_order({}, bot, focus))

    def test_codec_carries_begin_and_end_without_extra_columns(self):
        state = _bot_state()
        lengths = []
        for active in (False, True, False):
            state['local_combat_manoeuvre'] = active
            row = bot_state_codec.encode_row(state)
            lengths.append(len(row))
            self.assertEqual(active, bot_state_codec.decode_row(row, STATIC)['local_combat_manoeuvre'])
        self.assertEqual(1, len(set(lengths)))

    def test_local_motion_pauses_idle_fire_timer_and_release_restarts_it(self):
        planner = BotPlanner()
        bot = dict(id=10, state=_state(10, 1, 0., 0.))
        bot['state'].update(fire_seq=7, local_combat_manoeuvre=True)
        def order():
            return dict(combat_mode='engage', throttle_override=0.,
                target_id=20, target_kind='bot')
        for now in (0., 8., 20.):
            command = order()
            planner._release_unproductive_firing_hold(command, bot,
                dict(x=0.,y=0.,z=100.), dict(x=0.,y=0.,z=80.), now)
            self.assertEqual('engage', command['combat_mode'])
            self.assertEqual('local_combat_manoeuvre_active',
                command['tactical_evidence']['firing_hold']['reason'])
        bot['state']['local_combat_manoeuvre'] = False
        command = order()
        planner._release_unproductive_firing_hold(command, bot,
            dict(x=0.,y=0.,z=100.), dict(x=0.,y=0.,z=80.), 21.)
        self.assertEqual(0., command['tactical_evidence']['firing_hold']['ready_elapsed'])
        command = order()
        planner._release_unproductive_firing_hold(command, bot,
            dict(x=0.,y=0.,z=100.), dict(x=0.,y=0.,z=80.), 30.)
        self.assertEqual('route', command['combat_mode'])


if __name__ == '__main__':
    unittest.main()
