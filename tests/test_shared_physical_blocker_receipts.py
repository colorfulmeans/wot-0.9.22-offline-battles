"""Known wreck/debris collisions remain distinct from unavailable geometry.

These are real component/path observations and first-trigger consumers. They
do not turn a closed lane, a timer, or an exception into a movement permit.
"""
import contextlib
import io
from types import SimpleNamespace
import unittest

from test_player_fire_admission_complete import AutomaticFireScene
from test_port_0922_turret_obstacles import descriptor, row
from gui.mods.offline_lan_0922.entities.turret_obstacles import DetachedTurretObstacles


class KnownPhysicalBlockerReceiptTests(AutomaticFireScene):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        super(KnownPhysicalBlockerReceiptTests, self).setUp()

    def test_actual_wreck_component_contact_is_known_for_both_teams(self):
        wreck = self.vehicle(8043, (0., 0., 50.), 2)
        record = self.battle._records.pop('bot:8043')
        record.update(network_id=7, native_remote=True)
        record['state'].update(id=7, alive=False, health=0)
        self.battle._records['bot:7'] = record
        wreck.health = 0
        for team in (1, 2):
            with self.subTest(team=team):
                record['team'] = record['state']['team'] = team
                self.step()
                verdict = self.friendly_verdict()
                self.assertFalse(verdict['clear'])
                self.assertTrue(verdict.get('blocked'))
                self.assertEqual('wreck', verdict['blocker_kind'])
                self.assertEqual(('bot', 7), verdict['actor_key'])
                self.assertEqual(8043, verdict['vehicle_id'])
                self.assertEqual(team, verdict['blocker_team'])
                reason, blocker = self.admission._lane(self.candidate['solution']['path'])
                self.assertEqual('auto_world_blocked', reason)
                self.assertEqual('wreck', blocker['blocker_kind'])
                self.assertFalse(self.fire())
                self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
                self.assert_unspent()

    def test_real_landed_turret_is_known_but_future_landing_is_not_a_blocker(self):
        obstacles = DetachedTurretObstacles(self.battle._runtime.math)
        self.assertTrue(obstacles.add('bot:17', row(rest=(0., 1.5, 50.)), descriptor()))
        self.battle._detached_turret_obstacles = obstacles
        self.battle._projectile_server_local_time = self.now
        self.battle._projectile_server_time_ms = 2000
        self.assertTrue(self.friendly_verdict()['clear'])
        self.battle._projectile_server_time_ms = 4000
        verdict = self.friendly_verdict()
        self.assertFalse(verdict['clear'])
        self.assertTrue(verdict.get('blocked'))
        self.assertEqual('debris', verdict['blocker_kind'])
        self.assertFalse(self.fire())
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assert_unspent()

    def test_unknown_native_obstacle_query_is_not_a_known_physical_blocker(self):
        def unavailable(*unused):
            raise RuntimeError('native obstacle query unavailable')
        self.battle._detached_turret_obstacles = SimpleNamespace(block_distance=unavailable)
        verdict = self.friendly_verdict()
        self.assertEqual({'clear': False}, verdict)
        reason, blocker = self.admission._lane(self.candidate['solution']['path'])
        self.assertEqual('auto_lane_geometry_unknown', reason)
        self.assertFalse(blocker.get('blocked'))
        self.assertFalse(self.fire())
        self.assertEqual('auto_lane_geometry_unknown', self.control.last_fire_failure)
        self.assert_unspent()


if __name__ == '__main__':
    unittest.main()
