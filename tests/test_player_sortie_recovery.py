"""Independent SPG cursor recovery preserves fresh physical movement gates."""
import copy
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.sortie import SortieProgress, geometry
from gui.mods.offline_lan_0922.player_control.strategy import Strategy
from test_player_navigation_migration import controller, state, ALIVE_ALLY


HOME = dict(point=(-100., 0.), radius=10.)
ROAD = dict(id='audit-sortie', player_sortie=True,
            waypoints=[[-100., 0., 0], [-50., 0., 0], [0., 0., 0], [0., 100., 0]])


def reached(position, supported=True):
    return lambda goal, radius: bool(supported and math.hypot(
        position[0]-goal[0], position[2]-goal[1]) <= radius)


class SortieProgressTests(unittest.TestCase):
    def update(self, progress, now, position=(-70., 0., 0.), index=2, **fields):
        return progress.update(ROAD, index, state(now, position), HOME,
                               reached(position), **fields)

    def test_stalled_c_then_d_returns_through_b_a_and_home(self):
        progress = SortieProgress()
        self.assertEqual(2, self.update(progress, 0.)['index'])
        skip = self.update(progress, 20.)
        self.assertEqual(('skip', 3, 2), (skip['phase'], skip['index'], skip['failed_index']))
        self.update(progress, 21.)
        back = self.update(progress, 41.)
        self.assertEqual(('return', 1), (back['phase'], back['index']))
        back = self.update(progress, 42., (-50., 0., 0.))
        self.assertEqual(('return', 0), (back['phase'], back['index']))
        home = self.update(progress, 43., (-100., 0., 0.))
        self.assertEqual(('home', 'returned_home'), (home['phase'], home['reason']))
        self.assertTrue(home['replace'])
        self.assertNotIn('complete', home)

    def test_reaching_skipped_node_restores_forward_cursor(self):
        progress = SortieProgress()
        road = dict(ROAD, waypoints=ROAD['waypoints']+[[50., 150., 0]])
        for now in (0., 20.):
            progress.update(road, 2, state(now, (-70.,0.,0.)), HOME, lambda *args:False)
        result = progress.update(road, 3, state(21., (0.,0.,100.)), HOME,
                                 reached((0.,0.,100.)))
        self.assertEqual(('forward', 4), (result['phase'], result['index']))
        self.assertIsNone(result['failed_index'])

    def test_changing_goal_cannot_repeat_the_failed_c_forever(self):
        progress = SortieProgress()
        states = []
        for now in range(0, 201):
            result = progress.update(ROAD, 2, state(float(now), (-70.,0.,0.)), HOME,
                                     lambda *args:False)
            states.append((result['phase'], result['index']))
            if result.get('replace'):
                break
        self.assertEqual('home_progress_timeout', result['reason'])
        self.assertLess(now, 150)
        self.assertNotIn(('forward',2), states[21:])

    def test_real_distance_progress_resets_deadline_but_oscillation_does_not(self):
        progress = SortieProgress()
        self.update(progress, 0.)
        self.update(progress, 19., (-60.,0.,0.))
        self.assertEqual('forward', self.update(progress, 38., (-60.,0.,0.))['phase'])
        self.assertEqual('skip', self.update(progress, 39., (-70.,0.,0.))['phase'])

    def test_aim_pause_is_bounded_without_a_new_committed_round(self):
        progress = SortieProgress()
        for now in range(0, 61):
            result = self.update(progress, float(now), aiming=True, sequence=4)
            if result['phase'] == 'skip':
                break
        self.assertLessEqual(now, 41)
        self.assertEqual(20., result['aim_pause'])
        self.assertEqual('sortie_progress_timeout', result['reason'])

    def test_new_committed_round_can_renew_real_firing_pause(self):
        progress = SortieProgress()
        for now in range(0, 46):
            result = self.update(progress, float(now), aiming=True, sequence=now//10)
        self.assertEqual('forward', result['phase'])
        self.assertLessEqual(result['aim_pause'], 10.)

    def test_no_shot_sequence_is_not_evidence_of_a_protected_aim_hold(self):
        progress = SortieProgress()
        self.update(progress, 0., aiming=True)
        self.assertEqual('skip', self.update(progress, 20., aiming=True)['phase'])

    def test_task_suspension_freezes_existing_elapsed_not_recovery_state(self):
        progress = SortieProgress()
        self.update(progress, 0.)
        self.update(progress, 10.)
        progress.pause(10.)
        progress.resume(100.)
        self.assertEqual(11., self.update(progress, 101.)['elapsed'])
        self.assertEqual('skip', self.update(progress, 110.)['phase'])

    def test_overhead_or_unsupported_arrival_never_completes_road(self):
        progress = SortieProgress()
        result = progress.update(ROAD, 3, state(0., (0.,20.,100.)), HOME,
                                 reached((0.,20.,100.), supported=False))
        self.assertNotIn('complete', result)
        self.assertEqual('travelling', result['reason'])

    def test_two_players_do_not_share_recovery_cursor(self):
        first, second = SortieProgress(), SortieProgress()
        self.update(first, 0.)
        self.update(first, 20.)
        other = self.update(second, 20.)
        self.assertEqual(('skip', 'forward'), (first.phase, other['phase']))
        first.reset()
        self.assertIsNone(first.identity)
        self.assertEqual(2, second.index)


class SortieNavigationTests(unittest.TestCase):
    def navigation(self, alternative=True):
        nav = controller('SPG')
        self.addCleanup(nav.close)
        nav.route, nav.index = copy.deepcopy(ROAD), 2
        nav.sortie_routes = [nav.route]
        if alternative:
            nav.sortie_routes.append(dict(id='alternative', player_sortie=True,
                waypoints=[[-100.,0.,0],[60.,60.,0],[0.,100.,0]]))
        nav.selection = list(nav.sortie_routes)
        nav.blocked_reports = []
        nav.navigator.report_blocked_plan = lambda position, target: nav.blocked_reports.append(
            (tuple(position), tuple(target)))
        nav.artillery.mode = 'sortie'
        nav.sortie_started = True
        nav.set_context(dict(allies=[ALIVE_ALLY], supported=True))
        return nav

    def update(self, nav, now, position=(-70.,0.,0.), clear=False, hold=False):
        return nav.decide(state(now, position), lambda *args:clear, hold=hold)

    def recover_home(self, nav):
        for now, position in ((0.,(-70.,0.,0.)),(20.,(-70.,0.,0.)),(21.,(-70.,0.,0.)),
                              (41.,(-70.,0.,0.)),(42.,(-50.,0.,0.)),(43.,(-100.,0.,0.))):
            order = self.update(nav, now, position)
        return order

    def test_new_node_does_not_override_blocked_native_driving_corridor(self):
        nav = self.navigation()
        self.update(nav, 0.)
        order = self.update(nav, 20.)
        self.assertEqual('skip', order['sortie_recovery']['phase'])
        self.assertEqual(3, nav.index)
        self.assertEqual(0., order['throttle'])
        # The new node owns a fresh driver request, not the previous node's
        # recovery clock or clearance receipt. Both entry and the next
        # bounded recovery must still respect the blocked native corridor.
        self.assertIsNone(order['driving']['clearance_checks'])
        for now in (21., 22., 23.1):
            order = self.update(nav, now)
            self.assertEqual(3, nav.index)
            self.assertEqual(0., order['throttle'])
        self.assertFalse(order['driving']['clearance_checks']['front'])
        self.assertFalse(order['driving']['clearance_checks']['rear'])

    def test_bare_traffic_or_other_hold_cannot_pause_route_progress(self):
        nav = self.navigation()
        self.update(nav, 0., hold=True)
        order = self.update(nav, 20., hold=True)
        self.assertEqual('skip', order['sortie_recovery']['phase'])

    def test_returned_home_selects_another_player_road_without_reusing_failed_geometry(self):
        nav = self.navigation()
        order = self.recover_home(nav)
        self.assertEqual('another_player_sortie_route', order['sortie_recovery']['handoff'])
        self.assertEqual(['alternative'], [row['id'] for row in nav.selection])
        self.assertIn(geometry(ROAD), nav.sortie_rejections)
        self.assertIsNone(nav.route)
        self.assertIsNone(nav.mission)
        self.assertFalse(nav.retask([ROAD], 'front_pressure'))

    def test_exhausted_roads_handoff_to_real_capture_mission_not_fake_success(self):
        nav = self.navigation(alternative=False)
        order = self.recover_home(nav)
        self.assertEqual('native_capture_after_route_exhaustion', order['sortie_recovery']['handoff'])
        self.assertEqual('capture_base', nav.mission.action)
        self.assertEqual('sortie_routes_exhausted_native_capture', nav.mission.reason)
        self.assertNotEqual('completed', nav.mission.status)
        self.assertFalse(nav.mission.arrival['inside'])
        self.assertEqual(0., order['throttle'])
        self.assertIn('sortie_recovery', nav.mission_status())

    def test_defence_restores_actual_cursor_and_excludes_paused_time(self):
        nav = self.navigation()
        self.update(nav, 0.)
        self.update(nav, 10.)
        nav.retask([dict(id='player_base_defence',waypoints=[[-100.,0.]])], 'defend')
        nav.set_context(dict(allies=[ALIVE_ALLY], supported=True, now=100.))
        nav.retask(nav.sortie_routes, 'rejoin_after_defence')
        order = self.update(nav, 101.)
        self.assertEqual(2, nav.index)
        self.assertEqual(11., order['sortie_recovery']['elapsed'])

    def test_new_command_and_stop_release_failed_routes_and_private_cursor(self):
        nav = self.navigation()
        self.recover_home(nav)
        nav.start_mission('attack',dict(command_id='new-local-command'),state(44.,(-100.,0.,0.)))
        self.assertEqual({},nav.sortie_rejections)
        self.assertIsNone(nav.sortie_progress.identity)
        self.assertIsNone(nav.sortie_receipt)
        self.update(nav, 45.,(-100.,0.,0.))
        nav.cancel_mission('stop',46.)
        self.assertEqual({},nav.sortie_rejections)
        self.assertIsNone(nav.sortie_progress.identity)
        self.assertIsNone(nav.sortie_receipt)

    def test_unproved_route_entries_have_a_deadline_and_do_not_restart_forever(self):
        nav = self.navigation()
        nav.route = nav.index = None
        nav.navigator.grid.begin_plan = lambda *args, **kwargs: SimpleNamespace(
            done=True, result=None, step=lambda *args:None)
        for now in range(31):
            order = self.update(nav, float(now))
        self.assertEqual('sortie_entry_timeout', order['sortie_recovery']['reason'])
        self.assertEqual('native_capture_after_route_exhaustion', order['sortie_recovery']['handoff'])
        self.assertEqual(2,len(nav.sortie_rejections))
        self.assertEqual('capture_base',nav.mission.action)
        self.assertNotEqual('completed',nav.mission.status)

    def test_empty_sortie_catalog_hands_off_to_capture_instead_of_joining_forever(self):
        nav=self.navigation(alternative=False)
        nav.route=nav.index=None
        nav.sortie_routes=nav.selection=nav.travel_routes=nav.routes=[]
        order=self.update(nav,0.)
        self.assertEqual('no_sortie_routes',order['sortie_recovery']['reason'])
        self.assertEqual('native_capture_after_route_exhaustion',order['sortie_recovery']['handoff'])
        self.assertEqual('capture_base',nav.mission.action)
        self.assertNotEqual('completed',nav.mission.status)

    def test_empty_sortie_catalog_without_objective_reports_terminal_failure(self):
        nav=self.navigation(alternative=False)
        nav.route=nav.index=None
        nav.sortie_routes=nav.selection=nav.travel_routes=nav.routes=[]
        nav.enemy_area=None
        order=self.update(nav,0.)
        self.assertEqual('no_sortie_routes',order['sortie_recovery']['reason'])
        self.assertEqual('sortie_failed_no_capture_objective',order['sortie_recovery']['handoff'])
        self.assertEqual('failed',nav.mission_status()['status'])
        self.update(nav,500.)
        self.assertEqual('failed',nav.mission_status()['status'])

    def test_strategy_plain_road_maps_to_owned_sortie_and_keeps_progress_deadline(self):
        nav=controller('SPG')
        self.addCleanup(nav.close)
        nav.artillery.mode='sortie'
        nav.sortie_started=True
        nav.set_context(dict(allies=[ALIVE_ALLY],supported=True))
        nav.navigator.report_blocked_plan=lambda *args:None
        plain=nav.travel_routes[0]
        self.assertTrue(nav.retask([plain],'route'))
        self.assertEqual(['player_spg_borrowed_main'],[row['id'] for row in nav.selection])
        self.assertTrue(nav.selection[0]['player_sortie'])
        self.assertNotIn('player_sortie',plain)
        self.update(nav,0.)
        order=self.update(nav,20.)
        self.assertEqual('skip',order['sortie_recovery']['phase'])
        self.assertEqual('sortie_progress_timeout',order['sortie_recovery']['reason'])

    def test_unknown_plain_road_retask_cannot_discard_existing_sortie_cursor(self):
        nav=self.navigation(alternative=False)
        self.update(nav,0.)
        self.update(nav,10.)
        self.assertFalse(nav.retask([nav.travel_routes[0]],'route'))
        self.assertEqual('audit-sortie',nav.route['id'])
        order=self.update(nav,20.)
        self.assertEqual('skip',order['sortie_recovery']['phase'])

    def test_repeated_strategy_lane_suggestions_do_not_restart_the_same_sortie(self):
        nav=controller('SPG')
        self.addCleanup(nav.close)
        nav.artillery.mode='sortie'
        nav.sortie_started=True
        nav.navigator.report_blocked_plan=lambda *args:None
        nav.set_context(dict(allies=[ALIVE_ALLY],supported=True))
        self.assertTrue(nav.retask([nav.travel_routes[0]],'route'))
        strategy=Strategy()
        contacts=[dict(id=9,position=(0.,0.,10.),health=100,max_health=100,alive=True)]
        repeated=[]
        retired_at=None
        for now in range(182):
            sample=state(float(now),(-70.,0.,0.))
            suggestion=strategy.decide(float(now),nav.routes,nav.route,contacts,[],{},
                nav.home,state=sample,mission=nav.mission_status())
            if suggestion is not None:
                changed=nav.retask(suggestion,strategy.mode)
                repeated.append((now,changed,nav.receipt['status']))
            nav.decide(sample,lambda *args:False)
            if retired_at is None and nav.sortie_rejections:
                retired_at=now
        self.assertTrue(any(row[2]=='sortie_route_unchanged' for row in repeated))
        self.assertIsNotNone(retired_at)
        self.assertLess(retired_at,100)
        self.assertTrue(nav.sortie_rejections)

    def test_natural_capture_timeouts_never_revive_exhausted_roads_over_six_hundred_seconds(self):
        nav=controller('SPG')
        self.addCleanup(nav.close)
        nav.artillery.mode='sortie'
        nav.navigator.report_blocked_plan=lambda *args:None
        nav.set_context(dict(allies=[ALIVE_ALLY],supported=True))
        captures=set()
        backoff=[]
        for now in range(601):
            order=nav.decide(state(float(now),(-70.,0.,0.)),lambda *args:False)
            if nav.route is not None:
                self.assertNotIn(geometry(nav.route),nav.sortie_rejections,now)
            if nav.mission is not None:
                self.assertEqual('capture_base',nav.mission.action)
                self.assertNotEqual('completed',nav.mission.status)
                captures.add(nav.mission.identity)
            recovery=order.get('sortie_recovery') or {}
            if recovery.get('handoff')=='capture_retry_backoff':
                backoff.append(now)
                self.assertGreater(recovery['retry_at'],float(now))
        self.assertEqual(2,len(nav.sortie_rejections))
        self.assertGreater(len(captures),2)
        self.assertTrue(backoff)
        self.assertGreater(nav.capture_failures,1)

    def test_switching_roads_keeps_global_failures_until_native_capture_handoff(self):
        nav = self.navigation()
        self.recover_home(nav)
        for now in (44.,64.,65.,85.,86.):
            order = self.update(nav,now,(-100.,0.,0.))
        self.assertEqual('native_capture_after_route_exhaustion', order['sortie_recovery']['handoff'])
        self.assertEqual({'audit-sortie','alternative'},set(order['sortie_recovery']['failed_routes']))
        self.assertEqual(2,len(nav.sortie_rejections))

    def test_no_objective_after_recovery_is_a_terminal_failure_not_a_live_cursor(self):
        nav = self.navigation(alternative=False)
        nav.enemy_area=None
        order=self.recover_home(nav)
        self.assertEqual('sortie_failed_no_capture_objective',order['sortie_recovery']['handoff'])
        self.assertEqual('failed',nav.mission_status()['status'])
        self.assertIsNone(nav.sortie_progress.identity)
        self.update(nav,100.)
        self.assertIsNone(nav.sortie_progress.identity)
        self.assertEqual('failed',nav.mission_status()['status'])

    def test_arrived_last_node_without_objective_cannot_repeat_completion_forever(self):
        nav=self.navigation(alternative=False)
        nav.enemy_area=None
        nav.index=3
        order=self.update(nav,0.,(0.,0.,100.))
        self.assertEqual('sortie_failed_no_capture_objective',order['sortie_recovery']['handoff'])
        self.assertEqual('failed',nav.mission_status()['status'])
        self.update(nav,100.,(0.,0.,100.))
        self.assertIsNone(nav.sortie_progress.identity)

    def test_indefinite_authored_parking_is_not_a_twenty_second_stall(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'][2]=[0.,0.,1,0.,[[12.,0.,-1.]]]
        for now in (0.,20.,100.,500.):
            order=self.update(nav,now,(12.,0.,0.))
            self.assertEqual('authored_parking',order['sortie_recovery']['phase'])
            self.assertEqual('parking_hold',order['combat_mode'])
            self.assertTrue(order['brake'])
            self.assertEqual(2,nav.index)
        self.assertEqual({},nav.sortie_rejections)

    def test_oscillating_parking_approach_cannot_pause_sortie_for_five_hundred_seconds(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'][2]=[0.,0.,1,0.,[[12.,0.,30.]]]
        parking_ticks=[]
        for now in range(501):
            position=(-12. if now % 2 == 0 else -10.,0.,0.)
            order=self.update(nav,float(now),position)
            if (order.get('sortie_recovery') or {}).get('phase')=='authored_parking':
                parking_ticks.append(now)
        record=nav.parking.records[('audit-sortie',2)]
        self.assertTrue(record['complete'])
        self.assertIsNone(record['arrived_at'])
        self.assertEqual('blocked_approach_timeout',record['reason'])
        self.assertLess(max(parking_ticks),32)
        self.assertLess(record['progress_at'],2.)

    def test_small_net_parking_progress_has_a_total_approach_deadline(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'][2]=[0.,0.,1,0.,[[12.,0.,30.]]]
        for now in range(121):
            self.update(nav,float(now),(-190.+.6*now,0.,0.))
        record=nav.parking.records[('audit-sortie',2)]
        self.assertTrue(record['complete'])
        self.assertIsNone(record['arrived_at'])
        self.assertEqual('parking_approach_deadline',record['reason'])

    def test_completed_authored_wait_advances_even_when_place_is_off_road_node(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'][2]=[0.,0.,1,0.,[[12.,0.,1.]]]
        self.update(nav,0.,(12.,0.,0.))
        order=self.update(nav,2.,(12.,0.,0.))
        self.assertEqual(3,nav.index)
        self.assertEqual('forward',order['sortie_recovery']['phase'])

    def test_nearby_node_burst_stops_before_a_future_authored_wait(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'].insert(3,[2.,0.,1,0.,[[2.,0.,-1.]]])
        order=self.update(nav,0.,(0.,0.,0.))
        self.assertEqual(3,nav.index)
        self.assertEqual('authored_node_pending',order['sortie_recovery']['reason'])
        self.assertTrue(order['brake'])
        for now in (1.,20.,100.):
            order=self.update(nav,now,(0.,0.,0.))
            self.assertEqual(3,nav.index)
            self.assertEqual('authored_parking',order['sortie_recovery']['phase'])
            self.assertEqual('parking_hold',order['combat_mode'])
            self.assertTrue(order['brake'])
        self.assertIsNone(nav.mission)
        self.assertEqual({},nav.sortie_rejections)

    def test_completed_wait_does_not_complete_a_distinct_wait_at_same_coordinates(self):
        nav=self.navigation(alternative=False)
        nav.route['waypoints'][2]=[0.,0.,1,0.,[[12.,0.,1.]]]
        nav.route['waypoints'].insert(3,[0.,0.,1,0.,[[12.,0.,-1.]]])
        self.update(nav,0.,(12.,0.,0.))
        order=self.update(nav,2.,(12.,0.,0.))
        self.assertEqual(3,nav.index)
        self.assertEqual('authored_node_pending',order['sortie_recovery']['reason'])
        for now in (3.,100.):
            order=self.update(nav,now,(12.,0.,0.))
            self.assertEqual(3,nav.index)
            self.assertEqual('authored_parking',order['sortie_recovery']['phase'])
            self.assertEqual('parking_hold',order['combat_mode'])
            self.assertTrue(order['brake'])
        self.assertEqual({},nav.sortie_rejections)


if __name__ == '__main__':
    unittest.main()
