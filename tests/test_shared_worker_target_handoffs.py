"""The worker's physical recovery consumes its resolved shared intention.

The scene runs real BotPlanner orders, BotControlBinding, AttackPolicy, native
geometry and LocalDriver. External vehicle poses and component armour change;
slow-query cases also account deterministic cost after real evaluations.
No candidate, policy decision or recovery marker is prescribed, and the
original handoff cases retain their real clock and bounded wait.
"""
import copy
import unittest

from shared_multi_bot_scene import MultiBotScene
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import ATOMIC_WALL_SECONDS


class SharedWorkerTargetHandoffTests(unittest.TestCase):
    def scene_with_proved_target(self):
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
        return scene, binding

    @staticmethod
    def account_slow_native_queries(binding, cost=.0015):
        """Charge real native evaluations without replacing their results."""
        policy = binding.attack_policy
        clock = dict(seconds=0., evaluations=0, atomic_evaluations=0)
        policy.atomic_clock = lambda: clock['seconds']
        evaluate = policy.evaluator.evaluate

        def charged(*args, **kwargs):
            result = evaluate(*args, **kwargs)
            channel = args[6] if len(args) > 6 else kwargs['channel']
            clock['seconds'] += cost
            clock['evaluations'] += 1
            if channel == 'atomic':
                clock['atomic_evaluations'] += 1
            return result

        policy.evaluator.evaluate = charged
        return clock

    def scene_with_friendly_recovery(self, atomic_cost=None):
        scene, binding = self.scene_with_proved_target()
        engine = scene.engine
        if atomic_cost is not None:
            scene.query_clock = self.account_slow_native_queries(binding, atomic_cost)
        self.move_actor(scene, 12, (-16., 0., 0.))
        source = tuple(binding.state['position'])
        committed = int(binding.state['fire_seq'])
        # A real blocker now finishes the shared stationary-alternative
        # frontier before granting movement. Wait for that event instead of
        # assuming a partial scan is an early relocation certificate.
        for unused in range(200):
            scene.step()
            if 11 in engine._friendly_repositions:
                break
            self.assertEqual(source, tuple(binding.state['position']))
            self.assertEqual(committed, binding.state['fire_seq'])
            self.assertFalse(hasattr(binding.attack_policy, 'search_started'))
        self.assertEqual('firing_position', binding.attack_policy.decision['action'])
        marker = engine._friendly_repositions[11]
        self.assertEqual(14, marker['target_id'])
        self.assertEqual((14, 'bot', 12), marker['identity'][:3])
        self.assertGreater(marker['deadline'], scene.now)
        self.assertFalse(hasattr(binding.attack_policy, 'search_started'),
                          'A real friendly blocker is not an armour failure.')
        return scene, binding, marker

    def test_slow_native_frontier_can_recover_a_current_friendly_blocker(self):
        scene, binding, marker = self.scene_with_friendly_recovery(atomic_cost=.0015)
        self.assertEqual(.008, ATOMIC_WALL_SECONDS)
        self.assertEqual(ATOMIC_WALL_SECONDS, binding.attack_policy.atomic_time_budget)
        self.assertGreater(scene.query_clock['evaluations'], 0)
        # Legitimate foreground/background coverage may finish before the
        # first atomic slice. Recovery must not depend on that faster path.
        for kind in ('candidate', 'world', 'component'):
            self.assertGreater(sum(value for (actor, unused_channel, observed), value
                in scene.counts.items() if actor == 11 and observed == kind), 0)
        self.assertLessEqual(binding.attack_policy._used['foreground'], 2)
        self.assertLessEqual(binding.attack_policy._used['background'], 2)
        for frame in scene.frames[5:]:
            for channel in ('foreground', 'background'):
                self.assertLessEqual(frame['counts'].get((11, channel, 'candidate'), 0), 2)
        self.assertEqual((14, 'bot', 12), marker['identity'][:3])
        self.assertFalse(hasattr(binding.attack_policy, 'search_authority'))
        self.assertEqual(scene.initial_ammo[11][0] - 1, binding.gun.ammo[0])
        self.assertEqual(1, binding.state['fire_seq'])

    def assert_unknown_native_geometry_cannot_authorize_recovery(self, stale_blocker=False):
        scene, binding = self.scene_with_proved_target()
        self.account_slow_native_queries(binding)
        source = tuple(binding.state['position'])
        ammo = tuple(binding.gun.ammo)
        committed = int(binding.state['fire_seq'])
        if stale_blocker:
            self.move_actor(scene, 12, (-16., 0., 0.))
            scene.step()
            self.assertEqual('stationary_alternatives_pending',
                             binding.attack_policy.decision['reason'])
            self.assertNotIn(11, scene.engine._friendly_repositions)
            # A prior real obstruction is history, not current movement
            # authority once the ally has left the shot lane.
            self.move_actor(scene, 12, (0., 0., -25.))

        def unavailable():
            raise RuntimeError('native world query unavailable')

        # Invalidate the old clear lane with an actual changed target pose;
        # the external native boundary now fails, rather than reporting a hit.
        scene.on_probe = unavailable
        self.move_actor(scene, 14, (-16., 0., 26.))
        for unused in range(200):
            scene.step()
            self.assertNotIn(11, scene.engine._friendly_repositions)
            self.assertNotIn('_gun_angle_adjustment', binding.state)
            self.assertEqual(source, tuple(binding.state['position']))
            self.assertEqual(ammo, tuple(binding.gun.ammo))
            self.assertEqual(committed, binding.state['fire_seq'])
            self.assertFalse(hasattr(binding.attack_policy, 'search_started'))
            self.assertFalse(hasattr(binding.attack_policy, 'search_authority'))
        self.assertGreater(scene.counts[(11, 'foreground', 'world')], 0)
        self.assertEqual('wait', binding.attack_policy.decision['action'])

    def test_slow_unknown_native_geometry_cannot_authorize_physical_recovery(self):
        self.assert_unknown_native_geometry_cannot_authorize_recovery()

    def test_slow_stale_blocker_cannot_survive_unknown_native_geometry(self):
        self.assert_unknown_native_geometry_cannot_authorize_recovery(stale_blocker=True)

    def test_slow_review_prefers_a_fresh_native_shot_before_physical_movement(self):
        scene, binding = self.scene_with_proved_target()
        self.account_slow_native_queries(binding)
        self.move_actor(scene, 12, (-16., 0., 0.))
        scene.step()
        self.assertEqual('stationary_alternatives_pending',
                         binding.attack_policy.decision['reason'])
        self.assertNotIn(11, scene.engine._friendly_repositions)
        self.set_armor(scene, 15, 30.)
        self.move_actor(scene, 15, (-5., 0., 5.))
        scene.next_plan = 0.
        for unused in range(200):
            scene.step()
            self.assertNotIn(11, scene.engine._friendly_repositions)
            self.assertFalse(hasattr(binding.attack_policy, 'search_started'))
            if binding.attack_policy.current_target_key() == ('bot', 15):
                break
        self.assertEqual(('bot', 15), binding.attack_policy.current_target_key())
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        candidate = binding.attack_policy.decision['candidate']
        evidence = binding.attack_policy.current_row(candidate, require_line=True)
        self.assertEqual(('clear', 'passed', 'reachable'),
                         tuple(evidence[name] for name in ('line', 'armor', 'mechanical')))

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
            decision = binding.attack_policy.decision
            self.assertIn(decision['action'], ('firing_position', 'wait'))
            if decision['action'] == 'wait':
                self.assertEqual('stationary_alternatives_pending', decision['reason'])
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
        for unused in range(100):
            scene.step()
            if binding.attack_policy.current_target_key() == ('bot', 15):
                break
            # The fresh contact's real native frontier may finish on the
            # following callback. It cannot cancel the old movement owner
            # before the replacement actually qualifies.
            self.assertIs(marker, scene.engine._friendly_repositions.get(11))
        self.assertEqual(('bot', 15), binding.attack_policy.current_target_key())
        self.assertEqual('aim', binding.attack_policy.decision['action'])
        self.assertNotIn(11, scene.engine._friendly_repositions)
        event = binding.state['_friendly_reposition_event']
        # The shared phase now retires its own exact marker once the native
        # replacement is proved, before the old physical target-change hook.
        self.assertEqual('verified_shot', event['outcome'])
        self.assertEqual(marker['identity'], event['marker']['identity'])
        self.assertEqual(('bot', 15), binding.combat_stop._intent_target)
        self.assertIsNone(binding.combat_stop._physical_recovery)
        candidate = binding.attack_policy.decision['candidate']
        evidence = binding.attack_policy.current_row(candidate, require_line=True)
        self.assertEqual(('clear', 'passed', 'reachable'),
                         tuple(evidence[name] for name in ('line', 'armor', 'mechanical')))

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
