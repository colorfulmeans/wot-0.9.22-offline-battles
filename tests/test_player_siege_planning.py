"""Future-mode geometry and native point/contact checks, not Windows proof.

The prospective planner cannot enter the actual attack proof table.  Native
world/component observations below reuse the foreground fire fixture; body
sweep receipts are explicitly controlled only in the tests of that boundary.
"""
import copy
import math
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'),
               str(Path(__file__).resolve().parent)]

from player_native_fixtures import descriptor
from gui.mods.offline_lan_0922 import ballistics, shot_geometry, siege_mechanics
from gui.mods.offline_lan_0922.player_control.attack_policy import _mechanical
from gui.mods.offline_lan_0922.player_control.siege_planning import (
    SiegePrecheck, PRECHECK_CANDIDATES, PRECHECK_WORLD_CHORDS,
    native_descriptor_pair, project_solution, projected_body)


def pitch_limits(gun, minimum, maximum):
    gun.pitchLimits = dict(absolute=(minimum, maximum),
        minPitch=((0., minimum), (2. * math.pi, minimum)),
        maxPitch=((0., maximum), (2. * math.pi, maximum)))


def hydraulic(descriptor, minimum=-.19, maximum=.19, center=-1.):
    descriptor.type.hullAimingParams = dict(pitch=dict(isAvailable=True,
        isEnabled=True, wheelsCorrectionAngles=dict(pitchMin=minimum, pitchMax=maximum),
        wheelsCorrectionSpeed=.3, wheelCorrectionCenterZ=center))


def paired(gun_minimum=-.07, gun_maximum=.035, limits=(0., 0.), correction=True):
    travel = descriptor(0., 0., limits)
    enabled = descriptor(gun_minimum, gun_maximum, limits)
    travel.hasSiegeMode = True
    travel.defaultVehicleDescr, travel.siegeVehicleDescr = travel, enabled
    if correction:
        hydraulic(enabled)
    return travel, enabled


