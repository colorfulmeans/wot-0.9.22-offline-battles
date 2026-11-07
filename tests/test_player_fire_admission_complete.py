"""First-trigger native admission through the real foreground fire transaction.

FullPlayerRuntime is attached with its complete copied engine. Native matrices,
BSP segments, component hit testers and flat support observations are fixtures;
PlayerControl, NativeAttackEvaluator, TriggerAdmission, scatter, gun accounting
and battle.shoot are production code. Tests deliberately select a native aim
sample where necessary, so they prove admission rather than tactical ranking.
They do not establish Windows BigWorld rendering or physics acceptance.
"""
import math
from types import SimpleNamespace
import unittest
from unittest import mock

import test_port_0922_battle_runtime as f
import test_port_0922_player_burst as burst_tests
import test_player_full_runtime as full_tests
from gui.mods.offline_lan_0922 import ballistics, gun_mechanics, shot_geometry
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.native_aim import (
    NativeAimGeometry, mechanical_reach)
from gui.mods.offline_lan_0922.player_control.trigger_admission import (
    WORLD_CHORDS_PER_ATTEMPT, MAX_PROOF_CHORDS)
from gui.mods.offline_lan_0922.entities.remote_vehicle import collide_vehicle_at_matrix

ADMISSION = 'gui.mods.offline_lan_0922.player_control.trigger_admission'


class Pose(f._RigidMatrix):
    @property
    def translation(self):
        return f._Vector(self.offset)

    @translation.setter
    def translation(self, value):
        self.offset = tuple(value)

    @property
    def pitch(self):
        return -math.asin(max(-1., min(1., self.rows[2][1])))

    @property
    def roll(self):
        return 0.


class SourceRotator(f._GunRotator):
    @property
    def shotPointSourceFunctor(self):
        return self._VehicleGunRotator__shotPointSourceFunctor

    @shotPointSourceFunctor.setter
    def shotPointSourceFunctor(self, value):
        self._VehicleGunRotator__shotPointSourceFunctor = value


class SpatialPose(Pose):
    """Full row-vector Ry * Rx * Rz native observation for cross slopes."""
    @property
    def roll(self):
        return math.atan2(self.rows[0][1], self.rows[1][1])

    def setRotateYPR(self, value):
        yaw, pitch, roll = tuple(float(component) for component in value)
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cr, sr = math.cos(roll), math.sin(roll)
        self.rows = ((cy*cr+sy*sp*sr, cp*sr, -sy*cr+cy*sp*sr),
                     (-cy*sr+sy*sp*cr, cp*cr, sy*sr+cy*sp*cr),
                     (sy*cp, -sp, cy*cp))
        self.offset = (0., 0., 0.)


class BoxTester(f._HitTester1513):
    def localHitTest(self, start, end):
        callback = getattr(self, 'on_hit', None)
        if callback is not None:
            callback()
        distance = shot_geometry.segment_box_entry_distance(
            tuple(start), tuple(end), (tuple(self.bbox[0]), tuple(self.bbox[1])))
        if distance is None:
            return ()
        return ((distance, f._Vector(0., 0., -1.), 1., 0),)


