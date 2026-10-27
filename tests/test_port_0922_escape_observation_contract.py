"""Recorded Highway short-escape and remembered-radio boundary regressions."""
import copy
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import subprocess
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/res/scripts/client'), str(ROOT / 'server')]
from gui.mods.offline_lan_0922.ai.driver import LocalDriver, short_escape_remaining
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922.prebaked_navigation import with_shore_hazards
from gui.mods.offline_lan_0922.lan_client import LANClient, PROTOCOL_VERSION
import test_port_0922_bot_runtime as worker_fixture


class EscapeEndpointTests(unittest.TestCase):
    def test_selected_and_retained_commands_keep_the_same_endpoint(self):
        driver = LocalDriver()
        state = dict(clock=0.)
        command = driver._short_escape(state, (0., 0., 0.), 0., 0.,
            .1, .2, 0., [], lambda *args: True, 3.5, 1.7)
        self.assertEqual(-1., command['throttle'])
        self.assertAlmostEqual(.2, short_escape_remaining(command, (0., 0., -1.8)))
        state['clock'] = .2
        retained = driver._retained_short_escape(state, (0., 0., -1.8),
            0., [], lambda *args: True, 3.5, 1.7)
        self.assertEqual(command['recovery_probe_origin'], retained['recovery_probe_origin'])
        self.assertEqual(command['recovery_probe_length'], retained['recovery_probe_length'])
        self.assertAlmostEqual(.1, short_escape_remaining(retained, (0., 0., -1.9)))
        self.assertEqual(0., short_escape_remaining(retained, (0., 0., -2.1)))

    def test_forward_reverse_and_rotated_projection(self):
        for sign in (-1., 1.):
            for yaw in (0., 1., -math.pi, math.pi - .01):
                heading = yaw + (math.pi if sign < 0. else 0.)
                command = dict(recovery_mode='short_reverse_escape' if sign < 0. else
                    'short_forward_escape', recovery_probe_origin=(3., 0., 4.),
                    recovery_probe_yaw=heading, recovery_probe_length=2.)
                position = (3.+math.sin(heading)*1.8, 10., 4.+math.cos(heading)*1.8)
                self.assertAlmostEqual(.2, short_escape_remaining(command, position))
        self.assertIsNone(short_escape_remaining(dict(recovery_mode='drive'), (0.,0.,0.)))

    def test_recorded_cda_interval_ends_before_the_rejected_shore_cell(self):
        fixture = worker_fixture.BotRuntimeTests(); fixture.setUp()
        try:
            runtime = fixture.runtime
            # Preserve the recorded pre-1.2 m hazard when testing endpoint
            # accounting; the water-rebake suite covers the new real map.
            graph = with_shore_hazards(json.loads(subprocess.check_output(
                ['git','show','100bac61:navgraphs/45_north_america.json'],cwd=ROOT)))
            runtime.baked_graph = graph
            runtime.navigator.grid = TerrainGrid(lambda *args: None, baked_graph=graph)
            origin = (-157.94161115478047, -13.256248474121094, -241.96019255325092)
            current = (-158.5181349696705, -13.082676887512207, -243.5402650249587)
            heading = .34986168198842005 + math.pi
            command = dict(recovery_mode='short_reverse_escape', recovery_probe_distance=2.,
                recovery_probe_origin=origin, recovery_probe_yaw=heading, recovery_probe_length=2.)
            state = {}
            distance = runtime._short_escape_commit_distance(state, command, current, 525.243)
            self.assertLess(distance, .5)
            self.assertGreater(distance, .05)
            self.assertFalse(runtime._planner_corridor_clear(current, heading, 0.,
                hazard_only=True, maximum_distance=.5))
            self.assertTrue(runtime._planner_corridor_clear(current, heading, 0.,
                hazard_only=True, maximum_distance=distance))
            self.assertEqual('bounded_endpoint', state['_short_escape_commit']['reason'])
            self.assertEqual(origin, state['_short_escape_commit']['selected_origin'])
        finally:
            fixture.tearDown()

    def test_runtime_commit_uses_remaining_interval_and_retires_completed_cache(self):
        fixture = worker_fixture.BotRuntimeTests(); fixture.setUp()
        try:
            runtime = fixture.runtime
            runtime.battle_start(fixture.start)
            runtime._server_orders = {11: dict(combat_mode='route',
                move_position=(0.,0.,-10.),fire_allowed=False)}
            state = runtime.states[11]
            state.update(x=0.,y=0.,z=-1.8,yaw=0.,speed=0.,grounded_once=True)
            decide = runtime.adapter.decide_with_order
            def short_command(*args):
                command = decide(*args)
                command.update(recovery_mode='short_reverse_escape',throttle=-1.,turn=0.,
                    target_yaw=0.,movement_intent=True,brake=False,
                    recovery_probe_origin=(0.,0.,0.),recovery_probe_yaw=math.pi,
                    recovery_probe_length=2.,recovery_probe_distance=2.)
                return command
            runtime.adapter.decide_with_order = short_command
            with contextlib.redirect_stdout(io.StringIO()):
                runtime.update(.1, 1.)
            receipt = state['_short_escape_commit']
            self.assertEqual('bounded_endpoint', receipt['reason'])
            self.assertAlmostEqual(.2, receipt['probe_distance'])
            self.assertAlmostEqual(.2, state['_committed_corridor']['maximum_distance'])
            state.update(x=0.,y=0.,z=-2.1,yaw=0.,speed=0.)
            with contextlib.redirect_stdout(io.StringIO()):
                runtime.update(.1, 1.1)
            self.assertEqual('completed', state['_short_escape_commit']['reason'])
            self.assertNotIn(11, runtime._decision_cache)
            state.update(x=0.,y=0.,z=-1.,yaw=0.,speed=0.)
            runtime._planner_corridor_clear = lambda *args, **kwargs: False
            with contextlib.redirect_stdout(io.StringIO()):
                runtime.update(.1, 1.2)
            self.assertEqual('hazard_rejected',state['_committed_corridor']['reason'])
            self.assertTrue(state['_committed_corridor']['cache_retired'])
            self.assertNotIn(11,runtime._decision_cache)
        finally:
            fixture.tearDown()

    def test_recorded_caernarvon_and_edelweiss_have_the_same_horizon_mismatch(self):
        graph = with_shore_hazards(json.loads(subprocess.check_output(
            ['git','show','100bac61:navgraphs/45_north_america.json'],cwd=ROOT)))
        grid = TerrainGrid(lambda *args: None, baked_graph=graph)
        cases = [((-147.678998616346,-12.94148063659668,383.7186671942012),
                  4.550603872527937,.2635838600024083),
                 ((-151.7575250498032,-13.3972487449646,374.77057694737135),
                  5.301925554812718,.09417472766375434),
                 ((-151.77989756524047,-13.430670738220215,373.80785992336354),
                  4.862358547219511,.11404639920486404)]
        for position,yaw,remaining in cases:
            def rejected(distance):
                end=(position[0]+math.sin(yaw)*distance,position[1],
                     position[2]+math.cos(yaw)*distance)
                return grid.segment_has_motion_hazard(position,end,13)
            self.assertTrue(rejected(.5))
            self.assertFalse(rejected(remaining))


