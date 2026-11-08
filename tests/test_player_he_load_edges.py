"""Ordinary HE's reduced trial has one contract at every load entry point."""
import unittest

from test_player_rebuilt_attack_policy import Observations


class OrdinaryHELoadEdgesTests(unittest.TestCase):
    def scene(self, clips=6, loaded=0, ammo=(30, 0, 30), points=1):
        scene = Observations(clips=clips, targets=1, points=points,
                             he_validation='single_point')
        scene.frame.update(loaded=loaded, ammo=ammo)
        scene.he(80.)
        scene.prime()
        scene.prime('he_fallback')
        return scene

    def assert_he_plan(self, scene, decision, action):
        self.assertEqual(action, decision['action'])
        self.assertEqual(2, decision['shell_index'])
        self.assertIsNotNone(decision['candidate'])
        self.assertEqual('he_fallback', decision['candidate']['mode'])
        self.assertIs(decision['candidate']['contact'], True)
        self.assertEqual(2, scene.policy.next_shell)
        self.assertEqual('verified_he_fallback', scene.policy.next_status)
        next_plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual(2, next_plan['shell_index'])

    def test_ap_clip_preserves_eight_seconds_then_loads_the_verified_ordinary_he(self):
        scene = self.scene()
        first = scene.tick(0.)
        self.assertEqual('search_penetration', first['action'])
        self.assertEqual(0., scene.policy.search_started)
        before = scene.tick(7.9)
        self.assertEqual('search_penetration', before['action'])
        self.assertIsNone(scene.policy.reload_authority)
        decision = scene.tick(8.)
        self.assert_he_plan(scene, decision, 'reload_clip')
        self.assertTrue(decision['early_reload'])
        self.assertEqual('verified', decision['replacement_status'])

    def test_exhausted_single_or_clip_keeps_verified_he_candidate_and_next(self):
        for clips in (1, 6):
            with self.subTest(clips=clips):
                scene = self.scene(clips=clips, ammo=(0, 0, 30))
                scene.frame['clip'] = 0
                decision = scene.tick(0.)
                self.assert_he_plan(scene, decision,
                                    'reload_clip' if clips > 1 else 'switch_shell')
                self.assertFalse(decision['early_reload'])
                self.assertIsNone(scene.policy.search_started)

    def test_empty_clip_keeps_verified_he_candidate_with_or_without_old_ap_stock(self):
        for loaded, ammo in ((0, (30, 0, 30)), (2, (0, 0, 30))):
            with self.subTest(loaded=loaded):
                scene = self.scene(loaded=loaded, ammo=ammo)
                scene.frame['clip'] = 0
                decision = scene.tick(0.)
                self.assert_he_plan(scene, decision, 'reload_clip')
                self.assertFalse(decision['early_reload'])
                self.assertIsNone(scene.policy.search_started)

    def test_expired_he_contact_cannot_become_a_verified_reload_candidate(self):
        scene = self.scene(ammo=(0, 0, 30))
        scene.frame.update(clip=0, pose=('source', 1))
        decision = scene.tick(0., background=False)
        self.assertEqual('reload_clip', decision['action'])
        self.assertIsNone(decision['candidate'])
        self.assertIsNone(scene.policy.next_at_edge()[0])

    def test_current_he_clip_keeps_its_tail_while_next_ap_stays_independent(self):
        scene = self.scene(loaded=2, ammo=(30, 0, 30))
        scene.passed(0)
        scene.prime()
        for now in (0., 8.1):
            decision = scene.tick(now)
            self.assertEqual('aim', decision['action'])
            self.assertEqual((2, 'he_fallback'),
                (decision['candidate']['shell_index'], decision['candidate']['mode']))
            self.assertIsNone(scene.policy.reload_authority)
            self.assertIsNone(scene.policy.search_started)
            self.assertEqual(0, scene.policy.next_shell)
        scene.frame['trigger_active'] = True
        decision = scene.tick(8.2)
        self.assertEqual('trigger_active', decision['action'])
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertEqual(0, scene.policy.next_at_edge()[0]['shell_index'])

    def test_settling_source_can_consume_fresh_he_after_real_atomic_ap_failure(self):
        scene = Observations(targets=1, points=9, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(30, 0, 30))
        scene.he(80.)
        decision = None
        for step in range(31):
            scene.frame['pose'] = ('source', step)
            decision = scene.tick(step * .1)
            self.assertLessEqual(scene.policy._used['foreground'], 2)
            self.assertIsNone(scene.policy.search_started)
            if decision['action'] == 'aim':
                break
        self.assertEqual('aim', decision['action'], decision)
        self.assertEqual('he_fallback', decision['candidate']['mode'])
        self.assertEqual(scene.frame['pose'], decision['candidate']['pose_stamp'][1])
        self.assertTrue(scene.policy._all_failed((0,)),
                        'current-frame AP failure is still required before contact use')
        probes = [call for call in scene.calls if call[2] == 2 and call[-1] == 'penetration']
        self.assertEqual(1, len(probes))


if __name__ == '__main__':
    unittest.main()
