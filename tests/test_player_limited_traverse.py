"""Limited-arc regressions through the complete foreground runtime.

Synthetic installed arcs below are not measured WZ data. Native bodies, barrel
actuation, BSP and component collision are observations; the copied planner and
driver, attack policy, trigger admission and physical ammunition are production
consumers. No retired player Aiming/Weapon/DirectEngagement/HullAlignment runs.
"""
import copy
import math
import os
import types
import unittest
from unittest import mock

import test_player_fire_admission_complete as fire_tests
from player_native_fixtures import descriptor
from gui.mods.offline_lan_0922 import gun_mechanics, shot_geometry
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control import attack_policy
from gui.mods.offline_lan_0922.player_control.native_aim import (
    NATIVE_ANGLE_TOLERANCE, _direction, mechanical_reach)
from gui.mods.offline_lan_0922.player_control.copied.ai import driver


class TraverseScene(fire_tests.AutomaticFireScene):
    """Full control loop with explicit physical body/barrel feedback."""
    def configure(self, limits=(-.2, .2), tag='AT-SPG', clip=1,
                  bearing=.7, burst=1, rate=.8, capture=False):
        self.control.close()
        self.entity.typeDescriptor.gun.turretYawLimits = limits
        self.entity.typeDescriptor.type.tags = (tag,)
        self.entity.typeDescriptor.gun.clip = (clip, .5)
        self.entity.typeDescriptor.gun.burst = (burst, .1)
        self.battle._gun_state = gun_mechanics.GunState(
            self.entity.typeDescriptor, ammo_layout={101: 20, 102: 10})
        self.battle._gun_state.reload_time = 0.
        self.battle._gun_state.clip = clip
        self.position = (0., 0., 0.)
        self.bearing, self.rate = bearing, rate
        self.rotator_enabled = False
        self.source_enabled = True
        self.source_queries, self.trace = [], []
        self.set_hull(0.)
        self.origin = (0., 2., 0.)
        self.pose(self.target, (math.sin(bearing)*40., 0., math.cos(bearing)*40.))
        self.battle.local_pose = lambda: (self.position, self.body.yaw)
        self.battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        self.battle._local_speed = self.battle._local_turn_speed = 0.
        self.battle._runtime.get_shot_angles = self.source_angles
        session = mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'limited-traverse'})
        session.start()
        self.addCleanup(session.stop)
        self.control = PlayerControl(self.battle, ('drive', 'fire'), notify=lambda text: None)
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: True
        self.control.gateway.emit = self.control.emit_result
        self.battle._player_control = self.control
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime = self.control.runtime
        self.admission = self.control._admission()
        self.trigger = mock.Mock(wraps=self.control._native_trigger)
        self.control._native_trigger = self.trigger
        if capture:
            # Canonical observed circles feed the complete copied planner.
            self.battle._last_snapshot = dict(capture_bases={
                '1': [dict(id='1:0', x=0., y=0., z=-40., radius=12.)],
                '2': [dict(id='2:0', x=0., y=0., z=0., radius=12.)]},
                capture_contributors={'2:0': [1]})
        return self

    def set_hull(self, yaw):
        self.body.setRotateY(yaw)
        self.body.translation = getattr(self, 'position', (0., 0., 0.))
        self.entity.matrix = self.body
        self.battle._local_matrix = self.battle._local_pose_matrix = self.body
        self.battle._local_yaw = float(yaw)

    def source_angles(self, *args):
        self.source_queries.append((self.now, self.body.yaw, args[-1]))
        if not self.source_enabled:
            raise RuntimeError('native source temporarily unavailable')
        return self.get_angles(*args)

    def evaluate(self, sample_index=0, complete=True, mode='penetration'):
        policy = self.runtime.attack_policy
        for unused in range(80 if complete else 1):
            self.observe()
            policy.frame = policy.evaluator.snapshot(self.now)
            jobs = [job for job in policy._jobs(mode, self.battle._gun_state.shot_index)
                    if job[2]['entity'] is self.target and job[3] == sample_index]
            self.assertEqual(1, len(jobs))
            row = policy._evaluate(jobs[0], self.now, 'foreground')
            if row.get('line') != 'pending':
                return row
            self.fixture.now += .1
        return row

    def lay_current(self, sample_index=0, move_barrel=True):
        row = self.evaluate(sample_index)
        solution = row['solution']
        self.runtime.attack_policy._choose('aim', 'selected_native_fixture_sample', row)
        reach = mechanical_reach(self.entity.typeDescriptor, solution['direction'],
                                 (self.body.yaw, self.body.pitch, self.body.roll))
        rotator = self.battle._avatar.gunRotator
        if move_barrel:
            rotator.turretYaw, rotator.gunPitch = reach['local_yaw'], reach['local_pitch']
            self.direction = tuple(solution['direction'])
            self.observe()
            # Physical barrel changes invalidate the previous pose evidence.
            row = self.evaluate(sample_index)
            solution = row['solution']
            self.runtime.attack_policy._choose('aim', 'selected_native_fixture_sample', row)
        self.runtime.weapon.aim(self.runtime.state, row['target'],
            dict(aim_position=solution['point']),
            dict(turret_yaw=reach['local_yaw'], gun_pitch=reach['local_pitch']))
        self.runtime.state['gun_aligned'] = bool(
            self.runtime.weapon.verified and reach['reachable'] and
            abs(rotator.turretYaw-reach['local_yaw']) <= 1.e-6 and
            abs(rotator.gunPitch-reach['local_pitch']) <= 1.e-6)
        self.candidate = row
        return row

    def actuate(self, seconds):
        sender = self.battle._sender
        turn = float(sender.turn)
        # Explicit A/D still owns traverse with longitudinal brake, matching
        # battle._local_autorotation_turn's first branch.
        self.set_hull(self.body.yaw + turn*self.rate*seconds)
        self.battle._local_turn_speed = turn*self.rate
        if not self.rotator_enabled:
            return
        source = self.battle._avatar.gunRotator.shotPointSourceFunctor
        if not callable(source) or source() is None:
            return
        angles = self.get_angles(self.entity.typeDescriptor, self.body, (0., 0.), source())
        limits = self.entity.typeDescriptor.gun.turretYawLimits
        yaw = angles[0] if limits is None else min(limits[1], max(limits[0], angles[0]))
        rotator = self.battle._avatar.gunRotator
        rotator.turretYaw, rotator.gunPitch = yaw, angles[1]
        self.direction = shot_geometry.transform_vehicle_vector(
            _direction(yaw, angles[1]), self.body.yaw, self.body.pitch, self.body.roll)

    def tick(self, seconds=.11):
        self.actuate(seconds)
        self.fixture.now += seconds
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.trace.append(dict(now=self.now, yaw=self.body.yaw,
            sender=(self.battle._sender.forward, self.battle._sender.turn,
                    self.battle._sender.handbrake),
            hull_aiming=self.runtime.state.get('hull_aiming'),
            action=self.runtime.attack_policy.decision.get('action'),
            reason=self.runtime.attack_policy.decision.get('reason'),
            order=dict(self.control.last_order),
            aim=dict(self.control.aim_receipt or {}),
            failure=self.control.last_control_failure))
        return self.trace[-1]

    def native_flat_drive(self):
        """Use the real foreground physics with explicit flat-world I/O."""
        from test_port_0922_bot_runtime import _plain_attribute_factors
        battle = self.battle
        battle._local_matrix = None
        battle._local_descriptor = self.entity.typeDescriptor
        battle._local_factors_cache = _plain_attribute_factors(self.entity.typeDescriptor)
        battle._prepare_local_presentation(self.entity)
        self.body = battle._local_matrix
        battle._local_physics.update(rotationIsAroundCenter=False, trackCenter=1.5)
        battle._smoothed_drive_pitch = lambda *args: 0.
        battle._ensure_local_suspension_params = lambda *args: None
        battle._update_vertical_motion = lambda entity, position, yaw, dt: position
        battle._ground_pitch = lambda *args: 0.
        battle._apply_slope_slide = lambda position, yaw, dt, entity=None: position
        battle._resolve_local_tank_contacts = lambda entity, position, yaw, dt: position
        battle._contact_tanks = lambda *args, **kwargs: []
        # Rendering is not under test; pose integration and all rotation
        # guards, including capture-circle track arcs, remain real consumers.
        battle._update_local_presentation = lambda entity, dt: battle._local_position
        battle._destructible_pose_sweep = lambda *args, **kwargs: dict(status='clear', token=None)
        battle._destructibles = types.SimpleNamespace(
            native_replacement_bsp_active=lambda: False,
            _vehicle_body_bbox=lambda descriptor: ((-1.5, -.8, -3.5), (1.5, 2., 3.5)))


