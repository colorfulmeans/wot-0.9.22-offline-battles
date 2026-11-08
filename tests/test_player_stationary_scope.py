"""Stationary-domain sufficient proofs, never invented armour failures."""
import copy
import math
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import ballistics, shot_geometry
from gui.mods.offline_lan_0922.player_control import stationary_scope
from player_native_fixtures import descriptor


class ScopeScene(object):
    def __init__(self, fixed=False, point=(0., 30., 100.), speed=1000., maximum=5000.):
        self.descriptor = descriptor(-.01, .01, (-.1, .1))
        self.descriptor.chassis.rotationIsAroundCenter = True
        self.entity = types.SimpleNamespace(typeDescriptor=self.descriptor, siegeState=0)
        self.source = dict(critical=dict(destroyed=['engineHealth'] if fixed else []))
        self.record = dict(local=True, state=copy.deepcopy(self.source))
        self.owner = types.SimpleNamespace(_local_speed=0., _local_turn_speed=0.,
            _local_vertical_speed=0., _local_airborne=False,
            _records={'player:1': self.record}, _server=types.SimpleNamespace(vehicle_id=7),
            _server_entity=lambda unused: self.entity)
        self.runtime = types.SimpleNamespace(owner=self.owner, current_source=lambda: self.source,
                                             _local_record_key='player:1')
        self.frame = dict(descriptor=self.descriptor, position=(0., 0., 0.),
            origin=(0., 2., 0.), body=(0., 0., 0.), planning_pose=('pose', 1),
            pose=((0., 0., 0.), (0., 0., 0.), (0., 2., 0.), (0., 0.)))
        self.shell = dict(shot=dict(speed=speed, gravity=10., maxDistance=maximum))
        self.target = dict(velocity=(0., 0., 0.))
        self.predicted = dict(sample_point=point, reach=dict(status='mechanical_limited'))

    def assess(self):
        return stationary_scope.assess(self.runtime, self.frame, self.shell,
                                       self.target, self.predicted)


