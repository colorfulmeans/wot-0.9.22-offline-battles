"""Protected stationary tasks keep their movement while consuming legal gun targets.

These tests use the complete player controller, original planner/driver, native
point evaluation, trigger admission and actual GunState/battle.shoot accounting.
Only the native geometry and native gun actuator observations are fixtures.
"""
import copy
import unittest
from unittest import mock

from test_player_combat_ownership import OwnershipScene


class CaptureFireHandoffTests(unittest.TestCase):
    def scene(self, features=('drive', 'fire'), limited=False, clip=1, soft_armor=10.):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(features=features, limited=limited, clip=clip, burst=1)
        scene.native_position((45., 0., 45.))
        hard = scene.eligible_enemy(5, armor=10000.)
        scene.pose(hard, (45., 0., 85.))
        soft = scene.eligible_enemy(2, armor=soft_armor)
        scene.pose(soft, (48., 0., 95.) if limited else (65., 0., 85.))
        scene.sample_original_lanes()
        return scene

    def trace_handoffs(self, scene):
        traces = []
        consume = scene.runtime.consume_gun_handoff
        def observe(source, command, target, now):
            original = copy.deepcopy(command)
            result, selected = consume(source, command, target, now)
            if selected is not None and selected['network_id'] == 2 and target['network_id'] == 5:
                for field in ('move_position', 'face_position', 'throttle', 'turn',
                              'brake', 'movement_intent', 'recovery_mode', 'combat_mode'):
                    self.assertEqual(original.get(field), result.get(field), field)
                traces.append(original)
            return result, selected
        scene.runtime.consume_gun_handoff = observe
        return traces

    def run_until_shots(self, scene, count=1, steps=150):
        for unused in range(steps):
            scene.battle._advance_local_gun_to(scene.entity, scene.now)
            scene.tick()
            if len(scene.launches()) >= count:
                return
        self.fail('no committed shot: %r' % scene.runtime.status())

    def test_capture_hold_consumes_alternative_without_moving_the_task(self):
        scene = self.scene()
        scene.runtime.set_mission('capture_base', {})
        traces = self.trace_handoffs(scene)
        initial_ammo = sum(scene.battle._gun_state.ammo)
        saw_conflict = False
        for unused in range(100):
            scene.tick()
            owner = scene.runtime.combat_stop
            candidate = scene.runtime.attack_policy.decision.get('candidate')
            if owner.active and candidate and candidate['target']['network_id'] == 2:
                saw_conflict = True
                self.assertEqual(5, owner.task_order['target_id'])
                self.assertFalse(owner.stop_allowed)
                self.assertEqual((45., 0., 45.), scene.applied_order()['move_position'])
                self.assertEqual(0., scene.battle._sender.forward)
            if scene.launches():
                break
        self.assertTrue(saw_conflict, scene.runtime.status())
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual(initial_ammo - 1, sum(scene.battle._gun_state.ammo))
        self.assertEqual(2, scene.runtime.weapon.target['network_id'])
        self.assertGreater(scene.battle._gun_state.reload_time, 0.)
        self.assertTrue(traces)
        self.assertEqual(traces[-1]['face_position'], scene.control.last_order['face_position'])
        self.assertEqual(traces[-1]['turn'], scene.battle._sender.turn)
        self.assertEqual(traces[-1]['throttle'], scene.battle._sender.forward)

    def test_fire_only_uses_an_admitted_alternative_without_writing_drive(self):
        scene = self.scene(features=('fire',))
        traces = self.trace_handoffs(scene)
        sender = scene.battle._sender
        original = (sender.forward, sender.turn, sender.handbrake)
        self.run_until_shots(scene)
        self.assertTrue(traces)
        self.assertEqual(original, (sender.forward, sender.turn, sender.handbrake))
        self.assertEqual(2, scene.runtime.weapon.target['network_id'])
        self.assertEqual(29, sum(scene.battle._gun_state.ammo))

    def test_original_parking_hold_keeps_face_and_controls_through_gun_handoff(self):
        scene = self.scene()
        original = scene.runtime._mission_order
        def parking(order, now):
            # The original parking owner supplies the hold through its order
            # seam; target admission and all gun consumers remain production.
            result = original(order, now)
            return dict(result, parking_phase='waiting', move_position=(45., 0., 45.),
                        throttle_override=0.)
        scene.runtime._mission_order = parking
        traces = self.trace_handoffs(scene)
        self.run_until_shots(scene)
        self.assertTrue(traces)
        self.assertEqual('waiting', scene.applied_order()['parking_phase'])
        self.assertEqual(traces[-1]['face_position'], scene.control.last_order['face_position'])
        self.assertEqual((traces[-1]['throttle'], traces[-1]['turn']),
                         (scene.battle._sender.forward, scene.battle._sender.turn))

    def test_limited_gun_inside_actual_arc_can_fire_without_a_new_hull_turn(self):
        scene = self.scene(limited=True)
        scene.runtime.set_mission('capture_base', {})
        traces = self.trace_handoffs(scene)
        self.run_until_shots(scene)
        self.assertTrue(traces)
        self.assertEqual(0., scene.battle._sender.turn)
        self.assertEqual(0., scene.battle._sender.forward)
        self.assertFalse(scene.runtime.state['hull_aiming'])
        self.assertEqual(29, sum(scene.battle._gun_state.ammo))

    def test_limited_gun_outside_arc_does_not_gain_turn_then_recovers_inside_arc(self):
        scene = self.scene(limited=True)
        target = scene.battle._runtime.bigworld.entities[2]
        scene.pose(target, (65., 0., 85.))
        scene.runtime.set_mission('capture_base', {})
        for unused in range(70):
            scene.tick()
            self.assertFalse(scene.launches())
            self.assertEqual((0., 0.), (scene.battle._sender.forward, scene.battle._sender.turn))
            self.assertFalse(scene.runtime.state['hull_aiming'])
            self.assertFalse(scene.runtime.attack_policy.fallback)
        scene.pose(target, (48., 0., 95.))
        self.run_until_shots(scene)
        self.assertEqual(2, scene.runtime.weapon.target['network_id'])

    def test_loaded_he_clip_fallback_uses_gun_handoff_without_eight_second_search(self):
        scene = self.scene(clip=3, soft_armor=30.)
        scene.set_he(piercing=1.)
        scene.runtime.set_mission('capture_base', {})
        traces = self.trace_handoffs(scene)
        reasons = set()
        for unused in range(150):
            scene.battle._advance_local_gun_to(scene.entity, scene.now)
            scene.tick()
            reasons.add(scene.runtime.attack_policy.decision['reason'])
            self.assertIsNone(scene.runtime.attack_policy.search_started)
            if scene.launches():
                break
        self.assertIn('current_he_clip_fallback', reasons)
        self.assertTrue(traces)
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual(2, scene.battle._gun_state.clip)
        self.assertEqual(29, sum(scene.battle._gun_state.ammo))
        self.assertEqual(0, scene.launches()[0]['shell_index'])

    def test_limited_single_he_fallback_consumes_the_same_protected_handoff(self):
        scene = self.scene(limited=True, soft_armor=30.)
        scene.set_he(piercing=1.)
        gun = scene.battle._gun_state
        for index, shot in enumerate(gun.shots):
            shot.piercingPower = (1., 1.)
            scene.battle.client.effective_params['gun']['shots'][index]['source_shot'][
                'piercingPower'] = shot.piercingPower
        scene.runtime.set_mission('capture_base', {})
        traces = self.trace_handoffs(scene)
        self.run_until_shots(scene)
        self.assertTrue(traces)
        self.assertEqual('he_fallback_contact', scene.runtime.attack_policy.decision['reason'])
        self.assertEqual(29, sum(gun.ammo))
        self.assertEqual((0., 0.), (scene.battle._sender.forward, scene.battle._sender.turn))

    def test_repeated_capture_shots_and_target_loss_continue_to_another_admitted_enemy(self):
        scene = self.scene()
        scene.runtime.set_mission('capture_base', {})
        self.run_until_shots(scene, count=2, steps=350)
        self.assertEqual(28, sum(scene.battle._gun_state.ammo))
        scene.battle._records['bot:2']['state'].update(alive=False, health=0)
        scene.battle._runtime.bigworld.entities[2].health = 0
        third = scene.eligible_enemy(7, armor=10.)
        scene.pose(third, (20., 0., 85.))
        scene.sample_original_lanes()
        self.run_until_shots(scene, count=3, steps=200)
        self.assertEqual(7, scene.runtime.weapon.target['network_id'])
        self.assertEqual(27, sum(scene.battle._gun_state.ammo))
        self.assertEqual((45., 0., 45.), scene.applied_order()['move_position'])

    def test_new_travel_task_retires_a_prepared_handoff_before_any_shot(self):
        scene = self.scene()
        scene.runtime.set_mission('capture_base', {})
        for unused in range(10):
            scene.tick()
            if scene.runtime._gun_handoff is not None:
                break
        self.assertIsNotNone(scene.runtime._gun_handoff)
        self.assertFalse(scene.launches())
        scene.runtime.set_mission('return_base', {})
        for unused in range(15):
            scene.tick()
            self.assertFalse(scene.launches())
            self.assertFalse(scene.runtime.combat_stop.active)
            self.assertIsNone(scene.runtime._gun_handoff)
            self.assertEqual('team_return_base', scene.applied_order()['combat_mode'])
        self.assertEqual(30, sum(scene.battle._gun_state.ammo))

    def test_stop_and_stale_frame_cannot_consume_an_old_handoff(self):
        for stop in (False, True):
            with self.subTest(stop=stop):
                scene = self.scene()
                scene.runtime.set_mission('capture_base', {})
                for unused in range(10):
                    scene.tick()
                    if scene.runtime._gun_handoff is not None:
                        break
                runtime = scene.runtime
                self.assertIsNotNone(runtime._gun_handoff)
                original_target = next(row for row in runtime.visible_targets() if row['network_id'] == 5)
                command = dict(scene.control.last_order, target_id=5, target_kind='bot')
                if stop:
                    runtime.stop('test_stop')
                result, target = runtime.consume_gun_handoff(runtime.state, command, original_target,
                    scene.now if stop else scene.now + .1)
                self.assertEqual(command, result)
                self.assertIs(original_target, target)
                self.assertFalse(scene.launches())
                scene.doCleanups()

    def test_unadmitted_alternative_cannot_be_promoted_by_a_capture_hold(self):
        scene = self.scene()
        scene.world[:] = [((54., -10., 64.), (57., 20., 68.))]
        lanes = scene.sample_original_lanes()
        self.assertEqual({2: False, 5: True}, lanes)
        scene.runtime.set_mission('capture_base', {})
        for unused in range(40):
            scene.tick()
            self.assertNotIn(2, [row['network_id'] for row in scene.runtime.combat_stop.targets])
            self.assertFalse(scene.launches())
            self.assertIsNone(scene.runtime._gun_handoff)


if __name__ == '__main__':
    unittest.main()
