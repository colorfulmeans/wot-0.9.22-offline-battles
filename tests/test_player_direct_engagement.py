"""Foreground-only regression coverage for ordered engagement and HE fallback."""
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


class SweptCommandTests(unittest.TestCase):
    def test_plain_pivot_checks_world_and_uses_track_offset(self):
        from gui.mods.offline_lan_0922.player_control.traffic import Traffic, body
        traffic = Traffic(body(1, (9.85, .31, 99.39), 3.019, (1.62, 3.1, 0., 3.)), [])
        world = mock.Mock(return_value=False)
        self.assertFalse(traffic.swept_command_clear(
            0., .8, 0., lambda turn, throttle: 1.2, world))
        world.assert_called_once()
        position, yaw, end_yaw, pivot, travel = world.call_args.args
        self.assertEqual((1.2, (0., 0.)), (pivot, travel))
        self.assertGreater(end_yaw, yaw)
