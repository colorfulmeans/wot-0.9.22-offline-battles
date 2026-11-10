"""Regression boundaries from the AT7 control/pose-refresh report.

The supplied observations model native point/probe receipts. CombatStop and
its accept/resolve/apply chain are production code; no test grants movement
ownership or bypasses the original driver/collision authority.
"""
import unittest

from test_player_combat_stop import Scene
from gui.mods.offline_lan_0922 import siege_mechanics


class RecoveryAdmissionAndContinuityTests(unittest.TestCase):
    def scene(self, statuses=(), siege=None):
        scene = Scene(admitted=False, siege=siege)
        # Exercise the original recovery consumer with an already eligible
        # tactical order; the player-route gate has separate report tests.
        scene.owner._route_requires_confirmation = lambda order: False
        scene.raw_order.update(combat_mode='route', target_kind=None,
            target_id=None, move_position=(20., 0., -30.),
            face_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False, route_index=4)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'),
            target_key=('bot', 2), sample=0, line='world_blocked',
            armor='unknown', mechanical='hull_laying',
            pose_stamp=('current',), line_stamp=('current_lane',))
        scene.probes = []
        scene.probe_statuses = list(statuses)

        def probe(candidate, destination, now):
            scene.probes.append((candidate['key'], tuple(destination), now))
            return dict(status=scene.probe_statuses.pop(0)
                if scene.probe_statuses else 'blocked', fire_permission=False)

        scene.runtime.point_recovery_probe = probe
        return scene

    def assert_route(self, scene, result):
        for name in ('combat_mode', 'move_position', 'face_position',
                     'throttle_override', 'target_id', 'target_kind', 'route_index'):
            self.assertEqual(scene.raw_order[name], result[name], name)
        self.assertFalse(scene.owner.combat_owned)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertNotIn('_combat_movement_owner', scene.state)
        self.assertFalse(result['fire_allowed'])

    def test_current_world_blocker_with_pending_probe_keeps_actual_route(self):
        scene = self.scene(['pending'] * 8)
        for tick in range(4):
            scene.state['yaw'] = tick * .2
            self.assert_route(scene, scene.apply(tick * .1))
        self.assertEqual(0, scene.owner._episode)
        self.assertEqual(1, len(set(row[1] for row in scene.probes)))

    def test_checked_same_point_destination_is_the_first_movement_admission(self):
        scene = self.scene(['pending', 'clear'])
        self.assert_route(scene, scene.apply(0.))
        result = scene.apply(.1)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual(1, scene.owner._episode)
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertEqual(scene.probes[-1][1], result['move_position'])
        self.assertEqual(scene.candidate['key'], scene.owner._physical_recovery['key'])
        self.assertFalse(result['fire_allowed'])

    def test_yaw_or_translation_after_failed_review_requires_new_checked_goal(self):
        scene = self.scene(['blocked'] * 100)
        for tick in range(12):
            self.assert_route(scene, scene.apply(tick * .1))
        for tick in range(1, 6):
            scene.state['yaw'] = tick * .3
            scene.position((tick * 1., 1.e-8 * tick, 0.))
            self.assert_route(scene, scene.apply(2. + tick * .1))
        self.assertEqual(0, scene.owner._episode)

    def test_reopened_current_line_retires_only_the_old_blocked_point_failure(self):
        scene = self.scene(['blocked'] * 40)
        for tick in range(12):
            self.assert_route(scene, scene.apply(tick * .1))
        self.assertIsNotNone(scene.owner._failed_recovery)
        scene.candidate.update(line='clear', mechanical='hull_laying')
        result = scene.apply(2.)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertFalse(result['fire_allowed'])
        self.assertIsNone(scene.owner._failed_recovery)

    def test_cold_wall_cannot_enter_native_siege_mode(self):
        scene = self.scene(['pending'] * 4, siege=siege_mechanics.DISABLED)
        for tick in range(3):
            self.assert_route(scene, scene.apply(tick * .1))
            self.assertFalse(scene.owner.waiting_for_siege())

    def test_mode_entry_cannot_add_authority_to_single_feature_control(self):
        for features in ({'fire'}, {'drive'}):
            with self.subTest(features=features):
                scene = self.scene(siege=siege_mechanics.DISABLED)
                scene.runtime.features = features
                scene.candidate.update(line='clear', mechanical='mechanical_limited')
                self.assert_route(scene, scene.apply(0.))
                self.assertFalse(scene.owner.waiting_for_siege())

    def lay_scene(self):
        scene = self.scene()
        scene.candidate.update(line='clear', mechanical='hull_laying')
        scene.candidate['solution'].update(point=(25., 1., 80.), yaw=.7,
            mechanical_reason='yaw_limit')
        scene.apply(0.)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertIsNotNone(scene.owner.pivot)
        scene.lay_receipt = dict(status='pending',
            mechanical='hull_laying', candidate=dict(scene.candidate),
            solution=dict(scene.candidate['solution']))
        scene.policy.retained_lay_candidate = lambda key, now: scene.lay_receipt
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        return scene

    def test_admitted_lay_keeps_current_point_across_pending_global_review(self):
        scene = self.lay_scene()
        pivot = scene.owner.pivot
        for tick in range(1, 5):
            scene.state['yaw'] = .1 * tick
            scene.position((0., tick * 1.e-8, 0.))
            result = scene.apply(float(tick))
            self.assertIs(pivot, scene.owner.pivot)
            self.assertEqual((25., 1., 80.), result['face_position'])
            self.assertFalse(result.get('stable_hull_face'))
            self.assertFalse(result['fire_allowed'])
            self.assertEqual('native_lay', scene.owner.receipt['reason'])
        self.assertGreater(pivot['progress_at'], 0.)

    def test_pending_global_review_cannot_bypass_real_pivot_stall_exit(self):
        scene = self.lay_scene()
        result = scene.apply(6.1)
        self.assert_route(scene, result)
        self.assertIsNone(scene.runtime._native_hull_laying)

    def test_load_intent_does_not_cancel_an_admitted_native_lay(self):
        for action in ('reload_clip', 'switch_shell'):
            with self.subTest(action=action):
                scene = self.lay_scene()
                pivot = scene.owner.pivot
                # An actuator can withhold its aim input during a load
                # transaction. That is not a new route or mode-exit task.
                scene.lay_receipt.update(status='blocked',
                    mechanical='mechanical_limited')
                scene.decide(action)
                order = dict(scene.raw_order)
                result = scene.owner.apply_order(order, .1)
                self.assertEqual(order, result)
                self.assertTrue(scene.owner.combat_owned)
                self.assertTrue(scene.owner.stop_allowed)
                self.assertIs(pivot, scene.owner.pivot)
                self.assertIsNone(scene.owner._failed_recovery)

    def test_other_policy_target_cannot_rewrite_the_retained_pivot_contact(self):
        scene = self.lay_scene()
        other = dict(scene.target, id=3, network_id=3, position=(-25., 0., 80.))
        scene.runtime._targets += (other,)
        scene.candidate = dict(scene.candidate, target=other,
            key=(0, ('bot', 3), 1, 'penetration'), target_key=('bot', 3), sample=1,
            solution=dict(point=(-25., 1., 80.), yaw=-.7))
        scene.decide('firing_position')
        result = scene.apply(.1)
        self.assertEqual(('bot', 2), (result['target_kind'], result['target_id']))
        self.assertEqual((25., 1., 80.), result['face_position'])
        self.assertEqual((25., 1., 80.), result['aim_position'])
        self.assertFalse(result['fire_allowed'])

    def test_reaching_native_arc_completes_lay_without_granting_a_shot(self):
        scene = self.lay_scene()
        scene.lay_receipt['mechanical'] = 'reachable'
        result = scene.apply(.1)
        self.assertIsNone(scene.owner.pivot)
        self.assertEqual(scene.state['position'], result['face_position'])
        self.assertFalse(result['fire_allowed'])

    def test_rotation_refusal_stops_retained_lay_before_any_recheck(self):
        scene = self.lay_scene()
        scene.state['_native_rotation_refused_until'] = 3.
        self.assert_route(scene, scene.apply(.1))

    def test_stalled_lay_requests_one_unowned_same_point_recovery_pass(self):
        scene = self.lay_scene()
        self.assert_route(scene, scene.apply(6.1))
        scene.probe_statuses[:] = ['pending', 'clear']
        self.assert_route(scene, scene.apply(6.2))
        self.assertEqual(1, len(scene.probes))
        result = scene.apply(6.3)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertEqual(scene.probes[-1][1], result['move_position'])
        self.assertFalse(result['fire_allowed'])

    def test_stalled_clear_lay_cannot_reacquire_from_yaw_noise(self):
        scene = self.lay_scene()
        self.assert_route(scene, scene.apply(6.1))
        scene.decide('firing_position')
        scene.probe_statuses[:] = ['blocked'] * 80
        for tick in range(20):
            scene.state['yaw'] = 1.e-8 * tick
            scene.candidate['pose_stamp'] = ('refreshed', tick)
            self.assert_route(scene, scene.apply(6.2 + tick * .1))
        self.assertEqual(1, scene.owner._episode)

    def test_failed_point_does_not_block_another_current_legal_lay_point(self):
        scene = self.lay_scene()
        self.assert_route(scene, scene.apply(6.1))
        other = dict(scene.target, id=3, network_id=3, position=(-25., 0., 80.))
        scene.runtime._targets += (other,)
        scene.candidate = dict(scene.candidate, target=other,
            key=(0, ('bot', 3), 1, 'penetration'), target_key=('bot', 3), sample=1,
            solution=dict(point=(-25., 1., 80.), yaw=-.7))
        scene.decide('firing_position')
        result = scene.apply(6.2)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertEqual(2, scene.owner._episode)
        self.assertEqual(('bot', 3), (result['target_kind'], result['target_id']))
        self.assertEqual(scene.candidate['key'], scene.owner.pivot['key'])
        self.assertFalse(result['fire_allowed'])

    def test_new_move_request_cannot_rebind_a_failed_pivot_sample(self):
        scene = self.lay_scene()
        key = scene.owner.pivot['key']
        self.assert_route(scene, scene.apply(6.1))
        scene.candidate = dict(scene.candidate, key=(0, ('bot', 2), 7, 'penetration'),
                               sample=7, fresh=False)
        scene.decide('firing_position', move_request=dict(key=scene.candidate['key']))
        scene.probe_statuses[:] = ['pending']
        self.assert_route(scene, scene.apply(6.2))
        phase = scene.owner._physical_recovery
        self.assertEqual(key, phase['key'])
        self.assertEqual(key, phase['candidate']['key'])
        self.assertEqual(key[2], phase['sample'])
        self.assertEqual(key, scene.probes[-1][0])

    def test_missing_current_lay_geometry_never_replays_the_old_turn(self):
        scene = self.lay_scene()
        scene.lay_receipt = dict(status='pending', candidate=None, solution=None)
        result = scene.apply(.1)
        self.assertEqual(scene.state['position'], result['face_position'])
        self.assertFalse(result['fire_allowed'])
        self.assert_route(scene, scene.apply(6.1))

    def test_friendly_blocker_uses_same_point_probe_without_an_independent_marker(self):
        scene = self.scene(['pending', 'clear'])
        scene.candidate.update(line='friendly_blocked', mechanical='reachable',
            blocker=dict(blocker_kind='bot', blocker_id=5, blocker_team=1,
                         blocker_position=(0., 0., 12.), blocker_radius=2.))
        self.assert_route(scene, scene.apply(0.))
        result = scene.apply(.1)
        self.assertEqual('gun_angle_adjust', result['combat_mode'])
        self.assertEqual(scene.candidate['key'], scene.owner._physical_recovery['key'])
        self.assertEqual(scene.probes[-1][1], result['move_position'])
        self.assertFalse(getattr(scene.runtime.engine, '_friendly_repositions', {}))

    def test_capture_handoff_retires_retained_pivot_and_preserves_base_face(self):
        scene = self.lay_scene()
        scene.raw_order.update(combat_mode='base_capture', capture_area=True,
            throttle_override=0., face_position=(7., 0., 9.))
        result = scene.apply(.1)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertIsNone(scene.runtime._native_hull_laying)
        self.assertEqual((7., 0., 9.), result['face_position'])

    def test_arrival_lay_uses_the_same_pending_continuation_and_stall_exit(self):
        scene = self.scene(['clear'])
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        scene.position(phase['goal'])
        scene.apply(.1)
        scene.candidate.update(line='clear', mechanical='hull_laying')
        scene.candidate['solution'].update(point=(25., 1., 80.), yaw=.7)
        scene.apply(.2)
        pivot = scene.owner.pivot
        self.assertIsNotNone(pivot)
        scene.policy.retained_lay_candidate = lambda key, now: dict(
            status='pending', candidate=scene.candidate,
            solution=scene.candidate['solution'], mechanical='hull_laying')
        scene.decide('wait', candidate=False, reason='stationary_alternatives_pending')
        result = scene.apply(.3)
        self.assertIs(pivot, scene.owner.pivot)
        self.assertEqual((25., 1., 80.), result['face_position'])
        self.assertFalse(result['fire_allowed'])
        self.assert_route(scene, scene.apply(6.3))

    def test_arrival_lay_load_intent_preserves_the_admitted_motion_task(self):
        for action in ('wait', 'reload_clip', 'switch_shell'):
            with self.subTest(action=action):
                scene = self.scene(['clear'], siege=siege_mechanics.ENABLED)
                scene.apply(0.)
                phase = scene.owner._physical_recovery
                scene.position(phase['goal'])
                scene.apply(.1)
                scene.candidate.update(line='clear', mechanical='hull_laying')
                scene.candidate['solution'].update(point=(25., 1., 80.), yaw=.7)
                previous = scene.apply(.2)
                pivot = scene.owner.pivot
                self.assertIsNotNone(pivot)
                self.assertTrue(phase['checking'])
                # The same current hydraulic input compensates a limited
                # gun. Its real consumer withholds it for load actions.
                scene.runtime._siege_aim_candidate = dict(scene.candidate,
                    mechanical='hydraulic_laying',
                    solution=dict(scene.candidate['solution'],
                        needs_hydraulic=True, hydraulic_pitch=.05))
                scene.candidate['mechanical'] = 'mechanical_limited'
                reviews = []

                def retained(key, now):
                    reviews.append(key)
                    return dict(status='blocked', candidate=scene.candidate,
                        solution=scene.candidate['solution'],
                        mechanical='mechanical_limited')

                scene.policy.retained_lay_candidate = retained
                scene.decide(action)
                self.assertEqual(action == 'wait',
                    scene.runtime.siege_aim_candidate() is not None)
                # As in the native-mode reload boundary test, pass the
                # accepted order directly to this movement consumer.
                scene.runtime.now = .3
                result = scene.owner.apply_order(dict(previous), .3)
                self.assertTrue(scene.owner.combat_owned)
                self.assertTrue(scene.owner.stop_allowed)
                self.assertIs(phase, scene.owner._physical_recovery)
                self.assertIs(pivot, scene.owner.pivot)
                self.assertTrue(phase['checking'])
                self.assertIsNone(scene.owner._failed_recovery)
                self.assertEqual([], reviews)
                for name in ('combat_mode', 'move_position',
                             'face_position', 'throttle_override'):
                    self.assertEqual(previous[name], result[name], name)
                self.assertFalse(result['fire_allowed'])


if __name__ == '__main__':
    unittest.main()
