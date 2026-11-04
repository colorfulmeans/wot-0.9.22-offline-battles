"""Real command receipts with explicit native point-source/rotation boundaries.

The rotator fixture does not instantly aim when a source is installed. Tests
advance the observed native angles separately; this is not a live-client test.
"""
import copy
import math
import types
import unittest
from unittest import mock

import test_player_control_completion as completion
from test_player_weapon_migration import aiming_scene, descriptor

from gui.mods.offline_lan_0922 import shot_geometry
from gui.mods.offline_lan_0922.player_control.manual_aim import (
    ManualAim, MAX_VISIBLE_TARGETS, RELEASE_STAGE, SOURCE_ATTRIBUTE)


class ObservedRotator(object):
    def __init__(self, source, mode=False):
        setattr(self, SOURCE_ATTRIBUTE, source)
        self._mode = mode
        self.turretYaw = self.gunPitch = 0.
        self.source_before = self.source_after = self.mode_before = None
        self.writes = []

    @property
    def shotPointSourceFunctor(self):
        return getattr(self, SOURCE_ATTRIBUTE)

    @shotPointSourceFunctor.setter
    def shotPointSourceFunctor(self, value):
        self.writes.append(('source', value))
        if self.source_before is not None:
            self.source_before(value)
        setattr(self, SOURCE_ATTRIBUTE, value)
        if self.source_after is not None:
            self.source_after(value)

    @property
    def clientMode(self):
        return self._mode

    @clientMode.setter
    def clientMode(self, value):
        self.writes.append(('mode', value))
        if self.mode_before is not None:
            self.mode_before(value)
        self._mode = value


class ManualAimHarness(object):
    def setUp(self):
        self.fixture = completion.ForegroundCompletionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.control = self.fixture.control(features=())
        self.owner = self.control.owner
        native, self.target, self.shot, self.body = aiming_scene()
        self.target.position = (20., 0., 100.)
        own = native._server_entity(1)
        own.isAlive = lambda: self.fixture.alive[0]
        own.health = 1000
        self.entities = {1: own, 42: self.target}
        self.owner._server_entity = lambda identity: self.entities.get(identity)
        self.owner._runtime = native._runtime
        self.owner._vector = native._vector
        self.owner._local_stabilised_pose = native._local_stabilised_pose
        self.owner._collision_shape = native._collision_shape
        self.owner._gun_state.shots = [self.shot]
        self.old_source = lambda: (91., 92., 93.)
        self.rotator = ObservedRotator(self.old_source)
        self.owner._avatar.gunRotator = self.rotator
        self.owner._avatar.autoAim = mock.Mock()
        self.owner._avatar.shoot = mock.Mock()
        self.owner._avatar._PlayerAvatar__autoAimVehID = 77
        self.owner._records = {42: dict(ready=True, engine_id=42, state=dict(team=2),
                                       spot_visible=True, tombstone=False)}
        self.ray_override = None

        def ray():
            direction = (math.sin(self.rotator.turretYaw)*math.cos(self.rotator.gunPitch),
                         -math.sin(self.rotator.gunPitch),
                         math.cos(self.rotator.turretYaw)*math.cos(self.rotator.gunPitch))
            return ((0., 1., 0.), self.ray_override or shot_geometry.transform_vehicle_vector(
                direction, self.body.yaw, self.body.pitch, self.body.roll))

        self.owner._mutable_shot_ray = ray
        self.aim = getattr(self.control, 'manual_aim', None) or ManualAim(self.control)
        self.control.manual_aim = self.aim
        # Keep the real core routing, validator, journal and deadline handling.
        self.sequence = 0

    def submit(self, action='aim_point', args=None, identity=None, timeout=15., replace=True):
        self.sequence += 1
        identity = identity or 'aim-%s' % self.sequence
        if args is None:
            args = dict(position=(20., 1., 100.)) if action == 'aim_point' else (
                dict(target_id=42) if action == 'aim_target' else {})
        request = self.fixture.request(self.control, action, identity=identity, args=args,
                                       timeout_seconds=timeout, replace=replace)
        return self.control.gateway.submit(request, self.fixture.now[0])

    def receipt(self, identity='aim-one'):
        return self.control.gateway.requests[identity]['receipt']

    def observe(self, now):
        self.fixture.now[0] = now
        self.aim.update(now)

    def align(self):
        source = self.rotator.shotPointSourceFunctor()
        self.assertIsNotNone(source)
        self.rotator.turretYaw, self.rotator.gunPitch = self.owner._runtime.get_shot_angles(
            self.entities[1].typeDescriptor, self.body,
            (self.rotator.turretYaw, self.rotator.gunPitch), source)

    def complete(self, action='aim_point', identity='aim-one', timeout=15.):
        self.assertEqual('accepted', self.submit(action, identity=identity, timeout=timeout)['status'])
        self.align()
        self.observe(.1)
        self.assertEqual('completed', self.receipt(identity)['status'])


