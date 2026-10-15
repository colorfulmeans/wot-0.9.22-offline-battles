import unittest
from unittest import mock
from test_port_0922_battle_projectiles import _worker_battle, _bot_event


class ProjectileEpochTests(unittest.TestCase):
    def test_reflection_and_restore_keep_the_original_local_epoch(self):
        battle, unused = _worker_battle(1.)
        event = _bot_event()
        normalized = battle._projectile_wire_meta(event)
        battle._projectile_meta[normalized['projectile_id']] = {}
        with mock.patch.object(battle, '_projectile_local_launch_time',
                side_effect=(1., .974)) as mapping:
            first = battle._projectile_manager_snapshot(normalized, 1.1)
            reflected = dict(normalized, segment_start_time_ms=55,
                             base_checked_ms=55, ricochet_count=1)
            second = battle._projectile_manager_snapshot(reflected, 1.2)
            restored = battle._projectile_manager_snapshot(reflected, 1.3)
        self.assertAlmostEqual(.055, second['launch_time'] - first['launch_time'])
        self.assertEqual(second['launch_time'], restored['launch_time'])
        mapping.assert_called_once()

    def test_distinct_projectiles_do_not_share_an_epoch(self):
        battle, unused = _worker_battle(1.)
        normalized = battle._projectile_wire_meta(_bot_event())
        other = dict(normalized, projectile_id='bot:7:2')
        battle._projectile_meta = {normalized['projectile_id']: {}, other['projectile_id']: {}}
        with mock.patch.object(battle, '_projectile_local_launch_time', side_effect=(1., 2.)):
            first = battle._projectile_manager_snapshot(normalized, 3.)
            second = battle._projectile_manager_snapshot(other, 3.)
        self.assertNotEqual(first['launch_time'], second['launch_time'])

    def test_future_canonical_segment_is_retained_without_early_physics(self):
        battle, unused = _worker_battle(1.)
        normalized = battle._projectile_wire_meta(_bot_event())
        normalized.update(segment_start_time_ms=50, base_checked_ms=50, ricochet_count=1)
        battle._projectile_meta[normalized['projectile_id']] = {'physics_launch_time': 1.}
        self.assertTrue(battle._admit_projectile_manager_state(normalized, 1.))
        chord = mock.Mock(return_value=None)
        terminal = mock.Mock()
        battle._projectiles.advance(1.02, chord, terminal)
        chord.assert_not_called()
        terminal.assert_not_called()
        battle._projectiles.advance(1.06, chord, terminal)
        self.assertTrue(chord.called)
