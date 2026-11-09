"""Engine-free contracts executed in both Python 3 and the real 2.7 gate.

Load the exact helper sources without requiring stock #1513 GUI packages.
This is interpreter/logic evidence, not a native-client acceptance run.
"""
from __future__ import print_function
import collections
import os
import importlib
import sys
import types
import unittest


BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'res', 'scripts', 'client', 'gui', 'mods',
                    'offline_lan_0922', 'vehicle_control')


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


class EmbeddedSharedImportOrderTests(unittest.TestCase):
    """Cold imports and their support consumers must run in Python 2.7."""

    def setUp(self):
        self.saved_gui = dict((name, module) for name, module in sys.modules.items()
                              if name == 'gui' or name.startswith('gui.'))
        for name in self.saved_gui:
            del sys.modules[name]
        self.addCleanup(self.restore_namespace)
        package_root = os.path.dirname(BASE)
        mods_root = os.path.dirname(package_root)
        for name, path in (('gui', os.path.dirname(mods_root)),
                           ('gui.mods', mods_root),
                           ('gui.mods.offline_lan_0922', package_root),
                           ('gui.mods.offline_lan_0922.vehicle_control', BASE)):
            package = types.ModuleType(name)
            package.__path__ = [path]
            package.__package__ = name
            sys.modules[name] = package
            if '.' in name:
                parent, child = name.rsplit('.', 1)
                setattr(sys.modules[parent], child, package)

    def restore_namespace(self):
        for name in list(sys.modules):
            if name == 'gui' or name.startswith('gui.'):
                del sys.modules[name]
        sys.modules.update(self.saved_gui)

    def test_engine_boundary_does_not_import_its_partially_defined_owner(self):
        owner_name = 'gui.mods.offline_lan_0922.bot_runtime'
        class NoPhysicalOwnerDuringBoundaryImport(object):
            def find_module(self, fullname, path=None):
                if fullname == owner_name:
                    raise ImportError('engine boundary re-entered its owner')
                return None

            def find_spec(self, fullname, path=None, target=None):
                if fullname == owner_name:
                    raise ImportError('engine boundary re-entered its owner')
                return None
        guard = NoPhysicalOwnerDuringBoundaryImport()
        sys.meta_path.insert(0, guard)
        self.addCleanup(sys.meta_path.remove, guard)
        engine = importlib.import_module(
            'gui.mods.offline_lan_0922.vehicle_control.engine_control')
        self.assertTrue(hasattr(engine, 'SharedEngineControl'))
        self.assertNotIn(owner_name, sys.modules)

    def check_live_types(self, first):
        prefix = 'gui.mods.offline_lan_0922.'
        importlib.import_module(prefix + first)
        runtime = importlib.import_module(prefix + 'bot_runtime')
        engine = importlib.import_module(prefix + 'vehicle_control.engine_control')
        combat = importlib.import_module(prefix + 'vehicle_control.combat_control')
        player = importlib.import_module(prefix + 'vehicle_control.full_runtime')
        worker = importlib.import_module(prefix + 'vehicle_control.bot_binding')
        self.assertTrue(issubclass(runtime.BotRuntime, engine.SharedEngineControl))
        # Python 2 wraps a class function in a fresh unbound-method object on
        # each access. Compare its function, not that transient wrapper.
        def function(method):
            return getattr(method, 'im_func', method)
        self.assertIs(function(runtime.BotRuntime._cadenced_ballistic_solution),
                      function(engine.SharedEngineControl._cadenced_ballistic_solution))
        for binding in (player.FullPlayerRuntime, worker.BotControlBinding):
            self.assertTrue(issubclass(binding, combat.CombatControl))
            self.assertIs(function(binding._ordinary_firing_order),
                          function(combat.CombatControl._ordinary_firing_order))

    def test_physical_runtime_imports_before_shared_bindings(self):
        self.check_live_types('bot_runtime')

    def test_shared_combat_imports_before_physical_runtime(self):
        self.check_live_types('vehicle_control.combat_control')

    def check_profiled_support_solve(self, kind):
        prefix = 'gui.mods.offline_lan_0922.'
        battle_module = importlib.import_module(prefix + 'battle_runtime')
        geometry = importlib.import_module(prefix + 'vehicle_control.geometry')
        battle = battle_module.BattleRuntime()
        physical_reads = []

        def physical_clock():
            physical_reads.append(73.125)
            return 73.125

        battle._clock = physical_clock
        battle._stack_candidates = lambda actor: iter(())
        point = collections.namedtuple('SupportPoint', 'x y z')
        start, end = point(0., 2., 0.), point(0., -2., 0.)
        ground = (point(0., 0., 0.), point(0., 1., 0.))
        probes = []

        def terrain_probe(ray_start, ray_end, ground_filter):
            probes.append((ray_start, ray_end, ground_filter))
            return ground

        battle._collide_static_down = terrain_probe
        outer = dict(outer_solve=True)
        battle._stack_context = outer
        actor = dict(id=11, kind=kind, x=0., y=0., z=0.,
                     _stack_carrier=['bot', 12])
        # Do not supply or patch a profiling clock. The real cold-imported
        # BattleRuntime and shared geometry must resolve the Python 2 clock.
        previous = battle._stack_support_context(actor)
        try:
            self.assertIs(outer, previous)
            self.assertNotIn('_stack_carrier', actor)
            battle._stack_context['physics_dt'] = .125
            battle._stack_context['purpose'] = kind + '_vertical'
            batch = battle._stack_context['queries']
            for unused in range(2):
                self.assertIs(ground, battle._collide_down(start, end, None))
            self.assertEqual([(start, end, None)], probes)
            self.assertEqual(1, batch.calls['candidate_select'])
            self.assertEqual(1, batch.calls['terrain'])
            self.assertEqual(1, batch.calls['terrain_cache_hit'])
            self.assertEqual(2, batch.calls['roof_stage'])
            self.assertIs(geometry._SUPPORT_PROFILE_CLOCK, batch.clock)
            self.assertIs(geometry._PROFILE_CLOCK, batch.clock)
            self.assertIs(battle_module._PROFILE_CLOCK, batch.clock)
            self.assertIsNot(physical_clock, batch.clock)
        finally:
            battle._finish_stack_support_context(previous)
        self.assertIs(outer, battle._stack_context)
        profile = battle._support_profiles[(kind, 11)]
        self.assertEqual(.125, profile['physics_dt'])
        self.assertEqual(73.125, profile['at'])
        self.assertEqual(1, profile['calls']['context_' + kind + '_vertical'])
        self.assertGreaterEqual(profile['ms']['context_total'], 0.)
        self.assertTrue(physical_reads)
        self.assertEqual(set([73.125]), set(physical_reads))

    def test_player_support_solve_runs_with_the_embedded_profile_clock(self):
        self.check_profiled_support_solve('player')

    def test_bot_support_solve_runs_with_the_embedded_profile_clock(self):
        self.check_profiled_support_solve('bot')

    def test_shared_geometry_lazily_opens_a_support_solve_on_python27(self):
        geometry = importlib.import_module(
            'gui.mods.offline_lan_0922.vehicle_control.geometry')
        owner = geometry.SharedBattleGeometry()
        actor = dict(id=11, kind='bot', x=0., y=0., z=0.)
        owner._stack_context = dict(actor=actor, candidates=[], hits=[])
        point = collections.namedtuple('SupportPoint', 'x y z')
        start, end = point(0., 2., 0.), point(0., -2., 0.)
        ground = (point(0., 0., 0.), point(0., 1., 0.))
        self.assertNotIn('queries', owner._stack_context)
        self.assertIs(ground, owner._stack_ground_hit(start, end, ground))
        batch = owner._stack_context['queries']
        self.assertEqual(1, batch.calls['roof_stage'])
        self.assertGreaterEqual(batch.milliseconds['roof_stage'], 0.)
        self.assertIs(geometry._PROFILE_CLOCK, batch.clock)
        self.assertIs(geometry._SUPPORT_PROFILE_CLOCK, batch.clock)


