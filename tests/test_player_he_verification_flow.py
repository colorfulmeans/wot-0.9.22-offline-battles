"""HE validation scope reaches real targeting, ammunition and projectile consumers.

The original planner, evaluator, first-trigger proof, battle.shoot and GunState
run unchanged. Only native BSP/material and actuator observations are fixtures.
These tests cannot establish real Windows frame pacing or BigWorld physics.
"""
import math
from types import SimpleNamespace
import unittest
from unittest import mock

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

    @staticmethod
    def move_target_with_armor(scene, target, armor, offset):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(target.typeDescriptor, name).materials[0].armor = armor
        scene.pose(target, (20. + offset, 0., 40.))

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

    def test_ordinary_he_first_point_failure_finds_a_penetrating_point_on_the_same_vehicle(self):
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
        candidate = policy.decision['candidate']
        self.assertEqual(('bot', 5), candidate['target_key'])
        self.assertEqual('penetration', candidate['mode'])
        self.assertNotEqual(0, candidate['sample'])
        self.assertIn(0, he_samples)
        self.assertIn(candidate['sample'], he_samples)
        self.assertFalse(any(row['mode'] == 'he_fallback' for row in policy.rows.values()))

    def test_single_he_returns_to_ap_after_two_consecutive_fallback_rounds(self):
        scene, target = self.scene(armor=300.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        gun.shots[1].piercingPower = (800., 800.)
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot'][
            'piercingPower'] = gun.shots[1].piercingPower
        sequence = (('he_fallback', 300., 1), ('penetration', 10., 0),
                    ('penetration', 10., 0), ('he_fallback', 300., 1),
                    ('he_fallback', 300., 0))
        for number, (mode, armor, streak) in enumerate(sequence, 1):
            self.move_target_with_armor(scene, target, armor, number * .4)
            self.run_until_shots(scene, count=number)
            self.assertEqual(mode, policy.decision['candidate']['mode'])
            self.assertEqual(streak, policy.ordered.he_fallback_rounds)
            self.assertIsNone(gun.pending_index)
            self.assertEqual(int(number == len(sequence)), gun.shot_index)
        self.run_until_shots(scene, count=6)
        self.assertEqual([0, 0, 0, 0, 0, 1],
                         [shot['shell_index'] for shot in scene.launches()])

    def test_refused_second_fallback_does_not_keep_its_next_shell(self):
        scene, target = self.scene(armor=300.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        self.run_until_shots(scene)
        with mock.patch.object(scene.battle._avatar, 'shoot') as refused:
            for unused in range(100):
                self.tick(scene)
                if refused.called:
                    break
            self.assertTrue(refused.called, policy.status())
        self.assertEqual(1, len(scene.launches()))
        self.assertEqual(1, policy.ordered.he_fallback_rounds)
        self.assertEqual((0, None), (gun.shot_index, gun.pending_index))
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.move_target_with_armor(scene, target, 10., .4)
        self.run_until_shots(scene, count=2)
        self.assertEqual('penetration', policy.decision['candidate']['mode'])
        self.assertEqual(0, policy.ordered.he_fallback_rounds)
        self.assertEqual((0, None), (gun.shot_index, gun.pending_index))

    def test_penetrating_he_keeps_its_shell_after_a_full_clip(self):
        scene, target = self.scene(clip=3)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        self.run_until_shots(scene, count=5)
        self.assertEqual([0] * 5, [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((0, None), (gun.shot_index, gun.pending_index))
        self.assertEqual(0, policy.ordered.he_fallback_rounds)

    def test_he_clip_finishes_with_he_after_qualifying_for_the_next_ap_load(self):
        scene, target = self.scene(clip=4, armor=300.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        self.run_until_shots(scene, count=2)
        self.assertTrue(policy.ordered.he_clip_return)
        self.move_target_with_armor(scene, target, 10., .4)
        self.run_until_shots(scene, count=3)
        self.assertEqual('penetration', policy.decision['candidate']['mode'])
        self.assertEqual((0, 1), (gun.shot_index, gun.pending_index))
        self.run_until_shots(scene, count=5)
        self.assertEqual([0, 0, 0, 0, 1], [shot['shell_index'] for shot in scene.launches()])

    def test_he_magazine_failure_falls_back_without_discarding_clip_or_next_ap(self):
        scene, target = self.scene(clip=6, burst=3, armor=300.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        def observe():
            self.assertEqual(0, gun.shot_index)
            self.assertFalse(hasattr(policy, 'search_started'))
            self.assertIsNone(policy.reload_authority)
        self.run_until_shots(scene, observe=observe)
        self.assertEqual('current_he_fallback_contact', policy.decision['reason'])
        self.assertEqual('he_fallback', policy.decision['candidate']['mode'])
        self.assertIsNone(policy.next_plan)
        for streak in (2, 3):
            self.assertTrue(scene.advance())
            self.assertEqual(streak, policy.ordered.he_fallback_rounds)
            self.assertIsNone(gun.pending_index)
        self.assertEqual([0, 1, 2], [shot['burst_index'] for shot in scene.launches()])
        self.assertEqual(1, len(set(shot['burst_group_seq'] for shot in scene.launches())))
        self.assertEqual([0, 0, 0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((initial[0] - 3, initial[1]), tuple(gun.ammo))
        self.assertEqual(3, gun.clip)
        self.assertEqual(3, scene.control.shot_commits)
        self.tick(scene)
        self.assertEqual((0, 3, 1), (gun.shot_index, gun.clip, gun.pending_index))

    def test_two_round_he_burst_promotes_ap_only_after_its_final_commit(self):
        scene, target = self.scene(clip=2, burst=2, armor=300.)
        gun = scene.battle._gun_state
        self.run_until_shots(scene)
        self.assertEqual((0, 1, 1), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertTrue(scene.advance())
        self.assertEqual([0, 0], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual((1, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertGreater(gun.reload_time, 0.)

    def test_single_he_does_not_probe_ap_before_executing_fallback(self):
        scene, target = self.scene(layered=True)
        scene.set_he(piercing=1.)
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        # AP's later upper sample can penetrate, but AP is only reviewed
        # after it physically loads.
        gun.shots[1].piercingPower = (200., 200.)
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot'][
            'piercingPower'] = (200., 200.)
        policy.atomic_time_budget = 0.
        policy.background_budget = 1
        initial = tuple(gun.ammo)
        for unused in range(180):
            self.tick(scene)
            self.assertFalse(policy._rows_for('penetration', 1, fresh_line=True))
            if scene.launches():
                break
            self.assertEqual(initial, tuple(gun.ammo))
            self.assertEqual(0, gun.shot_index)
            self.assertNotEqual('switch_shell', policy.decision['action'])
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

    def test_failed_ap_magazine_loads_he_then_verifies_and_fires_it(self):
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
        saw_native_load = False
        for unused in range(350):
            self.tick(scene)
            self.assertFalse(hasattr(policy, 'search_started'))
            decision = policy.decision
            if decision['action'] == 'reload_clip' and decision.get('early_reload'):
                if reload_qualified_at is None:
                    reload_qualified_at = scene.now
                self.assertEqual(1, decision['shell_index'],
                    'completed ordinary-HE trial must not make early reload choose AP again')
                self.assertEqual('ordered_he_fallback_load', decision['reason'])
                self.assertIsNone(decision['candidate'])
                self.assertFalse(policy._rows_for('he_fallback', 1, fresh_line=True))
            if gun.shot_index == 1 and gun.clip == 0 and gun.reload_time > 0.:
                saw_native_load = True
            if scene.launches():
                break
        self.assertIsNotNone(reload_qualified_at)
        self.assertLess(reload_qualified_at - began, 8.)
        self.assertTrue(saw_native_load)
        self.assertEqual([1], [shot['shell_index'] for shot in scene.launches()], policy.status())
        self.assertTrue(scene.launches()[0]['is_he'])
        self.assertEqual('current_he_fallback_contact', policy.decision['reason'])
        self.assertEqual((initial[0], initial[1] - 1), tuple(gun.ammo))
        self.assertEqual(5, gun.clip)
        self.assertEqual(1, scene.control.shot_commits)

    def test_all_five_hesh_pairs_reach_the_penetrating_point_on_the_current_target(self):
        for pair in HESH_PAIRS:
            with self.subTest(pair=pair):
                scene, target = self.scene(layered=True, hesh=pair)
                gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
                initial = tuple(gun.ammo)
                self.run_until_shots(scene)
                candidate = policy.decision['candidate']
                self.assertEqual('full', policy.frame['shells'][0]['validation_mode'])
                self.assertEqual('penetration', candidate['mode'])
                self.assertNotEqual(0, candidate['sample'])
                self.assertEqual(('bot', 5), candidate['target_key'])
                self.assertTrue(any(row['sample'] == 0 and row['armor'] == 'failed'
                                    for row in policy.rows.values()))
                self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
                self.assertEqual((initial[0] - 1, initial[1]), tuple(gun.ammo))
                self.assertEqual(1, scene.control.shot_commits)
                scene.doCleanups()

    def test_whitelisted_hesh_compares_fallback_only_after_the_current_plate_sweep(self):
        scene, target = self.scene(armor=300., hesh=HESH_PAIRS[0])
        policy = scene.runtime.attack_policy
        self.run_until_shots(scene)
        self.assertEqual('he_fallback', policy.decision['candidate']['mode'])
        self.assertEqual(('bot', 5), policy.decision['candidate']['target_key'])
        points = {row['sample'] for row in policy.rows.values()
                  if row['mode'] == 'penetration' and row['armor'] == 'failed'}
        self.assertEqual(set(policy.frame['targets'][0]['samples']), points)
        self.assertGreater(len(points), 1)
        fallback = [row for row in policy.rows.values() if row['mode'] == 'he_fallback']
        self.assertEqual(points, {row['sample'] for row in fallback})
        self.assertEqual(max(row['expected_damage'] for row in fallback),
                         policy.decision['candidate']['expected_damage'])

    def test_native_he_fallback_chooses_the_largest_blast_on_the_current_vehicle(self):
        scene, target = self.scene(layered=True)
        scene.set_he(piercing=1.)
        policy = scene.runtime.attack_policy
        self.run_until_shots(scene)
        rows = [row for row in policy.rows.values() if row['mode'] == 'he_fallback']
        candidate = policy.decision['candidate']
        self.assertEqual(('bot', 5), candidate['target_key'])
        self.assertEqual('he_fallback', candidate['mode'])
        self.assertEqual(max(row['expected_damage'] for row in rows), candidate['expected_damage'])
        self.assertGreater(candidate['expected_damage'], min(row['expected_damage'] for row in rows))

    def test_fallback_scores_blast_when_only_nominal_penetration_could_pass(self):
        scene, target = self.scene(armor=98.5)
        policy = scene.runtime.attack_policy
        self.run_until_shots(scene)
        candidate = policy.decision['candidate']
        self.assertEqual(('failed', 'he_fallback'), (candidate['armor'], candidate['mode']))
        self.assertEqual(0., candidate['expected_damage'])
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])

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

    def test_blocked_he_point_does_not_trigger_an_ap_scan_or_switch(self):
        scene, target = self.scene()
        gun, policy = scene.battle._gun_state, scene.runtime.attack_policy
        initial = tuple(gun.ammo)
        # This low slab blocks the selected lower HE path. The original
        # centre lane and some other AP sample paths remain physically open.
        scene.world[:] = [((9., 1.35, 19.), (11., 1.50, 21.))]
        saw_blocked = False
        for unused in range(15):
            self.tick(scene)
            self.assertTrue(scene.runtime.combat_stop.active)
            rows = list(policy.rows.values())
            saw_blocked = saw_blocked or any(row['shell_index'] == 0 and
                row['mode'] == 'penetration' and row.get('line') == 'world_blocked' and
                row.get('armor') == 'unknown' for row in rows)
            self.assertFalse(any(row['shell_index'] == 1 for row in rows))
            self.assertFalse(policy._all_failed((0,)))
            self.assertFalse(scene.launches())
            self.assertEqual(initial, tuple(gun.ammo))
            self.assertEqual(0, gun.shot_index)
            self.assertFalse(hasattr(policy, 'search_started'))
        self.assertTrue(saw_blocked)
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
        self.assertEqual(0, gun.shot_index)
        self.assertEqual(1, policy.ordered.he_fallback_rounds)
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
                he_rounds = 2 if clip == 1 else clip
                # Let the native frontier complete while the observed barrel
                # has not yet followed its real aim source. No decision,
                # ammunition receipt or readiness result is mocked.
                for unused in range(80):
                    scene.fixture.now += .1
                    scene.battle._last_frame_time = scene.now
                    scene.control.update(.1, scene.now)
                    self.assertFalse(scene.launches())
                    self.assertEqual(0, gun.shot_index)
                    self.assertIsNone(gun.pending_index)
                self.assertIsNone(policy.next_shell, policy.status())
                saw_ap_loading = []

                def observe():
                    launches = scene.launches()
                    if len(launches) < he_rounds:
                        self.assertEqual(0, gun.shot_index)
                        self.assertIsNone(policy.reload_authority)
                    if gun.shot_index == 1 and gun.reload_time > 0.:
                        saw_ap_loading.append(scene.now)
                    self.assertFalse(hasattr(policy, 'search_started'))

                self.run_until_shots(scene, count=he_rounds + 1, steps=400, observe=observe)
                self.assertEqual([0] * he_rounds + [1],
                    [shot['shell_index'] for shot in scene.launches()])
                self.assertTrue(saw_ap_loading, 'the actual AP load must start')
                self.assertEqual((initial[0] - he_rounds, initial[1] - 1), tuple(gun.ammo))
                self.assertEqual(he_rounds + 1, scene.control.shot_commits)
                scene.doCleanups()


if __name__ == '__main__':
    unittest.main()
