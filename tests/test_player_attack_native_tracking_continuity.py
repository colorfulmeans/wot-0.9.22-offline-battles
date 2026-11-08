"""Deferred ammunition plans through bounded native barrel feedback.

Only native pose/actuator and component collision observations are fixtures.
The installed source functor, copied planner, attack policy, native first edge,
GunState, projectile collision and damage proposal are real. The server send
seam records the proposal; server HP settlement is not exercised. This does not
certify Windows physics or frame pacing, and the actuator grants no navigation
ownership.
"""
import math
import sys
import unittest
from unittest import mock

from test_player_combat_ownership import OwnershipScene, navigation_view
from test_player_fire_admission_complete import Pose, f, shot_geometry


def angle(value):
    return (float(value) + math.pi) % (2. * math.pi) - math.pi


class VectorPose(Pose):
    def applyVector(self, value):
        point = self.applyPoint(value)
        return f._Vector(*(point[index] - self.offset[index] for index in range(3)))


class FiniteTrackingScene(OwnershipScene):
    turret_rate = .35
    gun_rate = .25
    body_rate = .8

    def configure(self, *args, **kwargs):
        super().configure(*args, **kwargs)
        self.battle._runtime.math.Matrix = VectorPose
        self.native_position((0., 0., 0.))
        self.trace = []
        self.battle._advance_local_gun_to(self.entity, self.now)
        return self

    def tick(self, seconds=.1):
        sender = self.battle._sender
        self.native_position(tuple(self.entity.position),
                             self.body.yaw + float(sender.turn) * self.body_rate * seconds)
        self.battle._local_turn_speed = float(sender.turn) * self.body_rate
        rotator = self.battle._avatar.gunRotator
        before = rotator.turretYaw, rotator.gunPitch
        source = rotator.shotPointSourceFunctor
        point = source() if callable(source) else None
        if point is not None:
            yaw, pitch = self.get_angles(self.entity.typeDescriptor, self.body, before, point)
            yaw_delta = max(-self.turret_rate * seconds,
                            min(self.turret_rate * seconds, angle(yaw - before[0])))
            pitch_delta = max(-self.gun_rate * seconds,
                              min(self.gun_rate * seconds, pitch - before[1]))
            rotator.turretYaw = angle(before[0] + yaw_delta)
            rotator.gunPitch = before[1] + pitch_delta
        self.direction = shot_geometry.transform_vehicle_vector(
            (math.sin(rotator.turretYaw) * math.cos(rotator.gunPitch),
             -math.sin(rotator.gunPitch),
             math.cos(rotator.turretYaw) * math.cos(rotator.gunPitch)),
            self.body.yaw, self.body.pitch, self.body.roll)
        self.fixture.now += seconds
        self.battle._advance_local_gun_to(self.entity, self.now)
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.assertIsNone(self.control.last_control_failure)
        self.assertTrue(self.runtime.active)
        decision = self.runtime.attack_policy.decision
        self.trace.append(dict(now=self.now, before=before,
            angles=(rotator.turretYaw, rotator.gunPitch), seconds=seconds,
            source=tuple(point) if point is not None else None,
            body_yaw=self.body.yaw, aligned=self.runtime.state.get('gun_aligned'),
            action=decision['action'], reason=decision['reason'],
            candidate=(decision.get('candidate') or {}).get('key'),
            selected=self.runtime.attack_policy.selected,
            loaded=self.runtime.gun.shot_index, reload=self.runtime.gun.reload_time,
            shots=self.control.shot_commits,
            original=dict(self.original_order()), applied=dict(self.applied_order())))
        return self.applied_order()


