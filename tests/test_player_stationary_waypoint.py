"""Observed stationary vehicles cannot keep owning an unconsumed A* corner.

T34/T110E4 poses and chassis shapes come from report 133716, round 1 on
100_thepit. Flat support and native-clearance replies are explicit seams;
these tests exercise the real player pathfinder, modifier and driver, not
Windows motion timing or the map's complete native BSP.
"""
import json
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


def captured_pit_neighbours():
    """Report 144204, worker contact_chain at 14:41:08.530, line 5929.

    These stationary shapes/poses are shared with the opening controller
    replay. Engine IDs are joined to the visible TRACK SURFACE records by
    their unique observed positions; no private server targets are supplied.
    """
    rows = (
        (2130706441, (-46., .2500002384185791, -110.),
         (1.8386110067367554, 3.669321060180664, .011706000193953514, 1.7258760333061218), .0010183393134704946, 0.),
        (2130706443, (-18., .2539999485015869, -110.),
         (1.7990260124206543, 3.313530921936035, -.000009999999747378752, 1.938812017440796), .0015089617554458871, .00019100356491389038),
        (2130706445, (-62., .2500002384185791, -110.),
         (1.723338007926941, 3.40755295753479, -.000009999999747378752, 1.9145479798316956), 0., 0.),
        (2130706447, (-6., .2500002384185791, -110.),
         (1.7882659435272217, 3.3853719234466553, .0002519999979995191, 2.691987991333008), 0., 0.),
        (2130706449, (-74., .2500002384185791, -110.),
         (1.6142549514770508, 3.6577529907226562, .004255000036209822, 1.8282999992370605), 0., 0.),
        (2130706451, (14., .25, -110.),
         (1.2527639865875244, 2.506582021713257, 0., 1.3582489788532257), 0., 0.),
        (2130706453, (-74., .25000011920928955, -98.),
         (1.5048600435256958, 3.124521017074585, .0007050000131130219, 1.6989060044288635), .00000005722923076817417, 0.),
        (2130706455, (26., .25, -114.),
         (1.2395429611206055, 2.0993480682373047, -.0014260000316426158, 1.6680829524993896), 0., 0.),
        (2130706457, (-30., .2500002384185791, -98.),
         (1.6618980169296265, 3.407438039779663, 0., 1.7179380059242249), -.0006746860172715002, 0.),
        (2130706459, (-50., .3028402328491211, -98.),
         (1.8655439615249634, 3.1621220111846924, .0007440000190399587, 2.010150969028473), .010938742826754376, -.0677588451072916),
        (2130706461, (-18., .2500002384185791, -98.),
         (1.9185899496078491, 3.890415906906128, .0022869999520480633, 1.8815849423408508), 0., 0.),
        (2130706463, (-62., .31700026988983154, -98.),
         (1.8655439615249634, 3.122407913208008, -.0007440000190399587, 1.6375709772109985), .0014898058115962584, .008979309915734876),
        (2130706465, (-6., .2500002384185791, -98.),
         (2.037031888961792, 3.966768980026245, .0023270000237971544, 1.8543199300765991), 0., -.0007827484367733493),
        (2130706467, (-90., .2500002384185791, -110.),
         (1.2397199869155884, 3.243720054626465, .022065000608563423, 2.859639048576355), .00021118843817677078, 0.),
    )
    return [dict(id=identity, position=point, yaw=.029842, collision_shape=shape,
                 pitch=pitch, roll=roll, alive=True, team=1, speed=0., velocity=(0., 0., 0.))
            for identity, point, shape, pitch, roll in rows]


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

    def pit_scene(self):
        baked = json.loads((ROOT / 'navgraphs/100_thepit.json').read_text())
        nav = PlayerPathfinder(lambda *args: .25, lambda *args: False, baked_graph=baked)
        self.addCleanup(nav.close)
        support = PlayerHeightSupport(nav.grid, lambda *args: .25, None)
        self.addCleanup(support.close)
        return nav, support, LocalRoutes(nav, support, 1)

    def completed_fallback_scene(self, neighbours=None):
        # The position/consumed tip come from the copied-physics opening
        # fixture after the alignment-point fix, not a new Windows capture.
        # Its map and fourteen observed hulls still come from report 144204.
        scene = self.pit_scene()
        nav, support, local = scene
        current = pose(154.92099990844727,
            (-62.13645962633774, .25, -104.55434915857333), 4.675003214097741)
        completed = (-59.84345992952434, .302, -103.73001037900198)
        goal = (-78.8077, .25, -98.9527)
        request = ('route', 1, 'class_mt_rim_west', 1)
        unused, traffic = self.observe(scene, current,
            captured_pit_neighbours() if neighbours is None else neighbours)
        nav._boundary_actor = 1
        state = dict(request_key=nav._cache_key(request, goal),
            request_path_key=request, planned_goal=goal, replan_generation=0,
            last_target=current['position'], last_position=current['position'],
            progress_time=current['now'], pending_since=current['now'])
        state['local_completed_target'] = (completed, nav._local_fallback_intent(goal, state))
        nav.player_states[1] = state
        return scene, current, completed, goal, request, state, traffic

    def test_exhausted_completed_fan_uses_the_checked_actual_hull_exit(self):
        for consumer in ('failed_path', 'pending_path'):
            with self.subTest(consumer=consumer):
                scene, current, completed, goal, request, state, traffic = self.completed_fallback_scene()
                nav = scene[0]
                start, now = current['position'], current['now']
                frontier = dict(request=state['request_key'], at=now-20.,
                    visited={nav.grid.cell_for(start)}, best={}, replans=0,
                    reason='retained_route_progress')
                state['path_frontier'] = frontier
                with mock.patch.object(nav.grid, 'safe_local_target',
                                       wraps=nav.grid.safe_local_target) as choose:
                    selected = (nav._fallback_target(1, start, goal, now, None, state, True)
                        if consumer == 'failed_path' else nav._pending_target(
                            1, start, goal, now, state, immediate_safe_local=True))
                    reach = math.hypot(selected[0]-start[0], selected[2]-start[2])
                    self.assertGreater(reach, 1.5, state['local_selection'])
                    self.assertEqual([completed, start], [call.args[0] for call in choose.call_args_list])
                    self.assertFalse(nav.player_segment_penalized(1, start, selected, now))
                    self.assertTrue(nav.grid.dry_segment_clear(start, selected, now))
                    self.assertTrue(traffic.clear(math.atan2(selected[0]-start[0], selected[2]-start[2]), reach))
                    self.assertNotIn('local_completed_target', state)
                    admitted_at = state['local_target_progress_at']
                    moved = (start[0]+.02*(selected[0]-start[0])/reach,
                             start[1], start[2]+.02*(selected[2]-start[2])/reach)
                    self.assertEqual(selected, nav._safe_fallback_target(
                        1, moved, goal, now+.1, None, state))
                    self.assertEqual(2, choose.call_count)
                    self.assertEqual(admitted_at, state['local_target_progress_at'])
                self.assertIs(frontier, state['path_frontier'])
                self.assertEqual(now-20., frontier['at'])

    def test_available_completed_fan_and_active_leg_keep_their_original_owner(self):
        scene, current, completed, goal, request, state, unused = self.completed_fallback_scene([])
        nav, start, now = scene[0], current['position'], current['now']
        with mock.patch.object(nav.grid, 'safe_local_target',
                               wraps=nav.grid.safe_local_target) as choose:
            selected = nav._fallback_target(1, start, goal, now, None, state, True)
            self.assertNotEqual(start, selected)
            self.assertEqual([completed], [call.args[0] for call in choose.call_args_list])
            self.assertEqual(completed, state['local_completed_target'][0])
            admitted_at = state['local_target_progress_at']
            self.assertEqual(selected, nav._safe_fallback_target(1, start, goal, now+.1, None, state))
            self.assertEqual(1, choose.call_count)
            self.assertEqual(admitted_at, state['local_target_progress_at'])

    def test_conclusive_empty_fans_feed_the_existing_bounded_replan(self):
        scene, current, completed, goal, request, state, unused = self.completed_fallback_scene()
        nav, start, now = scene[0], current['position'], current['now']
        # An explicit native wall veto covers both the old fan and the new
        # actual-pose fan. It must keep holding while the existing retry
        # interval advances, without fabricating failed terrain edges.
        nav.grid.review_native_corridor(start, (start[0]-4., start[1], start[2]))
        nav.grid.obstacle_probe = lambda *unused: True
        with mock.patch.object(nav.grid, 'safe_local_target',
                               wraps=nav.grid.safe_local_target) as choose:
            for offset in (0., .1, 1., 11.9):
                self.assertEqual(start, nav._pending_target(
                    1, start, goal, now+offset, state, immediate_safe_local=True))
                self.assertFalse(nav.grid._proof_deferred)
                self.assertEqual(0, state['replan_generation'])
            self.assertEqual([completed, start, start, start, start],
                             [call.args[0] for call in choose.call_args_list])
        self.assertNotIn('local_completed_target', state)
        self.assertEqual(now, state['local_retry_progress']['at'])
        self.assertEqual(2, state['local_retry_progress']['failures'])
        nav.next_target(1, start, goal, request, now+12.1)
        self.assertEqual(1, state['replan_generation'])
        nav.next_target(1, start, goal, request, now+12.2)
        self.assertEqual(1, state['replan_generation'])
        self.assertEqual({}, nav.player_failed_edges)
        self.assertEqual({}, nav.grid._failed_edges)

    def test_unproved_empty_fan_preserves_the_completed_anchor_and_retry_budget(self):
        for reason in ('deferred', 'revision_changed', 'unknown_ground'):
            with self.subTest(reason=reason):
                scene, current, completed, goal, request, state, unused = self.completed_fallback_scene()
                nav, start, now = scene[0], current['position'], current['now']
                nav.grid.review_native_corridor(start, (start[0]-4., start[1], start[2]))
                def collision(*unused):
                    if reason == 'revision_changed':
                        nav.grid._native_proof_revision += 1
                        return False
                    return 'deferred'
                nav.grid.obstacle_probe = collision
                if reason == 'unknown_ground':
                    nav.grid.ground_probe = lambda *unused: None
                with mock.patch.object(nav.grid, 'safe_local_target',
                                       wraps=nav.grid.safe_local_target) as choose:
                    for offset in (0., 13.):
                        self.assertEqual(start, nav._pending_target(
                            1, start, goal, now+offset, state, immediate_safe_local=True))
                        self.assertTrue(nav.grid._proof_deferred)
                    self.assertEqual([completed, completed],
                                     [call.args[0] for call in choose.call_args_list])
                self.assertEqual(completed, state['local_completed_target'][0])
                self.assertNotIn('local_retry_progress', state)
                self.assertEqual(0, state['replan_generation'])

    def test_report_144204_clear_kv2_corner_is_not_a_circle_only_detour(self):
        scene = self.pit_scene()
        nav, support, local = scene
        selected, goal = (-26., .25, -102.), (14., .28999999165534973, 118.)
        current = pose(62.53900146484375,
            (-31.016707908194757, .2500060074375176, -109.88047219137214), 1.1877044136966244)
        context, traffic = self.observe(scene, current, captured_pit_neighbours())
        self.assertTrue(local._occupied(selected, local._bodies(current, context),
                                       math.hypot(*PLAYER_SHAPE[:2]), current))
        self.assertFalse(nav.player_segment_penalized(1, current['position'], selected, current['now']))
        self.assertTrue(nav.grid.dry_segment_clear(current['position'], selected, current['now']))
        dx, dz = selected[0]-current['position'][0], selected[2]-current['position'][2]
        self.assertTrue(traffic.clear(math.atan2(dx, dz), math.hypot(dx, dz)))
        self.assertEqual(selected, local.adjust(current, context, goal, selected,
            ('player_contact', 2130706452), traffic.clear, allow_lane=False))
        self.assertIsNone(local.leg)

    def test_finished_circle_only_midpoint_cannot_hold_the_proved_forward_corner(self):
        selected, goal = (-26., .25, -102.), (14., .28999999165534973, 118.)
        request = ('player_contact', 2130706452)
        for reason in ('bypass_completed', 'bypass_stalled', 'bypass_refused'):
            with self.subTest(reason=reason):
                scene = self.pit_scene()
                nav, support, local = scene
                current = pose(62.53900146484375,
                    (-31.016707908194757, .2500060074375176, -109.88047219137214), 1.1877044136966244)
                context, traffic = self.observe(scene, current, captured_pit_neighbours())
                nav.player_states[1] = dict(index=1, replan_generation=0)
                # These are the terminal states reported while this exact
                # corner kept passing the real pathfinder's admission.
                local._record_finished((request, selected, 0), reason)
                for now in (62.53900146484375, 74.54, 116.54):
                    current['now'] = now
                    self.assertEqual(selected, local.adjust(current, context, goal, selected,
                        request, traffic.clear, allow_lane=False))
                    self.assertEqual(1, nav.player_states[1]['index'])

    def test_completed_or_stalled_endpoint_yields_the_clear_destination_to_its_owner(self):
        goal = (-26., .25, -102.)
        request = ('local', 1, 'endpoint')
        for outcome in ('completed', 'stalled'):
            with self.subTest(outcome=outcome):
                scene = self.pit_scene()
                nav, support, local = scene
                current = pose(44.555999755859375,
                    (-35.523880391239345, .26113834925287244, -114.11042671568345), .645)
                context, traffic = self.observe(scene, current, captured_pit_neighbours())
                first = local.adjust(current, context, goal, goal, request, traffic.clear, allow_lane=False)
                self.assertEqual('bypass_issued', local.receipt['status'])
                self.assertNotEqual(goal, first)
                if outcome == 'completed':
                    current.update(now=46.356998443603516,
                        position=(-31.948739345495195, .2501904450826252, -109.37562836903275))
                else:
                    current['now'] += 9.
                context, traffic = self.observe(scene, current, captured_pit_neighbours())
                self.assertFalse(nav.player_segment_penalized(1, current['position'], goal, current['now']))
                dx, dz = goal[0]-current['position'][0], goal[2]-current['position'][2]
                self.assertTrue(traffic.clear(math.atan2(dx, dz), math.hypot(dx, dz)))
                self.assertEqual(goal, local.adjust(current, context, goal, goal,
                    request, traffic.clear, allow_lane=False))
                self.assertEqual('bypass_'+outcome, local.receipt['status'])
                current['now'] += 60.
                self.assertEqual(goal, local.adjust(current, context, goal, goal,
                    request, traffic.clear, allow_lane=False))
                self.assertIsNone(local.leg)

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

    def test_true_t110e4_centre_is_not_issued_by_the_real_planner(self):
        scene, current = self.pit_scene(), pose()
        nav, support, local = scene
        context, traffic = self.observe(scene, current, [t110e4()])
        request = ('local', 1, 'occupied_destination')
        # Removing the circle-only intermediate modifier does not remove the
        # exact planner refusal, including when the requested endpoint itself
        # is the stationary tank's centre.
        for tick in range(20):
            current['now'] = tick * .1
            target = nav.next_target(1, current['position'], CORNER, request, current['now'])
            selected = local.adjust(current, context, CORNER, target, request,
                                    traffic.clear, allow_lane=False)
            self.assertGreater(math.hypot(selected[0]-CORNER[0], selected[2]-CORNER[2]), 1.5)
            self.assertFalse(nav.player_segment_penalized(1, current['position'], selected, current['now']))
            self.assertFalse(nav.target_is_terminal(1))

    def test_real_planner_rejects_the_occupied_corner_after_each_captured_retreat(self):
        scene = self.scene()
        nav, support, local = scene
        # These are the repeatedly completed head-on retreats in the report.
        # Feed the stale corner through the actual planner, not straight into
        # a modifier while treating its indefinite self-position hold as a fix.
        for now, point in ((13., (-52.258, .25, -82.193)),
                           (27., (-52.222, .25, -82.233)),
                           (52., (-52.295, .25, -78.859))):
            current = pose(now, point)
            context, traffic = self.observe(scene, current, [t110e4()])
            key = self.path_key(nav)
            nav.paths[key], nav.path_times[key] = (point, CORNER, GOAL), now
            nav.path_hull_revisions[key] = nav.grid.static_hull_revision
            moving = False
            for tick in range(20):
                current['now'] = now + tick*.1
                target = nav.next_target(1, point, GOAL, REQUEST, current['now'])
                selected = local.adjust(current, context, GOAL, target, REQUEST, traffic.clear)
                self.assertGreater(math.hypot(selected[0]-CORNER[0], selected[2]-CORNER[2]), 1.5)
                self.assertFalse(nav.player_segment_penalized(1, point, selected, current['now']))
                dx, dz = selected[0]-point[0], selected[2]-point[2]
                if math.hypot(dx, dz) > 1.5:
                    self.assertTrue(traffic.clear(math.atan2(dx, dz), math.hypot(dx, dz)))
                    moving = True
                    break
            self.assertTrue(moving, (point, nav.player_states[1]))

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
        previous = current['position']
        for tick in range(160):
            current['now'] = tick * .1
            current['speed'] = math.hypot(current['position'][0]-previous[0],
                                          current['position'][2]-previous[2]) / .1
            previous = current['position']
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
                # Heading is an instantaneous geometry seam; observed speed is
                # derived from the preceding realised step, not native dynamics.
                current['yaw'] = heading
                command = driver.drive(current['position'], heading, current['speed'], target,
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

    def test_endpoint_bypass_requires_wall_height_and_live_clearance_before_handoff(self):
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
                    target = local.adjust(current, context, CORNER, CORNER, REQUEST, traffic.clear)
                # No unproved bypass is published. Returning the unchanged
                # proposal yields to the path/driver owners; the real planner
                # test above rejects an actually occupied destination.
                self.assertEqual(CORNER, target)
                self.assertEqual('no_checked_bypass', local.receipt['status'])
                self.assertEqual(1, nav.player_states[1]['index'])
                remember.assert_not_called()
                self.assertIsNone(local.leg)
                # Missing proof is retried without inventing a permanent wall.
                current['now'] = 1.
                target = local.adjust(current, context, CORNER, CORNER, REQUEST, traffic.clear)
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