class AutomaticFireScene(unittest.TestCase):
    """Reusable real fire boundary; no authorization/admission mock."""
    def setUp(self):
        self.fixture = burst_tests.PlayerBurstTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Reuse only the reviewed native flat-ground observation seams. The
        # complete planner/driver and firing consumers are not replaced.
        self.complete = full_tests.FullRuntimeTests()
        self.complete.setUp()
        self.addCleanup(self.complete.doCleanups)
        self.battle = battle = self.fixture.battle
        battle.client.team = 1
        battle._runtime.math.Matrix = Pose
        battle._runtime.math.Vector3 = f._Vector
        native_clock = mock.patch.object(battle._runtime.bigworld, 'time', lambda: self.now)
        native_clock.start()
        self.addCleanup(native_clock.stop)
        self.body = Pose()
        battle._local_stabilised_pose = lambda: self.body
        battle._local_body_pose = lambda: self.body
        self.origin, self.direction = (0., 2., 0.), (0., 0., 1.)
        self.world, self.world_queries, self.on_probe = [], [], None
        battle._runtime.bigworld.wg_collideSegment = self.world_probe
        self.entity = self.fixture.entity
        self.pose(self.entity, (0., 0., 0.))
        limits = self.entity.typeDescriptor.gun.pitchLimits
        limits.update(minPitch=((0., -.8), (2.*math.pi, -.8)),
                      maxPitch=((0., .8), (2.*math.pi, .8)))
        rotator = SourceRotator(**vars(battle._avatar.gunRotator))
        rotator._VehicleGunRotator__shotPointSourceFunctor = lambda: f._Vector(0., 2., 100.)
        rotator.getCurShotPosition = lambda: (f._Vector(self.origin), f._Vector(self.direction))
        battle._avatar.gunRotator = rotator
        battle._avatar.autoAim = lambda unused: None
        battle._avatar.shoot = lambda: battle.shoot(0., 0.)
        battle._runtime.get_shot_angles = self.get_angles
        battle._navigation_graph = self.complete.battle._navigation_graph
        battle._arena_bounds = battle._navigation_graph['bounds']
        battle._start_message.update(map='01_karelia',
            bots=[dict(id=999, team=2)], bot_skill_mode='elite')
        own_record = battle._records['player:1']
        own_record.update(ready=True, team=1, vehicle='ussr:R11_MS-1')
        own_record['state'].update(id=1, team=1, x=0., y=0., z=0., yaw=0.)
        self.target = self.vehicle(42, (0., 0., 100.), team=2)
        self.control = PlayerControl(battle, ('fire',), notify=lambda text: None)
        battle._player_control = self.control
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: None
        self.assertTrue(self.control.live())
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime = self.control.runtime
        self.admission = self.control._admission()
        self.control.target_engine = self.target.id
        self.lay()

    @property
    def now(self):
        return self.fixture.now

    def pose(self, vehicle, position):
        vehicle.position = f._Vector(position)
        vehicle.matrix = Pose()
        vehicle.matrix.translation = position
        vehicle.appearance.turretMatrix = Pose()
        vehicle.appearance.gunMatrix = Pose()

    def vehicle(self, identity, position, team):
        desc = f._Descriptor()
        for name in ('chassis', 'hull', 'turret', 'gun'):
            comp = getattr(desc, name)
            comp.hitTester = BoxTester(*comp.hitTester.bbox[:2])
            comp.materials = {0: SimpleNamespace(armor=10., vehicleDamageFactor=1., kind=0)}
        vehicle = f._Vehicle(identity, desc, f._Vector(position), (0., 0., 0.), {'health': 500})
        self.pose(vehicle, position)
        vehicle.collideSegmentExt = lambda first, last: collide_vehicle_at_matrix(
            vehicle, vehicle.matrix, first, last, self.battle._runtime.math)
        self.battle._runtime.bigworld.entities[identity] = vehicle
        self.battle._records['bot:%s' % identity] = dict(engine_id=identity, ready=True,
            team=team, state=dict(id=identity, team=team, health=500, alive=True),
            spot_visible=team == 2, kind='bot', network_id=identity)
        return vehicle

    def world_probe(self, space, first, last, mask):
        first, last = tuple(first), tuple(last)
        self.world_queries.append((first, last))
        if self.on_probe is not None:
            self.on_probe()
        hits = [shot_geometry.segment_box_entry_distance(first, last, bounds)
                for bounds in self.world]
        hits = [value for value in hits if value is not None]
        if not hits:
            return None
        length = math.sqrt(sum((last[i]-first[i])**2 for i in range(3)))
        fraction = min(hits)/length
        return (f._Vector(tuple(first[i]+fraction*(last[i]-first[i]) for i in range(3))),)

    def get_angles(self, desc, body, previous, point):
        shot = self.battle._gun_state.shots[self.battle._gun_state.shot_index]
        roots = ballistics.ballistic_solutions(self.origin, tuple(point), shot.speed, shot.gravity)
        if not roots:
            raise ValueError('unreachable native source')
        pitch = roots[0][0]
        yaw = math.atan2(point[0]-self.origin[0], point[2]-self.origin[2])
        direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch), math.cos(yaw)*math.cos(pitch))
        return shot_geometry.world_direction_to_local_gun_angles(direction, body.yaw, body.pitch, body.roll)

    def observe(self):
        self.runtime.now = self.now
        self.battle._last_frame_time = self.now
        self.runtime._observe(self.now)

    def lay(self, move_barrel=True, sample_index=0, mode='penetration', target_velocity=None):
        """Evaluate one actual plate, then use the native source verifier."""
        gun = self.battle._gun_state
        sample = shot_geometry.ordered_vehicle_aim_samples(self.target.typeDescriptor)[sample_index]
        point = shot_geometry.vehicle_aim_point(sample, dict(position=tuple(self.target.position)))
        shot = gun.shots[gun.shot_index]
        if target_velocity is not None:
            self.battle._records['bot:%s' % self.target.id]['state']['velocity'] = target_velocity
            point = ballistics.ballistic_intercept(self.origin, point, target_velocity,
                                                   shot.speed, shot.gravity)[0]
        pitch = ballistics.ballistic_solutions(self.origin, point, shot.speed, shot.gravity)[0][0]
        yaw = math.atan2(point[0]-self.origin[0], point[2]-self.origin[2])
        if move_barrel:
            self.direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch), math.cos(yaw)*math.cos(pitch))
            local = shot_geometry.world_direction_to_local_gun_angles(
                self.direction, self.body.yaw, self.body.pitch, self.body.roll)
            self.battle._avatar.gunRotator.turretYaw = local[0]
            self.battle._avatar.gunRotator.gunPitch = local[1]
        policy = self.runtime.attack_policy
        for unused in range(80):
            self.observe()
            policy.frame = policy.evaluator.snapshot(self.now)
            jobs = [job for job in policy._jobs(mode, gun.shot_index)
                    if job[2]['entity'] is self.target and job[3] == sample_index]
            self.assertEqual(1, len(jobs))
            row = policy._evaluate(jobs[0], self.now, 'foreground')
            if row.get('line') != 'pending' and row.get('solution') is not None:
                break
            self.fixture.now += .1
        self.assertIsNotNone(row.get('solution'), row)
        self.candidate = row
        policy._choose('aim', 'selected_native_fixture_sample', row)
        solution = row['solution']
        target = row['target']
        angles = shot_geometry.world_direction_to_local_gun_angles(
            solution['direction'], self.body.yaw, self.body.pitch, self.body.roll)
        self.runtime.weapon.aim(self.runtime.state, target,
            dict(aim_position=solution['point']),
            dict(turret_yaw=angles[0], gun_pitch=angles[1]))
        rotator = self.battle._avatar.gunRotator
        # A native actuator observation, not an always-true readiness gate.
        self.runtime.state['gun_aligned'] = bool(
            self.runtime.weapon.verified and
            abs(rotator.turretYaw-angles[0]) <= 1.e-6 and
            abs(rotator.gunPitch-angles[1]) <= 1.e-6)
        return solution

    def step(self, seconds=.1):
        self.fixture.now += seconds
        self.observe()

    def fire(self):
        self.observe()
        return self.runtime.engine._fire(self.runtime.state,
            self.runtime.engine._gun_states[self.runtime.actor_id], 1.,
            self.entity.typeDescriptor)

    def advance(self, seconds=.1):
        self.step(seconds)
        self.battle._advance_local_gun_to(self.entity, self.now)
        return self.battle._advance_local_player_burst()

    def launches(self):
        return sorted(self.battle._projectile_meta.values(), key=lambda row: row['shot_seq'])

    def set_he(self, piercing=None):
        shot = self.battle._gun_state.shots[0]
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        source = self.battle.client.effective_params['gun']['shots'][0]['source_shot']
        source['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        if piercing is not None:
            shot.piercingPower = (float(piercing), float(piercing))
            source['piercingPower'] = (float(piercing), float(piercing))

    def assert_unspent(self):
        self.assertEqual([20, 10], self.battle._gun_state.ammo)
        self.assertEqual(6, self.battle._gun_state.clip)
        self.assertFalse(self.battle._projectile_meta)
        self.assertIsNone(self.battle._local_player_burst)
        self.assertFalse([row for row in self.battle.client.sent
                          if row[0] == 'projectile_launch'])

    def friend_beside_barrel_path(self):
        """Only a 90-degree rotated attached gun can touch the native ray."""
        shot = self.battle._gun_state.shots[self.battle._gun_state.shot_index]
        flight = (50.-self.origin[2])/(shot.speed*self.direction[2])
        height = (self.origin[1]+shot.speed*self.direction[1]*flight-
                  .5*shot.gravity*flight*flight)
        # The fixture gun pivot is chassis.hullPosition.y (.6) plus
        # turret.gunPosition.y (.9); its barrel extends 2 m forward.
        friend = self.vehicle(43, (-1.85, height-1.5, 50.), 1)
        self.observe()
        return friend

    def friendly_verdict(self):
        self.observe()
        return self.runtime.geometry._bot_friendly_path_verdict(
            self.runtime.current_source(), self.candidate['solution']['path'], 0.)

    def detach_turret(self, vehicle):
        vehicle.health = f._TURRET_DETACHED
        vehicle._Vehicle__turretDetachmentConfirmed = True
        self.battle._records['bot:%s' % vehicle.id]['state'].update(
            alive=False, health=vehicle.health)
        self.assertTrue(vehicle.isTurretDetached)


class ArtilleryFireScene(AutomaticFireScene):
    """Full SPG planning loop with a low-root native solver and actuator.

    The analytical 50 m/s shell and 60 m ridge are controlled observations,
    not a claim about a stock vehicle. Only the native body/barrel response and
    BSP callback are supplied. No candidate, arc, source proof, alignment or
    fire admission is forced to succeed.
    """
    def configure_artillery(self, ridge=True, velocity=(0., 0., 0.)):
        self.control.close()
        descriptor = self.entity.typeDescriptor
        descriptor.type.tags = ('SPG',)
        descriptor.gun.clip = (1,)
        descriptor.gun.burst = (1, 0.)
        descriptor.gun.reloadTime = 12.
        descriptor.gun.pitchLimits.update(
            absolute=(-1.5, .2),
            minPitch=((0., -1.5), (2.*math.pi, -1.5)),
            maxPitch=((0., .2), (2.*math.pi, .2)))
        for index, shot in enumerate(descriptor.gun.shots):
            shot.speed, shot.gravity, shot.maxDistance = 50., 10., 5000.
            shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 3.
            source = self.battle.client.effective_params['gun']['shots'][index]['source_shot']
            source.update(speed=50., gravity=10., maxDistance=5000.)
            source['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=3.)
        self.battle._gun_state = gun_mechanics.GunState(
            descriptor, ammo_layout={101: 20, 102: 10})
        self.battle._gun_state.clip = 1
        self.battle._gun_state.reload_time = 0.
        self.origin, self.direction = (0., 2., 0.), (0., 0., 1.)
        self.pose(self.target, (0., 0., 200.))
        self.target_velocity = tuple(velocity)
        self.world = [((-100., -10., 99.), (100., 60., 101.))] if ridge else []
        self.source_queries, self.artillery_trace = [], []
        self.barrel_enabled = True
        self.battle._runtime.get_shot_angles = self.observed_source_angles
        self.battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        rotator = self.battle._avatar.gunRotator
        rotator.turretYaw = rotator.gunPitch = 0.
        self.control = PlayerControl(self.battle, ('fire',), notify=lambda text: None)
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: None
        self.battle._player_control = self.control
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime, self.admission = self.control.runtime, self.control._admission()
        # The generic flat-world fixture replaces this native query with an
        # open sky. SPG coverage explicitly restores the copied production
        # chord consumer, so this scenario actually observes the ridge.
        from gui.mods.offline_lan_0922.player_control.copied.battle_geometry import CopiedBattleGeometry
        self.runtime.geometry._artillery_arc_probe = (
            CopiedBattleGeometry._artillery_arc_probe.__get__(
                self.runtime.geometry, type(self.runtime.geometry)))
        self.control.target_engine = None
        return self

    def observed_source_angles(self, *args):
        result = self.get_angles(*args)
        self.source_queries.append(dict(at=self.now, source=tuple(args[-1]),
                                        angles=tuple(result)))
        return result

    def artillery_tick(self, seconds=.1):
        self.fixture.now += seconds
        if any(self.target_velocity):
            self.pose(self.target, tuple(self.target.position[index] +
                self.target_velocity[index]*seconds for index in range(3)))
        self.battle._records['bot:%s' % self.target.id]['state']['velocity'] = self.target_velocity
        # Emulate only the native rotator reading its installed input source.
        # It chooses the low root, even when the controller wants a high arc.
        source = self.battle._avatar.gunRotator.shotPointSourceFunctor
        if self.barrel_enabled and callable(source) and source() is not None:
            yaw, pitch = self.observed_source_angles(
                self.entity.typeDescriptor, self.body, (0., 0.), source())
            rotator = self.battle._avatar.gunRotator
            rotator.turretYaw, rotator.gunPitch = yaw, pitch
            self.direction = shot_geometry.transform_vehicle_vector(
                (math.sin(yaw)*math.cos(pitch), -math.sin(pitch),
                 math.cos(yaw)*math.cos(pitch)),
                self.body.yaw, self.body.pitch, self.body.roll)
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.artillery_trace.append(dict(
            at=self.now, action=self.runtime.attack_policy.decision.get('action'),
            target=self.runtime.state.get('target_id'),
            aligned=self.runtime.state.get('gun_aligned'),
            pitch=self.battle._avatar.gunRotator.gunPitch,
            native_yaw=self.battle._avatar.gunRotator.turretYaw,
            desired=dict(self.runtime.state.get('_diagnostic_aim_intent') or {}),
            source=self.runtime.weapon.source_point,
            intent=bool(self.runtime.engine._artillery_intents),
            verified=self.runtime.weapon.verified,
            order=dict(self.control.last_order),
            admission=dict(self.admission.receipt),
            failure=self.control.last_control_failure))

    def run_until_artillery_launch(self, limit=300):
        for unused in range(limit):
            self.artillery_tick()
            self.assertTrue(self.control.active, self.artillery_trace[-1])
            if self.launches():
                return self.launches()[0]
        self.fail('SPG loop never committed: %r' % self.artillery_trace[-4:])


class AutomaticArtilleryAdmissionTests(ArtilleryFireScene):
    def test_copied_high_arc_reaches_native_source_and_real_first_trigger(self):
        self.configure_artillery()
        with mock.patch.object(self.battle, 'shoot', wraps=self.battle.shoot) as shoot, \
                mock.patch.object(self.admission, 'prepare', wraps=self.admission.prepare) as prepare:
            launch = self.run_until_artillery_launch()
        self.assertEqual('SPG', self.runtime.state['profile']['class_tag'])
        self.assertLess(self.battle._avatar.gunRotator.gunPitch, -.9)
        self.assertTrue(self.source_queries)
        self.assertTrue(shoot.called)
        self.assertTrue(prepare.called)
        self.assertEqual(1, launch['burst_count'])
        self.assertEqual(0, launch['burst_index'])
        self.assertEqual([19, 10], self.battle._gun_state.ammo)
        self.assertEqual(0, self.battle._gun_state.clip)
        self.assertTrue(any(min(first[2], last[2]) <= 100. <= max(first[2], last[2])
                            for first, last in self.world_queries))

    def test_high_arc_cross_slope_uses_actual_full_body_and_local_barrel(self):
        self.configure_artillery()
        self.body = SpatialPose()
        self.body.setRotateYPR((.2, -.08, .12))
        self.battle._runtime.math.Matrix = SpatialPose
        self.battle._local_matrix = self.body
        self.battle._local_pose_matrix = self.body
        self.battle._local_pitch, self.battle._local_roll = self.body.pitch, self.body.roll
        self.battle.local_pose = lambda: (tuple(self.body.translation), self.body.yaw)
        launch = self.run_until_artillery_launch()
        rotator = self.battle._avatar.gunRotator
        local = (math.sin(rotator.turretYaw)*math.cos(rotator.gunPitch),
                 -math.sin(rotator.gunPitch),
                 math.cos(rotator.turretYaw)*math.cos(rotator.gunPitch))
        actual = tuple(self.body.applyPoint(f._Vector(local)))
        for index in range(3):
            self.assertAlmostEqual(actual[index]*50., launch['velocity'][index], places=4)
        self.assertGreater(launch['velocity'][1], 40.)
        self.assertAlmostEqual(.2, self.runtime.state['yaw'])
        self.assertAlmostEqual(-.08, self.runtime.state['pitch'])
        self.assertAlmostEqual(.12, self.runtime.state['roll'])
        self.assertEqual([19, 10], self.battle._gun_state.ammo)

    def test_both_native_arcs_blocked_spend_nothing_and_recover_when_wall_clears(self):
        self.configure_artillery()
        self.world = [((-100., -10., 99.), (100., 300., 101.))]
        for unused in range(180):
            self.artillery_tick()
            self.assertTrue(self.control.active, self.artillery_trace[-1])
        self.assertTrue(self.world_queries)
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, self.battle._gun_state.clip)
        self.assertIsNone(self.battle._local_player_burst)
        self.world[:] = []
        launch = self.run_until_artillery_launch()
        self.assertEqual([19, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, launch['burst_count'])

    def test_new_high_arc_world_obstacle_is_checked_by_actual_first_trigger(self):
        self.configure_artillery()
        original, calls = self.battle.shoot, []
        def obstacle_appears(*args):
            if not calls:
                # The copied planner's high-arc proof has completed by now;
                # put a new ceiling in the real native ray before admission.
                self.world.append(((-100., 90., 95.), (100., 115., 105.)))
            calls.append(self.now)
            return original(*args)
        self.battle.shoot = obstacle_appears
        for unused in range(220):
            self.artillery_tick()
            if self.control.last_fire_failure == 'auto_world_blocked':
                break
        self.assertTrue(calls)
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure,
                         self.artillery_trace[-4:])
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, self.battle._gun_state.clip)
        self.world.pop()
        launch = self.run_until_artillery_launch()
        self.assertEqual([19, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, launch['burst_count'])

    def test_moving_target_high_arc_uses_current_motion_at_native_commit(self):
        self.configure_artillery(velocity=(.5, 0., 0.))
        captured, original = [], self.battle._preinstall_player_projectile
        def capture_native_commit(*args):
            proof = self.admission.pending['proof']
            captured.append(dict(at=self.now, proof=dict(proof),
                                 target=tuple(self.target.position)))
            return original(*args)
        self.battle._preinstall_player_projectile = capture_native_commit
        launch = self.run_until_artillery_launch(limit=600)
        self.assertTrue(captured)
        proof = captured[-1]['proof']
        self.assertEqual((.5, 0., 0.), proof['solution']['velocity'])
        self.assertGreater(proof['solution']['point'][0], captured[-1]['target'][0])
        self.assertEqual('vehicle', proof['terminal_kind'])
        self.assertEqual(self.target.id, proof['terminal_vehicle'])
        self.assertLess(self.battle._avatar.gunRotator.gunPitch, -.9)
        self.assertEqual([19, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, launch['burst_count'])

    def test_high_arc_target_pose_change_after_preinstall_cannot_use_old_proof(self):
        self.configure_artillery()
        original, changed = self.battle._preinstall_player_projectile, []
        def native_target_moves(*args):
            installed = original(*args)
            if not changed:
                changed.append(self.now)
                self.pose(self.target, (12., 0., 200.))
            return installed
        self.battle._preinstall_player_projectile = native_target_moves
        for unused in range(300):
            self.artillery_tick()
            if changed:
                break
        self.assertTrue(changed)
        self.assertIn(self.control.last_fire_failure,
                      ('auto_target_changed', 'auto_target_pose_changed'))
        self.assertFalse(self.launches())
        self.assertEqual([20, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, self.battle._gun_state.clip)
        self.assertIsNone(self.battle._local_player_burst)
        self.battle._preinstall_player_projectile = original
        launch = self.run_until_artillery_launch()
        self.assertGreater(self.runtime.weapon.point[0], 10.)
        self.assertEqual([19, 10], self.battle._gun_state.ammo)
        self.assertEqual(1, launch['burst_count'])


class AutomaticFireAdmissionTests(AutomaticFireScene):
    def test_external_native_source_takeover_revokes_only_the_next_trigger(self):
        rotator = self.battle._avatar.gunRotator
        external = lambda: f._Vector(10., 5., 30.)
        rotator.shotPointSourceFunctor = external
        self.assertFalse(self.fire())
        self.assert_unspent()
        self.assertIs(external, rotator.shotPointSourceFunctor)

    def test_external_native_client_mode_takeover_revokes_only_the_next_trigger(self):
        self.battle._avatar.gunRotator.clientMode = False
        self.assertFalse(self.fire())
        self.assert_unspent()

    def lease_change_during_install(self, field):
        rotator, original = self.battle._avatar.gunRotator, self.battle._preinstall_player_projectile
        external = lambda: f._Vector(10., 5., 30.)
        def replace_native_owner(*args):
            installed = original(*args)
            if field == 'source':
                rotator.shotPointSourceFunctor = external
            else:
                rotator.clientMode = False
            return installed
        self.battle._preinstall_player_projectile = replace_native_owner
        self.assertFalse(self.fire())
        self.assert_unspent()
        if field == 'source':
            self.assertIs(external, rotator.shotPointSourceFunctor)
        else:
            self.assertFalse(rotator.clientMode)

    def test_native_source_takeover_inside_preinstall_cannot_commit_first_edge(self):
        self.lease_change_during_install('source')

    def test_native_client_mode_takeover_inside_preinstall_cannot_commit_first_edge(self):
        self.lease_change_during_install('mode')

    def test_rotated_friend_gun_blocks_first_trigger_until_detached(self):
        friend = self.friend_beside_barrel_path()
        self.assertTrue(self.friendly_verdict()['clear'])
        friend.appearance.turretMatrix.setRotateY(math.pi/2.)
        self.assertFalse(self.friendly_verdict()['clear'])
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assert_unspent()
        self.detach_turret(friend)
        self.step()
        self.assertTrue(self.friendly_verdict()['clear'])
        self.assertTrue(self.fire(), self.admission.receipt)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_overhead_friend_is_not_a_two_dimensional_lane_blocker(self):
        self.vehicle(43, (0., -12., 50.), 1)
        self.assertTrue(self.friendly_verdict()['clear'])
        self.assertTrue(self.fire(), self.admission.receipt)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_live_front_enemy_and_wreck_use_distinct_native_guards(self):
        blocker = self.vehicle(43, (0., 0., 50.), 1)
        self.assertFalse(self.friendly_verdict()['clear'])
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assert_unspent()
        record = self.battle._records['bot:43']
        record.update(team=2, spot_visible=True)
        record['state']['team'] = 2
        self.step()
        # Live enemies are not allies: the native centre-contact guard, not
        # the friendly lane guard, rejects a different intervening target.
        self.assertTrue(self.friendly_verdict()['clear'])
        self.assertFalse(self.fire())
        self.assertEqual('auto_front_vehicle', self.control.last_fire_failure)
        self.assert_unspent()
        record['state'].update(alive=False, health=0)
        blocker.health = 0
        self.step()
        self.assertFalse(self.friendly_verdict()['clear'])
        self.assertFalse(self.fire())
        # The copied dead/debris guard intentionally has no ally escape
        # metadata; it is reported as a closed, unproved lane.
        self.assertEqual('auto_lane_geometry_unknown', self.control.last_fire_failure)
        self.assert_unspent()

    def test_missing_attached_friend_gun_cannot_certify_a_clear_first_trigger(self):
        friend = self.friend_beside_barrel_path()
        friend.appearance.turretMatrix.setRotateY(math.pi/2.)
        self.assertFalse(self.friendly_verdict()['clear'])
        friend.typeDescriptor.gun.hitTester = None
        self.assertFalse(self.fire())
        self.assert_unspent()
        # A physically absent turret has no attached gun to prove. Its
        # separate landed-debris authority is tested independently below.
        self.detach_turret(friend)
        self.step()
        self.assertTrue(self.fire(), self.admission.receipt)

    def test_current_detached_turret_contact_rejects_real_first_trigger(self):
        obstacle = SimpleNamespace(block_distance=mock.Mock(return_value=0.))
        self.battle._detached_turret_obstacles = obstacle
        self.battle._projectile_server_time_ms = 1234
        self.battle._projectile_server_local_time = self.now
        self.assertFalse(self.fire())
        self.assertEqual('auto_lane_geometry_unknown', self.control.last_fire_failure)
        self.assertTrue(obstacle.block_distance.called)
        self.assertEqual(1234, obstacle.block_distance.call_args.args[2])
        self.assert_unspent()
        obstacle.block_distance.reset_mock()
        obstacle.block_distance.return_value = None
        self.step(.2)
        self.assertTrue(self.fire(), self.admission.receipt)
        self.assertTrue(obstacle.block_distance.called)
        self.assertLessEqual(abs(1434-obstacle.block_distance.call_args.args[2]), 1)

    def test_centre_ray_reports_visible_front_enemy_without_debit(self):
        self.vehicle(43, (0., 0., 25.), 2)
        self.assertFalse(self.fire())
        self.assertEqual('auto_front_vehicle', self.admission.receipt['reason'])
        self.assert_unspent()

    def test_new_trigger_has_real_proof_and_each_tail_has_one_ammo_debit(self):
        self.world_queries[:] = []
        self.assertTrue(self.fire(), self.admission.receipt)
        self.assertTrue(self.world_queries)
        for unused in range(2):
            self.world_queries[:] = []
            self.assertTrue(self.advance())
            self.assertEqual([], self.world_queries)
        self.assertEqual([17, 10], self.battle._gun_state.ammo)
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in self.launches()])
        self.assertEqual(3, self.control.shot_commits)

    def test_first_trigger_rechecks_live_friend_after_plate_candidate(self):
        self.vehicle(43, (0., 0., 50.), 1)
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_lane', self.admission.receipt['reason'])
        self.assert_unspent()

    def test_first_trigger_rechecks_armor_not_only_candidate_boolean(self):
        for name in ('chassis', 'hull', 'turret', 'gun'):
            getattr(self.target.typeDescriptor, name).materials[0].armor = 10000.
        self.assertEqual('passed', self.candidate['armor'])
        self.assertFalse(self.fire())
        self.assertEqual('auto_actual_barrel_armour', self.admission.receipt['reason'])
        self.assert_unspent()

    def test_real_target_pose_change_invalidates_old_first_trigger_evidence(self):
        self.pose(self.target, (10., 0., 100.))
        self.assertFalse(self.fire())
        self.assertEqual('auto_target_pose_changed', self.admission.receipt['reason'])
        self.assert_unspent()

    def test_missing_native_plate_tester_cannot_become_a_passing_candidate(self):
        self.target.typeDescriptor.hull.hitTester.localHitTest = None
        self.runtime.attack_policy.reset()
        self.runtime.attack_policy.evaluator.jobs.clear()
        self.lay()
        self.assertEqual('unknown', self.candidate['armor'])
        self.assertFalse(self.fire())
        self.assert_unspent()

    def test_exact_scattered_lane_cannot_reroll_until_friend_moves(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        friend = self.vehicle(43, (-5., 0., 50.), 1)
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.) as gauss, \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
            candidate = self.admission.pending
            velocity = candidate['proof']['velocity']
            self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
            for unused in range(4):
                self.step()
                self.assertFalse(self.fire())
                self.assertIs(candidate, self.admission.pending)
            self.assertEqual(1, sum(call.args == (0., 1.) for call in gauss.call_args_list))
            self.assert_unspent()
            self.pose(friend, (-20., 0., 50.))
            self.step()
            self.assertTrue(self.fire(), self.admission.receipt)
        self.assertEqual(velocity, tuple(self.launches()[0]['velocity']))
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_scattered_near_world_contact_is_not_hidden_by_clear_centre(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self.world = [((-2.5, 0., 19.), (-1.5, 3., 21.))]
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.), \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
            candidate = self.admission.pending
            self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
            self.step()
            self.assertFalse(self.fire())
            self.assertIs(candidate, self.admission.pending)
            self.assert_unspent()
            self.world[:] = []
            self.step()
            self.assertTrue(self.fire(), self.admission.receipt)

    def test_scattered_miss_proves_allies_beyond_the_target_plane(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self.vehicle(43, (-15., 0., 150.), 1)
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.), \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.admission.pending['proof']
        self.assertTrue(proof['done'])
        self.assertNotIn('terminal_impact', proof)
        self.assertGreater(proof['path'][-1][2], 150.)
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assert_unspent()

    def test_external_only_penetration_cannot_hide_a_rear_friend(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        external = self.vehicle(44, (-5., 0., 50.), 2)
        for name in ('chassis', 'hull', 'turret', 'gun'):
            material = getattr(external.typeDescriptor, name).materials[0]
            material.armor, material.vehicleDamageFactor = 1., 0.
        self.vehicle(43, (-15., 0., 150.), 1)
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.), \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.admission.pending['proof']
        self.assertTrue(proof['done'])
        self.assertNotIn('terminal_impact', proof)
        self.assertGreater(proof['path'][-1][2], 150.)
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assert_unspent()

    def test_real_native_target_contact_stops_proof_before_rear_ally(self):
        self.vehicle(43, (0., 0., 150.), 1)
        seen, original = [], self.battle._preinstall_player_projectile
        def capture_proof(*args):
            seen.append(dict(self.admission.pending['proof']))
            return original(*args)
        self.battle._preinstall_player_projectile = capture_proof
        self.assertTrue(self.fire(), self.admission.receipt)
        self.assertEqual('vehicle', seen[0]['terminal_kind'])
        self.assertLess(seen[0]['terminal_impact'][2], 100.)
        self.assertGreater(seen[0]['target_queries'], 0)

    def test_he_endpoint_splash_blocks_friend_outside_shell_lane(self):
        self.set_he()
        self.lay()
        self.vehicle(43, (4., 0., 96.), 1)
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assert_unspent()

    def test_he_scattered_ground_impact_beyond_target_plane_checks_splash(self):
        self.set_he()
        self.lay()
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self.world = [((-18., -5., 149.), (-12., 5., 150.))]
        self.vehicle(43, (-18.5, 0., 149.), 1)
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.), \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.admission.pending['proof']
        self.assertEqual('world', proof['terminal_kind'])
        self.assertGreater(proof['terminal_impact'][2], 100.)
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assert_unspent()

    def test_he_first_visible_enemy_not_selected_target_defines_splash(self):
        self.set_he()
        self.lay()
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        intervening = self.vehicle(44, (-5., 0., 50.), 2)
        self.vehicle(43, (-8., 0., 48.), 1)
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.), \
                mock.patch(ADMISSION+'.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.admission.pending['proof']
        self.assertEqual(intervening.id, proof['terminal_vehicle'])
        self.assertEqual('vehicle', proof['terminal_kind'])
        self.assertLess(proof['terminal_impact'][2], 50.)
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assert_unspent()

    def test_oversized_collision_roster_cannot_silently_skip_native_actors(self):
        for identity in range(50, 80):
            self.vehicle(identity, (30., 0., 100.), 2)
        self.assertFalse(self.fire())
        self.assertEqual('auto_collision_geometry_unknown', self.control.last_fire_failure)
        self.assert_unspent()

    def test_fresh_dynamic_check_after_world_callback_prevents_launch(self):
        friend = self.vehicle(43, (20., 0., 50.), 1)
        def enter_lane():
            self.on_probe = None
            self.pose(friend, (0., 0., 50.))
        self.on_probe = enter_lane
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assert_unspent()

    def test_preinstall_reentry_cannot_send_a_different_native_pose(self):
        original, direction = self.battle._preinstall_player_projectile, self.direction
        def move_after_install(*args):
            result = original(*args)
            self.direction = (.2, 0., math.sqrt(.96))
            return result
        self.battle._preinstall_player_projectile = move_after_install
        self.assertFalse(self.fire())
        self.assertEqual('auto_pose_changed', self.control.last_fire_failure)
        self.assert_unspent()
        self.battle._preinstall_player_projectile = original
        self.direction = direction
        self.step()
        self.assertTrue(self.fire(), self.admission.receipt)

    def test_stop_during_native_plate_query_revokes_uncommitted_trigger(self):
        tester = self.target.typeDescriptor.hull.hitTester
        def stop():
            tester.on_hit = None
            self.control.stop('native_plate_callback')
        tester.on_hit = stop
        self.assertFalse(self.fire())
        self.assertFalse(self.control.active)
        self.assert_unspent()

    def test_preinstall_canonical_trajectory_cannot_replace_proven_velocity(self):
        original = self.battle._preinstall_player_projectile
        def replace_velocity(*args):
            result = original(*args)
            self.battle._projectile_meta[result]['velocity'] = (800., 0., 0.)
            return result
        self.battle._preinstall_player_projectile = replace_velocity
        self.assertFalse(self.fire())
        self.assertEqual('auto_launch_changed', self.control.last_fire_failure)
        self.assert_unspent()

    def test_stop_after_preinstall_still_revokes_uncommitted_first_edge(self):
        original = self.battle._preinstall_player_projectile
        def stop_after_install(*args):
            result = original(*args)
            self.control.stop('stop_during_first_install')
            return result
        self.battle._preinstall_player_projectile = stop_after_install
        self.assertFalse(self.fire())
        self.assertFalse(self.control.active)
        self.assert_unspent()

    def test_native_target_articulation_change_invalidates_terminal_proof(self):
        original = self.battle._preinstall_player_projectile
        def turn_turret_after_install(*args):
            result = original(*args)
            self.target.appearance.turretMatrix.setRotateY(.5)
            return result
        self.battle._preinstall_player_projectile = turn_turret_after_install
        self.assertFalse(self.fire())
        self.assertIn(self.control.last_fire_failure,
                      ('auto_target_changed', 'auto_target_pose_changed'))
        self.assert_unspent()

    def test_native_hull_articulation_after_preinstall_invalidates_source_proof(self):
        original = self.battle._preinstall_player_projectile
        def change_body_after_install(*args):
            result = original(*args)
            self.body.setRotateYPR((0., -.1, 0.))
            return result
        self.battle._preinstall_player_projectile = change_body_after_install
        self.assertFalse(self.fire())
        self.assertEqual('auto_source_pose_changed', self.control.last_fire_failure)
        self.assert_unspent()

    def long_range(self):
        for shot in self.battle._gun_state.shots:
            shot.speed, shot.maxDistance = 100., 5000.
        for row in self.battle.client.effective_params['gun']['shots']:
            row['source_shot'].update(speed=100., maxDistance=5000.)
        self.pose(self.target, (0., 0., 800.))
        self.lay()

    def test_long_path_uses_bounded_slices_without_redrawing_or_debiting(self):
        self.long_range()
        candidate, attempts = None, 0
        for unused in range(20):
            self.world_queries[:] = []
            success = self.fire()
            attempts += 1
            self.assertLessEqual(len(self.world_queries), WORLD_CHORDS_PER_ATTEMPT)
            if success:
                break
            self.assert_unspent()
            if candidate is None:
                candidate = self.admission.pending
            else:
                self.assertIs(candidate, self.admission.pending)
            self.step()
        self.assertTrue(success, self.admission.receipt)
        self.assertGreater(attempts, 1)

    def test_scene_revision_during_sliced_proof_restarts_same_random_shot(self):
        self.long_range()
        revision = [0]
        self.battle._destructibles = SimpleNamespace(_spatial_revision_1513=lambda: revision[0])
        self.assertFalse(self.fire())
        candidate = self.admission.pending
        self.assertGreater(candidate['proof']['cursor'], 0)
        def add_blocking_scene():
            self.on_probe = None
            self.world = [((-20., -10., 5.), (20., 50., 6.))]
            revision[0] += 1
        self.on_probe = add_blocking_scene
        self.step()
        self.assertFalse(self.fire())
        self.assertIs(candidate, self.admission.pending)
        self.assertIsNone(candidate['proof'])
        self.assertEqual('auto_world_changed', self.control.last_fire_failure)
        self.step()
        self.assertFalse(self.fire())
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assert_unspent()

    def test_moving_long_range_target_finishes_current_exact_proof(self):
        self.long_range()
        captured, original = [], self.battle._preinstall_player_projectile
        def capture(*args):
            captured.append(dict(self.admission.pending['proof']))
            return original(*args)
        self.battle._preinstall_player_projectile = capture
        candidate, probes = None, []
        with mock.patch(ADMISSION+'.random.gauss', return_value=1.) as gauss:
            for tick in range(12):
                self.pose(self.target, (float(tick+1), 0., 800.))
                self.step(.1)
                self.lay(target_velocity=(10., 0., 0.))
                self.world_queries[:] = []
                accepted = self.fire()
                probes.append(len(self.world_queries))
                self.assertLessEqual(probes[-1], MAX_PROOF_CHORDS)
                if accepted:
                    break
                self.assert_unspent()
                if candidate is None:
                    candidate = self.admission.pending
                else:
                    self.assertIs(candidate, self.admission.pending)
            self.assertTrue(accepted, self.admission.receipt)
            self.assertEqual(1, sum(call.args == (0., 1.) for call in gauss.call_args_list))
        self.assertLessEqual(tick, 4)
        self.assertTrue(any(count > WORLD_CHORDS_PER_ATTEMPT for count in probes))
        self.assertEqual('complete', self.admission.receipt['proof_mode'])
        self.assertEqual((10., 0., 0.), captured[0]['solution']['velocity'])
        self.assertEqual('vehicle', captured[0]['terminal_kind'])

    def test_scene_revision_churn_finishes_fresh_full_proof(self):
        self.long_range()
        revision = [0]
        self.battle._destructibles = SimpleNamespace(_spatial_revision_1513=lambda: revision[0])
        candidate = None
        for attempt in range(4):
            revision[0] += 1
            success = self.fire()
            if success:
                break
            if candidate is None:
                candidate = self.admission.pending
            else:
                self.assertIs(candidate, self.admission.pending)
            self.step()
        self.assertTrue(success, self.admission.receipt)
        self.assertEqual(2, attempt)
        self.assertEqual('complete', self.admission.receipt['proof_mode'])
        self.assertLessEqual(self.admission.receipt['world_chords'], MAX_PROOF_CHORDS)

    def test_completed_world_proof_expires_while_waiting_for_friend(self):
        friend = self.vehicle(43, (20., 0., 50.), 1)
        def enter_lane():
            self.on_probe = None
            self.pose(friend, (0., 0., 50.))
        self.on_probe = enter_lane
        self.assertFalse(self.fire())
        candidate = self.admission.pending
        self.assertTrue(candidate['proof']['done'])
        self.pose(friend, (20., 0., 50.))
        self.world = [((-2., 0., 40.), (2., 3., 41.))]
        self.step(.3)
        self.assertFalse(self.fire())
        self.assertIs(candidate, self.admission.pending)
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assert_unspent()

    def test_material_trace_uses_shell_calibre_and_retains_external_only_hit(self):
        module = 'gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix'
        track = SimpleNamespace(dist=2., matInfo=SimpleNamespace(
            armor=15., vehicleDamageFactor=0., kind=0), hitAngleCos=1., compName='chassis')
        hull = SimpleNamespace(dist=3.36, matInfo=SimpleNamespace(
            armor=20., vehicleDamageFactor=1., kind=0), hitAngleCos=1., compName='hull')
        roster = dict(target=self.target, body=self.target.matrix, chassis=None,
            velocity=(0., 0., 0.), bounds=((-2., 0., 91.), (2., 4., 100.)))
        proof = dict(roster=[roster], range_origin=(0., 2., 0.),
                     penetration_factor=1., target_queries=0)
        evaluator = self.runtime.attack_policy.evaluator
        frame = evaluator.snapshot(self.now)
        target = next(row for row in frame['targets'] if row['entity'] is self.target)
        with mock.patch(module, return_value=(track, hull)):
            for caliber, layer in ((90., None), (150., 'structural')):
                proof['shot'] = dict(shell=dict(kind='ARMOR_PIERCING', caliber=caliber),
                                    piercingPower=(300., 300.), maxDistance=400.,
                                    speed=1000., gravity=0.)
                scored = evaluator._armour_geometry(frame, dict(shot=proof['shot'], is_he=False),
                    target, (0., 2., 96.), (0., 0., 1.), .096)['penetration']
                self.assertEqual('failed' if caliber == 90. else 'passed', scored['armor'])
                hit = self.admission._contact(proof, (0., 2., 90.), (0., 2., 100.), .09, .1,
                                              centre=True)
                self.assertEqual(layer, (hit['contact'] or {}).get('layer'))
                self.assertAlmostEqual(.2, hit['fraction'])
                sampled = self.admission._contact(proof, (0., 2., 90.),
                                                   (0., 2., 100.), .09, .1)
                if caliber == 90.:
                    self.assertIsNone(sampled)
                else:
                    self.assertEqual('structural', sampled['contact']['layer'])

    def test_he_spaced_external_contact_requires_a_real_blast_surface(self):
        module = 'gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix'
        track = SimpleNamespace(dist=2., matInfo=SimpleNamespace(
            armor=400., vehicleDamageFactor=0., kind=0), hitAngleCos=1., compName='chassis')
        hull = SimpleNamespace(dist=3.36, matInfo=SimpleNamespace(
            armor=10., vehicleDamageFactor=1., kind=0), hitAngleCos=1., compName='hull')
        shot = dict(shell=dict(kind='HIGH_EXPLOSIVE', caliber=90., damage=(300., 0.)),
                    piercingPower=(30., 30.), speed=1000., gravity=0., maxDistance=400.)
        evaluator = self.runtime.attack_policy.evaluator
        frame = evaluator.snapshot(self.now)
        target = next(row for row in frame['targets'] if row['entity'] is self.target)
        shell = dict(shot=shot, is_he=True)
        with mock.patch(module, return_value=(track, hull)) as collide, \
                mock.patch.object(self.battle, '_projectile_he_blast_contact',
                    side_effect=(None, dict(nominal_armor=40., damage=65.))) as blast:
            geometry = evaluator._armour_geometry(frame, shell, target,
                (0., 2., 96.), (0., 0., 1.), .096)
            first = evaluator._he_damage(shell, target, geometry)
            second = evaluator._he_damage(shell, target, geometry)
        self.assertEqual(1, collide.call_count)
        self.assertIsNone(first['contact'])
        self.assertIsNone(first['expected_damage'])
        self.assertIs(second['contact'], True)
        self.assertEqual(65., second['expected_damage'])
        self.assertEqual(2, blast.call_count)

    def test_he_fallback_requires_blast_surface_including_valid_zero_damage(self):
        self.set_he(piercing=1.)
        with mock.patch.object(self.battle, '_projectile_he_blast_contact', return_value=None):
            self.lay(mode='he_fallback')
            self.assertIsNone(self.candidate['contact'])
            self.assertFalse(self.fire())
            self.assert_unspent()
        with mock.patch.object(self.battle, '_projectile_he_blast_contact',
                               return_value=dict(nominal_armor=40., damage=0.)) as blast:
            self.lay(mode='he_fallback')
            self.assertIs(self.candidate['contact'], True)
            self.assertEqual(0., self.candidate['expected_damage'])
            self.step()
            self.assertTrue(self.fire(), self.admission.receipt)
            self.assertGreater(blast.call_count, 1)

    def _hydraulic(self):
        desc = self.entity.typeDescriptor
        desc.hasSiegeMode = True
        self.entity.siegeState = 2
        desc.gun.pitchLimits = HydraulicReachTests().descriptor().gun.pitchLimits
        desc.type.hullAimingParams = dict(pitch=dict(isAvailable=True, isEnabled=True,
            wheelsCorrectionAngles=dict(pitchMin=math.radians(-11.), pitchMax=math.radians(11.)),
            wheelsCorrectionSpeed=.1, wheelCorrectionCenterZ=0.))
        self.battle._local_siege_flat_body_matrix = Pose()
        self.battle._local_siege_aim_matrix = Pose()
        self.battle._local_siege_aim_pitch = 0.
        return desc

    def test_hydraulic_target_waits_for_real_local_actuator_before_fire(self):
        self._hydraulic()
        self.pose(self.target, (0., 20., 100.))
        solution = self.lay(move_barrel=False)
        self.assertFalse(solution['reachable'])
        self.assertFalse(self.fire())
        self.assert_unspent()
        echoes = []
        self.battle._binding = SimpleNamespace(update_vehicle_aim=lambda *args: echoes.append(args))
        # Use the actual native mailbox and actual hydraulic update. A test
        # does not manufacture a reachable barrel from theoretical travel.
        self.assertTrue(self.battle._sender.send_avatar_input(self.entity.id, 'track_world',
            dict(point=solution['point'])))
        self.assertTrue(echoes)
        self.assertTrue(self.battle._update_local_hull_aiming(self.entity, 2.))
        correction = self.battle._local_siege_aim_pitch
        self.assertLess(correction, 0.)
        self.body.setRotateYPR((0., correction, 0.))
        self.step()
        self.assertTrue(self.lay()['reachable'])
        self.assertTrue(self.fire(), self.admission.receipt)

    def test_disabled_hydraulics_cannot_publish_extended_reach(self):
        self._hydraulic()
        geometry = NativeAimGeometry(self.battle)
        self.entity.siegeState = 0
        self.assertIsNone(geometry._own()['hydraulic'])
        self.entity.siegeState = 2
        self.assertIsNotNone(geometry._own()['hydraulic'])

    def test_contact_hook_preserves_actual_sat_axis(self):
        receipts = []
        self.control.drive_contact = lambda *args, **kwargs: receipts.append((args, kwargs))
        own = dict(id=-1, kind='player', network_id=1, x=0., y=0., z=0.,
                   yaw=0., pitch=0., roll=0., shape=(1., 2., 0., 2.))
        peer = dict(id=42, kind='bot', network_id=42, x=1.5, y=0., z=1.,
                    yaw=0., pitch=0., roll=0., shape=(1., 2., 0., 2.), _vehicle=self.target)
        self.battle._report_player_planar_contacts(own, [peer], 0., .1, self.now)
        self.assertEqual(1, len(receipts))
        witness = receipts[0][1]['contact']
        self.assertEqual((-1., -0.), witness['normal'])
        self.assertEqual('copied_planar_contact', witness['source'])
        peer['x'] = 10.
        self.battle._report_player_planar_contacts(own, [peer], 0., .1, self.now)
        self.assertEqual(1, len(receipts))


class HydraulicReachTests(unittest.TestCase):
    """Preserved helper contracts now belong to neutral native_aim."""
    def descriptor(self):
        desc = f._Descriptor()
        minimum, maximum = math.radians(-4.), math.radians(2.)
        desc.gun.pitchLimits = dict(absolute=(minimum, maximum),
            minPitch=((0., minimum), (2.*math.pi, minimum)),
            maxPitch=((0., maximum), (2.*math.pi, maximum)))
        return desc

    def test_extended_travel_is_laying_not_a_false_native_gun_envelope(self):
        desc = self.descriptor()
        angle = math.radians(-10.)
        direction = (0., -math.sin(angle), math.cos(angle))
        self.assertFalse(mechanical_reach(desc, direction, (0., 0., 0.))['reachable'])
        config = dict(body=(0., 0., 0.), minimum=math.radians(-11.),
                      maximum=math.radians(11.), speed=.1)
        planned = mechanical_reach(desc, direction, (0., 0., 0.), config)
        self.assertTrue(planned['reachable'])
        self.assertTrue(planned['needs_hydraulic'])
        self.assertAlmostEqual(math.radians(-6.), planned['hydraulic_pitch'], places=5)
        laid = mechanical_reach(desc, direction, (0., planned['hydraulic_pitch'], 0.))
        self.assertTrue(laid['reachable'])

    def test_manual_point_command_waits_for_actual_hydraulic_laying(self):
        import test_player_manual_aim as manual_tests
        from player_native_fixtures import Matrix
        fixture = manual_tests.ManualAimOwnershipTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        own = fixture.entities[1]
        desc = own.typeDescriptor
        desc.hasSiegeMode = True
        own.siegeState = 2
        desc.gun.pitchLimits = self.descriptor().gun.pitchLimits
        desc.type.hullAimingParams = dict(pitch=dict(isAvailable=True, isEnabled=True,
            wheelsCorrectionAngles=dict(pitchMin=math.radians(-11.), pitchMax=math.radians(11.)),
            wheelsCorrectionSpeed=.1, wheelCorrectionCenterZ=0.))
        fixture.owner._local_siege_flat_body_matrix = Matrix(fixture.body)
        response = fixture.submit(args=dict(position=(0., 20., 100.)), identity='hydraulic')
        self.assertEqual('accepted', response['status'])
        self.assertTrue(fixture.aim.operation['solution']['needs_hydraulic'])
        self.assertEqual('aim_not_aligned', fixture.aim.fire_preflight())
        fixture.body.pitch = -.15
        fixture.align()
        fixture.observe(.1)
        self.assertEqual('completed', fixture.receipt('hydraulic')['status'])
        self.assertIsNone(fixture.aim.fire_preflight())


if __name__ == '__main__':
    unittest.main()
