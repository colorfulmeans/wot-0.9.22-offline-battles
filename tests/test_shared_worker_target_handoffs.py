"""The worker's physical recovery consumes its resolved shared intention.

The scene runs real BotPlanner orders, BotControlBinding, AttackPolicy, native
geometry and LocalDriver. Only external vehicle poses and component armour
change; no candidate, policy decision or recovery marker is prescribed.
"""
import copy
import unittest

from shared_multi_bot_scene import MultiBotScene


class SharedWorkerTargetHandoffTests(unittest.TestCase):
    def scene_with_friendly_recovery(self):
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_workers(6, diverse=False)
        engine = scene.engine
        for actor, point in ((15, (120., 0., 120.)),
                             (16, (150., 0., 150.))):
            self.move_actor(scene, actor, point)
            self.set_armor(scene, actor, 1000.)
        for unused in range(5):
            scene.step()
        binding = engine._actor_controls[11]
        self.assertEqual(('bot', 14), binding.attack_policy.current_target_key())
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.move_actor(scene, 12, (-16., 0., 0.))
        for unused in range(15):
            scene.step()
            if 11 in engine._friendly_repositions:
                break
        self.assertEqual('firing_position', binding.attack_policy.decision['action'])
        marker = engine._friendly_repositions[11]
        self.assertEqual(14, marker['target_id'])
        self.assertEqual((14, 'bot', 12), marker['identity'][:3])
        self.assertGreater(marker['deadline'], scene.now)
        self.assertIsNone(binding.attack_policy.search_started,
                          'A real friendly blocker is not an armour failure.')
        return scene, binding, marker

    @staticmethod
    def move_actor(scene, actor, point):
        scene.engine.states[actor].update(
            x=point[0], y=point[1], z=point[2], position=point, speed=0.)

    @staticmethod
    def set_armor(scene, actor, armor):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(scene.descriptors[str(actor)], name).materials[0].armor = armor

    def test_nearer_macro_hint_cannot_cancel_or_restart_retained_recovery(self):
        scene, binding, marker = self.scene_with_friendly_recovery()
        original = copy.deepcopy(marker)
        route = copy.deepcopy(binding.state['route'])
        self.move_actor(scene, 15, (-5., 0., 5.))
        scene.next_plan = 0.
        for unused in range(4):
            scene.step()
            # The ordinary initial hint changes naturally with distance. The
            # native armour review keeps the existing blocked target instead
            # of laundering that hint into a second physical target owner.
            self.assertIsNone(scene.engine._server_orders[11]['target_id'])
            self.assertEqual(15, scene.engine._server_orders[11]['initial_target_hint']['target_id'])
            self.assertEqual(('bot', 14), binding.attack_policy.current_target_key())
            self.assertEqual('firing_position', binding.attack_policy.decision['action'])
            self.assertIs(marker, scene.engine._friendly_repositions.get(11),
                          'The raw macro hint cancelled the retained shared recovery.')
            self.assertEqual(original, marker,
                             'A hint change must not renew the existing recovery deadline.')
            self.assertEqual(route, binding.state['route'])
            command = scene.engine._decision_cache[11][3]
            self.assertEqual('friendly_lane_reposition', command['combat_mode'])
            self.assertEqual(14, command['target_id'])
            self.assertEqual(marker['destination'], command['move_position'])

    def test_actual_shared_replacement_retires_previous_recovery(self):
        scene, binding, marker = self.scene_with_friendly_recovery()
        self.set_armor(scene, 15, 30.)
        self.move_actor(scene, 15, (-5., 0., 5.))
        scene.next_plan = 0.
        scene.step()
        self.assertEqual(('bot', 15), binding.attack_policy.current_target_key())
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.assertNotIn(11, scene.engine._friendly_repositions)
        event = binding.state['_friendly_reposition_event']
        self.assertEqual('target_changed', event['outcome'])
        self.assertEqual(marker['identity'], event['marker']['identity'])

    def test_explicit_shared_hold_task_takes_over_recovery(self):
        scene, binding, unused_marker = self.scene_with_friendly_recovery()
        binding.set_mission('hold_position')
        scene.step()
        self.assertEqual('hold_position', binding._mission['action'])
        self.assertNotIn(11, scene.engine._friendly_repositions)
        self.assertFalse(binding.combat_stop.active)
        self.assertEqual(0., binding.state['speed'])
        self.assertFalse(binding._last_order.get('fire_allowed'))

    def test_actual_target_death_retires_recovery(self):
        scene, binding, unused_marker = self.scene_with_friendly_recovery()
        scene.engine.states[14].update(alive=False, health=0.)
        scene.next_plan = 0.
        scene.step()
        self.assertNotEqual(('bot', 14), binding.attack_policy.current_target_key())
        self.assertNotIn(11, scene.engine._friendly_repositions)
        self.assertNotEqual(14, binding.state.get('target_id'))


if __name__ == '__main__':
    unittest.main()
