"""Stop-and-fire ownership through the real foreground control/navigation loop.

The 2026-11-06 13:37 report contains a healthy T-34 moving at 185--195 m
while its selected target was already shootable. These tests keep the real
PlayerControl, CombatPolicy, PlayerNavigation, Driver and final sender path.
Only native aiming observations, ground/path queries and shot commits are
controlled seams; this is not a Windows physics or native-hit acceptance test.
"""
import math
import types
import unittest
from unittest import mock

from test_player_navigation_migration import controller as navigation_controller
from test_player_navigation_migration import state


class AimingBoundary(object):
    """Replay direct-engagement outputs, including its one-frame unknown gap."""
    def __init__(self, target):
        self.target = target.id
        self.kind = 'clear'
        self.checking = False
        self.scan = None
        self.stage = (0, .97)
        self.sample = 6
        self.search_since = None
        self.fallback = self.retreat = self.seek = self.locked_wait = False
        self.pivot_search = self.laying_until = self.next_shell = None
        self.confirmed = self.last_solution = None
        self.shot_admitted = mock.Mock()

    def update(self, control, candidates, now):
        target = next((item for item in candidates if item.id == self.target), None)
        self.checking = self.kind in ('checking', 'stale')
        self.scan = dict(identity=(self.target, 0, 'full'), pending=[1, 2]) if self.checking else None
        self.laying_until = now + 1. if self.kind == 'laying' else None
        if target is None or self.kind in ('unknown', 'checking'):
            self.sample = self.confirmed = None
            return None, None, False
        if self.kind == 'stale':
            return target, self.last_solution, False
        self.sample = 6
        self.confirmed = (target.id, self.sample, control.owner._gun_state.shot_index)
        self.last_solution = dict(point=(target.position[0], 1., target.position[2]),
            source_point=target.position, reachable=True, geometry_clear=True,
            # A verified proposed line remains clear while the physical
            # barrel lays; DirectEngagement separately returns fire_clear=False.
            clear=True, source_verified=True, laying=self.kind == 'laying',
            sample=self.sample, key=(target.id, self.sample), created=now)
        return target, self.last_solution, self.kind == 'clear'


class StationaryScenario(object):
    def __init__(self, distance=190., bearing=0.):
        # Reuse the established unavailable-native fixture, then replace its
        # mocked navigation with the actual foreground navigation controller.
        from test_player_control import PlayerRegressionTests
        self.control, self.target = PlayerRegressionTests().aim_controller()
        control, owner = self.control, self.control.owner
        self.entity = owner._server_entity(1)
        self.entity.typeDescriptor.type = types.SimpleNamespace(tags=('mediumTank',))
        self.entity.typeDescriptor.gun = types.SimpleNamespace()
        self.target.position = (distance * math.sin(bearing), 0., distance * math.cos(bearing))
        self.records = {self.target.id: self.target}
        self.neighbours = []
        self.now = 0.
        self.position = (0., 0., 0.)
        owner._clock = lambda: self.now
        owner.local_pose = lambda: (self.position, 0.)
        owner._mutable_shot_ray = lambda: ((self.position[0], 1., self.position[2]),
                                           (math.sin(bearing), 0., math.cos(bearing)))
        owner._local_turn_speed = 0.
        self.gun = owner._gun_state
        self.gun.can_fire = lambda unused: bool(self.gun.ammo[0] and self.gun.clip > 0
                                               and self.gun.reload_time <= 0.)
        control._contacts = lambda unused: ([], self.neighbours, self.records)
        control.firing_lane = lambda unused: True
        control.lane_from = mock.Mock(return_value=False)
        control.navigation = navigation_controller('mediumTank')
        control.navigation.route = control.navigation.routes[0]
        control.navigation.index = 1
        control.emit_result = mock.Mock(return_value=True)
        control.publish_status = mock.Mock()
        control.aiming.defer_ordered_point = mock.Mock()
        control.direct_engagement = self.aim = AimingBoundary(self.target)
        control.weapon.fired, control.weapon.committed = False, 0
        self.commit = False
        self.admission_reason = None
        self.projectile = 0

        def native_trigger():
            if self.admission_reason is not None:
                control.fire_admission.receipt = dict(status='pending', reason=self.admission_reason)
                return False
            control.fire_admission.receipt = dict(status='accepted', reason='test_native_commit')
            if self.commit:
                self.projectile += 1
                control.shot_committed(dict(projectile_id='stationary-%s' % self.projectile,
                                            shell_index=0), {})
                self.gun.ammo[0] -= 1
                self.gun.clip, self.gun.reload_time = 0, 3.4
            return True
        control.weapon.trigger = mock.Mock(side_effect=native_trigger)

    def step(self, now, kind='clear'):
        self.now, self.aim.kind = now, kind
        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned',
                        return_value=True):
            self.control.update(.1, now)
        return self.control.last_order

    def cover_candidate(self):
        candidate = dict(target=self.target.id, goal=(0., 0., -6.), peek=(0., 0., 0.))
        self.control.navigation._cover_candidate = mock.Mock(return_value=candidate)
        self.control.navigation.cover_search.current_exposure = lambda *args: 0.
        self.control.navigation.cover_search.peek_clear = lambda *args: True
        return candidate


