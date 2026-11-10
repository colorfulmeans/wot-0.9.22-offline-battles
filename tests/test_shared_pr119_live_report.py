"""Live-report liveness at the shared planner/driver/native fire boundaries.

These are deterministic #1513-shaped observation fixtures, not a Windows
physics replay. Native matrices, world boxes and query cost are supplied;
the shared policy, original driver, trigger admission and ammunition ledger
are production code. No candidate, penetration result or fire permission is
injected by these regressions.
"""
import contextlib
import io
import unittest

from test_player_combat_ownership import OwnershipScene


class LiveReportLivenessTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def scene(self, features=('drive', 'fire'), limited=False):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(features=features, limited=limited, clip=10, burst=1)
        return scene

    def test_blocked_opening_keeps_final_route_controls_during_yaw_changes(self):
        traces = []
        for features in (('drive',), ('drive', 'fire')):
            scene = self.scene(features=features, limited=True)
            scene.obstructed_enemy(2)
            self.assertEqual({2: False}, scene.sample_original_lanes())
            trace = []
            for index in range(30):
                # Route-only rotation may schedule a fresh observation. It
                # cannot itself prove an executable combat recovery.
                scene.native_position((0., 0., 0.), yaw=.13 * index)
                scene.tick(.1)
                command = scene.control.last_order
                trace.append(tuple(command.get(key) for key in
                    ('throttle', 'turn', 'brake', 'movement_intent',
                     'move_position', 'face_position', 'combat_mode')))
                self.assertFalse(scene.runtime.combat_stop.combat_owned,
                    (index, scene.runtime.combat_stop.receipt))
                self.assertEqual('class_mt_rim_east', scene.applied_order()['route_id'])
                self.assertFalse(scene.launches())
            traces.append(trace)
            scene.doCleanups()
        self.assertEqual(traces[0], traces[1],
            'pending combat inspection must not change the final route inputs')
        self.assertTrue(any(row[0] != 0. for row in traces[0]),
                        'the baseline must actually ask the original driver to travel')

    def test_loaded_he_commits_with_source_jitter_and_fourteen_blocked_enemies(self):
        for features in (('fire',), ('drive', 'fire')):
            with self.subTest(features=features):
                scene = self.scene(features=features)
                scene.set_he(piercing=1.)
                scene.battle._gun_state.ammo[1] = 0
                scene.battle.client.effective_params['ammo'][1][1] = 0
                target = scene.eligible_enemy(50, armor=30.)
                scene.pose(target, (0., 0., 40.))
                for identity in range(70, 84):
                    scene.obstructed_enemy(identity)
                lanes = scene.sample_original_lanes()
                self.assertTrue(lanes[50])
                self.assertEqual(14, sum(not value for value in lanes.values()))
                policy = scene.runtime.attack_policy
                clock, queries, commits = [0.], [], []
                policy.atomic_clock = lambda: clock[0]
                original_evaluate = policy._evaluate
                original_commit = policy.shot_committed

                def costed_query(job, now, channel, *args, **kwargs):
                    result = original_evaluate(job, now, channel, *args, **kwargs)
                    queries.append((channel, job[4], job[0][1]))
                    clock[0] += .001
                    return result

                def record_commit(event, pending):
                    candidate = ((pending.get('player_control') or {}).get('candidate') or
                                 policy.trigger or policy.decision.get('candidate') or {})
                    commits.append((candidate.get('target_key'), candidate.get('mode'),
                                    candidate.get('sample')))
                    return original_commit(event, pending)

                policy._evaluate = costed_query
                policy.shot_committed = record_commit
                initial_ammo = tuple(scene.battle._gun_state.ammo)
                for index in range(60):
                    height = 1.e-8 if index % 2 else 0.
                    scene.native_position((0., height, 0.))
                    scene.tick(.1)
                    self.assertLessEqual(policy._used['foreground'], policy.foreground_budget)
                    self.assertLessEqual(policy._used['background'], policy.background_budget)
                    self.assertEqual(2, policy.foreground_budget)
                    self.assertEqual(.008, policy.atomic_time_budget)
                    if scene.launches():
                        break
                self.assertTrue(scene.launches(), policy.status())
                self.assertEqual(1, len(scene.launches()))
                self.assertEqual([(('bot', 50), 'he_fallback', 0)], commits)
                self.assertGreater(policy.proof_revocations['source'], 0,
                                   'the test must exercise exact physical proof invalidation')
                self.assertTrue(any(channel == 'foreground' and mode == 'he_fallback'
                                    for channel, mode, unused_target in queries))
                self.assertEqual(initial_ammo[0] - 1, scene.battle._gun_state.ammo[0])
                self.assertEqual(9, scene.battle._gun_state.clip)
                self.assertEqual(0, scene.battle._gun_state.shot_index)
                self.assertFalse(hasattr(policy, 'search_started'))
                scene.doCleanups()


if __name__ == '__main__':
    unittest.main()
