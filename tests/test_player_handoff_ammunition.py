"""Gun-target execution gates do not rewrite ammunition evidence or ownership.

All cases run the original planner, native point evaluation, PlayerControl and
actual battle.shoot/GunState accounting. Native geometry and actuator observations
come from OwnershipScene; this is not a Windows physics or timing play test.
"""
import unittest

from test_player_combat_ownership import OwnershipScene


class HandoffAmmunitionTests(unittest.TestCase):
    def scene(self, clip=3, burst=1, limited=False, player_id=1):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=clip, burst=burst, limited=limited, player_id=player_id)
        # configure can change the session player identity to exercise the
        # original BOT's advance personality. Publish its real fixture
        # parameters under that same identity for the actual launch boundary.
        scene.battle.client._published_player_effective_params[player_id] = (
            scene.battle.client.effective_params)
        return scene

    def enemy(self, scene, identity, point, armor):
        target = scene.eligible_enemy(identity, armor=armor)
        scene.pose(target, point)
        return target

    def test_he_machinegun_handoff_consumes_one_trigger_group_and_preserves_next_plan(self):
        scene = self.scene(clip=6, burst=3)
        scene.native_position((45., 0., 45.))
        self.enemy(scene, 5, (45., 0., 85.), 10000.)
        self.enemy(scene, 2, (65., 0., 85.), 30.)
        scene.set_he(piercing=1.)
        self.assertEqual({5: True, 2: True}, scene.sample_original_lanes())
        scene.runtime.set_mission('capture_base', {})
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial_ammo = tuple(gun.ammo)
        for unused in range(100):
            scene.tick()
            self.assertIsNone(policy.search_started)
            self.assertEqual(0, gun.shot_index)
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()), scene.runtime.status())
        self.assertEqual('current_he_clip_fallback', policy.decision['reason'])
        self.assertEqual(5, scene.runtime.combat_stop.task_order['target_id'])
        self.assertEqual(2, scene.runtime.weapon.target['network_id'])
        self.assertEqual((0., 0.), (scene.battle._sender.forward, scene.battle._sender.turn))
        # The current HE contact and the next AP load have independent plans.
        self.assertEqual((0, 'he_fallback'),
            (policy.decision['candidate']['shell_index'], policy.decision['candidate']['mode']))
        self.assertEqual((1, 'penetration'),
                         (policy.next_shell, policy.next_plan['mode']))
        next_key = policy.next_plan['key']
        self.assertEqual(1, gun.pending_index)
        self.assertIsNotNone(scene.battle._local_player_burst)
        for tail in (1, 2):
            # Advance the real committed trigger clock and fire its physical
            # tail; do not call another trigger or replace the fire admission.
            self.assertTrue(scene.advance())
            self.assertEqual(tail + 1, len(scene.launches()))
            self.assertEqual(initial_ammo[0] - tail - 1, gun.ammo[0])
            self.assertEqual(initial_ammo[1], gun.ammo[1])
            self.assertEqual(0, gun.shot_index)
            self.assertEqual(1, gun.pending_index)
            self.assertEqual(next_key, policy.next_plan['key'])
            self.assertEqual('penetration', policy.next_plan['mode'])
        launches = scene.launches()
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in launches])
        self.assertEqual([3, 3, 3], [row['burst_count'] for row in launches])
        self.assertEqual(1, len(set(row['burst_group_seq'] for row in launches)))
        self.assertEqual([0, 0, 0], [row['shell_index'] for row in launches])
        self.assertTrue(all(row['is_he'] for row in launches))
        self.assertEqual(3, gun.clip)
        self.assertEqual(3, scene.control.shot_commits)
        self.assertIsNone(scene.battle._local_player_burst)

    def test_unconsumable_higher_he_damage_keeps_evidence_and_fires_original_target(self):
        scene = self.scene(player_id=2)
        self.enemy(scene, 5, (0., 0., 220.), 40.)
        self.enemy(scene, 2, (40., 0., 240.), 10.)
        scene.set_he(piercing=1.)
        self.assertEqual({5: True, 2: True}, scene.sample_original_lanes())
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial_ammo = tuple(gun.ammo)
        saw_execution_filter = False
        for unused in range(100):
            scene.tick()
            self.assertEqual(('advance', 5),
                (scene.original_order()['combat_mode'], scene.original_order()['target_id']))
            self.assertIsNone(policy.search_started)
            self.assertIsNone(policy.reload_authority)
            self.assertEqual(0, gun.shot_index)
            candidate = policy.decision.get('candidate')
            best = policy._best_he(0)
            if (candidate is not None and candidate['mode'] == 'he_fallback' and
                    candidate['target']['network_id'] == 5 and best is not None and
                    best['target']['network_id'] == 2):
                saw_execution_filter = True
                self.assertGreater(best['expected_damage'], candidate['expected_damage'])
                self.assertTrue(policy._executable(best, 'he_fallback'))
                self.assertFalse(scene.runtime.attack_candidate_consumable(best))
                self.assertTrue(scene.runtime.attack_candidate_consumable(candidate))
                self.assertEqual((True, 'reachable', 'clear'),
                                 (best['contact'], best['mechanical'], best['line']))
                self.assertEqual((1, 'penetration'),
                                 (policy.next_shell, policy.next_plan['mode']))
            if scene.launches():
                break
        self.assertTrue(saw_execution_filter, policy.status())
        self.assertEqual(1, len(scene.launches()), scene.runtime.status())
        self.assertEqual(5, scene.runtime.weapon.target['network_id'])
        self.assertEqual([0], [row['shell_index'] for row in scene.launches()])
        self.assertEqual((initial_ammo[0] - 1, initial_ammo[1]), tuple(gun.ammo))
        self.assertEqual(2, gun.clip)
        self.assertEqual(1, gun.pending_index)

    def test_driver_margin_refusal_stays_positive_until_original_target_can_fire(self):
        scene = self.scene(clip=1, limited=True)
        scene.native_position((45., 0., 45.))
        original = self.enemy(scene, 5, (45., 0., 85.), 10000.)
        self.enemy(scene, 2, (51., 0., 85.), 10.)
        self.assertEqual({5: True, 2: True}, scene.sample_original_lanes())
        scene.runtime.set_mission('capture_base', {})
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial_ammo = tuple(gun.ammo)
        saw_refused_positive = False
        reasons = set()
        for unused in range(60):
            scene.tick()
            reasons.add(policy.decision['reason'])
            # The point fits the native gun arc but the unchanged driver's
            # safety margin would demand a new hull turn. Its rejection is
            # an execution boundary, never a negative armour certificate.
            rows = [row for row in policy._rows_for('penetration', 0, fresh_line=True)
                    if row['target']['network_id'] == 2 and policy._executable(row)]
            if rows:
                saw_refused_positive = True
                self.assertFalse(scene.runtime.attack_candidate_consumable(rows[0]))
                self.assertFalse(policy._all_failed((0,)))
                self.assertEqual('passed', rows[0]['armor'])
            self.assertFalse(scene.launches())
            self.assertEqual(initial_ammo, tuple(gun.ammo))
            self.assertEqual(0, gun.shot_index)
            self.assertIsNone(gun.pending_index)
            self.assertIsNone(policy.search_started)
            self.assertIsNone(policy.reload_authority)
            self.assertFalse(policy.fallback)
            self.assertEqual((0., 0.), (scene.battle._sender.forward, scene.battle._sender.turn))
        self.assertTrue(saw_refused_positive, policy.status())
        self.assertIn('current_shot_navigation_owned', reasons)
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(original.typeDescriptor, component).materials[0].armor = 10.
        # A real new target pose invalidates its old plate observation.
        scene.pose(original, (45.1, 0., 85.))
        for unused in range(100):
            scene.tick()
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()), scene.runtime.status())
        self.assertEqual(5, scene.runtime.weapon.target['network_id'])
        self.assertEqual((initial_ammo[0] - 1, initial_ammo[1]), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)


if __name__ == '__main__':
    unittest.main()