class FutureSiegeProjectionTests(unittest.TestCase):
    shot = dict(speed=1000., gravity=9.81, maxDistance=720.)

    def project(self, travel, point=(0., 20., 100.), body=(0., 0., 0.), velocity=(0., 0., 0.)):
        return project_solution(travel, (0., 0., 0.), body, self.shot, point, velocity)

    def test_travel_zero_pitch_does_not_reject_future_hydraulic_point(self):
        travel, enabled = paired()
        result = self.project(travel)
        self.assertEqual('ready', result['status'], result)
        self.assertIs(enabled, result['descriptor'])
        self.assertEqual('mechanical_limited', _mechanical(
            travel, result['direction'], (0., 0., 0.))['status'])
        self.assertEqual('reachable', _mechanical(
            enabled, result['direction'], result['body'])['status'])
        self.assertTrue(result['needs_hydraulic'])
        self.assertFalse(result['reachable'])
        self.assertFalse(result['source_verified'])
        self.assertTrue(result['future_reachable'])

    def test_plain_gun_travel_in_future_mode_needs_no_fabricated_hydraulics(self):
        travel, unused = paired(-.5, .5, correction=False)
        result = self.project(travel)
        self.assertEqual('ready', result['status'], result)
        self.assertFalse(result['needs_hydraulic'])
        self.assertEqual(0., result['hydraulic_pitch'])

    def test_missing_hydraulic_parameters_remain_unknown_when_correction_is_needed(self):
        travel, unused = paired(0., 0., correction=False)
        result = self.project(travel)
        self.assertEqual(('unknown', 'hydraulic_parameters_unavailable'),
                         (result['status'], result['reason']))

    def test_outside_combined_envelope_is_not_approved(self):
        travel, unused = paired()
        result = self.project(travel, point=(0., 50., 100.))
        self.assertEqual(('unreachable', 'siege_pitch_limit'),
                         (result['status'], result['reason']))

    def test_enabled_descriptor_mount_and_hydraulic_pivot_move_actual_origin(self):
        travel, enabled = paired()
        enabled.turret.gunPosition = (.3, .5, 1.)
        result = self.project(travel)
        self.assertEqual('ready', result['status'], result)
        origin, direction = shot_geometry.shot_origin_and_direction(enabled,
            result['position'], *result['body'], result['local_yaw'], result['local_pitch'])
        for actual, expected in zip(result['origin'], origin):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertNotEqual((0., 2., 0.), result['origin'])
        self.assertNotEqual((0., 0., 0.), result['position'])
        for actual, expected in zip(result['direction'], direction):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_native_gun_pivot_not_barrel_tip_is_the_launch_origin(self):
        travel, enabled = paired(-.5, .5, correction=False)
        enabled.turret.gunPosition = (.2, .8, 1.2)
        first = shot_geometry.shot_origin_and_direction(
            enabled, (1., 2., 3.), .1, .2, .3, .05, -.4)
        second = shot_geometry.shot_origin_and_direction(
            enabled, (1., 2., 3.), .1, .2, .3, .05, .3)
        self.assertEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])

    def test_roll_composition_matches_exact_nested_native_transform(self):
        position, body, correction, center = (7., 5., -9.), (.4, .12, -.25), -.15, -1.5
        transformed, composed = projected_body(position, body, correction, center)
        from gui.mods.offline_lan_0922.player_control.copied import hull_aiming
        offset = hull_aiming.correction_translation(correction, center)
        for value in ((1., 2., 3.), (0., 0., 0.), (0., 0., 10.)):
            local = shot_geometry.transform_vehicle_vector(value, 0., correction, 0.)
            local = tuple(local[index] + offset[index] for index in range(3))
            expected = shot_geometry.transform_vehicle_point(local, position, *body)
            actual = shot_geometry.transform_vehicle_point(value, transformed, *composed)
            for first, second in zip(actual, expected):
                self.assertAlmostEqual(first, second, places=10)
        self.assertNotAlmostEqual(body[1] + correction, composed[1], places=5)

    def test_pivot_and_target_motion_are_solved_without_modifying_descriptors(self):
        travel, enabled = paired()
        old_limits = copy.deepcopy(enabled.gun.pitchLimits)
        result = self.project(travel, point=(30., 20., 100.), body=(0., .05, .2), velocity=(1., 0., 0.))
        self.assertEqual('ready', result['status'], result)
        self.assertTrue(result['needs_hull'])
        self.assertNotEqual(0., result['hull_yaw'])
        self.assertGreater(result['point'][0], 30.)
        self.assertEqual(old_limits, enabled.gun.pitchLimits)
        self.assertIs(travel, travel.defaultVehicleDescr)
        final = ballistics.ballistic_position(result['origin'], result['yaw'],
            result['pitch'], self.shot['speed'], self.shot['gravity'], result['flight_time'])
        for first, second in zip(final, result['point']):
            self.assertAlmostEqual(first, second, places=6)

    def test_full_turret_siege_projection_does_not_invent_a_clip_restriction(self):
        travel, enabled = paired(-.5, .5, limits=None, correction=False)
        enabled.gun.clip = (4, .5)
        result = self.project(travel, point=(30., 2., 100.))
        self.assertEqual('ready', result['status'], result)
        self.assertFalse(result['needs_hull'])
        self.assertGreater(result['local_yaw'], .2)

    def test_invalid_shell_and_missing_pair_do_not_become_usable(self):
        travel, unused = paired()
        for shot in (dict(self.shot, speed=0.), dict(self.shot, maxDistance=float('nan'))):
            result = project_solution(travel, (0., 0., 0.), (0., 0., 0.),
                shot, (0., 20., 100.), (0., 0., 0.))
            self.assertEqual('unknown', result['status'])
        travel.siegeVehicleDescr = None
        self.assertEqual('unknown', self.project(travel)['status'])

    def test_unrelated_old_composite_cannot_prove_the_current_gun(self):
        travel, enabled = paired()
        runtime = types.SimpleNamespace(owner=types.SimpleNamespace(_local_descriptor=travel),
                                        engine=types.SimpleNamespace(_descriptor_pairs={}), actor_id=1)
        current = descriptor()
        composite, pair = native_descriptor_pair(runtime, current)
        self.assertIs(current, composite)
        self.assertIsNone(pair[1])
        composite, pair = native_descriptor_pair(runtime, enabled)
        self.assertIs(travel, composite)
        self.assertIs(enabled, pair[1])


