"""Native gun intent survives proof refresh without acquiring movement authority.

The scenes use the production planner, shared attack controller and real
native-query adapters against analytic component geometry. A retained gun
input is never a penetration, lane or first-trigger certificate.
"""
import contextlib
import io
import unittest

from test_player_combat_ownership import OwnershipScene
from test_player_fire_admission_complete import AutomaticFireScene


class FrontVehicleIdentityTests(AutomaticFireScene):
    def test_first_enemy_contact_keeps_network_identity_and_current_pose(self):
        blocker = self.vehicle(8043, (0., 0., 50.), 2)
        record = self.battle._records.pop('bot:8043')
        record['network_id'] = record['state']['id'] = 7
        self.battle._records['bot:7'] = record
        self.step()
        self.assertFalse(self.fire())
        self.assertEqual('auto_front_vehicle', self.control.last_fire_failure)
        receipt = self.admission.receipt['blocker']
        self.assertEqual(8043, receipt['vehicle_id'])
        self.assertEqual(('bot', 7), receipt['actor_key'])
        self.assertEqual(2, receipt['team'])
        self.assertTrue(receipt['hostile'])
        self.assertIsNotNone(receipt['target_pose'])
        self.assertLess(receipt['point'][2], self.target.position.z)
        # This admission fixture does not run the planning callback itself.
        # Admit the newly visible contact through the real shared planner,
        # not a blocker-specific target insertion or selector.
        self.runtime._planner_order(self.now)
        self.assertEqual({('bot', 7), ('bot', 42)},
                         {(row['kind'], row['network_id'])
                          for row in self.runtime.combat_targets()})
        self.assert_unspent()


class SharedNativeAimContinuityTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        self.scene = OwnershipScene()
        self.scene.setUp()
        self.addCleanup(self.scene.doCleanups)
        self.scene.configure(clip=1, burst=1)
        self.enemy = self.scene.eligible_enemy(14, armor=10.)
        self.scene.pose(self.enemy, (24., 0., 50.))
        self.scene.sample_original_lanes()
        # The native barrel remains off the selected point while the policy
        # genuinely acquires it; no shot or alignment outcome is prescribed.
        for unused in range(20):
            self.advance()
            if self.scene.runtime.attack_policy.decision['action'] == 'aim':
                break
        self.assertEqual('aim', self.scene.runtime.attack_policy.decision['action'])
        self.assertEqual(14, self.scene.runtime.state['_diagnostic_aim_intent']['target_id'])
        self.assertFalse(self.scene.launches())

    def advance(self):
        scene = self.scene
        scene.fixture.now += .1
        scene.battle._last_frame_time = scene.now
        scene.control.update(.1, scene.now)
        self.assertIsNone(scene.control.last_control_failure)

    def obstruct(self):
        # A newly observed wall invalidates the line proof, not the selected
        # task's gun-facing intention. Native query verdicts remain real.
        self.scene.world[:] = [((7., -20., 15.), (17., 20., 30.))]
        self.scene.runtime.attack_policy.evaluator.jobs.clear()
        self.scene.runtime.attack_policy.rows.clear()
        self.advance()

    def test_lost_line_proof_does_not_snap_gun_to_hull_forward(self):
        self.obstruct()
        runtime = self.scene.runtime
        self.assertNotEqual('aim', runtime.attack_policy.decision['action'])
        self.assertEqual('enemy', runtime.state['_diagnostic_aim_intent']['owner'])
        self.assertEqual(14, runtime.state['_diagnostic_aim_intent']['target_id'])
        self.assertFalse(runtime.state['gun_aligned'])
        self.assertFalse(runtime._last_order.get('fire_allowed'))
        self.assertFalse(self.scene.launches())
        self.assertFalse(hasattr(runtime.attack_policy, 'search_started'))

    def test_pending_aim_tracks_current_enemy_pose_not_stale_world_point(self):
        old = tuple(self.scene.runtime.weapon.point)
        self.obstruct()
        self.scene.pose(self.enemy, (28., 0., 50.))
        self.advance()
        runtime = self.scene.runtime
        self.assertEqual(14, runtime.state['_diagnostic_aim_intent']['target_id'])
        self.assertNotEqual(old, tuple(runtime.weapon.point))
        self.assertFalse(runtime.state['gun_aligned'])
        self.assertFalse(self.scene.launches())

    def test_restored_native_lane_can_fire_without_restarting_the_gun_task(self):
        self.obstruct()
        scene = self.scene
        episode = scene.runtime.combat_stop._episode
        scene.world[:] = []
        scene.runtime.attack_policy.evaluator.jobs.clear()
        scene.runtime.attack_policy.rows.clear()
        for unused in range(100):
            # Consume the actual installed native gun source and then run
            # the complete fire transaction, not a prescribed ready flag.
            scene.tick()
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual(14, scene.runtime.state['_diagnostic_aim_intent']['target_id'])
        self.assertEqual(episode, scene.runtime.combat_stop._episode)
        self.assertEqual(19, scene.battle._gun_state.ammo[0])

    def test_actual_target_loss_releases_pending_gun_intention(self):
        self.obstruct()
        self.scene.battle._records['bot:14']['spot_visible'] = False
        self.advance()
        self.assertEqual('hull_forward_rest',
                         self.scene.runtime.state['_diagnostic_aim_intent']['owner'])
        self.assertFalse(self.scene.runtime.state['gun_aligned'])
        self.assertFalse(self.scene.launches())

    def test_explicit_return_releases_pending_gun_intention(self):
        self.obstruct()
        self.scene.runtime.set_mission('return_base', {})
        self.advance()
        self.assertFalse(self.scene.runtime.combat_stop.active)
        self.assertEqual('hull_forward_rest',
                         self.scene.runtime.state['_diagnostic_aim_intent']['owner'])
        self.assertFalse(self.scene.launches())


