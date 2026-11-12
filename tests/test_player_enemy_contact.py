"""Ordinary physical translation never creates a new engagement owner.

The native-world boundary supplies flat support and observed peer bodies.
The production SAT sweep/response and original planar-contact feedback must
remain unchanged by player automation. These are not native Windows tests.
"""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as battle_fixtures
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

    def test_player_activation_preserves_original_sat_fraction_and_response(self):
        results = []
        sweeps = []
        original = tank_collision.translation_fraction
        for active in (False, True):
            battle, entity, events = self.physical_scene(active=active)
            fractions = []

            def observe_sweep(*args, **kwargs):
                # Ordinary navigation retains the original three-argument
                # sweep, not the newer enemy-translation observation path.
                self.assertEqual(3, len(args))
                self.assertEqual({}, kwargs)
                fraction = original(*args, **kwargs)
                fractions.append(fraction)
                return fraction

            with mock.patch.object(tank_collision, 'translation_fraction',
                                   side_effect=observe_sweep) as sweep:
                position = self.move(battle, entity)
                self.assertGreater(sweep.call_count, 0)
                self.assertEqual((0., 10.), sweep.call_args_list[0].args[1])
                sweeps.append(tuple(fractions))
            results.append((position, battle._local_speed,
                            battle._local_push_x, battle._local_push_z))
            self.assertGreaterEqual(fractions[0], 0.)
            self.assertLess(fractions[0], 1.)
            self.assertLess(position[2], 10.)
            self.assertFalse(any(row.get('enemy_blocking') for row in events))
            self.assertFalse(any(row.get('source') == 'foreground_enemy_translation'
                                 for row in events))
        self.assertEqual(results[0], results[1])
        self.assertEqual(sweeps[0], sweeps[1])

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

    def test_ordinary_navigation_collision_cannot_emit_combat_entry(self):
        battle, entity, unused = self.physical_scene()
        control = battle._player_control
        control.last_order = dict(action='move', target=None, reason='route',
                                  destination=(0., 0., 200.))
        before = dict(control.last_order)
        control.drive_contact = mock.Mock()
        position = self.move(battle, entity)
        # The swept enemy still physically blocks the route. It does not
        # supply an independent "enemy_blocking" engagement-admission event.
        self.assertLess(position[2], 10.)
        control.drive_contact.assert_not_called()
        self.assertEqual(before, control.last_order)

    def test_original_planar_contact_feedback_is_preserved(self):
        battle, unused, events = self.physical_scene()
        own = dict(id=-1, kind='player', network_id=1, x=0., y=0., z=0.,
                   yaw=0., pitch=0., roll=0., shape=(1., 2., 0., 2.))
        for team, alive in ((1, True), (2, True), (2, False)):
            with self.subTest(team=team, alive=alive):
                events[:] = []
                peer = dict(_tank(1000011, 1.5, 1., shape=(1., 2., 0., 2.)),
                    network_id=11, kind='bot', team=team, alive=alive,
                    _record=dict(engine_id=11))
                battle._report_player_planar_contacts(own, [peer], 0., .1, 10.)
                self.assertEqual(1, len(events))
                self.assertEqual('copied_planar_contact', events[0]['source'])
                self.assertEqual((-1., -0.), events[0]['normal'])
                self.assertEqual(11, events[0]['peer'])
                self.assertNotIn('enemy_blocking', events[0])
                peer['x'] = 10.
                battle._report_player_planar_contacts(own, [peer], 0., .1, 10.1)
                self.assertEqual(1, len(events))


if __name__ == '__main__':
    unittest.main()
