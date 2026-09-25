"""Landing contact observations retain server damage and repair ownership."""
import copy
import types
import unittest
from unittest import mock

import test_port_0922_lan_client_projectiles as client_fixture
import test_port_0922_server_projectiles as server_fixture

from gui.mods.offline_lan_0922 import vehicle_physics


LEFT = 'leftTrackHealth'
RIGHT = 'rightTrackHealth'


class LandingCriticalServerTests(unittest.TestCase):
    def setUp(self):
        self.state = server_fixture._state()
        self.player = self.state.players[1]
        self.player.max_health = self.player.health = 1780
        self.player.effective_params['critical'] = {
            'devices': [
                {'name': LEFT, 'max_hp': 240.0, 'regen_hp': 120.0},
                {'name': RIGHT, 'max_hp': 300.0, 'regen_hp': 150.0},
                {'name': 'engineHealth', 'max_hp': 100.0, 'regen_hp': 50.0},
            ],
            'crew_roster': ['commander', 'driver'],
        }
        self.results = []
        self.player.offer_reliable = lambda row: self.results.append(row) or True
        self.next_input()

    def next_input(self):
        self.state.tick += 1
        self.assertTrue(server_fixture._update_player_input(self.state, 1))

    def observation(self, loads=None, speed=20.0):
        result = {
            'type': 'landing_observation', 'round_id': self.state.round_id,
            'authority_epoch': self.state.authority_epoch,
            'observation_seq': self.player.landing_observation_seq + 1,
            'input_seq': self.player.input_seq, 'impact_speed': speed,
        }
        if loads is not None:
            result['track_loads'] = list(loads)
        return result

    def submit(self, message):
        return self.state.submit_landing_observation(1, message)

    def devices(self):
        return {row['name']: row for row in self.player.critical['devices']}

    def test_single_dual_and_hull_loads_keep_existing_hp_budget(self):
        budget = vehicle_physics.fall_damage(1780, 20.0)
        for shares in ((1.0, 0.0), (0.5, 0.5), (0.2, 0.3)):
            with self.subTest(shares=shares):
                self.setUp()
                self.assertTrue(self.submit(self.observation(shares)))
                self.assertEqual(1780 - budget, self.player.health)
                devices = self.devices()
                for name, maximum, share in (
                        (LEFT, 240.0, shares[0]), (RIGHT, 300.0, shares[1])):
                    if share:
                        self.assertAlmostEqual(
                            max(0.0, maximum - budget * share),
                            devices[name]['hp'], places=3)
                    else:
                        self.assertNotIn(name, devices)
                event = self.state.pending_events[-1]
                self.assertEqual(('environment', 3),
                                 (event['source'], event['attack_reason']))
                self.assertNotIn('engineHealth', devices)
                self.assertFalse(self.player.critical['crew_ko'])
                self.assertFalse(self.player.critical['fire'])
                for critical_event in event['critical']['events']:
                    self.assertIn(critical_event['name'], (LEFT, RIGHT))
                    self.assertEqual('world_collision', critical_event['cause'])

    def test_legacy_and_hull_only_observations_remain_hp_only(self):
        for shares in (None, (0.0, 0.0)):
            with self.subTest(shares=shares):
                self.setUp()
                before = copy.deepcopy(self.player.critical)
                self.assertTrue(self.submit(self.observation(shares)))
                self.assertLess(self.player.health, 1780)
                self.assertEqual(before, self.player.critical)
                self.assertEqual(0, self.player.critical_revision)
                self.assertNotIn('critical', self.state.pending_events[-1])

    def test_replay_and_load_tampering_cannot_damage_twice(self):
        message = self.observation((0.75, 0.25))
        self.assertTrue(self.submit(message))
        before = (self.player.health, copy.deepcopy(self.player.critical),
                  self.player.critical_revision, len(self.state.pending_events))
        self.assertTrue(self.submit(copy.deepcopy(message)))
        self.assertFalse(self.submit(dict(message, track_loads=[0.25, 0.75])))
        self.assertEqual('identity_conflict', self.results[-1]['reason'])
        self.assertEqual(before, (
            self.player.health, self.player.critical,
            self.player.critical_revision, len(self.state.pending_events)))

    def test_malformed_loads_and_client_damage_verdict_do_not_advance(self):
        invalid = ([True, 0], [float('nan'), 0], [float('inf'), 0],
                   [10 ** 400, 0], [-0.1, 0], [0.8, 0.8], [0.5],
                   'left', {'left': 1})
        for loads in invalid:
            with self.subTest(loads=loads):
                self.assertFalse(self.submit(dict(
                    self.observation(), track_loads=loads)))
        self.assertFalse(self.submit(dict(
            self.observation((1, 0)), critical={'devices': []})))
        self.assertFalse(self.submit(dict(self.observation(), damage=1000)))
        self.assertEqual((1780, 0, 0), (
            self.player.health, self.player.landing_observation_seq,
            self.player.critical_revision))
        self.assertFalse(self.state.pending_events)
        self.assertTrue(self.submit(self.observation((1, 0))))

    def test_stale_authority_input_and_round_preserve_the_operation(self):
        valid = self.observation((0.6, 0.2))
        self.assertFalse(self.submit(dict(
            valid, authority_epoch=self.state.authority_epoch + 1)))
        self.assertEqual('stale_authority', self.results[-1]['reason'])
        self.assertFalse(self.submit(dict(valid, input_seq=999)))
        self.assertEqual('stale_input', self.results[-1]['reason'])
        self.assertFalse(self.submit(dict(valid, round_id=self.state.round_id + 1)))
        self.assertEqual(0, self.player.landing_observation_seq)
        self.assertEqual(1780, self.player.health)
        self.assertTrue(self.submit(valid))

    def test_new_landing_resets_repair_and_rejects_old_checkpoint(self):
        self.player.critical = {
            'devices': [{'name': LEFT, 'hp': 60.0, 'max_hp': 240.0,
                         'state': 'destroyed'}],
            'destroyed': [LEFT], 'crew_ko': [], 'fire': False,
            'ammo_rack_death': False, 'events': [],
            'crew_roster': ['commander', 'driver'],
        }
        self.player.critical_revision = 4
        self.player.critical_report_base_revision = 4
        checkpoint = {
            'round_id': self.state.round_id, 'critical_base_revision': 4,
            'repair_seq': 1,
            'tracks': [{'name': LEFT, 'hp': 80.0, 'max_hp': 240.0,
                        'state': 'destroyed'}],
        }
        self.assertTrue(self.state.report_track_repair(1, checkpoint))
        self.assertEqual(80.0, self.devices()[LEFT]['hp'])
        self.assertTrue(self.submit(self.observation((0.1, 0.0))))
        self.assertEqual(0.0, self.devices()[LEFT]['hp'])
        self.assertGreater(self.player.critical_report_base_revision, 4)
        self.assertEqual(0, self.player.critical_ack_seq)
        self.assertFalse(self.player.track_repair_fingerprints)
        self.assertFalse(self.state.report_track_repair(
            1, dict(checkpoint, repair_seq=2)))
        self.assertEqual(0.0, self.devices()[LEFT]['hp'])
        previous_base = self.player.critical_report_base_revision
        self.next_input()
        self.assertTrue(self.submit(self.observation((0.1, 0.0))))
        self.assertGreater(self.player.critical_report_base_revision, previous_base)
        self.assertEqual(0.0, self.devices()[LEFT]['hp'])

    def test_landing_preserves_unrelated_critical_state_and_fire_lineage(self):
        self.player.critical = {
            'devices': [{'name': 'engineHealth', 'hp': 30.0,
                         'max_hp': 100.0, 'state': 'critical'},
                        {'name': LEFT, 'hp': 170.0,
                         'max_hp': 240.0, 'state': 'normal'}],
            'destroyed': [], 'crew_ko': ['driver'], 'fire': True,
            'ammo_rack_death': False, 'events': [],
            'crew_roster': ['commander', 'driver'],
        }
        self.player.fire_attacker_kind = 'bot'
        self.player.fire_attacker_id = 9
        self.player.combat_fire_elapsed = 2.0
        self.assertTrue(self.submit(self.observation((0.1, 0.0))))
        self.assertAlmostEqual(
            170.0 - vehicle_physics.fall_damage(1780, 20.0) * 0.1,
            self.devices()[LEFT]['hp'], places=3)
        self.assertEqual(30.0, self.devices()['engineHealth']['hp'])
        self.assertEqual(['driver'], self.player.critical['crew_ko'])
        self.assertTrue(self.player.critical['fire'])
        self.assertEqual(('bot', 9, 2.0), (
            self.player.fire_attacker_kind, self.player.fire_attacker_id,
            self.player.combat_fire_elapsed))

    def test_fatal_landing_keeps_native_death_after_contact_critical(self):
        import test_port_0922_battle_runtime as runtime_fixture

        self.player.health = 50
        message = self.observation((1.0, 0.0))
        self.assertTrue(self.submit(message))
        event = self.state.pending_events[-1]
        self.assertEqual((50, 0, True, 3), (
            event['damage'], event['health'], event['dead'], event['death_reason']))
        self.assertFalse(self.player.alive)
        self.assertEqual(1, self.player.landing_observation_seq)

        runtime = runtime_fixture._runtime()
        battle = runtime_fixture.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        battle._binding = mock.Mock()
        battle._avatar.playerVehicleID = 10
        descriptor = runtime_fixture._Descriptor()
        descriptor.type = types.SimpleNamespace(
            crewRoles=(('commander',), ('driver',)))
        entity = runtime_fixture._Vehicle(
            10, descriptor, runtime_fixture._Vector(), (0, 0, 0), {'health': 50})
        runtime.bigworld.entities[10] = entity
        record = {
            'engine_id': 10, 'kind': 'player', 'network_id': 1, 'local': True,
            'state': {'health': 50, 'alive': True, 'team': 1},
        }
        battle._records = {'player:1': record}
        battle._present_critical = mock.Mock()
        battle._sync_fire_effect = mock.Mock()
        entity.onHealthChanged = mock.Mock(wraps=entity.onHealthChanged)
        with mock.patch.object(
                runtime_fixture.critical_damage, 'apply_death',
                wraps=runtime_fixture.critical_damage.apply_death) as death:
            self.assertTrue(battle._apply_combat_event(event))
            death.assert_called_once_with(entity, 'world_collision')
            terminal = copy.deepcopy(record['critical_state'])
            self.assertEqual(['commander', 'driver'], terminal['crew_ko'])
            self.assertIn(LEFT, terminal['destroyed'])
            self.assertIn('engineHealth', terminal['destroyed'])
            self.assertFalse(terminal['events'])
            self.assertTrue(battle._apply_combat_event(event))
            self.assertEqual(1, death.call_count)
            self.assertFalse(battle._apply_critical_state(
                record, event['critical'], event))
            self.assertEqual(terminal, record['critical_state'])
        entity.onHealthChanged.assert_called_once_with(0, 0, 3)
        self.assertFalse(entity.isCrewActive)
        self.assertTrue(self.submit(message))
        self.assertEqual(1, len(self.state.pending_events))


