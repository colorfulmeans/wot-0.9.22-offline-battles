"""Observed stationary vehicles cannot keep owning an unconsumed A* corner.

T34/T110E4 poses and chassis shapes come from report 133716, round 1 on
100_thepit. Flat support and native-clearance replies are explicit seams;
these tests exercise the real player pathfinder, modifier and driver, not
Windows motion timing or the map's complete native BSP.
"""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.driving import Driver
from gui.mods.offline_lan_0922.player_control.local_routes import LocalRoutes
from gui.mods.offline_lan_0922.player_control.navigation_support import PlayerHeightSupport
from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder
from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
from test_player_navigation_independence import graph
from test_player_navigation_migration import controller


PLAYER_SHAPE = (1.5080519914627075, 2.9235379695892334,
                .0026149998884648085, 1.6808550357818604)
PEER_SHAPE = (1.8655439615249634, 3.1621220111846924,
             .0007440000190399587, 2.010150969028473)
CORNER = (-50., .303, -98.)
GOAL = (-34., .25, -130.)
REQUEST = ('route', 1, 'captured_t110e4', 0)


def pose(now=0., position=(-52.053, .25, -80.333), yaw=2.987):
    return dict(id=1, engine_id=2130706436, position=position, yaw=yaw,
                speed=0., now=now, half_width=PLAYER_SHAPE[0],
                half_length=PLAYER_SHAPE[1], collision_shape=PLAYER_SHAPE)


def t110e4(**fields):
    result = dict(id=2130706459, alive=True, team=1,
        position=(-50., .3028, -98.), yaw=.029842,
        collision_shape=PEER_SHAPE, speed=0., velocity=(0., 0., 0.))
    result.update(fields)
    return result


