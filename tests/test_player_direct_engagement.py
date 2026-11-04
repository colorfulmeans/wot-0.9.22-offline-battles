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
        self.state = DirectEngagement(dict(type=dict(name='uk:GB80_Charioteer'),
                                           gun=dict(name='_105mm_AT_Gun_L7')))
        self.gun = SimpleNamespace(ammo=[8, 8], shot_index=0, reload_time=0.)
        self.rounds = SimpleNamespace(main=0, shells=[
            dict(index=0, kind='HIGH_EXPLOSIVE', name='_105mm_HESH_L7', premium=True),
            dict(index=1, kind='ARMOR_PIERCING_CR', name='_105mm_APCR_L7', premium=False)])
        self.calls = []
        self.verdicts = {}
        self.control = SimpleNamespace(owner=SimpleNamespace(_gun_state=self.gun),
            ammo_policy=self.rounds, aiming=SimpleNamespace(ordered=self.scan),
            queue_automatic_shell=self.calls.append, lane_from=lambda *args: True,
            record=lambda *args, **kwargs: None)
        self.first = SimpleNamespace(id=21)
        self.second = SimpleNamespace(id=22)
        self.hesh = (0, PENETRATION_FACTOR_65)
        self.apcr = (1, PENETRATION_FACTOR_65)
        self.fallback = (0, None)

    def scan(self, target, index, threshold, now, lane, physical=False):
        status = self.verdicts.get((target.id, (index, threshold)), 'pending')
        return status, dict(created=now, key=(0, 'low'), geometry_clear=True) if status == 'ready' else None

    def test_hesh_apcr_and_same_shell_fallback(self):
        self.assertEqual([self.hesh, self.apcr, self.fallback],
                         self.state.stages(self.rounds, self.gun.ammo))
        self.verdicts[(21, self.hesh)] = 'armor'
        self.assertFalse(self.state.update(self.control, [self.first], 0.)[2])
        self.assertEqual(self.apcr, self.state.stage)
        self.verdicts[(21, self.apcr)] = 'armor'
        self.assertFalse(self.state.update(self.control, [self.first], .1)[2])
        self.assertEqual(self.apcr, self.state.stage)
        self.gun.shot_index = 1
        self.assertFalse(self.state.update(self.control, [self.first], .2)[2])
        self.assertEqual(self.fallback, self.state.stage)
        self.gun.shot_index = 0
        self.verdicts[(21, self.fallback)] = 'ready'
        self.assertTrue(self.state.update(self.control, [self.first], .3)[2])

    def test_he_fallback_yields_but_penetration_lock_does_not(self):
        self.state.adopt(21, self.fallback)
        self.verdicts[(21, self.fallback)] = 'ready'
        self.verdicts[(22, self.hesh)] = 'ready'
        self.state.update(self.control, [self.first, self.second], 0.)
        self.assertFalse(self.state.update(self.control, [self.first, self.second], .1)[2])
        self.assertEqual((22, self.hesh), (self.state.target, self.state.stage))
        self.verdicts[(21, self.hesh)] = 'ready'
        self.assertEqual(self.second,
                         self.state.update(self.control, [self.first, self.second], .2)[0])

    def test_obstruction_does_not_trigger_shell_change(self):
        self.verdicts[(21, self.hesh)] = 'unavailable'
        self.state.update(self.control, [self.first], 0.)
        self.assertEqual([], self.calls)
        self.assertEqual(self.hesh, self.state.stage)

    def test_ordinary_he_main_has_no_penetration_gate(self):
        self.state.vehicle = 'uk:GB70_FV4202_105'
        self.assertEqual([self.fallback, self.apcr],
                         self.state.stages(self.rounds, self.gun.ammo))


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
