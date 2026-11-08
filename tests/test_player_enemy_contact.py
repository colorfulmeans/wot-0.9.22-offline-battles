"""Existing physical translation witnesses enter engagement, not avoidance.

The native-world boundary supplies flat support and observed peer bodies.
The SAT sweep/response, foreground event adapter and engagement decisions
remain production consumers; these tests are not native Windows acceptance.
"""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as battle_fixtures
import test_player_limited_traverse as player_fixtures
from test_port_0922_tank_collision import tank_collision, _tank


class EnemyTranslationTests(unittest.TestCase):
    def physical_scene(self, alive=True, team=2, active=True, forward=1., peers=None):
        native = battle_fixtures._runtime()
        battle = battle_fixtures.BattleRuntime(native)
        battle.client = battle_fixtures._Client()
        battle.client.team = 1
        battle._avatar = native.bigworld.avatar
        battle._local_physics = dict(
            battle_fixtures._effective_params_snapshot()['physics'], mass=100575.)
        entity = battle_fixtures._Vehicle(10, battle_fixtures._Descriptor(),
            battle_fixtures._Vector(), (0, 0, 0), {'health': 500})
        peer = _tank(1000011, 0., 8., mass=31370.)
        peer.update(network_id=11, engine_id=11, kind='bot', alive=alive, team=team)
        roster = [peer] if peers is None else peers
        battle._collision_shape = lambda unused: tank_collision.DEFAULT_SHAPE
        battle._contact_tanks = lambda *args, **kwargs: roster
        battle._motion_is_clear = lambda *args, **kwargs: True
        battle._baked_pose_safe = lambda *args: True
        battle._poll_local_ram_contact_episodes = lambda *args: None
        events = []
        battle._sender = types.SimpleNamespace(forward=forward)
        battle._player_control = types.SimpleNamespace(active=active, features=('drive', 'fire'),
            drive_contact=lambda *args, **kwargs: events.append(kwargs.get('contact') or args[-1]))
        return battle, entity, events

    def move(self, battle, entity, distance=10.):
        battle._local_speed = 10.
        battle._local_contact_start_position = (0., 0., 0.)
        with mock.patch('sys.stdout'):
            return battle._resolve_local_tank_contacts(entity, (0., 0., distance), 0., .1)

    def test_live_enemy_receipt_does_not_change_physical_fraction_or_response(self):
        results = []
        counts = []
        for active in (False, True):
            battle, entity, events = self.physical_scene(active=active)
            with mock.patch.object(tank_collision, 'translation_fraction',
                                   wraps=tank_collision.translation_fraction) as sweep:
                position = self.move(battle, entity)
                counts.append(sweep.call_count)
            results.append((position, battle._local_speed,
                            battle._local_push_x, battle._local_push_z))
            enemy = [row for row in events if row.get('enemy_blocking')]
            self.assertEqual(int(active), len(enemy))
            if active:
                self.assertEqual(('foreground_enemy_translation', 11, 'bot', 11),
                    (enemy[0]['source'], enemy[0]['peer'], enemy[0]['peer_kind'], enemy[0]['peer_id']))
                self.assertGreaterEqual(enemy[0]['fraction'], 0.)
                self.assertLess(enemy[0]['fraction'], 1.)
        self.assertEqual(results[0], results[1])
        self.assertEqual(counts[0], counts[1])

    def test_friends_wrecks_and_movement_opposite_input_are_not_enemy_entry(self):
        for alive, team, forward in ((False, 2, 1.), (True, 1, 1.),
                                      (True, 2, -1.), (True, 2, 0.)):
            with self.subTest(alive=alive, team=team, forward=forward):
                battle, entity, events = self.physical_scene(alive, team, forward=forward)
                self.move(battle, entity)
                self.assertFalse(any(row.get('enemy_blocking') for row in events))

    def test_enemy_beyond_the_first_friendly_stop_is_not_the_obstruction(self):
        friend = dict(_tank(1000011, 0., 8.), network_id=11, engine_id=11,
                      kind='bot', team=1, alive=True)
        enemy = dict(_tank(1000012, 0., 16.), network_id=12, engine_id=12,
                     kind='bot', team=2, alive=True)
        battle, entity, events = self.physical_scene(peers=[friend, enemy])
        self.move(battle, entity, 20.)
        self.assertFalse(any(row.get('enemy_blocking') for row in events))

    def test_physical_witness_stops_initial_check_then_yields_to_ordinary_finding(self):
        scene = player_fixtures.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(limits=None, tag='mediumTank', bearing=0.)
        target = scene.runtime.visible_targets()[0]
        battle, entity, unused = self.physical_scene()
        peer = dict(_tank(1000000 + scene.target.id, 0., 8.),
            network_id=target['network_id'], engine_id=scene.target.id,
            kind='bot', team=2, alive=True)
        battle._contact_tanks = lambda *args, **kwargs: [peer]
        battle._player_control = scene.control

        def pending_geometry():
            raise RuntimeError('world observation pending')

        scene.on_probe = pending_geometry
        self.move(battle, entity)
        self.assertIsNotNone(scene.runtime.firing_position.contact_witness)
        first = scene.tick()
        self.assertIsNone(first['failure'])
        self.assertEqual('contact_verify', scene.runtime.firing_position.episode['phase'])
        self.assertEqual((0., 0.), first['sender'][:2])
        moving = False
        for unused in range(70):
            row = scene.tick()
            self.assertIsNone(row['failure'], row)
            self.assertIsNone(scene.runtime.attack_policy.search_started)
            moving = moving or bool(row['sender'][0] or row['sender'][1])
        self.assertTrue(moving, scene.trace[-4:])
        self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
