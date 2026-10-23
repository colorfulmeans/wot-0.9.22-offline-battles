"""The same mounted chassis bounds fence planning, recovery and live motion."""
import math
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import arena_boundary as boundary
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
import test_port_0922_bot_runtime as fixture


class BoundaryPolicyTests(unittest.TestCase):
    def test_lakeville_vertex_inside_map_is_outside_complete_chassis(self):
        bounds=(-400.,-400.,400.,400.)
        self.assertTrue(-400<398<400)
        self.assertFalse(boundary.progress_clear(bounds,(-62.,9.,395.),0.,
                                                  (-62.,9.,398.),0.,4.,1.7))
        self.assertTrue(boundary.progress_clear(bounds,(-62.,9.,398.),0.,
                                                 (-62.,9.,394.),0.,4.,1.7))

    def test_rotation_checks_middle_of_arc_even_when_both_ends_fit(self):
        bounds=(-10.,-10.,10.,10.)
        self.assertFalse(any(boundary.overflow(bounds,(6.,0.,0.),0.,4.,2.)))
        self.assertFalse(any(boundary.overflow(bounds,(6.,0.,0.),math.pi/2,4.,2.)))
        self.assertFalse(boundary.rotation_clear(bounds,(6.,0.,0.),0.,math.pi/2,4.,2.))
        self.assertTrue(boundary.rotation_clear(bounds,(0.,0.,0.),0.,math.pi/2,4.,2.))

    def test_stale_outside_pose_can_recover_without_teleport(self):
        self.assertTrue(boundary.rotation_clear((-10.,-10.,10.,10.),(11.,0.,0.),
                                                math.pi/2,0.,4.,2.))
        self.assertFalse(boundary.progress_clear((-10.,-10.,10.,10.),(11.,0.,0.),0.,
                                                  (12.,0.,0.),0.,4.,2.))

    def make_nav(self):
        return TerrainNavigator(lambda *a:0.,lambda *a:False,baked_graph=fixture._flat_open_graph())

    def test_boundary_masks_are_reused_but_do_not_mutate_shared_grid(self):
        nav=self.make_nav();original=list(nav.grid._baked_links)
        nav.set_boundary_body(7,(0.,0.,0.),0.,4.,2.)
        edges=nav.boundary_bodies[7]['edges']
        self.assertTrue(edges)
        for at in range(10):nav.set_boundary_body(7,(at*.01,0.,0.),0.,4.,2.)
        self.assertIs(edges,nav.boundary_bodies[7]['edges'])
        nav.set_boundary_body(8,(0.,0.,0.),0.,2.,1.)
        self.assertNotEqual(edges,nav.boundary_bodies[8]['edges'])
        self.assertEqual(original,list(nav.grid._baked_links))
        nav.close();self.assertFalse(nav.boundary_bodies)

    def test_mask_uses_official_bounds_inside_wider_baked_arrays(self):
        graph=fixture._flat_open_graph();graph['bounds']=(-30.,-30.,30.,30.)
        nav=TerrainNavigator(lambda *a:0.,lambda *a:False,baked_graph=graph)
        nav.set_boundary_body(7,(0.,0.,0.),0.,4.,2.)
        self.assertTrue(nav.boundary_bodies[7]['edges'])
        self.assertTrue(nav.bot_segment_penalized(7,(0.,0.,24.),(0.,0.,28.),0.))
        # A later inward move retains the actor's original body and bounds.
        nav.set_boundary_body(7,(0.,0.,28.),0.,4.,2.)
        self.assertFalse(nav.bot_segment_penalized(7,(0.,0.,28.),(0.,0.,20.),1.))

    def test_outward_local_leg_is_refused_but_inward_leg_remains_legal(self):
        nav=self.make_nav();nav.set_boundary_body(7,(0.,0.,57.),0.,4.,2.)
        self.assertTrue(nav.bot_segment_penalized(7,(0.,0.,57.),(0.,0.,60.),0.))
        self.assertFalse(nav.bot_segment_penalized(7,(0.,0.,57.),(0.,0.,48.),0.))

    def test_astar_cached_border_detour_is_retired_for_real_chassis(self):
        nav=self.make_nav();start=(-20.,0.,48.);goal=(20.,0.,48.)
        nav.set_boundary_body(7,start,0.,4.,2.)
        nav._boundary_actor=7
        key=nav._cache_key(('route',1,'road',0),goal)
        bad=(start,(-20.,0.,60.),(20.,0.,60.),goal)
        nav.paths[key]=bad;nav.path_times[key]=0.
        nav.path_hull_revisions[key]=nav.grid.static_hull_revision
        unused,path=nav._path(('route',1,'road',0),start,goal,1.,())
        self.assertNotEqual(bad,path)
        self.assertTrue(path)
        self.assertTrue(all(not nav.bot_segment_penalized(7,a,b,1.) for a,b in zip(path,path[1:])))

    def test_coarse_boundary_mask_does_not_reject_a_legal_subcell_direct_leg(self):
        nav=self.make_nav();start=(-20.,0.,58.);end=(20.,0.,58.)
        nav.set_boundary_body(7,start,math.pi/2,4.,2.1)
        self.assertTrue(any(edge in nav.boundary_bodies[7]['edges']
                            for edge in nav.grid._edge_keys_for_segment(start,end)))
        self.assertFalse(nav.bot_segment_penalized(7,start,end,0.))
        nav._boundary_actor=7
        key,path=nav._path(('route',1,'edge',0),start,end,0.,())
        self.assertEqual((start,end),path)
        self.assertIs(path,nav._path(('route',1,'edge',0),start,end,1.,())[1])

    def test_final_outward_guard_replans_the_invalid_leg_once(self):
        harness=fixture.BotRuntimeTests();harness.setUp()
        self.addCleanup(harness.doCleanups)
        runtime=harness.runtime;runtime.battle_start(harness.start)
        runtime.baked_graph['bounds']=(-62.,-62.,62.,62.)
        state=runtime.states[11]
        state.update(x=0.,y=0.,z=60.,yaw=0.,half_length=4.,half_width=2.)
        state['_navigation_target_receipt']={'final_target':(0.,0.,61.)}
        with mock.patch.object(runtime.navigator,'request_replan') as replan, \
             mock.patch.object(runtime.navigator,'report_blocked_step') as report:
            self.assertTrue(runtime._guard_realised_pose(state,(0.,0.,58.),True,0.))
            state.update(z=60.)
            self.assertTrue(runtime._guard_realised_pose(state,(0.,0.,58.),True,0.))
        replan.assert_called_once();report.assert_called_once()

    def test_forward_and_reverse_preview_reject_boundary_before_native_sweep(self):
        from test_port_0922_battle_runtime import BattleRuntime,_runtime
        from types import SimpleNamespace
        battle=BattleRuntime(_runtime());battle._arena_bounds=(-10.,-10.,10.,10.)
        battle._bots=SimpleNamespace(states={7:dict(half_length=4.,half_width=2.)})
        for position,body,travel in (((0.,0.,6.),0.,0.),((0.,0.,-6.),0.,math.pi)):
            with mock.patch.object(battle,'_resolve_bot_motion') as native:
                row=battle._probe_bot_local_motion(7,position,body,travel,2.,None,.1,1.)
                self.assertFalse(row['clear']);self.assertEqual('arena_boundary',row['reason'])
                native.assert_not_called()

