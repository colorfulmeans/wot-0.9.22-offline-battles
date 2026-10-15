"""Command ownership regressions on the initial v0.10.1 navigation law."""
import math
import unittest
from unittest import mock

from test_port_0922_driver_arrival import BotAdapter, vehicle_physics
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state


class InitialNavigationHandoffTests(unittest.TestCase):
    @staticmethod
    def state(team=1, slot=0, size=(1.5, 3.5), yaw=0.0):
        return dict(id=slot+1, slot=slot, team=team, position=(0., 0., 0.),
                    yaw=yaw, speed=0., dt=.1, half_width=size[0],
                    half_length=size[1], collision_shape=(size[0], size[1], -.8, 2.),
                    turn_speed_limit=.5, neighbours=[], pose_clear=lambda yaw: True)

    def test_strategic_drive_preserves_local_braking_across_slots_and_hulls(self):
        for team in (1, 2):
            for slot in range(15):
                for size in ((1., 2.), (1.7, 3.5), (2.5, 5.)):
                    for distance in (2., 6., 20.):
                        for yaw in (0., .2, .4, .6):
                            for mode in ('advance', 'friendly_lane_reposition', 'take_cover'):
                                state = self.state(team, slot, size, yaw)
                                command = BotAdapter('airfield', 1).decide_with_order(
                                    state, dict(combat_mode=mode,
                                                move_position=(0., 0., distance),
                                                throttle_override=1.), lambda *args: True)
                                self.assertFalse(command['brake'] and command['throttle'] > 0.,
                                                 (team, slot, size, distance, yaw, mode))

    def test_turn_alignment_then_advance_reaches_close_goal(self):
        for slot in range(15):
            adapter = BotAdapter('airfield', 1)
            state = self.state(slot=slot, yaw=.6)
            params = dict(vehicle_physics._DEFAULTS, rotSpd=.5)
            omega = 0.
            commands = []
            for unused in range(150):
                command = adapter.decide_with_order(state,
                    dict(combat_mode='advance', move_position=(0., 0., 6.),
                         throttle_override=1.), lambda *args: True)
                commands.append(command)
                omega = vehicle_physics.traverse_step(params, omega, command['turn'],
                    state['speed'], .1, drive_intent=command['throttle'])
                state['yaw'] += omega*.1
                state['speed'] = vehicle_physics.longitudinal_step(params, state['speed'],
                    command['throttle'], command['turn'], 0., .1, handbrake=command['brake'])
                x, y, z = state['position']
                state['position'] = (x+math.sin(state['yaw'])*state['speed']*.1, y,
                                     z+math.cos(state['yaw'])*state['speed']*.1)
                if math.hypot(state['position'][0], 6.-state['position'][2]) <= 1.5:
                    break
            self.assertLessEqual(math.hypot(state['position'][0], 6.-state['position'][2]), 1.5)
            self.assertTrue(any(c['brake'] and c['turn'] for c in commands))
            self.assertTrue(any(c['throttle'] > 0. and not c['brake'] for c in commands))

    def test_parallel_contact_does_not_steal_route_or_hold(self):
        for team in (1, 2):
            for slot in range(15):
                for side in (-1., 1.):
                    for held in (False, True):
                        state = self.state(team, slot)
                        state['neighbours'] = [dict(id=100, team=team, alive=True,
                            position=(side*3., 0., 0.), yaw=0., half_width=1.5,
                            half_length=3.5, shape=(1.5, 3.5, -.8, 2.), velocity=(0., 0., 0.))]
                        adapter = BotAdapter('airfield', 1)
                        order = dict(combat_mode='hold' if held else 'route',
                            move_position=(0., 0., 0. if held else 8.),
                            throttle_override=0. if held else None)
                        with mock.patch.object(adapter, '_contact_escape_plan',
                                               wraps=adapter._contact_escape_plan) as escape:
                            command = adapter.decide_with_order(state, order, lambda *args: True)
                        self.assertEqual(escape.call_count, 0)
                        self.assertNotEqual(command['recovery_mode'], 'contact_escape')
                        if held:
                            self.assertFalse(command['movement_intent'])
                            self.assertEqual(command['throttle'], 0.)

    def test_penetration_or_goal_into_side_keeps_original_escape_checks(self):
        for x, goal in ((2.9, (0., 0., 8.)), (3., (4., 0., 8.))):
            state = self.state()
            state['neighbours'] = [dict(id=100, team=1, alive=True,
                position=(x, 0., 0.), yaw=0., half_width=1.5, half_length=3.5,
                shape=(1.5, 3.5, -.8, 2.), velocity=(0., 0., 0.))]
            adapter = BotAdapter('airfield', 1)
            with mock.patch.object(adapter, '_contact_escape_plan',
                                   wraps=adapter._contact_escape_plan) as escape:
                adapter.decide_with_order(state, dict(combat_mode='route',
                    move_position=goal), lambda *args: True)
            self.assertEqual(escape.call_count, 1)

    @staticmethod
    def route_scene():
        planner = BotPlanner()
        route = _route('handoff_lane', [(0, 0, False), (0, 100, False),
                                       (0, 200, False), (0, 300, False)])
        bot = _bot(1, 1, 0, route, 'heavyTank')
        bot['state'] = _state(1, 1, 0, 0)
        return planner, bot

    @staticmethod
    def route_order(planner, bot, now, mode, override):
        rid, idx, move, anchor, join = planner._route(bot, now)
        return dict(id=1, combat_mode=mode, throttle_override=override,
                    route_id=rid, route_index=idx, move_position=move)

    def test_route_advance_handoffs_keep_original_twenty_second_gate_budget(self):
        for sequence in (('route',), ('advance',), ('route', 'advance')):
            planner, bot = self.route_scene()
            for now in range(21):
                mode = sequence[now % len(sequence)]
                order = self.route_order(planner, bot, now, mode,
                                         1. if mode == 'advance' else None)
                planner._reroute_wreck_stall(order, bot, [bot], now)
                if now < 20:
                    self.assertNotIn('route_point_skip_reason', order)
                else:
                    self.assertEqual(order['route_point_skip_reason'], 'blocked_timeout')
                    self.assertEqual(order['previous_route_index']+1, order['route_index'])
                    waypoint = bot['route']['waypoints'][order['route_index']]
                    self.assertEqual(order['move_position'],
                                     {key: waypoint[key] for key in ('x', 'y', 'z')})

    def test_holds_commands_and_disabled_vehicles_do_not_accrue_stall(self):
        for override, command, disabled in ((0., False, False), (-1., False, False),
                                            (1., True, False), (1., False, True)):
            planner, bot = self.route_scene()
            for now in range(25):
                order = self.route_order(planner, bot, now, 'advance', override)
                if command:
                    order['team_command'] = 'move'
                with mock.patch.object(planner, '_route_donor_eligible', return_value=not disabled):
                    planner._reroute_wreck_stall(order, bot, [bot], now)
                self.assertNotIn('route_point_skip_reason', order)
            self.assertNotIn(1, planner._wreck_route_progress)

    def test_real_forward_progress_renews_existing_gate_budget(self):
        planner, bot = self.route_scene()
        for now in range(21):
            if now == 15:
                bot['state']['z'] = 6.
            order = self.route_order(planner, bot, now, 'advance', 1.)
            planner._reroute_wreck_stall(order, bot, [bot], now)
            self.assertNotIn('route_point_skip_reason', order)
        self.assertEqual(planner._wreck_route_progress[1]['since'], 15.)


if __name__ == '__main__':
    unittest.main()
