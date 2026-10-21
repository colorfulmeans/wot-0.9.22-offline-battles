"""Replay the E5 fine-grid gate and prove a failed push cannot reclaim recovery."""
import json
import math
from pathlib import Path
import types
import unittest
import test_port_0922_bot_runtime as bots
import test_port_0922_oct03_bot_egress as egress
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922 import prebaked_navigation as pn


class E5GridTests(unittest.TestCase):
    def test_recorded_one_metre_exit_is_not_vetoed_by_a_four_metre_shore(self):
        module = bots._load()
        graph = pn.with_shore_hazards(json.loads((Path(__file__).resolve().parents[1]/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        runtime = module.BotRuntime(1)
        runtime.baked_graph = graph
        runtime.navigator = types.SimpleNamespace(grid=grid)
        position = (131.36720942127297, -8.927963256835938, -271.86953915534394)
        yaw = -1.3146007912838868
        evidence = {}
        self.assertTrue(runtime._planner_corridor_clear(position, yaw, 0., hazard_only=True, evidence=evidence))
        self.assertEqual(1., evidence['corridor_cell_size'])
        self.assertEqual('local_mesh', evidence['corridor_resolution'])
        end = (position[0]+math.sin(yaw)*4., position[1], position[2]+math.cos(yaw)*4.)
        self.assertTrue(grid.segment_has_motion_hazard(position, end, 13))
        # The actual future shore stays dangerous; only the candidate horizon changes.
        shore = (127., position[1], -271.)
        self.assertFalse(pn.pose_is_safe(graph, shore, hazard_mask=9))


class E5PushTests(unittest.TestCase):
    wreck_scene = egress.EgressTests.wreck_scene

    def test_unknown_probe_does_not_exhaust_the_existing_attempt(self):
        for reason in ('native_probe_deferred', 'native_probe_unavailable',
                       'direction_callback_exception', 'callback_receipt_unavailable'):
            adapter, state, order = self.wreck_scene()
            def probe(*a):
                return False
            probe.last_receipt = dict(reason=reason)
            self.assertIsNone(adapter._wreck_push_plan(state['id'], state,
                state['position'], order, probe))
            self.assertEqual('world_probe_pending', state['_wreck_push_evidence']['phase'])
            self.assertFalse(adapter._wreck_attempts[state['id']]['exhausted'])
            self.assertIsNotNone(adapter._wreck_push_plan(state['id'], state,
                state['position'], order, lambda *a: True))

    def test_committed_reverse_owns_until_its_existing_terminal_condition(self):
        adapter, state, order = self.wreck_scene()
        self.assertIsNotNone(adapter._wreck_push_plan(state['id'], state,
            state['position'], order, lambda *a: True))
        driver = adapter.driver._state(state['id'], state['slot'], state['position'])
        for ordinary in (True, False):
            driver['recovery_time'] = .4 if ordinary else 0.
            driver['navigation_wait'] = dict(active=not ordinary, completed=False)
            self.assertIsNone(adapter._wreck_push_plan(state['id'], state,
                state['position'], order, lambda *a: True))
            self.assertEqual('driver_recovery_active', state['_wreck_push_evidence']['phase'])
            self.assertFalse(adapter._wreck_attempts[state['id']]['exhausted'])
        driver['navigation_wait']['completed'] = True
        self.assertIsNotNone(adapter._wreck_push_plan(state['id'], state,
            state['position'], order, lambda *a: True))

    def test_denied_push_has_terminal_handoff_and_does_not_reclaim_each_clear_frame(self):
        adapter, state, order = self.wreck_scene()
        first = adapter.decide_with_order(state, order, lambda *a: False)
        self.assertNotEqual('wreck_push', first['recovery_mode'])
        self.assertEqual('world_corridor_refused', first['wreck_push']['terminal']['reason'])
        for frame in range(40):
            command = adapter.decide_with_order(state, order, lambda *a: frame % 2 == 0)
            self.assertNotEqual('wreck_push', command['recovery_mode'])
        self.assertTrue(adapter._wreck_history[state['id']][2]['exhausted'])
        commands = [adapter.decide_with_order(state, order, lambda *a: True) for unused in range(20)]
        self.assertTrue(any(c['throttle'] > 0. for c in commands))

    def test_a_real_wreck_displacement_still_renews_the_existing_encounter(self):
        adapter, state, order = self.wreck_scene()
        adapter.decide_with_order(state, order, lambda *a: False)
        state['neighbours'][0]['position'] = (0., 0., 10.1)
        command = adapter.decide_with_order(state, order, lambda *a: True)
        self.assertEqual('wreck_push', command['recovery_mode'])

    def test_successful_push_keeps_original_progress_and_motor_budget(self):
        adapter, state, order = self.wreck_scene()
        for frame in range(160):
            state['position'] = (0., 0., frame*.03)
            command = adapter.decide_with_order(state, order, lambda *a: True)
            self.assertEqual('wreck_push', command['recovery_mode'])
