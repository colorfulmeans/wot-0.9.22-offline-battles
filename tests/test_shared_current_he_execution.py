"""A proved CURRENT HE point owns the uncommitted first trigger.

The scenes use real shared planning, AttackPolicy, NativeAttackEvaluator,
TriggerAdmission, GunState and worker controls. Native component boxes, poses
and actuator observations are analytic fixtures; no policy result, armour
verdict, readiness or ammunition transaction is replaced.
"""
import contextlib
import copy
import io
import math
import unittest

from test_player_combat_ownership import OwnershipScene
from shared_multi_bot_scene import MultiBotScene
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import AttackPolicy


class CurrentHEScene(OwnershipScene):
    def observe_control(self, seconds=.1):
        """Observe a native barrel which has not yet followed the aim input."""
        self.fixture.now += seconds
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.assertIsNone(self.control.last_control_failure)
        self.assertTrue(self.runtime.active)
        return self.applied_order()


class SharedCurrentHEExecutionTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def scene(self, armor=30., burst=1, limited=False):
        scene = CurrentHEScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=6, burst=burst, limited=limited)
        scene.set_he(piercing=1.)
        # This physical load has only ordinary HE in stock. NEXT may compare
        # the same shell for a future trigger, but cannot spend CURRENT.
        scene.battle._gun_state.ammo[1] = 0
        scene.battle.client.effective_params['ammo'][1][1] = 0
        scene.initial = scene.eligible_enemy(14, armor=armor)
        if limited:
            scene.pose(scene.initial, (3., 0., 40.))
        scene.sample_original_lanes()
        scene.commits = []
        native_commit = scene.runtime.attack_policy.shot_committed

        def committed(event, pending):
            policy = scene.runtime.attack_policy
            candidate = ((pending.get('player_control') or {}).get('candidate') or
                         policy.trigger or policy.decision.get('candidate') or {})
            scene.commits.append(dict(target=candidate.get('target_key'),
                key=candidate.get('key'), index=event.get('burst_index', 0),
                count=event.get('burst_count', 1)))
            return native_commit(event, pending)

        scene.runtime.attack_policy.shot_committed = committed
        return scene

    def acquire(self, scene, target=14):
        for unused in range(50):
            scene.observe_control()
            policy = scene.runtime.attack_policy
            candidate = policy.decision.get('candidate') or {}
            self.assertFalse(scene.launches())
            if policy.decision['action'] == 'aim' and candidate.get('mode') == 'he_fallback':
                break
        self.assertEqual('aim', policy.decision['action'], policy.status())
        self.assertEqual(('bot', target), candidate['target_key'])
        self.assertTrue(policy._executable_current(candidate, 'he_fallback'))
        self.assertEqual(0, policy.he_comparison['pending'])
        self.assertEqual(policy.he_comparison['total'], policy.he_comparison['observed'])
        return candidate

    @staticmethod
    def add_better(scene):
        target = scene.eligible_enemy(2, armor=10.)
        scene.pose(target, (-30., 0., 40.))
        scene.sample_original_lanes()
        scene.runtime._strategic_due = 0.
        return target

    def assert_current(self, scene, key):
        policy = scene.runtime.attack_policy
        candidate = policy.decision.get('candidate') or {}
        self.assertEqual('aim', policy.decision['action'], policy.status())
        self.assertEqual(key, candidate['key'])
        current = policy.current_row(candidate, require_line=True)
        self.assertIsNotNone(current)
        self.assertTrue(policy._executable_current(current, 'he_fallback'))
        self.assertEqual(candidate['pose_stamp'], current['pose_stamp'])
        self.assertLessEqual(policy._used['foreground'], policy.foreground_budget)
        self.assertIsNone(policy.search_started)

    def test_first_comparison_still_observes_all_points_and_selects_highest_damage(self):
        scene = self.scene()
        self.add_better(scene)
        candidate = self.acquire(scene, target=2)
        self.assertEqual(37., candidate['expected_damage'])
        self.assertEqual({2, 14}, {row['network_id'] for row in scene.runtime.combat_targets()})
        self.assertGreater(scene.runtime.attack_policy.he_comparison['total'], 2)
        self.assertFalse(scene.launches())

    def test_new_higher_damage_target_and_verified_next_cannot_preempt_current_he(self):
        for armor, damage in ((30., 11.), (60., 0.)):
            with self.subTest(current_damage=damage):
                scene = self.scene(armor=armor)
                first = self.acquire(scene)
                self.assertEqual(damage, first['expected_damage'])
                self.add_better(scene)
                next_target = None
                for unused in range(25):
                    scene.observe_control()
                    self.assert_current(scene, first['key'])
                    self.assertEqual(14, scene.original_order()['target_id'])
                    self.assertEqual({2, 14}, {row['network_id'] for row in scene.runtime.combat_targets()})
                    plan, unused_reason = scene.runtime.attack_policy.next_at_edge()
                    if plan is not None:
                        next_target = plan['target_key']
                    self.assertFalse(scene.launches())
                self.assertEqual(('bot', 2), next_target)
                for unused in range(15):
                    scene.tick(.1)
                    if scene.launches():
                        break
                self.assertTrue(scene.launches(), scene.runtime.attack_policy.status())
                self.assertEqual(('bot', 14), scene.commits[0]['target'])

    def test_current_pose_change_is_reproved_without_using_the_old_solution(self):
        scene = self.scene()
        first = self.acquire(scene)
        self.add_better(scene)
        scene.pose(scene.initial, (22., 0., 40.))
        scene.observe_control()
        self.assert_current(scene, first['key'])
        current = scene.runtime.attack_policy.decision['candidate']
        self.assertNotEqual(first['pose_stamp'], current['pose_stamp'])
        self.assertNotEqual(first['solution']['point'], current['solution']['point'])
        self.assertEqual(22., current['target']['position'][0])
        self.assertFalse(scene.launches())

    def test_dead_current_target_releases_execution_for_the_new_full_comparison(self):
        scene = self.scene()
        self.acquire(scene)
        self.add_better(scene)
        scene.battle._records['bot:14']['state'].update(alive=False, health=0)
        scene.initial.health = 0
        scene.runtime._strategic_due = 0.
        current = self.acquire(scene, target=2)
        self.assertEqual(37., current['expected_damage'])
        self.assertEqual({2}, {row['network_id'] for row in scene.runtime.combat_targets()})

    def test_unrelated_target_reentry_cannot_restart_the_current_he_comparison(self):
        scene = self.scene()
        first = self.acquire(scene)
        other = self.add_better(scene)
        scene.observe_control()
        self.assert_current(scene, first['key'])
        # A new source pose requires an actual current-point query. During
        # that query only the separate, off-line competitor moves; neither
        # the source nor this trigger's target changes inside the callback.
        scene.native_position((.1, 0., 0.))
        tester = scene.initial.typeDescriptor.hull.hitTester
        callbacks = []

        def move_other_during_query():
            tester.on_hit = None
            callbacks.append(True)
            scene.pose(other, (-32., 0., 40.))

        tester.on_hit = move_other_during_query
        scene.observe_control()
        policy = scene.runtime.attack_policy
        self.assertEqual([True], callbacks)
        self.assertFalse(policy._frame_invalid)
        self.assert_current(scene, first['key'])
        self.assertIsNotNone(policy._current_he_execution)
        self.assertNotEqual(first['pose_stamp'], policy.decision['candidate']['pose_stamp'])
        self.assertFalse(scene.launches())
        for unused in range(15):
            scene.tick(.1)
            if scene.launches():
                break
        self.assertTrue(scene.launches(), policy.status())
        self.assertEqual(('bot', 14), scene.commits[0]['target'])

    def test_native_reentry_during_current_recheck_cannot_publish_an_old_pose(self):
        for changed in ('source', 'target', 'friendly'):
            with self.subTest(changed=changed):
                scene = self.scene()
                self.acquire(scene)
                friendly = scene.vehicle(9, (-30., 0., 20.), team=1)
                scene.native_position((.1, 0., 0.))
                tester = scene.initial.typeDescriptor.hull.hitTester
                callbacks = []

                def move_during_query():
                    tester.on_hit = None
                    callbacks.append(True)
                    if changed == 'source':
                        scene.native_position((.4, 0., 0.))
                    elif changed == 'target':
                        scene.pose(scene.initial, (22., 0., 40.))
                    else:
                        scene.pose(friendly, (10., 0., 20.))

                tester.on_hit = move_during_query
                scene.observe_control()
                policy = scene.runtime.attack_policy
                self.assertEqual([True], callbacks)
                self.assertTrue(policy._frame_invalid)
                self.assertEqual({}, policy.rows)
                self.assertIsNone(policy.selected)
                self.assertIsNone(policy._current_he_execution)
                self.assertNotEqual('aim', policy.decision['action'])
                self.assertFalse(scene.applied_order()['fire_allowed'])
                self.assertFalse(scene.launches())
                self.assertLessEqual(policy._used['foreground'], policy.foreground_budget)

    def test_new_native_friendly_obstruction_cannot_keep_current_he_fire_authority(self):
        scene = self.scene()
        self.acquire(scene)
        scene.vehicle(9, (10., 0., 20.), team=1)
        scene.observe_control()
        policy = scene.runtime.attack_policy
        self.assertNotEqual('aim', policy.decision['action'])
        self.assertIsNone(policy._current_he_execution)
        self.assertFalse(scene.applied_order()['fire_allowed'])
        self.assertFalse(scene.launches())
        self.assertIsNone(policy.search_started)

    def test_real_load_input_retires_the_current_he_execution_qualification(self):
        scene = self.scene()
        self.acquire(scene)
        scene.battle._gun_state.ammo[1] = 10
        scene.battle.client.effective_params['ammo'][1][1] = 10
        ammo = list(scene.battle._gun_state.ammo)
        code = scene.battle._runtime.constants.VEHICLE_SETTING.CURRENT_SHELLS
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, code, 102))
        self.assertIsNone(scene.runtime.attack_policy._current_he_execution)
        self.assertIsNone(scene.runtime.attack_policy.selected)
        self.assertEqual(1, scene.battle._gun_state.shot_index)
        self.assertGreater(scene.battle._gun_state.reload_time, 0.)
        self.assertEqual(ammo, scene.battle._gun_state.ammo)
        self.assertFalse(scene.launches())

    def test_world_obstruction_releases_current_point_without_false_armour_search(self):
        scene = self.scene()
        self.acquire(scene)
        ammo = list(scene.battle._gun_state.ammo)
        scene.world[:] = [((7., -3., 15.), (14., 8., 25.))]
        # Move the actual source after changing the analytic map so no
        # static-world cache from the former source pose can be reused.
        scene.native_position((.1, 0., 0.))
        scene.sample_original_lanes()
        for unused in range(30):
            scene.observe_control()
            policy = scene.runtime.attack_policy
            self.assertNotEqual('aim', policy.decision['action'])
            self.assertIsNone(policy.search_started)
            self.assertFalse(scene.applied_order()['fire_allowed'])
            self.assertFalse(scene.launches())
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertEqual(ammo, scene.battle._gun_state.ammo)

    def test_real_mechanical_limit_does_not_inherit_the_previous_he_fire_authority(self):
        scene = self.scene(limited=True)
        self.acquire(scene)
        scene.native_position((0., 0., 0.), math.pi)
        scene.observe_control()
        policy = scene.runtime.attack_policy
        self.assertNotEqual('aim', policy.decision['action'])
        self.assertFalse(scene.applied_order()['fire_allowed'])
        self.assertFalse(scene.launches())
        self.assertIsNone(policy.search_started)

    def test_real_laying_refusal_preserves_the_uncommitted_intention_but_not_fire_proof(self):
        scene = self.scene()
        first = self.acquire(scene)
        gun = scene.battle._gun_state
        gun.reload_time = .3
        scene.tick(.1)
        self.assertTrue(scene.runtime.state['gun_aligned'])
        scene.battle._advance_local_gun_to(scene.entity, scene.now)
        scene.advance(.4)
        self.assertEqual(0., gun.reload_time)
        self.assertFalse(scene.launches())
        ammo = list(gun.ammo)
        # A real body turn after the actuator observation leaves the old
        # readiness observation true but the actual barrel off the point.
        scene.native_position((0., 0., 0.), .15)
        x, y, z = scene.direction
        scene.direction = (x * math.cos(.15) + z * math.sin(.15), y,
                           z * math.cos(.15) - x * math.sin(.15))
        self.assertFalse(scene.fire())
        self.assertEqual('auto_gun_laying', scene.control.last_fire_failure)
        self.assertEqual(ammo, gun.ammo)
        self.assertFalse(scene.launches())
        self.assertEqual(first['key'], scene.runtime.attack_policy.selected)
        self.add_better(scene)
        scene.observe_control()
        self.assert_current(scene, first['key'])
        for unused in range(15):
            scene.tick(.1)
            if scene.launches():
                break
        self.assertTrue(scene.launches(), scene.runtime.attack_policy.status())
        self.assertEqual(('bot', 14), scene.commits[0]['target'])

    def test_replaced_current_entity_or_collider_cannot_inherit_execution_qualification(self):
        for replacement in ('entity', 'collider'):
            with self.subTest(replacement=replacement):
                scene = self.scene()
                first = self.acquire(scene)
                self.add_better(scene)
                if replacement == 'entity':
                    current = scene.eligible_enemy(14, armor=60.)
                    self.assertIsNot(current, scene.initial)
                    scene.initial = current
                else:
                    scene.initial.typeDescriptor.hull.hitTester = copy.deepcopy(
                        scene.initial.typeDescriptor.hull.hitTester)
                    for name in ('chassis', 'hull', 'turret', 'gun'):
                        getattr(scene.initial.typeDescriptor, name).materials[0].armor = 60.
                scene.sample_original_lanes()
                candidate = self.acquire(scene, target=2)
                self.assertNotEqual(first['key'], candidate['key'])
                self.assertEqual(37., candidate['expected_damage'])

    def test_real_first_commit_and_burst_tail_then_next_trigger_start_a_full_new_comparison(self):
        scene = self.scene(burst=3)
        first = self.acquire(scene)
        self.add_better(scene)
        scene.observe_control()
        self.assert_current(scene, first['key'])
        admission = scene.control._admission()
        prepares = []
        native_prepare = admission.prepare

        def prepare(*args, **kwargs):
            prepares.append(scene.now)
            return native_prepare(*args, **kwargs)

        admission.prepare = prepare
        for unused in range(15):
            scene.tick(.1)
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual((('bot', 14), 0, 3),
            (scene.commits[0]['target'], scene.commits[0]['index'], scene.commits[0]['count']))
        first_prepare_count = len(prepares)
        for unused in range(2):
            scene.observe_control(.01)
            self.assertEqual('trigger_active', scene.runtime.attack_policy.decision['action'])
            self.assertIsNone(scene.runtime.attack_policy._current_he_execution)
            scene.advance(.11)
        self.assertEqual(3, len(scene.launches()))
        self.assertEqual(first_prepare_count, len(prepares), 'native tail must not run a second admission')
        self.assertEqual([0, 1, 2], [row['index'] for row in scene.commits])
        self.assertEqual({('bot', 14)}, {row['target'] for row in scene.commits})
        for unused in range(30):
            scene.observe_control()
            decision = scene.runtime.attack_policy.decision
            candidate = decision.get('candidate') or {}
            if decision['action'] == 'aim' and candidate.get('target_key') == ('bot', 2):
                break
        self.assertEqual(('bot', 2), candidate.get('target_key'))
        self.assertEqual(37., candidate['expected_damage'])
        self.assertEqual(0, scene.runtime.attack_policy.he_comparison['pending'])
        self.assertEqual(3, len(scene.launches()))

    def test_worker_uses_same_current_he_owner_through_real_native_first_commit(self):
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_workers(4)
        # An actual initial reload leaves a finite window in which the
        # selected point is laid but its first trigger cannot commit yet.
        scene.engine._gun_states[12].elapsed = 0.
        scene.engine.states[14].update(alive=False, health=0)
        for unused in range(150):
            scene.step()
            binding = scene.engine._actor_controls[12]
            policy = binding.attack_policy
            candidate = policy.decision.get('candidate') or {}
            if policy.decision['action'] == 'aim' and candidate.get('mode') == 'he_fallback':
                break
        self.assertIs(type(policy), AttackPolicy)
        self.assertEqual(('bot', 13), candidate.get('target_key'))
        self.assertFalse([row for row in scene.launches_observed if row['id'] == 12])
        key = candidate['key']
        scene.engine.states[14].update(alive=True, health=1000., x=-40., z=40.)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(scene.descriptors['14'], name).materials[0].armor = 10.
        scene.next_plan = 0.
        for unused in range(180):
            scene.step()
            events = [row for row in scene.launches_observed if row['id'] == 12]
            if events:
                break
            self.assertEqual('aim', policy.decision['action'], policy.status())
            self.assertEqual(key, policy.decision['candidate']['key'])
            self.assertTrue(policy._executable_current(policy.decision['candidate'], 'he_fallback'))
            self.assertEqual({13, 14}, {row['network_id'] for row in binding.combat_targets()})
        self.assertTrue(events, policy.status())
        self.assertEqual(13, events[0]['evidence']['target'])
        self.assertEqual(2, events[0]['shell_index'])


if __name__ == '__main__':
    unittest.main()
