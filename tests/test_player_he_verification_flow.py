"""HE validation scope reaches real targeting, ammunition and projectile consumers.

The original planner, evaluator, first-trigger proof, battle.shoot and GunState
run unchanged. Only native BSP/material and actuator observations are fixtures.
These tests cannot establish real Windows frame pacing or BigWorld physics.
"""
import math
from types import SimpleNamespace
import unittest

from test_player_combat_ownership import OwnershipScene
from test_player_fire_admission_complete import BoxTester


HESH_PAIRS = (
    ('_183mm_L4', '_183mm_HESH'),
    ('_183mm_AT_Gun', '_183mm_HESH'),
    ('_105mm_Gun_L7', '_105mm_HESH_L7'),
    ('_105mm_AT_Gun_L7', '_105mm_HESH_L7'),
    ('_5_5inch_AT_Gun', '_5_5inch_HESH_Mk_1'),
)


class LayeredPlateBox(BoxTester):
    """A native BSP whose upper plate is thinner than its lower plate."""
    available = True

    def localHitTest(self, start, end):
        if not self.available:
            return ()
        hits = super().localHitTest(start, end)
        if not hits:
            return hits
        distance, normal, cosine, unused_material = hits[0]
        length = math.sqrt(sum((end[i] - start[i]) ** 2 for i in range(3)))
        height = start[1] + (end[1] - start[1]) * distance / length
        return ((distance, normal, cosine, 1 if height > .7 else 0),)


