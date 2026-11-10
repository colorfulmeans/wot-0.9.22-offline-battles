"""Gun-only ownership survives worker cache slices, never expired fire evidence.

These regressions run the real shared producer, driver, gun input consumer,
policy and physical trigger pipeline. Only native observations are synthetic.
The worker's actual 10 Hz callback is deliberately late enough to contain a
new-decision slice followed by a cached physical slice.
"""
import contextlib
import copy
import io
import unittest

from shared_multi_bot_scene import MultiBotScene
from test_player_combat_ownership import OwnershipScene


class SharedGunIntentLeaseTests(unittest.TestCase):
    def scene(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_workers(4, diverse=False, schedule='worker10')
        positions = ((11, (0., 0., -25.)), (12, (100., 0., -25.)),
                     (13, (0., 0., 20.)), (14, (25., 0., 40.)))
        for actor, point in positions:
            scene.engine.states[actor].update(x=point[0], z=point[2],
                position=point, speed=0.)
            scene.descriptors[str(actor)].turret.rotationSpeed = .15
        # The normal closest-contact hint is 13. The real native armour
        # evaluator selects 14, so the protected hold needs gun-only handoff.
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(scene.descriptors['13'], name).materials[0].armor = 5000.
        scene.step(.1)
        for binding in scene.engine._actor_controls.values():
            binding.set_mission('hold_position', {})
        binding = scene.engine._actor_controls[11]
        for unused in range(30):
            scene.step(.1)
            intent = binding.state.get('_diagnostic_aim_intent') or {}
            if (binding.attack_policy.decision['action'] == 'aim' and
                    intent.get('target_id') == 14 and
                    binding._gun_handoff is not None):
                break
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.assertIsNotNone(binding._gun_handoff)
        self.assertEqual(13, binding.combat_stop.task_order['initial_target_hint']['target_id'])
        self.assertFalse(binding.combat_stop.stop_allowed)
        self.assertEqual(14, binding.state['_diagnostic_aim_intent']['target_id'])
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])
        return scene, binding

    def observe_aim(self, scene):
        rows = []
        native = scene.engine._update_gun_aim
        def observe(state, command, target, *args, **kwargs):
            before = state['turret_yaw']
            result = native(state, command, target, *args, **kwargs)
            if state['id'] == 11:
                binding = scene.engine._actor_controls[11]
                rows.append(dict(disposition=state.get('_planning_disposition'),
                    intent=copy.deepcopy(state['_diagnostic_aim_intent']),
                    before=before, after=state['turret_yaw'],
                    action=binding.attack_policy.decision['action'],
                    solution=copy.deepcopy(command.get('_ballistic_solution')),
                    fire_allowed=command.get('fire_allowed'),
                    movement=dict((name, copy.deepcopy(command.get(name))) for name in
                        ('move_position', 'face_position', 'throttle', 'turn',
                         'movement_intent', 'combat_mode'))))
            return result
        scene.engine._update_gun_aim = observe
        return rows

    def cached_physics_step(self, scene):
        scene.fixture.now += .05
        scene.battle._last_frame_time = scene.now
        scene.sync_native_poses()
        return scene.engine._run_update_once(.05, scene.now, [], [], False, True)

    def test_parked_worker_keeps_same_target_on_every_cached_physical_slice(self):
        scene, binding = self.scene()
        rows = self.observe_aim(scene)
        episode = binding.combat_stop._episode
        position = tuple(binding.state['position'])
        for unused in range(4):
            scene.step(.3)
        self.assertTrue(any(row['disposition'] == 'new_decision' for row in rows))
        self.assertTrue(any(row['disposition'] == 'cache_reused' for row in rows))
        for row in rows:
            self.assertEqual(('enemy', 'bot', 14), tuple(row['intent'].get(name)
                for name in ('owner', 'target_kind', 'target_id')), row)
            self.assertGreater(row['intent']['turret_yaw'], .2, row)
            self.assertEqual('hold', row['movement']['combat_mode'], row)
            self.assertEqual((0., 0.), (row['movement']['throttle'], row['movement']['turn']), row)
            self.assertFalse(row['movement']['movement_intent'], row)
        self.assertEqual(position, tuple(binding.state['position']))
        self.assertEqual(episode, binding.combat_stop._episode)

    def test_absent_physical_target_keeps_aim_action_as_fresh_motion_only(self):
        scene, binding = self.scene()
        candidate = binding.attack_policy.decision['candidate']
        self.assertIsNotNone(binding.current_attack_candidate(binding.state, candidate['target']))
        command = dict(binding._last_order, _ballistic_solution=None,
                       aim_position=None, fire_allowed=True)
        result, target = scene.engine._shared_gun_aim_input(
            binding.state, command, None, scene.now + .01)
        self.assertIsNotNone(target)
        self.assertEqual(14, target['network_id'])
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.assertFalse(result['fire_allowed'])
        self.assertTrue(result['_shared_aim_pending'])
        self.assertTrue(result['_ballistic_solution']['_player_motion_only'])
        self.assertEqual('refreshed', binding.attack_policy.evaluator.trigger_refresh_receipt['status'])
        self.assertEqual(candidate['key'], binding.attack_policy.decision['candidate']['key'])
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])

    def test_expired_proof_keeps_gun_intention_but_cannot_launch(self):
        scene, binding = self.scene()
        policy = binding.attack_policy
        selected = policy.decision['candidate']['key']
        policy.rows.clear()
        policy.evaluator.jobs.clear()
        self.assertIsNone(binding.current_attack_candidate(binding.state,
            policy.decision['candidate']['target']))
        rows = self.observe_aim(scene)
        before = (tuple(binding.gun.ammo), binding.gun.clip, binding.state['fire_seq'])
        self.cached_physics_step(scene)
        self.assertEqual(1, len(rows))
        self.assertEqual(('enemy', 14), (rows[0]['intent']['owner'], rows[0]['intent']['target_id']))
        self.assertTrue(rows[0]['intent']['planning_pending'])
        self.assertTrue(rows[0]['solution']['_player_motion_only'])
        self.assertFalse(rows[0]['fire_allowed'])
        self.assertFalse(binding.state['gun_aligned'])
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(selected, policy.decision['candidate']['key'])
        self.assertEqual(before, (tuple(binding.gun.ammo), binding.gun.clip, binding.state['fire_seq']))
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])

    def test_death_and_despawn_release_the_retained_target(self):
        for reason in ('death', 'despawn'):
            with self.subTest(reason=reason):
                scene, binding = self.scene()
                if reason == 'death':
                    scene.engine.states[14].update(alive=False, health=0.)
                    scene.native_entities[14].health = 0
                else:
                    scene.battle._runtime.bigworld.entities.pop(1014)
                rows = self.observe_aim(scene)
                self.cached_physics_step(scene)
                self.assertEqual(1, len(rows))
                self.assertNotEqual(14, rows[0]['intent']['target_id'])
                self.assertIsNone(getattr(binding, '_shared_aim_intention', None))
                self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])

    def test_explicit_return_and_cancel_release_pending_intention(self):
        for action in ('return_base', 'cancel'):
            with self.subTest(action=action):
                scene, binding = self.scene()
                if action == 'return_base':
                    binding.set_mission('return_base', {})
                else:
                    binding._cancel_mission('test_cancel')
                # Cancellation retires the old lease synchronously. The
                # queued return-base mission applies at the next control
                # callback. Neither blocks a fresh post-cancel decision.
                if action == 'cancel':
                    self.assertIsNone(getattr(binding, '_shared_aim_intention', None))
                    self.assertIsNone(binding._gun_handoff)
                rows = self.observe_aim(scene)
                scene.step(.3)
                self.assertTrue(rows)
                if action == 'cancel':
                    self.assertEqual('new_decision', rows[0]['disposition'], rows[0])
                for row in rows:
                    if action == 'return_base':
                        self.assertEqual('hull_forward_rest', row['intent']['owner'], row)
                        self.assertIsNone(row['intent']['target_id'], row)
                    else:
                        self.assertIn(row['disposition'], ('new_decision', 'cache_reused'), row)
                        if row['intent']['owner'] == 'enemy':
                            self.assertEqual('aim', row['action'], row)
                if action == 'return_base':
                    self.assertIsNone(getattr(binding, '_shared_aim_intention', None))
                self.assertFalse([row for row in scene.launches_observed if row['id'] == 11])

    def test_manual_player_stop_releases_pending_intention(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=1, burst=1)
        # Isolate the downstream consumer from authored-route confirmation.
        scene.runtime.combat_stop._route_requires_confirmation = lambda order: False
        enemy = scene.eligible_enemy(14, armor=10.)
        scene.pose(enemy, (24., 0., 50.))
        scene.sample_original_lanes()
        for unused in range(20):
            scene.fixture.now += .1
            scene.battle._last_frame_time = scene.now
            scene.control.update(.1, scene.now)
            if scene.runtime.attack_policy.decision['action'] == 'aim':
                break
        runtime = scene.runtime
        self.assertIsNotNone(getattr(runtime, '_shared_aim_intention', None))
        command = dict(runtime._last_order, aim_position=None,
                       _ballistic_solution=None, fire_allowed=False)
        runtime.stop('manual')
        result, target = runtime.engine._shared_gun_aim_input(
            runtime.state, command, None, scene.now)
        self.assertIsNone(target)
        self.assertIsNone(getattr(runtime, '_shared_aim_intention', None))
        self.assertFalse(result.get('fire_allowed'))
        self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
