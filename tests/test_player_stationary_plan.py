"""Native support/collision-backed stationary plans, never shot permission.

Only physical world/catalog/ground observations are fixtures. Projection,
ground-plane fit, continuous collision arcs, peers, boundaries and the real
NativeAttackEvaluator are production code. Windows physics is not simulated.
"""
import copy
import math
import types
import unittest

from test_player_limited_traverse import TraverseScene
from test_player_fire_admission_complete import SpatialPose
from gui.mods.offline_lan_0922 import destructibles_sensor, shot_geometry, vehicle_physics
from gui.mods.offline_lan_0922.vehicle_control.stationary_plan import (
    StationaryPlanner, SLICES_PER_TICK, DESTRUCTIBLE_POSE_MAX_ANGLE_STEP)
from gui.mods.offline_lan_0922.vehicle_control.geometry import SharedBattleGeometry


def install_plan_observations(scene, around_center=True, track_center=1.5, slope=(0., 0.)):
    """Add exact descriptor/support/empty-catalog native I/O to TraverseScene."""
    descriptor, battle, runtime = scene.entity.typeDescriptor, scene.battle, scene.runtime
    descriptor.chassis.rotationIsAroundCenter = around_center
    descriptor.physics['trackCenterOffset'] = track_center
    scene.entity.siegeState = 0
    scene.catalog_calls, scene.ground_calls = [], []
    scene.catalog_status, scene.scene_revision = 'clear', 0
    scene.tree_status = 'clear'
    scene.ground_function = lambda x, z: slope[0] * x + slope[1] * z

    def ground(x, z, hint=0.):
        scene.ground_calls.append((x, z, hint))
        return scene.ground_function(x, z)

    def support_hit(start, end, unused_filter):
        height = ground(start.x, start.z, start.y - 2.)
        if height is not None and end.y <= height <= start.y:
            return battle._vector((start.x, height, start.z)), battle._vector((0., 1., 0.))
        return None

    def catalog(*args, **kwargs):
        scene.catalog_calls.append((args, kwargs))
        return dict(status=scene.catalog_status, token=None, accepted_now=False,
                    requires_commit=False, used_kinetic_speed=False, kinds='-')

    scene.sensor = types.SimpleNamespace(
        _vehicle_body_bbox=destructibles_sensor._vehicle_body_bbox,
        _catalog_motion_proposal=catalog,
        _tree_motion_proposal=lambda *args, **kwargs: dict(status=scene.tree_status, token=None,
            accepted_now=False, requires_commit=False, kinds='-'),
        _spatial_revision_1513=lambda: scene.scene_revision)
    battle._destructibles = scene.sensor
    battle._collide_down = support_hit
    runtime.geometry._ground_y = ground
    # The broader runtime fixture has no debris. Restore the production
    # landed-turret consumer here so an observed obstacle is really tested.
    runtime.geometry._turret_motion_is_clear = types.MethodType(
        SharedBattleGeometry._turret_motion_is_clear, runtime.geometry)
    runtime.engine._turret_motion_probe = runtime.geometry._turret_motion_is_clear
    plane = runtime.geometry._sample_ground_plane(scene.position, scene.body.yaw, descriptor)
    if slope != (0., 0.):
        battle._runtime.math.Matrix = SpatialPose
        scene.body = SpatialPose()
        scene.body.setRotateYPR((0., plane['pitch'], plane['roll']))
        scene.body.translation = scene.position
        scene.entity.matrix = scene.body
        battle._local_matrix = battle._local_pose_matrix = scene.body
    battle._local_ground_plane = plane
    battle._local_terrain_pitch = plane['pitch']
    battle._local_pitch, battle._local_roll = plane['pitch'], plane['roll']
    battle._local_airborne = False
    battle._local_speed = battle._local_turn_speed = battle._local_vertical_speed = 0.
    battle._records['player:1']['state']['critical'] = dict(destroyed=[])
    rotator = battle._avatar.gunRotator
    scene.origin = shot_geometry.shot_origin_and_direction(descriptor,
        tuple(scene.body.translation), scene.body.yaw, scene.body.pitch, scene.body.roll,
        rotator.turretYaw, rotator.gunPitch)[0]
    scene.observe()
    scene.planner = StationaryPlanner(runtime)
    scene.planner.clock = lambda: 0.
    # Both helpers must be the same stateful object during policy integration.
    runtime.attack_policy.evaluator.stationary_planner = scene.planner
    return scene


