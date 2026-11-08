"""Siege engagement through the complete foreground/native input consumers.

The fixture exposes descriptor pairs, rigid body/barrel observations, flat
support, BSP/component collision and a controllable native mode echo.  The
player policy, actual enabled-mode actuator input, copied control loop, aim-source
lease, real track_world mailbox, hydraulic actuator, gun accounting and first
trigger admission remain production code.  Synthetic native observations do
not establish Windows #1513 rendering, timing or physical-client acceptance.
"""
import copy
import math
from types import SimpleNamespace
import unittest
from unittest import mock

import test_player_fire_admission_complete as fire_tests
from gui.mods.offline_lan_0922 import (
    ballistics, gun_mechanics, gun_pitch_limits, shot_geometry, siege_mechanics)
from gui.mods.offline_lan_0922.player_control import PlayerControl


def pitch_limits(low, high):
    return dict(absolute=(low, high),
        minPitch=((0., low), (2. * math.pi, low)),
        maxPitch=((0., high), (2. * math.pi, high)))


class SiegeScene(fire_tests.AutomaticFireScene):
    """An observed static-gun fixture with independently acknowledged mode."""

    def configure(self, enabled=True, clip=1, enabled_pitch=(-.035, .035),
                  hydraulic_center=0.):
        self.control.close()
        travel = copy.deepcopy(self.entity.typeDescriptor)
        travel.name = travel.type.name = 'sweden:S22_Strv_S1'
        travel.type.tags = ('AT-SPG',)
        travel.hasSiegeMode = True
        travel.isYawHullAimingAvailable = True
        travel.isPitchHullAimingAvailable = True
        travel.gun.pitchLimits = pitch_limits(0., 0.)
        travel.gun.turretYawLimits = (-.05, .05)
        travel.gun.clip = (clip, .5)
        travel.gun.burst = (1, .1)
        travel.gun.staticPitch = travel.gun.staticTurretYaw = None
        travel.type.hullAimingParams = dict(pitch=dict(
            isAvailable=True, isEnabled=False,
            wheelsCorrectionAngles=dict(pitchMin=-.25, pitchMax=.25),
            wheelsCorrectionSpeed=.2, wheelCorrectionCenterZ=hydraulic_center))
        enabled_descriptor = copy.deepcopy(travel)
        enabled_descriptor.gun.pitchLimits = pitch_limits(*enabled_pitch)
        enabled_descriptor.type.hullAimingParams['pitch']['isEnabled'] = True
        # Both observed native composites retain the installed immutable pair.
        # The suite separately tests descriptor switches with a live request.
        for descriptor in (travel, enabled_descriptor):
            descriptor.defaultVehicleDescr = travel
            descriptor.siegeVehicleDescr = enabled_descriptor
        self.travel_descriptor, self.enabled_descriptor = travel, enabled_descriptor
        self.entity.typeDescriptor = enabled_descriptor if enabled else travel
        self.entity.siegeState = siege_mechanics.ENABLED if enabled else siege_mechanics.DISABLED
        battle = self.battle
        battle._local_descriptor = travel
        battle._runtime.constants.VEHICLE_SIEGE_STATE = SimpleNamespace(
            DISABLED=0, SWITCHING_ON=1, ENABLED=2, SWITCHING_OFF=3)
        battle._runtime.math.Matrix = fire_tests.SpatialPose
        self.body = fire_tests.SpatialPose()
        self.flat_body = fire_tests.SpatialPose()
        battle._local_siege_flat_body_matrix = self.flat_body
        battle._local_siege_aim_matrix = fire_tests.SpatialPose()
        battle._local_siege_aim_pitch = 0.
        battle._local_siege_aim_center_z = 0.
        battle._local_terrain_pitch = 0.
        battle._local_pitch = battle._local_roll = 0.
        battle._local_speed = battle._local_turn_speed = 0.
        battle._local_ground_plane = dict(pitch=0., roll=0.)
        battle._spawn_planner = SimpleNamespace(capture_bases={
            '1': [dict(x=0., z=-45., radius=6.)],
            '2': [dict(x=0., z=45., radius=6.)]})
        battle.local_pose = lambda: ((0., 0., 0.), self.body.yaw)
        battle._local_body_pose = lambda: self.flat_body
        battle._local_stabilised_pose = lambda: self.body
        battle._local_matrix = self.flat_body
        battle._local_pose_matrix = self.body
        battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        battle._gun_state = gun_mechanics.GunState(
            self.entity.typeDescriptor, ammo_layout={101: 20, 102: 10})
        battle._gun_state.reload_time = 0.
        battle._gun_state.clip = clip
        record = battle._records['player:1']
        record.update(vehicle=travel.type.name, presented_siege_state=self.entity.siegeState)
        record['state'].update(siege_state=self.entity.siegeState,
                               siege_time_left_ms=0, vehicle=travel.type.name)
        self.native_aim_echoes = []
        battle._binding = SimpleNamespace(
            update_vehicle_aim=lambda *args: self.native_aim_echoes.append(args))
        self.update_barrel_observation()
        self.pose(self.target, (0., 12., 100.))
        self.control = PlayerControl(battle, ('drive', 'fire'), notify=lambda unused: None)
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: True
        self.control.gateway.emit = self.control.emit_result
        battle._player_control = self.control
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime = self.control.runtime
        self.admission = self.control._admission()
        self.trace = []
        return self

    def get_angles(self, descriptor, body, previous, point):
        """Native inverse observation, using the supplied actual body matrix."""
        origin, unused = shot_geometry.shot_origin_and_direction(
            descriptor, tuple(body.translation), body.yaw, body.pitch, body.roll,
            previous[0], previous[1])
        shot = self.battle._gun_state.shots[self.battle._gun_state.shot_index]
        roots = ballistics.ballistic_solutions(origin, tuple(point), shot.speed, shot.gravity)
        if not roots:
            raise ValueError('unreachable observed native source')
        pitch = roots[0][0]
        yaw = math.atan2(point[0] - origin[0], point[2] - origin[2])
        direction = (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                     math.cos(yaw) * math.cos(pitch))
        return shot_geometry.world_direction_to_local_gun_angles(
            direction, body.yaw, body.pitch, body.roll)

    def update_barrel_observation(self):
        rotator = self.battle._avatar.gunRotator
        self.origin, self.direction = shot_geometry.shot_origin_and_direction(
            self.entity.typeDescriptor, tuple(self.body.translation),
            self.body.yaw, self.body.pitch, self.body.roll,
            float(rotator.turretYaw), float(rotator.gunPitch))

    def actuate_native_source(self, seconds):
        """Expose native mailbox/actuator feedback, not a policy decision."""
        rotator = self.battle._avatar.gunRotator
        source = rotator.shotPointSourceFunctor
        point = source() if callable(source) else None
        if point is None:
            return
        self.assertTrue(self.battle._sender.send_avatar_input(
            self.entity.id, 'track_world', dict(point=point)))
        self.battle._update_local_hull_aiming(self.entity, seconds)
        self.body = fire_tests.SpatialPose(self.flat_body)
        self.body.preMultiply(self.battle._local_siege_aim_matrix)
        self.battle._local_pose_matrix = self.body
        self.entity.matrix = self.body
        yaw, pitch = self.get_angles(self.entity.typeDescriptor, self.body,
            (float(rotator.turretYaw), float(rotator.gunPitch)), point)
        low, high = self.entity.typeDescriptor.gun.turretYawLimits
        yaw = max(low, min(high, yaw))
        low, high = gun_pitch_limits.calc_pitch_limits(
            yaw, self.entity.typeDescriptor.gun.pitchLimits)
        rotator.turretYaw, rotator.gunPitch = yaw, max(low, min(high, pitch))
        self.update_barrel_observation()

    def tick(self, seconds=.1, actuate=True):
        self.fixture.now += seconds
        if actuate:
            self.actuate_native_source(seconds)
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.trace.append(dict(now=self.now,
            pitch=self.battle._local_siege_aim_pitch,
            policy=dict(self.runtime.attack_policy.status()),
            position=dict(self.runtime.firing_position.receipt),
            mode=self.entity.siegeState,
            order=dict(self.control.last_order),
            aim_verified=self.runtime.weapon.verified,
            failure=self.control.last_control_failure))
        self.assertIsNone(self.control.last_control_failure, self.trace[-1])
        return self.trace[-1]

    def echo_mode(self, state, sequence):
        """The native mode/descriptor/sequence observation arrives atomically."""
        self.entity.typeDescriptor = (self.enabled_descriptor if state == siege_mechanics.ENABLED
                                      else self.travel_descriptor)
        self.entity.siegeState = state
        record = self.battle._records['player:1']
        record['presented_siege_state'] = state
        row = dict(record['state'], siege_state=state, input_seq=sequence,
                   siege_time_left_ms=500 if state in (1, 3) else 0)
        record['state'] = row
        self.battle._apply_siege_state(record, row)
        self.update_barrel_observation()
        self.observe()


