"""Fair optional-work quotas do not own proof, target, clock or gun state."""
from collections import Counter
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.vehicle_control.evaluation_budget import EvaluationBudget


class EvaluationBudgetTests(unittest.TestCase):
    def test_twenty_nine_actors_get_background_within_eight_control_frames(self):
        budget = EvaluationBudget()
        actors = list(range(1, 30))
        seen = set()
        for frame in range(8):
            budget.begin(frame, actors)
            grants = {actor: budget.background(actor, 2) for actor in actors}
            self.assertLessEqual(sum(grants.values()), 8)
            self.assertTrue(all(value in (0, 2) for value in grants.values()))
            seen.update(actor for actor, grant in grants.items() if grant)
        self.assertEqual(set(actors), seen)

    def test_atomic_requests_are_fair_and_one_actor_cannot_reopen_same_frame(self):
        budget = EvaluationBudget()
        actors = list(range(1, 30))
        seen = Counter()
        for frame in range(58):
            budget.begin(frame, actors)
            granted = [actor for actor in actors if budget.atomic(actor)]
            self.assertEqual(1, len(granted))
            seen[granted[0]] += 1
            self.assertFalse(budget.atomic(granted[0]))
        self.assertEqual({actor: 2 for actor in actors}, dict(seen))

    def test_same_callback_and_late_physics_substeps_do_not_refill_tokens(self):
        budget = EvaluationBudget()
        frame = (7, 'render_callback', 20.)
        budget.begin(frame, range(1, 7))
        self.assertEqual([2, 2, 2, 2, 0, 0], [budget.background(actor, 2) for actor in range(1, 7)])
        self.assertTrue(budget.atomic(1))
        for unused in range(5):
            self.assertFalse(budget.begin(frame, range(1, 7)))
            self.assertEqual(0, sum(budget.background(actor, 2) for actor in range(1, 7)))
            self.assertFalse(any(budget.atomic(actor) for actor in range(1, 7)))
        self.assertEqual(8, budget.receipt()['background_used'])

    def test_death_and_new_actor_do_not_reset_or_starve_old_waiters(self):
        budget = EvaluationBudget()
        budget.begin(0, range(1, 7))
        for actor in range(1, 7):
            budget.background(actor, 2)
            budget.atomic(actor)
        # Actor2 was next for atomic, actor5 next for background. Both die;
        # new low-id actor0 cannot jump ahead of the surviving waiters.
        alive = (0, 1, 3, 4, 6)
        budget.begin(1, alive)
        atomic = [actor for actor in alive if budget.atomic(actor)]
        self.assertEqual([3], atomic)
        self.assertEqual(2, budget.background(6, 2))
        granted = set()
        for frame in range(2, 8):
            budget.begin(frame, alive)
            granted.update(actor for actor in alive if budget.atomic(actor))
            for actor in alive:
                budget.background(actor, 2)
        self.assertEqual(set(alive), granted)
        self.assertNotIn(2, budget.receipt()['atomic_waiting'])
        self.assertNotIn(5, budget.receipt()['background_waiting'])

    def test_independent_foreground_engine_preserves_original_two_candidates(self):
        worker, foreground = EvaluationBudget(), EvaluationBudget()
        for frame in range(4):
            worker.begin(frame, range(1, 30))
            foreground.begin(frame, (1000001,))
            for actor in range(1, 30):
                worker.background(actor, 2)
                worker.atomic(actor)
            self.assertEqual(2, foreground.background(1000001, 2))
            self.assertTrue(foreground.atomic(1000001))
            self.assertEqual(2, foreground.receipt()['background_used'])


class EvaluationBudgetControlIntegrationTests(unittest.TestCase):
    def test_late_worker_callback_shares_quota_across_real_physics_slices(self):
        from shared_multi_bot_scene import MultiBotScene
        scene = MultiBotScene()
        self.addCleanup(scene.doCleanups)
        with contextlib.redirect_stdout(io.StringIO()):
            scene.setUp()
            scene.configure_workers(6, diverse=False, schedule='worker10')
            frame = scene.step(.45)
        self.assertGreaterEqual(scene.engine._last_update_control_steps, 2)
        self.assertEqual((7, scene.now), frame['work_budget']['frame'])
        self.assertLessEqual(frame['work_budget']['background_used'], 8)
        self.assertLessEqual(sum(value for (actor, channel, kind), value in frame['counts'].items()
                                 if channel == 'background' and kind == 'candidate'), 8)
        self.assertEqual(6, len(scene.engine._actor_controls))

    def test_foreground_policy_and_its_engine_share_one_independent_frame(self):
        from test_player_combat_ownership import OwnershipScene
        scene = OwnershipScene()
        self.addCleanup(scene.doCleanups)
        with contextlib.redirect_stdout(io.StringIO()):
            scene.setUp()
            scene.configure()
            scene.eligible_enemy(5)
            budget = scene.runtime.engine._evaluation_budget
            native_begin = budget.begin
            opened = []
            def begin(frame, actors):
                result = native_begin(frame, actors)
                if result:
                    opened.append(frame)
                return result
            budget.begin = begin
            scene.tick(.2)
        self.assertEqual(1, len(opened))
        self.assertEqual({scene.runtime.actor_id}, budget.alive)
        self.assertEqual(2, budget.receipt()['background_used'])
        self.assertGreater(scene.runtime.attack_policy.evaluator.cache_observations['armour_batches'], 0)


if __name__ == '__main__':
    unittest.main()
