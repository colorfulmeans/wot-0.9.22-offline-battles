"""Checked shared recovery keeps the original driver's task progress."""
import math
import unittest

from test_player_combat_stop import Scene
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter


class AvoidanceHandoffTests(unittest.TestCase):
    def scene(self, kind='bot', status='clear'):
        scene = Scene(admitted=False)
        # Exercise the original recovery consumer with an already eligible
        # tactical order; the player-route gate has separate report tests.
        scene.owner._route_requires_confirmation = lambda order: False
        scene.target.update(kind=kind)
        scene.raw_order.update(combat_mode='route', target_id=None,
            target_kind=None, move_position=(20., 0., -30.),
            face_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.candidate.update(key=(0, (kind, 2), 0, 'penetration'),
            target_key=(kind, 2), sample=0, line='friendly_blocked',
            mechanical='reachable', blocker=dict(blocker_kind='bot',
                blocker_id=4, blocker_team=1, blocker_position=(0., 0., 20.)))
        scene.probes = []
        scene.probe_status = status
        def probe(candidate, destination, now):
            scene.probes.append((candidate['key'], tuple(destination)))
            return dict(status=scene.probe_status)
        scene.runtime.point_recovery_probe = probe
        return scene

    def test_pending_probe_keeps_route_for_all_turret_types(self):
        for limits in (None, (-math.pi, math.pi, False), (-.2, .2, True)):
            with self.subTest(limits=limits):
                scene = self.scene(status='pending')
                scene.runtime.engine._gun_yaw_limits[1] = limits
                for now in (1., 1.1, 1.2):
                    order = scene.apply(now)
                    self.assertEqual('route', order['combat_mode'])
                    self.assertEqual((20., 0., -30.), order['move_position'])
                    self.assertEqual((20., 0., -30.), order['face_position'])
                    self.assertFalse(scene.owner.stop_allowed)
                self.assertEqual(0, scene.owner._episode)
                self.assertEqual(1, len(set(row[1] for row in scene.probes)))

    def test_source_and_friendly_identity_do_not_replace_the_selected_point(self):
        scene = self.scene()
        order = scene.apply(1.)
        phase = scene.owner._physical_recovery
        self.assertEqual((0, ('bot', 2), 0, 'penetration'), phase['key'])
        self.assertEqual(scene.probes[-1][1], order['move_position'])
        self.assertEqual(2, order['target_id'])
        self.assertNotEqual(4, order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual(1, scene.owner._episode)

    def test_produced_bot_and_human_order_keep_adapter_progress_episode(self):
        for kind in ('bot', 'human'):
            with self.subTest(kind=kind):
                scene = self.scene(kind=kind)
                move = scene.apply(1.)
                self.assertEqual((kind, 2), (move['target_kind'], move['target_id']))
                adapter = BotAdapter('01_karelia', 7)
                state = dict(scene.state, slot=0, dt=.1, now=1., neighbours=(),
                    navigation_status='safe')
                approach = dict(move, combat_mode='advance_contact',
                    move_position=(0., 0., 100.), aim_position=scene.target['position'])
                adapter.decide_with_order(dict(state), approach, lambda *args: True)
                progress = adapter.driver.states[1]['objective_progress']
                command = adapter.decide_with_order(dict(state, now=1.1), move,
                                                   lambda *args: True)
                self.assertIs(progress, adapter.driver.states[1]['objective_progress'])
                self.assertFalse(command['fire_allowed'])
                adapter.decide_with_order(dict(state, now=1.2), approach,
                                          lambda *args: True)
                self.assertIs(progress, adapter.driver.states[1]['objective_progress'])

    def test_priority_target_loss_and_parking_release_the_single_owner(self):
        for cause in ('parking', 'priority', 'target_gone'):
            with self.subTest(cause=cause):
                scene = self.scene()
                scene.apply(1.)
                self.assertIsNotNone(scene.owner._physical_recovery)
                if cause == 'parking':
                    scene.raw_order['parking_phase'] = 'waiting'
                elif cause == 'priority':
                    scene.raw_order['combat_mode'] = 'base_defense'
                else:
                    scene.runtime._targets = ()
                order = scene.apply(2.)
                self.assertEqual((20., 0., -30.), order['move_position'])
                self.assertFalse(scene.owner.stop_allowed)
                self.assertIsNone(scene.owner._physical_recovery)
                self.assertNotIn('_combat_movement_owner', scene.state)


if __name__ == '__main__':
    unittest.main()
