"""Production policy using finite native-observation fixtures."""
import unittest
from types import SimpleNamespace

from test_player_rebuilt_attack_policy import Observations
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import AttackPolicy
from gui.mods.offline_lan_0922.vehicle_control.ordered_attack import OrderedAttack


class OrderedPlayerAttackTests(unittest.TestCase):
    def scene(self, **options):
        scene = Observations(**options)
        scene.policy.ordered = OrderedAttack()
        return scene

    def siege_he(self, points, movable=True):
        scene = Observations(targets=2, points=points, he_validation='single_point')
        owner = SimpleNamespace(combat_owned=True, stop_allowed=movable,
            receipt=dict(selected=('bot', 1), episode=1), can_review_route_attack=lambda: False,
            candidate_consumable=lambda row: True)
        runtime = SimpleNamespace(combat_stop=owner, siege_capable=lambda: True)
        scene.policy = AttackPolicy(runtime, evaluator=scene, ordered_he=True)
        scene.frame.update(loaded=2, ordered=True)
        return scene

    def test_siege_he_skips_block_then_recovers_same_vehicle_point_when_clear(self):
        scene = self.siege_he(2)
        scene.value(2, line='enemy_blocked', armor='unknown')
        scene.he(10., sample=0)
        scene.he(55., sample=1)
        scene.passed(2, target=2)
        decision = scene.tick(0.)
        self.assertEqual(('aim', ('bot', 1), 1, 'he_fallback'),
                         (decision['action'], decision['candidate']['target_key'],
                          decision['candidate']['sample'], decision['candidate']['mode']))
        self.assertTrue(scene.calls)
        self.assertEqual({('bot', 1)}, {row[3] for row in scene.calls})
        self.assertFalse(any(row[4:] == (0, 'he_fallback') for row in scene.calls))
        scene.frame['line_revision'] += 1
        scene.passed(2)
        decision = scene.tick(.2)
        self.assertEqual(('aim', 0, 'penetration'), (decision['action'],
                         decision['candidate']['sample'], decision['candidate']['mode']))

    def test_all_blocked_siege_he_uses_existing_clear_lane_then_checks_new_target(self):
        scene = self.siege_he(1)
        scene.value(2, line='unknown', mechanical='hull_laying', armor='unknown',
            stationary_plan=dict(status='proved', proof=dict(proved=True), line='world_blocked'))
        scene.passed(2, target=2)
        scene.policy.frame = scene.snapshot(0.)
        other = next(job for job in scene.policy._jobs(shell_index=2) if job[0][1] == ('bot', 2))
        scene.policy._evaluate(other, 0., 'background')
        scene.calls.clear()
        decision = scene.tick(.1)
        self.assertEqual(('wait', 'blocked_target_handoff'), (decision['action'], decision['reason']))
        self.assertEqual(('bot', 2), scene.policy.current_target_key())
        self.assertEqual({('bot', 1)}, {row[3] for row in scene.calls})
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertEqual('aim', scene.tick(.2)['action'])

    def test_siege_he_only_requests_position_for_stable_block_with_motion_permission(self):
        for lane, movable, action in (('world_blocked', True, 'firing_position'),
                                      ('world_blocked', False, 'navigate'),
                                      ('friendly_blocked', True, 'navigate'),
                                      ('enemy_blocked', True, 'navigate')):
            with self.subTest(lane=lane, movable=movable):
                scene = self.siege_he(1, movable=movable)
                scene.value(2, line=lane, armor='unknown')
                scene.value(2, target=2, line='pending', armor='unknown')
                decision = scene.tick(0.)
                self.assertEqual(action, decision['action'], decision)
                self.assertEqual({('bot', 1)}, {row[3] for row in scene.calls})
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_new_siege_admission_uses_confirmed_target_while_old_target_is_visible(self):
        scene = self.siege_he(1)
        scene.value(2, line='world_blocked', armor='unknown')
        scene.passed(2, target=2)
        self.assertEqual('firing_position', scene.tick(0.)['action'])
        scene.policy.runtime.combat_stop.receipt.update(episode=2, selected=('bot', 2))
        scene.calls.clear()
        result = scene.tick(.1)
        self.assertEqual(('aim', ('bot', 2)), (result['action'], result['candidate']['target_key']))
        self.assertEqual({('bot', 2)}, {row[3] for row in scene.calls})

    def test_equal_penetration_damage_order_qualifies_a_distinct_higher_load(self):
        scene = self.scene(targets=1, points=1, he=False)
        first, second = scene.frame['shells']
        first.update(piercing=200., nominal_damage=500.)
        second.update(piercing=200., nominal_damage=400.)
        scene.frame['loaded'] = 1
        decision = scene.tick(0., background=False)
        self.assertEqual(('switch_shell', 0), (decision['action'], decision['shell_index']))

        scene.frame['loaded'] = 0
        scene.move_target(1, 1.)
        scene.passed(0)
        scene.tick(.1, background=False)
        scene.policy.ordered.shot_committed(0)
        plan, reason = scene.policy.next_at_edge(trigger=dict(shell_index=0))
        self.assertEqual((1, 'higher_penetration_cycle_finished'),
                         (plan['shell_index'], reason))

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

    def test_he_uses_the_first_clear_penetration_on_the_held_vehicle(self):
        scene = self.scene(targets=2, points=4, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.value(2, sample=0, line='enemy_blocked', armor='unknown')
        scene.passed(2, sample=2)
        scene.value(2, sample=3, line='pending', armor='unknown')
        scene.passed(2, target=2)
        for step in range(4):
            decision = scene.tick(float(step), background=False)
            if decision['action'] == 'aim':
                break
        self.assertEqual((2, ('bot', 1), 2, 'penetration'), decision['candidate']['key'])
        self.assertEqual({(2, ('bot', 1), 'penetration')},
                         {(row[2], row[3], row[5]) for row in scene.calls})
        self.assertEqual({0, 1, 2}, {row[4] for row in scene.calls})

    def test_scatter_refusal_uses_other_points_before_the_next_vehicle(self):
        scene = self.scene(targets=2, points=2)
        scene.passed(0, target=1, sample=0)
        scene.passed(0, target=1, sample=1)
        scene.passed(0, target=2)
        scene.prime()
        blocker = dict(kind='world', ray_stage='scatter', point=(0., 2., 10.))
        first = scene.tick(0., background=False)['candidate']
        self.assertEqual((0, ('bot', 1), 0, 'penetration'), first['key'])
        scene.policy.admission_failed(first, 'auto_world_blocked', blocker)
        second = scene.tick(.1, background=False)['candidate']
        self.assertEqual((0, ('bot', 1), 1, 'penetration'), second['key'])
        scene.policy.admission_failed(second, 'auto_world_blocked', blocker)
        third = scene.tick(.2, background=False)['candidate']
        self.assertEqual((0, ('bot', 2), 0, 'penetration'), third['key'])

    def test_he_fallback_skips_the_same_physically_blocked_penetration_sample(self):
        scene = self.scene(targets=2, points=2, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.passed(2, target=1, sample=0)
        scene.he(100., target=1, sample=0)
        scene.he(20., target=1, sample=1)
        scene.he(200., target=2)
        scene.prime()
        first = scene.tick(0., background=False)['candidate']
        self.assertEqual((2, ('bot', 1), 0, 'penetration'), first['key'])
        scene.policy.admission_failed(first, 'auto_world_blocked',
            dict(kind='world', ray_stage='scatter', point=(0., 2., 10.)))
        decision = scene.tick(.1, background=False)
        self.assertEqual((2, ('bot', 1), 1, 'he_fallback'), decision['candidate']['key'])

    def test_he_waits_for_the_best_unblocked_blast_on_the_same_vehicle(self):
        scene = self.scene(targets=2, points=4, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.value(2, sample=1, line='enemy_blocked', armor='unknown')
        scene.he(9., sample=0)
        scene.he(900., sample=1)
        scene.he(32., sample=2)
        scene.value(2, sample=3, mode='he_fallback', line='pending')
        scene.he(800., target=2)
        for step in range(5):
            decision = scene.tick(float(step), background=False)
            self.assertNotEqual('aim', decision['action'])
        self.assertEqual(dict(total=3, observed=2, pending=1), scene.policy.he_comparison)
        scene.he(15., sample=3)
        decision = scene.tick(5., background=False)
        self.assertEqual((2, ('bot', 1), 2, 'he_fallback'), decision['candidate']['key'])
        self.assertEqual(32., decision['candidate']['expected_damage'])
        self.assertEqual({('bot', 1)}, {row[3] for row in scene.calls})
        self.assertEqual({0, 2, 3}, {row[4] for row in scene.calls if row[5] == 'he_fallback'})

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
        self.assertEqual((None, 'keep_mounted_shell'), scene.policy.next_at_edge())
        context = dict(automatic=True, candidate=decision['candidate'])
        for unused in range(2):
            scene.policy.shot_committed(dict(shell_index=2), dict(player_control=context))
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
