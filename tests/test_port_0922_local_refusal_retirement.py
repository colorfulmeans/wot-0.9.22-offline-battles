"""Windows292 rejected local legs must not return through a path handoff.

Recorded IS-7/Tortoise coordinates locate the rejected connectors. The false
proof replies isolate ownership; they are not a reconstruction of native BSP.
"""
import unittest
from unittest import mock
from test_port_0922_navigation import TerrainNavigator


class LocalRefusalRetirementTests(unittest.TestCase):
    cases = (
        ((-172.881795, .280025, 57.252903), (-174.595813, .28, 56.074539),
         (-107.13, 0., -9.016)),
        ((-181.517017, .427849, -36.043957), (-182., .322, -34.),
         (-35.013, 0., -104.376)),
    )

    def scene(self, current, target, goal):
        nav = TerrainNavigator(lambda *args: current[1], lambda *args: False,
                               cell_size=4.)
        state = dict(request_key=('route_join', 18, 'recorded'), path_key='old',
                     index=0, last_position=current, macro_progress_at=0.)
        nav.bot_states[18] = state
        nav._remember_local_fallback(target, goal, state, current, 0.)
        state['last_target'] = target
        return nav, state

    def test_rejected_recorded_connector_survives_private_replan(self):
        for current, target, goal in self.cases:
            with self.subTest(current=current):
                nav, state = self.scene(current, target, goal)
                shared = dict(nav.grid._failed_edges)
                with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False), \
                     mock.patch.object(nav, '_observe_macro_progress', return_value=False):
                    self.assertIsNone(nav._retained_local_fallback(18, current, goal, 1., state))
                self.assertTrue(nav.bot_segment_penalized(18, current, target, 1.1))
                nav.request_replan(18, current, 1.2)
                self.assertTrue(nav.bot_segment_penalized(18, current, target, 1.3))
                self.assertFalse(nav.bot_segment_penalized(19, current, target, 1.3))
                self.assertEqual(shared, nav.grid._failed_edges)
                self.assertFalse(nav.bot_segment_penalized(18, current, target, 20.))

    def test_cross_cell_refusal_does_not_invent_a_located_edge(self):
        current, target, goal = self.cases[1]
        nav, state = self.scene(current, target, goal)
        edge = nav.grid._edge_cells_for_segment(current, target)
        self.assertIsNotNone(edge)
        with mock.patch.object(nav.grid, 'dry_segment_clear', return_value=False), \
             mock.patch.object(nav, '_observe_macro_progress', return_value=False):
            nav._retained_local_fallback(18, current, goal, 1., state)
        self.assertIsNone(nav._active_planning_edge_penalties(18, 1.1))
        self.assertTrue(nav.bot_segment_penalized(18, current, target, 1.1))
        self.assertIsNone(nav._active_planning_edge_penalties(19, 1.1))

    def test_deferred_proof_keeps_its_target_without_retiring_any_edge(self):
        current, target, goal = self.cases[0]
        nav, state = self.scene(current, target, goal)
        def defer(*args):
            nav.grid._proof_deferred = True
            return False
        with mock.patch.object(nav.grid, 'dry_segment_clear', side_effect=defer):
            self.assertEqual(current, nav._retained_local_fallback(18, current, goal, 1., state))
        self.assertEqual(target, state['local_fallback_target'])
        self.assertFalse(nav.bot_failed_edges)
        self.assertNotIn('local_target_retired', state)

    def test_far_obstacle_preserves_clear_prefix_and_other_approaches(self):
        current, target, goal = (2.,0.,2.), (22.,0.,2.), (50.,0.,2.)
        nav, state = self.scene(current, target, goal)
        # Only the distant half of the old chord is blocked. There is no
        # evidence against its first edge or a perpendicular new approach.
        def proof(start, end, *unused):
            return max(start[0], end[0]) < 12.
        self.assertTrue(proof(current, (6.,0.,2.)))
        with mock.patch.object(nav.grid, 'dry_segment_clear', side_effect=proof), \
             mock.patch.object(nav, '_observe_macro_progress', return_value=False), \
             mock.patch.object(nav, '_cancel_bot_searches') as cancel:
            nav._retained_local_fallback(18, current, goal, 1., state)
        cancel.assert_not_called()
        self.assertTrue(nav.bot_segment_penalized(18, current, target, 1.1))
        self.assertFalse(nav.bot_segment_penalized(18, current, (6.,0.,2.), 1.1))
        self.assertFalse(nav.bot_segment_penalized(18, (22.,0.,8.), target, 1.1))
        self.assertFalse(nav.bot_failed_edges)
