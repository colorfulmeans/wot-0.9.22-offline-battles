"""The reviewed HE planning split, independent of physical shell mechanics."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_player_rebuilt_attack_policy import Observations
from gui.mods.offline_lan_0922.player_control import ammunition_validation as roles


class AmmunitionValidationTests(unittest.TestCase):
    def test_only_the_five_reviewed_gun_shell_pairs_are_full_he(self):
        self.assertEqual(5, len(roles.FULL_VALIDATION_HE))
        for gun, shell in roles.FULL_VALIDATION_HE:
            self.assertEqual(roles.FULL, roles.validation_mode(gun, shell, roles.HE))
            self.assertEqual(roles.SINGLE_POINT,
                roles.validation_mode('china:' + gun.split(':')[1], shell, roles.HE))
        for gun, shell in (
                ('uk:_105mm_Gun_L7', 'uk:_105mm_HE_L7'),
                ('uk:_183mm_L4', 'uk:_183mm_HE_Mk1'),
                ('uk:_5_5inch_AT_Gun', 'uk:_5_5inch_HE_Mk_1T'),
                ('uk:Gun_FV4202', 'uk:_105mm_HESH_L7')):
            self.assertEqual(roles.SINGLE_POINT, roles.validation_mode(gun, shell, roles.HE))
        for kind in ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR', 'HOLLOW_CHARGE'):
            self.assertEqual(roles.FULL, roles.validation_mode(None, None, kind))
        self.assertEqual(roles.SINGLE_POINT, roles.shell_mode(dict(is_he=True)))

    def test_failed_ordinary_he_tries_one_point_then_uses_current_he_contact(self):
        scene = Observations(targets=3, points=3, he_validation=roles.SINGLE_POINT)
        scene.frame.update(loaded=2, ammo=(0, 0, 10))
        scene.he(90.)
        for tick in range(12):
            scene.frame['pose'] = ('settling_source', tick)
            decision = scene.tick(tick * .1)
        probes = [call for call in scene.calls if call[2] == 2 and call[-1] == 'penetration']
        self.assertEqual(1, len(probes))
        self.assertEqual((('bot', 1), 0), probes[0][3:5])
        self.assertEqual('aim', decision['action'])
        self.assertEqual('he_fallback', decision['candidate']['mode'])
        self.assertIsNone(scene.policy.search_started)

    def test_failed_ordinary_he_can_switch_to_a_verified_original_rank(self):
        scene = Observations(targets=2, points=3, he_validation=roles.SINGLE_POINT)
        scene.frame['loaded'] = 2
        scene.passed(0, target=2, sample=2)
        for tick in range(20):
            decision = scene.tick(tick * .1)
            if decision['action'] == 'switch_shell':
                break
        self.assertEqual('switch_shell', decision['action'])
        self.assertEqual(0, decision['shell_index'])
        self.assertEqual(1, len([c for c in scene.calls if c[2] == 2 and c[-1] == 'penetration']))
        self.assertIsNone(scene.policy.search_started)

    def test_unknown_and_blocked_he_are_not_a_failed_trial(self):
        for line, armor, mechanical in (('clear', 'unknown', 'reachable'),
                ('world_blocked', 'unknown', 'reachable'),
                ('friendly_blocked', 'failed', 'reachable'),
                ('clear', 'failed', 'mechanical_limited')):
            with self.subTest(line=line, armor=armor, mechanical=mechanical):
                scene = Observations(targets=2, points=3, he_validation=roles.SINGLE_POINT)
                scene.frame['loaded'] = 2
                scene.value(2, line=line, armor=armor, mechanical=mechanical)
                scene.passed(0)
                scene.he(80.)
                for tick in range(8):
                    decision = scene.tick(tick * .1)
                self.assertNotEqual('switch_shell', decision['action'])
                self.assertFalse((decision.get('candidate') or {}).get('mode') == 'he_fallback')
                self.assertIsNone(scene.policy.search_started)

    def test_single_he_waits_for_late_alternative_while_source_keeps_settling(self):
        scene = Observations(targets=1, points=7, he_validation=roles.SINGLE_POINT)
        scene.frame.update(loaded=2, ammo=(30, 0, 10))
        scene.allow_atomic = False
        scene.policy.background_budget = 1
        scene.passed(0, sample=6)
        scene.he(90.)
        switched = False
        for tick in range(15):
            scene.frame['pose'] = ('settling_source', tick)
            decision = scene.tick(tick * .1)
            if decision['action'] == 'switch_shell':
                switched = True
                self.assertEqual(0, decision['shell_index'])
                break
            self.assertFalse(scene.policy.fallback)
            self.assertNotEqual('aim', decision['action'])
        self.assertTrue(switched)

    def test_same_frame_failed_trial_is_not_a_next_launch_proof(self):
        scene = Observations(targets=1, points=1, he_validation=roles.SINGLE_POINT)
        scene.frame.update(loaded=0, ammo=(1, 30, 10))
        scene.passed(0)
        scene.passed(1)
        scene.tick(0.)
        plan, reason = scene.policy.next_at_edge()
        self.assertEqual('verified', reason)
        self.assertEqual(1, plan['shell_index'])
        self.assertTrue(all(row['shell_index'] != 2 for row in scene.policy.next_proofs))
        domain = scene.policy._failure_domain((2,))
        self.assertFalse(domain['all_failed'])
        self.assertEqual(1, domain['single_point_failed'])
        self.assertEqual(0, domain['failed'])

    def test_whitelisted_he_still_searches_later_points_and_keeps_clip(self):
        for clips in (1, 6):
            scene = Observations(clips=clips, targets=2, points=3)
            scene.frame['loaded'] = 2
            scene.frame['shells'][2]['validation_mode'] = roles.FULL
            scene.passed(2, target=1, sample=2)
            for tick in range(6):
                decision = scene.tick(tick * .1)
                if decision['action'] == 'aim':
                    break
            self.assertEqual(('aim', 2), (decision['action'], decision['candidate']['sample']))
            self.assertIsNone(scene.policy.reload_authority)

    def test_atomic_rate_limit_survives_only_combat_domain_reset(self):
        scene = Observations(targets=2, points=3, he=False)
        scene.allow_atomic = False
        scene.frame['combat_signature'] = ('admitted', 1)
        scene.tick(0., background=False)
        self.assertEqual(1, scene.atomic_calls)
        scene.frame['combat_signature'] = ('admitted', 2)
        scene.tick(.05, background=False)
        self.assertEqual(1, scene.atomic_calls)
        scene.tick(2.01, background=False)
        self.assertEqual(2, scene.atomic_calls)
        scene.frame['identity'] = ('round', 'replacement_gun')
        scene.tick(2.02, background=False)
        self.assertEqual(3, scene.atomic_calls)


if __name__ == '__main__':
    unittest.main()