class StationaryWaypointTests(unittest.TestCase):
    def setUp(self):
        diagnostics = mock.patch('gui.mods.offline_lan_0922.player_control.pathfinding.write_json_record')
        diagnostics.start()
        self.addCleanup(diagnostics.stop)

    def scene(self):
        baked = graph()
        baked.update(origin=[-100., -160.], bounds=[-100., -160., 0., -60.],
                     heights_mm=[250] * len(baked['heights_mm']))
        nav = PlayerPathfinder(lambda *args: .25, lambda *args: False, baked_graph=baked)
        self.addCleanup(nav.close)
        support = PlayerHeightSupport(nav.grid, lambda *args: .25, None)
        self.addCleanup(support.close)
        return nav, support, LocalRoutes(nav, support, 1)

    def observe(self, scene, current, neighbours):
        nav, support, local = scene
        support.begin(current['position'], current['now'])
        context = dict(neighbours=neighbours)
        local.publish(current, context)
        nav.set_boundary_body(1, current['position'], current['yaw'],
                              current['half_length'], current['half_width'])
        traffic = Traffic(body(current['engine_id'], current['position'],
                               current['yaw'], PLAYER_SHAPE), neighbours)
        return context, traffic

    def path_key(self, nav):
        previous, nav._boundary_actor = nav._boundary_actor, 1
        try:
            return nav._cache_key(REQUEST, GOAL)
        finally:
            nav._boundary_actor = previous

    def subcell_scene(self, extra_side=0., goal_offset=0., erased=False, erased_radius=0):
        scene = self.scene()
        nav, support, local = scene
        peer = t110e4()
        yaw = peer['yaw']
        side, forward = (math.cos(yaw), -math.sin(yaw)), (math.sin(yaw), math.cos(yaw))
        width = PEER_SHAPE[0] - .15 + PLAYER_SHAPE[0]
        centre = (CORNER[0]+side[0]*(width+.005), .25,
                  CORNER[2]+side[1]*(width+.005))
        start = (centre[0]-.8*forward[0]+extra_side*side[0], .25,
                 centre[2]-.8*forward[1]+extra_side*side[1])
        end = (centre[0]+.8*forward[0], .25, centre[2]+.8*forward[1])
        goal = (start[0]+math.sin(yaw+goal_offset)*10.8, .25,
                start[2]+math.cos(yaw+goal_offset)*10.8)
        if erased:
            cell = nav.grid.cell_for(start)
            for oz in range(-erased_radius, erased_radius+1):
                for ox in range(-erased_radius, erased_radius+1):
                    index = nav.grid._baked_index((cell[0]+ox, cell[1]+oz))
                    nav.grid._baked_heights[index] = None
        current = pose(position=start, yaw=yaw)
        self.observe(scene, current, [peer])
        peer['position'] = (peer['position'][0]+side[0]*.02,
                            peer['position'][1], peer['position'][2]+side[1]*.02)
        self.observe(scene, current, [peer])
        nav._boundary_actor = 1
        state = dict(planned_goal=goal, request_path_key=REQUEST,
            request_key=nav._cache_key(REQUEST, goal), last_position=start,
            progress_time=0., replan_generation=0)
        nav.player_states[1] = state
        return scene, current, end, goal, state

    def test_actual_intermediate_t110e4_corner_gets_checked_local_bypass(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        context, traffic = self.observe(scene, current, [t110e4()])
        nav.player_states[1] = dict(index=1)
        selected = local.adjust(current, context, GOAL, CORNER, REQUEST, traffic.clear)
        self.assertNotEqual(CORNER, selected)
        self.assertNotEqual(current['position'], selected)
        self.assertEqual('bypass_issued', local.receipt['status'])
        self.assertTrue(local.receipt['intermediate'])
        self.assertEqual(1, nav.player_states[1]['index'])
        heading = math.atan2(selected[0]-current['position'][0], selected[2]-current['position'][2])
        reach = math.hypot(selected[0]-current['position'][0], selected[2]-current['position'][2])
        self.assertTrue(traffic.clear(heading, reach))
        self.assertTrue(nav.grid.dry_segment_clear(current['position'], selected, 0.))

    def test_completed_side_leg_and_repeated_retreat_do_not_reissue_peer_centre(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        context, traffic = self.observe(scene, current, [t110e4()])
        nav.player_states[1] = dict(index=1)
        bypass = local.adjust(current, context, GOAL, CORNER, REQUEST, traffic.clear)
        current = pose(1., bypass)
        context, traffic = self.observe(scene, current, [t110e4()])
        self.assertEqual(bypass, local.adjust(
            current, context, GOAL, bypass, REQUEST, traffic.clear))
        self.assertEqual('bypass_completed', local.receipt['status'])
        # These are the repeatedly completed head-on retreats in the report.
        for now, point in ((13., (-52.258, .25, -82.193)),
                           (27., (-52.222, .25, -82.233)),
                           (52., (-52.295, .25, -78.859))):
            current = pose(now, point)
            context, traffic = self.observe(scene, current, [t110e4()])
            selected = local.adjust(current, context, GOAL, CORNER, REQUEST, traffic.clear)
            self.assertEqual(point, selected)
            self.assertEqual(1, nav.player_states[1]['index'])
            self.assertEqual('bypass_completed', local.receipt['status'])

    def test_real_pathfinder_replaces_captured_cached_corner_and_reaches_forward_route(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        context, traffic = self.observe(scene, current, [t110e4()])
        key = self.path_key(nav)
        nav.paths[key] = [current['position'], CORNER, GOAL]
        nav.path_times[key] = 0.
        nav.path_hull_revisions[key] = nav.grid.static_hull_revision
        nav.player_states[1] = dict(request_key=key, request_path_key=REQUEST,
            planned_goal=GOAL, planned_at=0., path_key=key, index=1,
            last_position=current['position'], progress_time=0., last_target=CORNER,
            replan_generation=0)
        driver, advanced = Driver(), 0
        for tick in range(160):
            current['now'] = tick * .1
            context, traffic = self.observe(scene, current, [t110e4()])
            target = nav.next_target(1, current['position'], GOAL, REQUEST, current['now'])
            target = local.adjust(current, context, GOAL, target, REQUEST, traffic.clear)
            self.assertGreater(math.hypot(target[0]-CORNER[0], target[2]-CORNER[2]), 1.5)
            dx, dz = target[0]-current['position'][0], target[2]-current['position'][2]
            remaining = math.hypot(dx, dz)
            if remaining > 1.5:
                heading = math.atan2(dx, dz)
                self.assertTrue(traffic.clear(heading, remaining), (tick, target))
                self.assertTrue(nav.grid.dry_segment_clear(current['position'], target, current['now']))
                current['yaw'] = heading
                command = driver.drive(current['position'], heading, 0., target,
                                       current['now'], traffic.clear)
                self.assertGreater(command['throttle'], 0.)
                step = min(1., remaining)
                current['position'] = (current['position'][0]+dx/remaining*step,
                                       .25, current['position'][2]+dz/remaining*step)
                advanced += 1
            if math.hypot(current['position'][0]-GOAL[0], current['position'][2]-GOAL[2]) <= 1.5:
                break
        self.assertGreater(advanced, 25)
        self.assertLess(tick, 159, current)
        self.assertEqual({}, nav.grid._failed_edges)
        self.assertEqual({}, nav.player_failed_edges)
        self.assertEqual((), nav.grid._static_hulls)

    def test_unchanged_living_observation_keeps_revision_and_pending_search(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        revision = local.stationary_receipt['revision']
        nav._boundary_actor = 1
        with mock.patch.object(nav, '_advance_searches'), \
             mock.patch.object(nav.grid, 'begin_plan', wraps=nav.grid.begin_plan) as begin:
            key, unused = nav._path(REQUEST, current['position'], GOAL, 0., None)
            pending = nav.searches[key]
            for now in (.1, 1., 10.):
                current['now'] = now
                self.observe(scene, current, [t110e4()])
                nav._path(REQUEST, current['position'], GOAL, now, None)
                self.assertIs(pending, nav.searches[key])
                self.assertEqual(revision, local.stationary_receipt['revision'])
                self.assertFalse(local.stationary_receipt['changed'])
            self.assertEqual(1, begin.call_count)
        self.assertEqual(0, nav.grid.static_hull_revision)

    def test_moving_or_absent_vehicle_releases_only_living_layer(self):
        for neighbours in ([], [t110e4(speed=2., velocity=(0., 0., 2.))]):
            with self.subTest(neighbours=bool(neighbours)):
                scene, current = self.scene(), pose()
                nav, support, local = scene
                self.observe(scene, current, [t110e4()])
                self.assertTrue(nav.player_segment_penalized(1, current['position'], CORNER, 0.))
                current['now'] = 1.
                self.observe(scene, current, neighbours)
                self.assertFalse(nav.player_segment_penalized(1, current['position'], CORNER, 1.))
                self.assertEqual(0, local.stationary_receipt['count'])
                self.assertEqual(0, nav.grid.static_hull_revision)

    def test_unseen_enemy_unknown_speed_and_other_floor_are_not_inferred_obstacles(self):
        unknown = t110e4()
        unknown.pop('speed')
        unknown.pop('velocity')
        for peer in (t110e4(team=2, visible=False), unknown,
                     t110e4(position=(-50., 10., -98.))):
            with self.subTest(peer=peer):
                scene, current = self.scene(), pose()
                nav, support, local = scene
                self.observe(scene, current, [peer])
                self.assertFalse(nav.player_segment_penalized(1, current['position'], CORNER, 0.))
                self.assertEqual({}, nav.stationary_layers[1]['edges'])

    def test_missing_observation_channel_preserves_last_observed_layer(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        revision = local.stationary_receipt['revision']
        local.publish(current, {})
        self.assertEqual(revision, local.stationary_receipt['revision'])
        self.assertTrue(nav.player_segment_penalized(1, current['position'], CORNER, 0.))

    def test_moved_footprint_releases_old_lane_without_erasing_wrecks(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        wreck = t110e4(id=99, alive=False, position=(-80., .25, -98.))
        self.observe(scene, current, [t110e4(), wreck])
        revision = nav.grid.static_hull_revision
        self.observe(scene, current, [t110e4(position=(-20., .25, -98.)), wreck])
        self.assertFalse(nav.player_segment_penalized(1, current['position'], CORNER, 0.))
        self.assertEqual(revision, nav.grid.static_hull_revision)
        self.assertEqual(99, nav.grid._static_hulls[0][0])

    def test_live_to_wreck_transition_keeps_physical_obstacle_with_separate_owner(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        self.observe(scene, current, [t110e4(alive=False)])
        self.assertEqual(0, local.stationary_receipt['count'])
        self.assertEqual(1, local.static_receipt['count'])
        self.assertTrue(nav.grid.path_crosses_static_hull((current['position'], CORNER)))

    def test_wall_unknown_height_or_new_live_sweep_refusal_cannot_skip_corner(self):
        for refusal in ('wall', 'height', 'live_sweep'):
            with self.subTest(refusal=refusal):
                scene, current = self.scene(), pose()
                nav, support, local = scene
                context, traffic = self.observe(scene, current, [t110e4()])
                nav.player_states[1] = dict(index=1)
                owner, name = ((nav.grid, 'dry_segment_clear') if refusal == 'wall' else
                               (support, 'height') if refusal == 'height' else (traffic, 'clear'))
                with mock.patch.object(owner, name, return_value=None if refusal == 'height' else False), \
                     mock.patch.object(nav, 'remember_runtime_target', wraps=nav.remember_runtime_target) as remember:
                    target = local.adjust(current, context, GOAL, CORNER, REQUEST, traffic.clear)
                self.assertEqual(current['position'], target)
                self.assertEqual('no_checked_bypass', local.receipt['status'])
                self.assertEqual(1, nav.player_states[1]['index'])
                remember.assert_not_called()
                self.assertIsNone(local.leg)
                # Missing proof is retried from the same route, without
                # inventing a permanent wall or consuming its corner.
                current['now'] = 1.
                target = local.adjust(current, context, GOAL, CORNER, REQUEST, traffic.clear)
                self.assertNotEqual(current['position'], target)
                self.assertNotEqual(CORNER, target)

    def test_departure_invalidates_cached_no_path_without_waiting_for_old_cooldown(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        nav._boundary_actor = 1
        key = self.path_key(nav)
        nav.paths[key] = ()
        nav.path_times[key] = 0.
        nav.path_stationary_revisions[key] = local.stationary_receipt['revision']
        current['now'] = 1.
        self.observe(scene, current, [])
        unused_key, path = nav._path(REQUEST, current['position'], GOAL, 1., None)
        self.assertEqual((current['position'], GOAL), path)

    def test_new_stationary_observation_rejects_old_inflight_path_before_publication(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [])
        key = self.path_key(nav)
        job = SimpleNamespace(result=[current['position'], CORNER, GOAL],
                              progress={}, steps=1, hull_revision=0)
        nav.searches[key] = job
        nav.search_times[key] = 0.
        nav.search_stationary_revisions[key] = (1, 0)
        self.observe(scene, current, [t110e4()])
        self.assertFalse(nav._finish_search(key, job, 1.))
        self.assertNotIn(key, nav.paths)
        self.assertNotIn(key, nav.searches)

    def test_real_path_consumer_cannot_finish_a_stale_job_twice(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [])
        nav._boundary_actor = 1
        key = self.path_key(nav)
        job = SimpleNamespace(result=[current['position'], CORNER, GOAL],
                              progress={}, steps=1, hull_revision=0, done=True)
        nav.searches[key] = job
        nav.search_times[key] = 0.
        nav.search_stationary_revisions[key] = (1, 0)
        def complete(now):
            self.observe(scene, current, [t110e4()])
            nav._finish_search(key, job, now)
        with mock.patch.object(nav, '_advance_searches', side_effect=complete), \
             mock.patch.object(nav, '_finish_search', wraps=nav._finish_search) as finish:
            unused_key, result = nav._path(REQUEST, current['position'], GOAL, 1., None)
        self.assertIsNone(result)
        self.assertEqual(2, finish.call_count)
        self.assertNotIn(key, nav.paths)
        self.assertNotIn(key, nav.searches)
        self.assertNotIn(key, nav.search_stationary_revisions)

    def test_subcell_hull_shift_invalidates_cached_exact_segment_without_edge_change(self):
        scene = self.scene()
        nav, support, local = scene
        peer = t110e4()
        yaw = peer['yaw']
        side, forward = (math.cos(yaw), -math.sin(yaw)), (math.sin(yaw), math.cos(yaw))
        width = PEER_SHAPE[0] - .15 + PLAYER_SHAPE[0]
        centre = (CORNER[0]+side[0]*(width+.005), .25,
                  CORNER[2]+side[1]*(width+.005))
        start = (centre[0]-.8*forward[0], .25, centre[2]-.8*forward[1])
        end = (centre[0]+.8*forward[0], .25, centre[2]+.8*forward[1])
        current = pose(position=start, yaw=yaw)
        self.observe(scene, current, [peer])
        self.assertEqual(nav.grid.cell_for(start), nav.grid.cell_for(end))
        self.assertFalse(nav.player_segment_penalized(1, start, end, 0.))
        edges, revision = dict(nav.stationary_layers[1]['edges']), local.stationary_receipt['revision']
        nav._boundary_actor = 1
        key = nav._cache_key(REQUEST, end)
        nav.paths[key], nav.path_times[key] = (start, end), 0.
        nav.path_hull_revisions[key] = 0
        peer['position'] = (peer['position'][0]+side[0]*.02,
                            peer['position'][1], peer['position'][2]+side[1]*.02)
        self.observe(scene, current, [peer])
        self.assertEqual(edges, nav.stationary_layers[1]['edges'])
        self.assertEqual(revision, local.stationary_receipt['revision'])
        self.assertTrue(nav.player_segment_penalized(1, start, end, 1.))
        with mock.patch.object(nav, '_advance_searches'):
            unused_key, result = nav._path(REQUEST, start, end, 1., None)
        self.assertIsNone(result)
        self.assertNotIn(key, nav.paths)

    def test_current_job_subcell_overlap_becomes_bounded_no_path_not_clearance(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        key = self.path_key(nav)
        job = SimpleNamespace(result=[current['position'], CORNER, GOAL],
                              progress={}, steps=1, hull_revision=0)
        nav.searches[key], nav.search_times[key] = job, 0.
        revision = local.stationary_receipt['revision']
        nav.search_stationary_revisions[key] = (1, revision)
        self.assertTrue(nav._finish_search(key, job, 1.))
        self.assertEqual((), nav.paths[key])
        self.assertEqual('observed_stationary_hull', nav.path_native_refusals[key]['reason'])
        self.assertEqual(revision, nav.path_stationary_revisions[key])

    def test_first_local_fallback_rejects_same_cell_hull_crossing_and_selects_an_exit(self):
        scene, current, end, goal, state = self.subcell_scene()
        nav, support, local = scene
        start = current['position']
        self.assertTrue(nav.player_segment_penalized(1, start, end, 1.))
        self.assertFalse(nav.grid.path_has_edge_penalty(
            (start, end), nav._active_planning_edge_penalties(1, 1.)))
        selected = nav._fallback_target(1, start, goal, 1., None, state, True)
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 1.))
        self.assertGreater(math.hypot(selected[0]-start[0], selected[2]-start[2]), 1.5)
        self.assertTrue(nav.grid.dry_segment_clear(start, selected, 1.))
        self.assertEqual('safe', state['navigation_status'])
        self.assertEqual(selected, nav._fallback_target(1, start, goal, 1.1, None, state, True))

    def test_pending_lookahead_cannot_resurrect_an_exactly_rejected_prefix(self):
        scene, current, end, goal, state = self.subcell_scene(extra_side=.1)
        nav, support, local = scene
        start = current['position']
        self.assertFalse(nav.player_segment_penalized(1, start, start, 1.))
        self.assertTrue(nav.player_segment_penalized(1, start, end, 1.))
        self.assertFalse(nav.grid.path_has_edge_penalty(
            (start, end), nav._active_planning_edge_penalties(1, 1.)))
        request = ('local', 1, 'pending_test')
        key = nav._cache_key(request, goal)
        state.update(request_path_key=request, request_key=key, path_key=key)
        job = SimpleNamespace(done=False,
            progress=dict(start=start, revision=1, selected_path=(start, end)),
            proved_prefix=lambda grid: (start, end))
        nav.searches[key] = job
        self.assertIsNone(nav._pending_search_target(1, start, goal, 1., state, key, None))
        self.assertNotIn('pending_prefix_target', state)
        # A rejected shortcut retires this prefix, not the healthy search or
        # the player's opportunity to take another checked local connector.
        selected = nav._pending_target(1, start, goal, 1., state, immediate_safe_local=True)
        self.assertIs(job, nav.searches[key])
        self.assertNotEqual(end, selected)
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 1.))
        self.assertGreater(math.hypot(selected[0]-start[0], selected[2]-start[2]), 1.5)

    def test_first_direct_stall_escape_checks_the_exact_observed_hull(self):
        scene, current, end, goal, state = self.subcell_scene(goal_offset=-.45)
        nav, support, local = scene
        start = current['position']
        self.assertIsNone(nav.observe_direct_target(1, start, goal, REQUEST, 0.))
        selected = nav.observe_direct_target(1, start, goal, REQUEST, 13.)
        self.assertIsNotNone(selected)
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 13.))
        self.assertGreater(math.hypot(selected[0]-start[0], selected[2]-start[2]), 1.5)
        self.assertEqual(selected, nav.player_direct_progress[1]['escape_target'])

    def test_first_macro_escape_checks_the_exact_observed_hull(self):
        scene, current, end, goal, state = self.subcell_scene(goal_offset=-.45)
        nav, support, local = scene
        start = current['position']
        self.assertTrue(nav._start_macro_replan(1, state, start, goal, 13.))
        selected = state['macro_escape_target']
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 13.))
        self.assertGreater(math.hypot(selected[0]-start[0], selected[2]-start[2]), 1.5)

    def test_first_erased_cell_ingress_escape_filters_the_exact_hull_before_ranking(self):
        scene, current, end, goal, state = self.subcell_scene(goal_offset=-.45, erased=True)
        nav, support, local = scene
        start = current['position']
        self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(start)))
        self.assertIsNone(nav._stationary_ingress_escape(1, state, start, goal, 0., True, None))
        selected = nav._stationary_ingress_escape(1, state, start, goal, 13., True, None)
        self.assertIsNotNone(selected)
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 13.))
        self.assertGreater(math.hypot(selected[0]-start[0], selected[2]-start[2]), 1.5)
        self.assertTrue(nav.grid.dry_segment_clear(start, selected, 13.))
        self.assertEqual(selected, state['ingress_escape']['target'])

    def test_private_hull_refusals_do_not_exhaust_the_native_egress_probe_budget(self):
        scene, current, end, goal, state = self.subcell_scene(
            goal_offset=-.45, erased=True, erased_radius=2)
        nav, support, local = scene
        start = current['position']
        self.assertIsNone(nav._stationary_ingress_escape(1, state, start, goal, 0., True, None))
        selected = nav._stationary_ingress_escape(1, state, start, goal, 13., True, None)
        self.assertIsNotNone(selected)
        self.assertFalse(nav.player_segment_penalized(1, start, selected, 13.))
        self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(selected)))
        self.assertIn(selected, nav.grid._live_join_targets)
        attempts = state['local_fallback']['native_egress_attempts']
        self.assertLessEqual(len(attempts), 3)

    def test_height_support_refusal_uses_exact_private_admission_for_its_fallback(self):
        scene, current, end, goal, state = self.subcell_scene()
        nav, support, local = scene
        control = controller()
        control.support.close()
        control.navigator.close()
        control.navigator, control.support, control.local_routes = nav, support, local
        self.addCleanup(control.close)
        control.context = dict(neighbours=[row[0] for row in nav.stationary_layers[1]['entries']])
        emitted = []
        choose = nav.grid.safe_local_target
        def record(*args, **kwargs):
            result = choose(*args, **kwargs)
            emitted.append(result)
            return result
        inspect, first = support.inspect, [True]
        def reject_first_target(point):
            # The support oracle rejects this route target. Later candidate
            # support and geometry run normally through the actual grid.
            if first[0]:
                first[0] = False
                return 'disconnected', point
            return inspect(point)
        with mock.patch.object(support, 'inspect', side_effect=reject_first_target), \
             mock.patch.object(nav.grid, 'safe_local_target', side_effect=record):
            order = control._drive_goal(current, lambda *args: True, goal, REQUEST)
        self.assertTrue(emitted)
        for selected in emitted:
            self.assertIsNotNone(selected)
            self.assertFalse(nav.player_segment_penalized(1, current['position'], selected, 0.))
        self.assertEqual('route', order['combat_mode'])

    def test_only_this_player_observation_owns_the_temporary_edges(self):
        scene, current = self.scene(), pose()
        nav, support, local = scene
        self.observe(scene, current, [t110e4()])
        self.assertTrue(nav.player_segment_penalized(1, current['position'], CORNER, 0.))
        self.assertFalse(nav.player_segment_penalized(2, current['position'], CORNER, 0.))
        self.assertTrue(nav.grid.dry_segment_clear(current['position'], CORNER, 0.))
        self.assertEqual({}, nav.grid._failed_edges)
        self.assertEqual({}, nav.grid._static_hull_edges)


if __name__ == '__main__':
    unittest.main()
