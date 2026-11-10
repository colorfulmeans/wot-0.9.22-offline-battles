"""One current gun/recovery owner across ordinary strategic target changes.

These scenes run the common planner, CombatStop, AttackPolicy,
NativeAttackEvaluator, driver and native GunState. Native poses, armour and
collision observations are fixtures; policy outcomes are never substituted.
"""
import copy
import unittest

from test_player_combat_ownership import OwnershipScene, initial_hint
from test_player_fire_admission_complete import ArtilleryFireScene, ballistics, shot_geometry


class SharedTargetExecutionOwnershipTests(unittest.TestCase):
    def fresh_scene(self):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=1, burst=1)
        return scene

    def scene(self):
        scene = self.fresh_scene()
        initial = scene.eligible_enemy(1, armor=10000.)
        scene.pose(initial, (0., 0., 50.))
        executable = scene.eligible_enemy(14, armor=10.)
        scene.pose(executable, (30., 0., 100.))
        self.assertEqual({1: True, 14: True}, scene.sample_original_lanes())
        for unused in range(20):
            scene.tick(.1)
            candidate = scene.runtime.attack_policy.decision.get('candidate') or {}
            if (scene.runtime.attack_policy.decision['action'] == 'aim' and
                    candidate.get('target_key') == ('bot', 14)):
                break
        self.assertEqual(('bot', 1), initial_hint(scene.original_order()))
        self.assertIsNone(scene.original_order()['target_id'])
        self.assertEqual('aim', scene.runtime.attack_policy.decision['action'])
        candidate = scene.runtime.attack_policy.decision['candidate']
        self.assertEqual(('bot', 14), candidate['target_key'])
        self.assertEqual(('passed', 'clear', 'reachable'),
            tuple(candidate[name] for name in ('armor', 'line', 'mechanical')))
        self.assertTrue(scene.runtime.attack_policy._executable_current(candidate))
        self.assertFalse(scene.launches(), 'regression starts before the first trigger')
        return scene, initial, executable

    @staticmethod
    def receipt(scene):
        policy = scene.runtime.attack_policy
        candidate = policy.decision.get('candidate') or {}
        return dict(macro_hint=initial_hint(scene.original_order()),
            macro_target=scene.original_order().get('target_id'),
            macro_mode=scene.original_order().get('combat_mode'),
            applied_target=scene.applied_order().get('target_id'),
            action=policy.decision['action'], reason=policy.decision['reason'],
            target=candidate.get('target_key'), selected=policy.selected,
            stop_allowed=scene.runtime.combat_stop.stop_allowed)

    def test_macro_initial_target_motion_cannot_cancel_another_verified_current_shot(self):
        scene, initial, unused_executable = self.scene()
        candidate = scene.runtime.attack_policy.decision['candidate']
        key, point = candidate['key'], candidate['solution']['point']
        # The obsolete macro target crosses its heuristic 340m fire range.
        # The actual selected enemy, player pose and native weapon stay put.
        scene.pose(initial, (0., 0., 360.))
        scene.runtime._strategic_due = 0.
        scene.tick(.1)
        decision = scene.runtime.attack_policy.decision
        self.assertEqual('aim', decision['action'], self.receipt(scene))
        self.assertEqual(key, decision['candidate']['key'])
        self.assertEqual(point, decision['candidate']['solution']['point'])
        self.assertEqual(14, scene.applied_order()['target_id'])
        self.assertTrue(scene.runtime.attack_policy._executable_current(decision['candidate']))
        self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
        self.assertTrue(scene.runtime.combat_stop.stop_allowed)

    def test_macro_initial_target_motion_cannot_retire_other_targets_friendly_recovery(self):
        scene, initial, unused_executable = self.scene()
        scene.vehicle(3, (15., 0., 50.), team=1)
        # A real blocker enters the same-point recovery. The new owner must
        # prove a particular destination before the driver may consume it.
        for unused in range(20):
            scene.tick(.1)
            phase = scene.runtime.combat_stop._physical_recovery
            if phase is not None and phase.get('goal') is not None:
                break
        policy = scene.runtime.attack_policy
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertEqual(('bot', 14), policy.decision['candidate']['target_key'])
        self.assertEqual('friendly_blocked', policy.decision['candidate']['line'])
        self.assertEqual('passed', policy.decision['candidate']['armor'])
        owner = scene.runtime.combat_stop
        episode = owner.receipt['episode']
        physical = owner._physical_recovery
        self.assertIsNotNone(physical)
        self.assertIsNotNone(physical['goal'])
        marker = copy.deepcopy(physical)
        self.assertEqual(policy.decision['candidate']['key'], physical['key'])
        self.assertFalse(hasattr(scene.runtime.engine, '_friendly_repositions'))
        scene.pose(initial, (0., 0., 360.))
        scene.runtime._strategic_due = 0.
        scene.tick(.1)
        current = owner._physical_recovery
        self.assertIsNotNone(current, self.receipt(scene))
        for field in ('identity', 'target', 'key', 'sample', 'shell_index',
                      'mode', 'started', 'goal'):
            self.assertEqual(marker[field], current[field], field)
        # The unrelated enemy's new pose can invalidate a policy query and
        # temporarily remove move_request. The accepted physical task, not
        # that provisional query result, owns the target and escape goal.
        self.assertEqual(episode, owner.receipt['episode'])
        self.assertIs(physical, owner._physical_recovery)
        self.assertEqual(('bot', 14), physical['target'])
        self.assertEqual('gun_angle_adjust', scene.runtime._last_order['combat_mode'])
        self.assertEqual(14, scene.runtime._last_order['target_id'])
        self.assertEqual(marker['goal'], scene.runtime._last_order['move_position'])
        self.assertFalse(scene.applied_order()['fire_allowed'])
        self.assertFalse(scene.launches())
        self.assertFalse(hasattr(policy, 'search_started'))

    def test_stale_route_hint_cannot_suspend_a_current_native_verified_point(self):
        scene, unused_initial, unused_executable = self.scene()
        policy = scene.runtime.attack_policy
        key = policy.decision['candidate']['key']
        signature = scene.runtime.combat_stop.signature
        incoming = dict(scene.original_order(), target_id=None, target_kind=None,
            combat_mode='route', aim_position=None, face_position=None,
            move_position=(30., 0., 20.), throttle_override=None, fire_allowed=False)
        original_input = copy.deepcopy(incoming)
        scene.step(.1)
        applied = scene.runtime._accept_combat_order(incoming, scene.now)
        self.assertEqual(original_input, incoming)
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(key, policy.decision['candidate']['key'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))
        self.assertEqual(signature, scene.runtime.combat_stop.signature)
        self.assertEqual(14, applied['target_id'])
        self.assertEqual('engage', applied['combat_mode'])
        self.assertEqual(original_input['route_id'], applied['route_id'])
        self.assertEqual(original_input['route_index'], applied['route_index'])
        self.assertEqual({1, 14}, set(row['network_id'] for row in scene.runtime.combat_targets()))

    def test_new_nearer_enemy_changes_hint_without_stealing_current_shot(self):
        scene, unused_initial, unused_executable = self.scene()
        policy = scene.runtime.attack_policy
        key = policy.decision['candidate']['key']
        closer = scene.eligible_enemy(3, armor=10.)
        scene.pose(closer, (-10., 0., 10.))
        scene.runtime._strategic_due = 0.
        scene.tick(.1)
        self.assertEqual(('bot', 3), initial_hint(scene.original_order()))
        self.assertIsNone(scene.original_order()['target_id'])
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(key, policy.decision['candidate']['key'])
        self.assertEqual(14, scene.applied_order()['target_id'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))
        self.assertEqual({1, 3, 14}, set(row['network_id'] for row in scene.runtime.combat_targets()))

    def test_current_target_death_releases_intention_for_real_revalidation(self):
        scene, unused_initial, executable = self.scene()
        other = scene.eligible_enemy(3, armor=10.)
        scene.pose(other, (-30., 0., 100.))
        scene.battle._records['bot:14']['state'].update(alive=False, health=0)
        executable.health = 0
        scene.runtime._strategic_due = 0.
        for unused in range(20):
            scene.tick(.1)
            candidate = scene.runtime.attack_policy.decision.get('candidate') or {}
            self.assertNotEqual(('bot', 14), candidate.get('target_key'))
            if candidate.get('target_key') == ('bot', 3):
                break
        policy = scene.runtime.attack_policy
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(('bot', 3), policy.decision['candidate']['target_key'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))
        self.assertNotIn(14, set(row['network_id'] for row in scene.runtime.combat_targets()))

    def test_real_target_pose_change_rebuilds_the_point_proof(self):
        scene, unused_initial, executable = self.scene()
        old = scene.runtime.attack_policy.decision['candidate']
        scene.pose(executable, (35., 0., 100.))
        for unused in range(20):
            scene.tick(.1)
            candidate = scene.runtime.attack_policy.decision.get('candidate') or {}
            if (scene.runtime.attack_policy.decision['action'] == 'aim' and
                    candidate.get('target_key') == ('bot', 14)):
                break
        current = scene.runtime.attack_policy.decision['candidate']
        self.assertNotEqual(old['pose_stamp'], current['pose_stamp'])
        self.assertNotEqual(old['solution']['point'], current['solution']['point'])
        self.assertEqual(35., current['target']['position'][0])
        sample = shot_geometry.ordered_vehicle_aim_samples(executable.typeDescriptor)[current['sample']]
        point = shot_geometry.vehicle_aim_point(sample, dict(position=tuple(executable.position)))
        shot = scene.runtime.gun.shots[current['shell_index']]
        expected = ballistics.ballistic_intercept(scene.origin, point,
            current['solution']['velocity'], shot.speed, shot.gravity)[0]
        for actual, predicted in zip(current['solution']['point'], expected):
            self.assertAlmostEqual(predicted, actual, places=6)
        self.assertTrue(scene.runtime.attack_policy._executable_current(current))

    def test_explicit_base_return_still_takes_control_from_valid_current_shot(self):
        scene, unused_initial, unused_executable = self.scene()
        scene.runtime.set_mission('return_base', {})
        scene.tick(.1)
        order = scene.applied_order()
        self.assertEqual('team_return_base', order['combat_mode'])
        self.assertEqual((0., 0., -45.), order['move_position'])
        self.assertFalse(scene.runtime.combat_stop.active)
        self.assertFalse(scene.runtime.combat_stop.stop_allowed)
        self.assertIsNone(scene.runtime.attack_policy.selected)
        self.assertEqual('original_navigation', scene.runtime.attack_policy.decision['reason'])
        self.assertFalse(scene.launches())

    def test_exact_distance_initial_tie_uses_actual_native_nominal_armor(self):
        scene = self.fresh_scene()
        for identity, position, armor in ((2, (-30., 0., 40.), 240.),
                                           (3, (30., 0., 40.), 60.)):
            target = scene.eligible_enemy(identity, armor=10.)
            target.typeDescriptor.hull.primaryArmor = (armor, armor, armor)
            target.typeDescriptor.turret.primaryArmor = (armor, armor, armor)
            scene.pose(target, position)
        self.assertEqual({2: True, 3: True}, scene.sample_original_lanes())
        observed = dict((row['network_id'], row['profile']['armor'])
                        for row in scene.runtime.visible_targets())
        self.assertEqual({2: 240., 3: 60.}, observed)
        scene.tick(.1)
        policy = scene.runtime.attack_policy
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(('bot', 3), policy.decision['candidate']['target_key'])
        self.assertEqual(('bot', 3), initial_hint(scene.original_order()))
        self.assertIsNone(scene.original_order()['target_id'])
        self.assertEqual(3, scene.applied_order()['target_id'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))

    def test_cold_start_uses_mounted_shell_range_until_actual_launch(self):
        scene = self.fresh_scene()
        target = scene.eligible_enemy(14, armor=10.)
        scene.pose(target, (0., 0., 400.))
        self.assertEqual(340., scene.runtime.state['profile']['fire_range'])
        self.assertEqual(500., scene.runtime.gun.shots[0].maxDistance)
        self.assertEqual({14: True}, scene.sample_original_lanes())
        for unused in range(60):
            scene.tick(.1)
            if scene.launches():
                break
        self.assertTrue(scene.launches(), self.receipt(scene))
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual(14, scene.applied_order()['target_id'])
        self.assertEqual(500., scene.applied_order()['fire_range'])
        self.assertEqual('route', scene.original_order()['combat_mode'])
        self.assertEqual(('bot', 14), initial_hint(scene.original_order()))
        self.assertTrue(scene.runtime.combat_stop.stop_allowed)

    def test_native_mounted_range_still_rejects_a_truly_unreachable_contact(self):
        scene = self.fresh_scene()
        for shot in scene.runtime.gun.shots:
            shot.maxDistance = 350.
        for row in scene.battle.client.effective_params['gun']['shots']:
            row['source_shot']['maxDistance'] = 350.
        target = scene.eligible_enemy(14, armor=10.)
        scene.pose(target, (0., 0., 400.))
        original_ammo = list(scene.battle._gun_state.ammo)
        for unused in range(60):
            scene.tick(.1)
            self.assertFalse(scene.launches())
            self.assertFalse(scene.applied_order()['fire_allowed'])
        policy = scene.runtime.attack_policy
        self.assertEqual({14}, set(row['network_id'] for row in scene.runtime.combat_targets()))
        self.assertTrue(policy.rows)
        self.assertFalse(any(policy._executable_current(row) for row in policy.rows.values()))
        self.assertEqual(original_ammo, scene.battle._gun_state.ammo)
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertFalse(scene.runtime.combat_stop.combat_owned)
        self.assertFalse(scene.runtime.combat_stop.stop_allowed)
        self.assertEqual('route', scene.original_order()['combat_mode'])
        self.assertEqual('route', scene.applied_order()['combat_mode'])
        self.assertEqual(scene.original_order()['move_position'],
            dict(zip(('x', 'y', 'z'), scene.applied_order()['move_position'])))
        self.assertIsNone(scene.applied_order().get('target_id'))
        self.assertFalse(hasattr(policy, 'search_started'),
            'true range obstruction is navigation work, not an armour-negative certificate')