class ManualAimOwnershipTests(ManualAimHarness, unittest.TestCase):
    def test_installed_source_is_not_success_until_real_native_alignment(self):
        row = self.submit(identity='aim-one')
        self.assertEqual('accepted', row['status'])
        self.assertTrue(self.aim.held)
        self.assertTrue(self.aim.busy)
        self.assertFalse(self.aim.snapshot()['aligned'])
        self.assertEqual('aim_not_aligned', self.aim.fire_preflight())
        self.observe(.05)
        self.assertEqual('accepted', self.receipt()['status'])
        self.align()
        self.observe(.1)
        self.assertEqual(('completed', 'aim_aligned'),
                         (self.receipt()['status'], self.receipt()['reason']))
        self.assertTrue(self.aim.held)
        self.assertFalse(self.aim.busy)
        self.owner._avatar.shoot.assert_not_called()
        self.owner._sender.send_current.assert_not_called()

    def test_angles_and_actual_barrel_must_both_align(self):
        self.submit(identity='aim-one')
        self.align()
        self.ray_override = (0., 0., 1.)
        self.observe(.1)
        self.assertEqual('accepted', self.receipt()['status'])
        self.assertEqual('aim_not_aligned', self.aim.fire_preflight())
        self.ray_override = None
        self.observe(.2)
        self.assertEqual('completed', self.receipt()['status'])

    def test_completed_source_survives_receipt_deadline_until_explicit_release(self):
        self.complete(timeout=.5)
        source = self.rotator.shotPointSourceFunctor
        self.control.gateway.tick(60.)
        self.observe(60.)
        self.assertTrue(self.aim.held)
        self.assertIs(source, self.rotator.shotPointSourceFunctor)
        self.assertIsNotNone(source())
        self.assertIsNone(self.aim.fire_preflight())
        row = self.submit('release_aim', dict(command_id='aim-one'))
        self.assertEqual(('completed', 'aim_released'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.assertIsNone(source())
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)
        self.assertFalse(self.rotator.clientMode)
        self.assertEqual('completed', self.receipt()['status'])

    def test_preexisting_manual_lock_and_drive_are_preserved(self):
        self.control.override = (20., 1., .3)
        self.control.observations = {42: (0., (0., 0., 100.))}
        before = copy.deepcopy(self.control.observations)
        self.complete('aim_target')
        self.submit('release_aim')
        self.owner._avatar.autoAim.assert_not_called()
        self.assertEqual(77, self.owner._avatar._PlayerAvatar__autoAimVehID)
        self.assertEqual((20., 1., .3), self.control.override)
        self.assertEqual(before, self.control.observations)
        self.owner._sender.send_current.assert_not_called()

    def test_replace_false_blocks_completed_hold_and_guarded_release_is_exact(self):
        self.complete()
        original = self.rotator.shotPointSourceFunctor
        row = self.submit('aim_target', replace=False)
        self.assertEqual(('rejected', 'aim_busy'), (row['status'], row['reason']))
        row = self.submit('release_aim', dict(command_id='someone-else'))
        self.assertEqual(('rejected', 'aim_owner_mismatch'), (row['status'], row['reason']))
        self.assertIs(original, self.rotator.shotPointSourceFunctor)
        self.assertEqual('aim-one', self.aim.snapshot()['command_id'])

    def test_replacement_retains_original_manual_source_not_retired_aim_callback(self):
        self.complete()
        previous = self.rotator.shotPointSourceFunctor
        self.submit(args=dict(position=(-20., 1., 100.)), identity='replacement')
        self.assertIsNone(previous())
        self.assertNotEqual(previous, self.rotator.shotPointSourceFunctor)
        self.assertEqual('completed', self.receipt()['status'])
        self.aim.stop('manual', .2)
        self.assertEqual('cancelled', self.receipt('replacement')['status'])
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)
        self.assertFalse(self.rotator.clientMode)

    def test_unreachable_replacement_does_not_remove_working_hold(self):
        self.complete()
        source = self.rotator.shotPointSourceFunctor
        row = self.submit(args=dict(position=(10000., 10000., 10000.)))
        self.assertEqual(('failed', 'aim_unreachable'), (row['status'], row['reason']))
        self.assertIs(source, self.rotator.shotPointSourceFunctor)
        self.assertEqual('aim-one', self.aim.snapshot()['command_id'])

    def test_newer_native_source_is_never_overwritten_on_release(self):
        self.complete()
        newer = lambda: (5., 6., 7.)
        self.rotator.shotPointSourceFunctor = newer
        self.rotator.clientMode = True
        writes = len(self.rotator.writes)
        self.observe(.2)
        self.assertFalse(self.aim.held)
        self.assertEqual('aim_source_lost', self.aim.snapshot()['reason'])
        self.assertIs(newer, self.rotator.shotPointSourceFunctor)
        self.assertTrue(self.rotator.clientMode)
        self.assertEqual(writes, len(self.rotator.writes))

    def test_native_manual_lock_mode_takeover_restores_only_our_source(self):
        self.complete()
        self.rotator.clientMode = False
        self.observe(.2)
        self.assertFalse(self.aim.held)
        self.assertFalse(self.rotator.clientMode)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_no_lease_release_is_idempotent_but_guarded_release_is_not_false_success(self):
        self.assertEqual('completed', self.submit('release_aim')['status'])
        row = self.submit('release_aim', dict(command_id='absent'))
        self.assertEqual(('rejected', 'aim_owner_mismatch'), (row['status'], row['reason']))
        self.assertEqual([], self.rotator.writes)

    def test_duplicate_request_does_not_reacquire_or_refresh_deadline(self):
        self.submit(identity='aim-one', timeout=.5)
        source, writes = self.rotator.shotPointSourceFunctor, len(self.rotator.writes)
        self.fixture.now[0] = .4
        self.submit(identity='aim-one', timeout=.5)
        self.assertIs(source, self.rotator.shotPointSourceFunctor)
        self.assertEqual(writes, len(self.rotator.writes))
        self.align()
        self.observe(.5)
        self.assertEqual(('failed', 'command_timeout'),
                         (self.receipt()['status'], self.receipt()['reason']))
        self.assertFalse(self.aim.held)

    def test_unreachable_turret_does_not_drive_hull(self):
        self.entities[1].typeDescriptor = descriptor(yaw_limits=(-.1, .1))
        row = self.submit()
        self.assertEqual(('failed', 'aim_unreachable'), (row['status'], row['reason']))
        self.assertEqual([], self.rotator.writes)
        self.owner._sender.send_current.assert_not_called()