class NativeTrackingContinuityTests(unittest.TestCase):
    def scene(self):
        scene = FiniteTrackingScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure(clip=1, burst=1)

    def assert_finite_actuator(self, scene):
        moved = 0
        for row in scene.trace:
            yaw = abs(angle(row['angles'][0] - row['before'][0]))
            pitch = abs(row['angles'][1] - row['before'][1])
            self.assertLessEqual(yaw, scene.turret_rate * row['seconds'] + 1.e-9)
            self.assertLessEqual(pitch, scene.gun_rate * row['seconds'] + 1.e-9)
            moved += yaw > 1.e-5
        self.assertGreater(moved, 5, 'the fixture must actually take multiple frames to aim')

    def assert_projectile_damage_proposal(self, scene, target_id):
        proposals = []
        scene.battle.client.send_projectile_resolve = (
            lambda *args, **kwargs: proposals.append((args, kwargs)) or True)
        ammo = tuple(scene.runtime.gun.ammo)
        # Critical damage imports the same native observation modules directly.
        # No collision, armour, damage or projectile consumer is replaced.
        with mock.patch.dict(sys.modules, {
                'BigWorld': scene.battle._runtime.bigworld,
                'Math': scene.battle._runtime.math}):
            for unused in range(20):
                scene.fixture.now += .05
                scene.battle._advance_projectiles(scene.now)
                if proposals:
                    break
        self.assertEqual(1, len(proposals))
        wire, extras = proposals[0]
        self.assertEqual('impact', wire[3])
        self.assertEqual(target_id, wire[6]['target_id'])
        self.assertEqual(2, wire[6]['shot_result'])
        self.assertGreater(wire[6]['damage'], 0)
        self.assertTrue(extras['hit_vehicle'])
        self.assertEqual(scene.launches()[0]['projectile_id'], wire[1])
        self.assertEqual(ammo, tuple(scene.runtime.gun.ammo))

    def test_first_trigger_waits_for_finite_native_barrel_then_spends_one_round(self):
        scene = self.scene()
        target = scene.eligible_enemy(5)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        scene.battle._avatar.gunRotator.turretYaw = -1.
        initial = tuple(scene.runtime.gun.ammo)
        for unused in range(150):
            scene.tick()
            if scene.launches():
                break
            self.assertEqual(initial, tuple(scene.runtime.gun.ammo))
        self.assertEqual(1, len(scene.launches()), scene.runtime.status())
        self.assertEqual(1, scene.control.shot_commits)
        self.assertEqual((initial[0]-1, initial[1]), tuple(scene.runtime.gun.ammo))
        self.assertEqual(5, scene.runtime.weapon.target['network_id'])
        self.assertTrue(scene.trace[-1]['aligned'])
        self.assertGreater(sum(not row['aligned'] for row in scene.trace[:-1]), 5)
        self.assert_finite_actuator(scene)
        self.assert_projectile_damage_proposal(scene, 5)

    def test_manual_he_reload_does_not_steer_toward_rotating_future_ap_candidates(self):
        scene = self.scene()
        targets = [scene.eligible_enemy(identity, armor=300.) for identity in (5, 6, 7)]
        for target, point in zip(targets, ((0., 0., 40.), (-28., 0., 45.), (28., 0., 45.))):
            scene.pose(target, point)
        gun = scene.runtime.gun
        gun.reload = 7.
        gun.shots[1].shell.kind = 'HIGH_EXPLOSIVE'
        gun.shots[1].shell.explosionRadius = 5.
        gun.shots[1].piercingPower = (10., 10.)
        published = scene.battle.client.effective_params['gun']['shots'][1]['source_shot']
        published['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        published['piercingPower'] = (10., 10.)
        self.assertEqual({5: True, 6: True, 7: True}, scene.sample_original_lanes())
        scene.battle._avatar.gunRotator.turretYaw = -1.
        scene.tick()
        self.assertFalse(scene.launches())
        settings = scene.battle._runtime.constants.VEHICLE_SETTING
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, settings.CURRENT_SHELLS, gun.shots[1].shell.compactDescr))
        self.assertEqual((1, 0), (gun.shot_index, gun.clip))
        initial = tuple(gun.ammo)
        candidates = set()
        waiting = []
        for index in range(65):
            # Real observed armour revisions make different AP candidates
            # qualify, without injecting policy decisions or firing grants.
            soft = targets[1 + (index // 8) % 2]
            for target in targets:
                for component in ('chassis', 'hull', 'turret', 'gun'):
                    getattr(target.typeDescriptor, component).materials[0].armor = (
                        300. if target is soft else 10000.)
                scene.battle._records['bot:%s' % target.id]['armor_revision'] = index
            scene.tick()
            row = scene.trace[-1]
            self.assertEqual(1, gun.shot_index)
            self.assertGreater(gun.reload_time, 0.)
            self.assertFalse(scene.launches())
            self.assertEqual(initial, tuple(gun.ammo))
            if row['action'] == 'switch_shell':
                candidates.add(row['candidate'][1])
                waiting.append(row)
                self.assertEqual(row['original'].get('target_id'),
                                 row['applied'].get('target_id'))
                self.assertEqual(navigation_view(row['original'])['face_position'],
                                 navigation_view(row['applied'])['face_position'])
                self.assertNotEqual(row['candidate'], row['selected'])
            self.assertNotEqual('native_lay_stalled', row['reason'])
        self.assertTrue(waiting, 'the real policy must request replacement during manual loading')
        self.assertGreaterEqual(len(candidates), 2)
        for unused in range(230):
            scene.tick()
            if scene.launches():
                break
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()], scene.runtime.status())
        self.assertEqual((initial[0]-1, initial[1]), tuple(gun.ammo))
        self.assertEqual(1, scene.control.shot_commits)
        self.assert_finite_actuator(scene)
        self.assert_projectile_damage_proposal(
            scene, scene.runtime.weapon.target['network_id'])


if __name__ == '__main__':
    unittest.main()