class TraverseHarness(object):
    def scene(self, **kwargs):
        scene = TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure(**kwargs)

    def advance_until(self, scene, predicate, limit=180):
        for unused in range(limit):
            scene.tick()
            if predicate():
                return
        self.fail('state did not complete: %r' % scene.trace[-3:])


class LimitedTraverseGeometryTests(TraverseHarness, unittest.TestCase):
    def test_completed_yaw_only_proof_survives_the_direct_comparison_boundary(self):
        for limits, bearing in (((-.2, .2), .7), ((-.2, .2), -.7),
                ((-.8, .8), 1.2), ((-.1, .6), -.5), ((0., 0.), .2)):
            with self.subTest(limits=limits, bearing=bearing):
                scene = self.scene(limits=limits, bearing=bearing)
                row = scene.evaluate()
                self.assertEqual(('hull_laying', 'clear', 'unknown'),
                    (row['mechanical'], row['line'], row['armor']))
                self.assertTrue(row['solution']['needs_hull'])
                self.assertFalse(row['solution']['reachable'])
                self.assertFalse(row['solution']['source_verified'])
                self.assertIsNone(scene.runtime.attack_policy.search_started)

    def test_wall_or_pitch_refusal_is_not_a_fireable_candidate(self):
        scene = self.scene()
        scene.world = [((-100., -100., 5.), (100., 100., 25.))]
        row = scene.evaluate()
        self.assertEqual('world_blocked', row['line'])
        self.assertNotEqual('passed', row['armor'])
        desc = descriptor(-.01, .01, yaw_limits=(-.2, .2))
        reach = mechanical_reach(desc, _direction(.7, .2), (0., 0., 0.))
        self.assertEqual('pitch_limit', reach['reason'])
        self.assertFalse(reach['needs_hull'])
        self.assertEqual('mechanical_limited', attack_policy._mechanical(
            desc, _direction(.7, .2), (0., 0., 0.))['status'])

    def test_full_or_already_in_arc_gun_does_not_acquire_a_hull_request(self):
        for limits in (None, (-.8, .8)):
            with self.subTest(limits=limits):
                scene = self.scene(limits=limits)
                row = scene.evaluate()
                self.assertEqual('reachable', row['mechanical'])
                self.assertFalse(row['solution']['needs_hull'])

    def test_spg_retains_the_complete_copied_artillery_owner(self):
        scene = self.scene(tag='SPG')
        scene.observe()
        decision = scene.runtime.attack_policy.update(scene.now)
        self.assertEqual(('unchanged', 'copied_artillery_owner'),
                         (decision['action'], decision['reason']))
        self.assertIsNone(scene.runtime.attack_policy.search_started)
        reach = mechanical_reach(scene.entity.typeDescriptor,
                                 _direction(.7, 0.), (0., 0., 0.))
        self.assertTrue(reach['needs_hull'])

    def test_unfinished_world_proof_cannot_admit_fire_or_global_failure(self):
        scene = self.scene()
        with mock.patch.object(attack_policy, 'WORLD_CHORDS_PER_FRONTIER', 0):
            row = scene.evaluate(complete=False)
        self.assertEqual('pending', row['line'])
        self.assertEqual('unknown', row['armor'])
        self.assertFalse(scene.fire())
        self.assertIsNone(scene.runtime.attack_policy.search_started)
        self.assertFalse(scene.battle._projectile_meta)

    def test_actual_hull_change_rebuilds_native_source_before_firing_proof(self):
        scene = self.scene()
        before = scene.evaluate()
        scene.set_hull(.58)
        after = scene.lay_current()
        self.assertNotEqual(before['pose_stamp'], after['pose_stamp'])
        self.assertEqual('reachable', after['mechanical'])
        self.assertEqual(before['solution']['point'], after['solution']['point'])
        self.assertTrue(scene.runtime.weapon.verified)
        self.assertTrue(scene.runtime.state['gun_aligned'])
        self.assertTrue(scene.fire(), scene.admission.receipt)
        self.assertEqual(1, scene.control.automatic_commits)

    def test_nonfiring_hull_proposal_cannot_pass_first_trigger_admission(self):
        scene = self.scene()
        row = scene.evaluate()
        scene.runtime.attack_policy._choose('aim', 'fixture_candidate', row)
        scene.runtime.weapon.target = row['target']
        scene.runtime.weapon.solution = row['solution']
        self.assertFalse(scene.fire())
        self.assertFalse(scene.battle._projectile_meta)
        self.assertEqual([20, 10], scene.battle._gun_state.ammo)

    def test_installed_asymmetric_and_zero_width_arcs_use_the_copied_hull_law(self):
        for limits, bearing, expected in (((-.2, .4), .5, 1),
                ((-.2, .4), -.3, -1), ((0., 0.), .015, 1),
                ((-.2, .4), .35, 0), ((-math.pi, math.pi), 1.2, 0)):
            with self.subTest(limits=limits, bearing=bearing):
                turn, throttle, aiming = driver.combat_hull_aim(
                    0., bearing, limits[0], limits[1], 0., 0., 'drive',
                    combat_mode='engage', movement_intent=False)
                self.assertEqual(expected, 1 if turn > 0. else -1 if turn < 0. else 0)
                self.assertEqual(bool(expected), aiming)
                self.assertEqual(0., throttle)

    def test_zero_width_gun_accepts_its_exact_transformed_heading(self):
        desc = descriptor(yaw_limits=(0., 0.))
        direction = shot_geometry.transform_vehicle_vector(_direction(0., 0.), .2, 0., 0.)
        reach = mechanical_reach(desc, direction, (.2, 0., 0.))
        self.assertTrue(reach['reachable'], reach)
        self.assertFalse(reach['needs_hull'])
        self.assertEqual('reachable', attack_policy._mechanical(desc, direction, (.2, 0., 0.))['status'])

    def test_yaw_precision_matches_native_solver_without_widening_pitch(self):
        tolerance = NATIVE_ANGLE_TOLERANCE
        for limits in ((0., 0.), (-.2, .4)):
            for edge, sign in ((limits[0], -1.), (limits[1], 1.)):
                for residual in (tolerance*.5, tolerance*2.):
                    with self.subTest(limits=limits, edge=edge, residual=residual):
                        desc = descriptor(yaw_limits=limits)
                        direction = _direction(edge + sign*residual, 0.)
                        reach = mechanical_reach(desc, direction, (0., 0., 0.))
                        native = attack_policy._mechanical(desc, direction, (0., 0., 0.))
                        self.assertEqual(residual < tolerance, reach['reachable'])
                        self.assertEqual(reach['reachable'], native['status'] == 'reachable')
        desc = descriptor(-.01, .01, yaw_limits=(0., 0.))
        reach = mechanical_reach(desc, _direction(tolerance*.5, .02), (0., 0., 0.))
        self.assertEqual('pitch_limit', reach['reason'])
        self.assertFalse(reach['needs_hull'])