class ManualAimObservationTests(ManualAimHarness, unittest.TestCase):
    def test_target_command_uses_current_visible_engine_id_and_tracks_after_completion(self):
        self.complete('aim_target')
        self.assertEqual(42, self.aim.target_id)
        self.target.position = (-20., 0., 100.)
        self.observe(.2)
        self.assertEqual('completed', self.receipt()['status'])
        self.assertTrue(self.aim.held)
        self.assertFalse(self.aim.snapshot()['aligned'])
        self.assertEqual('holding', self.aim.snapshot()['phase'])
        self.assertEqual('aim_not_aligned', self.aim.fire_preflight())
        self.align()
        self.observe(.3)
        self.assertTrue(self.aim.snapshot()['aligned'])
        self.assertIsNone(self.aim.fire_preflight())

    def test_missing_dead_friendly_hidden_unstarted_and_tombstone_targets_are_not_admitted(self):
        changes = (
            lambda: self.entities.pop(42),
            lambda: setattr(self.target, 'isAlive', lambda: False),
            lambda: self.owner._records[42]['state'].update(team=1),
            lambda: self.owner._records[42].update(spot_visible=False),
            lambda: setattr(self.target, 'isStarted', False),
            lambda: self.owner._records[42].update(tombstone=True),
        )
        for change in changes:
            with self.subTest(change=change):
                self.entities[42] = self.target
                self.target.isAlive, self.target.isStarted = lambda: True, True
                self.owner._records[42].update(spot_visible=True, tombstone=False, state=dict(team=2))
                change()
                row = self.submit('aim_target')
                self.assertEqual(('rejected', 'aim_target_unavailable'), (row['status'], row['reason']))
                self.assertFalse(self.aim.held)
        self.assertEqual([], self.rotator.writes)

    def test_loss_of_target_releases_pending_and_completed_lease_without_rewriting_success(self):
        self.submit('aim_target', identity='pending')
        source = self.rotator.shotPointSourceFunctor
        self.owner._records[42]['spot_visible'] = False
        self.assertIsNone(source())
        self.observe(.1)
        self.assertEqual(('failed', 'aim_target_unavailable'),
                         (self.receipt('pending')['status'], self.receipt('pending')['reason']))
        self.owner._records[42]['spot_visible'] = True
        self.complete('aim_target')
        self.target.isAlive = lambda: False
        self.observe(.2)
        self.assertFalse(self.aim.held)
        self.assertEqual('completed', self.receipt()['status'])
        self.assertEqual('aim_target_unavailable', self.aim.snapshot()['reason'])

    def test_status_visible_targets_are_bounded_and_do_not_change_auto_observations(self):
        self.control.observations = {42: (123., (9., 8., 7.))}
        for identity in range(50, 50 + MAX_VISIBLE_TARGETS + 8):
            target = types.SimpleNamespace(id=identity, position=(float(identity), 0., 100.),
                                          isAlive=lambda: True, isStarted=True)
            self.entities[identity] = target
            self.owner._records[identity] = dict(ready=True, engine_id=identity,
                                                spot_visible=True, state=dict(team=2))
        snapshot = self.aim.snapshot()
        self.assertEqual(MAX_VISIBLE_TARGETS, len(snapshot['visible_targets']))
        self.assertTrue(snapshot['visible_targets_truncated'])
        self.assertEqual(dict(target_id=42, position=[20., 0., 100.]), snapshot['visible_targets'][0])
        self.assertEqual({42: (123., (9., 8., 7.))}, self.control.observations)

    def test_missing_native_angle_or_barrel_observation_never_reports_success(self):
        getter = self.owner._runtime.get_shot_angles
        self.owner._runtime.get_shot_angles = None
        row = self.submit()
        self.assertEqual(('failed', 'aim_native_unavailable'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.owner._runtime.get_shot_angles = getter
        self.submit(identity='aim-one')
        self.align()
        self.rotator.turretYaw = float('nan')
        self.observe(.1)
        self.assertNotEqual('completed', self.receipt()['status'])
        self.assertFalse(self.aim.snapshot()['aligned'])

    def test_native_solver_mismatch_is_not_claimed_as_alignment(self):
        self.owner._runtime.get_shot_angles = lambda *unused: (0., 0.)
        row = self.submit()
        self.assertEqual(('failed', 'aim_native_unavailable'), (row['status'], row['reason']))
        self.assertEqual([], self.rotator.writes)

    def test_mechanically_reachable_high_arc_uses_verified_native_source(self):
        gun = descriptor(minimum=-1.5, maximum=-.4)
        native, unused_target, shot, unused_body = aiming_scene(speed=40., gravity=10., own_descriptor=gun)
        self.entities[1].typeDescriptor = gun
        self.owner._runtime = native._runtime
        self.owner._gun_state.shots = [shot]
        row = self.submit(identity='aim-one', args=dict(position=(0., 1., 100.)))
        self.assertEqual('accepted', row['status'])
        self.assertLess(self.aim.operation['solution']['pitch'], -1.)
        self.assertNotEqual((0., 1., 100.), self.rotator.shotPointSourceFunctor())
        self.align()
        self.observe(.1)
        self.assertEqual('completed', self.receipt()['status'])
        self.assertIsNone(self.aim.fire_preflight())

    def test_zero_gravity_and_tilted_body_use_actual_local_and_world_angles(self):
        native, unused_target, shot, unused_body = aiming_scene(gravity=0.)
        self.owner._runtime = native._runtime
        self.owner._gun_state.shots = [shot]
        self.body.yaw, self.body.pitch, self.body.roll = .3, .08, -.1
        self.submit(identity='aim-one', args=dict(position=(30., 7., 100.)))
        self.align()
        self.observe(.1)
        self.assertEqual('completed', self.receipt()['status'])
        self.assertIsNone(self.aim.fire_preflight())

    def test_fire_gate_is_fresh_readonly_and_does_not_reuse_completed_receipt(self):
        self.complete('aim_target')
        before = (len(self.rotator.writes), len(self.fixture.rows), self.aim.snapshot())
        self.assertIsNone(self.aim.fire_preflight())
        self.assertEqual(before, (len(self.rotator.writes), len(self.fixture.rows), self.aim.snapshot()))
        self.target.position = (-20., 0., 100.)
        self.assertEqual('aim_not_aligned', self.aim.fire_preflight())
        self.owner._records[42]['spot_visible'] = False
        self.assertEqual('aim_target_unavailable', self.aim.fire_preflight())
        self.assertTrue(self.aim.held)
        self.assertEqual('completed', self.receipt()['status'])
        self.owner._avatar.shoot.assert_not_called()

    def test_native_shot_or_burst_and_automatic_fire_block_new_aim_without_cancelling_them(self):
        for field in ('_local_fire_intent', '_local_player_burst'):
            with self.subTest(field=field):
                pending = dict(identity='native-shot')
                setattr(self.owner, field, pending)
                row = self.submit()
                self.assertEqual(('rejected', 'gun_not_ready'), (row['status'], row['reason']))
                self.assertIs(pending, getattr(self.owner, field))
                setattr(self.owner, field, None)
        self.control.active = True
        self.control.features.add('fire')
        row = self.submit()
        self.assertEqual(('rejected', 'automatic_fire_active'), (row['status'], row['reason']))
        self.assertEqual([], self.rotator.writes)
        self.owner._cancel_local_player_burst.assert_not_called()

    def test_existing_hold_survives_explicit_shot_burst_and_never_cancels_it(self):
        self.complete()
        pending = self.owner._local_player_burst = dict(identity='shot')
        self.observe(.2)
        self.assertTrue(self.aim.held)
        self.assertIs(pending, self.owner._local_player_burst)
        self.submit('release_aim')
        self.assertIs(pending, self.owner._local_player_burst)
        self.owner._cancel_local_player_burst.assert_not_called()

    def test_tolerance_applies_to_observed_rotation_not_write_acceptance(self):
        self.submit(identity='aim-one', args=dict(position=(20., 1., 100.), tolerance_deg=.05))
        self.align()
        self.rotator.turretYaw += math.radians(.07)
        self.observe(.1)
        self.assertEqual('accepted', self.receipt()['status'])
        self.rotator.turretYaw -= math.radians(.04)
        self.observe(.2)
        self.assertEqual('completed', self.receipt()['status'])


class ManualAimLifecycleTests(ManualAimHarness, unittest.TestCase):
    def test_timeout_releases_before_late_rotation_and_source_cannot_return_expired_point(self):
        self.submit(identity='aim-one', timeout=.5)
        source = self.rotator.shotPointSourceFunctor
        self.align()
        self.fixture.now[0] = .5
        self.assertIsNone(source())
        self.control.gateway.tick(.5)
        self.observe(.5)
        self.assertEqual(('failed', 'command_timeout'),
                         (self.receipt()['status'], self.receipt()['reason']))
        self.assertFalse(self.aim.held)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_identity_change_after_completion_releases_without_rewriting_history(self):
        self.complete()
        source = self.rotator.shotPointSourceFunctor
        self.owner._start_message['round_id'] = 'round-b'
        self.assertIsNone(source())
        self.assertEqual('identity_changed', self.aim.fire_preflight())
        self.observe(.2)
        self.assertFalse(self.aim.held)
        self.assertEqual('identity_changed', self.aim.snapshot()['reason'])
        self.assertEqual('completed', self.receipt()['status'])

    def test_identity_type_change_is_not_the_same_player(self):
        self.submit(identity='aim-one')
        self.owner.client.player_id = True
        self.observe(.1)
        self.assertEqual(('cancelled', 'identity_changed'),
                         (self.receipt()['status'], self.receipt()['reason']))
        self.assertFalse(self.aim.held)

    def test_entity_replacement_with_same_player_id_cannot_keep_old_lease(self):
        self.complete()
        source = self.rotator.shotPointSourceFunctor
        self.entities[1] = copy.copy(self.entities[1])
        self.assertIsNone(source())
        self.assertEqual('entity_changed', self.aim.fire_preflight())
        self.observe(.2)
        self.assertFalse(self.aim.held)
        self.assertEqual('entity_changed', self.aim.snapshot()['reason'])
        self.assertEqual('completed', self.receipt()['status'])

    def test_entity_replacement_inside_native_source_setter_never_completes(self):
        self.rotator.source_after = lambda unused: self.entities.__setitem__(1, copy.copy(self.entities[1]))
        row = self.submit(identity='aim-one')
        self.assertEqual(('cancelled', 'entity_changed'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_target_moves_during_alignment_read_is_not_certified_at_old_position(self):
        self.submit('aim_target', identity='aim-one')
        self.align()
        getter = self.owner._runtime.get_shot_angles

        def moving_getter(*args):
            result = getter(*args)
            self.target.position = (self.target.position[0] + 20., 0., 100.)
            return result

        self.owner._runtime.get_shot_angles = moving_getter
        self.observe(.1)
        self.assertEqual('accepted', self.receipt()['status'])
        self.assertTrue(self.aim.held)
        self.assertFalse(self.aim.snapshot()['aligned'])
        self.assertEqual('aim_observation_changed', self.aim.fire_preflight())

    def test_shot_definition_changes_during_native_read_is_not_certified_as_old_ballistics(self):
        self.complete()
        getter = self.owner._runtime.get_shot_angles

        def changing_getter(*args):
            result = getter(*args)
            self.owner._gun_state.shots = [dict(self.owner._gun_state.shots[0])]
            return result

        self.owner._runtime.get_shot_angles = changing_getter
        self.assertEqual('aim_observation_changed', self.aim.fire_preflight())
        self.observe(.2)
        self.assertTrue(self.aim.held)
        self.assertFalse(self.aim.snapshot()['aligned'])
        self.assertEqual('completed', self.receipt()['status'])

    def test_nonlive_and_closed_teardown_restore_native_manual_ownership(self):
        for reason in ('dead', 'closed', 'result'):
            with self.subTest(reason=reason):
                self.control.closed = False
                self.fixture.alive[0] = True
                self.owner._battle_result = None
                self.submit(identity=reason)
                if reason == 'dead':
                    self.fixture.alive[0] = False
                elif reason == 'closed':
                    self.control.closed = True
                else:
                    self.owner._battle_result = dict(result='victory')
                self.observe(self.fixture.now[0] + .1)
                self.assertFalse(self.aim.held)
                self.assertEqual('cancelled', self.receipt(reason)['status'])
                self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_clock_regression_cannot_extend_acquisition_or_reuse_completed_hold(self):
        self.complete()
        self.observe(.05)
        self.assertFalse(self.aim.held)
        self.assertEqual('clock_changed', self.aim.snapshot()['reason'])
        self.assertEqual('completed', self.receipt()['status'])

    def test_stop_from_source_setter_before_assignment_cannot_leave_late_bound_source(self):
        returned = []

        def before(value):
            if value is self.old_source:
                return
            returned.append(value())
            self.aim.stop('manual', self.fixture.now[0])

        self.rotator.source_before = before
        row = self.submit(identity='aim-one')
        self.assertEqual(('cancelled', 'manual'), (row['status'], row['reason']))
        self.assertEqual(1, len(returned))
        self.assertIsNotNone(returned[0])
        self.assertFalse(self.aim.held)
        self.assertFalse(self.control.release_pending)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)
        self.assertFalse(self.rotator.clientMode)

    def test_stop_from_client_mode_setter_is_not_overwritten_on_return(self):
        self.rotator.mode_before = lambda value: self.aim.stop('manual', 0.) if value else None
        row = self.submit(identity='aim-one')
        self.assertEqual(('cancelled', 'manual'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.assertFalse(self.rotator.clientMode)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_reentrant_replacement_during_native_install_is_rejected(self):
        nested = []

        def during(value):
            if value is not self.old_source:
                nested.append(self.submit('aim_target', identity='nested'))

        self.rotator.source_after = during
        row = self.submit(identity='aim-one')
        self.assertEqual('accepted', row['status'])
        self.assertEqual(('rejected', 'aim_busy'), (nested[0]['status'], nested[0]['reason']))
        self.assertEqual('aim-one', self.aim.snapshot()['command_id'])

    def test_native_install_exceeding_deadline_or_changing_identity_never_succeeds(self):
        self.rotator.source_after = lambda value: self.fixture.now.__setitem__(0, 2.)
        row = self.submit(identity='late', timeout=1.)
        self.assertEqual(('failed', 'command_timeout'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.rotator.source_after = lambda value: self.owner._start_message.update(round_id='other')
        row = self.submit(identity='changed')
        self.assertEqual(('cancelled', 'identity_changed'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)

    def test_completion_emit_reentry_stop_does_not_resurrect_completed_source(self):
        self.submit(identity='aim-one')
        self.align()
        emit = self.control.gateway.emit

        def stopping_emit(row):
            emit(row)
            if row['id'] == 'aim-one' and row['status'] == 'completed':
                self.aim.stop('manual', self.fixture.now[0])
            return True

        self.control.gateway.emit = stopping_emit
        self.observe(.1)
        self.assertEqual('completed', self.receipt()['status'])
        self.assertFalse(self.aim.held)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_failed_source_release_is_retained_and_retried_not_falsely_completed(self):
        self.complete()
        source = self.rotator.shotPointSourceFunctor
        failing = [True]

        def fail_restore(value):
            if value is self.old_source and failing[0]:
                raise RuntimeError('native restore temporarily unavailable')

        self.rotator.source_before = fail_restore
        row = self.submit('release_aim')
        self.assertEqual(('failed', 'aim_release_pending'), (row['status'], row['reason']))
        self.assertTrue(self.aim.held)
        self.assertTrue(self.aim.busy)
        self.assertEqual('releasing', self.aim.snapshot()['phase'])
        self.assertIsNone(source())
        self.assertEqual([RELEASE_STAGE], [stage for stage, unused in self.control.release_pending])
        writes = len(self.rotator.writes)
        self.observe(.2)
        self.assertEqual(writes, len(self.rotator.writes))
        row = self.submit(identity='blocked')
        self.assertEqual('release_pending', row['reason'])
        failing[0] = False
        self.control.retry_releases(2.)
        self.assertFalse(self.aim.held)
        self.assertFalse(self.control.release_pending)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)
        self.assertFalse(self.rotator.clientMode)

    def test_release_that_raises_after_source_write_still_restores_mode_on_retry(self):
        self.complete()
        failing = [True]

        def after(value):
            if value is self.old_source and failing[0]:
                failing[0] = False
                raise RuntimeError('post-set native error')

        self.rotator.source_after = after
        self.assertFalse(self.aim.stop('manual', .1))
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)
        self.assertTrue(self.rotator.clientMode)
        self.control.retry_releases(2.)
        self.assertFalse(self.aim.held)
        self.assertFalse(self.rotator.clientMode)

    def test_retry_does_not_overwrite_foreign_takeover_after_failed_cleanup(self):
        self.complete()

        def fail(value):
            if value is self.old_source:
                raise RuntimeError('blocked')

        self.rotator.source_before = fail
        self.assertFalse(self.aim.stop('manual', .1))
        self.rotator.source_before = None
        newer = lambda: (1., 2., 3.)
        self.rotator.shotPointSourceFunctor = newer
        self.rotator.clientMode = True
        self.control.retry_releases(2.)
        self.assertFalse(self.aim.held)
        self.assertIs(newer, self.rotator.shotPointSourceFunctor)
        self.assertTrue(self.rotator.clientMode)

    def test_foreign_takeover_inside_source_restoration_keeps_its_mode(self):
        self.complete()
        newer = lambda: (7., 8., 9.)

        def take_over(value):
            if value is self.old_source:
                setattr(self.rotator, SOURCE_ATTRIBUTE, newer)
                self.rotator.clientMode = True

        self.rotator.source_after = take_over
        self.assertTrue(self.aim.stop('manual', .1))
        self.assertFalse(self.aim.held)
        self.assertIs(newer, self.rotator.shotPointSourceFunctor)
        self.assertTrue(self.rotator.clientMode)

    def test_native_fire_guard_read_reentry_cannot_return_stale_success(self):
        self.complete()
        getter = self.owner._runtime.get_shot_angles

        def stop_getter(*args):
            result = getter(*args)
            self.aim.stop('manual', self.fixture.now[0])
            return result

        self.owner._runtime.get_shot_angles = stop_getter
        self.assertEqual('aim_source_lost', self.aim.fire_preflight())
        self.assertFalse(self.aim.held)

    def test_stop_during_prebind_native_proof_cannot_resurrect_new_aim(self):
        getter = self.owner._runtime.get_shot_angles

        def stopped_proof(*args):
            self.aim.stop('manual', self.fixture.now[0])
            return getter(*args)

        self.owner._runtime.get_shot_angles = stopped_proof
        row = self.submit(identity='aim-one')
        self.assertEqual(('cancelled', 'aim_owner_changed'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.assertEqual([], self.rotator.writes)

    def test_stop_when_replaced_receipt_is_emitted_prevents_new_native_owner(self):
        self.submit(identity='aim-one')
        emit = self.control.gateway.emit

        def stop_on_replacement(row):
            emit(row)
            if row['id'] == 'aim-one' and row.get('reason') == 'replaced':
                self.aim.stop('manual', self.fixture.now[0])
            return True

        self.control.gateway.emit = stop_on_replacement
        row = self.submit('aim_target', identity='replacement')
        self.assertEqual(('cancelled', 'aim_owner_changed'), (row['status'], row['reason']))
        self.assertFalse(self.aim.held)
        self.assertIs(self.old_source, self.rotator.shotPointSourceFunctor)

    def test_old_release_receipt_reentry_must_not_close_a_newer_lease(self):
        self.submit(identity='aim-one')
        emit = self.control.gateway.emit
        replacement = []

        def replace_on_release(row):
            emit(row)
            if row['id'] == 'aim-one' and row.get('reason') == 'aim_released':
                self.aim.stop('manual', self.fixture.now[0])
                replacement.append(self.submit('aim_target', identity='newer'))
            return True

        self.control.gateway.emit = replace_on_release
        row = self.submit('release_aim', dict(command_id='aim-one'))
        self.assertEqual('completed', row['status'])
        self.assertEqual('accepted', replacement[0]['status'])
        self.assertTrue(self.aim.held)
        self.assertEqual('newer', self.aim.snapshot()['command_id'])
        self.assertIsNotNone(self.rotator.shotPointSourceFunctor())

    def test_clock_regression_inside_fire_observation_cannot_return_stale_success(self):
        self.complete()
        getter = self.owner._runtime.get_shot_angles

        def time_reversal(*args):
            self.fixture.now[0] = .05
            return getter(*args)

        self.owner._runtime.get_shot_angles = time_reversal
        self.assertEqual('clock_changed', self.aim.fire_preflight())


if __name__ == '__main__':
    unittest.main()
