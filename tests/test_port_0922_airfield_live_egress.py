"""Report 225339: unsnapped occupied cells must not become synthetic walls.

Positions and goals are from the user's 0.9.3 hidden-worker BOT MOTION records.
The shipped graph is real; native support/collision replies are controlled
fixtures. These tests do not claim Windows acceptance of the captured scene.
"""
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime

ROOT = Path(__file__).resolve().parents[1]
REPORT_POSES = (
    (2, (343.71959872053503, -0.17999887466430664, -161.8906274280862),
     (282.7417022646512, -8.03, -170.94468176434148)),
    (18, (-296.94985268843425, -0.17999887466430664, -191.80153238809643),
     (-313.08065044950047, -0.18, -134.89442719099992)),
    (25, (-288.60957913357714, -0.17999887466430664, -166.60278451821057),
     (-312.005198856603, -5.846, -54.32241294010958)),
    (26, (-278.062505535449, -0.17999839782714844, -144.5884673404018),
     (-234.0, 0.0, -206.0)),
    (27, (-286.0261670751786, -0.17999887466430664, -186.38427289358302),
     (-329.00539956960966, -6.35, -5.767693003237659)),
    (30, (-268.17565537759526, 0.12851428985595703, -137.74413645531496),
     (-229.33997664229352, -8.17, -204.18776869422527)),
)