class LimitedTraverseConsumerTests(TraverseHarness, unittest.TestCase):
    def test_loaded_casemate_and_limited_turret_clip_variants_reach_final_sender(self):
        for limits, tag, bearing in (((-.2, .2), 'AT-SPG', .7),
                ((-.8, .8), 'heavyTank', -1.2), ((0., 0.), 'AT-SPG', .015)):
            for clip in (1, 4):
                with self.subTest(limits=limits, tag=tag, clip=clip):
                    scene = self.scene(limits=limits, tag=tag, clip=clip, bearing=bearing)
                    self.advance_until(scene, lambda: bool(scene.runtime.state.get('hull_aiming')))
                    self.assertEqual(0., scene.battle._sender.forward)
                    solution = scene.runtime.attack_policy.decision['candidate']['solution']
                    residual = (solution['yaw']-scene.body.yaw+math.pi)%(2.*math.pi)-math.pi
                    self.assertGreater(scene.battle._sender.turn*residual, 0.)
                    self.assertEqual(0, scene.control.automatic_commits)
                    scene.trigger.assert_not_called()

    def test_capture_circle_can_lay_limited_gun_without_claiming_a_fireable_target(self):
        scene = self.scene(capture=True)
        self.advance_until(scene, lambda: bool(scene.runtime.state.get('hull_aiming')))
        self.assertEqual((0., 0., 0.), scene.position)
        self.assertEqual(0., scene.battle._sender.forward)
        self.assertGreater(scene.battle._sender.turn, 0.)
        self.assertIsNone(scene.runtime._mission)
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertIsNone(scene.runtime.attack_policy.search_started)

    def test_real_capture_order_reaches_track_arc_guard_at_circle_edge_and_inside(self):
        for edge in (False, True):
            with self.subTest(edge=edge):
                scene = self.scene(capture=True)
                scene.native_flat_drive()
                center = -29.999 if edge else 0.
                circle = scene.battle._last_snapshot['capture_bases']['2'][0]
                circle.update(z=center, radius=30.)
                request = dict(scene.control.identity(), id='capture', action='capture_base',
                    args={}, timeout_seconds=15., replace=True,
                    expires_at=scene.control.gateway.wall_clock()+15.)
                self.assertEqual('accepted', scene.control.gateway.submit(request, scene.now)['status'])
                self.advance_until(scene, lambda: bool(scene.runtime.state.get('hull_aiming')))
                self.assertEqual(((0., center), 30.), scene.control.last_order['capture_pivot_circle'])
                self.assertEqual(0., scene.battle._sender.forward)
                self.assertGreater(scene.battle._sender.turn, 0.)
                before = tuple(scene.battle._local_position), scene.battle._local_yaw
                scene.battle._drive_local_step(.04)
                after = tuple(scene.battle._local_position), scene.battle._local_yaw
                if edge:
                    self.assertEqual(before, after)
                else:
                    self.assertGreater(after[1], before[1])
                    self.assertGreater(after[0][2], before[0][2])
                self.assertEqual(0, scene.control.automatic_commits)


