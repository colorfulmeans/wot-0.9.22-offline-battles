"""Engine-free contracts executed in both Python 3 and the real 2.7 gate.

Load the exact helper sources without requiring stock #1513 GUI packages.
This is interpreter/logic evidence, not a native-client acceptance run.
"""
from __future__ import print_function
import os
import importlib
import sys
import types
import unittest


BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'res', 'scripts', 'client', 'gui', 'mods',
                    'offline_lan_0922', 'player_control')


def load_helper(name):
    module = types.ModuleType('foreground_contract_' + name)
    path = os.path.join(BASE, name + '.py')
    with open(path, 'rb') as source:
        eval(compile(source.read(), path, 'exec'), module.__dict__)
    return module


commands = load_helper('commands')
receipts = load_helper('shot_receipts')
settling = load_helper('settling')


class EmbeddedForegroundContractTests(unittest.TestCase):
    def test_explicit_native_command_schema_and_unicode_holder_on_python27(self):
        self.assertEqual(42, commands.validate_action('aim_target',
            dict(target_id=42))['target_id'])
        point = commands.validate_action('aim_point',
            dict(position=[20., 1., 100.], tolerance_deg=.5))
        self.assertEqual([20., 1., 100.], list(point['position']))
        holder = commands.validate_action('release_aim', dict(command_id=u'\u6301\u6709'))
        self.assertEqual(u'\u6301\u6709', holder['command_id'])
        self.assertEqual('engineHealth', commands.validate_action('use_equipment',
            dict(equipment_id=4, target='engineHealth'))['target'])
        self.assertIs(True, commands.validate_action('set_siege', dict(enabled=True))['enabled'])
        for action, args in (
                ('aim_target', dict(target_id=True)),
                ('aim_point', dict(position=[float('nan'), 1., 2.])),
                ('use_equipment', dict(equipment_id=False)),
                ('use_equipment', dict(equipment_id=4, target='unknown')),
                ('set_siege', dict(enabled=1))):
            with self.assertRaises(ValueError):
                commands.validate_action(action, args)

    def test_explicit_command_default_deadlines_are_not_admission_deadlines(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        for action, args, timeout in (
                ('aim_target', dict(target_id=42), 30.),
                ('aim_point', dict(position=[20., 1., 100.]), 30.),
                ('release_aim', {}, 10.),
                ('use_equipment', dict(equipment_id=12, active=True), 30.),
                ('set_siege', dict(enabled=False), 30.)):
            gateway = commands.CommandGateway(lambda: identity, lambda row: True,
                lambda command, now: None, lambda command: None,
                lambda command, reason: None, wall_clock=lambda: 1000.)
            request = dict(identity, id=action, action=action, args=args, expires_at=1002.)
            result = gateway.submit(request, 3.)
            self.assertEqual('accepted', result['status'])
            self.assertEqual(3. + timeout, gateway.requests[action]['deadline'])
            gateway.tick(3. + timeout)
            self.assertEqual('command_timeout', gateway.requests[action]['receipt']['reason'])

    def test_identity_is_rechecked_after_native_preflight_on_python27(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        executed = []
        def preflight(command):
            identity['round_id'] = 2
        gateway = commands.CommandGateway(lambda: identity, lambda row: True,
            lambda command, now: executed.append(command), preflight,
            lambda command, reason: None, wall_clock=lambda: 1000.)
        request = dict(identity, id='mode', action='set_siege',
                       args=dict(enabled=True), expires_at=1002.)
        result = gateway.submit(request, 0.)
        self.assertEqual(('rejected', 'identity_changed'), (result['status'], result['reason']))
        self.assertEqual([], executed)
        self.assertFalse(commands.same_identity(dict(player_id=1), dict(player_id=True)))
        self.assertFalse(commands.same_identity(dict(player_id=1), dict(player_id=1.)))

    def test_unicode_native_failure_keeps_the_original_error_and_terminal_cleanup(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        cancelled = []
        failure = RuntimeError(u'\u539f\u751f\u9519\u8bef')
        def execute(command, now):
            raise failure
        gateway = commands.CommandGateway(lambda: identity, lambda row: True,
            execute, lambda command: None,
            lambda command, reason: cancelled.append(reason), wall_clock=lambda: 1000.)
        request = dict(identity, id='fire', action='fire', args={}, expires_at=1002.)
        with self.assertRaises(RuntimeError) as raised:
            gateway.submit(request, 0.)
        self.assertIs(failure, raised.exception)
        self.assertEqual('execution_error', gateway.requests['fire']['receipt']['reason'])
        self.assertEqual(['execution_error'], cancelled)

    def test_unicode_lookup_and_effect_ids_are_not_ascii_coerced(self):
        args = commands.validate_action('assert_state',
            dict(condition='shot_terminal', projectile_id=u'\u4e2d'))
        ledger = receipts.ShotReceipts()
        self.assertIsNone(ledger.get(args['projectile_id']))
        ledger.committed(dict(projectile_id=u'\u4e2d'), {}, {}, 0., 1)
        event = dict(projectile_id=u'\u4e2d', event_id=u'\u6548\u679c', damage=10)
        self.assertEqual(10., ledger.hit(event, 1.)['damage_total'])
        self.assertIsNone(ledger.hit(event, 1.))
        self.assertEqual(u'\u62d2\u7edd', ledger.rejected(u'\u4e2d', u'\u62d2\u7edd', 2.)['reason'])

    def test_unicode_readonly_request_is_acknowledged_without_callback_failure(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        rows = []
        ledger = receipts.ShotReceipts()
        def emit(row):
            rows.append(row)
            return True
        def execute(command, now):
            self.assertIsNone(ledger.get(command['args']['projectile_id']))
            return dict(status='failed', reason='observation_unavailable')
        gateway = commands.CommandGateway(lambda: identity, emit, execute,
            lambda command: None, lambda command, reason: None, wall_clock=lambda: 1000.)
        request = dict(identity, id=u'\u67e5\u8be2', action='assert_state',
            args=dict(condition='shot_terminal', projectile_id=u'\u4e2d'), expires_at=1002.)
        result = gateway.submit(request, 0.)
        self.assertEqual('observation_unavailable', result['reason'])
        self.assertEqual(['accepted', 'failed'], [row['status'] for row in rows])
        self.assertEqual(result, gateway.submit(request, 1.))

    def test_suspension_motion_prevents_false_full_body_rest(self):
        owner = types.ModuleType('observed_body')
        owner._local_speed = owner._local_turn_speed = owner._local_vertical_speed = 0.
        owner._local_pitch = owner._local_roll = 0.
        owner._local_suspension_pitch_velocity = owner._local_suspension_roll_velocity = 0.
        owner._local_air_lateral = (0., 0.)
        owner._local_airborne = owner._local_support_rise_blocked = False
        owner._overturn_level = 0
        owner.local_pose = lambda: ((0., 0., 0.), 0.)
        rest = settling.HaltObservation()
        self.assertFalse(rest.observe(owner, 0.))
        owner._local_pitch, owner._local_roll = .15, .12
        self.assertFalse(rest.observe(owner, .6))
        owner._local_suspension_pitch_velocity = .1
        self.assertFalse(rest.observe(owner, 1.2))
        owner._local_suspension_pitch_velocity = 0.
        self.assertFalse(rest.observe(owner, 1.3))
        self.assertTrue(rest.observe(owner, 1.9))


class EmbeddedIndependentRuntimeTests(unittest.TestCase):
    """Import the real package modules with only the stock GUI/native seam.

    CPython 2 does not provide the game's GUI namespace packages. Install that
    namespace explicitly, but execute the actual player and neutral primitive
    modules. No Bot import, stand-in pathfinder or substituted height algorithm
    is allowed. Native C++ is explicitly unavailable in this engine-free gate;
    the shipped Python fallback and real import closure must still work.
    """
    def setUp(self):
        self.saved_gui = dict((name, module) for name, module in sys.modules.items()
                              if name == 'gui' or name.startswith('gui.'))
        for name in self.saved_gui:
            del sys.modules[name]
        self.addCleanup(self.restore_namespace)
        class NoBotPolicy(object):
            @staticmethod
            def reject(fullname):
                prefix = 'gui.mods.offline_lan_0922.'
                if not fullname.startswith(prefix):
                    return
                leaf = fullname.rsplit('.', 1)[-1]
                if (fullname == prefix + 'ai' or fullname.startswith(prefix + 'ai.') or
                        leaf in ('bots', 'lan_client') or
                        leaf.startswith('bot_') and leaf != 'bot_tactics_default_data'):
                    raise ImportError('foreground imported Bot/network owner: ' + fullname)

            def find_module(self, fullname, path=None):
                self.reject(fullname)
                return None

            def find_spec(self, fullname, path=None, target=None):
                self.reject(fullname)
                return None
        guard = NoBotPolicy()
        sys.meta_path.insert(0, guard)
        self.addCleanup(sys.meta_path.remove, guard)
        package_root = os.path.dirname(BASE)
        mods_root = os.path.dirname(package_root)
        for name, path in (('gui', os.path.dirname(mods_root)),
                           ('gui.mods', mods_root),
                           ('gui.mods.offline_lan_0922', package_root),
                           ('gui.mods.offline_lan_0922.player_control', BASE)):
            package = types.ModuleType(name)
            package.__path__ = [path]
            package.__package__ = name
            sys.modules[name] = package
            if '.' in name:
                parent, child = name.rsplit('.', 1)
                setattr(sys.modules[parent], child, package)
        native = importlib.import_module('gui.mods.offline_lan_0922.native_math')
        native._backend, native._attempted = None, True
        diagnostics = importlib.import_module(
            'gui.mods.offline_lan_0922.native_input_diagnostics')
        diagnostics.write_json_record = lambda *args, **kwargs: None
        self.modules = dict((name, importlib.import_module(
            'gui.mods.offline_lan_0922.player_control.' + name)) for name in (
                'pathfinding', 'local_height', 'local_routes', 'navigation_support',
                'observations', 'targeting', 'tactics', 'fire_admission', 'cover',
                'traffic', 'route_catalog', 'sortie'))

    def restore_namespace(self):
        for name in list(sys.modules):
            if name == 'gui' or name.startswith('gui.'):
                del sys.modules[name]
        sys.modules.update(self.saved_gui)

    @staticmethod
    def graph():
        size, cell, origin = 31, 2., -30.
        links = []
        directions = ((-1, -1), (0, -1), (1, -1), (-1, 0),
                      (1, 0), (-1, 1), (0, 1), (1, 1))
        for z in range(size):
            for x in range(size):
                mask = 0
                for bit, (dx, dz) in enumerate(directions):
                    if 0 <= x + dx < size and 0 <= z + dz < size:
                        mask |= 1 << bit
                links.append(mask)
        return dict(format='offline-lan-0922-navgraph', version=2,
            width=size, height=size, origin=[origin, origin],
            bounds=[-30., -30., 30., 30.], cell_size=cell,
            heights_mm=[0] * (size * size), links=links,
            hazards=[0] * (size * size))

    def pathfinder(self):
        result = self.modules['pathfinding'].PlayerPathfinder(
            lambda *args: 0., lambda *args: False, baked_graph=self.graph())
        self.addCleanup(result.close)
        return result

    def test_all_new_modules_import_without_bot_or_game_runtime(self):
        for name, module in self.modules.items():
            self.assertEqual(os.path.join(BASE, name + '.py'), module.__file__.rstrip('co'))
        forbidden = [name for name in sys.modules if
            name == 'gui.mods.offline_lan_0922.ai' or
            name.startswith('gui.mods.offline_lan_0922.ai.') or
            name == 'gui.mods.offline_lan_0922.bot_runtime']
        self.assertEqual([], forbidden)
        self.assertEqual((object,), self.modules['pathfinding'].PlayerPathfinder.__bases__)
        self.assertEqual((object,), self.modules['pathfinding'].PlayerTerrainGrid.__bases__)
        self.assertEqual((object,), self.modules['local_height'].PlayerLocalHeightLinks.__bases__)

    def test_spent_traffic_lease_releases_and_only_real_reentry_rearms_on_python27(self):
        import math
        module = self.modules['traffic']
        shape = (1., 2., 0., 2.)
        player = module.PlayerTraffic()
        own = dict(id=1002, engine_id=2, position=(0., 0., 0.), yaw=0., speed=0.,
                   half_width=1., half_length=2., decision_horizon=.1)
        peer = dict(id=1, position=(0., 0., 4.3), yaw=math.pi,
                    velocity=(0., 0., 0.), alive=True, team=1, collision_shape=shape)
        def advance(now, clear):
            own['now'] = now
            command = dict(throttle=1., turn=0., brake=False, holding=False,
                travel_intent=True, combat_mode='route', recovery_mode='travel',
                local_target=(0., 0., 30.))
            traffic = module.Traffic(module.body(2, own['position'], 0., shape), [peer])
            player.apply(command, own, traffic, 1,
                lambda *args: clear, lambda: 0., 1./30., False, None)
            return command
        self.assertEqual('head_on_blocked', advance(0., False)['traffic_mode'])
        self.assertEqual('head_on_retreat', advance(1.6, False)['recovery_mode'])
        for now in (8., 100., 1000.):
            result = advance(now, True)
            self.assertEqual('finished', result['traffic_control']['phase'])
            self.assertNotEqual('head_on_retreat', result['recovery_mode'])
            self.assertNotIn('suppress_fire', result)
        peer['position'] = (10., 0., 4.3)
        advance(1001., True)
        self.assertFalse(player.pairs)
        peer['position'] = (0., 0., 4.3)
        self.assertEqual('head_on_blocked', advance(1002., False)['traffic_mode'])

    def test_default_map_is_readonly_and_each_player_gets_private_rows_on_python27(self):
        import copy
        catalog = self.modules['route_catalog']
        name = '02_malinovka'
        profile = dict(name='DEFAULT', maps={name: dict(
            routes=[], positions=[], default_routes=[])})
        original = copy.deepcopy(profile)
        expected = catalog.packaged_map(name)
        first = catalog.map_settings(profile, name)
        second = catalog.map_settings(profile, name)
        self.assertEqual(expected, first)
        self.assertEqual(expected, second)
        first['default_routes'][0]['points'][0][0] += 100.
        first['positions'].append(dict(id='player-only', point=[0., 0.]))
        self.assertNotEqual(first, second)
        self.assertEqual(expected, second)
        self.assertEqual(expected, catalog.map_settings(profile, name))
        self.assertEqual(original, profile)

    def test_stalled_sortie_and_unchanged_shot_reach_bounded_terminal_on_python27(self):
        module = self.modules['sortie']
        progress = module.SortieProgress()
        route = dict(id='local-sortie', waypoints=[[-100., 0., 0], [-50., 0., 0],
                                                   [0., 0., 0], [0., 100., 0]])
        home = dict(point=(-100., 0.), radius=10.)
        phases = set()
        for now in range(201):
            # The caller repeatedly supplies the original cursor and keeps
            # aiming, but neither is evidence of motion or another shot.
            result = progress.update(route, 2,
                dict(now=float(now), position=(-70., 0., 0.)), home,
                lambda *args: False, aiming=True, sequence=7)
            phases.add(result['phase'])
            if result.get('replace'):
                break
        self.assertLess(now, 150)
        self.assertEqual('home_progress_timeout', result['reason'])
        self.assertTrue(result['replace'])
        self.assertNotIn('complete', result)
        self.assertEqual(set(('forward', 'skip', 'return', 'home')), phases)
        self.assertEqual(module.MAX_AIM_PAUSE_SECONDS, result['aim_pause'])
        other = module.SortieProgress()
        unchanged = other.update(route, 2, dict(now=200., position=(-70., 0., 0.)),
                                 home, lambda *args: False)
        self.assertEqual(('forward', 2), (unchanged['phase'], unchanged['index']))
        progress.reset()
        self.assertIsNone(progress.identity)
        self.assertEqual(2, other.index)

    def test_neutral_projectile_rounding_keeps_half_even_and_signed_zero_on_python27(self):
        import math
        wire = importlib.import_module('gui.mods.offline_lan_0922.projectile_wire')
        # Exact binary fractions exercise both half-even tie directions;
        # relying on the host's built-in round would differ on Python 2.
        for value, expected in ((.0078125, .007812), (.0234375, .023438),
                                (-.0078125, -.007812), (-.0234375, -.023438)):
            self.assertEqual(expected, wire.round_scalar(value))
        for value in (0., -0., .0000001, -.0000001):
            actual = wire.round_scalar(value)
            self.assertEqual(0., actual)
            self.assertEqual(math.copysign(1., value), math.copysign(1., actual))
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaises((ValueError, OverflowError)):
                wire.round_scalar(value)

    def test_real_search_observed_wreck_and_private_close_on_python27(self):
        first, second = self.pathfinder(), self.pathfinder()
        support = self.modules['navigation_support'].PlayerHeightSupport(
            first.grid, lambda *args: 0., None)
        self.addCleanup(support.close)
        routes = self.modules['local_routes'].LocalRoutes(first, support, 1)
        current = dict(id=17, engine_id=77, position=(0., 0., -20.),
                       yaw=0., now=0., speed=0., half_length=3.5, half_width=1.5)
        routes.publish(current, dict(neighbours=[dict(id=9, alive=False,
            position=(0., 0., 0.), yaw=0., collision_shape=(1.5, 3.5, -.4, 2.))],
            turret_hulls=[(-90, 20., 0., 0., 2., 1.)]))
        self.assertEqual(2, routes.static_receipt['count'])
        self.assertGreater(first.grid.static_hull_revision, second.grid.static_hull_revision)
        self.assertTrue(first.grid.segment_penalty((0., 0., -20.), (0., 0., 20.), 0.))
        search = first.grid.begin_plan((0., 0., -20.), (0., 0., 20.))
        for unused in range(8):
            if search.step(4096):
                break
        self.assertTrue(search.done)
        self.assertGreater(len(search.result), 2)
        self.assertFalse(first.grid.path_crosses_static_hull(search.result))
        first.close()
        self.assertTrue(first.closed)
        self.assertIsNone(first.grid.ground_probe)
        self.assertFalse(second.closed)
        other = second.grid.begin_plan((0., 0., -20.), (0., 0., 20.))
        for unused in range(8):
            if other.step(4096):
                break
        self.assertTrue(other.done)
        self.assertGreater(len(other.result), 1)

    def test_actual_multilayer_links_and_budget_are_not_a_height_stub(self):
        calls = []
        def columns(x, z, low, high):
            calls.append((x, z, low, high))
            return dict(status='complete', generation=('scene', 1), surfaces=[
                dict(point=(x, 0., z), normal=(0., 1., 0.)),
                dict(point=(x, 8., z), normal=(0., 1., 0.))])
        links = self.modules['local_height'].PlayerLocalHeightLinks(columns)
        links.begin((0., 0., 0.), now=0.)
        status, point = links.inspect((0., 0., 0.), (0., 8., 4.), baked_start=8.)
        self.assertEqual('other_surface', status)
        self.assertEqual((0., 0., 4.), point)
        self.assertTrue(calls)
        self.assertLessEqual(links.queries, self.modules['local_height'].MAX_COLUMNS)
        count = len(calls)
        self.assertEqual(('connected', point), links.inspect((0., 0., 0.), point))
        self.assertEqual(count, len(calls))

    def test_visible_priority_public_roster_and_tactics_execute_on_python27(self):
        selection = self.modules['targeting'].TargetSelection()
        rows = [dict(id=8, position=(0., 0., 200.), alive=True, visible=True,
                     health=1000, max_health=1000),
                dict(id=9, position=(0., 0., 25.), alive=True, visible=True,
                     health=1000, max_health=1000)]
        self.assertEqual(([9, 8], True), selection.rank(rows, (0., 0., 0.), 8, 0.))
        owner = types.ModuleType('visible_client')
        owner.client = types.ModuleType('public_identity')
        owner.client.team, owner.client.player_id = 1, 7
        owner._start_message = dict(round_id=1, players=[dict(id=7, team=1),
                                                       dict(id=8, team=1)], bots=[])
        owner._records, owner._last_snapshot = {}, {}
        allies, complete = self.modules['observations'].public_allies(owner, [])
        self.assertTrue(complete)
        self.assertEqual('player:8', allies[0]['id'])
        self.assertTrue(allies[0]['alive'])
        self.assertNotIn('position', allies[0])
        tactics = self.modules['tactics'].CombatTactics()
        state = dict(now=0., position=(0., 0., 0.), yaw=0., speed=0., id=1,
                     engine_id=1, health=1000., max_health=1000.)
        descriptor = dict(type=dict(tags=('heavyTank',)), hull=dict(primaryArmor=(120., 80., 60.)))
        angle = tactics.facing(state, rows[0], descriptor)
        self.assertIsNotNone(angle)
        self.assertEqual(angle, tactics.facing(dict(state, now=1.), rows[0], descriptor))

    def test_fire_candidate_random_draw_and_flight_limit_execute_on_python27(self):
        module = self.modules['fire_admission']
        draw = module._ScatterDraw()
        first = (draw.uniform(-1., 1.), draw.uniform(3., 5.), draw.gauss(2., .5))
        draw.cursor = 0
        self.assertEqual(first, (draw.uniform(-1., 1.), draw.uniform(3., 5.), draw.gauss(2., .5)))
        path, times = module.FireAdmission._launch_path((0., 0., 0.), (100., 0., 0.), 0., 25.)
        self.assertAlmostEqual(25., path[-1][0], places=6)
        self.assertAlmostEqual(.25, times[-1], places=6)
        self.assertLessEqual(len(path), module.MAX_PROOF_CHORDS + 1)
        self.assertEqual(((), ()), module.FireAdmission._launch_path(
            (0., 0., 0.), (0., 0., 0.), 0., 25.))

    def test_real_cover_search_uses_native_angles_body_samples_and_rank_on_python27(self):
        import math
        class Record(object):
            def __init__(self, **values):
                self.__dict__.update(values)
        descriptor = dict(chassis=dict(hullPosition=(0., 0., 0.)),
            hull=dict(hitTester=dict(bbox=((-1., 0., -2.), (1., 1.4, 2.))),
                      turretPositions=((0., 1.4, 0.),)),
            turret=dict(hitTester=dict(bbox=((-0.7, 0., -1.), (.7, 1., 1.))),
                        gunPosition=(0., .3, 0.)),
            gun=dict(turretYawLimits=None, staticTurretYaw=None,
                     pitchLimits=dict(minPitch=((0., -.5), (2.*math.pi, -.5)),
                                      maxPitch=((0., .5), (2.*math.pi, .5)))))
        target = Record(id=9, typeDescriptor=descriptor, position=(0., 0., 40.),
            isStarted=True, isAlive=lambda: True, getAimParams=lambda: (.2, -.1),
            matrix=Record(yaw=0., pitch=0., roll=0.))
        own = Record(id=77, typeDescriptor=descriptor)
        owner = Record(client=Record(player_id=17, team=1),
            _avatar=Record(spaceID=1, gunRotator=Record(turretYaw=.1, gunPitch=.05)),
            _start_message=dict(round_id=1),
            _records={'target': dict(engine_id=9, ready=True, spot_visible=True, state=dict(team=2))},
            _server_entity=lambda identity: target if identity == 9 else None)
        context = dict(contacts=[dict(id=9, visible=True, alive=True, health=1000.,
            position=target.position, yaw=0., pitch=0., roll=0.)], supported=True)
        state = dict(now=0., position=(0., 0., 0.), yaw=0., pitch=0., roll=0.,
                     half_width=1., half_length=2., engine_id=77)
        sampler = self.modules['cover'].PlayerCover(owner)
        self.addCleanup(sampler.close)
        rays = []
        def ray(start, end):
            rays.append((start, end))
            return end[2] >= -4. if start[2] > 30. else True
        result = None
        for index in range(20):
            state['now'] = index*.1
            result = sampler.update(state, context, target, own,
                lambda *args: 0., lambda *args: 0., lambda *args: True, ray, scene=lambda: 1)
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertEqual((9,), result['threats'])
        self.assertEqual(4, len(self.modules['cover'].body_samples(descriptor)))
        self.assertIn('enemy_occlusion', result['breakdown'])
        self.assertTrue(result['peek_feasible'])
        self.assertLessEqual(sampler.receipt['queries'], sampler.receipt['query_limit'])
        observed = sampler.observe(state, context, target)[0]
        self.assertEqual((.2, -.1), (observed['pose']['turret_yaw'], observed['pose']['gun_pitch']))
        self.assertTrue(any(abs(first[1]-1.7) < 1.e-9 for first, unused in rays))


if __name__ == '__main__':
    unittest.main()
