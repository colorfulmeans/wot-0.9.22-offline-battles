"""Shared static navigation policy replaces vehicle/gear crush capabilities.

Physical collision still checks the actual tank. These fixtures exercise only
planning proofs, cache invalidation, deferred queries and consumer ownership.
"""
import unittest
from test_port_0922_navigation import TerrainGrid, TerrainNavigator
from test_port_0922_bot_runtime import _flat_open_graph
from gui.mods.offline_lan_0922.ai.navigation import STATIC_PLANNING_POLICY

class CapabilityNavigationTests(unittest.TestCase):
    def test_legacy_vehicle_policy_is_rejected_before_any_world_query(self):
        calls=[]
        grid=TerrainGrid(lambda *a:0.,lambda *a:calls.append(a) or False,cell_size=4.)
        for policy in ((('stock1513',10000.,2.),10000.,2.),
                       (('stock1513',30000.,-10.),30000.,-10.),()):
            with self.subTest(policy=policy),self.assertRaises(ValueError):
                grid.segment_clear((0.,0.,0.),(4.,0.,0.),policy)
        self.assertEqual([],calls)
    def test_native_queries_receive_the_static_policy_and_share_reverse_receipts(self):
        calls=[]
        def obstacle(start,end,width,policy,evidence):
            calls.append((start,end,width,policy));return False
        grid=TerrainGrid(lambda *a:0.,obstacle,cell_size=4.)
        start,end=(0.,0.,0.),(4.,0.,0.)
        self.assertTrue(grid.segment_clear(start,end,STATIC_PLANNING_POLICY))
        first=len(calls)
        self.assertGreater(first,0)
        self.assertTrue(grid.segment_clear(end,start,None))
        self.assertEqual(first,len(calls))
        self.assertTrue(all(row[3]==STATIC_PLANNING_POLICY for row in calls))
    def test_deferred_query_is_not_cached_as_a_clear_or_solid_segment(self):
        verdict=['deferred'];calls=[]
        def obstacle(*args):calls.append(args);return verdict[0]
        grid=TerrainGrid(lambda *a:0.,obstacle,cell_size=4.)
        start,end=(0.,0.,0.),(4.,0.,0.)
        self.assertFalse(grid.segment_clear(start,end,STATIC_PLANNING_POLICY))
        self.assertTrue(grid._proof_deferred)
        self.assertEqual({},grid._segment_cache)
        verdict[0]=False
        self.assertTrue(grid.segment_clear(start,end,STATIC_PLANNING_POLICY))
        self.assertGreater(len(calls),1)
    def test_geometry_revision_retires_a_previous_clear_receipt(self):
        blocked=[False]
        grid=TerrainGrid(lambda *a:0.,lambda *a:blocked[0],cell_size=4.)
        start,end=(0.,0.,0.),(4.,0.,0.)
        self.assertTrue(grid.segment_clear(start,end,STATIC_PLANNING_POLICY))
        blocked[0]=True;grid.invalidate_native_review()
        self.assertFalse(grid.segment_clear(start,end,STATIC_PLANNING_POLICY))
    def test_invalid_policy_does_not_create_or_replace_a_pending_consumer(self):
        nav=TerrainNavigator(lambda *a:0.,lambda *a:False,baked_graph=_flat_open_graph())
        with self.assertRaises(ValueError):
            nav.next_target(7,(0.,0.,0.),(20.,0.,0.),('route',1,'lane'),0.,native_capability=(('stock1513',),1.,1.))
        self.assertEqual({},nav.bot_states)
        self.assertEqual({},nav.searches)
    def test_same_static_request_shares_work_between_consumers(self):
        nav=TerrainNavigator(lambda *a:0.,lambda *a:False,baked_graph=_flat_open_graph())
        start,goal=(0.,0.,0.),(20.,0.,0.);request=('route',1,'shared')
        nav.begin_frame(0.)
        try:
            nav.next_target(7,start,goal,request,0.,native_capability=STATIC_PLANNING_POLICY)
            nav.next_target(8,start,goal,request,0.,native_capability=None)
        finally:nav.end_frame()
        self.assertEqual(nav.bot_states[7]['request_key'],nav.bot_states[8]['request_key'])
        self.assertEqual(1,len(nav.searches)+len(nav.paths))