class SiegeEngagementTests(unittest.TestCase):
    def scene(self, **kwargs):
        scene = SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure(**kwargs)

    def advance_until(self, scene, predicate, limit=120, actuate=True):
        for unused in range(limit):
            scene.tick(actuate=actuate)
            if predicate():
                return
        self.fail('Siege consumer did not complete: %r' % [dict(
            now=row['now'], pitch=row['pitch'], mode=row['mode'],
            action=row['policy']['action'], reason=row['policy']['reason'],
            mechanical=row['policy'].get('mechanical'), position=row['position'],
            order=row['order']) for row in scene.trace[-3:]])

    def test_enabled_hydraulics_publish_motion_only_then_require_actual_proof(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        before = tuple(gun.ammo)
        self.advance_until(scene, lambda: scene.runtime.weapon.motion_point is not None and
            scene.runtime.siege_aim_candidate() is not None, actuate=False)
        motion = scene.runtime.siege_aim_candidate()
        self.assertTrue(motion['solution']['needs_hydraulic'])
        self.assertFalse(motion['solution']['reachable'])
        self.assertFalse(motion['solution']['source_verified'])
        self.assertIsNone(scene.runtime.weapon.source_point)
        self.assertFalse(scene.runtime.weapon.verified)
        self.assertFalse(scene.runtime.state['gun_aligned'])
        self.assertIsNone(scene.runtime.current_attack_candidate(
            scene.runtime.state, motion['target']))
        self.assertEqual(0., scene.battle._local_siege_aim_pitch)
        self.assertEqual(before, tuple(gun.ammo))
        self.assertFalse(scene.launches())
        self.advance_until(scene, lambda: bool(scene.launches()))
        self.assertTrue(scene.native_aim_echoes)
        self.assertLess(scene.battle._local_siege_aim_pitch, 0.)
        self.assertTrue(scene.runtime.weapon.verified)
        self.assertEqual(before[0] - 1, gun.ammo[0])
        self.assertEqual(1, len(scene.launches()))
        committed = scene.runtime.attack_policy.trigger
        self.assertIsNone(committed)
        self.assertTrue(any(row['policy']['mechanical'] == 'reachable'
                            for row in scene.trace))

    def test_motion_only_source_is_released_when_target_is_no_longer_visible(self):
        scene = self.scene()
        self.advance_until(scene, lambda: scene.runtime.siege_aim_candidate() is not None,
                           actuate=False)
        previous = tuple(scene.runtime.weapon.motion_point)
        scene.battle._records['bot:42']['spot_visible'] = False
        scene.tick(actuate=False)
        self.assertIsNone(scene.runtime.siege_aim_candidate())
        self.assertNotEqual(previous, scene.runtime.weapon.motion_point)
        self.assertFalse(scene.runtime.state['gun_aligned'])
        self.assertFalse(scene.launches())

    def test_zero_pitch_gun_reaches_actual_proof_with_native_pivot_translation(self):
        # An exact static gun cannot absorb even a small flat/actual-origin
        # discrepancy. Drive the genuine hydraulic mailbox and actuator rather
        # than assigning the desired correction to the observed body.
        for center in (0., 1.5, -1.5):
            with self.subTest(hydraulic_center=center):
                scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=center)
                self.advance_until(scene, lambda: scene.runtime.siege_aim_candidate()
                                   is not None, actuate=False)
                self.assertFalse(scene.runtime.weapon.verified)
                self.advance_until(scene, lambda: bool(scene.launches()))
                self.assertEqual(1, len(scene.launches()))
                self.assertTrue(scene.runtime.weapon.verified)
                self.assertEqual(0., scene.battle._avatar.gunRotator.gunPitch)
                self.assertNotEqual(0., scene.battle._local_siege_aim_pitch)
                if center:
                    self.assertNotEqual((0., 0., 0.), tuple(scene.body.translation))
                scene.doCleanups()

    def test_settled_static_gun_does_not_oscillate_between_native_source_owners(self):
        scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5, clip=3)
        self.advance_until(scene, lambda: bool(scene.launches()))
        episodes = scene.runtime.firing_position.sequence
        pitches = []
        for unused in range(12):
            # The owner of physical reload time is the actual GunState, not
            # the copied observation. Only the native clock is advanced here.
            scene.battle._gun_state.tick(.1, True, 0., 0., 0.,
                                         scene.entity.typeDescriptor)
            scene.tick()
            pitches.append(scene.battle._local_siege_aim_pitch)
        self.assertGreaterEqual(len(scene.launches()), 2)
        self.assertEqual(episodes, scene.runtime.firing_position.sequence,
                         'An unchanged reachable target must not restart ordinary positioning')
        self.assertLessEqual(max(pitches) - min(pitches), .00002,
                             'Flat hydraulic and actual-gun sources must settle together')

    def assert_native_hydraulics_follow_manual_point(self, scene):
        # Read the real consumer with a distinct live native mailbox value.
        # A leaked automatic upper target would keep pitching upward instead.
        point = (0., -10., 100.)
        before = scene.battle._local_siege_aim_pitch
        self.assertTrue(scene.battle._sender.send_avatar_input(
            scene.entity.id, 'track_world', dict(point=point)))
        scene.battle._update_local_hull_aiming(scene.entity, .1)
        self.assertGreater(scene.battle._local_siege_aim_pitch, before + .009)

    def test_manual_source_and_stop_revoke_the_automatic_hydraulic_lease(self):
        for release in ('manual_source', 'stop'):
            with self.subTest(release=release):
                scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5)
                runtime = scene.runtime
                self.advance_until(scene, lambda: runtime.hydraulic_aim_point(scene.entity)
                                   is not None, actuate=False)
                if release == 'manual_source':
                    manual = lambda: scene.battle._vector((0., -10., 100.))
                    scene.battle._avatar.gunRotator.shotPointSourceFunctor = manual
                    self.assertFalse(runtime.weapon.owned())
                else:
                    scene.control.stop('manual')
                    self.assertFalse(runtime.active)
                # No control tick is allowed to clear a leaked lease for us.
                self.assertIsNone(runtime.hydraulic_aim_point(scene.entity))
                self.assert_native_hydraulics_follow_manual_point(scene)
                self.assertFalse(scene.launches())
                scene.doCleanups()

    def test_stale_target_or_flat_support_cannot_drive_automatic_hydraulics(self):
        for change in ('target_pose', 'flat_support', 'hidden_target'):
            with self.subTest(change=change):
                scene = self.scene(enabled_pitch=(0., 0.), hydraulic_center=1.5)
                runtime = scene.runtime
                self.advance_until(scene, lambda: runtime.hydraulic_aim_point(scene.entity)
                                   is not None, actuate=False)
                if change == 'target_pose':
                    scene.pose(scene.target, (0., 20., 100.))
                elif change == 'flat_support':
                    # The observed support frame changes, not hydraulic slew.
                    scene.flat_body.setRotateYPR((.1, 0., 0.))
                    scene.flat_body.translation = (2., 0., 0.)
                else:
                    scene.battle._records['bot:42']['spot_visible'] = False
                    scene.observe()
                self.assertIsNone(runtime.hydraulic_aim_point(scene.entity))
                self.assert_native_hydraulics_follow_manual_point(scene)
                self.assertFalse(scene.launches())
                scene.doCleanups()

    def test_travel_zero_pitch_enters_before_point_proof_and_actual_lay_waits_echo(self):
        scene = self.scene(enabled=False)
        runtime = scene.runtime
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        request = runtime._siege_pending
        self.assertTrue(request['enabled'])
        self.assertIsNone(runtime._siege_aim_candidate)
        self.assertIsNone(runtime.siege_aim_candidate())
        self.assertIsNone(runtime.firing_position.episode)
        self.assertEqual(0, runtime.firing_position.sequence)
        sequence = request['sequence']
        self.assertFalse(scene.launches())
        scene.echo_mode(siege_mechanics.SWITCHING_ON, sequence)
        for unused in range(3):
            scene.tick(actuate=False)
            self.assertIs(request, runtime._siege_pending)
            self.assertIsNone(runtime.firing_position.episode)
            self.assertEqual(0, runtime.firing_position.sequence)
            self.assertFalse(runtime._siege_request(False))
            self.assertFalse(scene.launches())
        scene.echo_mode(siege_mechanics.ENABLED, sequence)
        self.assertIsNone(runtime._siege_pending)
        enabled_at = scene.now
        self.advance_until(scene, lambda: runtime.siege_aim_candidate() is not None,
                           actuate=False)
        self.assertEqual(1, runtime.firing_position.sequence)
        self.assertGreaterEqual(runtime.firing_position.episode['started_at'], enabled_at)
        self.assertEqual('native_lay', runtime.firing_position.episode['phase'])
        self.assertFalse(scene.launches())
        self.advance_until(scene, lambda: bool(scene.launches()))
        self.assertEqual(1, len(scene.launches()))

    def test_synthetic_siege_magazine_uses_same_native_mode_owner(self):
        # No currently shipped vehicle is required for this independent axes
        # contract: loading structure cannot erase the native mode gate.
        scene = self.scene(enabled=False, clip=3)
        runtime, gun = scene.runtime, scene.battle._gun_state
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        self.assertEqual(3, runtime.attack_policy.frame['clip_size'])
        self.assertTrue(runtime._siege_pending['enabled'])
        self.assertIsNone(runtime._siege_aim_candidate)
        self.assertIsNone(runtime.firing_position.episode)
        self.assertEqual(3, gun.clip)
        self.assertFalse(scene.launches())
        self.assertIsNone(runtime.attack_policy.search_authority)
        sequence = runtime._siege_pending['sequence']
        scene.echo_mode(siege_mechanics.SWITCHING_ON, sequence)
        scene.tick(actuate=False)
        self.assertEqual(3, gun.clip)
        scene.echo_mode(siege_mechanics.ENABLED, sequence)
        self.advance_until(scene, lambda: bool(scene.launches()))
        self.assertEqual(2, gun.clip)
        self.assertEqual(1, len(scene.launches()))
        self.assertFalse(any(row['policy']['action'] == 'reload_clip'
                             for row in scene.trace))

    def test_visible_contact_loss_and_reappearance_run_native_exit_and_entry(self):
        scene = self.scene()
        runtime = scene.runtime
        self.advance_until(scene, lambda: runtime.siege_aim_candidate() is not None,
                           actuate=False)
        scene.battle._records['bot:42']['spot_visible'] = False
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        leaving = runtime._siege_pending
        self.assertFalse(leaving['enabled'])
        self.assertIsNone(runtime.siege_aim_candidate())
        self.assertFalse(scene.launches())
        scene.echo_mode(siege_mechanics.SWITCHING_OFF, leaving['sequence'])
        scene.tick(actuate=False)
        scene.echo_mode(siege_mechanics.DISABLED, leaving['sequence'])
        scene.tick(actuate=False)
        self.assertIsNone(runtime._siege_pending)
        scene.battle._records['bot:42']['spot_visible'] = True
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        entering = runtime._siege_pending
        self.assertTrue(entering['enabled'])
        self.assertGreater(entering['sequence'], leaving['sequence'])
        self.assertIsNone(runtime._siege_aim_candidate)
        self.assertFalse(scene.launches())
        scene.echo_mode(siege_mechanics.SWITCHING_ON, entering['sequence'])
        scene.tick(actuate=False)
        scene.echo_mode(siege_mechanics.ENABLED, entering['sequence'])
        self.advance_until(scene, lambda: bool(scene.launches()))
        self.assertEqual(1, len(scene.launches()))

    def test_attack_without_destination_engages_but_return_base_takes_route(self):
        scene = self.scene(enabled=False)
        runtime = scene.runtime
        self.assertEqual('running', runtime.set_mission('attack', {})['status'])
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        self.assertEqual('team_attack', runtime.firing_position.task_order['combat_mode'])
        entering = runtime._siege_pending
        self.assertTrue(entering['enabled'])
        self.assertIsNone(runtime._siege_aim_candidate)
        scene.echo_mode(siege_mechanics.ENABLED, entering['sequence'])
        self.advance_until(scene, lambda: runtime.firing_position.active, actuate=False)
        self.assertEqual('running', runtime.set_mission('return_base', {})['status'])
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        leaving = runtime._siege_pending
        self.assertFalse(leaving['enabled'])
        self.assertEqual('team_return_base', runtime.firing_position.task_order['combat_mode'])
        self.assertFalse(runtime.firing_position.active)
        self.assertFalse(scene.launches())
        scene.echo_mode(siege_mechanics.DISABLED, leaving['sequence'])
        scene.tick(actuate=False)
        self.assertEqual((0., 0., -45.), runtime._mission['destination'])
        self.assertFalse(scene.control.last_order['fire_allowed'])
        self.assertIsNone(runtime.weapon.target)
        self.assertIsNone(runtime.weapon.solution)
        self.assertFalse(runtime.state['gun_aligned'])
        self.assertIsNone(runtime.hydraulic_aim_point(scene.entity))
        self.assertIsNone(runtime._siege_pending)

    def test_original_protected_task_cannot_be_stopped_by_attack_overlay(self):
        # Substitute only the already-admitted strategic task at its public
        # order boundary. Point policy, local lifetime, driver, late targeting
        # and native mode transaction remain real consumers.
        for mode in ('base_defense', 'magazine_reload_retreat'):
            with self.subTest(mode=mode):
                scene = self.scene()
                runtime = scene.runtime
                self.advance_until(scene, lambda: runtime.firing_position.active,
                                   actuate=False)
                runtime._mission = None
                original = runtime.planner.build_orders

                def admitted_task(*args, **kwargs):
                    result = original(*args, **kwargs)
                    for order in result['orders']:
                        if order['id'] == runtime.actor_id:
                            order.update(combat_mode=mode, move_position=dict(x=-30., y=0., z=-30.),
                                face_position=dict(x=-30., y=0., z=-30.),
                                throttle_override=None, route_join=False, parking_phase=None)
                    return result

                with mock.patch.object(runtime.planner, 'build_orders', side_effect=admitted_task):
                    runtime._strategic_due = 0.
                    self.advance_until(scene, lambda: runtime._siege_pending is not None,
                                       actuate=False)
                    self.assertFalse(runtime._siege_pending['enabled'])
                    self.assertEqual(mode, runtime.firing_position.task_order['combat_mode'])
                    self.assertEqual(mode, runtime.engine._server_orders[runtime.actor_id]['combat_mode'])
                    self.assertEqual((-30., 0., -30.),
                        runtime.engine._server_orders[runtime.actor_id]['move_position'])
                    self.assertFalse(runtime.firing_position.active)
                    self.assertFalse(scene.control.last_order['fire_allowed'])
                    # The unchanged hull-forward rest may still bind a
                    # verified native input; it is not an enemy/fire lease.
                    self.assertIsNone(runtime.weapon.target)
                    self.assertIsNone(runtime.weapon.solution)
                    self.assertFalse(runtime.state['gun_aligned'])
                    self.assertIsNone(runtime.hydraulic_aim_point(scene.entity))
                    self.assertFalse(scene.launches())
                scene.doCleanups()

    def test_synthetic_siege_clip_accepted_cover_reload_owns_exit_not_generic_cover(self):
        # This tests the reload consumer boundary: a policy instruction asks
        # for early reload; the unchanged original cover law supplies its own
        # movement/arrival result. Mode ownership follows that admitted lease.
        for cover_x, expected_mode in ((20., 'take_cover'), (0., 'cover_hold')):
            with self.subTest(mode=expected_mode):
                scene = self.scene(clip=3)
                runtime = scene.runtime
                self.advance_until(scene, lambda: runtime.siege_aim_candidate() is not None,
                                   actuate=False)
                selected = runtime.siege_aim_candidate()
                runtime.attack_policy.decision = dict(action='reload_clip', early_reload=True,
                    reason='current_clip_all_armour_failed', candidate=selected, shell_index=1)
                runtime._mission = None
                planner = runtime.planner
                cover = dict(id='fixture-cover', position=dict(x=cover_x, y=0., z=0.),
                             peek_position=dict(x=cover_x, y=0., z=6.))
                phase = dict(phase='approach', last_progress_at=scene.now,
                             phase_started_at=scene.now, best_distance=abs(cover_x))
                planner._cover_states[runtime.actor_id] = phase
                original_order = dict(runtime.firing_position.task_order)
                with mock.patch.object(planner, '_capable', return_value=True), \
                        mock.patch.object(planner, '_cover_candidate', return_value=(cover, phase)):
                    result = runtime._reload_order(original_order, scene.now)
                    self.assertEqual(expected_mode, result['combat_mode'])
                    self.assertTrue(runtime._reload_retreat['navigation_owned'])
                    self.assertFalse(runtime.firing_position.navigation_owns(result, task_only=True))
                    self.assertTrue(runtime.firing_position.navigation_owns(result))
                    self.assertFalse(runtime.siege_desired(runtime.state, result, selected['target']))
                    self.assertFalse(result['fire_allowed'])
                    self.assertEqual(3, scene.battle._gun_state.clip)
                    self.assertFalse(scene.launches())
                scene.doCleanups()

    def test_completed_navigation_recovery_hands_off_then_exit_ack_fences_old_owners(self):
        scene = self.scene()
        runtime, engine = scene.runtime, scene.runtime.engine
        scene.pose(scene.target, (0., 6., 40.))
        scene.world = [((-50., -10., 15.), (50., 40., 25.))]
        # Translation and hydraulic feedback deliberately remain stationary.
        # Native laying first exhausts its original progress allowance; the
        # original driver then completes its own bounded local-stuck recovery.
        # No timeout/terminal/policy result is injected.
        self.advance_until(scene, lambda: runtime.firing_position.suppressed,
                           limit=160, actuate=False)
        owner = runtime.firing_position
        terminal = owner.terminal
        self.assertEqual('navigation_recovery_stalled', terminal['reason'])
        self.assertEqual('local_stuck', terminal['evidence']['reason'])
        self.assertEqual('driver_elapsed_seconds', terminal['evidence']['clock_basis'])
        self.assertGreater(terminal['evidence']['completed_count'], 0)
        self.assertGreater(terminal['evidence']['completed_clock'], terminal['evidence']['at'])
        self.assertTrue(any(row['position'].get('reason') == 'native_pivot_stalled'
                            and row['order']['movement_intent'] for row in scene.trace))
        self.assertFalse(terminal['navigation_owned'])
        self.assertEqual('handoff', terminal['phase'])
        self.assertIsNone(runtime.attack_policy.search_started)
        self.assertIsNone(runtime.attack_policy.search_authority)
        self.assertFalse(owner.exit_required)
        self.assertFalse(scene.launches())
        self.advance_until(scene, lambda: runtime._siege_pending is not None,
                           actuate=False)
        self.assertTrue(terminal['navigation_owned'])
        self.assertTrue(owner.exit_required)
        request = runtime._siege_pending
        self.assertFalse(request['enabled'])
        sequence = request['sequence']
        scene.echo_mode(siege_mechanics.SWITCHING_OFF, sequence)
        for unused in range(5):
            scene.tick(actuate=False)
            self.assertIs(request, runtime._siege_pending)
            self.assertIs(terminal, owner.terminal)
            self.assertTrue(owner.exit_required)
            self.assertFalse(runtime._siege_request(True))
            self.assertEqual(0., scene.control.last_order['throttle'])
            self.assertEqual(0., scene.control.last_order['turn'])
            self.assertTrue(scene.control.last_order['brake'])
            self.assertIsNone(scene.control.last_order['target_id'])
            self.assertIsNone(scene.control.last_order['aim_position'])
            self.assertIsNone(runtime.siege_aim_candidate())

        # A stable-looking descriptor is insufficient before the sequence
        # belonging to this native transaction has actually been observed.
        scene.echo_mode(siege_mechanics.DISABLED, sequence - 1)
        scene.tick(actuate=False)
        self.assertIs(request, runtime._siege_pending)
        self.assertTrue(owner.exit_required)
        self.assertEqual(0., scene.control.last_order['throttle'])
        self.assertIsNone(scene.control.last_order['target_id'])
        scene.echo_mode(siege_mechanics.DISABLED, sequence)
        scene.tick(actuate=False)
        self.assertIsNone(runtime._siege_pending)
        self.assertFalse(owner.exit_required)
        self.assertTrue(owner.suppressed)
        self.assertEqual('route', owner.terminal['phase'])
        self.assertIsNone(scene.control.last_order['target_id'])
        self.assertFalse(scene.control.last_order['fire_allowed'])
        self.assertNotEqual((0., 0., 0.), scene.control.last_order['move_position'])

        # Delayed copied owners receive a stale attack intent after handoff.
        # Their real wrapper methods must neither create a lease nor replace
        # the task route. The input is not a fake terminal or fake decision.
        target = runtime._targets[0]
        stale = dict(runtime._last_order, combat_mode='engage',
                     target_id=target['id'], move_position=(0., 0., 0.),
                     throttle_override=0.)
        targets = {target['id']: target}
        before = dict(stale)
        result = engine._gun_angle_order(runtime.state, stale, targets, scene.now,
                                        lambda yaw, distance: True)
        self.assertEqual(before, result)
        self.assertNotIn('_gun_angle_adjustment', runtime.state)
        result, expired = engine._friendly_reposition_order(
            runtime.state, targets, scene.now)
        self.assertIsNone(result)
        self.assertFalse(expired)
        self.assertFalse(engine._mark_friendly_reposition(runtime.state, stale, target,
            dict(fire_seq=1, shot_yaw=0.),
            dict(blocker_kind='bot', blocker_id=43, blocker_team=1,
                 blocker_position=(0., 0., 10.), blocker_radius=3.), scene.now))
        self.assertNotIn(runtime.actor_id, engine._friendly_repositions)
        result = engine._rear_laying_order(runtime.state, stale, targets, scene.now)
        self.assertEqual(before, result)
        self.assertFalse(runtime.state.get('_rear_aim_episode'))
        for unused in range(5):
            scene.tick(actuate=False)
            self.assertIs(terminal, owner.terminal)
            self.assertIsNone(runtime._siege_pending)
            self.assertIsNone(scene.control.last_order['target_id'])
        self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