class StationaryEngagementTests(unittest.TestCase):
    def assert_parked(self, scenario):
        control = scenario.control
        sender = control.owner._sender
        self.assertEqual((0., 0., True), (sender.forward, sender.turn, sender.handbrake),
                         control.last_order)
        self.assertTrue(control.last_order['holding'])
        self.assertEqual('engage', control.last_order['combat_mode'])
        self.assertTrue(control.last_order.get('traffic_hold_protected'))

    def assert_moving(self, scenario):
        sender = scenario.control.owner._sender
        self.assertTrue(sender.forward or sender.turn, scenario.control.last_order)
        self.assertFalse(sender.handbrake, scenario.control.last_order)

    def test_report_shootable_medium_range_stops_at_final_sender(self):
        for distance, speed in ((185., 0.), (189.256, -3.07), (194.574, 3.64), (195., 0.)):
            with self.subTest(distance=distance, speed=speed):
                scenario = StationaryScenario(distance)
                scenario.control.owner._local_speed = speed
                scenario.step(1.)
                self.assert_parked(scenario)
                self.assertEqual(scenario.target.id, scenario.control.target_engine)
                self.assertAlmostEqual(distance, scenario.control.navigation.combat.receipt['distance'])

    def test_usable_he_fallback_keeps_its_search_clock_without_restarting_travel(self):
        scenario = StationaryScenario()
        # DirectEngagement intentionally retains the penetration-search clock
        # during nominal HE fallback. A usable fallback still returns a real
        # current firing proof; movement must not mistake that clock for loss.
        scenario.aim.seek = scenario.aim.fallback = True
        scenario.aim.search_since = -10.
        scenario.aim.stage = (0, None)
        scenario.step(1.)
        self.assert_parked(scenario)
        self.assertEqual((scenario.target, 5.), scenario.control.engagement_hold)
        for now, phase in ((1.2, 'unknown'), (2.7, 'checking')):
            scenario.step(now, phase)
            self.assert_parked(scenario)
            self.assertEqual((scenario.target, 5.), scenario.control.engagement_hold)
        scenario.control.weapon.forward.assert_not_called()
        scenario.step(5.1, 'checking')
        self.assertEqual('advance_contact', scenario.control.last_order['combat_mode'])
        self.assertIsNone(scenario.control.engagement_hold)

    def test_aligned_turret_does_not_start_or_resume_optional_hull_rotation(self):
        for previous_pivot in (False, True):
            with self.subTest(previous_pivot=previous_pivot):
                scenario = StationaryScenario(distance=140., bearing=.5)
                if previous_pivot:
                    scenario.control.confirmed_facing.attempt = dict(
                        key=(scenario.target.id, 6, 0), phase='turning', start=.8,
                        progress=.8, error=.5, direction=1., outcome=None, pending_since=None)
                scenario.step(1.)
                self.assert_parked(scenario)
                self.assertIsNone(scenario.control.confirmed_facing.attempt)

    def test_single_round_reload_keeps_firing_position_beyond_recovery_clock(self):
        scenario = StationaryScenario()
        scenario.commit = True
        scenario.step(1.)
        self.assertEqual(1, scenario.control.automatic_commits)
        self.assertEqual(1, scenario.control.weapon.committed)
        self.assert_parked(scenario)
        # A long single-round reload is not an empty-magazine retreat and
        # must not consume the eight-second ready-without-shot lease.
        for now in (1.2, 2., 4., 6., 9., 11.):
            scenario.gun.reload_time = 12. - now
            scenario.step(now)
            self.assert_parked(scenario)
            self.assertIsNone(scenario.control.navigation.combat.recovery)
        self.assertEqual(1, scenario.control.automatic_commits)

    def test_committed_shot_unknown_first_frame_and_scan_keep_same_bounded_hold(self):
        scenario = StationaryScenario()
        scenario.commit = True
        scenario.step(1.)
        self.assertEqual(1, scenario.control.automatic_commits)
        original_lease = scenario.control.engagement_hold
        self.assertIsNotNone(original_lease)
        # Report 13:23:00.648: sample=None, checking=False, scan=None,
        # native_source_unverified just after a committed shot. The following
        # frames set checking=True; neither observation proves a blocked lane.
        for now, kind in ((1.2, 'unknown'), (1.4, 'checking'), (2.6, 'checking')):
            scenario.step(now, kind)
            self.assert_parked(scenario)
            self.assertEqual(original_lease, scenario.control.engagement_hold)
            self.assertIsNone(scenario.control.target_engine)
            self.assertEqual(scenario.target.id, scenario.aim.target)
        scenario.step(3., 'laying')
        self.assert_parked(scenario)
        self.assertGreater(scenario.control.engagement_hold[1], original_lease[1])
        scenario.control.weapon.forward.assert_not_called()

    def test_unknown_proof_expires_without_returning_to_unrelated_route(self):
        scenario = StationaryScenario()
        scenario.step(1.)
        lease = scenario.control.engagement_hold
        self.assertIsNotNone(lease)
        scenario.step(4.8, 'checking')
        self.assert_parked(scenario)
        self.assertEqual(lease, scenario.control.engagement_hold)
        scenario.step(5.2, 'checking')
        self.assertIsNone(scenario.control.engagement_hold)
        self.assertEqual('advance_contact', scenario.control.last_order['combat_mode'])
        self.assertEqual(scenario.target.position, scenario.control.navigation.navigator.path_calls[-1][2])
        self.assert_moving(scenario)

    def test_stale_pending_solution_cannot_renew_proven_hold(self):
        for locked_wait in (False, True):
            with self.subTest(locked_wait=locked_wait):
                scenario = StationaryScenario()
                scenario.step(1.)
                lease = scenario.control.engagement_hold
                self.assertIsNotNone(lease)
                scenario.aim.locked_wait = locked_wait
                for now in (1.2, 3., 4.8):
                    scenario.step(now, 'stale')
                    self.assert_parked(scenario)
                    self.assertEqual(lease, scenario.control.engagement_hold)
                # The previous order and old geometry_clear solution cannot
                # renew each other's hold indefinitely after the proof ages.
                scenario.step(5.2, 'stale')
                self.assertIsNone(scenario.control.engagement_hold)
                self.assertEqual('advance_contact', scenario.control.last_order['combat_mode'])
                self.assert_moving(scenario)

    def test_visible_enemy_without_any_shot_proof_does_not_create_hold(self):
        scenario = StationaryScenario()
        scenario.step(1., 'checking')
        self.assertIsNone(scenario.control.engagement_hold)
        self.assert_moving(scenario)
        self.assertEqual('advance_contact', scenario.control.last_order['combat_mode'])

    def test_cached_geometry_without_current_source_proof_cannot_establish_hold(self):
        scenario = StationaryScenario()
        scenario.control.direct_engagement = None
        # Aiming.update can return an older geometric path with clear=False
        # while its native budget/source proof is pending. That is distinct
        # from a verified laying solution and cannot establish a new hold.
        scenario.control.aiming.update = lambda item, now, lane, **kwargs: dict(
            point=(item.position[0], 1., item.position[2]), reachable=True,
            geometry_clear=True, clear=False, reason='budget_pending')
        scenario.step(1.)
        self.assertIsNone(scenario.control.engagement_hold)
        self.assertFalse(scenario.control.navigation.context.get('shot_lane_proven', False))
        self.assertFalse(scenario.control.last_order.get('holding'))
        self.assert_moving(scenario)

    def test_spg_firing_position_refusal_keeps_fallback_or_sortie_owner(self):
        for mode in ('fallback', 'sortie'):
            with self.subTest(mode=mode):
                scenario = StationaryScenario()
                scenario.entity.typeDescriptor.type.tags = ('SPG',)
                scenario.control.direct_engagement = None
                navigation = scenario.control.navigation = navigation_controller('SPG')
                navigation.artillery.mode, navigation.artillery.retry_at = mode, 10.
                navigation.route, navigation.index = navigation.travel_routes[0], 1
                scenario.control.aiming.update = lambda item, now, lane, **kwargs: dict(
                    point=(item.position[0], 1., item.position[2]), reachable=False,
                    geometry_clear=False, clear=False, reason='world_blocked')
                with mock.patch.object(navigation, 'firing_position',
                                       wraps=navigation.firing_position) as reposition:
                    scenario.step(1.)
                reposition.assert_called_once()
                self.assertIs(scenario.target, reposition.call_args.args[1])
                self.assertEqual(mode, navigation.artillery.mode)
                self.assertNotEqual('advance_contact', scenario.control.last_order['combat_mode'])
                self.assertFalse(navigation.context.get('shot_lane_proven', False))
                self.assertTrue(navigation.navigator.path_calls)
                self.assertNotEqual(scenario.target.position, navigation.navigator.path_calls[-1][2])

    def test_dead_target_and_same_id_replacement_release_old_object_lease(self):
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                scenario = StationaryScenario()
                scenario.step(1.)
                self.assert_parked(scenario)
                if replacement:
                    scenario.records[scenario.target.id] = types.SimpleNamespace(
                        id=scenario.target.id, position=(0., 0., 180.),
                        typeDescriptor=scenario.target.typeDescriptor)
                else:
                    scenario.records.clear()
                scenario.step(1.2, 'unknown')
                self.assertIsNone(scenario.control.engagement_hold)
                self.assert_moving(scenario)
                self.assertFalse(scenario.control.last_order.get('holding'))

    def test_normal_cover_phases_and_existing_flank_cannot_steal_usable_lane(self):
        for phase in (None, 'approach', 'hold', 'peek', 'return'):
            with self.subTest(phase=phase):
                scenario = StationaryScenario()
                candidate = scenario.cover_candidate()
                navigation = scenario.control.navigation
                if phase is not None:
                    navigation.cover_move = dict(candidate, phase=phase, progress_at=.5,
                        best_distance=6., held_since=.5, peek_until=3., fire_seq=0,
                        reason='combat_cover')
                scenario.control.combat_tactics.flank = dict(target=scenario.target.id,
                    target_point=scenario.target.position, goal=(30., 0., 100.),
                    progress_position=(0., 0., 0.), progress_at=.5, at=.5, support=[9])
                scenario.step(1.)
                self.assert_parked(scenario)
                self.assertIsNone(navigation.cover_move)
                self.assertIsNone(scenario.control.combat_tactics.flank)
                navigation._cover_candidate.assert_not_called()

    def test_withdrawal_entry_itself_rejects_ordinary_stationary_fire_hold(self):
        scenario = StationaryScenario()
        scenario.cover_candidate()
        scenario.step(1.)
        self.assert_parked(scenario)
        result = scenario.control.navigation.withdrawal(state(1.2), scenario.target,
            scenario.entity, scenario.gun, lambda *args: True, lambda *args: True)
        self.assertIsNone(result)
        self.assertIsNone(scenario.control.navigation.cover_move)

    def test_confirmed_barrel_blockage_moves_toward_same_enemy_with_or_without_side_lane(self):
        for side_lane in (False, True):
            with self.subTest(side_lane=side_lane):
                scenario = StationaryScenario()
                scenario.admission_reason = 'auto_world_blocked'
                scenario.step(1.)
                self.assertEqual(scenario.target.id, scenario.control.blocked_fire_target)
                scenario.control.lane_from.return_value = side_lane
                scenario.step(1.2)
                mode = 'firing_position' if side_lane else 'advance_contact'
                self.assertEqual(mode, scenario.control.last_order['combat_mode'])
                self.assertIsNone(scenario.control.engagement_hold)
                self.assert_moving(scenario)
                self.assertEqual(scenario.target.id, scenario.aim.target)
                for call in scenario.control.lane_from.call_args_list:
                    self.assertIs(scenario.target, call.args[0])
                if not side_lane:
                    self.assertEqual(scenario.target.position,
                                     scenario.control.navigation.navigator.path_calls[-1][2])

    def test_explicit_point_and_capture_missions_keep_movement_ownership(self):
        for action, args in (('hold_position', dict(position=(0., 0., 30.))),
                             ('capture_base', {})):
            with self.subTest(action=action):
                scenario = StationaryScenario()
                scenario.control.navigation.start_mission(action, args, state())
                scenario.step(1.)
                self.assert_moving(scenario)
                self.assertFalse(scenario.control.last_order.get('holding'))
                self.assertEqual(action, scenario.control.navigation.mission_status()['action'])

    def test_automatic_capture_handoff_waits_for_shootable_enemy_to_be_released(self):
        # The route endpoint is z=70; the enemy capture circle is centred on
        # z=100. Neither automatic opportunity may replace ordinary firing.
        for position_z in (70., 100.):
            with self.subTest(position_z=position_z):
                scenario = StationaryScenario()
                scenario.position = (0., 0., position_z)
                scenario.target.position = (0., 0., position_z + 190.)
                scenario.step(1.)
                self.assert_parked(scenario)
                self.assertEqual('idle', scenario.control.navigation.mission_status()['status'])
                scenario.step(1.2, 'checking')
                self.assert_parked(scenario)
                self.assertEqual('idle', scenario.control.navigation.mission_status()['status'])
                scenario.records.clear()
                scenario.step(1.4, 'unknown')
                mission = scenario.control.navigation.mission_status()
                self.assertIsNotNone(mission)
                self.assertEqual('capture_base', mission['action'])
                self.assertIsNone(scenario.control.engagement_hold)
                if position_z == 70.:
                    self.assert_moving(scenario)
                else:
                    self.assertTrue(scenario.control.owner._sender.handbrake)

    def test_empty_inventory_releases_proof_for_capture(self):
        scenario = StationaryScenario()
        scenario.step(1.)
        self.assert_parked(scenario)
        scenario.gun.ammo[0] = 0
        scenario.step(1.2)
        self.assertIsNone(scenario.control.engagement_hold)
        self.assert_moving(scenario)
        self.assertEqual('capture_base', scenario.control.navigation.mission_status()['action'])

    def test_critical_health_and_real_magazine_or_no_he_retreat_still_move(self):
        for reason in ('critical', 'magazine_reload', 'no_he'):
            with self.subTest(reason=reason):
                scenario = StationaryScenario()
                scenario.cover_candidate()
                scenario.step(1.)
                self.assert_parked(scenario)
                if reason == 'critical':
                    scenario.entity.health = 200
                elif reason == 'magazine_reload':
                    scenario.gun.clip_size, scenario.gun.clip, scenario.gun.reload_time = 3, 0, 30.
                else:
                    scenario.aim.retreat = True
                scenario.step(1.2, 'checking' if reason == 'magazine_reload' else 'clear')
                self.assert_moving(scenario)
                self.assertLess(scenario.control.owner._sender.forward, 0.)
                self.assertIsNone(scenario.control.engagement_hold)
                self.assertEqual('withdraw' if reason == 'critical' else 'ammo_retreat',
                                 scenario.control.last_order['combat_mode'])


if __name__ == '__main__':
    unittest.main()
