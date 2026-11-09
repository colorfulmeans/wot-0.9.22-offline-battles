"""Current ammunition execution and global penetration-search admission.

These finite observation fixtures do not substitute policy decisions. They
exercise the user-approved distinction between a loaded HE round and NEXT,
and between absent evidence and confirmed global armour failure.
"""
import copy
import unittest

from test_player_rebuilt_attack_policy import Observations


class LoadedHEPolicyTests(unittest.TestCase):
    def test_every_loaded_he_uses_its_own_fallback_before_a_better_next_shell(self):
        for clips in (1, 6):
            for validation in ('full', 'single_point'):
                with self.subTest(clips=clips, validation=validation):
                    scene = Observations(clips=clips, targets=1, points=1,
                                         he_validation=validation)
                    scene.frame['loaded'] = 2
                    scene.passed(0)
                    scene.he(30.)
                    scene.prime()
                    scene.prime('he_fallback')
                    decision = scene.tick(0.)
                    self.assertEqual('aim', decision['action'], decision)
                    self.assertEqual((2, 'he_fallback'),
                                     (decision['candidate']['shell_index'],
                                      decision['candidate']['mode']))
                    self.assertIsNone(scene.policy.search_authority)
                    self.assertIsNone(scene.policy.reload_authority)
                    self.assertEqual(0, scene.policy.next_shell)

    def test_pending_next_ammunition_cannot_block_ordinary_loaded_he(self):
        scene = Observations(targets=1, points=1, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.allow_atomic = False
        for index in (0, 1):
            scene.value(index, armor='unknown', line='unknown')
        scene.he(0.)
        scene.prime()
        scene.prime('he_fallback')
        decision = scene.tick(0.)
        self.assertEqual('aim', decision['action'], decision)
        self.assertEqual(2, decision['candidate']['shell_index'])
        self.assertEqual(0., decision['candidate']['expected_damage'])
        self.assertIsNone(scene.policy.next_plan)

    def test_higher_damage_other_he_is_next_not_current_replacement(self):
        scene = Observations(targets=1, points=1, he_validation='single_point')
        scene.frame['loaded'] = 2
        alternate = copy.deepcopy(scene.frame['shells'][2])
        alternate.update(index=3, signature=('other-he', 1))
        scene.frame['shells'] += (alternate,)
        scene.frame['ammo'] += (30,)
        scene.he(10., index=2)
        scene.he(200., index=3)
        scene.prime()
        scene.prime('he_fallback')
        decision = scene.tick(0.)
        self.assertEqual('aim', decision['action'], decision)
        self.assertEqual(2, decision['candidate']['shell_index'])
        self.assertEqual(3, scene.policy.next_shell)

    def test_loaded_he_can_use_legal_fallback_on_another_enemy_without_forging_blocked_armour(self):
        for clips in (1, 6):
            for validation in ('single_point', 'full'):
                with self.subTest(clips=clips, validation=validation):
                    scene = Observations(clips=clips, targets=2, points=1,
                                         he_validation=validation)
                    scene.frame['loaded'] = 2
                    scene.value(2, target=1, armor='unknown', line='world_blocked')
                    scene.value(2, target=1, mode='he_fallback', armor='unknown',
                                line='world_blocked')
                    scene.he(40., target=2)
                    scene.prime()
                    scene.prime('he_fallback')
                    decision = scene.tick(0.)
                    self.assertEqual('aim', decision['action'], decision)
                    self.assertEqual((2, ('bot', 2), 'he_fallback'),
                        (decision['candidate']['shell_index'],
                         decision['candidate']['target_key'], decision['candidate']['mode']))
                    self.assertFalse(scene.policy._all_failed((2,)))
                    self.assertIsNone(scene.policy.search_authority)
                    self.assertIsNone(scene.policy.reload_authority)
                    blocked = scene.policy.rows[(2, ('bot', 1), 0, 'penetration')]
                    self.assertEqual(('unknown', 'world_blocked'),
                                     (blocked['armor'], blocked['line']))

    def test_other_enemy_he_fallback_never_authorizes_unreviewed_high_damage_target(self):
        scene = Observations(targets=2, points=1, he_validation='full')
        scene.frame['loaded'] = 2
        scene.value(2, target=1, armor='unknown', line='clear')
        scene.he(200., target=1)
        scene.he(40., target=2)
        scene.prime()
        scene.prime('he_fallback')
        decision = scene.tick(0.)
        self.assertEqual('aim', decision['action'], decision)
        self.assertEqual(('bot', 2), decision['candidate']['target_key'])
        self.assertEqual(40., decision['candidate']['expected_damage'])
        self.assertFalse(scene.policy._all_failed((2,)))

    def test_blocked_retained_he_reviews_other_current_contacts_before_moving(self):
        for validation in ('single_point', 'full'):
            with self.subTest(validation=validation):
                scene = Observations(targets=2, points=1, he_validation=validation)
                scene.frame['loaded'] = 2
                scene.he(100., target=1)
                scene.he(40., target=2)
                scene.prime()
                scene.prime('he_fallback')
                first = scene.tick(0.)['candidate']
                self.assertEqual(('bot', 1), first['target_key'])
                self.assertIsNotNone(scene.policy._current_he_execution)
                # A newly observed front vehicle changes the live lane while
                # the original HE point is still being laid. It does not
                # manufacture a new target selection or a navigation order.
                blocker = dict(actor_key=('bot', 2), hostile=True, vehicle_id=102)
                scene.value(2, target=1, mode='he_fallback', armor='unknown',
                            line='enemy_blocked', blocker=blocker)
                scene.frame['line_revision'] += 1
                decision = scene.tick(.1)
                self.assertNotIn('move_request', decision)
                if decision['action'] == 'wait':
                    # The full HE role may need a second bounded frame to
                    # refresh the other enemy's penetration and contact ray.
                    self.assertEqual('stationary_alternatives_pending', decision['reason'])
                    decision = scene.tick(.2)
                self.assertEqual('aim', decision['action'], decision)
                self.assertEqual((('bot', 2), 2, 'he_fallback'),
                                 (decision['candidate']['target_key'],
                                  decision['candidate']['shell_index'],
                                  decision['candidate']['mode']))
                self.assertNotIn('move_request', decision)
                blocked = scene.policy.rows[first['key']]
                self.assertEqual('enemy_blocked', blocked['line'])
                self.assertEqual(('bot', 2), blocked['blocker']['actor_key'])

    def test_ordinary_he_gets_one_penetration_attempt_per_enemy(self):
        scene = Observations(targets=2, points=3, he_validation='single_point')
        scene.frame['loaded'] = 2
        scene.passed(2, target=2, sample=0)
        scene.he(20.)
        decision = scene.tick(0., background=False)
        self.assertEqual('aim', decision['action'], decision)
        self.assertEqual(('bot', 2), decision['candidate']['target_key'])
        self.assertEqual('penetration', decision['candidate']['mode'])
        attempts = [(row[3], row[4]) for row in scene.calls
                    if row[2] == 2 and row[5] == 'penetration']
        self.assertEqual([(('bot', 1), 0), (('bot', 2), 0)], attempts)

    @staticmethod
    def ordinary_he_stationary_scene():
        scene = Observations(targets=2, points=3, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(0, 0, 30))
        plan = dict(status='proved', proof=dict(proved=True), armor='failed',
                    line='clear', mechanical='reachable', contact=None,
                    expected_damage=None, solution=dict(point=(20., 2., 100.)))
        scene.value(2, target=1, armor='unknown', mechanical='hull_laying',
                    stationary_plan=plan)
        scene.value(2, target=2, armor='unknown', line='unknown',
                    mechanical='unknown')
        contact = copy.deepcopy(plan)
        contact.update(contact=True, expected_damage=40.)
        for sample in range(3):
            scene.value(2, target=1, sample=sample, mode='he_fallback',
                        armor='unknown', mechanical='hull_laying',
                        stationary_plan=contact)
            scene.value(2, target=2, sample=sample, mode='he_fallback',
                        armor='unknown', line='unknown', mechanical='unknown')
        return scene, plan

    def test_ordinary_he_projected_failure_allows_recovery_not_a_projected_shot(self):
        scene, unused_plan = self.ordinary_he_stationary_scene()
        scene.prime()
        scene.prime('he_fallback')
        self.assertEqual(frozenset((('bot', 1),)),
                         scene.policy._loaded_he_fallback_targets(2))
        self.assertFalse(scene.policy._all_failed((2,)))
        decision = scene.tick(0.)
        self.assertEqual('firing_position', decision['action'], decision)
        self.assertEqual((('bot', 1), 'he_fallback'),
                         (decision['candidate']['target_key'], decision['candidate']['mode']))
        self.assertFalse(scene.policy._executable_current(decision['candidate'], 'he_fallback'))
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertIsNone(scene.policy.search_authority)
        self.assertIsNone(scene.policy.reload_authority)
        self.assertTrue(all(not trial['failed']
                           for trial in scene.policy._single_point_history.values()))
        attempts = [(row[3], row[4]) for row in scene.calls
                    if row[2] == 2 and row[5] == 'penetration']
        self.assertEqual(set(((('bot', 1), 0), (('bot', 2), 0))), set(attempts))

    def test_ordinary_he_projected_failure_must_keep_fresh_complete_native_proof(self):
        for invalid in ('unproved', 'pending', 'unknown', 'blocked',
                        'stale_plan', 'stale_source', 'stale_target', 'stale_lane'):
            with self.subTest(invalid=invalid):
                scene, plan = self.ordinary_he_stationary_scene()
                if invalid == 'unproved':
                    plan['proof']['proved'] = False
                elif invalid == 'pending':
                    plan['status'] = 'pending'
                elif invalid == 'unknown':
                    plan['armor'] = 'unknown'
                elif invalid == 'blocked':
                    plan['line'] = 'world_blocked'
                scene.prime()
                scene.prime('he_fallback')
                if invalid == 'stale_plan':
                    scene.stationary_plan_current = lambda frame, proof: False
                elif invalid == 'stale_source':
                    scene.frame['pose'] = ('source', 1)
                elif invalid == 'stale_target':
                    scene.move_target(1, 1)
                elif invalid == 'stale_lane':
                    scene.frame['line_revision'] += 1
                scene.policy.frame = scene.snapshot(.1)
                self.assertEqual(frozenset(), scene.policy._loaded_he_fallback_targets(2))
                self.assertTrue(all(not trial['failed']
                                   for trial in scene.policy._single_point_history.values()))
                self.assertFalse(scene.policy._all_failed((2,)))
                self.assertIsNone(scene.policy.search_authority)
                self.assertIsNone(scene.policy.reload_authority)

    def test_non_he_clip_can_reload_verified_alternative_without_moving(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.passed(1)
        scene.prime()
        decision = scene.tick(0.)
        self.assertEqual('reload_clip', decision['action'], decision)
        self.assertEqual(1, decision['shell_index'])
        self.assertTrue(decision['early_reload'])
        self.assertIsNone(scene.policy.search_authority)

    def test_current_clip_failure_does_not_start_search_with_other_ammo_unknown(self):
        scene = Observations(clips=6, targets=1, points=1)
        scene.allow_atomic = False
        for index in (1, 2):
            scene.value(index, armor='unknown', line='clear')
        scene.prime()
        for now in (0., 2.1, 10., 30.):
            decision = scene.tick(now)
            self.assertIn(decision['action'], ('wait', 'preaim'), decision)
            self.assertIsNone(scene.policy.search_authority)
            self.assertIsNone(scene.policy.search_started)

    def test_limited_traverse_does_not_skip_global_eight_second_search(self):
        for clips in (1, 6):
            with self.subTest(clips=clips):
                scene = Observations(clips=clips, targets=1, points=1)
                scene.frame['limited_traverse'] = True
                scene.he(20.)
                scene.prime()
                scene.prime('he_fallback')
                decision = scene.tick(0.)
                self.assertEqual('search_penetration', decision['action'], decision)
                self.assertEqual((0, 1, 2), scene.policy.search_authority['shells'])
                self.assertIsNone(scene.policy.reload_authority)

    def test_query_timeout_never_becomes_a_physical_movement_request(self):
        scene = Observations(targets=1, points=1)
        scene.allow_atomic = False
        for index in (0, 1, 2):
            scene.value(index, armor='unknown', line='unknown', mechanical='unknown')
        for now in (0., 2.1, 10., 30.):
            decision = scene.tick(now)
            self.assertIn(decision['action'], ('wait', 'preaim'), decision)
            self.assertNotIn('move_request', decision)
            self.assertIsNone(scene.policy.search_authority)

    def test_waiting_for_native_barrel_keeps_qualified_ap_intention(self):
        scene = Observations(targets=1, points=1)
        scene.passed(0)
        candidate = scene.tick(0.)['candidate']
        scene.policy.admission_failed(candidate, 'auto_gun_laying')
        self.assertEqual(candidate['key'], scene.policy.selected)
        self.assertEqual(candidate['key'], scene.tick(.1)['candidate']['key'])

    def test_known_wall_recovery_is_not_vetoed_by_unavailable_other_enemy(self):
        scene = Observations(targets=2, points=1, he=False)
        scene.value(0, target=1, armor='passed', line='world_blocked')
        scene.value(0, target=2, armor='unknown', line='unknown',
                    mechanical='unknown', reason='entity_geometry_unavailable')
        scene.prime()
        for now in (0., 2.1, 8.1):
            decision = scene.tick(now)
            self.assertEqual('firing_position', decision['action'], decision)
            self.assertEqual(('bot', 1), decision['candidate']['target_key'])
            self.assertIsNone(scene.policy.search_authority)

    def test_search_elapsed_survives_roster_and_same_weapon_descriptor_changes(self):
        for change in ('roster', 'descriptor'):
            with self.subTest(change=change):
                scene = Observations(targets=1, points=1)
                scene.frame.update(weapon_identity=('round', 'gun'),
                                   combat_signature=('domain', 1))
                scene.he(20.)
                scene.prime()
                scene.prime('he_fallback')
                first = scene.tick(0.)
                self.assertEqual('search_penetration', first['action'])
                if change == 'roster':
                    scene.frame['combat_signature'] = ('domain', 2)
                else:
                    scene.frame['identity'] = ('round', 'siege_descriptor')
                scene.tick(4.)
                self.assertEqual(0., scene.policy.search_started)
                scene.prime()
                scene.prime('he_fallback')
                expired = scene.tick(8.)
                self.assertEqual('switch_shell', expired['action'], expired)
                self.assertEqual(2, expired['shell_index'])

    def test_large_rotating_all_ammo_domain_cannot_borrow_current_clip_failure(self):
        scene = Observations(clips=6, targets=3, points=9)
        for step in range(30):
            for target in range(1, 4):
                scene.move_target(target, step)
            result = scene.tick(step * .1)
            self.assertNotEqual('search_penetration', result['action'])
            self.assertIsNone(scene.policy.search_started)
            self.assertLessEqual(scene.policy._used['atomic'], 48)

    def test_full_he_late_enemy_gets_complete_fair_review_within_unchanged_atomic_budget(self):
        for unfinished in (False, True):
            with self.subTest(unfinished=unfinished):
                scene = Observations(clips=6, targets=7, points=9, he_validation='full')
                scene.frame.update(loaded=2, ammo=(0, 0, 60))
                scene.policy.atomic_clock = lambda: 0.
                for target in range(1, 8):
                    for sample in range(9):
                        if target != 7 or unfinished and sample == 8:
                            scene.value(2, target=target, sample=sample, armor='unknown',
                                        line='unknown', mechanical='unknown')
                        scene.he(40. if target == 7 else 200., target=target, sample=sample)
                aimed = False
                for step in range(601):
                    for target in scene.frame['targets']:
                        index = target['key'][1]
                        target.update(pose=('enemy', index, step), velocity=(1., 0., 0.))
                        target['value']['position'] = (step * .1, 0., 100. + index)
                    before = len(scene.calls)
                    decision = scene.tick(step * .1)
                    calls = scene.calls[before:]
                    for channel, limit in (('foreground', 2), ('background', 2), ('atomic', 48)):
                        self.assertLessEqual(sum(call[1] == channel for call in calls), limit)
                    self.assertFalse(scene.policy._all_failed((2,)))
                    self.assertIsNone(scene.policy.search_authority)
                    self.assertIsNone(scene.policy.reload_authority)
                    self.assertIsNone(scene.policy.next_at_edge()[0])
                    self.assertNotIn(decision['action'], ('switch_shell', 'reload_clip'))
                    if decision['action'] == 'aim':
                        self.assertFalse(unfinished, decision)
                        current = scene.policy.current_row(decision['candidate'])
                        self.assertEqual((2, ('bot', 7), 'he_fallback', 40.),
                            (current['shell_index'], current['target_key'], current['mode'],
                             current['expected_damage']))
                        self.assertEqual(('enemy', 7, step), current['pose_stamp'][2])
                        self.assertTrue(scene.policy._executable_current(current, 'he_fallback'))
                        self.assertTrue(scene.policy.apply_order({})['fire_allowed'])
                        aimed = True
                        break
                    self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                self.assertEqual(not unfinished, aimed, scene.policy.status())
                self.assertEqual((2, 6, (0, 0, 60)),
                                 (scene.frame['loaded'], scene.frame['clip'], scene.frame['ammo']))

    def test_temporary_navigation_gate_retains_intention_but_never_fire_permission(self):
        scene = Observations(targets=1, points=1)
        scene.passed()
        current = scene.tick(0.)['candidate']
        scene.policy.runtime.attack_candidate_consumable = lambda row: False
        blocked = scene.tick(.1)
        self.assertEqual('wait', blocked['action'])
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertEqual(current['key'], scene.policy.selected)
        scene.policy.runtime.attack_candidate_consumable = lambda row: True
        self.assertEqual(current['key'], scene.tick(.2)['candidate']['key'])


if __name__ == '__main__':
    unittest.main()
