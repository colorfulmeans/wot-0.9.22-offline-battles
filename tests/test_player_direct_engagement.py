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
            ammo_policy=self.rounds, aiming=SimpleNamespace(compare_direct=self.probe,
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

    def test_fixed_point_order_does_not_wait_for_later_geometry(self):
        self.verdicts[(21, 1, 0)] = 'ready'
        self.verdicts[(21, 2, 1)] = 'ready'
        for tick in range(2):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertEqual([1], self.calls)
        self.assertEqual(0, self.state.sample)

    def test_he_main_prefers_lowest_piercing_alternative_and_skips_empty(self):
        self.rounds.main = 2
        self.gun.shots[0]['piercingPower'] = (300., 250.)
        self.assertEqual([2, 1, 0], [row['index'] for row in self.state.shells(self.rounds, self.gun)])
        self.gun.ammo[1] = 0
        self.assertEqual([2, 0], [row['index'] for row in self.state.shells(self.rounds, self.gun)])

    def test_two_deadlines_do_not_renew_on_target_or_destination_change(self):
        state = self.state
        state.adopt(21)
        self.assertEqual('turret', state.movement_stage(0., True, True))
        state.adopt(22)
        self.assertEqual('turret', state.movement_stage(7.9, True, True))
        self.assertEqual('position', state.movement_stage(8., True, True))
        self.assertEqual('turret_timeout', state.receipt['reason'])
        state.adopt(21)
        self.assertEqual('position', state.movement_stage(13.9, False, True))
        self.assertEqual('retreat', state.movement_stage(14., False, True))
        self.assertEqual('position_timeout', state.receipt['reason'])
        self.assertEqual('turret', state.movement_stage(15., False, True, ready=True))
        self.assertEqual('ray_ready', state.receipt['reason'])

    def test_capture_never_spends_or_enters_movement_phase(self):
        self.state.adopt(21)
        for now in (0., 9., 16., 40.):
            self.assertEqual('turret', self.state.movement_stage(now, True, False))
            self.assertFalse(self.state.seek or self.state.retreat)

    def test_pending_candidate_does_not_starve_the_next_point(self):
        self.gun.ammo[1:] = [0, 0]
        self.verdicts[(21, 0, 0)] = 'pending'
        self.verdicts[(21, 0, 1)] = 'ready'
        target, unused, ready = self.state.update(self.control, [self.first], 0.)
        self.assertIs(target, self.first)
        self.assertTrue(ready)
        self.assertEqual(1, self.state.sample)

    def test_actual_armor_failure_advances_barrel_before_any_movement(self):
        self.gun.ammo[1:] = [0, 0]
        physical = []
        def probe(target, index, sample, now, *args, **kwargs):
            solution = dict(created=now, point=(0., 0., 10.), barrel_error=.1)
            if kwargs.get('physical'):
                physical.append(sample)
                return ('armor' if sample == 0 else 'laying'), solution
            return 'ready', solution
        self.control.aiming.compare_direct = probe
        self.state.update(self.control, [self.first], 0.)
        self.state.movement_stage(0., True, True)
        target, solution, ready = self.state.update(self.control, [self.first], .1)
        self.assertEqual([0, 1], physical)
        self.assertIs(target, self.first)
        self.assertFalse(ready)
        self.assertEqual('turret', self.state.phase)
        self.assertFalse(self.state.seek or self.state.retreat)

    def test_target_motion_does_not_restart_failed_physical_point_order(self):
        self.gun.ammo[1:] = [0, 0]
        physical = []
        def probe(target, index, sample, now, *args, **kwargs):
            if kwargs.get('physical'):
                physical.append(sample)
                return 'armor', dict(created=now)
            return 'ready', dict(created=now)
        self.control.aiming.compare_direct = probe
        self.state.update(self.control, [self.first], 0.)
        self.control.aiming.direct_pose = lambda target: (
            (0, 0, 0), 0., (0, 0, 10), .2, .3, 0., 0.)
        self.state.update(self.control, [self.first], .1)
        self.assertEqual([0, 1], physical)

    def test_penetrating_he_is_not_fallback_and_restores_turret_stage(self):
        self.gun.shot_index = 2
        self.verdicts[(21, 2, 0)] = 'ready'
        self.state.adopt(21)
        self.state.phase, self.state.phase_since = 'retreat', 14.
        self.state.retreat = self.state.search_expired = True
        target, solution, ready = self.state.update(self.control, [self.first], 15.)
        self.assertTrue(ready)
        self.assertFalse(self.state.fallback)
        self.assertEqual('turret', self.state.movement_stage(15., False, True, ready))
        self.assertFalse(self.state.retreat)

    def test_pending_physical_point_yields_and_is_revisited_later(self):
        self.gun.ammo[1:] = [0, 0]
        checked = []
        def probe(target, index, sample, now, *args, **kwargs):
            checked.append((sample, kwargs.get('physical', False)))
            return ('pending' if kwargs.get('physical') and sample == 0 else 'ready'), dict(created=now)
        self.control.aiming.compare_direct = probe
        for now in (0., .6, .7):
            self.state.update(self.control, [self.first], now)
        self.assertIn((1, True), checked)
        self.assertEqual(1, self.state.sample)

    def test_he_fallback_cannot_start_before_both_timeouts(self):
        self.state.adopt(21)
        self.state.movement_stage(0., True, True)
        for tick in range(3):
            self.state.update(self.control, [self.first], tick*.1)
        self.assertFalse(self.state.fallback)
        self.state.movement_stage(8., True, True)
        self.state.update(self.control, [self.first], 8.)
        self.assertFalse(self.state.fallback)
        self.state.movement_stage(14., True, True)
        for tick in range(10):
            self.state.update(self.control, [self.first], 14.+tick*.1)
            if self.state.fallback:
                break
        self.assertTrue(self.state.retreat)
        self.assertTrue(self.state.fallback)
        self.assertEqual(1, self.state.sample)
        self.assertIn(2, self.calls)

    def test_partial_cassette_compares_next_shell_after_both_timeouts(self):
        self.gun.clip_size, self.gun.clip = 3, 2
        self.verdicts[(21, 2, 0)] = 'ready'
        self.state.update(self.control, [self.first], 0.)
        self.state.movement_stage(0., True, True)
        self.state.movement_stage(8., True, True)
        self.control.reload_automatic_clip.assert_not_called()
        self.state.movement_stage(14., True, True)
        for tick in range(8):
            self.state.update(self.control, [self.first], 14.+tick*.1)
        self.control.reload_automatic_clip.assert_called_with(2)
        self.assertEqual([], self.calls)

    def test_own_hull_rescan_cools_down_but_target_turret_can_trigger_it(self):
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample = 0
        state.last_solution = dict(created=1.)
        state.motion = self.control.aiming.direct_pose(self.first)
        state.last_full_at = 1.
        changed = ((.2, 0, 0), 0., (0, 0, 10), 0., 0., 0., 0.)
        self.control.aiming.direct_pose = lambda target: changed
        scan = mock.Mock(return_value=('pending', None))
        state._scan = scan
        state.update(self.control, [self.first], 1.4)
        self.assertEqual('barrel', scan.call_args.args[-2])
        changed = changed[:4] + (.1, 0., 0.)
        state.update(self.control, [self.first], 1.5)
        self.assertEqual('full', scan.call_args.args[-2])

    def test_managed_pivot_rechecks_barrel_without_forcing_full_rescan(self):
        self.gun.ammo[1:] = [0, 0]
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample, state.last_solution = 0, dict(created=1.)
        state.motion = self.control.aiming.direct_pose(self.first)
        state.last_full_at = 1.
        self.verdicts[(21, 0, 0)] = 'ready'
        self.control.last_order = dict(combat_facing=dict(target=21, state='turning'))
        pose = ((0, 0, 0), .3, (0, 0, 10), 0., 0., 0., 0.)
        self.control.aiming.direct_pose = lambda target: pose
        with mock.patch.object(state, '_scan', wraps=state._scan) as scan:
            target, _, clear = state.update(self.control, [self.first], 1.9)
            self.assertEqual('barrel', scan.call_args.args[-2])
            self.assertIs(target, self.first)
            self.assertTrue(clear)
            self.control.last_order = {}
            state.update(self.control, [self.first], 2.)
            self.assertEqual('barrel', scan.call_args.args[-2])
            pose = pose[:4] + (.2, 0., 0.)
            state.update(self.control, [self.first], 2.1)
            self.assertEqual('full', scan.call_args.args[-2])

    def test_slow_barrel_keeps_its_point_while_angular_error_improves(self):
        state = self.state
        state.adopt(self.first.id, (0, PENETRATION_FACTOR_65))
        state.sample = 0
        self.control.aiming.compare_direct = mock.Mock(side_effect=[
            ('laying', dict(laying=True, barrel_error=error)) for error in (1.0, .8, .6)])
        for now in (1., 3., 5.):
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


    def test_direct_preparation_is_not_an_actual_barrel_proof(self):
        owner = SimpleNamespace(_mutable_shot_ray=lambda: ((0, 0, 0), (0, 0, 1)))
        aim = Aiming(owner)
        target = SimpleNamespace(id=1, typeDescriptor=object())
        aim.targets[1], aim.observations[1] = target, {}
        aim._own = lambda index: dict(key=(index,))
        aim._valid = lambda *args: True
        aim._candidate = lambda target, own, entry, key, now, *args: dict(
            key=key, sample=key[0], created=now, direction=(0., 0., 1.),
            reachable=True, source_verified=True, penetration_ok=False)
        aim._advance = lambda job, lane, limit, now: job.update(
            done=True, clear=True, completed=now)
        aim.actual_contact = mock.Mock(return_value='armor')
        aim._candidates = 10
        with mock.patch('gui.mods.offline_lan_0922.shot_geometry.ordered_vehicle_aim_samples',
                        return_value=(object(), object())):
            verdict, solution = aim.compare_direct(target, 0, 0, 0., None,
                PENETRATION_FACTOR_65, prepare=True)
            self.assertEqual('ready', verdict)
            aim.actual_contact.assert_not_called()
            for expected in ('laying', 'unknown', 'miss', 'armor', 'ready'):
                aim.actual_contact.return_value = expected
                verdict, unused = aim.compare_direct(target, 0, 0, .1, None,
                    PENETRATION_FACTOR_65, physical=True)
                self.assertEqual(expected, verdict)
                self.assertEqual((0, 0, 1), aim.actual_contact.call_args.args[3])

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
        for now, expected in ((1., 'short_reverse_escape'), (5.1, 'short_forward_escape')):
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