class SharedWorkerAimContinuityTests(unittest.TestCase):
    def scene(self):
        from shared_multi_bot_scene import MultiBotScene
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_workers(2, diverse=False)
        scene.engine.states[12].update(x=20., z=25., position=(20., 0., 25.), speed=0.)
        # A native descriptor observation makes target acquisition precede
        # physical alignment. No readiness result or candidate is injected.
        scene.descriptors['11'].turret.rotationSpeed = .15
        for unused in range(20):
            scene.step()
            binding = scene.engine._actor_controls[11]
            if binding.attack_policy.decision['action'] == 'aim':
                break
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.assertEqual(12, binding.state['_diagnostic_aim_intent']['target_id'])
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])
        return scene, binding

    def obstruct(self, scene, binding):
        scene.world[:] = [((4., -20., -8.), (16., 20., 8.))]
        binding.attack_policy.evaluator.jobs.clear()
        binding.attack_policy.rows.clear()

    def test_worker_keeps_stationary_target_intention_while_native_line_is_pending(self):
        scene, binding = self.scene()
        self.obstruct(scene, binding)
        episode = binding.combat_stop._episode
        for unused in range(4):
            scene.step()
            intent = binding.state['_diagnostic_aim_intent']
            self.assertNotEqual('aim', binding.attack_policy.decision['action'])
            self.assertEqual(('enemy', 'bot', 12),
                (intent['owner'], intent['target_kind'], intent['target_id']))
            self.assertTrue(intent['planning_pending'])
            self.assertFalse(binding.state['gun_aligned'])
            self.assertFalse(binding._last_order['fire_allowed'])
            self.assertEqual(episode, binding.combat_stop._episode)
            self.assertFalse(hasattr(binding.attack_policy, 'search_started'))
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])

    def test_worker_releases_pending_intention_when_actual_enemy_dies(self):
        scene, binding = self.scene()
        self.obstruct(scene, binding)
        scene.step()
        scene.engine.states[12].update(alive=False, health=0.)
        scene.next_plan = 0.
        scene.step()
        intent = binding.state['_diagnostic_aim_intent']
        self.assertEqual('hull_forward_rest', intent['owner'])
        self.assertIsNone(intent['target_id'])
        self.assertFalse(binding.state['gun_aligned'])
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])


if __name__ == '__main__':
    unittest.main()
