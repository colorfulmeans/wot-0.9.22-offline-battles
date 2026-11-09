"""Physical obstruction review coverage never substitutes launch evidence."""
import copy
import unittest

from test_player_rebuilt_attack_policy import Observations


class PhysicalReviewCoverageTests(unittest.TestCase):
    @staticmethod
    def scene(points=1):
        scene = Observations(targets=2, points=points, he=False)
        for target in scene.frame['targets']:
            target['sample_identity'] = ('native_entity', target['key'], 1)
        for sample in range(points):
            scene.value(0, target=1, sample=sample, armor='passed', line='friendly_blocked',
                        blocker=dict(blocker_kind='bot', blocker_id=12, blocker_team=1))
            scene.value(0, target=2, sample=sample, armor='unknown', line='unknown',
                        mechanical='unknown', reason='entity_geometry_unavailable')
        scene.allow_atomic = False
        return scene

    def test_completed_observations_survive_target_pose_churn_not_as_launch_or_failure_proof(self):
        scene = self.scene(points=9)
        for step in range(80):
            for target in (1, 2):
                scene.move_target(target, step)
            result = scene.tick(step * .05)
            self.assertLessEqual(scene.policy._used['foreground'], 2)
            self.assertLessEqual(scene.policy._used['background'], 2)
            self.assertIsNone(scene.policy.search_authority)
            self.assertIsNone(scene.policy.reload_authority)
            self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
            if result['action'] == 'firing_position':
                break
        self.assertEqual('firing_position', result['action'], scene.policy.status())
        self.assertEqual('friendly_blocked', scene.policy.current_row(result['candidate'])['line'])
        self.assertFalse(scene.policy._all_failed((0,)))
        fresh = [scene.policy._current(job, require_line=True)
                 for job in scene.policy._jobs(shell_index=0)]
        self.assertLess(sum(row is not None for row in fresh), len(fresh))
        self.assertEqual({0, 1, 2, 3, 4, 5, 6, 7, 8},
                         {row[4] for row in scene.calls if row[2] == 0 and row[3] == ('bot', 2)})

    def test_new_unfinished_observation_never_counts_as_completed_review(self):
        for pending in ('line', 'review', 'stationary', 'projected'):
            with self.subTest(pending=pending):
                scene = self.scene()
                value = dict(armor='unknown', line='unknown', mechanical='unknown')
                if pending == 'line':
                    value['line'] = 'pending'
                elif pending == 'review':
                    value['review_pending'] = True
                elif pending == 'stationary':
                    value['stationary_progress'] = True
                else:
                    value['stationary_plan'] = dict(status='proved', proof=dict(proved=True),
                        armor='unknown', line='pending', mechanical='reachable')
                scene.value(0, target=2, **value)
                for step in range(10):
                    result = scene.tick(step * .05)
                    self.assertNotEqual('firing_position', result['action'])
                    self.assertIsNone(scene.policy.search_authority)
                    self.assertFalse(scene.policy.apply_order({})['fire_allowed'])

    def test_fresh_blocker_sample_rotation_does_not_restart_the_same_review_pass(self):
        for blocker_ids in ((12, 12), (12, 13)):
            with self.subTest(blocker_ids=blocker_ids):
                scene = self.scene(points=9)
                for target, blocker in zip((1, 2), blocker_ids):
                    for sample in range(9):
                        scene.value(0, target=target, sample=sample, armor='passed',
                                    line='friendly_blocked', blocker=dict(
                                        blocker_kind='bot', blocker_id=blocker, blocker_team=1))
                for step in range(80):
                    for target in (1, 2):
                        scene.move_target(target, step)
                    result = scene.tick(step * .05)
                    self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
                    self.assertIsNone(scene.policy.search_authority)
                    if result['action'] == 'firing_position':
                        break
                self.assertEqual('firing_position', result['action'], scene.policy.status())
                self.assertIsNotNone(scene.policy.current_row(result['candidate']))
                self.assertEqual({(target, sample) for target in (('bot', 1), ('bot', 2))
                                  for sample in range(9)},
                                 {(row[3], row[4]) for row in scene.calls if row[2] == 0})

    def test_previous_completed_pass_requires_a_fresh_present_physical_obstruction(self):
        scene = self.scene()
        scene.prime()
        self.assertEqual('firing_position', scene.tick(0.)['action'])
        for sample in range(1):
            scene.value(0, target=1, sample=sample, armor='unknown', line='unknown',
                        mechanical='unknown', reason='entity_geometry_unavailable')
        for target in (1, 2):
            scene.move_target(target, 1)
        for step in range(1, 10):
            result = scene.tick(step * .05)
            self.assertNotEqual('firing_position', result['action'], result)
            self.assertIsNone(scene.policy.search_authority)

    def test_verified_aim_ends_review_before_a_later_same_place_obstruction(self):
        scene = self.scene(points=9)
        scene.prime()
        self.assertEqual('firing_position', scene.tick(0.)['action'])
        scene.passed(0, target=1, sample=0)
        scene.move_target(1, 1)
        self.assertEqual('aim', scene.tick(.1)['action'])
        scene.value(0, target=1, sample=0, armor='passed', line='friendly_blocked',
                    blocker=dict(blocker_kind='bot', blocker_id=12, blocker_team=1))
        for target in (1, 2):
            scene.move_target(target, 2)
        result = scene.tick(.2, background=False)
        self.assertNotEqual('firing_position', result['action'], result)
        self.assertFalse(scene.policy.apply_order({})['fire_allowed'])
        self.assertIsNone(scene.policy.search_authority)

    def test_new_scope_must_complete_its_own_observations(self):
        for change in ('source', 'shell', 'entity', 'sample', 'new_target', 'blocker', 'reset'):
            with self.subTest(change=change):
                scene = self.scene(points=9)
                scene.prime()
                self.assertEqual('firing_position', scene.tick(0.)['action'])
                for target in (1, 2):
                    scene.move_target(target, 1)
                if change == 'source':
                    scene.frame['position'] = (1., 0., 0.)
                    scene.frame['pose'] = ('source', 1)
                elif change == 'shell':
                    scene.frame['shells'][0]['signature'] = ('ap', 2)
                elif change == 'entity':
                    scene.frame['targets'][1]['sample_identity'] = ('native_entity', ('bot', 2), 2)
                elif change == 'sample':
                    scene.frame['targets'][1]['samples'] += (9,)
                elif change == 'new_target':
                    target = copy.deepcopy(scene.frame['targets'][1])
                    target.update(key=('bot', 3), sample_identity=('native_entity', ('bot', 3), 1))
                    scene.frame['targets'] += (target,)
                elif change == 'blocker':
                    for sample in range(9):
                        scene.values[0, ('bot', 1), sample, 'penetration']['blocker']['blocker_id'] = 13
                else:
                    scene.policy.reset()
                result = scene.tick(.1, background=False)
                self.assertNotEqual('firing_position', result['action'], (change, result))
                self.assertIsNone(scene.policy.search_authority)
                self.assertFalse(scene.policy.apply_order({})['fire_allowed'])


if __name__ == '__main__':
    unittest.main()