class LandingCriticalClientTests(unittest.TestCase):
    def setUp(self):
        self.fixture = client_fixture.ProjectileWireTests()
        self.client = self.fixture.active_client()
        self.assertTrue(self.fixture.send_player_input(self.client))

    def last_wire(self):
        return client_fixture.wire_copy(self.client._outbound_queue[-1][1])

    def reply(self, **changes):
        result = {
            'type': 'landing_observation_result', 'round_id': 3,
            'authority_epoch': 4, 'observation_seq': 1,
            'input_seq': 1, 'committed_seq': 0,
            'accepted': False, 'reason': 'stale_authority',
        }
        result.update(changes)
        return result

    def test_queued_landing_keeps_each_load_distribution_frozen(self):
        loads = [0.8, 0.1]
        self.assertEqual(1, self.client.send_landing_observation(20.0, loads))
        first = self.last_wire()
        loads[:] = [0.0, 1.0]
        self.assertTrue(self.fixture.send_player_input(self.client))
        self.assertEqual(1, self.client.send_landing_observation(18.0, (0.1, 0.7)))
        self.assertEqual(first, self.client._landing_observation_pending['wire'])
        self.assertTrue(self.client._handle_landing_observation_result(
            self.reply(accepted=True, reason='', committed_seq=1)))
        second = self.last_wire()
        self.assertEqual((2, 18.0, [0.1, 0.7]), (
            second['observation_seq'], second['impact_speed'], second['track_loads']))
        self.assertEqual([0.8, 0.1], first['track_loads'])

    def test_authority_and_input_rebinding_preserve_contact_evidence(self):
        self.assertEqual(1, self.client.send_landing_observation(20.0, (0.2, 0.6)))
        self.assertTrue(self.client._handle_landing_observation_result(
            self.reply(authority_epoch=5)))
        rebound = self.last_wire()
        self.assertEqual((5, 1, [0.2, 0.6]), (
            rebound['authority_epoch'], rebound['input_seq'], rebound['track_loads']))
        self.assertTrue(self.client._handle_landing_observation_result(
            self.reply(authority_epoch=5, reason='stale_input')))
        self.assertTrue(self.fixture.send_player_input(self.client))
        rebound = self.last_wire()
        self.assertEqual(('landing_observation', 1, 2, [0.2, 0.6]), (
            rebound['type'], rebound['observation_seq'], rebound['input_seq'],
            rebound['track_loads']))

    def test_failed_send_retries_same_loads_without_duplicate_observation(self):
        attempts = []

        def send(message):
            attempts.append(client_fixture.wire_copy(message))
            return len(attempts) > 1

        self.client._send = send
        self.assertFalse(self.client.send_landing_observation(18.0, (0.7, 0.1)))
        self.assertTrue(self.fixture.send_player_input(self.client))
        self.assertEqual(1, self.client.send_landing_observation(18.0, (0.7, 0.1)))
        observations = [row for row in attempts if row['type'] == 'landing_observation']
        self.assertEqual(2, len(observations))
        for row in observations:
            self.assertEqual((1, [0.7, 0.1]),
                             (row['observation_seq'], row['track_loads']))
        self.assertFalse(self.client._landing_observation_queue)


if __name__ == '__main__':
    unittest.main()
