"""Foreground-only regression coverage for ordered engagement and HE fallback."""
import math
import sys
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.aiming import Aiming
from gui.mods.offline_lan_0922.player_control.direct_engagement import (
    DirectEngagement, PENETRATION_FACTOR_65)


class DirectEngagementTests(unittest.TestCase):
    def setUp(self):
        self.state = DirectEngagement(None)
        self.gun = SimpleNamespace(ammo=[8, 8, 8], shots=[
            dict(piercingPower=(200., 180.)), dict(piercingPower=(250., 220.)),
            dict(piercingPower=(100., 100.))], shot_index=0, reload_time=0.,
            clip_size=1, clip=1)
        self.rounds = SimpleNamespace(main=0, shells=[
            dict(index=0, kind='ARMOR_PIERCING', premium=False),
            dict(index=1, kind='ARMOR_PIERCING_CR', premium=True),
            dict(index=2, kind='HIGH_EXPLOSIVE', premium=False)])
        self.calls = []
        self.verdicts = {}
        self.control = SimpleNamespace(owner=SimpleNamespace(_gun_state=self.gun),
            ammo_policy=self.rounds, aiming=SimpleNamespace(compare_direct=self.probe, defer_ordered_point=mock.Mock(),
                direct_samples=lambda target: 2, direct_pose=lambda target:
                    ((0, 0, 0), 0., (0, 0, 10), 0., 0., 0., 0.)),
            queue_automatic_shell=self.calls.append, lane_from=lambda *args: True,
            queue_next_automatic_clip=mock.Mock(), reload_automatic_clip=mock.Mock(return_value=True))
        self.first = SimpleNamespace(id=21)
        self.second = SimpleNamespace(id=22)

    def probe(self, target, index, point, now, lane, threshold, **kwargs):
        status = self.verdicts.get((target.id, index, point), 'armor')
        solution = dict(created=now, key=(point, 'low'), geometry_clear=True,
                        nominal_armor=70 if point == 0 else 25)
        return ('ready', solution) if kwargs.get('nominal') else (status, solution)

    def test_checks_every_point_and_chooses_he_before_premium(self):
        self.verdicts[(21, 1, 0)] = 'ready'
        self.verdicts[(21, 2, 1)] = 'ready'
        for tick in range(3):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual([2], self.calls)
        self.assertEqual(1, self.state.sample)

    def test_keeps_loaded_ap_when_another_point_penetrates_and_plans_he_next(self):
        self.verdicts.update({(21, 1, 0): 'ready', (21, 2, 0): 'ready',
                              (21, 0, 1): 'ready'})
        with mock.patch.object(self.control.aiming, 'compare_direct', wraps=self.probe) as compare:
            for tick in range(3):
                target, solution, fire_clear = self.state.update(self.control, [self.first], tick*.1)
        self.assertTrue(fire_clear)
        self.assertIs(target, self.first)
        self.assertEqual(1, self.state.sample)
        self.assertEqual(2, self.state.next_shell)
        self.assertEqual([], self.calls)
        self.assertEqual({(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)},
                         {call.args[1:3] for call in compare.call_args_list})

    def test_does_not_restart_apcr_reload_when_new_target_can_take_both_shells(self):
        self.gun.ammo[2] = 0
        self.verdicts[(21, 1, 0)] = 'ready'
        def switch(index):
            self.calls.append(index)
            self.gun.shot_index, self.gun.clip, self.gun.reload_time = index, 0, 6.7
        self.control.queue_automatic_shell = switch
        for tick in range(3):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual([1], self.calls)
        self.verdicts[(22, 0, 1)] = self.verdicts[(22, 1, 0)] = 'ready'
        for tick in range(3):
            self.state.update(self.control, [self.second], 1. + tick*.1)
        self.assertEqual([1], self.calls)
        self.assertEqual((1, 0, 6.7), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
        self.gun.clip, self.gun.reload_time = 1, 0.
        target, solution, fire_clear = self.state.update(self.control, [self.second], 8.)
        self.assertIs(target, self.second)
        self.assertTrue(fire_clear)
        self.assertEqual(0, self.state.next_shell)

    def test_old_aim_cannot_unload_a_shell_selected_at_the_previous_shot_boundary(self):
        self.state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        self.state.sample = 1
        self.gun.shot_index = 2
        self.gun.clip, self.gun.reload_time = 0, 6.7
        self.state.update(self.control, [self.first], 1.)
        self.assertEqual([], self.calls)
        self.assertIsNone(self.state.sample)
        self.assertEqual((2, 6.7), (self.gun.shot_index, self.gun.reload_time))

    def test_unknown_current_ammo_does_not_authorize_a_reload(self):
        self.verdicts[(21, 0, 1)] = 'unknown'
        self.verdicts[(21, 1, 0)] = 'ready'
        for tick in range(6):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual([], self.calls)

    def test_current_barrel_failure_requires_full_scan_before_switch(self):
        self.verdicts[(21, 1, 0)] = 'ready'
        self.verdicts[(21, 0, 1)] = 'ready'
        self.state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        self.state.motion = self.control.aiming.direct_pose(self.first)
        self.state.sample = 0
        self.state.last_solution = dict(created=0.)
        for tick in range(5):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual([], self.calls)
        self.assertEqual(1, self.state.sample)

    def test_direct_comparison_trace_distinguishes_budget_and_unobserved_target(self):
        aiming = Aiming.__new__(Aiming)
        aiming._candidates, aiming._segments, aiming._angles = 0, 8, 10
        aiming.targets = {self.first.id: self.first}
        aiming.comparison_trace = []
        for target in (self.first, self.second):
            self.assertEqual(('pending', None), aiming.compare_direct(target, 1, 2, 1.,
                lambda *args: True, PENETRATION_FACTOR_65, physical=True))
        first, second = aiming.comparison_trace
        self.assertEqual(('candidate_budget', 'target_not_observed'),
                         (first['reason'], second['reason']))
        self.assertEqual((0, 8, 10), first['before'])
        self.assertEqual(first['before'], first['after'])
        self.assertEqual(('physical', 1, 2), (first['mode'], first['shell'], first['sample']))
        aiming.comparison_trace = None
        self.assertEqual(('pending', None), aiming.compare_direct(self.first, 1, 2, 1.,
            lambda *args: True, PENETRATION_FACTOR_65, physical=True))
        self.assertIsNone(aiming.comparison_trace)

    def test_pivot_point_proof_is_independent_of_live_barrel_alignment(self):
        aiming = Aiming.__new__(Aiming)
        target = SimpleNamespace(id=21, typeDescriptor=object())
        aiming.owner = SimpleNamespace(_mutable_shot_ray=lambda: ((0, 0, 0), (0, 0, 1)))
        aiming.targets = {21: target}
        aiming._candidates = aiming._segments = 8
        aiming.comparison_deferrals = {}
        aiming._front_point_blocked = lambda *args: False
        aiming._own = lambda index: {}
        aiming._advance = mock.Mock(side_effect=lambda job, *args: job.update(done=True, clear=True))
        aiming._result = lambda solution, job: solution
        aiming.actual_contact = mock.Mock(return_value='laying')
        with mock.patch('gui.mods.offline_lan_0922.player_control.aiming.shot_geometry.'
                        'ordered_vehicle_aim_samples', return_value=[object()]):
            for proof, expected in ((True, 'laying'), (False, 'armor'), (None, 'unknown')):
                aiming.comparison_jobs = {}
                aiming._candidate = mock.Mock(return_value=dict(
                    geometry_clear=True, reachable=True, source_verified=True,
                    direction=(.1, 0, .99), penetration_ok=proof))
                verdict, result = aiming.compare_direct(target, 0, 0, 1., lambda a, b: True,
                    PENETRATION_FACTOR_65, physical=True, verify_point=True)
                self.assertEqual(expected, verdict)
                self.assertEqual(proof is True, bool(result.get('point_viable')))
                self.assertEqual(PENETRATION_FACTOR_65, aiming._candidate.call_args.args[-1])

    def test_he_main_prefers_lowest_piercing_alternative_and_skips_empty(self):
        self.rounds.main = 2
        self.gun.shots[0]['piercingPower'] = (300., 250.)
        self.assertEqual([2, 1, 0], [row['index'] for row in self.state.shells(self.rounds, self.gun)])
        self.gun.ammo[1] = 0
        self.assertEqual([2, 0], [row['index'] for row in self.state.shells(self.rounds, self.gun)])

    def test_search_expires_before_nominal_he_fallback(self):
        for tick in range(3):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual(.2, self.state.search_since)
        self.assertEqual([], self.calls)
        self.state.update(self.control, [self.first], 8.21)
        self.assertEqual([2], self.calls)
        self.assertEqual(1, self.state.sample)
        self.assertTrue(self.state.fallback)

    def test_expired_search_keeps_loaded_apcr_on_a_new_target(self):
        self.gun.shot_index = 1
        self.state.adopt(self.first.id)
        self.state.search_since = 1.
        self.verdicts[(22, 1, 1)] = 'ready'
        with mock.patch.object(self.control.aiming, 'compare_direct', wraps=self.probe) as compare:
            self.state.update(self.control, [self.second], 10.)
            self.state.update(self.control, [self.second], 10.1)
            target, unused, ready = self.state.update(self.control, [self.second], 10.2)
        self.assertIs(self.second, target)
        self.assertTrue(ready)
        self.assertEqual(1, self.state.sample)
        self.assertFalse(self.state.fallback)
        self.assertEqual([], self.calls)
        self.assertEqual(1., self.state.search_since)
        self.assertEqual([(2, 0), (0, 0), (1, 0), (2, 1), (0, 1), (1, 1)],
                         [call.args[1:3] for call in compare.call_args_list[:6]])

    def test_expired_search_checks_new_target_before_allowing_he_fallback(self):
        self.state.adopt(self.first.id)
        self.state.search_since = 1.
        self.state.update(self.control, [self.second], 10.)
        self.assertEqual([], self.calls)
        for now in (10.1, 10.2):
            self.state.update(self.control, [self.second, self.first], now)
            self.assertEqual([], self.calls)
        self.assertEqual(self.second.id, self.state.target)
        self.state.update(self.control, [self.second, self.first], 10.3)
        self.assertEqual([2], self.calls)
        self.assertTrue(self.state.fallback)
        self.assertEqual(1, self.state.sample)
        self.assertEqual(1., self.state.search_since)

    def test_expired_search_does_not_treat_new_target_unknown_as_armor(self):
        self.state.adopt(self.first.id)
        self.state.search_since = 1.
        self.verdicts[(22, 0, 1)] = 'unknown'
        self.state.update(self.control, [self.second], 10.)
        for now in (10.1, 10.2, 10.3, 10.4, 10.5):
            self.state.update(self.control, [self.second, self.first], now)
        self.assertEqual(self.first.id, self.state.target)
        self.assertEqual([], self.calls)
        self.assertFalse(self.state.fallback)
        self.assertEqual(1., self.state.search_since)

    def test_failed_splash_sweep_can_rotate_back_to_penetration(self):
        self.state.adopt(self.first.id)
        self.state.search_since = 1.
        self.verdicts[(22, 0, 1)] = 'ready'
        probe = self.probe
        def compare(*args, **kwargs):
            return ('unavailable', None) if kwargs.get('nominal') else probe(*args, **kwargs)
        self.control.aiming.compare_direct = compare
        for now in (10., 10.1, 10.2, 10.3, 10.4, 10.5):
            self.state.update(self.control, [self.first, self.second], now)
        target, unused, ready = self.state.update(self.control, [self.first, self.second], 10.6)
        self.assertIs(self.second, target)
        self.assertTrue(ready)
        self.assertEqual([], self.calls)
        self.assertEqual(1., self.state.search_since)

    def test_search_clock_survives_ready_point_until_shot_is_admitted(self):
        self.gun.ammo[1] = 0
        self.state.search_since = 1.
        self.state.exhausted.add(self.first.id)
        self.verdicts[(self.second.id, 0, 0)] = 'ready'
        self.state.update(self.control, [self.second], 2.)
        target, unused, ready = self.state.update(self.control, [self.second], 2.1)
        self.assertIs(self.second, target)
        self.assertTrue(ready)
        self.assertFalse(self.state.seek)
        self.assertEqual(1., self.state.search_since)
        self.assertEqual({self.first.id}, self.state.exhausted)
        self.state.shot_admitted(self.first.id)
        self.assertEqual(1., self.state.search_since)
        self.state.shot_admitted(self.second.id)
        self.assertIsNone(self.state.search_since)
        self.assertFalse(self.state.exhausted)

    def test_front_blocked_target_stays_deferred_through_own_pivot(self):
        aiming = Aiming(self.control.owner)
        aiming.targets = {target.id: target for target in (self.first, self.second)}
        poses = {
            self.first.id: ((0., 0., 0.), 0., (0., 0., 20.), 0., 0., 0., 0.),
            self.second.id: ((0., 0., 0.), 0., (0., 0., 10.), 0., 0., 0., 0.),
        }
        aiming.direct_pose = lambda target: poses[target.id]
        aiming.defer_front_point(self.first, self.second, dict(sample=0))
        self.assertTrue(aiming._front_point_blocked(self.first, 0))
        for identity, pose in list(poses.items()):
            poses[identity] = (pose[0], .5) + pose[2:]
        self.assertFalse(aiming._front_point_blocked(self.first, 0))
        self.assertEqual({self.first.id}, aiming.front_blocked_targets())
        poses[self.second.id] = ((0., 0., 0.), .5, (1., 0., 10.), 0., 0., 0., 0.)
        self.assertFalse(aiming.front_blocked_targets())

    def test_obstruction_does_not_start_the_armor_search_clock(self):
        self.control.aiming.compare_direct = mock.Mock(return_value=('unavailable', None))
        for tick in range(3):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertIsNone(self.state.search_since)
        self.assertEqual([], self.calls)


    def test_no_he_retreats_only_after_search_expires(self):
        self.gun.ammo[2] = 0
        for now in (0., .1, 7., 7.1, 8., 8.2):
            self.state.update(self.control, [self.first], now)
        self.assertTrue(self.state.retreat)
        self.assertEqual([], self.calls)

    def test_partial_cassette_uses_next_shell_only_after_timeout(self):
        self.gun.clip_size, self.gun.clip = 3, 2
        self.verdicts[(21, 2, 0)] = 'ready'
        self.state.update(self.control, [self.first], 0.)
        self.state.observe_search(0., (0., 0., 0.), 0., True)
        self.control.reload_automatic_clip.assert_not_called()
        # The timer now belongs to real admitted search attempts. Wall-clock
        # scanning alone must not discard a live clip, and only the final
        # withdrawal consumer may apply the requested native reload.
        for second in range(1, 9):
            self.state.update(self.control, [self.first], float(second))
            self.state.observe_search(float(second), (0., 0., 0.), 0., True)
            self.assertIsNone(self.state.reload_requested)
            self.assertEqual((0, 2, 0.), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
        for now in (8.1, 8.2, 8.3):
            self.state.update(self.control, [self.first], now)
        self.control.reload_automatic_clip.assert_not_called()
        self.assertTrue(self.state.retreat)
        self.assertEqual(2, self.state.reload_requested)
        self.assertEqual((0, 2, 0.), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
        self.assertEqual([], self.calls)
        self.verdicts[(21, 0, 1)] = 'ready'
        target, solution, clear = self.state.update(self.control, [self.first], 8.4)
        self.assertIs(self.first, target)
        self.assertTrue(clear)
        self.assertFalse(self.state.retreat)
        self.assertIsNone(self.state.reload_requested)
        self.control.reload_automatic_clip.assert_not_called()


    def test_own_hull_rescan_cools_down_but_target_turret_can_trigger_it(self):
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample = 0
        state.last_solution = dict(created=1.)
        state.motion = self.control.aiming.direct_pose(self.first)
        state.last_full_at = 1.
        changed = ((.2, 0, 0), 0., (0, 0, 10), 0., 0., 0., 0.)
        self.control.aiming.direct_pose = lambda target: changed
        self.verdicts[(21, 0, 0)] = 'ready'
        scan = mock.Mock(return_value=('pending', None))
        state._scan = scan
        state.update(self.control, [self.first], 1.4)
        scan.assert_not_called()
        changed = changed[:4] + (.1, 0., 0.)
        state.update(self.control, [self.first], 1.5)
        self.assertEqual('full', scan.call_args.args[-1])

    def test_locked_barrel_gets_first_candidate_and_alternates_resume_each_tick(self):
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample, state.last_solution = 0, dict(created=0.)
        state.motion = self.control.aiming.direct_pose(self.first)
        trace = []
        remaining = [0]
        def compare(target, index, point, now, lane, threshold, **options):
            trace.append((index, options.get('physical', False)))
            self.assertGreater(remaining[0], 0)
            remaining[0] -= 1
            if index == 2 and now == 0.:
                return 'pending', None
            return 'ready', dict(created=now)
        self.control.aiming.compare_direct = compare
        for tick, expected in enumerate((2, 1, 2, 1)):
            trace[:] = []
            remaining[0] = 2
            target, solution, clear = state.update(self.control, [self.first], tick*.1)
            self.assertEqual([(0, True), (expected, False)], trace)
            self.assertIs(target, self.first)
            self.assertTrue(clear)
            self.assertEqual(0, remaining[0])
        self.assertEqual(2, state.next_shell)

    def test_slow_barrel_keeps_its_point_while_angular_error_improves(self):
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample = 0
        self.control.aiming.compare_direct = mock.Mock(side_effect=[
            ('laying', dict(laying=True, barrel_error=error)) for error in (1.0, .8, .6)])
        for now in (1., 5., 9.):
            target, solution, ready = state.update(self.control, [self.first], now)
            self.assertIs(target, self.first)
            self.assertTrue(solution['laying'])
            self.assertFalse(ready)
        self.assertEqual(0, state.sample)


class OrderedPointTests(unittest.TestCase):
    def test_retain_first_eligible_point_and_restart_at_first_after_loss(self):
        aim = Aiming(SimpleNamespace(_gun_state=SimpleNamespace(shot_index=0)))
        target = SimpleNamespace(id=1, typeDescriptor=object())
        aim.targets[1] = target
        aim.observations[1] = {}
        aim._own = lambda index: {'key': (index,)}
        aim._valid = lambda *args: True
        checked = []
        green = {1, 2}

        def candidate(target, own, entry, key, now, direct, threshold):
            checked.append(key[0])
            return dict(key=key, reachable=True, source_verified=True,
                        penetration_ok=key[0] in green)

        def advance(job, lane, limit, now):
            job.update(done=True, clear=True, completed=now)

        aim._candidate = candidate
        aim._advance = advance
        aim._candidates = 2
        with mock.patch('gui.mods.offline_lan_0922.shot_geometry.ordered_vehicle_aim_samples',
                        return_value=(object(), object(), object())):
            for now, expected in enumerate(('pending', 'ready', 'ready', 'lost', 'ready')):
                if expected == 'lost':
                    green.remove(1)
                    green.add(0)
                status, result = aim.ordered(target, 0, PENETRATION_FACTOR_65,
                                             float(now), lambda *args: True)
                self.assertEqual(expected, status)
        self.assertEqual([0, 1, 1, 1, 0], checked)

    def test_physical_scan_moves_barrel_before_accepting_and_skips_bad_contact(self):
        owner = SimpleNamespace(_gun_state=SimpleNamespace(shot_index=0),
                                _mutable_shot_ray=lambda: ((0, 0, 0), (0, 0, 1)))
        aim = Aiming(owner)
        target = SimpleNamespace(id=1, typeDescriptor=object())
        aim.targets[1], aim.observations[1] = target, {}
        aim._own = lambda index: {'key': (index,)}
        aim._valid = lambda *args: True
        aim._candidate = lambda target, own, entry, key, *args: dict(
            key=key, reachable=True, source_verified=True, penetration_ok=True)
        aim._advance = lambda job, lane, limit, now: job.update(
            done=True, clear=True, completed=now)
        aim.actual_contact = mock.Mock(side_effect=('laying', 'armor', 'ready'))
        aim._candidates = 2
        with mock.patch('gui.mods.offline_lan_0922.shot_geometry.ordered_vehicle_aim_samples',
                        return_value=(object(), object())):
            result = aim.ordered(target, 0, PENETRATION_FACTOR_65, 0., None, physical=True)
            self.assertEqual('laying', result[0])
            self.assertTrue(result[1]['laying'])
            self.assertEqual('pending', aim.ordered(
                target, 0, PENETRATION_FACTOR_65, .1, None, physical=True)[0])
            result = aim.ordered(target, 0, PENETRATION_FACTOR_65, .2, None, physical=True)
            self.assertEqual(('ready', (1, 'low')), (result[0], result[1]['key']))


    def test_final_blockage_defers_only_the_locked_physical_point(self):
        owner = SimpleNamespace(_gun_state=SimpleNamespace(shot_index=0),
                                _mutable_shot_ray=lambda: ((0, 0, 0), (0, 0, 1)))
        aim = Aiming(owner)
        target = SimpleNamespace(id=1, typeDescriptor=object())
        aim.targets[1], aim.observations[1] = target, {}
        aim._own = lambda index: {'key': (index,)}
        aim._candidate = lambda target, own, entry, key, *args: dict(
            key=key, reachable=True, source_verified=True, penetration_ok=True)
        aim._advance = lambda job, lane, limit, now: job.update(
            done=True, clear=True, completed=now)
        aim.actual_contact = mock.Mock(return_value='ready')
        aim._candidates = 2
        threshold = PENETRATION_FACTOR_65
        with mock.patch('gui.mods.offline_lan_0922.shot_geometry.ordered_vehicle_aim_samples',
                        return_value=(object(), object())):
            verdict, solution = aim.ordered(target, 0, threshold, 1., None, physical=True)
            self.assertEqual(('ready', (0, 'low')), (verdict, solution['key']))
            aim.defer_ordered_point(target, 0, solution, 1.)
            verdict, solution = aim.ordered(target, 0, threshold, 1.1, None, physical=True)
            self.assertEqual(('ready', (1, 'low')), (verdict, solution['key']))
            verdict, solution = aim.ordered(target, 0, threshold, 1.1, None)
            self.assertEqual(('ready', (0, 'low')), (verdict, solution['key']))


    def test_ammo_retreat_only_reverses_and_stops_on_stall(self):
        from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
        nav = PlayerNavigation.__new__(PlayerNavigation)
        nav._height = lambda *a, **k: 0.
        state = dict(now=10., position=(0., 0., 0.), yaw=0., stopping_distance=0.)
        order = nav.ammo_withdrawal(state, lambda *a: True, [], lambda *a: False)
        self.assertTrue(order['reverse_only'])
        self.assertLess(order['throttle'], 0.)
        self.assertEqual(0., order['turn'])
        state['now'] = 18.
        order = nav.ammo_withdrawal(state, lambda *a: True, [], lambda *a: False)
        self.assertEqual((0., 0., True), (order['throttle'], order['turn'], order['brake']))


class PlayerTrafficRecoveryTests(unittest.TestCase):
    def test_short_escape_revalidates_and_changes_gear_after_real_contact(self):
        from gui.mods.offline_lan_0922.player_control.traffic import PlayerTraffic, Traffic, body
        player = PlayerTraffic()
        shape = (1.6, 3.1, 0., 3.)
        origin = (0., 0., 0.)
        state = dict(engine_id=1, position=origin, yaw=0., now=1.,
                     speed=0., half_length=shape[1], half_width=shape[0])
        traffic = Traffic(body(1, origin, 0., shape), [])
        clear = lambda heading, reach=None: reach <= 1.
        def apply(stalled=False, failure=None):
            order = dict(throttle=0., turn=0., brake=True, recovery_mode='blocked')
            player.apply(order, state, traffic, 1, clear, lambda: 0., 1. / 30.,
                         stalled, failure)
            return order

        self.assertEqual('short_reverse_escape', apply(stalled=True)['recovery_mode'])
        state['now'] += .1
        self.assertEqual('short_reverse_escape', apply()['recovery_mode'])
        state['now'] += .1
        self.assertEqual('short_forward_escape', apply(True, (origin, math.pi))['recovery_mode'])

    def test_stationary_escape_does_not_renew_the_expired_gear(self):
        from gui.mods.offline_lan_0922.player_control.traffic import PlayerTraffic, Traffic, body
        player = PlayerTraffic()
        shape = (1.6, 3.1, 0., 3.)
        origin = (0., 0., 0.)
        traffic = Traffic(body(1, origin, 0., shape), [])
        state = dict(position=origin, yaw=0., speed=0.)
        # An expired escape must hand back to the driver before a newly
        # proved attempt, not perpetually alternate the two gears in place.
        for now, expected in ((1., 'short_reverse_escape'), (5.1, 'blocked'),
                              (5.2, 'blocked'), (6.7, 'short_forward_escape')):
            state['now'] = now
            order = dict(throttle=0., turn=0., brake=True, recovery_mode='blocked')
            player.apply(order, state, traffic, 1, lambda *a: True,
                         lambda: 0., 1. / 30., True, None)
            self.assertEqual(expected, order['recovery_mode'])

    def test_foreground_stopping_law_has_a_python_fallback(self):
        from gui.mods.offline_lan_0922.player_control import traffic_laws
        with mock.patch.object(traffic_laws.vehicle_physics, 'native_stopping_distance',
                               return_value=None), mock.patch.object(
                traffic_laws.vehicle_physics, 'longitudinal_step', side_effect=(1., 0.)):
            self.assertAlmostEqual(1. / 30.,
                traffic_laws.traffic_stopping_distance({}, 2., 0., False))

    def test_stopping_envelope_brakes_a_straight_approach_to_an_ally(self):
        from gui.mods.offline_lan_0922.player_control.traffic import PlayerTraffic, Traffic, body
        shape = (1.6, 3.1, 0., 3.)
        origin = (0., 0., 0.)
        ally = dict(id=2, position=(0., 0., 8.), yaw=0., collision_shape=shape,
                    team=1, alive=True)
        traffic = Traffic(body(1, origin, 0., shape), [ally])
        state = dict(position=origin, yaw=0., speed=4., now=1.)
        order = dict(throttle=1., turn=0., brake=False, recovery_mode='travel')
        PlayerTraffic().apply(order, state, traffic, 1, lambda *a: True,
                              lambda: 4., 1. / 30., False, None)
        self.assertEqual(2, order['forward_blocked_by'])
        self.assertTrue(order['brake'])
        self.assertEqual(0., order['throttle'])
