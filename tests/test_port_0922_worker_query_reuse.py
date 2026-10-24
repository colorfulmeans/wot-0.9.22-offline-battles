"""Synchronous preparation reuse must not cache physical world results."""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixtures
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922 import native_destructibles as geometry


class WorkerQueryReuseTests(unittest.TestCase):
    def test_normal_entry_keeps_filter_identity_and_no_candidate_collection(self):
        from gui.mods.offline_lan_0922 import world_collision as world
        from gui.mods.offline_lan_0922 import native_input_diagnostics as diagnostic
        callback = mock.Mock(side_effect=lambda material,*args: material != 73)
        for detail in ('0', '1'):
            trace = {}
            with mock.patch.dict(diagnostic.os.environ, {diagnostic.DETAIL_ENV:detail}):
                selected = world._trace_collision_filter(callback, trace)
            self.assertEqual(False, selected(73,80,1,2))
            self.assertEqual(True, selected(87,80,1,2))
            if detail == '0':
                self.assertIs(selected, callback)
                self.assertEqual({}, trace)
            else:
                self.assertEqual([(73,80,1,2,False),(87,80,1,2,True)],
                                 trace['native_surface_candidates'])

    def test_prepared_rotation_geometry_is_exact_without_repeated_live_reads(self):
        import random
        import struct
        from gui.mods.offline_lan_0922 import world_collision as world
        module = fixtures.battle_runtime_module
        rng = random.Random(461)
        for unused in range(200):
            bbox = (tuple(rng.uniform(-8,0) for i in range(3)),
                    tuple(rng.uniform(0,8) for i in range(3)))
            descriptor = module._destructible_world_sweep_descriptor({}, bbox)
            expected = world._read_vehicle_motion_geometry(dict(descriptor))
            with mock.patch.object(world, '_vehicle_hull_bbox', side_effect=AssertionError('reread')):
                actual = world._vehicle_motion_geometry(descriptor)
                self.assertIs(actual, world._vehicle_motion_geometry(descriptor))
            self.assertEqual(struct.pack('6d', *(expected[0]+expected[1])),
                             struct.pack('6d', *(actual[0]+actual[1])))

    def test_rotation_reuses_preparation_but_preserves_every_posed_query(self):
        import math
        module = fixtures.battle_runtime_module
        battle = fixtures.BattleRuntime(fixtures._runtime())
        bbox = ((-1.,-.2,-3.),(2.,2.,4.))
        battle._destructibles = types.SimpleNamespace(_vehicle_body_bbox=lambda d:bbox)
        battle._avatar = types.SimpleNamespace(spaceID=1)
        descriptor = {'physics':{}}
        for pivot, travel, grounded in ((0.,(0.,0.),False),(.7,(.3,-.4),True)):
            calls = []
            def query(*args, **kwargs):
                calls.append((args,kwargs))
                return 'clear'
            with mock.patch.object(module.world_collision, 'check_horizontal_collision', side_effect=query), \
                    mock.patch.object(module, '_destructible_rotation_interval_bbox', wraps=module._destructible_rotation_interval_bbox) as prepare:
                self.assertTrue(battle._native_world_rotation_is_clear(
                    (1.,2.,3.),.1,.7,descriptor,pitch=.2,roll=-.1,
                    pivot_offset=pivot,translation=travel,follow_ground=grounded))
            steps = int(math.ceil(.6/module.DESTRUCTIBLE_POSE_MAX_ANGLE_STEP))
            self.assertEqual(1,prepare.call_count)
            self.assertEqual(steps*(1 if any(travel) else 2),len(calls))
            self.assertEqual(1,len(set(id(args[6]) for args,kw in calls)))
            for index,(args,kw) in enumerate(calls):
                step = index if any(travel) else index//2
                lower, upper = float(step)/steps, float(step+1)/steps
                yaw = .1 + module._angle_delta(.1,.7)*(lower+upper)*.5
                point = module.vehicle_physics.track_pivot_position((1.,2.,3.),.1,yaw,pivot)
                self.assertEqual(yaw,args[4])
                self.assertEqual((point[0]+travel[0]*lower,point[1],point[2]+travel[1]*lower),
                                 tuple(args[3]))
                self.assertFalse(kw['commit_enabled'])
                self.assertEqual(not any(travel),kw['exact_footprint'])

    def _fitted_control(self):
        from gui.mods.offline_lan_0922.native_control_core import NativeControl
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        runtime = object.__new__(BotRuntime)
        patch = mock.patch.dict(BotRuntime._spotting_profile.__globals__, {
            '_bot_profile':mock.Mock(return_value={}),
            '_base_invisibility':mock.Mock(return_value=0.),
            '_shot_invisibility_factor':mock.Mock(return_value=1.)})
        patch.start()
        self.addCleanup(patch.stop)
        runtime._descriptors = {7: object()}
        runtime._spotting_profiles = {}
        runtime._vision_ranges = {}
        runtime.bot_crew_level = lambda unused: 100
        source = dict(id=7, kind='bot', team=1, slot=1, critical={})
        control = object.__new__(NativeControl)
        control.runtime = runtime
        control._config_projections = {}
        def project(row, tick):
            return runtime._spotting_profile(row, tick), row['team']
        control._project_actor_config = mock.Mock(side_effect=project)
        return control, runtime, source

    def test_fitted_bot_cache_uses_real_producer_key_for_every_tier(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        with mock.patch.object(bot_fittings, 'context', return_value={}):
            for tier in range(4):
                owner, runtime, source = self._fitted_control()
                runtime.bot_crew_level = lambda unused, tier=tier: (50,75,100,100)[tier]
                for unused in range(1000):
                    owner._actor_config(source, {})
                self.assertEqual(1, owner._project_actor_config.call_count)
                self.assertIn(('bot',7,((),False)), runtime._spotting_profiles)
                self.assertNotIn(('bot',7), runtime._spotting_profiles)

    def test_fitted_projection_invalidates_on_real_mutable_inputs(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        with mock.patch.object(bot_fittings, 'context', return_value={}):
            owner, runtime, source = self._fitted_control()
            owner._actor_config(source, {})
            mutations = [lambda:source['critical'].update(crew_ko=['driver']),
                lambda:source['critical'].update(fire=True),
                lambda:source['critical'].update(devices=[dict(name='surveyingDeviceHealth',hp=0)]),
                lambda:source.update(team=2),
                lambda:runtime._vision_ranges.update({7:450.}),
                lambda:runtime._descriptors.update({7:object()})]
            for expected, mutate in enumerate(mutations, 2):
                mutate()
                owner._actor_config(source, {})
                owner._actor_config(source, {})
                self.assertEqual(expected, owner._project_actor_config.call_count)
            runtime._spotting_profiles.clear()
            owner._actor_config(source, {})
            self.assertEqual(8, owner._project_actor_config.call_count)

    def test_legacy_bot_reuses_projection_and_human_never_uses_bot_cache(self):
        from gui.mods.offline_lan_0922 import bot_fittings
        with mock.patch.object(bot_fittings, 'context', return_value=None):
            owner, runtime, source = self._fitted_control()
            for unused in range(10):
                owner._actor_config(source, {})
            self.assertEqual(1, owner._project_actor_config.call_count)
            self.assertIn(('bot',7), runtime._spotting_profiles)
            owner._project_actor_config = mock.Mock(return_value=('human',))
            source['kind'] = 'human'
            for unused in range(3):
                self.assertEqual(('human',), owner._actor_config(source, {}))
            self.assertEqual(3, owner._project_actor_config.call_count)

    def test_current_baked_footprint_is_reused_only_for_one_planning_snapshot(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        calls = []
        def probe(position, yaw, length, width):
            calls.append((position, yaw, length, width))
            return abs(yaw) < 1.0
        grid = types.SimpleNamespace(hull_pose_clear=probe)
        cache = {}
        for yaw in (0., .25, .5, 1., 1.5):
            self.assertEqual((True, abs(yaw) < 1.), BotRuntime._planning_grid_pose_pair(
                grid, (1., 2., 3.), 0., yaw, 3., 1.5, cache))
        self.assertEqual(5, len(calls))  # one current pose, four other candidates
        self.assertEqual(1, sum(row[1] == 0. for row in calls))
        BotRuntime._planning_grid_pose_pair(grid, (1., 2., 3.), 0., .25, 3., 1.5, {})
        self.assertEqual(7, len(calls))  # next decision rechecks the grid

    def test_rotation_detail_only_in_test_entry_preserves_queries_and_verdict(self):
        from gui.mods.offline_lan_0922.worker_diagnostics import WorkerCombatDiagnostics
        module = fixtures.battle_runtime_module
        for detail in ('0','1'):
            trace = WorkerCombatDiagnostics(lambda:1.)
            trace.begin_frame(1, 1., 'test')
            battle = object.__new__(fixtures.BattleRuntime)
            battle._combat_diagnostics = trace
            battle._bots = types.SimpleNamespace(states={})
            battle._bot_motion_kinds = {}
            calls = []
            battle._destructible_pose_sweep = lambda *a,**k:(calls.append('catalog') or dict(status='clear'))
            battle._native_world_rotation_is_clear = lambda *a,**k:(calls.append('native') or True)
            battle._tree_motion_proposal = lambda *a,**k:None
            battle._complete_bot_tree_contact = lambda *a,**k:'clear'
            with mock.patch.dict(module.native_input_diagnostics.os.environ,
                    {module.native_input_diagnostics.DETAIL_ENV:detail}):
                self.assertTrue(battle._resolve_bot_rotation(
                    1,(0.,0.,0.),0.,.1,object(),.1,1.,None))
            row = trace.finish_frame()
            self.assertEqual(['catalog','native'], calls)
            self.assertEqual(detail=='1', 'rotation.catalog_probe' in row['stages'])
            self.assertEqual(detail=='1', 'rotation.native_probe' in row['stages'])
            self.assertEqual(int(detail), row['counts'].get('rotation.realised',0))

    def test_baked_reuse_does_not_cross_pose_geometry_or_grid_identity(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        probe = mock.Mock(return_value=False)
        grid = types.SimpleNamespace(hull_pose_clear=probe)
        cache = {}
        for point, yaw, length in (((0, 0, 0), 0., 3.),
                                   ((1, 0, 0), 0., 3.),
                                   ((1, 0, 0), .1, 3.),
                                   ((1, 0, 0), .1, 4.)):
            self.assertEqual((False, False), BotRuntime._planning_grid_pose_pair(
                grid, point, yaw, yaw, length, 1.5, cache))
        self.assertEqual(4, probe.call_count)
        other = types.SimpleNamespace(hull_pose_clear=probe)
        BotRuntime._planning_grid_pose_pair(other, (1, 0, 0), .1, .1, 4., 1.5, cache)
        self.assertEqual(5, probe.call_count)

    def test_identical_candidate_footprints_share_only_the_synchronous_scope(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        probe = mock.Mock(side_effect=lambda p,y,l,w:y<1.)
        grid = types.SimpleNamespace(hull_pose_clear=probe)
        cache = {}
        for unused in range(20):
            self.assertEqual((True, True), BotRuntime._planning_grid_pose_pair(
                grid, (0.,0.,0.), 0., .5, 3., 1.5, cache))
        self.assertEqual(2, probe.call_count)
        BotRuntime._planning_grid_pose_pair(grid, (0.,0.,0.), 0., .5, 3., 1.5, {})
        self.assertEqual(4, probe.call_count)

    def test_navigation_handoff_keeps_early_returns_exceptions_and_gradual_rebases(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        authority = {'_navigation_target_receipt': {'source': 'retained'}}
        for step in range(5):
            BotRuntime._record_navigation_handoff(authority, (0, 0, 0), (50, 0, 0),
                {'combat_mode': 'route'}, {'now': step}, (3 + step, 0, 0))
        lineage = authority['_navigation_handoff_lineage']
        self.assertEqual(5, lineage['calls'])
        self.assertEqual(2, lineage['changes'])  # accumulated rebase exceeds 2 m
        BotRuntime._record_navigation_handoff(authority, (0, 0, 0), (50, 0, 0),
            {}, {'now': 5}, None)
        self.assertEqual('no_target', lineage['events'][-1]['outcome'])
        BotRuntime._record_navigation_handoff(authority, (0, 0, 0), (50, 0, 0),
            {}, {'now': 6}, None, failed=True)
        self.assertEqual('exception', lineage['events'][-1]['outcome'])
        self.assertEqual((50, 0, 0), lineage['last_goal'])

    def test_navigation_wrapper_records_actual_return_and_preserves_original_exception(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        runtime = object.__new__(BotRuntime)
        links = types.SimpleNamespace(origin=(1, 0, 0))
        runtime.navigator = types.SimpleNamespace(grid=types.SimpleNamespace(local_height_links=links))
        runtime.states = {1: {}}
        runtime._navigation_target_impl = mock.Mock(return_value=None)
        self.assertIsNone(runtime._navigation_target(1, (0, 0, 0), (10, 0, 0), {}, {'now': 1}))
        self.assertIsNone(links.origin)
        self.assertEqual('no_target', runtime.states[1]['_navigation_handoff_lineage']['events'][-1]['outcome'])
        error = ValueError('original failure')
        runtime._navigation_target_impl.side_effect = error
        with self.assertRaises(ValueError) as raised:
            runtime._navigation_target(1, (0, 0, 0), (10, 0, 0), {}, {'now': 2})
        self.assertIs(error, raised.exception)
        self.assertEqual('exception', runtime.states[1]['_navigation_handoff_lineage']['events'][-1]['outcome'])

    def test_shared_motion_geometry_is_exact_and_reads_the_hull_once(self):
        import random
        import struct
        from gui.mods.offline_lan_0922 import world_collision as world
        randomizer = random.Random(392)
        for unused in range(500):
            descriptor = dict(
                hull=dict(hitTester=types.SimpleNamespace(bbox=(
                    tuple(randomizer.uniform(-4, 0) for i in range(3)),
                    tuple(randomizer.uniform(0, 4) for i in range(3))))),
                chassis=dict(hitTester=types.SimpleNamespace(bbox=(
                    (-1., -0., -3.), (1., 0., 3.))),
                    hullPosition=tuple(randomizer.uniform(-1, 1) for i in range(3))))
            expected = (world._vehicle_motion_bounds(descriptor),
                        world._vehicle_motion_heights(descriptor))
            with mock.patch.object(world, '_vehicle_hull_bbox',
                                   wraps=world._vehicle_hull_bbox) as read:
                actual = world._vehicle_motion_geometry(descriptor)
                self.assertEqual(1, read.call_count)
            self.assertEqual(struct.pack('6d', *(expected[0]+expected[1])),
                             struct.pack('6d', *(actual[0]+actual[1])))

    def test_shared_geometry_observes_live_mount_and_bbox_changes(self):
        from gui.mods.offline_lan_0922 import world_collision as world
        self.assertEqual((None, (.6, 1.6)), world._vehicle_motion_geometry(None))
        descriptor = dict(hull=dict(hitTester=types.SimpleNamespace(
            bbox=((-1., .5, -2.), (1., 2., 2.)))), chassis=dict(
            hitTester=types.SimpleNamespace(bbox=((-1., 0., -3.), (1., 1., 3.))),
            hullPosition=(0., 0., 0.)))
        before = world._vehicle_motion_geometry(descriptor)
        descriptor['chassis']['hullPosition'] = (2., 3., 4.)
        descriptor['hull']['hitTester'].bbox = ((-2., -1., -4.), (2., 4., 4.))
        after = world._vehicle_motion_geometry(descriptor)
        self.assertNotEqual(before, after)
        self.assertEqual((world._vehicle_motion_bounds(descriptor),
                          world._vehicle_motion_heights(descriptor)), after)

    def test_ground_preparer_is_reused_but_each_column_remains_live(self):
        with sensor.collision_preparation_scope_1513():
            first = sensor.ground_filter_batch_1513(sensor.ground_collision_filter)
            for unused in range(100):
                self.assertIs(first, sensor.ground_filter_batch_1513(sensor.ground_collision_filter))
        with sensor.collision_preparation_scope_1513():
            self.assertIsNot(first, sensor.ground_filter_batch_1513(sensor.ground_collision_filter))
        self.assertIsNone(sensor.ground_filter_batch_1513(lambda *args: None))

    def test_exact_pose_axes_reuse_does_not_round_or_cache_world_answers(self):
        from gui.mods.offline_lan_0922 import tank_collision as collision
        collision._POSE_AXES_CACHE.clear()
        with mock.patch.object(collision, '_uncached_pose_axes', wraps=collision._uncached_pose_axes) as compute:
            first = collision.pose_axes(.2, .1, -.1)
            for unused in range(100):
                self.assertIs(first, collision.pose_axes(.2, .1, -.1))
            self.assertEqual(1, compute.call_count)
            collision.pose_axes(.20000001, .1, -.1)
            self.assertEqual(2, compute.call_count)
        for index in range(1000):
            angles = (index*.01, index*.003, -index*.005)
            self.assertEqual(collision._uncached_pose_axes(*angles), collision.pose_axes(*angles))
        self.assertLessEqual(len(collision._POSE_AXES_CACHE), 256)
        import struct
        for angles in ((0.,0.,0.),(-0.,0.,0.),(0.,-0.,0.),(0.,0.,-0.)):
            flatten = lambda axes: tuple(v for axis in axes for v in axis)
            self.assertEqual(struct.pack('9d', *flatten(collision._uncached_pose_axes(*angles))),
                             struct.pack('9d', *flatten(collision.pose_axes(*angles))))

    def test_support_columns_share_live_member_preparation_in_the_worker_scope(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        battle._destructibles = sensor
        callback = mock.Mock(return_value=True)
        with mock.patch.dict(sensor.__dict__, {
                'g_offh_destr_runtime_space': 1,
                'g_offh_destr_spatial_revision': 0,
                'g_offh_destr_contact_bins': {(0, 0): {(22, 7)}},
                'g_offh_tree_state': {'native_committed': set()},
                'g_offh_destr_spatial_mutation_batch': {}}), mock.patch.object(
                sensor, '_live_broken_collision_filter_1513', return_value=callback) as prepare:
            with sensor.collision_preparation_scope_1513():
                for index in range(100):
                    self.assertIs(callback,battle._ground_filter_impl(1.+index*.001,2.))
                self.assertEqual(1,prepare.call_count)
                sensor.g_offh_destr_spatial_revision += 1
                self.assertIs(callback,battle._ground_filter_impl(1.,2.))
                self.assertEqual(2,prepare.call_count)
            with sensor.collision_preparation_scope_1513():
                battle._ground_filter_impl(1.,2.)
            self.assertEqual(3,prepare.call_count)

    def test_custom_ground_provider_keeps_its_original_calls(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        provider = mock.Mock(return_value=None)
        battle._destructibles = types.SimpleNamespace(
            ground_collision_filter=provider,
            ground_filter_batch_1513=sensor.ground_filter_batch_1513)
        for index in range(10):
            self.assertIsNone(battle._ground_filter_impl(1.,2.))
        self.assertEqual(10,provider.call_count)

    def test_only_identical_pure_chunk_mapping_is_reused(self):
        owner = mock.Mock()
        owner.query.return_value = (22,22,())
        area = types.SimpleNamespace(chunkIDFromPosition=mock.Mock())
        p = types.SimpleNamespace(x=1.,y=2.,z=3.)
        with mock.patch.object(geometry,'_chunk_mapper_1513',return_value=True), \
                mock.patch.object(geometry,'_get',return_value=owner), \
                mock.patch.dict(sensor.__dict__,{'g_offh_destr_runtime_space':1}):
            with sensor.collision_preparation_scope_1513():
                for index in range(100):
                    self.assertEqual((22,22,()),geometry.neighbourhood(
                        sensor,area,p,0.,1.,0.,True))
                self.assertEqual(1,owner.query.call_count)
                p.x += .001
                geometry.neighbourhood(sensor,area,p,0.,1.,0.,True)
                geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
                sensor.g_offh_destr_runtime_space=2
                geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
                self.assertEqual(4,owner.query.call_count)
            geometry.neighbourhood(sensor,area,p,0.,1.,-1.,True)
            self.assertEqual(5,owner.query.call_count)

    def test_unavailable_mapping_is_retried_in_the_same_scope(self):
        owner = mock.Mock()
        owner.query.side_effect = [None,(22,22,())]
        area = types.SimpleNamespace(chunkIDFromPosition=mock.Mock())
        with mock.patch.object(geometry,'_chunk_mapper_1513',return_value=True), \
                mock.patch.object(geometry,'_get',return_value=owner):
            with sensor.collision_preparation_scope_1513():
                self.assertIsNone(geometry.neighbourhood(sensor,area,(0.,0.,0.),0.,1.,0.,True))
                self.assertEqual((22,22,()),geometry.neighbourhood(sensor,area,(0.,0.,0.),0.,1.,0.,True))
        self.assertEqual(2,owner.query.call_count)

    def test_landing_receipts_correlate_events_without_changing_submissions(self):
        battle = fixtures.BattleRuntime(fixtures._runtime())
        entity = types.SimpleNamespace(typeDescriptor=types.SimpleNamespace(maxHealth=7000))
        battle._clock = mock.Mock(side_effect=[1.,1.04])
        with mock.patch.object(fixtures.battle_runtime_module.native_input_diagnostics,
                               'write_json_record') as write:
            first = battle._apply_fall_damage(entity,18.641)
            second = battle._apply_fall_damage(entity,11.711)
        self.assertGreater(first,second)
        self.assertEqual([18.641,11.711],battle._pending_landing_impacts)
        rows=[call.args[1] for call in write.call_args_list
              if call.args[0]=='PLAYER LANDING IMPACT']
        self.assertEqual([1,2],[row['diagnostic_sequence'] for row in rows])
        self.assertAlmostEqual(40.,rows[1]['previous_gap_ms'])
        self.assertEqual(first,rows[1]['previous_impact']['damage'])

    def test_z_bank_entry_receipt_does_not_require_a_local_fallback(self):
        import test_port_0922_bot_runtime as bots
        fixture = bots.ShovedWreckTests()
        fixture.setUp()
        try:
            runtime=fixture._runtime()
            goal=(20.,0.,20.)
            runtime.navigator=types.SimpleNamespace(
                grid=types.SimpleNamespace(cell_size=4.),bot_states={},
                bot_direct_progress={},paths={},
                retained_local_target=lambda *args:goal)
            state=runtime.states[11]
            state.update(pitch=.3,now=1.)
            order=dict(combat_mode='route',throttle_override=1.)
            from gui.mods.offline_lan_0922 import native_input_diagnostics
            with mock.patch.object(native_input_diagnostics,'write_json_record') as write:
                self.assertEqual(goal,runtime._navigation_target(11,(0.,0.,0.),goal,order,state))
                state['now']=2.
                self.assertEqual(goal,runtime._navigation_target(11,(0.,0.,0.),goal,order,state))
            rows=[c.args[1] for c in write.call_args_list if c.args[0]=='BOT NAV CHOICE']
            self.assertEqual(1,len(rows))
            self.assertEqual([],rows[0]['receipt']['local_choices'])
            self.assertEqual('retained',rows[0]['receipt']['source'])
            self.assertFalse(rows[0]['decision_input'])
        finally:
            fixture.tearDown()
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
