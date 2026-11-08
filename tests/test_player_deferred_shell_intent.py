"""A proposed load cannot operate the gun before the native load accepts it.

The finite evaluator supplies armour facts; policy update/order projection and
the runtime's manual-reload guard are real. Native launch/debit integration is
covered independently by test_player_attack_native_tracking_continuity.
"""
from types import SimpleNamespace
import unittest

from test_player_rebuilt_attack_policy import Observations
from gui.mods.offline_lan_0922.player_control.full_runtime import FullPlayerRuntime


class DeferredShellIntentTests(unittest.TestCase):
    @staticmethod
    def original_order():
        return dict(target_kind='bot', target_id=1, combat_mode='engage',
            move_position=(0., 0., 0.), face_position=(0., 0., 101.),
            aim_position=(0., .5, 101.), throttle_override=0.,
            route_id='original-route', route_index=3)

    @staticmethod
    def manual_reload_runtime(policy, loaded=2):
        gun = SimpleNamespace(reload_time=3., shot_index=loaded, clip_size=1,
                              burst_count=1, ammo=(30, 0, 30))
        return SimpleNamespace(_live=lambda: True, _mission_brakes=lambda: False,
            features={'drive', 'fire'}, combat_stop=SimpleNamespace(active=True),
            attack_policy=policy, owner=SimpleNamespace(), gun=gun,
            _manual_shell=(gun, loaded, 'CURRENT_SHELLS'))

    def assert_original_control(self, policy):
        original = self.original_order()
        result = policy.apply_order(original)
        self.assertEqual(original, {key: result[key] for key in original})
        self.assertFalse(result['fire_allowed'])

    def test_manual_he_reload_keeps_current_intent_while_ap_candidates_alternate(self):
        scene = Observations(targets=3, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, reloading=True, ammo=(30, 0, 30))
        current_key = (2, ('bot', 1), 0, 'he_fallback')
        scene.policy.selected = current_key
        scene.he(80., target=1)
        runtime = self.manual_reload_runtime(scene.policy)
        planned = []
        for step in range(6):
            chosen = 2 + step % 2
            for target in (2, 3):
                scene.value(0, target=target,
                            armor='passed' if target == chosen else 'failed')
            scene.frame['pose'] = ('source', step)
            scene.prime()
            scene.prime('he_fallback')
            decision = scene.tick(step * .1, background=False)
            self.assertEqual('switch_shell', decision['action'])
            self.assertEqual(('bot', chosen), decision['candidate']['target_key'])
            planned.append(decision['candidate']['target_key'])
            self.assertEqual(current_key, scene.policy.selected)
            self.assert_original_control(scene.policy)
            FullPlayerRuntime._apply_shell_intent(runtime)
            self.assertEqual(2, runtime.gun.shot_index)
            self.assertIsNone(scene.policy.loading_plan)
            trial = scene.policy.status()['ordinary_he_trials'][0]
            self.assertEqual(('bot', 1), trial['target'])
            self.assertTrue(trial['failed'])
        self.assertEqual({('bot', 2), ('bot', 3)}, set(planned))
        he_trials = [call for call in scene.calls
                     if call[2] == 2 and call[-1] == 'penetration']
        self.assertEqual([('bot', 1)], [call[3] for call in he_trials])

    def test_empty_clip_load_proposal_keeps_the_original_target_and_facing(self):
        scene = Observations(clips=6, targets=2, points=1,
                             he_validation='single_point')
        scene.frame.update(clip=0, ammo=(30, 0, 30))
        scene.policy.selected = (0, ('bot', 1), 0, 'penetration')
        scene.passed(0, target=2)
        scene.prime()
        decision = scene.tick(0., background=False)
        self.assertEqual('reload_clip', decision['action'])
        self.assertEqual(('bot', 2), decision['candidate']['target_key'])
        self.assertEqual((0, ('bot', 1), 0, 'penetration'), scene.policy.selected)
        self.assert_original_control(scene.policy)

    def test_late_load_candidate_cannot_publish_a_different_aim_solution(self):
        scene = Observations(targets=2, points=1, he_validation='single_point')
        scene.frame.update(loaded=2, reloading=True, ammo=(30, 0, 30))
        scene.passed(0, target=2)
        scene.prime()
        decision = scene.tick(0., background=False)
        self.assertEqual('switch_shell', decision['action'])
        original = self.original_order()
        original.update(target_id=2, aim_position=(0., .25, 102.))
        command, target = scene.policy.select_command({}, original,
            decision['candidate']['target'], 0.)
        self.assertEqual(original['aim_position'], command['aim_position'])
        self.assertNotIn('_player_attack_solution', command)
        self.assertFalse(command['fire_allowed'])
        self.assertIs(target, decision['candidate']['target'])

    def test_only_accepted_load_plan_establishes_the_new_shell_aim(self):
        scene = Observations(targets=2, points=2, he_validation='single_point')
        scene.frame.update(loaded=2, reloading=True, ammo=(30, 0, 30))
        scene.passed(0, target=2, sample=1)
        scene.prime()
        decision = scene.tick(0., background=False)
        self.assertEqual('switch_shell', decision['action'])
        plan = decision['candidate']
        self.assertIsNone(scene.policy.loading_plan)
        # This is the policy callback used only after the native consumer has
        # accepted CURRENT/R. It carries intention, never a launch proof.
        scene.policy.load_started(0, plan)
        scene.frame.update(loaded=0, clip=0, reloading=True)
        result = scene.tick(.1, background=False)
        self.assertEqual(('aim', 'preaiming'), (result['action'], result['phase']))
        self.assertEqual(plan['key'], result['candidate']['key'])
        self.assertEqual(plan['key'], scene.policy.selected)
        self.assertIs(plan, scene.policy.loading_plan)
        self.assertFalse(scene.policy.apply_order(self.original_order())['fire_allowed'])
        scene.frame.update(clip=1, reloading=False)
        result = scene.tick(.2, background=False)
        self.assertEqual('aim', result['action'])
        self.assertEqual(plan['key'], result['candidate']['key'])
        order = scene.policy.apply_order(self.original_order())
        self.assertEqual(2, order['target_id'])
        self.assertTrue(order['fire_allowed'])


if __name__ == '__main__':
    unittest.main()
