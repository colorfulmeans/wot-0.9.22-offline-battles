"""A committed trigger completes its physical tail without tactical re-admission.

Every head uses the complete foreground runtime and real native geometry
admission fixture. World, friendly, armor, target and control changes affect
the NEXT trigger. Physical actor/battle/gun failures are separate, explicit
terminal events. These are engine-boundary tests, not Windows acceptance.
"""
import unittest
from unittest import mock

import test_player_fire_admission_complete as boundary
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import native_target_pose
from gui.mods.offline_lan_0922.vehicle_control.trigger_admission import barrel_path


class PlayerBurstLivenessTests(unittest.TestCase):
    def setUp(self):
        self.fixture = boundary.AutomaticFireScene()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.owner = self.fixture.battle
        self.control = self.fixture.control
        self.runtime = self.fixture.runtime
        self.admission = self.fixture.admission

    def _head(self):
        self.assertTrue(self.fixture.fire(), self.admission.receipt)
        self.burst = self.owner._local_player_burst
        self.assertIsNotNone(self.burst)
        self.assertEqual(1, self.burst['committed'])
        self.assertEqual('committed', self.admission.receipt['status'])
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        return self.burst

    def _tail(self):
        # These assertions would fail if any tactical gate were reintroduced
        # after the real, successful admission above.
        with mock.patch.object(self.control, 'authorize_trigger',
                               side_effect=AssertionError('tail authorization')), \
                mock.patch.object(self.control, 'prepare_trigger',
                                  side_effect=AssertionError('tail admission')):
            self.fixture.world_queries[:] = []
            self.assertTrue(self.fixture.advance(.1))
            self.assertEqual([], self.fixture.world_queries)
            self.assertTrue(self.fixture.advance(.1))
            self.assertEqual([], self.fixture.world_queries)
        self.assertIsNone(self.owner._local_player_burst)
        self.assertIsNone(self.owner._local_fire_intent)
        self.assertIsNone(self.control.owned_burst)
        self.assertEqual(0, self.owner._gun_state._burst_remaining)
        self.assertEqual([17, 10], self.owner._gun_state.ammo)
        self.assertEqual(3, self.owner._gun_state.clip)
        self.assertEqual(3, self.control.shot_commits)
        launches = self.fixture.launches()
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in launches])
        self.assertEqual([3, 3, 3], [row['burst_count'] for row in launches])
        self.assertEqual(1, len({row['burst_group_seq'] for row in launches}))
        self.assertEqual(3, len({row['projectile_id'] for row in launches}))
        self.assertAlmostEqual(.1, launches[1]['local_launch_time']-launches[0]['local_launch_time'])
        self.assertAlmostEqual(.1, launches[2]['local_launch_time']-launches[1]['local_launch_time'])
        return launches

    def _next_denied(self, reason=None):
        self.fixture.advance(.6)
        before = list(self.owner._gun_state.ammo)
        self.assertFalse(self.fixture.fire())
        self.assertEqual(before, self.owner._gun_state.ammo)
        self.assertEqual(3, len(self.fixture.launches()))
        self.assertIsNone(self.owner._local_player_burst)
        if reason is not None:
            self.assertEqual(reason, self.control.last_fire_failure)

    def _next_denied_without_current_target(self):
        # The final-pose refresh refuses an absent current intention before
        # constructing admission context; the physical tail above already
        # completed and this next edge still cannot launch or debit.
        with mock.patch.object(self.admission, 'prepare',
                               wraps=self.admission.prepare) as prepare:
            self._next_denied()
        prepare.assert_not_called()
        self.assertNotIn(42, [row['network_id'] for row in self.runtime.combat_targets()])
        receipt = self.runtime.attack_policy.evaluator.trigger_refresh_receipt
        self.assertEqual(('pending', 'intent_unavailable'),
                         (receipt['status'], receipt['reason']))
        self.assertEqual(0, receipt['work']['predictions'])

    def test_world_appears_after_head_tails_continue_next_trigger_rejects(self):
        self._head()
        self.fixture.world = [((-2., 0., 19.), (2., 3., 21.))]
        self._tail()
        self._next_denied('auto_world_blocked')

    def test_friend_enters_after_head_tails_continue_next_trigger_rejects(self):
        self._head()
        self.fixture.vehicle(43, (0., 0., 50.), 1)
        self._tail()
        self._next_denied('auto_friendly_lane')

    def test_target_dies_after_head_tails_continue_next_trigger_rejects(self):
        self._head()
        self.fixture.target.health = 0
        self.owner._records['bot:42']['state'].update(health=0, alive=False)
        self._tail()
        self._next_denied_without_current_target()
        self.assertFalse(self.fixture.target.isAlive())

    def test_target_unspotted_after_head_tails_continue_next_trigger_rejects(self):
        self._head()
        self.owner._records['bot:42']['spot_visible'] = False
        self._tail()
        self._next_denied_without_current_target()
        self.assertFalse(self.owner._records['bot:42']['spot_visible'])

    def test_target_pose_changes_after_head_tails_continue_next_trigger_rejects(self):
        self._head()
        previous_pose = self.fixture.candidate['solution']['target_pose']
        self.fixture.pose(self.fixture.target, (10., 0., 100.))
        self._tail()
        with mock.patch.object(self.admission, 'prepare',
                               wraps=self.admission.prepare) as prepare:
            self._next_denied('auto_gun_laying')
        prepare.assert_called_once()
        context, unused_entity, unused_gun, ray, unused_dispersion, shot, unused_now = prepare.call_args[0]
        solution = context['solution']
        actual_pose = native_target_pose(self.owner, self.fixture.target)[0]
        self.assertNotEqual(previous_pose, actual_pose)
        self.assertEqual(actual_pose, solution['target_pose'])
        receipt = self.runtime.attack_policy.evaluator.trigger_refresh_receipt
        self.assertEqual(('refreshed', 'same_intention'),
                         (receipt['status'], receipt['reason']))
        # The same point was truly recomputed at the new native pose. The
        # actual barrel still follows its old ray and misses that new point.
        path, unused_times, unused_flight = barrel_path(ray[0], ray[1], shot, solution['point'])
        self.assertTrue(path)
        self.assertGreater(sum((path[-1][i] - solution['point'][i]) ** 2 for i in range(3)), .30 ** 2)

    def test_armor_changes_after_head_tails_continue_next_trigger_rechecks(self):
        self._head()
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(self.fixture.target.typeDescriptor, name).materials[0].armor = 10000.
        self._tail()
        self._next_denied('auto_actual_barrel_armour')

    def test_stop_detaches_controller_but_cannot_cancel_committed_trigger(self):
        burst = self._head()
        generation = self.control.control_generation
        self.assertTrue(self.control.stop('explicit_stop'))
        self.assertFalse(self.control.active)
        self.assertGreater(self.control.control_generation, generation)
        self.assertIs(burst, self.owner._local_player_burst)
        self.assertTrue(burst['player_control']['controller_detached'])
        self.assertEqual('explicit_stop', burst['player_control']['stop_requested'])
        self._tail()
        self._next_denied()
        for row in self.control.shot_receipts.rows.values():
            self.assertEqual(generation, row['generation'])

    def test_controller_close_does_not_remove_physical_tail(self):
        self._head()
        self.control.close()
        self.assertTrue(self.control.closed)
        self._tail()
        self._next_denied()

    def test_disabling_automatic_fire_does_not_revoke_physical_tail(self):
        self._head()
        self.control.features.discard('fire')
        self.runtime.features.discard('fire')
        self._tail()
        self._next_denied()

    def test_native_source_takeover_cannot_cancel_already_committed_tail(self):
        self._head()
        external = lambda: (10., 5., 30.)
        self.owner._avatar.gunRotator.shotPointSourceFunctor = external
        self._tail()
        self._next_denied()
        self.assertIs(external, self.owner._avatar.gunRotator.shotPointSourceFunctor)

    def test_native_client_mode_takeover_cannot_cancel_already_committed_tail(self):
        self._head()
        self.owner._avatar.gunRotator.clientMode = False
        self._tail()
        self._next_denied()
        self.assertFalse(self.owner._avatar.gunRotator.clientMode)

    def test_mission_failure_and_withdrawn_fire_order_do_not_cancel_tail(self):
        self._head()
        self.runtime._mission = dict(status='failed', reason='route_unreachable')
        self.runtime._last_order = dict(fire_allowed=False, suppress_fire=True)
        self.control.last_order = dict(mission=dict(status='failed'), fire_allowed=False)
        self._tail()

    def test_yield_and_artillery_relocation_are_not_physical_cancellation(self):
        self._head()
        self.runtime._last_order = dict(suppress_fire=True, fire_allowed=False,
                                       artillery=dict(phase='relocating'))
        self._tail()

    def test_mission_cancellation_reentering_tail_install_does_not_retract_it(self):
        self._head()
        original = self.owner._preinstall_player_projectile
        def cancel_after_install(*args):
            result = original(*args)
            self.control.stop('mission_cancelled_during_tail_install')
            return result
        self.owner._preinstall_player_projectile = cancel_after_install
        self._tail()

    def test_actual_barrel_and_native_dispersion_are_resampled_for_tails(self):
        self._head()
        angles = []
        original = self.owner._gun_state.scatter
        def sample(direction, perfect, **kwargs):
            angles.append(kwargs['dispersion_angle'])
            return original(direction, perfect, **kwargs)
        self.owner._gun_state.scatter = sample
        self.fixture.direction = (1., 0., 0.)
        self.owner._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .02
        self.assertTrue(self.fixture.advance(.1))
        self.fixture.direction = (0., 0., -1.)
        self.owner._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .04
        self.assertTrue(self.fixture.advance(.1))
        launches = self.fixture.launches()
        self.assertGreater(launches[0]['velocity'][2], 0.)
        self.assertGreater(launches[1]['velocity'][0], 0.)
        self.assertLess(launches[2]['velocity'][2], 0.)
        self.assertEqual([.02, .04], angles)
        self.assertEqual([17, 10], self.owner._gun_state.ammo)
        self.assertEqual(3, len(launches))
        self._next_denied('auto_actual_barrel_unavailable')

    def test_he_splash_friend_arrival_affects_next_trigger_not_tail(self):
        self.fixture.set_he()
        self.fixture.lay()
        self._head()
        self.fixture.vehicle(43, (4., 0., 96.), 1)
        self._tail()
        self._next_denied('auto_friendly_splash')

    def test_he_zero_damage_contact_is_a_valid_trigger_and_tail_keeps_running(self):
        self.fixture.set_he(piercing=1.)
        with mock.patch.object(self.owner, '_projectile_he_blast_contact',
                               return_value=dict(nominal_armor=10000., damage=0.)):
            self.fixture.lay(mode='he_fallback')
            self.assertEqual(0., self.fixture.candidate['expected_damage'])
            self._head()
        head = self.fixture.launches()[0]
        self.control.shot_hit(dict(projectile_id=head['projectile_id'],
            event_id='zero-he', damage=0, shot_result=0, target_bot=42))
        self._tail()

    def test_miss_result_cannot_cancel_remaining_physical_shells(self):
        self._head()
        head = self.fixture.launches()[0]
        self.control.shot_terminal(dict(projectile_id=head['projectile_id'], hit_vehicle=False))
        self.assertEqual('terminal', self.control.shot_receipts.get(
            head['projectile_id'])['flight_status'])
        self._tail()

    def test_nonpenetration_result_cannot_cancel_remaining_physical_shells(self):
        self._head()
        head = self.fixture.launches()[0]
        self.control.shot_hit(dict(projectile_id=head['projectile_id'],
            event_id='failed-penetration', damage=0, shot_result=0, target_bot=42))
        self.assertEqual(0., self.control.shot_receipts.get(
            head['projectile_id'])['damage_total'])
        self._tail()

    def test_active_trigger_locks_policy_until_last_physical_commit(self):
        self._head()
        initial = self.runtime.attack_policy.trigger
        self.assertIsNotNone(initial)
        self.fixture.vehicle(44, (20., 0., 50.), 2)
        self.fixture.pose(self.fixture.target, (10., 0., 100.))
        self.fixture.step(.01)
        decision = self.runtime.attack_policy.update(self.fixture.now)
        self.assertEqual('trigger_active', decision['action'])
        self.assertIs(initial, self.runtime.attack_policy.trigger)
        self.assertEqual(0, self.owner._gun_state.shot_index)
        self.fixture.advance(.1)
        self.assertIs(initial, self.runtime.attack_policy.trigger)
        self.fixture.advance(.1)
        self.assertIsNone(self.runtime.attack_policy.trigger)
        self.assertEqual([17, 10], self.owner._gun_state.ammo)

    def test_clear_next_trigger_uses_remaining_clip_and_new_group(self):
        old = self._head()
        self._tail()
        self.fixture.advance(.6)
        self.fixture.lay()
        self.assertTrue(self.fixture.fire(), self.admission.receipt)
        new = self.owner._local_player_burst
        self.assertNotEqual(old['group_seq'], new['group_seq'])
        self.assertEqual([16, 10], self.owner._gun_state.ammo)
        self.assertEqual(2, self.owner._gun_state.clip)
        self.assertEqual(1, new['committed'])
        self.fixture.advance(.3)
        self.assertEqual([14, 10], self.owner._gun_state.ammo)
        self.assertEqual(0, self.owner._gun_state.clip)
        self.assertEqual([0, 1, 2, 0, 1, 2],
                         [row['burst_index'] for row in self.fixture.launches()])

    def test_old_receipt_cannot_terminate_new_control_generation_trigger(self):
        old = self._head()
        self.control.stop('old_generation')
        self._tail()
        self.fixture.advance(.6)
        self.assertTrue(self.control.toggle())
        self.fixture.lay()
        self.assertTrue(self.fixture.fire(), self.admission.receipt)
        current = self.owner._local_player_burst
        self.control.burst_cancelled(old)
        self.assertIs(current, self.owner._local_player_burst)
        self.assertIs(current, self.control.owned_burst)
        self.assertTrue(self.fixture.advance(.3))
        self.assertEqual(6, len(self.fixture.launches()))
        self.assertEqual([14, 10], self.owner._gun_state.ammo)

    def test_delayed_update_drains_tail_instead_of_using_tactical_timeout(self):
        self._head()
        self.fixture.world = [((-2., 0., 19.), (2., 3., 21.))]
        self.control.stop('stopped_during_delayed_frame')
        self.fixture.step(6.)
        self.assertTrue(self.owner._advance_local_player_burst())
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in self.fixture.launches()])
        self.assertEqual([17, 10], self.owner._gun_state.ammo)
        self.assertIsNone(self.owner._local_player_burst)

    def test_physical_actor_death_is_an_explicit_terminal_without_tail_debit(self):
        burst = self._head()
        self.fixture.entity.health = 0
        self.fixture.step(.1)
        self.assertFalse(self.owner._advance_local_player_burst())
        self.assertEqual('actor_destroyed', burst['terminal_reason'])
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self.assertEqual(1, len(self.fixture.launches()))
        self.assertIsNone(self.owner._local_player_burst)

    def test_round_identity_change_is_a_physical_lifecycle_terminal(self):
        burst = self._head()
        self.owner._generation += 1
        self.fixture.fixture.now += .1
        self.assertFalse(self.owner._advance_local_player_burst())
        self.assertEqual('round_changed', burst['terminal_reason'])
        self.assertEqual([19, 10], self.owner._gun_state.ammo)
        self.assertIsNone(self.owner._local_player_burst)


if __name__ == '__main__':
    unittest.main()