class AirfieldLiveEgressTests(unittest.TestCase):
    def setUp(self):
        self.graph = json.loads((ROOT / 'navgraphs/31_airfield.json').read_text())

    def scene(self, current, goal, ground=None, obstacle=None):
        samples, rays = [], []
        def ground_probe(x, z, hint):
            samples.append((x, z, hint))
            return current[1] if ground is None else ground(x, z, hint)
        def obstacle_probe(start, end, half_width):
            rays.append((tuple(start), tuple(end), half_width))
            return False if obstacle is None else obstacle(start, end, half_width)
        nav = TerrainNavigator(ground_probe, obstacle_probe, baked_graph=self.graph)
        nav.grid.review_native_corridor(current, goal)
        return nav, samples, rays

    def test_reported_occupied_cells_can_exit_after_native_review(self):
        for bot, current, goal in REPORT_POSES:
            with self.subTest(bot=bot):
                nav, samples, rays = self.scene(current, goal)
                self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(current)))
                state = {'pending_since': 0.0}
                target = nav._pending_target(bot, current, goal, 1.0, state)
                self.assertNotEqual(current, target)
                self.assertGreater(math.hypot(target[0]-current[0], target[2]-current[2]), 1.5)
                self.assertTrue(nav.grid.dry_segment_clear(current, target, 1.0))
                self.assertTrue(samples)
                self.assertTrue(any(ray[0] == current and ray[1][0] == target[0]
                                    and ray[1][2] == target[2] for ray in rays))
                self.assertEqual('pending', state['navigation_status'])

    def test_pending_real_navigator_releases_driver_at_simulated_cadences(self):
        descriptor = {'type': {'name': 'fixture', 'tags': ('mediumTank',)},
                      'physics': {'speedLimits': (18.0,)}, 'hull': {},
                      'turret': {}, 'gun': {'shots': ()}}
        yaws = (-1.6190630752041757, -0.33802882616391305,
                -0.35569306375834053, 2.6040338608473577,
                -0.25993647587052265, 2.6744495558238204)
        for (bot, current, goal), yaw in zip(REPORT_POSES, yaws):
            for fps in (60, 15, 5):
                with self.subTest(bot=bot, fps=fps):
                    nav, samples, rays = self.scene(current, goal)
                    def navigation_target(bot_id, position, target, order, state):
                        return nav.next_target(bot_id, position, target,
                            ('join', bot_id, nav.grid.cell_for(position)), state['now'])
                    adapter = BotAdapter('31_airfield', 7,
                                         navigation_target=navigation_target)
                    adapter.register(bot, 1, descriptor)
                    state = {'id': bot, 'slot': 0, 'position': current,
                             'yaw': yaw, 'speed': 0.0, 'dt': 1.0 / fps,
                             'now': 0.0, 'neighbours': ()}
                    strategic = {'move_position': goal, 'fire_allowed': False,
                                 'fire_range': 400.0, 'combat_mode': 'route',
                                 'shell_index': 0}
                    # Keep a genuine A* job queued: this is a pending-job exit,
                    # not a test replacing the navigator with a clear fake.
                    for frame in range(fps + 1):
                        nav.begin_frame(0.0)
                        nav.search_credit = 0.0
                        state['now'] = float(frame) / fps
                        order = adapter.decide_with_order(state, strategic,
                                                           lambda angle: True)
                        nav.end_frame()
                    self.assertTrue(nav.searches)
                    self.assertNotEqual('nav_wait', order['recovery_mode'])
                    self.assertTrue(order['movement_intent'])
                    self.assertTrue(abs(order['turn']) > 0.0 or
                                    abs(order['throttle']) > 0.0)
                    self.assertEqual(current, state['position'])
                    # Once facing the proven local waypoint the ordinary
                    # driver must request travel, not retain a waiting brake.
                    local = order['move_position']
                    state['yaw'] = math.atan2(local[0] - current[0],
                                              local[2] - current[2])
                    nav.begin_frame(0.0)
                    nav.search_credit = 0.0
                    state['now'] += 1.0 / fps
                    order = adapter.decide_with_order(state, strategic,
                                                       lambda angle: True)
                    nav.end_frame()
                    self.assertGreater(order['throttle'], 0.0)
                    self.assertFalse(order['brake'])
                    self.assertEqual(current, state['position'])

    def test_adjacent_missing_cell_does_not_require_a_snapped_graph_link(self):
        # This is a generated pose after 0.37 m of integrated movement from
        # report Bot 30, not an additional captured Windows position. The
        # nearest-cell corridor changes, but the actual native ray stays clear.
        bot, unused_current, goal = REPORT_POSES[-1]
        current = (-267.85435219250706, 0.12851428985595703,
                   -137.93039933299315)
        yaw = math.atan2(goal[0] - current[0], goal[2] - current[2]) - 1.75
        target = (current[0] + math.sin(yaw) * 3.12, current[1],
                  current[2] + math.cos(yaw) * 3.12)
        nav, samples, rays = self.scene(current, goal)
        self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(current)))
        self.assertEqual((False, 0), nav.grid._baked_corridor(current, target))
        self.assertTrue(nav.grid.dry_segment_clear(current, target, 1.0))
        self.assertTrue(samples)
        self.assertEqual(current, rays[-1][0])
        # The earlier bypass must still require each native safety condition.
        nav.grid.obstacle_probe = lambda *args: True
        self.assertFalse(nav.grid.dry_segment_clear(current, target, 1.0))
        nav.grid.obstacle_probe = lambda *args: False
        for height in (None, float('nan'), 20.0, -20.0):
            nav.grid.ground_probe = lambda *args: height
            self.assertFalse(nav.grid.dry_segment_clear(current, target, 1.0))

    def test_integrated_motion_continues_beyond_the_first_missing_cell(self):
        from test_port_0922_bot_runtime import _combat_descriptor
        from effective_params_fixture import bot_default_crew_factors
        from gui.mods.offline_lan_0922 import loadout
        # Exercise the real integrator, not just a positive drive command at
        # a fixed pose. Native probes are flat/clear; the generic descriptor
        # is deliberately not presented as these vehicles' retail physics.
        with mock.patch.object(loadout, 'attribute_factors',
                               bot_default_crew_factors), redirect_stdout(io.StringIO()):
            for bot, current, goal in REPORT_POSES:
                for fps in (5, 15):
                    with self.subTest(bot=bot, fps=fps):
                        runtime = BotRuntime(1,
                            descriptor_resolver=lambda *args: _combat_descriptor(),
                            direction_probe=lambda *args: dict(
                                clear=True, collision=False, slope=0.0),
                            spawn_resolver=lambda *args: (current, math.atan2(
                                goal[0] - current[0], goal[2] - current[2])),
                            ground_probe=lambda *args: current[1],
                            physics_ground_probe=lambda *args: current[1],
                            obstacle_probe=lambda *args: False,
                            baked_graph=self.graph,
                            visibility_probe=lambda *args: False,
                            firing_lane_probe=lambda *args: False)
                        runtime.battle_start({
                            'map': '31_airfield', 'round_id': fps,
                            'bot_authority_id': 1,
                            'bots': [{'id': bot, 'team': 1 if bot < 16 else 2,
                                      'slot': 0, 'vehicle': 'fixture', 'name': 'Probe',
                                      'profile': {
                                          'class_tag': 'mediumTank',
                                          'dominant_role': 'support',
                                          'roles': {'support': 1.0}, 'shells': [],
                                          'vehicle_name': 'fixture',
                                          'desired_range': 200, 'fire_range': 500}}]})
                        nav = runtime.navigator
                        nav.grid.review_native_corridor(current, goal)
                        nav.search_credit = 0.0
                        # A* remains pending for the whole test. Local egress
                        # must not depend on it happening to complete first.
                        nav._accrue_search_credit = lambda elapsed: None
                        def navigation_target(bot_id, position, target, order, state):
                            return nav.next_target(bot_id, position, target,
                                ('join', bot_id, nav.grid.cell_for(position)), state['now'])
                        runtime.adapter.navigation_target = navigation_target
                        duration = 20 if bot == 30 else 6
                        for frame in range(fps * duration):
                            runtime._server_orders = {bot: {
                                'move_position': goal, 'fire_allowed': False,
                                'fire_range': 400, 'combat_mode': 'route', 'shell_index': 0}}
                            runtime.update(1.0 / fps, float(frame) / fps)
                        state = runtime.states[bot]
                        displacement = math.hypot(state['x'] - current[0],
                                                  state['z'] - current[2])
                        self.assertTrue(state['alive'])
                        self.assertGreater(displacement, 5.0 if bot == 30 else 1.5)

    def test_native_connector_work_is_bounded_before_a_long_route(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        self.assertFalse(nav.grid._live_baked_egress_clear(current,
            (current[0] + 200.0, current[1], current[2])))
        self.assertFalse(samples)
        self.assertFalse(rays)
        local = nav._pending_target(bot, current, goal, 1.0,
                                    {'pending_since': 0.0})
        self.assertNotEqual(current, local)
        samples[:] = []
        rays[:] = []
        self.assertTrue(nav.grid.segment_clear(current, local))
        self.assertLessEqual(len(samples), 7)
        self.assertEqual(1, len(rays))

    def test_unreviewed_and_valid_baked_links_keep_the_existing_cache(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        cell = nav.grid._nearest_baked_cell(nav.grid.cell_for(current), 2)
        first = nav.grid.point_for(cell, nav.grid._baked_cell_height(cell))
        other = next(neighbour for dx, dz, unused in nav.grid._NEIGHBOURS
                     for neighbour in [(cell[0] + dx, cell[1] + dz)]
                     if nav.grid._baked_edge_height(cell, neighbour) is not None)
        second = nav.grid.point_for(other, nav.grid._baked_cell_height(other))
        self.assertTrue(nav.grid.segment_clear(first, second))
        calls = len(rays)
        self.assertGreater(calls, 0)
        self.assertTrue(nav.grid.segment_clear(first, second))
        self.assertEqual(calls, len(rays))
        self.assertFalse(samples)
        nav.grid._native_review_cells.clear()
        nav.grid.invalidate_native_review()
        self.assertTrue(nav.grid.segment_clear(first, second))
        self.assertEqual(calls, len(rays))

    def test_stall_evidence_records_real_grid_cell_without_native_work(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        nav.bot_states[bot] = {'navigation_status': 'pending',
                               'pending_since': 0.0}
        runtime = BotRuntime.__new__(BotRuntime)
        runtime.navigator = nav
        runtime.native_motion = False
        runtime._decision_cache = {}
        runtime._server_orders = {}
        runtime._hard_contact_grinds = {}
        state = {'id': bot, 'x': current[0], 'y': current[1], 'z': current[2]}
        command = {'recovery_mode': 'nav_wait', 'movement_intent': True}
        output = io.StringIO()
        with redirect_stdout(output):
            for now in (0.0, 2.9, 3.0, 3.1):
                runtime._log_motion_stall(state, command, 0.0, 0.0, True, {}, now)
        self.assertEqual(1, output.getvalue().count('[BOT STALL]'))
        evidence = state['_motion_stall_pending']['navigation']
        self.assertEqual((210, 84), evidence['occupied_cell'])
        self.assertIsNone(evidence['occupied_cell_height'])
        self.assertEqual(nav.grid._nearest_baked_cell((210, 84), 2),
                         evidence['nearest_baked_cell'])
        self.assertEqual(3000, evidence['pending_ms'])
        self.assertGreater(evidence['native_review_cells'], 0)
        self.assertEqual([], samples)
        self.assertEqual([], rays)

    def test_actual_exit_is_checked_not_a_snapped_surrogate(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        target = nav._pending_target(bot, current, goal, 1.0, {'pending_since': 0.0})
        self.assertNotEqual(current, target)
        snapped = nav.grid._nearest_baked_cell(nav.grid.cell_for(current), 2)
        centre = nav.grid.point_for(snapped, nav.grid._baked_cell_height(snapped))
        self.assertNotEqual(current, centre)
        self.assertTrue(any(start == current for start, end, width in rays))
        # A wall crossed only by the real pose must not be bypassed by snapping.
        nav.grid.obstacle_probe = lambda start, end, width: tuple(start) == current
        self.assertFalse(nav.grid.segment_clear(current, target))

    def test_hard_wall_still_holds_every_reported_pose(self):
        for bot, current, goal in REPORT_POSES:
            with self.subTest(bot=bot):
                nav, unused_samples, unused_rays = self.scene(current, goal,
                    obstacle=lambda *args: True)
                self.assertEqual(current, nav._pending_target(
                    bot, current, goal, 1.0, {'pending_since': 0.0}))

    def test_missing_nonfinite_and_wrong_layer_support_hold(self):
        bot, current, goal = REPORT_POSES[0]
        for height in (None, float('nan'), float('inf'), -float('inf'), 20.0, -20.0):
            with self.subTest(height=height):
                nav, unused_samples, unused_rays = self.scene(current, goal,
                    ground=lambda *args: height)
                self.assertEqual(current, nav._pending_target(
                    bot, current, goal, 1.0, {'pending_since': 0.0}))

    def test_probe_exception_does_not_grant_an_exit(self):
        bot, current, goal = REPORT_POSES[0]
        def failed(*args):
            raise RuntimeError('native query unavailable')
        for kwargs in ({'ground': failed}, {'obstacle': failed}):
            with self.subTest(kwargs=kwargs):
                nav, unused_samples, unused_rays = self.scene(current, goal, **kwargs)
                self.assertEqual(current, nav._pending_target(
                    bot, current, goal, 1.0, {'pending_since': 0.0}))

    def test_no_unsafe_cell_entry_or_out_of_bounds_shortcut(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        target = nav._pending_target(bot, current, goal, 1.0, {'pending_since': 0.0})
        self.assertNotEqual(current, target)
        index = nav.grid._baked_flat_index(nav.grid.cell_for(target))
        for hazard in (1, 2, 4):
            nav.grid._baked_hazards[index] = hazard
            nav.grid._baked_corridor_cache.clear()
            nav.grid._baked_corridor_order.clear()
            self.assertFalse(nav.grid.dry_segment_clear(current, target, 1.0))
        self.assertFalse(nav.grid.segment_clear(current, (9999.0, 0, 9999.0)))

    def test_egress_is_not_cached_across_native_changes(self):
        bot, current, goal = REPORT_POSES[0]
        nav, samples, rays = self.scene(current, goal)
        target = nav._pending_target(bot, current, goal, 1.0, {'pending_since': 0.0})
        self.assertNotEqual(current, target)
        nav.grid.obstacle_probe = lambda *args: True
        self.assertFalse(nav.grid.segment_clear(current, target))
        nav.grid.obstacle_probe = lambda *args: False
        self.assertTrue(nav.grid.segment_clear(current, target))


if __name__ == '__main__':
    unittest.main()