class MovingTraverseConsumerTests(TraverseHarness, unittest.TestCase):
    def test_pose_enters_arc_then_source_barrel_and_armor_gate_the_real_shot(self):
        for limits, tag, bearing, clip in (((-.2, .2), 'AT-SPG', .7, 1),
                ((-.2, .2), 'AT-SPG', .7, 4), ((-.8, .8), 'heavyTank', -1.2, 1),
                ((-.8, .8), 'heavyTank', -1.2, 4)):
            with self.subTest(limits=limits, clip=clip):
                scene = self.scene(limits=limits, tag=tag, bearing=bearing, clip=clip)
                initial = tuple(scene.battle._gun_state.ammo)
                self.advance_until(scene, lambda: scene.runtime.weapon.verified and
                    scene.runtime.attack_policy.decision['action'] == 'aim')
                self.assertTrue(any(row['hull_aiming'] for row in scene.trace))
                self.assertGreater(scene.body.yaw*bearing, 0.)
                self.assertEqual(initial, tuple(scene.battle._gun_state.ammo))
                self.assertFalse(scene.runtime.state['gun_aligned'])
                scene.trigger.assert_not_called()
                def unavailable():
                    raise RuntimeError('native target hit tester unavailable')
                for component in ('chassis', 'hull', 'turret', 'gun'):
                    getattr(scene.target.typeDescriptor, component).hitTester.on_hit = unavailable
                scene.rotator_enabled = True
                for unused in range(5):
                    scene.tick()
                self.assertEqual(initial, tuple(scene.battle._gun_state.ammo))
                self.assertFalse(scene.battle._projectile_meta)
                for component in ('chassis', 'hull', 'turret', 'gun'):
                    getattr(scene.target.typeDescriptor, component).hitTester.on_hit = None
                self.advance_until(scene, lambda: scene.control.automatic_commits == 1)
                self.assertEqual(initial[0]-1, scene.battle._gun_state.ammo[0])
                self.assertEqual(1, len(scene.battle._projectile_meta))
                self.assertEqual('committed', scene.admission.receipt['status'])

    def test_slow_zero_width_gun_can_finish_its_actual_pose_alignment(self):
        for clip in (1, 4):
            with self.subTest(clip=clip):
                scene = self.scene(limits=(0., 0.), clip=clip, bearing=.015, rate=.2)
                scene.rotator_enabled = True
                self.advance_until(scene, lambda: scene.control.automatic_commits == 1, limit=360)
                self.assertEqual(1, len(scene.battle._projectile_meta))

    def test_unchanged_native_pose_hands_failed_hull_laying_to_bounded_copied_navigation(self):
        scene = self.scene(rate=0.)
        self.advance_until(scene, lambda: bool(scene.runtime.state.get('hull_aiming')))
        admitted = scene.now
        # A clear proposed input is not physical progress. The existing Bot
        # angle recovery owns a bounded face/move attempt; repeatedly polling
        # the same candidate cannot retain a stationary turn forever.
        self.advance_until(scene, lambda: abs(scene.battle._sender.forward) > .01,
                           limit=150)
        self.assertLess(scene.now-admitted, 16.6)
        self.assertEqual(0., scene.body.yaw)
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertIsNone(scene.runtime.attack_policy.search_started)

    def test_limited_clip_trigger_commits_three_rounds_without_revalidating_tails(self):
        scene = self.scene(clip=6, burst=3)
        scene.rotator_enabled = True
        self.advance_until(scene, lambda: scene.control.automatic_commits == 1)
        self.assertTrue(any(row['hull_aiming'] for row in scene.trace))
        calls = scene.trigger.call_count
        with mock.patch.object(scene.control, 'authorize_trigger', side_effect=AssertionError('tail gate')):
            scene.control.stop('after_first_round')
            self.assertTrue(scene.advance(.1))
            self.assertTrue(scene.advance(.1))
        self.assertEqual(calls, scene.trigger.call_count)
        self.assertEqual([17, 10], scene.battle._gun_state.ammo)
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in scene.launches()])
        self.assertEqual(1, len({row['burst_group_seq'] for row in scene.launches()}))

    def test_target_replacement_during_world_query_cannot_publish_stale_fire(self):
        scene = self.scene()
        replaced = []
        def replace():
            scene.on_probe = None
            replaced.append(scene.vehicle(scene.target.id, (-30., 0., 30.), team=2))
        scene.on_probe = replace
        scene.tick()
        self.assertTrue(replaced)
        self.assertIs(scene.battle._server_entity(scene.target.id), replaced[-1])
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertFalse(scene.battle._projectile_meta)

    def test_pending_geometry_never_authorizes_a_first_trigger(self):
        scene = self.scene()
        with mock.patch.object(attack_policy, 'WORLD_CHORDS_PER_FRONTIER', 0):
            scene.tick()
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertFalse(scene.battle._projectile_meta)
        self.assertIsNone(scene.runtime.attack_policy.search_started)

    def test_world_blocked_candidates_do_not_acquire_a_firing_hull_owner(self):
        scene = self.scene(capture=True)
        scene.world = [((-100., -100., 5.), (100., 100., 25.))]
        for unused in range(25):
            scene.tick()
        self.assertTrue(scene.world_queries)
        self.assertFalse(any(row['hull_aiming'] for row in scene.trace))
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertIsNone(scene.runtime.attack_policy.search_started)

    def test_explicit_drive_retires_limited_hull_and_native_source_ownership(self):
        scene = self.scene()
        self.advance_until(scene, lambda: bool(scene.runtime.state.get('hull_aiming')))
        request = dict(scene.control.identity(), id='takeover', action='drive',
            args=dict(seconds=1., forward=1., turn=0.), timeout_seconds=15., replace=True,
            expires_at=scene.control.gateway.wall_clock()+15.)
        receipt = scene.control.gateway.submit(request, scene.now)
        self.assertEqual('accepted', receipt['status'])
        scene.tick()
        self.assertFalse(scene.runtime.active)
        self.assertEqual((1., 0., False), scene.trace[-1]['sender'])
        self.assertIsNone(scene.runtime.weapon.bound_source)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_stop_during_native_world_query_cannot_restore_turn_or_source(self):
        scene = self.scene()
        stopped = []
        def stop():
            scene.on_probe = None
            scene.control.stop('test_stop_during_native_query')
            stopped.append(True)
        scene.on_probe = stop
        scene.tick()
        self.assertTrue(stopped)
        self.assertFalse(scene.control.active)
        self.assertIsNone(scene.runtime.weapon.bound_source)
        self.assertEqual((0., 0.), scene.trace[-1]['sender'][:2])
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertFalse(scene.battle._projectile_meta)

    def test_descriptor_or_gun_replacement_retires_old_penetration_evidence(self):
        for changed in ('descriptor', 'gun'):
            with self.subTest(changed=changed):
                scene = self.scene(limits=(-.8, .8))
                scene.lay_current()
                before = scene.candidate['pose_stamp']
                desc = copy.deepcopy(scene.entity.typeDescriptor)
                desc.gun.turretYawLimits = (-.1, .1)
                if changed == 'descriptor':
                    scene.entity.typeDescriptor = desc
                else:
                    scene.battle._gun_state = gun_mechanics.GunState(desc,
                        ammo_layout={101: 20, 102: 10})
                self.assertFalse(scene.fire())
                self.assertFalse(scene.battle._projectile_meta)
                if changed == 'descriptor':
                    self.assertNotEqual(before, scene.evaluate()['pose_stamp'])


if __name__ == '__main__':
    unittest.main()