class StationaryScopeTests(unittest.TestCase):
    def test_already_reachable_is_not_an_exclusion(self):
        scene = ScopeScene()
        scene.predicted['reach']['status'] = 'reachable'
        self.assertEqual('reachable', scene.assess()['scope'])

    def test_a_mobile_hull_cannot_exhaust_pitch_domain_from_current_pose(self):
        scene = ScopeScene()
        result = scene.assess()
        self.assertEqual('pending', result['scope'])
        self.assertEqual('stationary_support_domain_unproved', result['reason'])
        # A fitted current ground plane does not certify another footprint.
        scene.owner._local_ground_plane = dict(normal=(0., 1., 0.), pitch=0., roll=0.)
        self.assertEqual('pending', scene.assess()['scope'])

    def test_a_single_lateral_yaw_refusal_is_not_an_exhausted_safe_pivot_domain(self):
        scene = ScopeScene(point=(100., 2., 0.))
        scene.predicted['reach']['status'] = 'hull_laying'
        self.assertEqual('pending', scene.assess()['scope'])

    def test_absolute_horizontal_range_excludes_without_an_armour_verdict(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
        result = scene.assess()
        self.assertEqual(('excluded', 'outside_stationary_horizontal_range'),
                         (result['scope'], result['reason']))
        self.assertEqual('all_pose_ballistic_bound', result['proof_type'])
        self.assertNotIn('armor', result)
        self.assertTrue(stationary_scope.current(scene.runtime, scene.frame, result))

    def test_the_whole_native_gun_mount_can_move_inside_the_stationary_sphere(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
        scene.descriptor.turret.gunPosition = (0., 0., 250.)
        scene.frame['origin'] = (0., 2., 250.)
        self.assertEqual('pending', scene.assess()['scope'])

    def test_track_pivot_translation_is_not_assumed_to_be_zero(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
        scene.descriptor.chassis.rotationIsAroundCenter = False
        scene.descriptor.physics = dict(trackCenterOffset=110.)
        self.assertEqual('pending', scene.assess()['scope'])

    def test_missing_pivot_or_mount_data_remains_unknown(self):
        for missing in ('pivot', 'mount'):
            with self.subTest(missing=missing):
                scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
                if missing == 'pivot':
                    del scene.descriptor.chassis.rotationIsAroundCenter
                else:
                    del scene.descriptor.turret.gunPosition
                self.assertEqual('pending', scene.assess()['scope'])

    def test_installed_native_pivot_law_is_not_replaced_by_an_invented_default(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
        del scene.descriptor.chassis.rotationIsAroundCenter
        scene.owner._local_physics = dict(rotationIsAroundCenter=True)
        self.assertEqual('excluded', scene.assess()['scope'])
        scene.owner._local_physics = dict(rotationIsAroundCenter=False, trackCenter=110.)
        self.assertEqual('pending', scene.assess()['scope'])

    def test_native_origin_offset_is_retained_in_the_rotation_bound(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500.)
        scene.frame['origin'] = (0., 2., 250.)
        self.assertEqual('pending', scene.assess()['scope'])

    def test_moving_target_can_enter_range_during_the_real_flight_window(self):
        scene = ScopeScene(point=(0., 2., 700.), maximum=500., speed=100.)
        scene.target['velocity'] = (0., 0., -100.)
        self.assertEqual('pending', scene.assess()['scope'])
        scene.target['velocity'] = (0., 0., 100.)
        self.assertEqual('excluded', scene.assess()['scope'])

    def test_absolute_ballistic_height_is_a_sufficient_all_pose_bound(self):
        scene = ScopeScene(point=(0., 1000., 20.), maximum=500., speed=100.)
        result = scene.assess()
        self.assertEqual(('excluded', 'above_stationary_envelope'),
                         (result['scope'], result['reason']))
        self.assertEqual('all_pose_ballistic_bound', result['proof_type'])

    def test_destroyed_stationary_engine_allows_a_whole_fixed_support_pitch_bound(self):
        scene = ScopeScene(fixed=True)
        result = scene.assess()
        self.assertEqual(('excluded', 'above_stationary_envelope'),
                         (result['scope'], result['reason']))
        self.assertEqual('fixed_support_envelope', result['proof_type'])
        self.assertIsNotNone(result['dependencies'])
        self.assertTrue(stationary_scope.current(scene.runtime, scene.frame, result))

    def test_destroyed_engine_does_not_delete_slope_roll_or_other_yaw_pitch_travel(self):
        for relief in ('slope', 'roll', 'yaw_curve'):
            with self.subTest(relief=relief):
                scene = ScopeScene(fixed=True)
                if relief == 'slope':
                    scene.frame['body'] = (0., -.4, 0.)
                elif relief == 'roll':
                    scene.frame['body'] = (0., 0., .4)
                else:
                    scene.descriptor.gun.pitchLimits['minPitch'] = (
                        (0., -.01), (math.pi, -.4), (2. * math.pi, -.01))
                self.assertEqual('pending', scene.assess()['scope'])

    def test_hydraulic_pitch_and_pivot_are_part_of_the_envelope_not_gun_travel(self):
        scene = ScopeScene(fixed=True)
        scene.descriptor.type.hullAimingParams = dict(pitch=dict(
            isAvailable=True, isEnabled=True,
            wheelsCorrectionAngles=dict(pitchMin=-.4, pitchMax=.4),
            wheelsCorrectionSpeed=.1, wheelCorrectionCenterZ=2.))
        scene.entity.siegeState = 2
        self.assertEqual('pending', scene.assess()['scope'])

    def test_possible_siege_descriptor_travel_cannot_be_excluded_by_travel_pitch_zero(self):
        scene = ScopeScene(fixed=True)
        siege = copy.deepcopy(scene.descriptor)
        siege.gun.pitchLimits['minPitch'] = ((0., -.4), (2. * math.pi, -.4))
        scene.descriptor.hasSiegeMode = True
        scene.descriptor.defaultVehicleDescr = scene.descriptor
        scene.descriptor.siegeVehicleDescr = siege
        self.assertEqual('pending', scene.assess()['scope'])

    def test_destroyed_but_moving_airborne_or_switching_hull_is_not_fixed_support(self):
        for field, value in (('_local_speed', .1), ('_local_turn_speed', .1),
                             ('_local_vertical_speed', -.1), ('_local_airborne', True),
                             ('siegeState', 1)):
            with self.subTest(field=field):
                scene = ScopeScene(fixed=True)
                setattr(scene.entity if field == 'siegeState' else scene.owner, field, value)
                self.assertEqual('pending', scene.assess()['scope'])

    def test_invalid_or_partial_pitch_curve_cannot_produce_a_pose_exclusion(self):
        for curve in ((), ((.1, -.01), (math.pi, -.01)),
                      ((0., -.01), (0., -.5), (2. * math.pi, -.01)),
                      ((0., float('nan')), (2. * math.pi, -.01))):
            with self.subTest(curve=curve):
                scene = ScopeScene(fixed=True)
                scene.descriptor.gun.pitchLimits['minPitch'] = curve
                self.assertEqual('pending', scene.assess()['scope'])

    def test_repair_invalidates_scope_from_the_native_record_even_if_frame_is_unchanged(self):
        scene = ScopeScene(fixed=True)
        result = scene.assess()
        scene.record['state']['critical']['destroyed'] = []
        self.assertEqual(['engineHealth'], scene.source['critical']['destroyed'])
        self.assertFalse(stationary_scope.current(scene.runtime, scene.frame, result))

    def test_even_a_range_exclusion_requiring_fixed_pivot_radius_expires_on_repair(self):
        scene = ScopeScene(fixed=True, point=(0., 2., 700.), maximum=500.)
        scene.descriptor.chassis.rotationIsAroundCenter = False
        scene.descriptor.physics = dict(trackCenterOffset=110.)
        result = scene.assess()
        self.assertEqual('excluded', result['scope'])
        scene.record['state']['critical']['destroyed'] = []
        self.assertFalse(stationary_scope.current(scene.runtime, scene.frame, result))
        self.assertEqual('pending', scene.assess()['scope'])

    def test_source_pose_change_or_missing_native_dependencies_retires_proof(self):
        scene = ScopeScene(fixed=True)
        result = scene.assess()
        scene.frame['planning_pose'] = ('pose', 2)
        self.assertFalse(stationary_scope.current(scene.runtime, scene.frame, result))
        scene.frame['planning_pose'] = ('pose', 1)
        del scene.owner._local_turn_speed
        self.assertFalse(stationary_scope.current(scene.runtime, scene.frame, result))

    def test_no_sample_velocity_or_solution_is_not_an_exclusion(self):
        for missing in ('sample', 'velocity', 'prediction'):
            with self.subTest(missing=missing):
                scene = ScopeScene(fixed=True)
                if missing == 'sample':
                    scene.predicted.pop('sample_point')
                elif missing == 'velocity':
                    scene.target['velocity'] = None
                else:
                    scene.predicted = None
                self.assertEqual('pending', scene.assess()['scope'])

    def test_bounded_envelope_never_excludes_explicit_reachable_launch_samples(self):
        # This checks an enclosing continuum, not a search that declares all
        # unsampled headings impossible. Every test shot is an actual analytic
        # trajectory launched within the descriptor's allowed gun travel.
        scene = ScopeScene(fixed=True, speed=300.)
        scene.descriptor.gun.pitchLimits['minPitch'] = ((0., -.2), (2. * math.pi, -.2))
        scene.descriptor.gun.pitchLimits['maxPitch'] = ((0., .1), (2. * math.pi, .1))
        for tilt, roll in ((0., 0.), (-.1, .2), (.2, -.1)):
            scene.frame['body'] = (0., tilt, roll)
            for turret_yaw in (-2., -.1, 0., 1.4):
                for gun_pitch in (-.2, -.05, .1):
                    origin, direction = shot_geometry.shot_origin_and_direction(
                        scene.descriptor, scene.frame['position'], 0., tilt, roll,
                        turret_yaw, gun_pitch)
                    yaw = math.atan2(direction[0], direction[2])
                    pitch = -math.atan2(direction[1], math.hypot(direction[0], direction[2]))
                    for flight in (.1, .5, 1.):
                        point = ballistics.ballistic_position(origin, yaw, pitch, 300., 10., flight)
                        scene.predicted['sample_point'] = point
                        result = scene.assess()
                        self.assertNotEqual('excluded', result['scope'],
                            (tilt, roll, turret_yaw, gun_pitch, flight, result))


class NativeStationaryScopeIntegrationTests(unittest.TestCase):
    """Use the real finite frontier and native fixture, not supplied scope flags."""
    def scene(self):
        from test_player_fire_admission_complete import AutomaticFireScene
        scene = AutomaticFireScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.entity.typeDescriptor.chassis.rotationIsAroundCenter = True
        scene.entity.siegeState = 0
        scene.battle._local_speed = scene.battle._local_turn_speed = 0.
        scene.battle._local_vertical_speed = 0.
        scene.battle._local_airborne = False
        return scene

    def row(self, scene):
        policy = scene.runtime.attack_policy
        for unused in range(40):
            scene.observe()
            policy.frame = policy.evaluator.snapshot(scene.now)
            job = next(job for job in policy._jobs('penetration', 0)
                       if job[2]['entity'] is scene.target and job[3] == 0)
            row = policy._evaluate(job, scene.now, 'foreground')
            if row['line'] != 'pending':
                return job, row
            scene.fixture.now += .1
        self.fail('native point frontier did not settle')

    def test_production_intercept_exclusion_stays_geometry_not_armour(self):
        scene = self.scene()
        scene.battle._gun_state.shots[0].maxDistance = 10.
        unused_job, row = self.row(scene)
        self.assertEqual(('excluded', 'unknown', 'mechanical_limited'),
                         (row.get('scope'), row['armor'], row['mechanical']))
        self.assertEqual('outside_stationary_horizontal_range', row['scope_reason'])
        self.assertEqual('all_pose_ballistic_bound', row['scope_proof']['proof_type'])

    def test_production_fixed_hull_scope_retires_on_native_engine_repair(self):
        scene = self.scene()
        limits = scene.entity.typeDescriptor.gun.pitchLimits
        limits.update(minPitch=((0., -.01), (2. * math.pi, -.01)),
                      maxPitch=((0., .01), (2. * math.pi, .01)))
        scene.battle._records['player:1']['state']['critical'] = dict(
            destroyed=['engineHealth'], devices=[], crew_ko=[])
        scene.pose(scene.target, (0., 30., 100.))
        job, row = self.row(scene)
        self.assertEqual(('excluded', 'unknown', 'clear'),
                         (row.get('scope'), row['armor'], row['line']))
        policy = scene.runtime.attack_policy
        self.assertIs(row, policy._current(job, require_line=True))
        # Canonical repair arrives before the next copied observation. It
        # must still invalidate the old engine-immobile exclusion immediately.
        scene.battle._records['player:1']['state']['critical']['destroyed'] = []
        self.assertIsNone(policy._current(job, require_line=True))
        unused_job, repaired = self.row(scene)
        self.assertEqual(('pending', 'unknown'), (repaired.get('scope'), repaired['armor']))

    def test_production_mobile_pitch_refusal_and_world_blocker_are_not_exclusions(self):
        scene = self.scene()
        limits = scene.entity.typeDescriptor.gun.pitchLimits
        limits.update(minPitch=((0., -.01), (2. * math.pi, -.01)),
                      maxPitch=((0., .01), (2. * math.pi, .01)))
        scene.pose(scene.target, (0., 30., 100.))
        unused_job, row = self.row(scene)
        self.assertEqual(('pending', 'unknown'), (row.get('scope'), row['armor']))
        scene.world = [((-100., -100., 5.), (100., 100., 16.))]
        scene.runtime.attack_policy.evaluator.invalidate_line(row['key'])
        unused_job, blocked = self.row(scene)
        self.assertEqual('world_blocked', blocked['line'])
        self.assertNotEqual('excluded', blocked.get('scope'))
        self.assertEqual('unknown', blocked['armor'])


if __name__ == '__main__':
    unittest.main()