class EmbeddedSharedRuntimeTests(unittest.TestCase):
    """Import the real package modules with only the stock GUI/native seam.

    CPython 2 does not provide the game's GUI namespace packages. Install that
    namespace explicitly, but execute the sole shared vehicle behavior
    and neutral primitives. Retired copies and network owners, stand-in
    pathfinders and substituted height algorithms are forbidden. Native C++ is unavailable;
    the shipped Python fallback and real import closure must still work.
    """
    def setUp(self):
        self.saved_gui = dict((name, module) for name, module in sys.modules.items()
                              if name == 'gui' or name.startswith('gui.'))
        for name in self.saved_gui:
            del sys.modules[name]
        self.addCleanup(self.restore_namespace)
        class NoRetiredPolicy(object):
            @staticmethod
            def reject(fullname):
                prefix = 'gui.mods.offline_lan_0922.'
                if not fullname.startswith(prefix):
                    return
                root = fullname[len(prefix):].split('.', 1)[0]
                if root in ('player_control', 'bots', 'lan_client') or '.copied.' in fullname:
                    raise ImportError('shared control imported retired/network owner: ' + fullname)

            def find_module(self, fullname, path=None):
                self.reject(fullname)
                return None

            def find_spec(self, fullname, path=None, target=None):
                self.reject(fullname)
                return None
        guard = NoRetiredPolicy()
        sys.meta_path.insert(0, guard)
        self.addCleanup(sys.meta_path.remove, guard)
        package_root = os.path.dirname(BASE)
        mods_root = os.path.dirname(package_root)
        for name, path in (('gui', os.path.dirname(mods_root)),
                           ('gui.mods', mods_root),
                           ('gui.mods.offline_lan_0922', package_root),
                           ('gui.mods.offline_lan_0922.vehicle_control', BASE)):
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
        common = ('ai.navigation', 'ai.local_height', 'ai.traffic',
                  'bot_tactics', 'spg_route_recovery')
        shared = ('strategy', 'geometry', 'strategy_compat',
                  'trigger_admission', 'full_runtime')
        self.modules = dict((name, importlib.import_module(
            'gui.mods.offline_lan_0922.' + name)) for name in common)
        self.modules.update((name, importlib.import_module(
            'gui.mods.offline_lan_0922.vehicle_control.' + name)) for name in shared)

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
        result = self.modules['ai.navigation'].TerrainNavigator(
            lambda *args: 0., lambda *args: False, baked_graph=self.graph())
        self.addCleanup(result.close)
        return result

    def test_shared_modules_import_without_retired_or_network_runtime(self):
        for name, module in self.modules.items():
            root = BASE if name in ('strategy', 'geometry', 'strategy_compat',
                'trigger_admission', 'full_runtime') else os.path.dirname(BASE)
            self.assertEqual(os.path.join(root, *name.split('.')) + '.py',
                             module.__file__.rstrip('co'))
        forbidden = [name for name in sys.modules if
            name.startswith('gui.mods.offline_lan_0922.player_control') or
            '.copied.' in name or
            name == 'gui.mods.offline_lan_0922.lan_client']
        self.assertEqual([], forbidden)
        self.assertIn('gui.mods.offline_lan_0922.bot_runtime',
                      sys.modules)

    def test_spent_traffic_lease_releases_and_only_real_reentry_rearms_on_python27(self):
        import math
        module = self.modules['ai.traffic']
        player = module.TrafficCoordinator()
        own = dict(id=2, position=(0., 0., 0.), yaw=0.,
                   velocity=(0., 0., 0.), alive=True, team=1,
                   half_width=1.5, half_length=3.5)
        peer = dict(own, id=1, position=(0., 0., 7.5), yaw=math.pi)
        order = dict(throttle=1., turn=0., target_yaw=0.,
                     recovery_mode='drive', combat_mode='route')
        def advance(now, clear):
            return player.adjust(own['id'], own, order, [peer], now,
                                 lambda *args: clear)
        self.assertEqual('head_on_blocked', advance(0., False)['traffic_mode'])
        player.adjust(peer['id'], peer, dict(order, target_yaw=peer['yaw']),
                      [own], 0., lambda *args: False)
        self.assertEqual(order, advance(module.YIELD_SECONDS + .1, False))
        self.assertEqual('head_on_retreat',
                         advance(module.YIELD_SECONDS + .1, True)['traffic_mode'])
        for now in (module.YIELD_SECONDS + module.HEAD_ON_RETREAT_SECONDS, 100., 1000.):
            result = advance(now, True)
            self.assertEqual(order, result)
            self.assertNotIn('suppress_fire', result)
        peer['position'] = (20., 0., 7.5)
        advance(1001., True)
        self.assertFalse(player._pairs)
        peer['position'] = (0., 0., 7.5)
        self.assertEqual('head_on_blocked', advance(1002., False)['traffic_mode'])

    def test_default_map_is_readonly_and_each_player_gets_private_rows_on_python27(self):
        import copy
        catalog = self.modules['bot_tactics']
        name = '02_malinovka'
        profile = dict(name='DEFAULT', maps={name: dict(
            routes=[], positions=[], default_routes=[])})
        original = copy.deepcopy(profile)
        expected = catalog.default_map(name)
        first = catalog.effective_map(profile, name)
        second = catalog.effective_map(profile, name)
        self.assertEqual(expected, first)
        self.assertEqual(expected, second)
        first['default_routes'][0]['points'][0][0] += 100.
        first['positions'].append(dict(id='player-only', point=[0., 0.]))
        self.assertNotEqual(first, second)
        self.assertEqual(expected, second)
        self.assertEqual(expected, catalog.effective_map(profile, name))
        self.assertEqual(original, profile)

    def test_stalled_sortie_attempts_expire_without_inventing_terminal_retry_limit(self):
        import copy
        module = self.modules['spg_route_recovery']
        runtime = types.ModuleType('physical_route_inputs')
        runtime.baked_graph = dict(objective_bases=((-100., 0.), (100., 0.)),
                                  objective_base_radii=(10., 10.))
        active = dict(id='local-sortie', index=2, points=[[-100., 0., 0],
                      [-50., 0., 0], [0., 0., 0], [0., 100., 0]])
        other = copy.deepcopy(active)
        state = dict(id=17, team=1, x=-70., z=50., fire_seq=7)
        phases, changes = set(), []
        previous = None
        for now in range(201):
            module.advance(runtime, state, active, float(now))
            phase = active.get('recovery_phase', 'forward')
            phases.add(phase)
            key = (phase, active['index'])
            if key != previous:
                changes.append(now)
                previous = key
            self.assertEqual(7, state['fire_seq'])
        self.assertEqual(set(('forward', 'skip', 'return', 'return_skip')), phases)
        self.assertGreater(len(changes), 8)
        self.assertTrue(all(b - a <= module.ATTEMPT_SECONDS + 1.
                            for a, b in zip(changes, changes[1:])))
        self.assertNotIn('complete', active)
        self.assertNotIn('replace', active)
        self.assertNotIn('attack_attempt', other)
        self.assertEqual(2, other['index'])

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
        first.grid.set_static_hulls(((9, 0., 0., 0., 3.5, 1.5),
                                     (-90, 20., 0., 0., 2., 1.)), clearance=1.)
        self.assertGreater(first.grid.static_hull_revision, second.grid.static_hull_revision)
        self.assertTrue(first.grid.segment_penalty((0., 0., -20.), (0., 0., 20.), 0.))
        search = first.grid.begin_plan((0., 0., -20.), (0., 0., 20.))
        for unused in range(8):
            if search.step(4096):
                break
        self.assertTrue(search.done)
        self.assertGreater(len(search.result), 2)
        self.assertFalse(first.grid.path_crosses_static_hull(search.result))
        first.searches[17] = search
        first.search_times[17] = 0.
        first.close()
        self.assertFalse(first.searches)
        self.assertFalse(first.search_times)
        self.assertFalse(first.boundary_bodies)
        self.assertIsNot(first.grid, second.grid)
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
        links = self.modules['ai.local_height'].LocalHeightLinks(columns)
        links.begin((0., 0., 0.), now=0.)
        status, point = links.inspect((0., 0., 0.), (0., 8., 4.), baked_start=8.)
        self.assertEqual('other_surface', status)
        self.assertEqual((0., 0., 4.), point)
        self.assertTrue(calls)
        self.assertLessEqual(links.queries, self.modules['ai.local_height'].MAX_COLUMNS)
        count = len(calls)
        self.assertEqual(('connected', point), links.inspect((0., 0., 0.), point))
        self.assertEqual(count, len(calls))

    def test_nearest_armor_hints_without_a_second_tracker_execute_on_python27(self):
        planner = self.modules['strategy'].BotPlanner()
        actor = dict(id=1, team=1, rating=10000,
            profile=dict(class_tag='heavyTank', desired_range=300., armor=120.),
            state=dict(x=0., y=0., z=0., ammo_remaining=[10], shell_index=0,
                       clip=1, clip_size=1, reload_time=0., health=1000, max_health=1000))
        rows = [dict(id=identity, target_kind='bot', position=dict(x=0., y=0., z=z),
            alive=True, visible=True, health=1000, max_health=1000,
            last_seen=0., shootable_by_bot_ids=(1,)) for identity, z in ((8, 200.), (9, 25.))]
        self.assertEqual(9, planner._initial_target_hints([actor], rows, 0.)[1]['id'])
        rows[0]['position']['z'] = 10.
        self.assertEqual(8, planner._initial_target_hints([actor], rows, .5)[1]['id'])
        rows[1]['visible'] = False
        self.assertEqual(8, planner._initial_target_hints([actor], rows, 1.)[1]['id'])
        planner.reset(2)
        rows[0].update(armor=120.)
        rows[1].update(visible=True, armor=20.)
        rows[1]['position']['z'] = 10.
        self.assertEqual(9, planner._initial_target_hints([actor], rows, 2.)[1]['id'])
        self.assertFalse(hasattr(planner, '_target_assignments'))
        self.assertFalse(hasattr(planner, '_angled_face_point'))
        self.assertFalse(hasattr(planner, '_apply_stationary_angling'))

    def test_public_roster_retains_unobserved_allies_without_inventing_geometry(self):
        module = self.modules['full_runtime']
        owner = types.ModuleType('public_roster_inputs')
        owner.client = types.ModuleType('public_roster_identity')
        owner.client.player_id = 7
        owner._start_message = dict(round_id=1, players=[dict(id=7, team=1, alive=True),
            dict(id=8, team=1, alive=True), dict(id=9, team=2, alive=True)])
        owner._last_snapshot = {}
        owner._records = {}
        runtime = module.FullPlayerRuntime(owner)
        runtime.actor_id = 17
        runtime.engine = module._PlayerBehaviorEngine(runtime)
        self.addCleanup(runtime.engine.close)
        # Only public identity data is supplied. No movement, target ranking,
        # route finder or observation algorithm is replaced by this fixture.
        runtime.engine.states[17] = dict(id=17, kind='bot', network_id=17,
                                         team=1, alive=True)
        allies = runtime._public_allies()
        self.assertEqual(1, len(allies))
        self.assertEqual(('human', 8), (allies[0]['kind'], allies[0]['network_id']))
        self.assertTrue(allies[0]['alive'])
        self.assertFalse(allies[0]['world_pose'])
        self.assertTrue(all(key not in allies[0] for key in ('position', 'x', 'y', 'z')))
        # An old battle's public death must not retire a same-ID teammate in
        # this round, and its unobserved coordinates remain non-spatial data.
        owner._last_snapshot = dict(round_id=0, players=[dict(id=8, team=1,
            alive=False, x=900., y=1., z=800.)])
        retained = runtime._public_allies()[0]
        self.assertTrue(retained['alive'])
        self.assertTrue(all(key not in retained for key in ('position', 'x', 'y', 'z')))
        # Public lifecycle may change independently of AOI. A transport row's
        # unobserved coordinates must not become a native spatial observation.
        owner._last_snapshot = dict(round_id=1, players=[dict(id=8, team=1,
            alive=False, x=900., y=1., z=800.)])
        dead = runtime._public_allies()[0]
        self.assertFalse(dead['alive'])
        self.assertTrue(all(key not in dead for key in ('position', 'x', 'y', 'z')))

    def test_shared_strategy_preserves_unicode_and_python3_half_even_contract(self):
        import math
        compat = self.modules['strategy_compat']
        planner_module = self.modules['strategy']
        for value, expected in ((.5, 0), (1.5, 2), (2.5, 2), (-.5, 0)):
            self.assertEqual(expected, compat.round_py3(value))
            self.assertEqual(expected, compat.round_half_even(value))
        self.assertEqual(2.67, compat.round_py3(2.675, 2))
        self.assertEqual(2.67, compat.round_half_even(2.675, 2))
        self.assertEqual(-1., math.copysign(1., compat.round_py3(-.0001, 3)))
        self.assertEqual(-1., math.copysign(1., compat.round_half_even(-.0001, 3)))
        planner = planner_module.BotPlanner()
        self.assertEqual(u'\u8def\u7ebf', planner._task_family(dict(id=u'\u8def\u7ebf'), 1))
        self.assertEqual(u'\u547d\u4ee4', compat.text(u'\u547d\u4ee4'))

    def test_fire_candidate_random_draw_and_flight_limit_execute_on_python27(self):
        module = self.modules['trigger_admission']
        draw = module._ScatterDraw()
        first = (draw.uniform(-1., 1.), draw.uniform(3., 5.), draw.gauss(2., .5))
        draw.cursor = 0
        self.assertEqual(first, (draw.uniform(-1., 1.), draw.uniform(3., 5.), draw.gauss(2., .5)))
        path, times = module.TriggerAdmission._launch_path((0., 0., 0.), (100., 0., 0.), 0., 25.)
        self.assertAlmostEqual(25., path[-1][0], places=6)
        self.assertAlmostEqual(.25, times[-1], places=6)
        self.assertLessEqual(len(path), module.MAX_PROOF_CHORDS + 1)
        self.assertEqual(((), ()), module.TriggerAdmission._launch_path(
            (0., 0., 0.), (0., 0., 0.), 0., 25.))

    def test_retired_cover_modules_and_runtime_entrances_are_absent_on_python27(self):
        geometry = self.modules['geometry'].SharedBattleGeometry()
        planner = self.modules['strategy'].BotPlanner()
        for name in ('_sample_bot_cover', '_cover_ground', '_cover_surface_pose',
                     '_cover_gun_lane', '_cover_slope'):
            self.assertFalse(hasattr(geometry, name), name)
        for name in ('_cover_candidate', '_cover_states', '_cover_reservations',
                     '_affordances', '_retreat_states'):
            self.assertFalse(hasattr(planner, name), name)
        for root in (os.path.dirname(BASE), BASE):
            for name in ('cover.py', 'tactical_geometry.py'):
                self.assertFalse(os.path.exists(os.path.join(root, 'ai', name)))


if __name__ == '__main__':
    unittest.main()
