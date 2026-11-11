"""Production policy using finite native-observation fixtures."""
import unittest

from test_player_rebuilt_attack_policy import Observations
from gui.mods.offline_lan_0922.vehicle_control.ordered_attack import OrderedAttack


class OrderedPlayerAttackTests(unittest.TestCase):
    def scene(self, **options):
        scene = Observations(**options)
        scene.policy.ordered = OrderedAttack()
        return scene

    def test_native_block_keeps_other_green_point_of_same_target(self):
        scene = self.scene(targets=3, points=2)
        scene.passed(0, target=1, sample=0)
        scene.passed(0, target=1, sample=1)
        scene.passed(0, target=2)
        scene.prime()
        first = scene.tick(0., background=False)['candidate']
        self.assertEqual((0, ('bot', 1), 0, 'penetration'), first['key'])
        scene.policy.admission_failed(first, 'auto_front_vehicle',
            dict(kind='vehicle', actor_key=('bot', 3), hostile=True))
        for now in (.1, 2.1):
            scene.calls.clear()
            decision = scene.tick(now, background=False)
            self.assertEqual((0, ('bot', 1), 1, 'penetration'), decision['candidate']['key'])
            self.assertEqual([], scene.calls)
        self.assertEqual('enemy_blocked', scene.policy.rows[first['key']]['line'])

    def test_a_complete_shell_sweep_precedes_reload_and_he_stays_on_c(self):
        scene = self.scene(clips=6, targets=3, points=1)
        scene.value(0, target=2, line='world_blocked', armor='unknown')
        scene.he(22., target=3)
        for time in range(4):
            decision = scene.tick(float(time))
            if decision['action'] == 'reload_clip':
                break
        self.assertEqual(('reload_clip', 1), (decision['action'], decision['shell_index']))
        self.assertEqual([0, 0, 0], [call[2] for call in scene.calls])
        self.assertEqual([('bot', 1), ('bot', 2), ('bot', 3)],
                         [call[3] for call in scene.calls])
        scene.frame['loaded'] = 1
        for time in range(4, 8):
            decision = scene.tick(float(time))
            if decision['action'] == 'reload_clip':
                break
        self.assertEqual(('reload_clip', 2), (decision['action'], decision['shell_index']))
        scene.frame['loaded'] = 2
        scene.calls.clear()
        decision = scene.tick(8.)
        self.assertEqual((2, ('bot', 3), 0, 'he_fallback'), decision['candidate']['key'])
        self.assertEqual([('bot', 3), ('bot', 3)], [call[3] for call in scene.calls])
        calls = list(scene.calls)
        self.assertEqual((None, 'ordered_lowest_penetration_still_failed'),
                         scene.policy.next_at_edge())
        self.assertEqual(calls, scene.calls)
        scene.move_target(3, 1)
        scene.tick(9., background=False)
        calls = list(scene.calls)
        self.assertEqual(0, scene.policy.next_at_edge()[0]['shell_index'])
        self.assertEqual(calls, scene.calls)

    def test_other_points_then_second_vehicle_use_the_same_loaded_shell(self):
        scene = self.scene(clips=6, targets=3, points=2)
        scene.value(0, target=1, line='enemy_blocked', armor='unknown')
        scene.passed(0, target=2)
        scene.passed(1, target=1)
        scene.passed(0, target=3)
        for step in range(4):
            decision = scene.tick(float(step))
            if decision['action'] == 'aim':
                break
            self.assertEqual('wait', decision['action'])
        self.assertEqual((0, ('bot', 2), 0, 'penetration'), decision['candidate']['key'])
        self.assertEqual([(0, ('bot', 1), 0), (0, ('bot', 1), 1), (0, ('bot', 2), 0)],
                         [call[2:5] for call in scene.calls])

    def test_pending_is_not_a_shell_exhaustion_or_a_retarget(self):
        scene = self.scene(targets=2, points=1)
        scene.value(0, target=1, line='pending', armor='unknown')
        scene.passed(0, target=2)
        scene.prime()
        decision = scene.tick(0.)
        self.assertEqual(('wait', 'ordered_current_target_pending'),
                         (decision['action'], decision['reason']))

    def test_no_he_releases_after_the_mounted_penetration_sweep(self):
        scene = self.scene(targets=2, points=1, he=False)
        scene.frame['ammo'] = (30, 0)
        decision = scene.tick(0.)
        self.assertEqual(('navigate', 'ordered_no_he'), (decision['action'], decision['reason']))
