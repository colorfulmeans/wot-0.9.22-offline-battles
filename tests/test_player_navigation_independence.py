"""Independent foreground route algorithms and observed-world integration.

The flat/corridor fixtures exercise real player pathfinding. Native movement
probes are explicit seams; these tests do not claim a Windows-client drive.
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from test_player_navigation_migration import controller, state
from gui.mods.offline_lan_0922 import native_navigation_query, prebaked_navigation
from gui.mods.offline_lan_0922.player_control import navigation
from gui.mods.offline_lan_0922.player_control.local_height import PlayerLocalHeightLinks
from gui.mods.offline_lan_0922.player_control.local_routes import LocalRoutes
from gui.mods.offline_lan_0922.player_control.navigation_support import PlayerHeightSupport
from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder, PlayerTerrainGrid


def graph(passage=False):
    size, cell, origin = 51, 2., -50.
    heights = []
    for z in range(size):
        for x in range(size):
            px, pz = origin + x * cell, origin + z * cell
            heights.append(0 if not passage or abs(pz) > 10. or abs(px) <= 2. else None)
    directions = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
    links = []
    for z in range(size):
        for x in range(size):
            mask = 0
            if heights[z * size + x] is not None:
                for bit, (dx, dz) in enumerate(directions):
                    nx, nz = x + dx, z + dz
                    if 0 <= nx < size and 0 <= nz < size and heights[nz * size + nx] is not None:
                        mask |= 1 << bit
            links.append(mask)
    return dict(format='offline-lan-0922-navgraph', version=2, width=size, height=size,
        origin=[origin, origin], bounds=[-50., -50., 50., 50.], cell_size=cell,
        heights_mm=heights, links=links, hazards=[0] * len(heights),
        routes={'1': [dict(id='main', waypoints=[(0., -30.), (0., 0.), (0., 40.)])], '2': []},
        objective_bases=[(0., -40.), (0., 45.)], objective_base_radii=[5., 5.])


def peer(identity=9, position=(0., 0., 20.), alive=False, speed=0., team=1, yaw=0.):
    return dict(id=identity, position=position, alive=alive, speed=speed, team=team,
                yaw=yaw, collision_shape=(1.5, 3.5, -.4, 2.))


class IndependentPathfindingTests(unittest.TestCase):
    def setUp(self):
        diagnostics = mock.patch('gui.mods.offline_lan_0922.player_control.pathfinding.write_json_record')
        diagnostics.start()
        self.addCleanup(diagnostics.stop)

    def scene(self, passage=False):
        nav = PlayerPathfinder(lambda *args: 0., lambda *args: False, baked_graph=graph(passage))
        self.addCleanup(nav.close)
        nav.player_states[17] = {}
        support = PlayerHeightSupport(nav.grid, lambda *args: 0., None)
        self.addCleanup(support.close)
        return nav, support, LocalRoutes(nav, support, 1)

    def test_player_owns_algorithms_and_never_imports_ai_implementation(self):
        folder = Path(navigation.__file__).parent
        for name in ('pathfinding.py', 'local_height.py', 'navigation_support.py', 'local_routes.py'):
            tree = ast.parse((folder / name).read_text())
            imports = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(any('ai.' in value or value.endswith('.ai') or 'bot_runtime' in value
                                 for value in imports), (name, imports))
        self.assertEqual((object,), PlayerPathfinder.__bases__)
        self.assertEqual((object,), PlayerTerrainGrid.__bases__)
        self.assertEqual((object,), PlayerLocalHeightLinks.__bases__)
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator, TerrainGrid
        from gui.mods.offline_lan_0922.ai.local_height import LocalHeightLinks
        with mock.patch.object(TerrainNavigator, '__init__', side_effect=AssertionError('Bot called')), \
             mock.patch.object(TerrainGrid, '__init__', side_effect=AssertionError('Bot called')), \
             mock.patch.object(LocalHeightLinks, '__init__', side_effect=AssertionError('Bot called')):
            nav, support, unused = self.scene()
            links = PlayerLocalHeightLinks(lambda *args: dict(status='complete', surfaces=[]))
            plan = nav.grid.begin_plan((0., 0., -20.), (0., 0., 20.))
            while not plan.done:
                plan.step(4096)
            self.assertGreater(len(plan.result), 1)
            self.assertIsNotNone(links)
            self.assertIs(support.grid, nav.grid)

    def test_wrecks_and_turrets_update_global_geometry_not_only_local_braking(self):
        nav, support, local = self.scene()
        current = state(position=(0., 0., -20.))
        context = dict(neighbours=[peer(position=(0., 0., 0.)), peer(10, alive=True)],
                       turret_hulls=[(-90, 20., 0., 0., 2., 1.)])
        local.publish(current, context)
        self.assertEqual(2, local.static_receipt['count'])
        self.assertTrue(nav.grid.segment_penalty((0., 0., -20.), (0., 0., 20.), 0.))
        plan = nav.grid.begin_plan((0., 0., -20.), (0., 0., 20.))
        while not plan.done:
            plan.step(4096)
        self.assertGreater(len(plan.result), 2)
        self.assertFalse(nav.grid.path_crosses_static_hull(plan.result))
        revision = nav.grid.static_hull_revision
        local.publish(current, context)
        self.assertEqual(revision, nav.grid.static_hull_revision)
        local.publish(current, dict(neighbours=[], turret_hulls=[]))
        self.assertEqual((), nav.grid._static_hulls)
        self.assertGreater(nav.grid.static_hull_revision, revision)

    def test_static_publish_rejects_invalid_pose_and_follows_a_pushed_wreck(self):
        nav, unused, local = self.scene()
        current = state()
        local.publish(current, dict(neighbours=[peer(position=(0., 0., 20.))]))
        revision = nav.grid.static_hull_revision
        local.publish(current, dict(neighbours=[peer(position=(20., 0., 20.)),
            peer(99, position=(float('nan'), 0., 5.))], turret_hulls=[(1, 2)]))
        self.assertGreater(nav.grid.static_hull_revision, revision)
        self.assertEqual(2, local.static_receipt['invalid'])
        self.assertEqual(20., nav.grid._static_hulls[0][1])
        self.assertFalse(nav.grid.path_crosses_static_hull(((0., 0., 0.), (0., 0., 40.))))

    def test_new_observed_wreck_retires_active_cached_join_and_keeps_clear_route(self):
        nav, unused, local = self.scene()
        nav.player_states.clear()
        start, goal = (0., 0., -20.), (0., 0., 20.)
        request = ('route', 17, 'lane', 1)
        nav.next_target(17, start, goal, request, 0.)
        active = nav._cache_key(('join', 17, nav.grid.cell_for(start)) + request, goal)
        nav.paths[active] = (start, (0., 0., 0.), goal)
        nav.path_times[active] = 0.
        nav.path_hull_revisions[active] = nav.grid.static_hull_revision
        nav.player_states[17].update(path_key=active, index=1, last_target=(0., 0., 0.))
        local.publish(state(position=start), dict(neighbours=[peer(position=(0., 0., 0.))]))
        shared = nav._cache_key(request, goal)
        nav.paths[shared] = (start, (-12., 0., -20.), (-12., 0., 20.), goal)
        nav.path_hull_revisions[shared] = nav.grid.static_hull_revision
        target = nav.next_target(17, start, goal, request, .1)
        self.assertNotEqual(active, nav.player_states[17]['path_key'])
        self.assertFalse(nav.grid.path_crosses_static_hull((start, target)))

    def test_retask_and_close_cancel_only_this_players_resources(self):
        first, support, unused = self.scene()
        second, unused, unused = self.scene()
        one, two = mock.Mock(), mock.Mock()
        first._native_navigation, second._native_navigation = one, two
        job = object()
        first.searches['old_command'] = job
        first.search_times['old_command'] = 0.
        second.searches['other_player'] = object()
        first.reset_travel()
        one.cancel.assert_called_once_with([job])
        two.cancel.assert_not_called()
        self.assertEqual({}, first.searches)
        self.assertIn('other_player', second.searches)
        first.grid.native_query_oracle = object()
        first.paths['old_path'] = ((0., 0., 0.), (0., 0., 20.))
        first.player_states[17] = dict(last_target=(0., 0., 20.))
        first.close()
        first.close()
        one.close.assert_called_once_with()
        two.close.assert_not_called()
        self.assertIsNone(first.grid.native_query_oracle)
        self.assertIsNone(first.grid.ground_probe)
        self.assertEqual({}, first.player_states)
        self.assertEqual({}, first.paths)
        self.assertEqual((1., 0., 1.), first.next_target(17, (1., 0., 1.),
                                                        (0., 0., 20.), ('late',), 1.))
        support.close()
        self.assertIsNone(support.ground)

    def test_narrow_axis_is_player_owned_and_retained_until_tail_exits(self):
        nav, support, local = self.scene(True)
        current = dict(state(), half_length=3.5, half_width=1.5)
        goal = (3., 0., 18.)
        support.begin(current['position'], 0.)
        target = local.adjust(current, {}, goal, goal, ('narrow',), lambda *args: True)
        self.assertEqual(0., target[0])
        self.assertGreater(target[2], 0.)
        self.assertEqual('narrow_passage', local.receipt['status'])
        self.assertEqual(target, nav.player_states[17]['local_fallback_target'])
        current.update(now=1., position=(0., 0., 12.))
        support.begin(current['position'], 1.)
        target = local.adjust(current, {}, goal, goal, ('narrow',), lambda *args: True)
        self.assertEqual(0., target[0])
        self.assertGreater(target[2], 12.)
        current.update(now=2., position=(0., 0., 17.))
        goal = (3., 0., 22.)
        self.assertEqual(goal, local.adjust(current, {}, goal, goal, ('narrow',), lambda *args: True))
        self.assertNotIn('narrow_passage_target', nav.player_states[17])

    def test_narrow_guidance_cannot_replace_an_owned_astar_bend(self):
        unused, support, local = self.scene(True)
        current = state()
        support.begin(current['position'], 0.)
        bend = (0., 0., 4.)
        self.assertEqual(bend, local.adjust(current, {}, (3., 0., 18.), bend,
                                           ('narrow',), lambda *args: True))

    def test_occupied_endpoint_gets_one_bounded_checked_bypass(self):
        nav, support, local = self.scene()
        current, goal = state(), (0., 0., 20.)
        context = dict(neighbours=[peer()])
        support.begin(current['position'], 0.)
        target = local.adjust(current, context, goal, goal, ('route', 1), lambda *args: True)
        self.assertNotEqual(goal, target)
        self.assertEqual('bypass_issued', local.receipt['status'])
        current['now'] = 1.
        self.assertEqual(target, local.adjust(current, context, goal, goal, ('route', 1), lambda *args: True))
        self.assertEqual('bypass_retained', local.receipt['status'])
        current.update(now=2., position=target)
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('route', 1), lambda *args: True))
        self.assertEqual('bypass_completed', local.receipt['status'])
        nav.grid.static_hull_revision += 1  # An unrelated death is not a new attempt.
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('route', 1), lambda *args: True))
        self.assertEqual('bypass_completed', local.receipt['status'])

    def test_bypass_stall_refusal_hidden_enemy_and_other_floor_stay_bounded(self):
        nav, support, local = self.scene()
        current, goal = state(), (0., 0., 20.)
        support.begin(current['position'], 0.)
        context = dict(neighbours=[peer()])
        local.adjust(current, context, goal, goal, ('route',), lambda *args: True)
        current['now'] = 9.
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('route',), lambda *args: True))
        self.assertEqual('bypass_stalled', local.receipt['status'])
        for body in (peer(position=(0., 10., 20.)), peer(alive=True, team=2), peer(alive=True, speed=4.)):
            local.reset()
            self.assertEqual(goal, local.adjust(current, dict(neighbours=[body]), goal, goal,
                ('no_occupancy',), lambda *args: False, allow_lane=False))
            self.assertEqual('unchanged', local.receipt['status'])
        local.reset()
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('refused',), lambda *args: False))
        self.assertEqual('no_checked_bypass', local.receipt['status'])

    def test_retained_bypass_keeps_its_budget_when_pathfinder_returns_that_same_leg(self):
        unused, support, local = self.scene()
        current, goal = state(), (0., 0., 20.)
        context = dict(neighbours=[peer()])
        support.begin(current['position'], 0.)
        target = local.adjust(current, context, goal, goal, ('route',), lambda *args: True)
        current['now'] = 5.
        self.assertEqual(target, local.adjust(current, context, goal, target, ('route',), lambda *args: True))
        self.assertEqual('bypass_retained', local.receipt['status'])
        current['now'] = 9.
        local.adjust(current, context, goal, target, ('route',), lambda *args: True)
        self.assertEqual('bypass_stalled', local.receipt['status'])
        self.assertIsNone(local.leg)

    def test_endpoint_occupancy_uses_destination_floor_on_a_hill_not_current_height(self):
        unused, support, local = self.scene()
        current, goal = state(), (0., 4., 20.)
        support.begin(current['position'], 0.)
        bodies = local._bodies(current, dict(neighbours=[peer(position=goal)]))
        self.assertEqual(1, len(bodies))
        self.assertTrue(local._occupied(goal, bodies, math.hypot(2., 1.), current))
        self.assertFalse(local._occupied((0., 0., 20.), bodies, math.hypot(2., 1.), current))

    def test_local_lane_uses_observed_teammates_not_global_queue_and_keeps_two_finite_legs(self):
        unused, support, local = self.scene()
        current, goal = state(), (0., 0., 40.)
        context = dict(neighbours=[peer(position=(0., 0., 14.), alive=True, speed=2.)])
        support.begin(current['position'], 0.)
        entry = local.adjust(current, context, goal, goal, ('route',), lambda *args: True)
        self.assertEqual('observed_lane', local.receipt['status'])
        self.assertGreater(entry[0], 0.)
        self.assertEqual('entry', local.receipt['phase'])
        current['now'] = 1.
        self.assertEqual(entry, local.adjust(current, context, goal, goal, ('route',), lambda *args: True))
        current.update(now=2., position=entry)
        support.begin(entry, 2.)
        exit_point = local.adjust(current, context, goal, goal, ('route',), lambda *args: True)
        self.assertEqual('passing', local.receipt['phase'])
        self.assertGreater(exit_point[2], 14.)
        current.update(now=3., position=exit_point)
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('route',), lambda *args: True))
        self.assertIsNone(local.lane)

    def test_ford_and_native_proof_refusal_cannot_be_widened_into_a_lane(self):
        nav, support, local = self.scene()
        current, goal = state(), (0., 0., 40.)
        context = dict(neighbours=[peer(position=(0., 0., 14.), alive=True, speed=2.)])
        support.begin(current['position'], 0.)
        nav.player_states[17]['controlled_shallow_target'] = goal
        self.assertEqual(goal, local.adjust(current, context, goal, goal, ('ford',), lambda *args: True))
        nav.player_states[17].clear()
        with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False):
            self.assertEqual(goal, local.adjust(current, context, goal, goal, ('lane',), lambda *args: True))

    def test_local_proofs_use_and_restore_only_this_players_boundary(self):
        nav, support, local = self.scene()
        current, goal = state(), (0., 0., 20.)
        support.begin(current['position'], 0.)
        nav._boundary_actor = 90
        def proof(*unused):
            self.assertEqual(17, nav._boundary_actor)
            return True
        with mock.patch.object(nav.grid, 'dry_segment_clear', side_effect=proof):
            local.adjust(current, dict(neighbours=[peer()]), goal, goal, ('route',), lambda *args: True)
        self.assertEqual(90, nav._boundary_actor)


class PlayerRouteIntegrationTests(unittest.TestCase):
    def test_player_constructor_uses_private_algorithms_and_static_observation_entry(self):
        world = graph()
        owner = SimpleNamespace(_start_message=dict(map='04_himmelsdorf'),
            client=SimpleNamespace(team=1), _arena_bounds=world['bounds'],
            _navigation_ground=lambda *args: 0., _navigation_obstacle=lambda *args: False)
        descriptor = SimpleNamespace(type=SimpleNamespace(tags=['heavyTank']))
        with mock.patch.object(prebaked_navigation, 'load_graph', return_value=world), \
             mock.patch.object(prebaked_navigation, 'clip_graph_to_arena'), \
             mock.patch.object(prebaked_navigation, 'with_shore_hazards', side_effect=lambda value: value), \
             mock.patch.object(native_navigation_query.Oracle, 'create', return_value=None):
            nav = navigation.PlayerNavigation(owner, descriptor)
        self.addCleanup(nav.close)
        self.assertIsInstance(nav.navigator, PlayerPathfinder)
        self.assertIsInstance(nav.navigator.grid, PlayerTerrainGrid)
        nav.set_context(dict(neighbours=[peer()], turret_hulls=[(-20, 20., 20., 0., 1., 1.)]))
        nav.movement_policy(state())
        self.assertEqual(2, len(nav.navigator.grid._static_hulls))

    def test_only_actual_endpoint_brakes_not_intermediate_route_or_astar_tip(self):
        nav = controller()
        current = state(position=(0., 0., 0.), speed=8.)
        current.update(stopping_distance=20., decision_horizon=.1)
        goal = (0., 0., 15.)
        route = nav._drive_goal(current, lambda *args: True, goal, ('route',), mode='route')
        self.assertFalse(route['brake'])
        command = nav._drive_goal(current, lambda *args: True, goal, ('mission',), mode='return_base')
        self.assertTrue(command['brake'])
        with mock.patch.object(nav.navigator, 'next_target', return_value=(0., 0., 8.)):
            command = nav._drive_goal(current, lambda *args: True, goal, ('mission',), mode='return_base')
            self.assertFalse(command['brake'])
        self.assertTrue(nav.drive_combat_goal(current, lambda *args: True, goal)['brake'])

    def test_every_travel_owner_reaches_traffic_coordination_even_when_driver_brakes(self):
        nav = controller()
        current = dict(state(speed=8.), stopping_distance=20., decision_horizon=.1)
        for mode in ('joining', 'return_base', 'base_capture', 'base_defence', 'attack',
                     'hold_position', 'parking_approach', 'artillery_deploy', 'artillery_relocate',
                     'firing_position', 'reload_withdraw', 'flank'):
            order = nav._drive_goal(current, lambda *args: True, (0., 0., 10.),
                                    ('travel', mode), mode=mode, end_point=True)
            self.assertTrue(order['brake'])
            self.assertTrue(order['travel_intent'], mode)
            held = nav._drive_goal(current, lambda *args: True, current['position'],
                                   ('held', mode), mode=mode, hold=True)
            self.assertFalse(held['travel_intent'], mode)
        reverse = nav._cover_motion(state(), lambda *args: True, (0., 0., -5.), 'return')
        self.assertTrue(reverse['travel_intent'])
        self.assertFalse(nav._cover_order('cover_hold', (0., 0., -5.))['travel_intent'])

    def test_fixed_and_authored_holds_are_protected_but_automatic_support_hold_can_yield(self):
        nav = controller()
        nav.start_mission('hold_position', {}, state())
        self.assertTrue(nav.decide(state(), lambda *args: True)['traffic_hold_protected'])
        nav = controller()
        parking = nav._drive_goal(state(), lambda *args: True, (0., 0., 0.),
                                  ('parking',), hold=True, mode='parking_hold')
        self.assertTrue(parking['traffic_hold_protected'])
        support = nav._drive_goal(state(), lambda *args: True, (0., 0., 0.),
                                  ('support',), hold=True, mode='support_hold')
        self.assertFalse(support['traffic_hold_protected'])

    def test_admitted_healthy_cover_does_not_abort_active_burst(self):
        nav = controller()
        entity = SimpleNamespace(typeDescriptor=SimpleNamespace(maxHealth=1000), health=1000)
        gun = SimpleNamespace(clip_size=1, clip=1, reload_time=0.)
        target = SimpleNamespace(id=4, position=(0., 0., 40.))
        nav.set_context(dict(fire_clear=True, gun_ready=True, fire_seq=0))
        # State-machine seam: real whole-body and multi-threat admission is
        # exercised by test_player_cover_independence's production consumer.
        nav._cover_candidate = lambda pose, target, entity, clear, ray: dict(
            target=target.id, goal=(0., 0., -5.), peek=(0., 0., 0.))
        nav.cover_search.current_exposure = lambda *args: 0.
        nav.cover_search.peek_clear = lambda *args: True
        ray = lambda unused, endpoint: endpoint[2] >= 0.
        order = nav.withdrawal(state(0.), target, entity, gun, lambda *args: True, ray)
        self.assertEqual('combat_cover', nav.cover_move['reason'])
        self.assertLess(order['throttle'], 0.)
        nav.withdrawal(state(1., (0., 0., -5.)), target, entity, gun, lambda *args: True, ray)
        nav.withdrawal(state(2.1, (0., 0., -5.)), target, entity, gun, lambda *args: True, ray)
        nav.set_context(dict(fire_clear=True, gun_ready=False, fire_seq=1, burst_active=True))
        order = nav.withdrawal(state(3.), target, entity, gun, lambda *args: True, ray)
        self.assertEqual('cover_peek', order['combat_mode'])
        self.assertEqual('peek', nav.cover_move['phase'])
        nav.set_context(dict(fire_clear=True, gun_ready=False, fire_seq=1, burst_active=False))
        order = nav.withdrawal(state(3.1), target, entity, gun, lambda *args: True, ray)
        self.assertEqual('cover_return', order['combat_mode'])

    def test_no_cover_clip_retreat_uses_a_visited_route_anchor_and_recovers_when_loaded(self):
        nav = controller()
        nav.route_history = [(0., 0., -12.)]
        entity = SimpleNamespace(typeDescriptor=SimpleNamespace(maxHealth=1000), health=1000)
        gun = SimpleNamespace(clip_size=3, clip=0, reload_time=20.)
        target = SimpleNamespace(id=4, position=(0., 0., 40.))
        order = nav.withdrawal(state(), target, entity, gun, lambda *args: True, lambda *args: True)
        self.assertEqual('reload_withdraw', order['combat_mode'])
        self.assertEqual((0., 0., -12.), order['reload_retreat']['goal'])
        order = nav.withdrawal(state(1., (0., 0., -12.)), None, entity, gun,
                               lambda *args: True, lambda *args: True)
        self.assertTrue(order['brake'])
        self.assertEqual('reload_route_hold', order['combat_mode'])
        gun.clip, gun.reload_time = 3, 0.
        self.assertIsNone(nav.withdrawal(state(2., (0., 0., -12.)), None, entity, gun,
                                        lambda *args: True, lambda *args: True))
        self.assertIsNone(nav.reload_route)

    def test_cover_and_reload_retreat_never_override_fixed_commands_or_total_no_ammo(self):
        entity = SimpleNamespace(typeDescriptor=SimpleNamespace(maxHealth=1000), health=1000)
        gun = SimpleNamespace(clip_size=3, clip=0, reload_time=20.)
        target = SimpleNamespace(id=4, position=(0., 0., 40.))
        for fixed in (True, False):
            nav = controller()
            if fixed:
                nav.start_mission('return_base', {}, state())
            else:
                nav.set_context(dict(empty_ammo=True))
            nav.route_history = [(0., 0., -12.)]
            self.assertIsNone(nav.withdrawal(state(), target, entity, gun,
                                            lambda *args: True, lambda *args: False))
            self.assertIsNone(nav.cover_move)
            self.assertIsNone(nav.reload_route)

    def test_no_cover_without_travel_evidence_cannot_invent_a_retreat_anchor(self):
        nav = controller()
        entity = SimpleNamespace(typeDescriptor=SimpleNamespace(maxHealth=1000), health=1000)
        gun = SimpleNamespace(clip_size=3, clip=0, reload_time=20.)
        target = SimpleNamespace(id=4, position=(0., 0., 40.))
        self.assertIsNone(nav.withdrawal(state(), target, entity, gun,
                                        lambda *args: True, lambda *args: True))
        self.assertIsNone(nav.reload_route)


if __name__ == '__main__':
    unittest.main()
