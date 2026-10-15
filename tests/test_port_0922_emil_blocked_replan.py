"""Windows288 EMIL II: checked blocked exits must reach the replan owner.

Recorded positions drive the progress owner. Probe replies isolate the local
blocked contract; this does not reconstruct the native map BSP or prove a route.
"""
import unittest
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class EmilBlockedReplanTests(unittest.TestCase):
    def scene(self):
        adapter = BotAdapter('100_thepit', 1)
        adapter.navigation_target = lambda *args: (-14., .26, 18.)
        state = dict(id=2, slot=1, team=1, position=(-14.033, .26, 15.117),
                     yaw=.0032, speed=0., dt=.1, neighbours=[],
                     half_length=3.6, half_width=1.7, pose_clear=lambda yaw: False)
        order = dict(combat_mode='advance', move_position=(-34.059, 0., 96.984),
                     throttle_override=None)
        return adapter, state, order

    def test_recorded_small_back_and_forth_admits_bounded_replans(self):
        adapter, state, order = self.scene()
        requests = []
        for tick in range(300):
            state['position'] = (-14.033, .26, 15.117 if (tick//30)%2 else 13.805)
            command = adapter._drive_order_controls(2, state, state['position'], order,
                                                     lambda *args: False)
            # Replanning cannot fabricate a motion command through these vetoes.
            self.assertEqual(0., command['throttle'])
            if command.get('navigation_replan'):
                requests.append(tick*.1)
        self.assertGreaterEqual(len(requests), 2)
        self.assertLessEqual(len(requests), 3)
        self.assertGreaterEqual(requests[0], 8.)
        self.assertTrue(all(b-a >= 8.-1e-8 for a,b in zip(requests, requests[1:])))
        self.assertEqual('local_blocked', adapter.driver.states[2]['recovery_replan_episode']['cause'])

    def test_clear_progress_does_not_create_a_blockage_episode(self):
        adapter, state, order = self.scene()
        state['pose_clear'] = lambda yaw: True
        adapter.navigation_target = lambda *args: (-14., .26, 100.)
        for tick in range(160):
            state['position'] = (-14., .26, 15.+tick*.15)
            command = adapter._drive_order_controls(2, state, state['position'], order,
                                                     lambda *args: True)
            self.assertFalse(command.get('navigation_replan', False))
        self.assertNotIn('recovery_replan_episode', adapter.driver.states[2])
