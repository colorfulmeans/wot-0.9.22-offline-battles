"""A reached cached corner cannot renew its incoming leg after a safe detour.

Tortoise/KV-3 positions come from 034127; geometry replies are explicit seams,
not a replay of the native BSP or a claim of in-client acceptance.
"""
import unittest
from contextlib import ExitStack
from unittest import mock
from test_port_0922_navigation import TerrainNavigator


class ReachedCornerTests(unittest.TestCase):
    def scene(self, corner=(78., .219, -34.)):
        nav = TerrainNavigator(lambda *args: corner[1], lambda *args: False)
        goal = (corner[0], corner[1], corner[2] + 60.)
        path_key = ('route_join', 3, 'reached_corner')
        key = nav._cache_key(path_key, goal)
        path = [corner, (corner[0], corner[1], corner[2] + 10.), goal]
        state = dict(request_key=key, request_path_key=path_key, planned_goal=goal,
                     planned_at=0., path_key=key, index=0, last_position=corner,
                     progress_time=0., last_target=corner, replan_generation=0)
        nav.paths[key] = path
        nav.bot_states[3] = state
        return nav, state, goal, path_key, key, path

    def seams(self, nav, key, path):
        stack = ExitStack()
        for obj, name, kwargs in (
            (nav, 'tick', dict(return_value=None)),
            (nav, '_observe_macro_progress', dict(return_value=False)),
            (nav, '_path', dict(return_value=(key, path))),
            (nav.grid, 'segment_clear', dict(return_value=True)),
            (nav.grid, 'segment_penalty', dict(return_value=0.)),
            (nav.grid, 'segment_has_baked_hazard', dict(return_value=False)),
            (nav, '_planned_next_segment_clear', dict(return_value=False)),
            (nav, '_lookahead_index', dict(side_effect=lambda current, path, index, *args: index)),
        ):
            stack.enter_context(mock.patch.object(obj, name, **kwargs))
        return stack

    def test_recorded_arrival_detour_does_not_reissue_consumed_corner(self):
        for corner, away in (
            ((78.,.219,-34.), (79.33,.20,-35.22)),
            ((-142.,.25,-70.), (-140.92,.25,-66.72)),
        ):
            nav,state,goal,path_key,key,path = self.scene(corner)
            def fallback(bot_id,current,goal,now,avoid,state,*args):
                state['last_target'] = away
                nav._remember_local_fallback(away,goal,state,current,now)
                return away
            with self.seams(nav,key,path), \
                 mock.patch.object(nav,'_fallback_target',side_effect=fallback), \
                 mock.patch.object(nav,'request_replan',wraps=nav.request_replan) as replan:
                self.assertEqual(away,nav.next_target(3,corner,goal,path_key,0.))
                self.assertEqual(corner,state['reached_path_corner']['point'])
                # Arriving at the safe local leg formerly made the old corner
                # available again, despite its outgoing edge remaining blocked.
                self.assertEqual(away,nav.next_target(3,away,goal,path_key,1.))
                replan.assert_called_once_with(3,away,1.)
            self.assertEqual(1,state['reached_corner_replans'])
            self.assertEqual('pending',state['navigation_status'])
            self.assertEqual(away,state['recovery_start'])
            self.assertEqual({},nav.grid._failed_edges)

    def test_old_handoff_reproduces_return_to_reached_tortoise_corner(self):
        nav,state,goal,path_key,key,path = self.scene()
        away=(79.33,.20,-35.22)
        self.stamp(state,key,path)
        state['last_target']=away
        with self.seams(nav,key,path), \
             mock.patch.object(nav,'_resume_reached_corner',side_effect=lambda bot,state,current,path,key,index,now: index):
            self.assertEqual(path[0],nav.next_target(3,away,goal,path_key,1.))

    def stamp(self, state, key, path):
        state['reached_path_corner'] = dict(key=key,index=0,point=path[0],request=state['request_key'])

    def test_proved_forward_connector_advances_without_replan(self):
        nav,state,goal,path_key,key,path = self.scene()
        self.stamp(state,key,path)
        away=(79.33,.20,-35.22)
        with mock.patch.object(nav,'_planned_next_segment_clear',return_value=True) as proof, \
             mock.patch.object(nav,'request_replan') as replan:
            self.assertEqual(1,nav._resume_reached_corner(3,state,away,path,key,0,1.))
        proof.assert_called_once_with(away,path,0,1.,3)
        replan.assert_not_called()
        self.assertNotIn('reached_path_corner',state)

    def test_deferred_proof_holds_without_marking_collision_or_replanning(self):
        for revision in (False,True):
            nav,state,goal,path_key,key,path = self.scene()
            self.stamp(state,key,path)
            def deferred(*args):
                if revision: nav.grid._native_proof_revision += 1
                else: nav.grid._proof_deferred = True
                return False
            with mock.patch.object(nav,'_planned_next_segment_clear',side_effect=deferred), \
                 mock.patch.object(nav,'request_replan') as replan:
                self.assertIsNone(nav._resume_reached_corner(3,state,(81.,.2,-34.),path,key,0,1.))
            replan.assert_not_called()
            self.assertIn('reached_path_corner',state)
            self.assertEqual('pending',state['navigation_status'])
            self.assertEqual({},nav.grid._failed_edges)

    def test_new_path_or_request_can_legitimately_revisit_setup(self):
        for change in ('path','request','point','index'):
            nav,state,goal,path_key,key,path = self.scene()
            self.stamp(state,key,path)
            index=0
            if change=='path': key=('new',)
            elif change=='request': state['request_key']=('new',)
            elif change=='point': path=list(path);path[0]=(78.,.219,-33.)
            else: index=1
            with mock.patch.object(nav,'_planned_next_segment_clear') as proof:
                self.assertEqual(index,nav._resume_reached_corner(3,state,(81.,.2,-34.),path,key,index,1.))
            proof.assert_not_called()

    def test_hold_and_private_replan_retire_receipt(self):
        for change in ('hold','replan','direct_hold','arrival'):
            nav,state,goal,path_key,key,path = self.scene()
            self.stamp(state,key,path)
            if change=='hold':
                nav.retained_local_target(3,path[0],goal,path_key,1.,False)
            elif change in ('direct_hold','arrival'):
                nav.observe_direct_target(3,goal if change=='arrival' else path[0],goal,path_key,1.,change=='arrival')
            else:
                nav.request_replan(3,path[0],1.)
            self.assertNotIn('reached_path_corner',state)


if __name__ == '__main__':
    unittest.main()