class RememberedObservationTests(unittest.TestCase):
    @staticmethod
    def contact():
        return dict(observing_team=2, target_team=1, target_kind='human', target_id=2,
            visible=True, fresh=False, time_left=5., visible_by_bot_ids=[],
            visible_by_player_ids=[], shootable_by_bot_ids=[11], threatened_bot_ids=[],
            radio_recipients=[dict(kind='bot', id=11, time_left=4.)])

    def deliver(self, contacts, round_id=2):
        client = LANClient('127.0.0.1', 28782, 'contract', 'ussr:R11_MS-1')
        client.phase = 'battle'; client.round_id = round_id
        delivered, rejected = [], []
        client._notify = lambda *args, **kwargs: delivered.append((args, kwargs))
        client._ignore_runtime_payload = lambda kind, reason, msg: rejected.append(reason) or True
        client._handle_message(dict(type='bot_observation', round_id=round_id,
            protocol=PROTOCOL_VERSION, contacts=contacts))
        return delivered, rejected

    def test_actual_server_relay_reaches_the_visible_client(self):
        server, unused_a, unused_b = worker_fixture.ServerBotObservationRelayTests._server()
        relay = server.update_bot_observation(worker_fixture.SIMULATION_WORKER_AUTHORITY_ID,
            dict(type='bot_observation', round_id=server.round_id, contacts=[self.contact()]))
        self.assertIsInstance(relay, dict)
        self.assertEqual([11], relay['contacts'][0]['shootable_by_bot_ids'])
        delivered, rejected = self.deliver(relay['contacts'], server.round_id)
        self.assertTrue(delivered)
        self.assertEqual([], rejected)

    def test_mixed_fresh_and_remembered_batch_is_not_discarded(self):
        remembered = self.contact()
        fresh = dict(self.contact(), target_id=1, fresh=True, visible_by_bot_ids=[11])
        delivered, rejected = self.deliver([fresh, remembered])
        self.assertTrue(delivered); self.assertEqual([], rejected)

    def test_received_memory_lights_an_enemy_for_a_dead_local_spectator(self):
        import test_port_0922_battle_runtime as presentation
        runtime = presentation._runtime()
        battle = presentation.BattleRuntime(runtime)
        battle.client = types.SimpleNamespace(team=2, player_id=1)
        battle._local_position = (0., 0., 0.)
        entity = presentation._Vehicle(12, presentation._Descriptor(),
            presentation._Vector(100.,0.,0.), (0,0,0), {'health':500})
        runtime.bigworld.entities[12] = entity
        target = dict(engine_id=12, network_id=2, kind='player', ready=True,
            presentation=True, local=False, tombstone=False, spot_visible=False,
            spot_until=0., state=dict(team=1, health=500, alive=True))
        battle._records = {'player:1': dict(local=True, state=dict(team=2,alive=False)),
            'player:2': target}
        battle._set_record_spot_visibility = lambda record, visible: record.update(
            spot_visible=bool(visible)) or bool(visible)
        battle._spot_line_of_sight = lambda *args: self.fail('radio presentation must not rescan LOS')
        client = LANClient('127.0.0.1',28782,'contract','ussr:R11_MS-1')
        client.phase='battle';client.round_id=2
        def receive(kind, message, **kwargs):
            battle._apply_team_observation(message, 10.)
        client._notify=receive
        client._handle_message(dict(type='bot_observation',protocol=PROTOCOL_VERSION,
            round_id=2,contacts=[self.contact()]))
        self.assertTrue(target['spot_visible'])
        self.assertTrue(target['spot_marker_visible'])
        self.assertEqual(15., target['radio_spot_until'])
        self.assertEqual(0., target['spot_until'])

    def test_invalid_memory_identity_and_false_freshness_still_reject(self):
        for change in (dict(time_left=0.), dict(time_left=float('nan')),
                       dict(target_team=2), dict(target_id=True),
                       dict(fresh=True), dict(shootable_by_bot_ids=[11,11]),
                       dict(threatened_bot_ids=[11]), dict(visible=False, time_left=0.)):
            delivered, rejected = self.deliver([dict(self.contact(), **change)])
            self.assertFalse(delivered, change)
            self.assertEqual(['invalid_contacts'], rejected, change)


if __name__ == '__main__':
    unittest.main()
