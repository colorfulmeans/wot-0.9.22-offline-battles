"""Sortie retries, mandatory home handoff and shared-road admission."""
import copy
import unittest
from types import SimpleNamespace
from unittest import mock

import test_port_0922_route_task_rules as travel_fixture
from gui.mods.offline_lan_0922 import spg_route_recovery as recovery


class ArtilleryRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = travel_fixture.AuthoredArtilleryTravelTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.runtime, self.state = fixture.runtime, fixture.state
        self.travel, self.settings = fixture.travel, fixture.settings
        self.runtime.baked_graph['objective_bases'][1] = [0, 400]
        self.runtime._ordered_states = lambda: [self.state]
        self.points = [[0, 0, 0], [0, 100, 0], [0, 200, 0], [0, 300, 0], [0, 400, 0]]
        attack = dict(id='attack', team=1, purpose='spg_attack', points=self.points)
        self.settings['routes'] = [attack]
        self.state.update(x=0., z=100., _authored_spg_attack=copy.deepcopy(attack),
                          _authored_spg_travel=dict(kind='attack', identity=('attack', 'attack'),
                                                   points=copy.deepcopy(self.points), index=2))
        self.active = self.state['_authored_spg_travel']

    def tick(self, now, **order):
        command = dict(combat_mode='base_capture', target_id=None, fire_allowed=False)
        command.update(order)
        return self.travel.apply(self.runtime, self.state, command, now)

    def blocked_until_return(self):
        self.tick(0)
        self.assertEqual(3, self.tick(21)['route_index'])
        self.tick(22)
        self.assertEqual(1, self.tick(43)['route_index'])
        self.assertEqual('return', self.active['recovery_phase'])

    def test_skip_then_reverse_every_node_and_select_only_after_home(self):
        self.blocked_until_return()
        with mock.patch.object(recovery, 'select_route', return_value=dict(
                id='borrowed', points=[[100, 0, 0], [100, 200, 0], [0, 400, 0]], borrowed=True)) as select:
            # B is already reached; go back to A, not forward toward C.
            self.assertEqual((0, 0., 0), self.tick(44)['move_position'])
            self.assertEqual('return', self.active['recovery_phase'])
            self.runtime.baked_graph['objective_bases'][0] = [-100, 0]
            self.state.update(x=0., z=0.)
            self.assertEqual((-100, 0., 0), self.tick(45)['move_position'])
            select.assert_not_called()
            self.state.update(x=-100., z=0.)
            self.assertEqual((100, 0., 0), self.tick(46)['move_position'])
            select.assert_called_once()
            self.assertEqual('transfer', self.active['recovery_phase'])
            self.state.update(x=100., z=0.)
            self.assertEqual((100, 0., 200), self.tick(47)['move_position'])
            self.assertNotIn('recovery_phase', self.active)

    def test_travel_uses_next_waypoint_not_old_parking_or_enemy_face(self):
        for mode in ('base_capture','base_defense'):
            result=self.tick(1.,combat_mode=mode,face_position=(900.,0.,900.),
                             aim_position=(500.,2.,500.),target_id=9,fire_allowed=False)
            self.assertEqual(result['move_position'],result['face_position'])
            self.assertEqual((500.,2.,500.),result['aim_position'])
            self.assertEqual(9,result['target_id'])

    def test_reaching_skipped_point_finishes_recovery_and_keeps_attack(self):
        self.tick(0); self.tick(21)
        self.state['z'] = 300.
        self.assertEqual(4, self.tick(22)['route_index'])
        self.assertNotIn('recovery_phase', self.active)

    def test_failed_return_skip_retries_original_forward_point_without_limit(self):
        self.state['z'] = 150.
        for now in range(0, 401, 21):
            self.tick(now); self.tick(now+.01)
        self.assertEqual('attack', self.active['kind'])
        self.assertIn(self.active.get('recovery_phase'), ('forward', 'skip', 'return', 'return_skip'))
        # Exercise the exact final failure of a round.
        self.active.update(index=0, failed_index=2, recovery_phase='return_skip')
        self.active.pop('attack_attempt', None)
        self.tick(500); self.tick(521)
        self.assertEqual(2, self.active['index'])
        self.assertEqual('forward', self.active['recovery_phase'])

    def test_firing_combat_pauses_clock_and_preserves_recovery_cursor(self):
        self.blocked_until_return()
        self.state['z'] = 150.
        self.tick(44)
        self.tick(50, combat_mode='engage', target_id=9, fire_allowed=True)
        self.tick(500, combat_mode='engage', target_id=9, fire_allowed=True)
        self.tick(501)
        self.assertEqual(1, self.active['index'])
        self.assertEqual('return', self.active['recovery_phase'])
        self.assertEqual(495., self.active['attack_attempt']['since'])
        self.tick(516)
        self.assertEqual('return_skip', self.active['recovery_phase'])

    def test_defense_interrupt_restores_return_progress_not_forward_attack(self):
        self.blocked_until_return()
        self.state['z'] = 150.
        self.tick(44)
        self.tick(45, combat_mode='base_defense')
        self.tick(500)
        active = self.state['_authored_spg_travel']
        self.assertEqual(1, active['index'])
        self.assertEqual('return', active['recovery_phase'])
        self.assertEqual(499., active['attack_attempt']['since'])

    def test_enemy_circle_holds_even_when_recovery_clock_has_expired(self):
        self.blocked_until_return()
        self.state['z'] = 380.
        result = self.tick(500)
        self.assertEqual('base_capture', result['combat_mode'])
        self.assertEqual(0., result['throttle_override'])
        self.state['z'] = 350.
        self.assertEqual((0, 0., 400), self.tick(501)['move_position'])
        self.assertNotIn('recovery_phase', self.active)

    def test_transfer_blockage_returns_home_and_retries_rather_than_stopping(self):
        self.state.update(x=50., z=50.)
        self.active.update(index=0, recovery_phase='transfer')
        self.tick(0)
        self.assertEqual((0, 0., 0), self.tick(21)['move_position'])
        self.assertEqual('home', self.active['recovery_phase'])
        for now in (22, 43, 44, 65):self.tick(now)
        self.assertEqual('home', self.active['recovery_phase'])


class ArtilleryRouteSelectionTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(id=11, team=1, alive=True, x=0., y=0., z=0.)
        self.states = [self.state]
        self.rows = []
        self.runtime = SimpleNamespace(_ordered_states=lambda: self.states,
            _bot_tactics={}, _navigation_map_name='08_ruinberg', baked_graph={}, _server_orders={})
        self.failed = dict(id='original', points=[[0, 0, 0], [0, 100, 0], [0, 400, 0]])
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(recovery, '_catalog', side_effect=lambda *args:self.rows).start()
        mock.patch.object(recovery.bot_tactics_runtime, 'graph_view', return_value=object()).start()
        self.validate = mock.patch.object(recovery.bot_tactics_runtime, 'validate_route', return_value=None).start()

    def route(self, identity, x, **extra):
        row = dict(id=identity, waypoints=[[0, 0, 60], [x, 200, 60], [0, 400, 0]])
        row.update(extra); self.rows.append(row)
        return row

    def choose(self):
        return recovery.select_route(self.runtime, self.state, self.failed)

    def test_reserve_empty_road_beats_occupied_main_road(self):
        main = self.route('main', 100)
        reserve = self.route('reserve', -100, _route_tier='reserve')
        self.states.append(dict(id=12, team=1, alive=True, route=main))
        self.assertEqual('reserve', self.choose()['id'])
        self.assertEqual([0, 0, 0], self.choose()['points'][0])

    def test_identical_class_variants_share_occupancy_and_are_not_extra_draws(self):
        self.route('lt', 100); self.route('ht', 100); self.route('other', -100)
        self.runtime._server_orders[12] = dict(route_id='ht')
        self.states.append(dict(id=12, team=1, alive=True))
        self.assertEqual('other', self.choose()['id'])
        self.states.pop()
        with mock.patch.object(recovery.random, 'choice', side_effect=lambda values:values[-1]) as choice:
            self.assertEqual('other', self.choose()['id'])
        self.assertEqual(2, len(choice.call_args[0][0]))

    def test_failed_geometry_is_avoided_even_if_renamed_and_empty(self):
        self.rows.append(dict(id='renamed', waypoints=self.failed['points']))
        busy = self.route('other', 100)
        self.states.append(dict(id=12, team=1, alive=True, route=busy))
        self.assertEqual('other', self.choose()['id'])

    def test_no_other_valid_route_retries_original(self):
        self.route('unreachable', 100)
        self.validate.return_value = 'waypoints_disconnected'
        self.assertEqual(self.failed, self.choose())
        self.assertIsNot(self.failed, self.choose())

    def test_unreachable_base_connector_excludes_otherwise_valid_route(self):
        self.route('unreachable', 100)
        self.validate.side_effect = lambda graph, route: 'waypoints_disconnected' if len(route['points']) == 2 else None
        self.assertEqual(self.failed, self.choose())

    def test_immediate_claim_spreads_two_switching_artillery_vehicles(self):
        self.route('a', 100); self.route('b', -100)
        peer = dict(id=12, team=1, alive=True, x=0., y=0., z=0.)
        self.states.append(peer)
        self.state['_authored_spg_attack'] = self.choose()
        selected = recovery.select_route(self.runtime, peer, self.failed)
        self.assertNotEqual(self.state['_authored_spg_attack']['id'], selected['id'])

    def test_dead_or_other_team_does_not_occupy_road(self):
        a = self.route('a', 100); self.route('b', -100)
        self.states.extend([dict(id=12, team=1, alive=False, route=a), dict(id=13, team=2, alive=True, route=a)])
        with mock.patch.object(recovery.random, 'choice', side_effect=lambda values:values[0]):
            self.assertEqual('a', self.choose()['id'])