class NativeSiegePrecheckTests(unittest.TestCase):
    def scene(self, bearing=0., hydraulic_needed=False):
        import test_player_limited_traverse as fixture
        scene = fixture.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(limits=(0., 0.), bearing=bearing, rate=0.)
        travel = scene.entity.typeDescriptor
        enabled = copy.deepcopy(travel)
        # Rotation tests below explicitly exercise the original centre-arc
        # probe; a track-centred turn has a different endpoint and proof.
        enabled.chassis.rotationIsAroundCenter = True
        travel.hasSiegeMode = True
        travel.defaultVehicleDescr, travel.siegeVehicleDescr = travel, enabled
        enabled.hasSiegeMode = False
        scene.battle._local_descriptor = travel
        scene.entity.siegeState = siege_mechanics.DISABLED
        pitch_limits(travel.gun, 0., 0.)
        pitch_limits(enabled.gun, -.035 if hydraulic_needed else -.8,
                     .035 if hydraulic_needed else .8)
        if hydraulic_needed:
            hydraulic(enabled, minimum=-.3, maximum=.3)
            scene.pose(scene.target, (0., 8., 40.))
        scene.siege_precheck = SiegePrecheck(scene.runtime)
        # Budget tests count actual work, independent of machine/test-suite
        # scheduling. Production still observes the four-millisecond budget.
        scene.siege_precheck.clock = lambda: 0.
        scene.observe()
        return scene

    def run_candidate(self, scene, attempts=20):
        result = None
        scene.siege_receipts = []
        for unused in range(attempts):
            scene.observe()
            frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
            result = scene.siege_precheck.candidate(frame, scene.now)
            scene.siege_receipts.append(scene.siege_precheck.status())
            if result is not None:
                return result
            scene.fixture.now += .11
        return result

    def test_concrete_future_contact_does_not_enter_current_attack_proof_table(self):
        scene = self.scene(hydraulic_needed=True)
        policy = scene.runtime.attack_policy
        before = dict(policy.rows)
        result = self.run_candidate(scene)
        self.assertIsNotNone(result, scene.siege_precheck.status())
        self.assertEqual(before, policy.rows)
        self.assertEqual(('siege_precheck', 'siege_projected'), (result['mode'], result['mechanical']))
        self.assertTrue(result['solution']['needs_hydraulic'])
        self.assertFalse(result['solution']['source_verified'])
        self.assertFalse(policy._executable(result, 'penetration'))
        self.assertTrue(scene.world_queries)
        self.assertFalse(scene.battle._projectile_meta)

    def test_wall_contact_is_not_enough_to_request_the_mode(self):
        scene = self.scene()
        scene.world = [((-100., -100., 5.), (100., 100., 30.))]
        result = self.run_candidate(scene)
        self.assertIsNone(result)
        self.assertTrue(any(row['reason'] == 'world_blocked' for row in scene.siege_receipts))

    def test_friendly_hull_is_not_a_clear_future_line(self):
        scene = self.scene()
        scene.vehicle(43, (0., 0., 20.), team=1)
        result = self.run_candidate(scene)
        self.assertIsNone(result)
        self.assertTrue(any(row['reason'] == 'friendly_blocked' for row in scene.siege_receipts))

    def test_unknown_native_target_data_never_counts_as_future_point(self):
        scene = self.scene()
        scene.target.typeDescriptor.hull.hitTester.localHitTest = None
        result = self.run_candidate(scene)
        self.assertIsNone(result)
        self.assertTrue(any(row['reason'] == 'native_armour_unknown' for row in scene.siege_receipts))

    def test_yaw_projection_requires_proved_clear_full_original_rotation(self):
        for proved, clear, expected in ((False, True, False), (True, False, False), (True, True, True)):
            with self.subTest(proved=proved, clear=clear):
                scene = self.scene(bearing=.6)
                with mock.patch.object(scene.runtime.geometry, '_probe_bot_local_motion',
                        return_value=dict(proved=proved, clear=clear, reason='test_body_sweep')) as probe:
                    result = self.run_candidate(scene)
                self.assertEqual(expected, result is not None, scene.siege_precheck.status())
                self.assertTrue(probe.called)
                args = probe.call_args.args
                self.assertIsNone(args[4])
                self.assertGreater(abs(args[3] - args[2]), .5)
                if result is not None:
                    self.assertTrue(result['solution']['needs_hull'])

    def test_hydraulic_obstacle_refusal_cannot_become_point_proof(self):
        scene = self.scene(hydraulic_needed=True)
        with mock.patch.object(scene.runtime.geometry, '_turret_motion_is_clear', return_value=False) as probe:
            result = self.run_candidate(scene)
        self.assertIsNone(result)
        self.assertTrue(probe.called)
        first, last, unused_descriptor = probe.call_args.args
        self.assertNotEqual(first['hull']['pitch'], last['hull']['pitch'])
        self.assertNotEqual(first['hull']['y'], last['hull']['y'])
        self.assertTrue(any(row['reason'] == 'siege_hydraulic_sweep' for row in scene.siege_receipts))

    def test_track_pivot_does_not_borrow_a_stationary_centre_arc_proof(self):
        scene = self.scene(bearing=.6)
        scene.entity.typeDescriptor.siegeVehicleDescr.chassis.rotationIsAroundCenter = False
        with mock.patch.object(scene.runtime.geometry, '_probe_bot_local_motion',
                return_value=dict(proved=True, clear=True)) as center_probe:
            result = self.run_candidate(scene)
        self.assertIsNone(result)
        center_probe.assert_not_called()
        self.assertEqual('siege_track_pivot_projection_pending', scene.siege_precheck.status()['reason'])

    def test_candidate_fence_rejects_target_change_during_native_collision(self):
        scene = self.scene()
        moved = [False]
        def move():
            if not moved[0]:
                moved[0] = True
                scene.pose(scene.target, (0., 0., 80.))
        scene.on_probe = move
        scene.observe()
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        result = scene.siege_precheck.candidate(frame, scene.now)
        self.assertIsNone(result)
        self.assertEqual('siege_observation_changed', scene.siege_precheck.status()['reason'])

    def test_same_observation_does_not_replenish_precheck_budget(self):
        scene = self.scene()
        scene.world = [((-100., -100., 5.), (100., 100., 30.))]
        scene.observe()
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        for unused in range(6):
            self.assertIsNone(scene.siege_precheck.candidate(frame, scene.now))
        self.assertLessEqual(scene.siege_precheck._used, PRECHECK_CANDIDATES)
        self.assertLessEqual(len(scene.world_queries), PRECHECK_WORLD_CHORDS)

    def test_enabled_plain_child_keeps_retained_pair_and_remains_motion_only(self):
        scene = self.scene(hydraulic_needed=True)
        first = self.run_candidate(scene)
        self.assertIsNotNone(first, scene.siege_precheck.status())
        travel = scene.entity.typeDescriptor
        scene.entity.typeDescriptor = travel.siegeVehicleDescr
        scene.entity.siegeState = siege_mechanics.ENABLED
        scene.fixture.now += .11
        second = self.run_candidate(scene)
        self.assertIsNotNone(second, scene.siege_precheck.status())
        self.assertTrue(second['solution']['needs_hydraulic'])
        self.assertFalse(second['solution']['reachable'])
        self.assertFalse(scene.battle._projectile_meta)

    def test_precheck_uses_enabled_shell_ballistics_not_the_travel_object(self):
        scene = self.scene()
        enabled = scene.entity.typeDescriptor.siegeVehicleDescr
        enabled.gun.shots[0].speed *= 1.5
        result = self.run_candidate(scene)
        self.assertIsNotNone(result, scene.siege_precheck.status())
        solution = result['solution']
        speed = enabled.gun.shots[0].speed
        final = ballistics.ballistic_position(solution['origin'], solution['yaw'],
            solution['pitch'], speed, enabled.gun.shots[0].gravity, solution['flight_time'])
        for first, last in zip(final, solution['point']):
            self.assertAlmostEqual(first, last, places=6)
        self.assertIsNot(scene.runtime.gun.shots[0], enabled.gun.shots[0])
        self.assertNotEqual(scene.runtime.gun.shots[0].speed, speed)

    def test_changed_mode_ammunition_contract_does_not_admit_entry(self):
        scene = self.scene()
        scene.entity.typeDescriptor.siegeVehicleDescr.gun.shots[0].shell.compactDescr += 1
        self.assertIsNone(self.run_candidate(scene))
        self.assertEqual('siege_loaded_shell_contract_unavailable', scene.siege_precheck.status()['reason'])

    def test_known_siege_with_missing_pair_is_unknown_not_a_non_siege_vehicle(self):
        scene = self.scene()
        scene.entity.typeDescriptor.siegeVehicleDescr = None
        scene.runtime.engine._descriptor_pairs.clear()
        scene.observe()
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        self.assertIsNone(scene.siege_precheck.candidate(frame, scene.now))
        self.assertEqual(('pending', 'siege_descriptor_pair_unavailable'),
            (scene.siege_precheck.status()['status'], scene.siege_precheck.status()['reason']))

    def test_returning_hydraulics_to_neutral_still_requires_the_motion_sweep(self):
        scene = self.scene()
        scene.battle._local_siege_aim_pitch = .1
        scene.battle._local_siege_flat_body_matrix = scene.body
        with mock.patch.object(scene.runtime.geometry, '_turret_motion_is_clear', return_value=False) as probe:
            self.assertIsNone(self.run_candidate(scene))
        self.assertTrue(probe.called)
        self.assertTrue(any(row['reason'] == 'siege_hydraulic_sweep' for row in scene.siege_receipts))

    def test_active_physical_trigger_never_invokes_prospective_mode_checks(self):
        scene = self.scene()
        scene.observe()
        frame = scene.runtime.attack_policy.evaluator.snapshot(scene.now)
        frame['trigger_active'] = True
        with mock.patch.object(scene.siege_precheck.evaluator, 'evaluate') as evaluate:
            self.assertIsNone(scene.siege_precheck.candidate(frame, scene.now))
        evaluate.assert_not_called()
        self.assertEqual('held', scene.siege_precheck.status()['status'])

    def test_matched_hydraulic_input_is_read_without_another_collision_frontier(self):
        scene = self.scene(hydraulic_needed=True)
        row = self.run_candidate(scene)
        self.assertIsNotNone(row, scene.siege_precheck.status())
        before = len(scene.world_queries)
        point = scene.siege_precheck.hydraulic_point(row, row['solution']['point'])
        self.assertEqual(row['solution']['source_point'], point)
        self.assertEqual(before, len(scene.world_queries))

    def test_hydraulic_input_cannot_cross_samples_shells_or_weapon_points(self):
        scene = self.scene(hydraulic_needed=True)
        row = self.run_candidate(scene)
        point = row['solution']['point']
        self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, point))
        for changed in (dict(row, sample=row['sample'] + 1),
                        dict(row, shell_index=1), dict(row, target_key=('bot', 999))):
            self.assertIsNone(scene.siege_precheck.hydraulic_point(changed, point))
        self.assertIsNone(scene.siege_precheck.hydraulic_point(row, (100., 100., 100.)))

    def test_target_or_flat_chassis_motion_invalidates_hydraulic_input(self):
        for moving in ('target', 'chassis'):
            with self.subTest(moving=moving):
                scene = self.scene(hydraulic_needed=True)
                row = self.run_candidate(scene)
                point = row['solution']['point']
                self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, point))
                if moving == 'target':
                    scene.pose(scene.target, (1., 8., 40.))
                else:
                    scene.body.translation = (1., 0., 0.)
                self.assertIsNone(scene.siege_precheck.hydraulic_point(row, point))

    def test_changed_world_or_friendly_lane_invalidates_hydraulic_input(self):
        scene = self.scene(hydraulic_needed=True)
        row = self.run_candidate(scene)
        point = row['solution']['point']
        self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, point))
        with mock.patch.object(scene.battle, '_destructibles',
                types.SimpleNamespace(_spatial_revision_1513=lambda: 'replacement')):
            self.assertIsNone(scene.siege_precheck.hydraulic_point(row, point))
        self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, point))
        scene.vehicle(43, (0., 3., 20.), team=1)
        self.assertIsNone(scene.siege_precheck.hydraulic_point(row, point))

    def test_hydraulic_input_is_revoked_when_its_actuator_or_shell_changes(self):
        scene = self.scene(hydraulic_needed=True)
        row = self.run_candidate(scene)
        point = row['solution']['point']
        self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, point))
        scene.runtime.state['critical'] = dict(destroyed=['engineHealth'])
        self.assertIsNone(scene.siege_precheck.hydraulic_point(row, point))
        scene.runtime.state.pop('critical')
        scene.runtime.gun.shot_index = 1
        self.assertIsNone(scene.siege_precheck.hydraulic_point(row, point))

    def test_reset_retires_hydraulic_and_projected_proofs_together(self):
        scene = self.scene(hydraulic_needed=True)
        row = self.run_candidate(scene)
        self.assertIsNotNone(scene.siege_precheck.hydraulic_point(row, row['solution']['point']))
        scene.siege_precheck.reset()
        self.assertIsNone(scene.siege_precheck.hydraulic_point(row, row['solution']['point']))
        self.assertFalse(scene.siege_precheck.evaluator.jobs)
        self.assertFalse(scene.siege_precheck.evaluator.predictions)


