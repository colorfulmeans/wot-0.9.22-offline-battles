"""A rejected local leg cannot renew a same-cell path/fallback loop.

Recorded 021603 IS-7 and Object 705 coordinates locate the local pocket.
Proof callbacks are explicit test replies, not a replay of native map BSP.
"""
import unittest
from unittest import mock
from test_port_0922_navigation import TerrainNavigator


class LocalRetryCycleTests(unittest.TestCase):
    def scene(self, position=(-231.4984, 29.6474, -25.3167)):
        nav = TerrainNavigator(lambda *args: position[1], lambda *args: False)
        goal = (-239.244, 0.0, 47.934)
        state = dict(request_key=('route_join', 3, 9), path_key='old', index=0,
                     last_position=position, macro_progress_at=0.0)
        nav.bot_states[3] = state
        return nav, state, position, goal

    def refuse(self, nav, state, position, goal, now):
        # Each verdict is a newly attempted connector. A retired exact point
        # is now rejected before probing and cannot fabricate another verdict.
        attempt = getattr(nav, '_fixture_refusal_attempt', 0)
        nav._fixture_refusal_attempt = attempt + 1
        target = (position[0]+(1.6 if attempt % 2 else -1.6), position[1], position[2]+2.65)
        nav._remember_local_fallback(target, goal, state, position, now)
        state['last_target'] = target
        with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False), \
             mock.patch.object(nav, '_observe_macro_progress', return_value=False):
            self.assertIsNone(nav._retained_local_fallback(3, position, goal, now, state))
        self.assertEqual('unsafe', state['local_target_end_reason'])

    def test_recorded_pockets_keep_retry_age_across_cached_path_handoffs(self):
        for position in ((-231.4984,29.6474,-25.3167),(-237.3578,31.6975,-8.3942)):
            nav, state, current, goal = self.scene(position)
            self.refuse(nav,state,current,goal,0.0)
            self.refuse(nav,state,current,goal,6.0)
            nav._clear_temporary_progress(state)
            nav._reset_macro_progress(state,current,(-230.,29.64,-26.),11.9)
            self.assertFalse(nav._local_retry_stalled(state,current,goal,11.9,True))
            self.assertTrue(nav._local_retry_stalled(state,current,goal,12.,True))
            self.assertEqual(0.0,state['local_retry_progress']['at'])

    def test_private_replan_does_not_fabricate_shared_terrain_failure(self):
        nav,state,current,goal = self.scene()
        self.refuse(nav,state,current,goal,0.)
        self.refuse(nav,state,current,goal,6.)
        nav.paths['shared'] = [current,goal]
        old_failures=dict(nav.grid._failed_edges)
        self.assertTrue(nav._local_retry_stalled(state,current,goal,12.,True))
        self.assertTrue(nav.request_replan(3,current,12.))
        self.assertEqual(old_failures,nav.grid._failed_edges)
        self.assertEqual([current,goal],nav.paths['shared'])
        self.assertEqual(1,state['local_retry_progress']['replans'])
        self.assertEqual('pending',state['navigation_status'])

    def test_next_target_handoff_actually_requests_a_private_replan(self):
        nav,state,current,goal = self.scene()
        path_key=('route_join',3,'recorded_cycle')
        state['request_key']=nav._cache_key(path_key,goal)
        self.refuse(nav,state,current,goal,0.)
        self.refuse(nav,state,current,goal,6.)
        with mock.patch.object(nav,'request_replan',wraps=nav.request_replan) as replan:
            nav.next_target(3,current,goal,path_key,12.)
            replan.assert_called_once_with(3,current,12.)
        self.assertEqual(1,state['replan_generation'])

    def test_new_realised_cell_restarts_progress_even_when_away_from_goal(self):
        nav,state,current,goal = self.scene()
        self.refuse(nav,state,current,goal,0.)
        self.refuse(nav,state,current,goal,6.)
        moved=(current[0]+nav.grid.cell_size*2,current[1],current[2])
        self.assertFalse(nav._local_retry_stalled(state,moved,goal,13.,True))
        self.assertEqual(13.,state['local_retry_progress']['at'])
        self.assertEqual(0,state['local_retry_progress']['failures'])

    def test_single_refusal_or_deferred_proof_does_not_trigger_replan(self):
        nav,state,current,goal = self.scene()
        self.refuse(nav,state,current,goal,0.)
        self.assertFalse(nav._local_retry_stalled(state,current,goal,30.,True))
        state.pop('local_retry_progress')
        target=(current[0],current[1],current[2]+3.)
        nav._remember_local_fallback(target,goal,state,current,0.)
        state['last_target']=target
        def deferred(*args):
            nav.grid._native_proof_revision+=1
            return False
        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=deferred):
            self.assertEqual(current,nav._retained_local_fallback(3,current,goal,1.,state))
        self.assertNotIn('local_retry_progress',state)

    def test_proof_budget_deferral_is_not_a_geometric_refusal(self):
        nav,state,current,goal = self.scene()
        target=(current[0],current[1],current[2]+3.)
        nav._remember_local_fallback(target,goal,state,current,0.)
        state['last_target']=target
        def deferred(*args):
            nav.grid._proof_deferred=True
            return False
        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=deferred):
            self.assertEqual(current,nav._retained_local_fallback(3,current,goal,1.,state))
        self.assertNotIn('local_retry_progress',state)
        self.assertEqual(target,state['local_fallback_target'])

    def test_changed_request_hold_and_arrival_retire_the_episode(self):
        for change in ('request','hold','arrival'):
            nav,state,current,goal = self.scene()
            self.refuse(nav,state,current,goal,0.)
            if change=='request':state['request_key']=('new',)
            self.assertFalse(nav._local_retry_stalled(state,
                goal if change=='arrival' else current,goal,30.,change!='hold'))
            self.assertNotIn('local_retry_progress',state)

    def test_shortcut_hold_clears_recorded_wz132a_retry_age(self):
        nav,state,current,goal = self.scene((-5.19,-4.82,25.39))
        self.refuse(nav,state,current,goal,0.)
        path_key=('route_join',3,'hold')
        state['request_path_key']=path_key
        state['planned_goal']=goal
        self.assertIsNone(nav.retained_local_target(3,current,goal,path_key,36.,False))
        self.assertNotIn('local_retry_progress',state)

    def test_direct_hold_and_arrival_clear_old_local_retry(self):
        for arrived in (False,True):
            nav,state,current,goal = self.scene()
            self.refuse(nav,state,current,goal,0.)
            nav.observe_direct_target(3,goal if arrived else current,goal,
                ('direct',3),36.,movement_intent=arrived)
            self.assertNotIn('local_retry_progress',state)

    def test_retry_is_bounded_and_needs_more_actual_refusals(self):
        nav,state,current,goal = self.scene()
        self.refuse(nav,state,current,goal,0.)
        self.refuse(nav,state,current,goal,1.)
        self.assertTrue(nav._local_retry_stalled(state,current,goal,12.,True))
        self.assertFalse(nav._local_retry_stalled(state,current,goal,30.,True))
        self.refuse(nav,state,current,goal,30.)
        self.refuse(nav,state,current,goal,31.)
        self.assertTrue(nav._local_retry_stalled(state,current,goal,31.,True))


if __name__ == '__main__':
    unittest.main()