class HEVerificationFlowTests(unittest.TestCase):
    def scene(self, clip=1, burst=1, armor=10., layered=False, hesh=None):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=clip, burst=burst)
        scene.set_he(piercing=100.)
        if hesh is not None:
            gun_name, shell_name = hesh
            descriptor = scene.entity.typeDescriptor
            descriptor.name = descriptor.type.name = 'uk:GB83_FV4005'
            descriptor.gun.name = gun_name
            scene.battle._gun_state.shots[0].shell.name = shell_name
        target = scene.eligible_enemy(5, armor=armor)
        if layered:
            self.layered(target)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        return scene, target

    @staticmethod
    def layered(target):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            component = getattr(target.typeDescriptor, name)
            component.hitTester = LayeredPlateBox(*component.hitTester.bbox[:2])
            component.materials = {
                0: SimpleNamespace(armor=300., vehicleDamageFactor=1., kind=0),
                1: SimpleNamespace(armor=10., vehicleDamageFactor=1., kind=0),
            }

    @staticmethod
    def tick(scene):
        scene.battle._advance_local_gun_to(scene.entity, scene.now)
        return scene.tick()

    def run_until_shots(self, scene, count=1, steps=180, observe=None):
        for unused in range(steps):
            self.tick(scene)
            if observe is not None:
                observe()
            if len(scene.launches()) >= count:
                return
        self.fail('no actual projectile: %r' % scene.runtime.status())

    def test_ordinary_he_first_point_success_launches_without_loading_another_shell(self):
        scene, target = self.scene()
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        self.run_until_shots(scene)
        self.assertEqual((0, 'penetration', 0),
            (policy.decision['candidate']['shell_index'],
             policy.decision['candidate']['mode'], policy.decision['candidate']['sample']))
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)

    def test_ordinary_he_first_point_failure_fires_current_he_before_next_ap(self):
        scene, target = self.scene(layered=True)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        saw_switch = []
        he_samples = set()
        def observe():
            self.assertFalse(hasattr(policy, 'search_started'))
            he_samples.update(row['sample'] for row in policy.rows.values()
                              if row['shell_index'] == 0 and row['mode'] == 'penetration')
            if policy.decision['action'] == 'switch_shell':
                candidate = policy.decision['candidate']
                saw_switch.append((candidate['shell_index'], candidate['armor'], candidate['line']))
        self.run_until_shots(scene, observe=observe)
        self.assertEqual([], saw_switch)
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)
        # The same native target has a penetrable upper HE point. Ordinary
        # HE must finish its chosen lower point instead of scanning to it.
        self.assertEqual({0}, he_samples)

    def test_he_magazine_failure_falls_back_without_discarding_clip_or_next_ap(self):
        scene, target = self.scene(clip=6, burst=3, layered=True)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        def observe():
            self.assertEqual(0, gun.shot_index)
            self.assertFalse(hasattr(policy, 'search_started'))
            self.assertIsNone(policy.reload_authority)
        self.run_until_shots(scene, observe=observe)
        self.assertEqual('current_he_clip_fallback', policy.decision['reason'])
        self.assertEqual('he_fallback', policy.decision['candidate']['mode'])
        self.assertEqual((1, 'penetration'), (policy.next_shell, policy.next_plan['mode']))
        next_key = policy.next_plan['key']
        for unused in range(2):
            self.assertTrue(scene.advance())
            self.assertEqual(next_key, policy.next_plan['key'])
            self.assertEqual(1, gun.pending_index)
        self.assertEqual([0, 1, 2], [shot['burst_index'] for shot in scene.launches()])
        self.assertEqual(1, len(set(shot['burst_group_seq'] for shot in scene.launches())))
        self.assertEqual([0, 0, 0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 3, initial[1]), tuple(gun.ammo))
        self.assertEqual(3, gun.clip)
        self.assertEqual(3, scene.control.shot_commits)

    def test_single_he_does_not_wait_for_late_ap_plate_to_execute_fallback(self):
        scene, target = self.scene(layered=True)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        # Both shells fail the first lower plates; AP's later upper sample
        # is a real penetration. That finite independent NEXT review must not
        # prevent the currently loaded HE from executing legal contact damage.
        gun.shots[1].piercingPower = (200., 200.)
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot'][
            'piercingPower'] = (200., 200.)
        policy.atomic_time_budget = 0.
        policy.background_budget = 1
        initial = tuple(gun.ammo)
        pending_frames = []
        verified_samples = set()
        for unused in range(180):
            self.tick(scene)
            rows = [row for row in policy._rows_for('penetration', 1, fresh_line=True)]
            verified_samples.update(row['sample'] for row in rows if policy._executable(row))
            if not verified_samples and not policy._all_failed((1,)):
                pending_frames.append(scene.now)
                self.assertFalse(scene.launches())
                self.assertEqual(initial, tuple(gun.ammo))
                self.assertEqual(0, gun.shot_index)
                self.assertNotEqual('switch_shell', policy.decision['action'])
            if scene.launches():
                break
        self.assertTrue(pending_frames, 'the native AP review must actually span frames')
        self.assertIn(4, verified_samples)
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()], policy.status())
        self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)

    def test_only_ordinary_he_left_uses_real_fallback_after_its_failed_point(self):
        scene, target = self.scene(armor=300.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        gun.ammo[1] = 0
        initial = tuple(gun.ammo)
        def observe():
            self.assertFalse(hasattr(policy, 'search_started'))
            self.assertEqual(0, gun.shot_index)
        self.run_until_shots(scene, observe=observe)
        self.assertEqual('he_fallback', policy.decision['candidate']['mode'])
        self.assertIs(policy.decision['candidate']['contact'], True)
        self.assertEqual((initial[0] - 1, 0), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)

    def test_failed_ap_magazine_loads_verified_he_without_eight_second_delay_and_fires(self):
        scene, target = self.scene(clip=6, armor=30.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        # There are two stocked roles: the loaded AP cassette and an
        # ordinary HE reserve. Neither can penetrate this native target.
        for index, kind in enumerate(('ARMOR_PIERCING', 'HIGH_EXPLOSIVE')):
            shot = gun.shots[index]
            shot.piercingPower = (1., 1.)
            shot.shell.kind = kind
            shot.shell.explosionRadius = 5. if index else 0.
            source = scene.battle.client.effective_params['gun']['shots'][index]['source_shot']
            source['piercingPower'] = shot.piercingPower
            source['shell'].update(kind=kind, explosionRadius=shot.shell.explosionRadius)
        initial = tuple(gun.ammo)
        began = scene.now
        reload_qualified_at = None
        saw_he_next = saw_native_load = False
        for unused in range(350):
            self.tick(scene)
            self.assertFalse(hasattr(policy, 'search_started'))
            if (policy.next_plan is not None and policy.next_shell == 1 and
                    policy.next_plan['mode'] == 'he_fallback'):
                saw_he_next = True
            decision = policy.decision
            if decision['action'] == 'reload_clip' and decision.get('early_reload'):
                if reload_qualified_at is None:
                    reload_qualified_at = scene.now
                self.assertEqual(1, decision['shell_index'],
                    'completed ordinary-HE trial must not make early reload choose AP again')
                self.assertEqual('he_fallback', decision['candidate']['mode'])
            if gun.shot_index == 1 and gun.clip == 0 and gun.reload_time > 0.:
                saw_native_load = True
            if scene.launches():
                break
        self.assertTrue(saw_he_next)
        self.assertIsNotNone(reload_qualified_at)
        self.assertLess(reload_qualified_at - began, 8.)
        self.assertTrue(saw_native_load)
        self.assertEqual([1], [shot['shell_index'] for shot in scene.launches()], policy.status())
        self.assertTrue(scene.launches()[0]['is_he'])
        self.assertEqual('current_he_clip_fallback', policy.decision['reason'])
        self.assertEqual((initial[0], initial[1] - 1), tuple(gun.ammo))
        self.assertEqual(5, gun.clip)
        self.assertEqual(1, scene.control.shot_commits)

    def test_all_five_hesh_pairs_still_find_a_later_native_plate_and_fire(self):
        for pair in HESH_PAIRS:
            with self.subTest(pair=pair):
                scene, target = self.scene(layered=True, hesh=pair)
                gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
                initial = tuple(gun.ammo)
                self.run_until_shots(scene)
                candidate = policy.decision['candidate']
                self.assertEqual('full', policy.frame['shells'][0]['validation_mode'])
                self.assertEqual('penetration', candidate['mode'])
                self.assertGreater(candidate['sample'], 0)
                self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
                self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))
                self.assertEqual(1, scene.control.shot_commits)
                scene.doCleanups()

    def test_native_unknown_does_not_authorize_switch_then_geometry_recovers(self):
        scene, target = self.scene(layered=True)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(target.typeDescriptor, component).hitTester.available = False
        saw_unknown = False
        for unused in range(15):
            self.tick(scene)
            saw_unknown = saw_unknown or any(row.get('armor') == 'unknown'
                                            for row in policy.rows.values())
            self.assertFalse(policy._all_failed((0,)))
            self.assertFalse(scene.launches())
            self.assertEqual(initial, tuple(gun.ammo))
            self.assertEqual(0, gun.shot_index)
            self.assertFalse(hasattr(policy, 'search_started'))
        self.assertTrue(saw_unknown)
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(target.typeDescriptor, component).hitTester.available = True
        scene.pose(target, (20.1, 0., 40.))
        self.run_until_shots(scene)
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))

    def test_blocked_he_point_is_not_armour_failure_even_with_a_verified_ap_point(self):
        scene, target = self.scene()
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        # This low slab blocks the selected lower HE path. The original
        # centre lane and some other AP sample paths remain physically open.
        scene.world[:] = [((9., 1.35, 19.), (11., 1.50, 21.))]
        saw_blocked = saw_alternative = False
        for unused in range(15):
            self.tick(scene)
            self.assertTrue(scene.runtime.combat_stop.active)
            rows = list(policy.rows.values())
            saw_blocked = saw_blocked or any(row['shell_index'] == 0 and
                row['mode'] == 'penetration' and row.get('line') == 'world_blocked' and
                row.get('armor') == 'unknown' for row in rows)
            saw_alternative = saw_alternative or any(row['shell_index'] == 1 and
                policy._executable(row) for row in rows)
            self.assertFalse(policy._all_failed((0,)))
            self.assertFalse(scene.launches())
            self.assertEqual(initial, tuple(gun.ammo))
            self.assertEqual(0, gun.shot_index)
            self.assertFalse(hasattr(policy, 'search_started'))
        self.assertTrue(saw_blocked)
        self.assertTrue(saw_alternative)
        scene.world[:] = []
        scene.pose(target, (20.1, 0., 40.))
        self.run_until_shots(scene)
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))

    def test_target_motion_death_and_new_mission_cannot_reuse_old_single_point(self):
        scene, target = self.scene()
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        self.run_until_shots(scene)
        scene.battle._records['bot:5']['state'].update(alive=False, health=0)
        target.health = 0
        replacement = scene.eligible_enemy(2, armor=300.)
        scene.pose(replacement, (25., 0., 45.))
        scene.sample_original_lanes()
        for unused in range(100):
            self.tick(scene)
            candidate = policy.decision.get('candidate')
            if candidate and candidate['target']['network_id'] == 2:
                break
        self.assertEqual(1, len(scene.launches()))
        scene.pose(replacement, (-25., 0., 45.))
        self.tick(scene)
        self.assertEqual(1, len(scene.launches()), 'a moved target must not consume the old aim')
        self.run_until_shots(scene, count=2)
        self.assertEqual(2, scene.runtime.weapon.target['network_id'])
        self.assertEqual([0, 0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 2, initial[1]), tuple(gun.ammo))
        scene.runtime.set_mission('return_base', {})
        for unused in range(30):
            self.tick(scene)
            self.assertEqual(2, len(scene.launches()))
            self.assertFalse(scene.runtime.combat_stop.active)
            self.assertIsNone(scene.runtime._gun_handoff)
        self.assertEqual(2, scene.control.shot_commits)

    def test_real_current_he_load_finishes_then_verified_ap_loads_and_fires(self):
        for clip in (1, 3):
            with self.subTest(clip=clip):
                scene, target = self.scene(clip=clip, armor=30.)
                scene.set_he(piercing=1.)
                gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
                initial = tuple(gun.ammo)
                # Let the native frontier complete while the observed barrel
                # has not yet followed its real aim source. No decision,
                # ammunition receipt or readiness result is mocked.
                for unused in range(80):
                    scene.fixture.now += .1
                    scene.battle._last_frame_time = scene.now
                    scene.control.update(.1, scene.now)
                    self.assertFalse(scene.launches())
                    self.assertEqual(0, gun.shot_index)
                    if policy.next_shell == 1 and gun.pending_index == 1:
                        break
                self.assertEqual(1, policy.next_shell, policy.status())
                self.assertEqual(1, gun.pending_index)
                saw_ap_loading = []

                def observe():
                    launches = scene.launches()
                    if len(launches) < clip:
                        self.assertEqual(0, gun.shot_index)
                        self.assertIsNone(policy.reload_authority)
                    if gun.shot_index == 1 and gun.reload_time > 0.:
                        saw_ap_loading.append(scene.now)
                    self.assertFalse(hasattr(policy, 'search_started'))

                self.run_until_shots(scene, count=clip + 1, steps=400, observe=observe)
                self.assertEqual([0] * clip + [1],
                    [shot['shell_index'] for shot in scene.launches()])
                self.assertTrue(saw_ap_loading, 'the actual AP load must start')
                self.assertEqual((initial[0] - clip, initial[1] - 1), tuple(gun.ammo))
                self.assertEqual(clip + 1, scene.control.shot_commits)
                scene.doCleanups()


if __name__ == '__main__':
    unittest.main()
