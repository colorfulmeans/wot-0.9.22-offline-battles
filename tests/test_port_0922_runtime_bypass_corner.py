"""020500 FV4005/ST-I: consuming a bypass must consume its source corner.

Controlled connector proofs exercise ownership, not native map BSP.
"""
import unittest
from unittest import mock
import test_port_0922_navigation_reached_corner as corner_fixture


class RuntimeBypassCornerTests(unittest.TestCase):
    cases = (
        ((-174., .708, -78.), (-170.506908, .647, -80.802422),
         (-170.73, .65, -80.71)),
        ((-178., .905, -78.), (-166.209041, .493, -80.230085),
         (-167.33, .51, -80.20)),
    )

    def test_rejected_cached_join_does_not_restart_its_consumed_entry(self):
        fixture=corner_fixture.ReachedCornerTests()
        corner=(-302.,0.,-194.)
        current=(-302.129,0.,-191.851)
        for deferred in (False,True):
            nav,state,goal,path_key,key,path=fixture.scene(corner)
            path[1]=(-306.,0.,-190.)
            state.update(index=1,last_target=path[1])
            def proof(*unused):
                nav.grid._proof_deferred=deferred
                return False
            with self.subTest(deferred=deferred),fixture.seams(nav,key,path), \
                 mock.patch.object(nav.grid,'segment_clear',side_effect=proof), \
                 mock.patch.object(nav,'request_replan',wraps=nav.request_replan) as replan, \
                 mock.patch.object(nav,'_fallback_target',return_value=current):
                result=nav.next_target(3,current,goal,path_key,1.)
                self.assertEqual(current,result)
                self.assertNotEqual(corner,result)
                replan.assert_not_called()
                self.assertEqual(1,state['index'])

    def test_clear_cached_setup_remains_available_for_a_real_turn(self):
        fixture=corner_fixture.ReachedCornerTests()
        corner=(-302.,0.,-194.)
        current=(-302.129,0.,-191.851)
        nav,state,goal,path_key,key,path=fixture.scene(corner)
        path[1]=(-306.,0.,-190.)
        state['last_target']=current
        # Passing the setup's projection is a heuristic, not a collision.
        # The outgoing edge is not proved; returning to the clear setup is
        # still a legal way to make this actual bend.
        with fixture.seams(nav,key,path), \
             mock.patch.object(nav,'_fallback_target') as fallback:
            self.assertEqual(corner,nav.next_target(3,current,goal,path_key,1.))
        fallback.assert_not_called()
        self.assertEqual(0,state['index'])

    def scene(self, corner, bypass):
        fixture = corner_fixture.ReachedCornerTests()
        nav, state, goal, path_key, key, path = fixture.scene(corner)
        state['last_target'] = corner
        nav.remember_runtime_target(3, (corner[0],corner[1],corner[2]-4.),
                                    goal,bypass,0.,corner)
        return fixture,nav,state,goal,path_key,key,path

    def test_recorded_bypass_arrival_replans_instead_of_returning_to_source(self):
        for corner,bypass,current in self.cases:
            fixture,nav,state,goal,path_key,key,path = self.scene(corner,bypass)
            with fixture.seams(nav,key,path), \
                 mock.patch.object(nav,'request_replan',wraps=nav.request_replan) as replan:
                self.assertEqual(current,nav.next_target(3,current,goal,path_key,1.))
                replan.assert_called_once_with(3,current,1.)
            self.assertEqual('pending',state['navigation_status'])
            self.assertEqual({},nav.grid._failed_edges)

    def test_a_proved_outgoing_leg_advances_from_the_actual_bypass_pose(self):
        corner,bypass,current = self.cases[0]
        fixture,nav,state,goal,path_key,key,path = self.scene(corner,bypass)
        with fixture.seams(nav,key,path), \
             mock.patch.object(nav,'_planned_next_segment_clear',return_value=True) as proof:
            target=nav.next_target(3,current,goal,path_key,1.)
        self.assertNotEqual(corner,target)
        self.assertIn(mock.call(current,path,0,1.,3),proof.call_args_list)
        self.assertEqual(1,state['index'])

    def test_a_deferred_outgoing_proof_keeps_receipt_and_does_not_replan(self):
        corner,bypass,current = self.cases[0]
        fixture,nav,state,goal,path_key,key,path = self.scene(corner,bypass)
        def deferred(*unused):
            nav.grid._proof_deferred=True
            return False
        with fixture.seams(nav,key,path), \
             mock.patch.object(nav,'_planned_next_segment_clear',side_effect=deferred), \
             mock.patch.object(nav,'request_replan') as replan:
            self.assertEqual(current,nav.next_target(3,current,goal,path_key,1.))
        replan.assert_not_called()
        self.assertEqual(corner,state['reached_path_corner']['point'])

    def test_not_yet_reached_bypass_is_retained_without_consuming_corner(self):
        corner,bypass,unused = self.cases[0]
        fixture,nav,state,goal,path_key,key,path = self.scene(corner,bypass)
        current=(corner[0],corner[1],corner[2]-4.)
        with mock.patch.object(nav.grid,'dry_segment_clear',return_value=True):
            self.assertEqual(bypass,nav._retained_local_fallback(3,current,goal,1.,state))
        self.assertNotIn('reached_path_corner',state)

    def test_stale_path_or_nonvertex_override_cannot_consume_a_corner(self):
        for change in ('path','request','index','nonvertex'):
            corner,bypass,current = self.cases[0]
            fixture,nav,state,goal,path_key,key,path = self.scene(corner,bypass)
            if change=='path':state['path_key']=('new',)
            elif change=='request':state['request_key']=('new',)
            elif change=='index':state['index']=1
            else:
                nav.remember_runtime_target(3,current,goal,bypass,.5,(100.,0.,100.))
            nav._retained_local_fallback(3,current,goal,1.,state)
            self.assertNotIn('reached_path_corner',state)