class ArtilleryCatalogTests(unittest.TestCase):
    def test_real_navigation_rejects_disconnected_entry_not_connected_route_itself(self):
        from gui.mods.offline_lan_0922 import spg_positions
        bounds = recovery.bot_tactics.MAPS['08_ruinberg']['bounds']
        graph = dict(map='08_ruinberg', game_version=spg_positions.CATALOG['game_version'],
            bounds=bounds, width=4, height=1, cell_size=4., origin=[0., 0.],
            heights_mm=[0]*4, hazards=[0]*4, links=[1, 16, 1, 16],
            directions=[[1, 0], [1, 1], [0, 1], [-1, 1], [-1, 0], [-1, -1], [0, -1], [1, -1]])
        good = dict(id='good', waypoints=[[0, 0, 0], [4, 0, 0]])
        disconnected = dict(id='disconnected', waypoints=[[8, 0, 0], [12, 0, 0]])
        runtime = SimpleNamespace(adapter=SimpleNamespace(director=SimpleNamespace(
            map_data=dict(routes={1:[good, disconnected]}))), _bot_tactics={},
            baked_graph=graph, _navigation_map_name='08_ruinberg', _ordered_states=lambda:[])
        state = dict(id=11, team=1, x=0., y=0., z=0.)
        failed = dict(id='old', points=[[0, 0, 0], [0, 4, 0]])
        self.assertEqual('good', recovery.select_route(runtime, state, failed)['id'])

    def test_effective_variants_disabled_scope_and_team_are_respected(self):
        route = dict(id='road', waypoints=[[0, 0, 0], [100, 200, 0]])
        rows = [route]
        for tag in ('lightTank', 'mediumTank', 'heavyTank', 'AT-SPG'):
            rows.append(dict(route, id=tag, _editor_source='road', _editor_class=tag,
                             class_weights={c:float(c==tag) for c in recovery.bot_tactics.CLASSES}))
        rows.append(dict(route, id='disabled', disabled=True))
        runtime = SimpleNamespace(adapter=SimpleNamespace(director=SimpleNamespace(
            map_data=dict(routes={1:rows, 2:[dict(route, id='enemy')]}))),
            _bot_tactics={}, _navigation_map_name='08_ruinberg')
        result = recovery._catalog(runtime, 1)
        self.assertEqual({'lightTank', 'mediumTank', 'heavyTank', 'AT-SPG'}, {r['id'] for r in result})


if __name__ == '__main__':
    unittest.main()
