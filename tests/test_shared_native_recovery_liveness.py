"""The future-position hypothesis has its own exact bounded ray task.

Native adapters and synthetic native matrices/colliders are exercised here.
No projected position is a real source or an authorization to launch.
"""
import copy
import unittest

import test_shared_point_recovery as point_recovery


class NativeRecoveryHypothesisTests(unittest.TestCase):
    def setUp(self):
        fixture = point_recovery.NativeProjectedPointTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.scene = fixture.scene
        self.runtime, self.policy = fixture.runtime, fixture.policy
        self.evaluator, self.candidate = fixture.evaluator, fixture.candidate
        self.destination = (4., 0., 8.)
        for shot in self.runtime.gun.shots:
            shot.speed, shot.maxDistance = 100., 5000.
        target = self.runtime.target_entity(self.candidate['target'])
        self.scene.pose(target, (24., 0., 200.))
        # This is the fixture's stationary initial layout, not a 150 m
        # movement over the adapter's preceding velocity sample interval.
        self.evaluator.observations.clear()

    def probe(self, revision, budget=6):
        self.scene.fixture.now += .1
        self.runtime.now = self.scene.now
        height = revision * 1.e-8
        self.scene.origin = (0., 2. + height, 0.)
        self.scene.body.setRotateYPR((0., height, 0.))
        frame = self.evaluator.snapshot(self.scene.now)
        self.policy.frame = frame
        self.evaluator._budgets.update(foreground=12 - budget, recovery=budget)
        before = len(self.scene.world_queries)
        receipt = self.evaluator.point_recovery_probe(
            frame, self.candidate, self.destination, self.scene.now)
        self.assertLessEqual(len(self.scene.world_queries) - before, budget)
        return receipt

    def test_source_settling_finishes_one_exact_hypothetical_path_under_original_budget(self):
        before = (tuple(self.runtime.gun.ammo), self.runtime.gun.clip,
                  self.runtime.state['fire_seq'])
        pending = 0
        hypothetical_path = None
        hypothetical_pose = None
        for revision in range(1, 11):
            receipt = self.probe(revision)
            progress = self.evaluator._recovery_probe
            self.assertIsNotNone(progress)
            if hypothetical_path is None:
                hypothetical_path = progress['predicted']['path']
                hypothetical_pose = progress['projected_frame']['pose']
            else:
                self.assertIs(hypothetical_path, progress['predicted']['path'])
                self.assertEqual(hypothetical_pose, progress['projected_frame']['pose'])
            pending += receipt['status'] == 'pending'
            if receipt['status'] == 'clear':
                break
        self.assertGreater(pending, 0, 'the native path must span multiple bounded slices')
        self.assertEqual('clear', receipt['status'], receipt)
        self.assertEqual(before, (tuple(self.runtime.gun.ammo), self.runtime.gun.clip,
                                 self.runtime.state['fire_seq']))
        self.assertIsNone(self.policy.current_row(self.candidate))
        self.assertFalse(self.scene.launches())

    def test_current_friendly_identity_is_blocked_but_missing_geometry_remains_unknown(self):
        for verdict, expected in ((dict(clear=False, blocker_kind='bot', blocker_id=5,
                blocker_team=1), 'blocked'), (dict(clear=False), 'unknown')):
            with self.subTest(expected=expected):
                self.evaluator._recovery_probe = None
                self.runtime.geometry._bot_friendly_path_verdict = lambda *args: verdict
                for revision in range(10):
                    receipt = self.probe(0)
                    if receipt['status'] != 'pending':
                        break
                self.assertEqual(expected, receipt['status'], receipt)
                self.assertFalse(self.scene.launches())

    def test_cancelled_task_cannot_reuse_old_hypothesis_or_chord_progress(self):
        self.assertEqual('pending', self.probe(1)['status'])
        old = self.evaluator._recovery_probe
        self.assertEqual(6, old['cursor'])
        self.evaluator.cancel_point_recovery()
        self.assertIsNone(self.evaluator._recovery_probe)
        self.assertEqual('pending', self.probe(2, budget=0)['status'])
        current = self.evaluator._recovery_probe
        self.assertIsNot(old, current)
        self.assertEqual(0, current['cursor'])
        self.assertNotEqual(old['projected_frame']['pose'], current['projected_frame']['pose'])

    def test_cancelled_during_native_query_cannot_publish_the_old_plan(self):
        self.scene.on_probe = lambda *args: self.evaluator.cancel_point_recovery()
        self.assertEqual('pending', self.probe(1)['status'])
        self.assertIsNone(self.evaluator._recovery_probe)
        self.assertFalse(self.scene.launches())

    def test_final_native_callback_retires_task_before_clear_publication(self):
        native_lane = self.runtime.geometry._bot_friendly_path_verdict
        native_fence = self.evaluator.fence
        for boundary in ('lane', 'fence', 'same_key_replacement'):
            with self.subTest(boundary=boundary):
                self.evaluator.cancel_point_recovery()
                retired, replacement = [], []

                def retire():
                    retired.append(self.evaluator._recovery_probe)
                    self.evaluator.cancel_point_recovery()
                    if boundary == 'same_key_replacement':
                        # Start a genuinely new probe through the production
                        # entry point, without refilling this callback's work.
                        self.evaluator._budgets['recovery'] = 0
                        pending = self.evaluator.point_recovery_probe(
                            self.policy.frame, self.candidate, self.destination, self.scene.now)
                        self.assertEqual('pending', pending['status'])
                        replacement.append(self.evaluator._recovery_probe)

                def lane(*args):
                    result = native_lane(*args)
                    retire()
                    return result

                def fence(frame):
                    result = native_fence(frame)
                    retire()
                    return result

                self.runtime.geometry._bot_friendly_path_verdict = (
                    native_lane if boundary == 'fence' else lane)
                self.evaluator.fence = fence if boundary == 'fence' else native_fence
                try:
                    for revision in range(10):
                        receipt = self.probe(0)
                        if retired:
                            break
                    self.assertTrue(retired)
                    self.assertEqual('pending', receipt['status'], receipt)
                    if replacement:
                        self.assertIsNot(retired[0], replacement[0])
                        self.assertIs(replacement[0], self.evaluator._recovery_probe)
                        self.assertEqual(0, replacement[0]['cursor'])
                    else:
                        self.assertIsNone(self.evaluator._recovery_probe)
                    self.assertFalse(self.scene.launches())
                finally:
                    self.runtime.geometry._bot_friendly_path_verdict = native_lane
                    self.evaluator.fence = native_fence

    def test_changed_planning_domain_restarts_exact_future_ray_work(self):
        for change in ('destination', 'sample', 'target', 'component', 'shell', 'scene', 'lane'):
            with self.subTest(change=change):
                self.evaluator.cancel_point_recovery()
                self.evaluator.observations.clear()
                self.assertEqual('pending', self.probe(1)['status'])
                old = self.evaluator._recovery_probe
                self.assertEqual(6, old['cursor'])
                target = self.runtime.target_entity(self.candidate['target'])
                if change == 'destination':
                    self.destination = (5., 0., 8.)
                elif change == 'sample':
                    self.candidate = dict(self.candidate, sample=self.candidate['sample'] + 1)
                    self.candidate['key'] = (self.candidate['shell_index'],
                        self.candidate['target_key'], self.candidate['sample'], self.candidate['mode'])
                elif change == 'target':
                    self.scene.pose(target, (25., 0., 200.))
                    self.evaluator.observations.clear()
                elif change == 'component':
                    target.typeDescriptor.hull.hitTester = copy.copy(target.typeDescriptor.hull.hitTester)
                elif change == 'shell':
                    self.runtime.gun.shots[self.candidate['shell_index']].speed = 90.
                elif change == 'scene':
                    self.evaluator._scene_stamp = lambda: ('changed_native_scene',)
                else:
                    self.scene.vehicle(213, (5., 0., 30.), team=1)
                self.assertEqual('pending', self.probe(2, budget=0)['status'])
                current = self.evaluator._recovery_probe
                self.assertIsNot(old, current)
                self.assertEqual(0, current['cursor'])
                self.assertFalse(self.scene.launches())


if __name__ == '__main__':
    unittest.main()
