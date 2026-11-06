"""Player magazine policy over real GunState clip and trigger transitions.

The descriptors cover behavior classes, not a claimed native vehicle catalog.
Only the native aiming verdict is supplied at the policy boundary. Ammunition,
pending selection, burst debits and full/intra-clip reloads use the real owner.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.gun_mechanics import GunState
from gui.mods.offline_lan_0922.player_control.direct_engagement import DirectEngagement


class MagazineScene:
    def __init__(self, clip=6, burst=3, loaded=0, limits=None, stock=30, samples=2):
        self.descriptor = SimpleNamespace(
            gun=SimpleNamespace(
                shots=tuple(dict(shell=dict(compactDescr=100 + index),
                                 piercingPower=power) for index, power in enumerate(
                                     ((200., 180.), (250., 220.), (100., 100.)))),
                shotDispersionAngle=.1,
                shotDispersionFactors=dict(afterShot=4., afterShotInBurst=1., turretRotation=0.),
                aimingTime=1., reloadTime=12., clip=(clip, .8), burst=(burst, .1),
                maxAmmo=90, turretYawLimits=limits),
            chassis=dict(shotDispersionFactors=(0., 0.)),
            turret=dict(maxAmmo=90), maxAmmo=90, activeGunShotIndex=loaded)
        self.gun = GunState(self.descriptor, ammo_layout={100 + index: stock for index in range(3)})
        self.gun.clip, self.gun.reload_time = min(clip, stock), 0.
        self.target = SimpleNamespace(id=21)
        self.owner = SimpleNamespace(_gun_state=self.gun, _local_player_burst=None,
                                     _local_fire_intent=None)
        self.state = DirectEngagement(self.descriptor)
        self.verdicts = {}
        self.nominal = {}
        self.calls = []
        self.queued = []
        self.reloads = []
        self.immediate = []
        self.pose = ((0., 0., 0.), 0., (0., 0., 20.), 0., 0., 0., 0.)
        self.control = SimpleNamespace(owner=self.owner,
            ammo_policy=SimpleNamespace(main=0, shells=[
                dict(index=0, kind='ARMOR_PIERCING', premium=False),
                dict(index=1, kind='ARMOR_PIERCING_CR', premium=True),
                dict(index=2, kind='HIGH_EXPLOSIVE', premium=False)]),
            aiming=SimpleNamespace(compare_direct=self.compare,
                direct_samples=lambda target: samples, direct_pose=lambda target: self.pose,
                defer_ordered_point=lambda *args: None),
            lane_from=lambda *args: True,
            queue_automatic_shell=self.immediate.append,
            queue_next_automatic_clip=self.queue,
            reload_automatic_clip=self.reload)

    def compare(self, target, shell, sample, now, lane, threshold, **options):
        self.calls.append((shell, sample, bool(options.get('physical')), options))
        verdicts = self.nominal if options.get('nominal') else self.verdicts
        verdict = verdicts.get((shell, sample), 'armor')
        solution = dict(created=now, sample=sample, key=(sample, 'low'),
                        geometry_clear=True, nominal_armor=25. + sample,
                        reachable=True, source_verified=True)
        if verdict == 'needs_hull':
            solution.update(needs_hull=True, reachable=False, source_verified=False,
                            reason='yaw_limit', clear=False)
        return verdict, solution

    def queue(self, selected):
        self.queued.append(selected)
        if self.owner._local_player_burst or self.owner._local_fire_intent or self.gun.clip <= 0:
            return False
        self.gun.request_shell_index(self.gun.shot_index if selected is None else selected)
        return True

    def reload(self, selected):
        self.reloads.append((selected, self.state.retreat))
        if not self.queue(selected):
            return False
        return self.gun.reload_partial_clip()

    def update(self, now, candidates=None):
        return self.state.update(self.control, [self.target] if candidates is None else candidates, now)

    def ready(self, shell, sample=0):
        self.verdicts[(shell, sample)] = 'ready'

    def trigger(self):
        count = min(self.gun.burst_count, self.gun.clip, self.gun.ammo[self.gun.shot_index])
        self.gun.begin_burst(count)
        shells = []
        for index in range(count):
            shells.append(self.gun.shot_index)
            if not self.gun.commit_burst_round(index == count - 1):
                raise AssertionError('real GunState rejected an expected physical burst round')
        return shells


class MagazinePolicyTests(unittest.TestCase):
    def test_plan_next_clip_while_current_clip_is_still_full(self):
        for clip, burst, limits in ((4, 1, None), (6, 3, None), (10, 2, (-.2, .2))):
            with self.subTest(clip=clip, burst=burst, limits=limits):
                scene = MagazineScene(clip, burst, limits=limits)
                scene.ready(0)
                scene.ready(2)
                for now in (0., .1, .2):
                    unused_target, unused_solution, clear = scene.update(now)
                self.assertTrue(clear)
                self.assertEqual(2, scene.gun.pending_index)
                self.assertEqual((0, clip, 0.),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertEqual([], scene.immediate)

    def test_last_trigger_promotes_the_plan_after_all_physical_rounds(self):
        for clip, burst, remaining in ((6, 3, 3), (5, 3, 2), (4, 1, 1), (3, 3, 3)):
            with self.subTest(clip=clip, burst=burst, remaining=remaining):
                scene = MagazineScene(clip, burst)
                scene.gun.clip = remaining
                scene.ready(0)
                scene.ready(2)
                for now in (0., .1, .2):
                    scene.update(now)
                self.assertEqual([0] * remaining, scene.trigger())
                self.assertEqual((2, 0, scene.gun.reload),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertEqual(30 - remaining, scene.gun.ammo[0])
                self.assertEqual(30, scene.gun.ammo[2])

    def test_pending_next_clip_comparison_does_not_block_a_proved_current_trigger(self):
        scene = MagazineScene(4, 1)
        scene.gun.clip = 1
        scene.ready(0)
        scene.verdicts[(2, 0)] = 'pending'
        target, solution, clear = scene.update(0.)
        self.assertIs(scene.target, target)
        self.assertIsNotNone(solution)
        self.assertTrue(clear)
        self.assertIsNone(scene.gun.pending_index)
        self.assertEqual([], scene.reloads)

    def test_next_clip_plan_can_be_replaced_and_cancelled_before_last_trigger(self):
        scene = MagazineScene(6, 3, loaded=1)
        scene.ready(1)
        scene.ready(2)
        scene.ready(0)
        for now in (0., .1, .2):
            scene.update(now)
        self.assertEqual(2, scene.gun.pending_index)
        scene.verdicts[(2, 0)] = 'armor'
        for now in (.3, .4, .5):
            scene.update(now)
        self.assertEqual(0, scene.gun.pending_index)
        scene.verdicts[(0, 0)] = 'armor'
        for now in (.6, .7, .8):
            scene.update(now)
        self.assertIsNone(scene.gun.pending_index)
        self.assertEqual((1, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual([], scene.reloads)

    def test_unknown_current_clip_never_authorizes_an_early_reload(self):
        scene = MagazineScene(6, 3)
        scene.verdicts[(0, 0)] = 'unknown'
        scene.ready(2)
        for now in (0., .1, 10., 20., 30.):
            scene.update(now)
        self.assertIsNone(scene.state.search_since)
        self.assertEqual([], scene.reloads)
        self.assertEqual([], scene.immediate)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_empty_full_reload_cannot_be_restarted_by_a_new_comparison(self):
        scene = MagazineScene(6, 3)
        scene.gun.clip, scene.gun.reload_time = 0, 9.
        scene.ready(2)
        for now in (0., .1, 10.):
            scene.update(now)
        self.assertEqual((0, 0, 9.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual([], scene.queued)
        self.assertEqual([], scene.immediate)
        self.assertEqual([], scene.reloads)

    def test_hull_required_current_clip_is_a_nonfiring_candidate(self):
        scene = MagazineScene(6, 3, limits=(-.2, .2))
        scene.verdicts[(0, 0)] = 'needs_hull'
        scene.ready(2)
        target, solution, clear = scene.update(0.)
        self.assertIs(scene.target, target)
        self.assertTrue(solution['needs_hull'])
        self.assertFalse(clear)
        self.assertEqual(0, scene.state.stage[0])
        self.assertEqual(0, scene.state.sample)
        self.assertIsNone(scene.state.search_since)
        self.assertEqual([], scene.immediate)
        self.assertEqual([], scene.reloads)

    def test_wall_clock_without_a_search_attempt_cannot_unload_the_clip(self):
        scene = MagazineScene(6, 3)
        scene.ready(2)
        for now in (0., .1, 8.1, 8.2, 8.3, 30., 30.1, 30.2):
            scene.update(now)
        self.assertEqual([], scene.reloads)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_active_search_timeout_requests_withdrawal_before_native_reload(self):
        for moved, loaded in ((True, 0), (False, 0), (True, 2), (False, 2)):
            with self.subTest(moved=moved, loaded=loaded):
                scene = MagazineScene(6, 3, loaded=loaded)
                scene.ready(1)
                scene.update(0.)
                self.assertTrue(scene.state.seek)
                scene.state.observe_search(0., scene.pose[0], scene.pose[1], True)
                for second in range(1, 9):
                    if moved:
                        scene.pose = ((second * .2, 0., 0.), 0.) + scene.pose[2:]
                    scene.update(float(second))
                    scene.state.observe_search(float(second), scene.pose[0], scene.pose[1], True)
                for now in (8.1, 8.2, 8.3, 8.4):
                    scene.update(now)
                    if scene.state.reload_requested is not None:
                        break
                self.assertTrue(scene.state.retreat)
                self.assertFalse(scene.state.seek)
                self.assertEqual(1, scene.state.reload_requested)
                self.assertEqual([], scene.reloads)
                self.assertEqual((loaded, 6, 0.),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertTrue(scene.reload(scene.state.reload_requested))
                scene.state.clip_reload_started(scene.gun)
                self.assertEqual([(1, True)], scene.reloads)
                self.assertEqual((1, 0, scene.gun.reload),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertIsNone(scene.state.reload_requested)

    def test_search_budget_pauses_without_a_search_owner_including_scan_only_waits(self):
        scene = MagazineScene(6, 3)
        scene.ready(2)
        scene.update(0.)
        scene.state.observe_search(0., scene.pose[0], scene.pose[1], True)
        scene.update(2.)
        scene.state.observe_search(2., scene.pose[0], scene.pose[1], True)
        self.assertAlmostEqual(2., scene.state.search_elapsed)
        scene.state.observe_search(2.1, scene.pose[0], scene.pose[1], False)
        scene.update(10.)
        scene.state.observe_search(10., scene.pose[0], scene.pose[1], True)
        self.assertAlmostEqual(2., scene.state.search_elapsed)
        scene.verdicts[(0, 0)] = 'pending'
        scene.update(20.)
        scene.state.observe_search(20., scene.pose[0], scene.pose[1], False)
        self.assertAlmostEqual(2., scene.state.search_elapsed)
        self.assertIsNone(scene.state.reload_requested)

    def test_multiframe_scan_does_not_starve_a_real_search_attempt_clock(self):
        scene = MagazineScene(6, 3, samples=6)
        scene.ready(2)
        for tick in range(96):
            now = tick * .1
            scene.update(now)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
            if scene.state.reload_requested is not None:
                break
        self.assertEqual(8., scene.state.search_elapsed)
        self.assertEqual(2, scene.state.reload_requested)
        self.assertEqual([], scene.reloads)

    def test_real_search_attempts_remain_bounded_when_each_point_needs_native_slices(self):
        scene = MagazineScene(6, 3, samples=6)
        scene.ready(2)
        compare = scene.control.aiming.compare_direct
        slices = {}
        def sliced(target, shell, sample, now, lane, threshold, **options):
            key = shell, sample
            slices[key] = slices.get(key, 0) + 1
            if slices[key] % 2:
                return 'pending', None
            return compare(target, shell, sample, now, lane, threshold, **options)
        scene.control.aiming.compare_direct = sliced
        for tick in range(160):
            now = tick * .1
            scene.update(now)
            if scene.state.native_deferred:
                self.assertIsNone(scene.state.reload_requested)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
            if scene.state.reload_requested is not None:
                break
        self.assertEqual(8., scene.state.search_elapsed)
        self.assertEqual(2, scene.state.reload_requested)
        self.assertEqual([], scene.reloads)

    def test_deferred_unused_current_point_cannot_hide_an_already_ready_point(self):
        scene = MagazineScene(6, 3)
        scene.ready(0, 0)
        scene.verdicts[(0, 1)] = 'pending'
        target, solution, clear = scene.update(0.)
        self.assertIs(scene.target, target)
        self.assertTrue(clear)
        self.assertEqual(0, solution['sample'])
        self.assertEqual([], scene.reloads)

    def test_new_usable_point_and_successful_trigger_clear_the_search_budget(self):
        scene = MagazineScene(6, 3)
        scene.update(0.)
        scene.state.observe_search(0., scene.pose[0], scene.pose[1], True)
        scene.update(4.)
        scene.state.observe_search(4., scene.pose[0], scene.pose[1], True)
        self.assertAlmostEqual(4., scene.state.search_elapsed)
        scene.ready(0, 1)
        target, solution, clear = scene.update(4.1)
        self.assertIs(scene.target, target)
        self.assertTrue(clear)
        self.assertEqual(1, scene.state.sample)
        self.assertFalse(scene.state.seek)
        self.assertEqual(4., scene.state.search_elapsed)
        self.assertEqual([0, 0, 0], scene.trigger())
        scene.state.shot_admitted(scene.target.id)
        self.assertEqual(0., scene.state.search_elapsed)
        self.assertIsNone(scene.state.search_since)
        self.assertIsNone(scene.state.reload_requested)

    def test_next_clip_plan_can_use_a_different_penetrating_point(self):
        scene = MagazineScene(6, 3)
        scene.ready(0, 0)
        scene.ready(2, 1)
        for tick in range(8):
            target, solution, clear = scene.update(tick * .1)
            self.assertIs(scene.target, target)
            self.assertTrue(clear)
        self.assertEqual(0, scene.state.sample)
        self.assertEqual(2, scene.gun.pending_index)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_loaded_he_fallback_keeps_the_clip_and_can_plan_another_shell(self):
        scene = MagazineScene(6, 3, loaded=2)
        scene.nominal[(2, 1)] = 'ready'
        for tick in range(100):
            now = tick * .1
            target, solution, clear = scene.update(now)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
            if clear:
                break
        self.assertGreaterEqual(now, 8.)
        self.assertTrue(clear)
        self.assertTrue(scene.state.fallback)
        self.assertEqual((2, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual([], scene.reloads)
        self.assertIsNone(scene.state.reload_requested)
        scene.ready(0, 0)
        for offset in range(1, 15):
            scene.update(now + offset * .1)
        self.assertEqual(0, scene.gun.pending_index)
        self.assertEqual((2, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_he_fallback_is_a_next_clip_request_and_rechecks_after_full_reload(self):
        scene = MagazineScene(6, 3)
        scene.nominal[(2, 1)] = 'ready'
        for tick in range(100):
            now = tick * .1
            scene.update(now)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
            if scene.state.reload_requested is not None:
                break
        self.assertEqual(2, scene.state.reload_requested)
        self.assertTrue(scene.state.retreat)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertTrue(scene.reload(2))
        self.assertTrue(scene.state.clip_reload_started(scene.gun))
        scene.update(now + .1)
        scene.gun.tick(scene.gun.reload, True, 0., 0., 0., scene.descriptor)
        scene.calls[:] = []
        target, solution, clear = scene.update(now + scene.gun.reload)
        self.assertIs(scene.target, target)
        self.assertTrue(clear)
        self.assertTrue(scene.state.fallback)
        self.assertEqual(1, scene.state.sample)
        self.assertEqual((2, 6), (scene.gun.shot_index, scene.gun.clip))
        self.assertTrue(scene.calls[0][2])
        self.assertTrue(scene.calls[0][3]['nominal'])

    def test_unknown_alternate_after_timeout_cannot_authorize_he_fallback(self):
        scene = MagazineScene(6, 3)
        scene.verdicts[(1, 1)] = 'unknown'
        scene.nominal[(2, 1)] = 'ready'
        for tick in range(150):
            now = tick * .1
            scene.update(now)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
        self.assertIsNone(scene.state.reload_requested)
        self.assertFalse(scene.state.fallback)
        self.assertFalse(any(call[3].get('nominal') for call in scene.calls))
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_each_trigger_rechecks_its_point_but_a_physical_burst_keeps_its_shell(self):
        scene = MagazineScene(6, 3)
        scene.ready(0, 0)
        scene.ready(2, 0)
        for now in (0., .1, .2):
            scene.update(now)
        self.assertTrue(scene.gun.begin_burst(3))
        scene.owner._local_player_burst = dict(shell_index=0, count=3)
        self.assertTrue(scene.gun.commit_burst_round(False))
        scene.verdicts[(0, 0)] = 'armor'
        scene.ready(0, 1)
        scene.update(.3)
        self.assertTrue(scene.gun.commit_burst_round(False))
        scene.update(.4)
        self.assertEqual((0, 1), (scene.gun.shot_index, scene.gun._burst_remaining))
        self.assertTrue(scene.gun.commit_burst_round(True))
        self.assertEqual((0, 3, scene.gun.clip_reload),
                         (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        scene.owner._local_player_burst = None
        scene.gun.tick(scene.gun.clip_reload, True, 0., 0., 0., scene.descriptor)
        for now in (1.2, 1.3):
            target, solution, clear = scene.update(now)
        self.assertIs(scene.target, target)
        self.assertTrue(clear)
        self.assertEqual(1, scene.state.sample)
        self.assertEqual([], scene.immediate)
        self.assertEqual([], scene.reloads)

    def test_two_candidate_budget_protects_current_trigger_before_next_clip_work(self):
        scene = MagazineScene(6, 3)
        scene.ready(0, 0)
        scene.ready(2, 1)
        compare = scene.control.aiming.compare_direct
        remaining = [0]
        charged = []
        def budgeted(*args, **options):
            if remaining[0] <= 0:
                return 'pending', None
            remaining[0] -= 1
            charged.append((args[1], bool(options.get('physical'))))
            return compare(*args, **options)
        scene.control.aiming.compare_direct = budgeted
        for tick in range(12):
            charged[:] = []
            remaining[0] = 2
            target, solution, clear = scene.update(tick * .1)
            self.assertIs(scene.target, target)
            self.assertTrue(clear)
            self.assertLessEqual(len(charged), 2)
            if tick:
                self.assertEqual((0, True), charged[0])
        self.assertEqual(2, scene.gun.pending_index)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_a_cross_frame_alternate_hit_is_rechecked_before_reload_permission(self):
        for changed in ('unknown', 'pending', 'armor'):
            with self.subTest(changed=changed):
                scene = MagazineScene(6, 3)
                scene.ready(2, 0)
                compare = scene.control.aiming.compare_direct
                comparisons = [0]
                def lost(target, shell, sample, now, lane, threshold, **options):
                    if (shell, sample) == (2, 0):
                        comparisons[0] += 1
                        if comparisons[0] > 1:
                            return changed, None
                    return compare(target, shell, sample, now, lane, threshold, **options)
                scene.control.aiming.compare_direct = lost
                for tick in range(120):
                    now = tick * .1
                    scene.update(now)
                    scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
                    self.assertIsNone(scene.state.reload_requested)
                self.assertGreater(comparisons[0], 1)
                self.assertEqual((0, 6, 0.),
                                 (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
                self.assertEqual([], scene.reloads)

    def test_reload_recheck_resumes_after_the_two_candidate_budget_is_spent(self):
        scene = MagazineScene(6, 3)
        scene.ready(2, 0)
        compare = scene.control.aiming.compare_direct
        remaining = [0]
        def budgeted(*args, **options):
            if remaining[0] <= 0:
                return 'pending', None
            remaining[0] -= 1
            return compare(*args, **options)
        scene.control.aiming.compare_direct = budgeted
        saw_deferred_recheck = False
        for tick in range(120):
            remaining[0] = 2
            now = tick * .1
            scene.update(now)
            scene.state.observe_search(now, scene.pose[0], scene.pose[1], True)
            if scene.state._reload_candidate is not None:
                saw_deferred_recheck = True
                self.assertIsNone(scene.state.reload_requested)
            if scene.state.reload_requested is not None:
                break
        self.assertTrue(saw_deferred_recheck)
        self.assertEqual(2, scene.state.reload_requested)
        self.assertTrue(scene.state.retreat)
        self.assertEqual((0, 6, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_replaced_gun_cannot_inherit_the_previous_search_timeout(self):
        scene = MagazineScene(6, 3)
        scene.update(0.)
        scene.state.observe_search(0., scene.pose[0], scene.pose[1], True)
        scene.update(4.)
        scene.state.observe_search(4., scene.pose[0], scene.pose[1], True)
        self.assertEqual(4., scene.state.search_elapsed)
        replacement = MagazineScene(5, 1, loaded=2)
        scene.gun = scene.owner._gun_state = replacement.gun
        scene.update(20.)
        self.assertEqual(0., scene.state.search_elapsed)
        self.assertEqual(20., scene.state.search_since)
        self.assertIsNone(scene.state.reload_requested)
        self.assertEqual((2, 5, 0.), (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))

    def test_inventory_shortened_last_trigger_uses_the_next_clip_plan(self):
        scene = MagazineScene(6, 3, stock=2)
        scene.ready(0)
        scene.ready(2)
        for now in (0., .1, .2):
            scene.update(now)
        self.assertEqual(2, scene.gun.clip)
        self.assertEqual([0, 0], scene.trigger())
        self.assertEqual((2, 0, scene.gun.reload),
                         (scene.gun.shot_index, scene.gun.clip, scene.gun.reload_time))
        self.assertEqual((0, 2), (scene.gun.ammo[0], scene.gun.ammo[2]))


if __name__ == '__main__':
    unittest.main()
