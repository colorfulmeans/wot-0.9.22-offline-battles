"""Concurrent production BOT combat, native debit and private proof state.

The analytic world is documented in shared_multi_bot_scene. These tests drive
all six actors in the same BotRuntime authority frame, with the real shared
planner/driver/AttackPolicy/NativeAttackEvaluator/TriggerAdmission and worker
gun. They do not turn a successful policy stub into a firing certificate.
"""
import collections
import contextlib
import unittest

from shared_multi_bot_scene import MultiBotScene, bot_runtime
from gui.mods.offline_lan_0922.projectile_wire import round_scalar
from gui.mods.offline_lan_0922.vehicle_control.evaluation_budget import BACKGROUND_CANDIDATES_PER_FRAME
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import (
    ATOMIC_ARMOUR_BATCHES, ATOMIC_CANDIDATES, ATOMIC_WORLD_QUERIES,
    ATOMIC_WALL_SECONDS, BACKGROUND_CANDIDATES, FOREGROUND_CANDIDATES,
    WORLD_CHORDS_PER_FRONTIER)


class DiagnosticSink(object):
    def write(self, value):
        return len(value)
    def flush(self):
        pass


class SharedMultiBotCombatTests(unittest.TestCase):
    def scene(self, diverse=True):
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure_workers(6, diverse=diverse)

    def low_penetration_worker(self, scene):
        # Actor11 owns a real low-penetration AP load. Remove the empty
        # alternate kinetic slot from its observed stock; do not set any
        # policy outcome or failure timer. Other actors retain 300 mm AP.
        for shot in scene.descriptors['11'].gun.shots:
            shot.piercingPower = (1., 1.)
        ammo = scene.engine._ammo_states[11]
        ammo.restore(dict(ammo_remaining=[24, 0, 12], shell_index=0,
                          next_shell_index=0, ammo_reload_pending=False))
        ammo.publish(scene.engine.states[11])
        scene.initial_ammo[11] = (24, 0, 12)
        binding = scene.engine._control_for(scene.engine.states[11])
        self.assertEqual(ATOMIC_WALL_SECONDS, binding.attack_policy.atomic_time_budget)
        return binding

    def assert_private_state_and_real_debits(self, scene, minimum_each=0):
        bindings = list(scene.engine._actor_controls.values())
        self.assertEqual(6, len(bindings))
        for attribute in ('attack_policy', 'combat_stop', 'gun'):
            self.assertEqual(6, len({id(getattr(binding, attribute)) for binding in bindings}))
        self.assertEqual(6, len({id(binding.attack_policy.evaluator) for binding in bindings}))
        self.assertEqual(6, len({id(binding.gun.native) for binding in bindings}))
        self.assertEqual({1, 2}, {binding.actor_team for binding in bindings})
        for binding in bindings:
            actor = binding.actor_id
            self.assertIsInstance(binding.gun.native, bot_runtime._BotGunState)
            self.assertIs(binding.engine, scene.engine)
            self.assertEqual(scene.routes[actor], binding.state['route'])
            events = [row for row in scene.launches_observed if row['id'] == actor]
            self.assertGreaterEqual(len(events), minimum_each,
                'actor %s did not commit enough real launches; failure=%s policy=%r' % (
                    actor, binding._last_fire_failure, binding.attack_policy.status()))
            used = collections.Counter(event['shell_index'] for event in events)
            self.assertEqual([count-used.get(index, 0) for index, count in
                enumerate(scene.initial_ammo[actor])], list(binding.gun.ammo))
            self.assertEqual(list(range(1, len(events)+1)), [event['fire_seq'] for event in events])
            if events:
                self.assertIsNotNone(binding.trigger_admission)
            for event in events:
                evidence = event['evidence']
                self.assertEqual(actor, evidence['actor'])
                self.assertIn(evidence['target'], scene.actor_ids)
                self.assertNotEqual(binding.actor_team,
                    scene.engine.states[evidence['target']]['team'])
                self.assertEqual(evidence['context_source'], evidence['actual_source'],
                    'a native commit reused a proof from a different physical source pose')
                self.assertEqual(tuple(event['shot_origin']), tuple(
                    round_scalar(value) for value in evidence['actual_source'][2]))
                self.assertEqual(tuple(event['launch_pose'][:3]), evidence['actual_source'][0])
            candidate = binding.attack_policy.decision.get('candidate')
            if candidate is not None:
                target = candidate['target']['network_id']
                self.assertNotEqual(binding.actor_team, scene.engine.states[target]['team'])
                self.assertEqual(binding.actor_id, binding.attack_policy.evaluator.runtime.actor_id)

    def assert_budget_receipts(self, scene):
        maximum_global = dict(foreground=0, background=0)
        for frame in scene.frames:
            budget = frame['work_budget']
            self.assertIsNotNone(budget)
            self.assertLessEqual(budget['background_used'], BACKGROUND_CANDIDATES_PER_FRAME)
            atomic_actors = set(actor for (actor, channel, kind), value in frame['counts'].items()
                                if channel == 'atomic' and kind == 'candidate' and value)
            self.assertLessEqual(len(atomic_actors), 1)
            if atomic_actors:
                self.assertEqual({budget['atomic_actor']}, atomic_actors)
            for actor in scene.actor_ids:
                counts = frame['counts']
                for channel, limit in (('foreground', FOREGROUND_CANDIDATES),
                                       ('background', BACKGROUND_CANDIDATES)):
                    self.assertLessEqual(counts.get((actor, channel, 'candidate'), 0), limit)
                    self.assertLessEqual(counts.get((actor, channel, 'world'), 0),
                                         WORLD_CHORDS_PER_FRONTIER)
                row = frame['actors'][actor]
                self.assertLessEqual(row['atomic_evaluations'], ATOMIC_CANDIDATES)
                self.assertLessEqual(row['atomic_world'], ATOMIC_WORLD_QUERIES)
                self.assertLessEqual(row['atomic_armor'], ATOMIC_ARMOUR_BATCHES)
            for channel in maximum_global:
                total = sum(value for (actor, name, kind), value in frame['counts'].items()
                            if name == channel and kind == 'candidate')
                maximum_global[channel] = max(maximum_global[channel], total)
                self.assertLessEqual(total, 6 * FOREGROUND_CANDIDATES if channel == 'foreground'
                                     else BACKGROUND_CANDIDATES_PER_FRAME)
        self.assertGreater(sum(value for (actor, channel, kind), value in scene.counts.items()
                               if kind == 'component'), 0)
        self.assertGreater(maximum_global['foreground'], 0)

    def test_six_mixed_workers_commit_from_their_own_native_pose_and_ammunition(self):
        # HE damage ranking selects a different enemy from the initial nearest
        # strategic hint. The two HE hulls must turn naturally; initial poses
        # are deliberately not pre-aligned to the selected native candidate.
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene = self.scene()
            for unused in range(240):
                scene.step()
        self.assert_private_state_and_real_debits(scene, minimum_each=2)
        self.assertEqual({0, 2}, {event['shell_index'] for event in scene.launches_observed})
        self.assertEqual({1, 2}, {binding.gun.clip_size for binding in scene.engine._actor_controls.values()})
        for actor in scene.actor_ids:
            observations = [frame['actors'][actor] for frame in scene.frames]
            self.assertTrue(any(row['reload'] > 0. for row in observations))
            self.assertTrue(any(row['clip'] > 0 and row['seq'] > 0 for row in observations))
            self.assertTrue(all('clock' not in row for row in observations))
        self.assert_budget_receipts(scene)

    def test_complete_native_failure_can_select_he_without_a_timer_while_peers_fire(self):
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene = self.scene(diverse=False)
            failing = self.low_penetration_worker(scene)
            # A complete native armour-failure certificate, not an elapsed
            # search clock, admits the available HE fallback. Peers retain
            # independent native budgets, loading and physical triggers.
            atomic_now = [0.]
            failing.attack_policy.atomic_clock = lambda: atomic_now[0]
            first_he_load = None
            seen_native_failure = False
            for unused in range(650):
                scene.step()
                policy = failing.attack_policy
                self.assertFalse(hasattr(policy, 'search_started'))
                self.assertFalse(hasattr(policy, 'search_authority'))
                for actor in (12, 13, 14, 15, 16):
                    peer = scene.engine._actor_controls[actor]
                    self.assertFalse(hasattr(peer.attack_policy, 'search_started'))
                    self.assertIsNot(policy.atomic_clock, peer.attack_policy.atomic_clock)
                if any(domain['all_failed'] for domain in policy.status()['failure_domains']):
                    seen_native_failure = True
                if failing.gun.shot_index == 2 and first_he_load is None:
                    first_he_load = scene.now
                if first_he_load is not None and any(
                        event['id'] == 11 for event in scene.launches_observed):
                    break
        self.assertTrue(seen_native_failure or first_he_load is not None,
                        failing.attack_policy.status())
        self.assertIsNotNone(first_he_load, failing.attack_policy.status())
        self.assert_private_state_and_real_debits(scene)
        fallback_shots = [event for event in scene.launches_observed if event['id'] == 11]
        self.assertEqual(1, len(fallback_shots), failing.attack_policy.status())
        self.assertEqual(2, fallback_shots[0]['shell_index'])
        self.assertGreaterEqual(fallback_shots[0]['evidence']['at'], first_he_load)
        self.assertEqual((24, 0, 11), tuple(failing.gun.ammo))
        self.assertGreaterEqual(sum(event['id'] != 11 for event in scene.launches_observed), 10)
        self.assert_budget_receipts(scene)

    def test_atomic_deadline_keeps_partial_native_failure_pending_while_peers_fire(self):
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene = self.scene(diverse=False)
            failing = self.low_penetration_worker(scene)
            policy = failing.attack_policy
            atomic_now = [0.]
            policy.atomic_clock = lambda: atomic_now[0]
            native_evaluate = policy.evaluator.evaluate
            slow_evaluations = []

            def slow_native_evaluation(*args, **kwargs):
                # Run the original native evaluator and its instrumentation
                # first. Only its observed elapsed time is synthetic: one
                # completed candidate costs 9 ms against the unchanged 8 ms.
                result = native_evaluate(*args, **kwargs)
                channel = args[6] if len(args) > 6 else kwargs['channel']
                if channel == 'atomic':
                    atomic_now[0] += ATOMIC_WALL_SECONDS + .001
                    slow_evaluations.append((scene.now, result.get('line'), result.get('armor')))
                return result

            policy.evaluator.evaluate = slow_native_evaluation
            timed_out = []
            for unused in range(180):
                scene.step()
                status = policy.status()
                self.assertFalse(hasattr(policy, 'search_started'), status)
                self.assertFalse(any(domain['all_failed'] for domain in
                                     status['failure_domains']), status)
                receipt = status['atomic']
                if receipt.get('reason') == 'atomic_frame_budget_exhausted':
                    self.assertEqual('incomplete', receipt['status'])
                    self.assertGreater(receipt['evaluations'], 0)
                    self.assertLess(receipt['evaluations'], receipt['candidates'])
                    self.assertGreaterEqual(receipt['elapsed_ms'], 8.)
                    self.assertEqual('global_snapshot_budget_pending', status['reason'])
                    timed_out.append(receipt['observed_at'])
                for actor in (12, 13, 14, 15, 16):
                    self.assertFalse(hasattr(
                        scene.engine._actor_controls[actor].attack_policy, 'search_started'))
                    self.assertIsNot(policy.atomic_clock,
                        scene.engine._actor_controls[actor].attack_policy.atomic_clock)
        self.assertTrue(slow_evaluations)
        self.assertTrue(timed_out)
        self.assertGreater(scene.now - timed_out[0], 2.,
            'an incomplete native review may remain pending across frames')
        self.assertGreater(scene.counts[(11, 'atomic', 'world')], 0)
        self.assertGreater(scene.counts[(11, 'atomic', 'component')], 0)
        self.assertEqual(ATOMIC_WALL_SECONDS, policy.atomic_time_budget)
        self.assertEqual(scene.initial_ammo[11], tuple(failing.gun.ammo))
        self.assertFalse(any(event['id'] == 11 for event in scene.launches_observed))
        self.assertGreater(len(scene.launches_observed), 10)
        self.assert_private_state_and_real_debits(scene)
        self.assert_budget_receipts(scene)

    def test_one_workers_unresolved_native_wall_does_not_create_team_armour_failure(self):
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene = self.scene(diverse=False)
            # Native engine damage holds this source behind a box wall. Its
            # turret/loaded gun remain real; peers can still shoot other rays.
            scene.engine.states[11]['critical'] = dict(
                destroyed=['engineHealth'], crew_ko=[], devices=[])
            scene.world[:] = [((-22., -2., -23.), (-10., 5., -20.))]
            for unused in range(180):
                scene.step()
                blocked = scene.engine._actor_controls[11]
                self.assertFalse(hasattr(blocked.attack_policy, 'search_started'))
                self.assertFalse(any(domain.get('all_failed') for domain in
                                     blocked.attack_policy.status()['failure_domains']))
        self.assert_private_state_and_real_debits(scene)
        self.assertFalse(any(event['id'] == 11 for event in scene.launches_observed))
        self.assertGreater(len(scene.launches_observed), 10)
        self.assertTrue(any(actor == 11 and line in ('pending', 'world_blocked', 'unknown')
            for at, actor, channel, target, line, passed, reason in scene.evaluations))
        self.assert_budget_receipts(scene)

    def test_native_pose_change_after_prepare_rejects_only_that_workers_commit(self):
        with contextlib.redirect_stdout(DiagnosticSink()):
            scene = self.scene(diverse=False)
            binding = scene.engine._control_for(scene.engine.states[11])
            native_validate = binding.validate_trigger
            changes = []

            def changed_physical_pose(proposal, now):
                # An external native movement between admission and final
                # commit must invalidate an otherwise real accepted token.
                # Do not replace the policy, prepare result or guard verdict.
                before = binding.source_pose()
                binding.state['x'] += .25
                scene.sync_native_poses()
                result = native_validate(proposal, now)
                changes.append((before, binding.source_pose(), result))
                return result

            binding.validate_trigger = changed_physical_pose
            for unused in range(60):
                scene.step()
        self.assertTrue(changes, 'the real worker never reached final validation')
        self.assertTrue(all(before != after and result == 'auto_pose_changed'
                            for before, after, result in changes), changes)
        self.assertFalse(any(event['id'] == 11 for event in scene.launches_observed))
        self.assertEqual(scene.initial_ammo[11], tuple(binding.gun.ammo))
        self.assertGreater(len(scene.launches_observed), 5)
        self.assert_private_state_and_real_debits(scene)


if __name__ == '__main__':
    unittest.main()
