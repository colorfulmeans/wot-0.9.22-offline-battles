"""An admitted reload retreat survives pose churn and reaches native input.

Only body/plate observations are supplied. AttackPolicy, the copied retreat
state machine, FullPlayerRuntime, _LANInputSender and GunState are production
consumers. These are lifecycle tests, not Windows physics acceptance.
"""
import copy
import unittest

import test_player_full_shell_settings as shell_fixtures
import test_player_siege_engagement as siege_fixtures
from gui.mods.offline_lan_0922 import siege_mechanics
from gui.mods.offline_lan_0922.player_control import attack_policy
from gui.mods.offline_lan_0922.player_control.copied import server_bot_ai


class ReloadAuthorityLifecycleTests(unittest.TestCase):
    scene = shell_fixtures.FullShellSettingsTests.scene

    def limited_scene(self):
        scene = self.scene(clip=6, burst=3)
        scene.entity.typeDescriptor.gun.turretYawLimits = (-.2, .2)
        gun = scene.battle._gun_state
        gun.clip = 3
        for index, piercing in enumerate((1., 1000.)):
            gun.shots[index].piercingPower = (piercing, piercing)
            scene.battle.client.effective_params['gun']['shots'][index][
                'source_shot']['piercingPower'] = (piercing, piercing)
        scene.runtime.attack_policy.reset()
        scene.runtime.attack_policy.atomic_time_budget = .25
        return scene

    def qualify(self, scene):
        policy = scene.runtime.attack_policy
        self.assertIsInstance(policy.evaluator, attack_policy.NativeAttackEvaluator)
        for unused in range(120):
            scene.step(.11)
            decision = policy.update(scene.now)
            policy.background(scene.now)
            self.assertIsNone(policy.search_started)
            if decision['action'] == 'reload_clip' and decision.get('early_reload'):
                return decision
        self.fail('native complete failure did not admit limited-gun retreat: %r' % policy.status())

    @staticmethod
    def route_order(scene):
        return dict(id=scene.runtime.actor_id, combat_mode='advance',
            target_id=scene.target.id, target_kind='bot',
            move_position=(0., 0., -24.), face_position=(0., 0., 40.),
            fire_allowed=False, shell_index=0)

    def test_limited_retreat_keeps_qualification_across_pose_changes_until_native_load(self):
        scene = self.limited_scene()
        gun = scene.battle._gun_state
        policy = scene.runtime.attack_policy
        self.qualify(scene)
        qualified_at = policy.reload_authority['qualified_at']
        # The map fixture supplies a previous route anchor away from this
        # observed position. Retreat endpoint freezing, progress, timeout
        # and native loading remain the actual production consumers.
        order = self.route_order(scene)
        settings, observed = scene.battle.change_vehicle_setting, []

        def capture_setting(code, value):
            if code in (scene.settings.CURRENT_SHELLS, scene.settings.RELOAD_PARTIAL_CLIP):
                observed.append(dict(now=scene.now,
                    decision=copy.deepcopy(scene.runtime.attack_policy.decision),
                    retreat=copy.deepcopy(scene.runtime._reload_retreat)))
            return settings(code, value)

        scene.battle.change_vehicle_setting = capture_setting
        before = list(gun.ammo)
        trace = []
        for step in range(240):
            if step < 10:
                # A real observed source change expires every old armour
                # row, without inventing a new tactical reload transaction.
                scene.position = (.001 * step, 0., 0.)
                scene.origin = (.001 * step, 2., 0.)
                scene.set_hull(0.)
            scene.step(.11)
            decision = policy.update(scene.now)
            self.assertIsNone(policy.search_started)
            authority = policy.reload_authority
            self.assertIsNotNone(authority)
            self.assertEqual(qualified_at, authority['qualified_at'])
            self.assertEqual('reload_clip', decision['action'])
            moved = scene.runtime._reload_order(order, scene.now)
            trace.append((scene.now, copy.deepcopy(decision), copy.deepcopy(moved)))
            scene.runtime._apply_shell_intent()
            policy.background(scene.now)
            scene.runtime._apply_next_shell()
            self.assertEqual(before, gun.ammo)
            if observed:
                break
        self.assertGreater(len(trace), 10)
        self.assertEqual(1, len(observed), trace[-3:])
        receipt = observed[0]
        self.assertEqual('limited_traverse_current_clip_failed', receipt['decision']['reason'])
        self.assertTrue(receipt['retreat']['ready'])
        self.assertIn(receipt['retreat']['reason'],
            ('copied_cover_attempt_complete', 'copied_retreat_attempt_complete'))
        self.assertEqual((1, 0), (gun.shot_index, gun.clip))
        self.assertGreater(gun.reload_time, 0.)
        self.assertIsNone(scene.runtime.attack_policy.reload_authority)
        self.assertFalse(scene.launches())

    def test_pending_replacement_clears_old_ai_queue_before_same_shell_partial_reload(self):
        scene = self.limited_scene()
        runtime, gun = scene.runtime, scene.battle._gun_state
        self.qualify(scene)
        # Finish the independent background ranking through real geometry.
        for unused in range(40):
            if runtime.attack_policy.next_shell == 1:
                break
            scene.step(.11)
            runtime.attack_policy.update(scene.now)
            runtime.attack_policy.background(scene.now)
        self.assertEqual(1, runtime.attack_policy.next_shell)
        runtime._apply_next_shell()
        self.assertEqual(1, gun.pending_index)
        order = self.route_order(scene)
        first = runtime._reload_order(order, scene.now)
        self.assertEqual('magazine_reload_retreat', first['combat_mode'])
        self.assertFalse(runtime._reload_retreat['ready'])
        scene.step(server_bot_ai.RETREAT_PROGRESS_TIMEOUT_SECONDS + .01)
        runtime._reload_order(order, scene.now)
        self.assertTrue(runtime._reload_retreat['ready'])
        # This is a missing native shot descriptor, not a supplied decision.
        # The foreground update sees pending rank before the post-control
        # background pass has released its previous NEXT_SHELLS lease.
        gun.shots[1].speed = None
        scene.step(.01)
        decision = runtime.attack_policy.update(scene.now)
        self.assertEqual(('reload_clip', 0, None),
            (decision['action'], decision['shell_index'], decision['candidate']))
        self.assertEqual(1, gun.pending_index)
        runtime._apply_shell_intent()
        self.assertEqual((0, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertGreater(gun.reload_time, 0.)
        self.assertIsNone(runtime.attack_policy.reload_authority)
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102),
                          (scene.settings.NEXT_SHELLS, 101),
                          (scene.settings.RELOAD_PARTIAL_CLIP, 0)], scene.setting_calls)

    def test_native_siege_descriptor_exit_preserves_the_same_partial_clip_retreat(self):
        scene = siege_fixtures.SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(enabled=True, clip=3, enabled_pitch=(-.8, .8))
        gun, runtime = scene.battle._gun_state, scene.runtime
        gun.clip = 2
        for shot in gun.shots:
            shot.piercingPower = (1., 1.)
        policy = runtime.attack_policy
        policy.reset()
        policy.atomic_time_budget = .25
        self.qualify(scene)
        qualified = policy.reload_authority['qualified_at']
        old_identity = policy.frame['identity']
        physical_identity = policy.frame['weapon_identity']
        order = self.route_order(scene)
        runtime._reload_order(order, scene.now)
        retreat = runtime._reload_retreat
        self.assertFalse(retreat['ready'])
        # A real native composite/sequence echo, not a supplied policy frame,
        # changes the mounted gun envelope to travel's exact zero pitch.
        scene.echo_mode(siege_mechanics.SWITCHING_OFF, 1)
        scene.step(.1)
        decision = policy.update(scene.now)
        self.assertNotEqual(old_identity, policy.frame['identity'])
        self.assertEqual(physical_identity, policy.frame['weapon_identity'])
        self.assertEqual(('reload_clip', qualified),
            (decision['action'], decision['reload_qualified_at']))
        runtime._reload_order(order, scene.now)
        self.assertIs(retreat, runtime._reload_retreat)
        scene.echo_mode(siege_mechanics.DISABLED, 1)
        scene.step(server_bot_ai.RETREAT_PROGRESS_TIMEOUT_SECONDS + .01)
        decision = policy.update(scene.now)
        self.assertEqual(('reload_clip', qualified),
            (decision['action'], decision['reload_qualified_at']))
        runtime._reload_order(order, scene.now)
        self.assertTrue(runtime._reload_retreat['ready'])
        runtime._apply_shell_intent()
        self.assertEqual((0, 0), (gun.shot_index, gun.clip))
        self.assertGreater(gun.reload_time, 0.)
        self.assertIsNone(policy.reload_authority)
        self.assertFalse(scene.launches())

    def test_last_stocked_ap_shot_loads_ranked_he_fallback_without_current_fallback_phase(self):
        scene = self.scene(clip=1, burst=1, third=True)
        runtime, gun = scene.runtime, scene.battle._gun_state
        gun.ammo[0] = gun.clip = 1
        for index in (1, 2):
            gun.shots[index].piercingPower = (1., 1.)
            scene.battle.client.effective_params['gun']['shots'][index][
                'source_shot']['piercingPower'] = (1., 1.)
        he = gun.shots[2]
        he.shell.kind, he.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        scene.battle.client.effective_params['gun']['shots'][2][
            'source_shot']['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        policy = runtime.attack_policy
        policy.reset()
        for unused in range(100):
            scene.step(.05)
            decision = policy.update(scene.now)
            policy.background(scene.now)
            self.assertEqual('aim', decision['action'])
            self.assertFalse(policy.fallback)
            if policy.next_status == 'verified_he_fallback':
                break
        self.assertEqual((2, 'verified_he_fallback'),
                         (policy.next_shell, policy.next_status))
        self.assertTrue(policy._all_failed((1, 2)))
        runtime._apply_next_shell()
        self.assertEqual(2, gun.pending_index)
        scene.rotator_enabled = True
        for unused in range(100):
            scene.battle._advance_local_gun_to(scene.entity, scene.now)
            scene.tick()
            if scene.launches():
                break
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((2, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertEqual(0, gun.ammo[0])
        self.assertGreater(gun.reload_time, 0.)
        self.assertEqual((2, 'he_fallback'),
            (policy.loading_plan['shell_index'], policy.loading_plan['mode']))
        self.assertIsNone(policy.search_started)


if __name__ == '__main__':
    unittest.main()