class NativePlanScene(TraverseScene):
    def configure_plan(self, **kwargs):
        physical = dict((name, kwargs.pop(name)) for name in
            ('around_center', 'track_center', 'slope') if name in kwargs)
        self.configure(**kwargs)
        self.plan_receipts = []
        return install_plan_observations(self, **physical)

    def plan_frame(self, sample=0, target_entity=None, shell_index=0):
        self.observe()
        evaluator = self.runtime.attack_policy.evaluator
        frame = evaluator.snapshot(self.now)
        target = next(row for row in frame['targets'] if row['entity'] is
                      (target_entity if target_entity is not None else self.target))
        shell = frame['shells'][shell_index]
        raw = evaluator._prediction(frame, shell, target, sample)
        return frame, shell, target, raw

    def plan(self, sample=0, attempts=25, target_entity=None, shell_index=0):
        result = None
        for unused in range(attempts):
            frame, shell, target, raw = self.plan_frame(sample, target_entity, shell_index)
            result = self.planner.project(frame, shell, target, raw, self.now, 'foreground')
            self.plan_receipts.append(result)
            if result['status'] == 'proved' or not result.get('progressing'):
                return frame, result
            self.fixture.now += .11
        return frame, result


class StationaryPlanTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = NativePlanScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_plan(**kwargs)
        scene.plan_receipts = []
        return scene

    def test_native_center_arc_and_support_produce_motion_only_receipt(self):
        scene = self.scene(bearing=.7)
        old_state, old_origin = copy.deepcopy(scene.runtime.state), scene.origin
        old_matrix = tuple(scene.body.translation), scene.body.yaw
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertTrue(plan['proof']['arc'])
        self.assertTrue(scene.catalog_calls)
        self.assertTrue(scene.world_queries)
        self.assertGreater(len(scene.ground_calls), 5)
        self.assertFalse(plan['proof']['fire_permission'])
        self.assertFalse(plan['prediction']['solution']['source_verified'])
        self.assertEqual(old_origin, scene.origin)
        self.assertEqual(old_matrix, (tuple(scene.body.translation), scene.body.yaw))
        self.assertEqual(old_state.get('_rotation_contact_trace'),
                         scene.runtime.state.get('_rotation_contact_trace'))
        self.assertTrue(scene.planner.current(frame, plan))
        self.assertEqual('hull_laying', scene.plan_frame()[3]['reach']['status'])
        self.assertFalse(scene.battle._projectile_meta)

    def test_track_pivot_uses_real_translated_arc_and_endpoint(self):
        scene = self.scene(bearing=.7, around_center=False, track_center=1.5)
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        proof = plan['proof']
        self.assertEqual(1.5, proof['pivot_offset'])
        expected = vehicle_physics.track_pivot_position(frame['position'], frame['body'][0],
            plan['projected_frame']['body'][0], 1.5)
        self.assertEqual(expected, plan['projected_frame']['position'])
        self.assertNotEqual(frame['position'], expected)
        self.assertTrue(all(row['pivot_offset'] == 1.5 for row in proof['arc']))
        self.assertNotEqual(proof['arc'][0]['start'], proof['arc'][-1]['start'])

    def test_negative_track_pivot_preserves_inner_track(self):
        scene = self.scene(bearing=-.7, around_center=False, track_center=1.5)
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertEqual(-1.5, plan['proof']['pivot_offset'])
        self.assertLess(plan['projected_frame']['position'][0], 0.)

    def test_physics_only_track_pivot_cannot_certify_a_descriptor_based_catalog_arc(self):
        scene = self.scene(bearing=.7, around_center=False)
        del scene.entity.typeDescriptor.chassis.rotationIsAroundCenter
        scene.battle._local_physics = dict(rotationIsAroundCenter=False, trackCenter=1.5)
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'], plan)
        self.assertFalse(scene.catalog_calls)

    def test_every_native_slice_has_independent_middle_and_end_support(self):
        scene = self.scene(bearing=.7)
        unused, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        for row in plan['proof']['arc']:
            self.assertLessEqual(abs(row['end_yaw'] - row['start_yaw']),
                                 DESTRUCTIBLE_POSE_MAX_ANGLE_STEP + 1.e-9)
            middle, end = row['support']
            self.assertAlmostEqual((row['start_yaw'] + row['end_yaw']) * .5, middle['yaw'])
            self.assertEqual(row['end_yaw'], end['yaw'])

    def test_budget_is_shared_between_points_and_channels_then_progresses(self):
        scene = self.scene(bearing=2.8)
        frame, shell, target, raw = scene.plan_frame()
        first = scene.planner.project(frame, shell, target, raw, scene.now, 'foreground')
        calls = len(scene.catalog_calls)
        self.assertTrue(first['progressing'], first)
        self.assertLessEqual(calls, SLICES_PER_TICK)
        second = scene.planner.project(frame, shell, target, raw, scene.now, 'background')
        self.assertEqual(calls, len(scene.catalog_calls))
        self.assertEqual(first['progress_token'], second['progress_token'])
        unused, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        tokens = [r['progress_token'] for r in scene.plan_receipts if 'progress_token' in r]
        self.assertGreater(len(set(tokens)), 1)

    def test_second_sample_reuses_safe_arc_but_not_its_projectile(self):
        scene = self.scene(bearing=.7)
        unused, first = scene.plan(sample=0)
        calls, supports = len(scene.catalog_calls), len(scene.ground_calls)
        unused, second = scene.plan(sample=1)
        self.assertEqual(('proved', 'proved'), (first['status'], second['status']))
        self.assertEqual(calls, len(scene.catalog_calls))
        self.assertEqual(supports, len(scene.ground_calls))
        self.assertNotEqual(first['prediction']['sample_point'], second['prediction']['sample_point'])

    def test_far_moving_friend_does_not_reset_shared_static_arc_prefix(self):
        scene = self.scene(bearing=2.8)
        friend = scene.vehicle(43, (35., 0., 35.), team=1)
        epochs, tokens, line_stamps = [], [], []
        result = None
        for tick in range(20):
            scene.pose(friend, (35. + tick * .2, 0., 35.))
            frame, shell, target, raw = scene.plan_frame()
            line_stamps.append(frame['line_revision'])
            result = scene.planner.project(frame, shell, target, raw, scene.now, 'foreground')
            epochs.append(scene.planner._epoch_serial)
            tokens.append(len(scene.planner._arcs))
            if result['status'] == 'proved':
                break
            self.assertTrue(result['progressing'], result)
            scene.fixture.now += .11
        self.assertEqual('proved', result['status'], result)
        self.assertEqual(1, len(set(epochs)))
        self.assertEqual(sorted(tokens), tokens)
        self.assertGreater(len(set(line_stamps)), 1)
        self.assertGreater(len(set(tokens)), 1)

    def test_nearby_moving_peer_keeps_completed_static_checks(self):
        scene = self.scene(bearing=2.8)
        friend = scene.vehicle(43, (6.2, 0., 0.), team=1)
        counts, epochs = [], []
        for tick in range(20):
            scene.pose(friend, (6.2, 0., tick * .01))
            frame, shell, target, raw = scene.plan_frame()
            result = scene.planner.project(frame, shell, target, raw, scene.now, 'foreground')
            epochs.append(scene.planner._epoch_serial)
            counts.append(len(scene.planner._arcs))
            if result['status'] == 'proved':
                break
            self.assertTrue(result['progressing'], result)
            scene.fixture.now += .11
        self.assertEqual('proved', result['status'], result)
        self.assertGreater(len(set(epochs)), 1)
        self.assertEqual(sorted(counts), counts)
        self.assertTrue(scene.planner.current(frame, result))
        scene.pose(friend, (3.7, 0., 0.))
        self.assertFalse(scene.planner.current(frame, result))
        unused, blocked = scene.plan()
        self.assertEqual('stationary_peer_rotation_blocked', blocked['reason'])

    def test_new_peer_entering_any_stationary_arc_retires_old_safety_receipt(self):
        scene = self.scene(bearing=1.5, around_center=False)
        friend = scene.vehicle(43, (35., 0., 35.), team=1)
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        epoch = scene.planner._epoch_serial
        scene.pose(friend, (4., 0., 0.))
        self.assertFalse(scene.planner.current(frame, plan))
        unused, result = scene.plan()
        self.assertGreater(scene.planner._epoch_serial, epoch)
        self.assertEqual('pending', result['status'], result)
        self.assertEqual('stationary_peer_rotation_blocked', result['reason'])

    def test_new_landed_turret_retires_old_frame_without_catalog_revision_change(self):
        from gui.mods.offline_lan_0922.entities.turret_obstacles import DetachedTurretObstacles
        from test_port_0922_turret_obstacles import row, descriptor
        scene = self.scene(bearing=1.5)
        obstacle = DetachedTurretObstacles(scene.battle._runtime.math)
        scene.battle._detached_turret_obstacles = obstacle
        scene.battle._projectile_server_time_ms = 10000
        scene.battle._projectile_server_local_time = scene.now
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertTrue(scene.planner.current(frame, plan))
        revision = scene.scene_revision
        self.assertTrue(obstacle.add('bot:17', row(rest=(3.2, 1., 0.)), descriptor()))
        self.assertEqual(revision, scene.scene_revision)
        self.assertFalse(scene.planner.current(frame, plan))
        unused, after = scene.plan()
        self.assertEqual('pending', after['status'], after)
        self.assertEqual('stationary_detached_turret_rotation_blocked', after['reason'])

    def test_intermediate_ground_hole_is_not_cleared_by_identical_endpoints(self):
        scene = self.scene(bearing=.7)
        # The front footprint at an intermediate angular slice alone is void.
        angle = DESTRUCTIBLE_POSE_MAX_ANGLE_STEP * 3.5
        missing = (math.sin(angle) * 3.5, math.cos(angle) * 3.5)
        scene.ground_function = lambda x, z: (None if
            abs(x - missing[0]) < .01 and abs(z - missing[1]) < .01 else 0.)
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'])
        self.assertEqual('stationary_native_support_pending', plan['reason'])
        self.assertFalse(plan['progressing'])

    def test_changed_intermediate_support_is_not_a_flat_plane_certificate(self):
        scene = self.scene(bearing=.7)
        angle = DESTRUCTIBLE_POSE_MAX_ANGLE_STEP * 3.5
        changed = (math.sin(angle) * 3.5, math.cos(angle) * 3.5)
        scene.ground_function = lambda x, z: (.2 if
            abs(x - changed[0]) < .01 and abs(z - changed[1]) < .01 else 0.)
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'])
        self.assertEqual('stationary_support_plane_changes', plan['reason'])

    def test_center_pivot_uses_measured_cross_slope_support(self):
        scene = self.scene(bearing=.7, slope=(.03, -.04))
        unused, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertNotEqual((0., 0.), plan['projected_frame']['body'][1:])
        self.assertAlmostEqual(.03, plan['proof']['arc'][-1]['support'][-1]['gradient_x'])

    def test_track_pivot_vertical_travel_requires_separate_native_owner(self):
        scene = self.scene(bearing=.7, around_center=False, slope=(.1, -.1))
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'])
        self.assertEqual('stationary_track_vertical_path_pending', plan['reason'])

    def test_catalog_rejection_is_not_plan_or_exclusion(self):
        scene = self.scene(bearing=.7)
        scene.catalog_status = 'hard'
        unused, plan = scene.plan()
        self.assertEqual(('pending', 'stationary_native_rotation_blocked'),
                         (plan['status'], plan['reason']))
        self.assertNotIn('armor', plan)
        self.assertNotIn('scope', plan)

    def test_native_peer_rotation_rejects_swept_corner(self):
        scene = self.scene(bearing=1.5)
        scene.vehicle(43, (3.7, 0., 0.), team=1)
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'], plan)
        self.assertEqual('stationary_peer_rotation_blocked', plan['reason'])

    def test_native_world_wall_is_not_overridden_by_clear_catalog(self):
        scene = self.scene(bearing=.7)
        scene.world = [((2., -1., -10.), (2.1, 5., 10.))]
        def physical_hit(space, first, last, mask):
            hit = scene.world_probe(space, first, last, mask)
            if hit is None:
                return None
            normal = scene.battle._vector((-1., 0., 0.))
            return hit[0], normal, 0
        scene.battle._runtime.bigworld.wg_collideSegment = physical_hit
        unused, plan = scene.plan()
        self.assertEqual('pending', plan['status'], plan)
        self.assertEqual('stationary_native_rotation_blocked', plan['reason'])

    def test_native_unknown_tree_does_not_inherit_the_motion_legacy_clear_seam(self):
        for status in ('pending', 'hard'):
            with self.subTest(status=status):
                scene = self.scene(bearing=.7)
                scene.tree_status = status
                unused, plan = scene.plan()
                self.assertEqual('pending', plan['status'], plan)
                self.assertEqual('stationary_native_tree_contact_pending', plan['reason'])

    def test_arena_and_missing_native_geometry_do_not_invent_clear(self):
        for missing in ('arena', 'box', 'pivot', 'sensor'):
            with self.subTest(missing=missing):
                scene = self.scene(bearing=.7)
                if missing == 'arena':
                    scene.battle._arena_bounds = (-1., -1., 1., 1.)
                elif missing == 'box':
                    scene.entity.typeDescriptor.hull.hitTester.bbox = None
                elif missing == 'pivot':
                    del scene.entity.typeDescriptor.chassis.rotationIsAroundCenter
                    scene.battle._local_physics = None
                else:
                    scene.battle._destructibles = None
                unused, plan = scene.plan()
                self.assertEqual('pending', plan['status'], plan)
                self.assertFalse(plan.get('proved'))

    def test_current_reads_native_scene_peer_source_and_critical_dependencies(self):
        for changed in ('world', 'peer', 'source', 'critical', 'mode'):
            with self.subTest(changed=changed):
                scene = self.scene(bearing=.7)
                frame, plan = scene.plan()
                self.assertEqual('proved', plan['status'], plan)
                if changed == 'world':
                    scene.scene_revision += 1
                elif changed == 'peer':
                    scene.pose(scene.target, (4., 0., 0.))
                elif changed == 'source':
                    scene.position = (1., 0., 0.)
                    scene.set_hull(scene.body.yaw)
                elif changed == 'critical':
                    scene.battle._records['player:1']['state']['critical']['destroyed'] = ['engineHealth']
                else:
                    scene.entity.siegeState = 1
                self.assertFalse(scene.planner.current(frame, plan), changed)

    def test_native_support_rise_retires_old_plan_before_observe(self):
        scene = self.scene(bearing=.7)
        frame, plan = scene.plan()
        self.assertEqual('proved', plan['status'], plan)
        self.assertFalse(scene.runtime.state.get('_foreground_support_blocked'))
        scene.battle._local_support_rise_blocked = True
        self.assertFalse(scene.runtime.state.get('_foreground_support_blocked'))
        self.assertFalse(scene.planner.current(frame, plan))


if __name__ == '__main__':
    unittest.main()
