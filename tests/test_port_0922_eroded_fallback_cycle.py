"""Report test143 Chieftain's consumed eroded origin and repeated local tip.

The actual winter Himmelsdorf bake/recorded poses are used. Native support is
an explicit level plane and walls are controlled replies, not a world replay.
"""
import json
import math
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator, LocalDriver


CURRENT=(254.28075302805212,1.230116367340088,296.1028479182326)
CONSUMED=(254.5722747392958,1.258,294.9329327325988)
GOAL=(360.738,0.,-274.055)


class ErodedFallbackCycleTests(unittest.TestCase):
    def scene(self, blocked=False, ground=1.23):
        bake=json.loads((Path(__file__).resolve().parents[1]/'navgraphs/86_himmelsdorf_winter.json').read_text())
        support=mock.Mock(return_value=ground)
        collision=mock.Mock(return_value=blocked)
        nav=TerrainNavigator(support,collision,baked_graph=bake)
        if blocked:
            # A thin-wall refusal marks this region for native reproof, as
            # the report's nonempty native_review_cells does.
            nav.grid.review_native_corridor(CURRENT,(CURRENT[0]+1.,CURRENT[1],CURRENT[2]))
        state=dict(request_key=(('route_join',19,2,'hill',11,0,0),(165,6)),
            replan_generation=0,temporary_stalled=True,
            temporary_visited_cells={nav.grid.cell_for(CURRENT),nav.grid.cell_for(CONSUMED)},
            pending_since=0.)
        state['local_completed_target']=(CONSUMED,nav._local_fallback_intent(GOAL,state))
        nav.bot_states[19]=state
        return nav,state,support,collision

    def test_recorded_wait_produces_checked_new_tip_and_actual_drive_input(self):
        nav,state,support,collision=self.scene()
        target=nav._pending_target(19,CURRENT,GOAL,80.,state,allow_last_target=False)
        self.assertGreater(math.hypot(target[0]-CURRENT[0],target[2]-CURRENT[2]),1.5)
        self.assertNotIn(nav.grid.cell_for(target),state['temporary_visited_cells'])
        self.assertEqual(CURRENT,state['local_fallback']['current'])
        self.assertEqual(target,state['local_fallback']['selected'])
        self.assertEqual(1,state['local_fallback']['accepted'])
        yaw=math.atan2(target[0]-CURRENT[0],target[2]-CURRENT[2])
        control=LocalDriver().drive(19,3,CURRENT,yaw,0.,.1,target,(),lambda *a: True,
            half_length=3.550792932510376,half_width=1.557752013206482)
        self.assertGreater(control['throttle'],0.)
        self.assertLessEqual(collision.call_count,3)

    def test_consumed_eroded_anchor_is_retired_only_after_supported_reentry(self):
        nav,state,unused,unused2=self.scene()
        self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(CONSUMED)))
        self.assertIsNotNone(nav.grid._baked_cell_height(nav.grid.cell_for(CURRENT)))
        self.assertEqual(CURRENT,nav._local_fallback_origin(CURRENT,GOAL,state))
        self.assertNotIn('local_completed_target',state)
        state['local_completed_target']=(CONSUMED,nav._local_fallback_intent(GOAL,state))
        self.assertEqual(CONSUMED,nav._local_fallback_origin(CONSUMED,GOAL,state))

    def test_missing_origin_skips_visited_nearest_node_before_one_native_proof(self):
        nav,state,unused,collision=self.scene()
        receipt={}
        tip=nav.grid.safe_local_target(CONSUMED,GOAL,80.,diagnostic=receipt,
            excluded_target_cells=state['temporary_visited_cells'])
        self.assertIsNotNone(tip)
        self.assertNotIn(nav.grid.cell_for(tip),state['temporary_visited_cells'])
        self.assertEqual(tip,receipt['selected'])
        self.assertLessEqual(collision.call_count,1)

    def test_real_wall_still_holds_and_does_not_fill_missing_bake(self):
        nav,state,unused,unused2=self.scene(blocked=True)
        target=nav._pending_target(19,CURRENT,GOAL,80.,state,allow_last_target=False)
        self.assertEqual(CURRENT,target)
        self.assertIsNone(nav.grid._baked_cell_height(nav.grid.cell_for(CONSUMED)))

    def test_unknown_support_still_holds(self):
        nav,state,unused,unused2=self.scene(ground=None)
        self.assertEqual(CONSUMED,nav._pending_target(19,CONSUMED,GOAL,80.,state,allow_last_target=False))

    def test_retained_visited_history_is_not_a_normal_driving_prohibition(self):
        nav,state,unused,unused2=self.scene()
        state['temporary_stalled']=False
        tip=nav._new_local_fallback(19,CURRENT,CURRENT,GOAL,80.,(),state)
        self.assertIsNotNone(tip)
        self.assertNotIn('visited_rejected',state['local_fallback'])

    def test_completed_supported_corner_keeps_fixed_origin(self):
        nav,state,unused,unused2=self.scene()
        supported=(254.,1.258,298.)
        state['local_completed_target']=(supported,nav._local_fallback_intent(GOAL,state))
        self.assertEqual(supported,nav._local_fallback_origin(CURRENT,GOAL,state))

    def test_another_order_does_not_inherit_the_eroded_reentry_exclusions(self):
        nav,state,unused,unused2=self.scene()
        state['request_key']=('different_order',)
        nav._safe_fallback_target(19,CURRENT,GOAL,80.,(),state)
        self.assertNotIn('visited_rejected',state['local_fallback'])