class NativeSiegeTravelRecoveryTests(unittest.TestCase):
    """A refused future track-arc proof must not block actual recovery.

    Native flat-world observations are the same as the existing real-drive
    fixture. Policy, copied angle/driver laws, track-pivot integration, body
    sweeps, mode request/ack, hydraulic actuation and fire stay production.
    No projected body or yaw is assigned to the physical observation.
    """
    def scene(self, side):
        from test_player_siege_engagement import SiegeScene
        from test_player_limited_traverse import TraverseScene
        scene = SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(enabled=False, enabled_pitch=(0., 0.), hydraulic_center=1.5)
        scene.pose(scene.target, (side * 50., 12., 100.))
        TraverseScene.native_flat_drive(scene)
        battle = scene.battle
        battle.local_pose = lambda: (tuple(battle._local_position), battle._local_yaw)
        # Test determinism does not change the candidate/chord budgets or any
        # native geometry verdict. The production frontier retains its clock.
        scene.runtime.siege_precheck.clock = lambda: 0.
        self.observe_drive(scene)
        return scene

    @staticmethod
    def observe_drive(scene):
        from test_player_fire_admission_complete import SpatialPose
        battle = scene.battle
        scene.flat_body = SpatialPose()
        scene.flat_body.setRotateYPR((battle._local_yaw,
            battle._local_terrain_pitch, battle._local_roll))
        scene.flat_body.translation = battle._local_position
        battle._local_siege_flat_body_matrix = scene.flat_body
        battle._local_matrix = scene.flat_body
        scene.body = SpatialPose(scene.flat_body)
        scene.body.preMultiply(battle._local_siege_aim_matrix)
        battle._local_pose_matrix = scene.body
        scene.entity.matrix = scene.body
        scene.entity.position = battle._vector(battle._local_position)
        scene.update_barrel_observation()

    def tick_drive(self, scene):
        # Consume the actual previous native mailbox, including turn inertia
        # and the physical track-pivot translation, then publish its result.
        scene.battle._drive_local(.1)
        self.observe_drive(scene)
        scene.tick()

    def until(self, scene, condition, limit=160):
        for unused in range(limit):
            self.tick_drive(scene)
            if condition():
                return
        self.fail('Actual Siege travel recovery did not complete: %r' % dict(
            pose=(scene.battle._local_position, scene.battle._local_yaw),
            precheck=scene.runtime.siege_precheck.status(),
            position=scene.runtime.firing_position.receipt,
            pending=scene.runtime._siege_pending,
            policy=scene.runtime.attack_policy.status()))

    def test_unproved_future_track_arc_recovers_through_actual_native_travel(self):
        for side in (-1., 1.):
            with self.subTest(side=side):
                scene = self.scene(side)
                runtime, battle = scene.runtime, scene.battle
                self.assertFalse(scene.enabled_descriptor.chassis.rotationIsAroundCenter)
                self.assertFalse(battle._local_physics['rotationIsAroundCenter'])
                self.assertEqual((0., 0.), scene.travel_descriptor.gun.pitchLimits['absolute'])
                self.tick_drive(scene)
                self.assertEqual('siege_track_pivot_projection_pending',
                                 runtime.siege_precheck.status()['reason'])
                self.assertIsNone(runtime._siege_motion_candidate)
                self.assertIsNone(runtime._siege_pending)
                self.assertTrue(runtime.firing_position.active)
                self.assertEqual(0., battle._sender.forward)
                self.assertGreater(side * battle._sender.turn, 0.)
                self.assertFalse(scene.launches())

                self.until(scene, lambda: runtime._siege_motion_candidate is not None)
                preview = runtime._siege_motion_candidate
                self.assertFalse(preview['solution']['needs_hull'])
                self.assertFalse(preview['solution']['reachable'])
                self.assertGreater(side * battle._local_yaw, .3)
                self.assertNotEqual((0., 0., 0.), tuple(battle._local_position))
                self.assertFalse(runtime.firing_position.suppressed)
                self.assertFalse(scene.launches())
                episode = runtime.firing_position.episode['id']

                self.until(scene, lambda: (runtime._siege_pending or {}).get('sequence') is not None)
                request = runtime._siege_pending
                self.assertTrue(request['enabled'])
                scene.echo_mode(siege_mechanics.SWITCHING_ON, request['sequence'])
                self.tick_drive(scene)
                self.assertIs(request, runtime._siege_pending)
                self.assertFalse(scene.launches())
                scene.echo_mode(siege_mechanics.ENABLED, request['sequence'])
                self.until(scene, lambda: bool(scene.launches()))
                self.assertEqual(episode, runtime.firing_position.sequence)
                self.assertEqual(1, len(scene.launches()))
                self.assertTrue(runtime.weapon.verified)
                self.assertFalse(runtime.firing_position.suppressed)
                scene.doCleanups()


if __name__ == '__main__':
    unittest.main()