class SharedArtilleryMountedRangeTests(unittest.TestCase):
    def scene(self, maximum):
        scene = ArtilleryFireScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_artillery(ridge=False)
        for shot in scene.battle._gun_state.shots:
            shot.speed, shot.gravity, shot.maxDistance = 150., 10., maximum
        for row in scene.battle.client.effective_params['gun']['shots']:
            row['source_shot'].update(speed=150., gravity=10., maxDistance=maximum)
        scene.pose(scene.target, (0., 0., 1500.))
        self.assertEqual(1250., scene.runtime.state['profile']['fire_range'])
        return scene

    def test_verified_native_he_arc_beyond_role_range_reaches_actual_launch(self):
        scene = self.scene(3000.)
        scene.run_until_artillery_launch()
        self.assertEqual(1, len(scene.launches()))
        order = scene.runtime.engine._server_orders[scene.runtime.actor_id]
        self.assertEqual(3000., order['fire_range'])
        self.assertEqual(42, order['target_id'])
        self.assertEqual('HIGH_EXPLOSIVE', scene.battle._gun_state.shots[0].shell.kind)

    def test_native_he_arc_beyond_mounted_range_cannot_launch(self):
        scene = self.scene(1400.)
        ammo = list(scene.battle._gun_state.ammo)
        for unused in range(100):
            scene.artillery_tick()
            self.assertTrue(scene.control.active, scene.artillery_trace[-1])
            self.assertFalse(scene.launches())
        self.assertEqual(ammo, scene.battle._gun_state.ammo)
        order = scene.runtime.engine._server_orders[scene.runtime.actor_id]
        self.assertFalse(order['fire_allowed'])
        self.assertEqual('blocked', order['tactical_evidence']['artillery_selection']['status'])


if __name__ == '__main__':
    unittest.main()
