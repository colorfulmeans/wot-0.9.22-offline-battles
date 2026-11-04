"""Real foreground trigger/physical projectile regression at the native boundary.

Only native Matrix, BSP and hit-tester data are supplied by geometric test
adapters. Aiming, admission, scatter, gun transactions and projectile installs
are production code; no decisive gate is replaced with an always-true mock.
"""
import math
from types import SimpleNamespace
import unittest
from unittest import mock

import test_port_0922_battle_runtime as f
import test_port_0922_player_burst as burst_tests
from gui.mods.offline_lan_0922 import ballistics, shot_geometry
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.aiming import Aiming, mechanical_reach
from gui.mods.offline_lan_0922.player_control.weapon import Weapon
from gui.mods.offline_lan_0922.player_control.fire_admission import (
    WORLD_CHORDS_PER_ATTEMPT, MAX_PROOF_CHORDS)


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


class AutomaticFireAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = burst_tests.PlayerBurstTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.battle = battle = self.fixture.battle
        battle.client.team = 1
        battle._runtime.math.Matrix = Pose
        battle._runtime.math.Vector3 = f._Vector
        self.body = Pose()
        battle._local_stabilised_pose = lambda: self.body
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
        self.target = self.vehicle(42, (0., 0., 100.), team=2)
        self.control = PlayerControl(battle, ('fire',), notify=lambda text: None)
        battle._player_control = self.control
        self.control.active = True
        self.control.live = lambda: True
        self.control.record = lambda *args, **kwargs: None
        self.control.target_engine = self.target.id
        self.control.aiming = Aiming(battle)
        self.control.weapon = Weapon(battle)
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
        self.battle._runtime.bigworld.entities[identity] = vehicle
        self.battle._records['test:%s' % identity] = dict(engine_id=identity, ready=True,
            state=dict(team=team, health=500, alive=True), spot_visible=team == 2,
            kind='bot', network_id=identity)
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

    def lay(self, move_barrel=True):
        planner, gun = self.control.aiming, self.battle._gun_state
        sample = shot_geometry.ordered_vehicle_aim_samples(self.target.typeDescriptor)[0]
        point = shot_geometry.vehicle_aim_point(sample, dict(position=tuple(self.target.position)))
        pitch, unused_flight = ballistics.ballistic_solutions(
            self.origin, point, gun.shots[0].speed, gun.shots[0].gravity)[0]
        yaw = math.atan2(point[0]-self.origin[0], point[2]-self.origin[2])
        laid = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch), math.cos(yaw)*math.cos(pitch))
        if move_barrel:
            self.direction = laid
        for unused in range(80):
            planner.begin([self.target], self.now)
            status, result = planner.ordered(self.target, 0, None, self.now,
                lambda a, b: self.battle._tactical_ray_clear(a, b), physical=True)
            if status in ('ready', 'laying'):
                self.control.weapon.aim_solution(self.target.id, result, self.now)
                return result
            self.fixture.now += .1
        self.fail('real ordered planner failed to finish: %s' % status)

    def step(self, seconds=.1):
        self.fixture.now += seconds
        self.control.aiming.begin([self.target], self.now)

    def fire(self):
        return self.control.trigger(self.control.weapon, self.now)

    def test_every_automatic_round_has_fresh_proof_and_one_ammo_debit(self):
        before = sum(self.battle._gun_state.ammo)
        self.world_queries[:] = []
        self.assertTrue(self.fire(), self.control.fire_admission.receipt)
        self.assertTrue(self.world_queries)
        for unused in range(2):
            self.step()
            self.world_queries[:] = []
            self.assertTrue(self.battle._advance_local_player_burst(), self.control.fire_admission.receipt)
            self.assertTrue(self.world_queries)
        self.assertEqual(before-3, sum(self.battle._gun_state.ammo))
        self.assertEqual(3, len(self.battle._projectile_meta))
        self.assertIsNone(self.battle._local_player_burst)

    def test_ally_crosses_between_tail_rounds_waits_then_resumes_same_burst(self):
        self.assertTrue(self.fire())
        burst = self.battle._local_player_burst
        ammo = list(self.battle._gun_state.ammo)
        friend = self.vehicle(43, (0., 0., 50.), 1)
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        candidate = self.control.fire_admission.pending
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assertIs(burst, self.battle._local_player_burst)
        self.assertEqual(ammo, self.battle._gun_state.ammo)
        self.pose(friend, (20., 0., 50.))
        self.step()
        self.assertTrue(self.battle._advance_local_player_burst(), self.control.fire_admission.receipt)
        self.assertIsNone(self.control.fire_admission.pending)
        self.assertIsNotNone(candidate)
        self.assertEqual(2, burst['committed'])

    def test_target_motion_or_hidden_target_never_fires_a_stale_tail(self):
        self.assertTrue(self.fire())
        ammo = list(self.battle._gun_state.ammo)
        self.pose(self.target, (10., 0., 100.))
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertEqual(ammo, self.battle._gun_state.ammo)
        self.assertIsNotNone(self.battle._local_player_burst)
        self.battle._records['test:42']['spot_visible'] = False
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertIsNone(self.battle._local_player_burst)
        self.assertEqual(1, len(self.battle._projectile_meta))

    def test_tail_obeys_new_yield_and_artillery_deployment_orders(self):
        self.assertTrue(self.fire())
        burst = self.battle._local_player_burst
        for order, reason in ((dict(suppress_fire=True), 'auto_order_holds_fire'),
                (dict(fire_allowed=False), 'auto_order_holds_fire'),
                (dict(artillery=dict(phase='relocating')), 'auto_artillery_repositioning')):
            self.control.last_order = order
            self.step()
            self.assertFalse(self.battle._advance_local_player_burst())
            self.assertIs(burst, self.battle._local_player_burst)
            self.assertEqual(reason, self.control.last_fire_failure)
            self.assertEqual(19, self.battle._gun_state.ammo[0])
        self.control.last_order = {}
        self.step()
        self.assertTrue(self.battle._advance_local_player_burst())

    def test_failed_mission_terminates_tail_instead_of_waiting_forever(self):
        self.assertTrue(self.fire())
        self.control.last_order = dict(mission=dict(status='failed', reason='route_unreachable'))
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertIsNone(self.battle._local_player_burst)
        self.assertIsNone(self.control.fire_admission.pending)
        self.assertEqual('auto_mission_failed', self.control.last_fire_failure)
        self.assertEqual('rejected', self.control.fire_admission.receipt['status'])
        self.assertEqual(19, self.battle._gun_state.ammo[0])
        self.assertEqual(1, len(self.battle._projectile_meta))

    def test_mission_cancelled_during_final_preinstall_retires_the_tail(self):
        self.assertTrue(self.fire())
        original = self.battle._preinstall_player_projectile
        def cancel_after_install(*args):
            result = original(*args)
            self.control.last_order = dict(mission=dict(status='cancelled'))
            return result
        self.battle._preinstall_player_projectile = cancel_after_install
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertIsNone(self.battle._local_player_burst)
        self.assertIsNone(self.control.fire_admission.pending)
        self.assertEqual('auto_mission_cancelled', self.control.last_fire_failure)
        self.assertEqual('rejected', self.control.fire_admission.receipt['status'])
        self.assertEqual(19, self.battle._gun_state.ammo[0])
        self.assertEqual(1, len(self.battle._projectile_meta))

    def test_exact_scattered_lane_cannot_reroll_until_friend_moves(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        friend = self.vehicle(43, (-5., 0., 50.), 1)
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.) as gauss, \
                mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
            candidate = self.control.fire_admission.pending
            direction = candidate['proof']['direction']
            velocity = candidate['proof']['velocity']
            self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
            for unused in range(4):
                self.step()
                self.assertFalse(self.fire())
                self.assertIs(candidate, self.control.fire_admission.pending)
            self.assertEqual(1, sum(call.args == (0., 1.) for call in gauss.call_args_list))
            self.assertFalse(self.battle._projectile_meta)
            self.assertEqual(20, self.battle._gun_state.ammo[0])
            self.pose(friend, (-20., 0., 50.))
            self.step()
            self.assertTrue(self.fire(), self.control.fire_admission.receipt)
        launch = next(iter(self.battle._projectile_meta.values()))
        self.assertEqual(velocity, tuple(launch['velocity']))
        self.assertTrue(all(abs(velocity[i]-direction[i]*800.) < .000001 for i in range(3)))
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_scattered_near_world_contact_is_not_hidden_by_clear_centre(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self.world = [((-2.5, 0., 19.), (-1.5, 3., 21.))]
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.), \
                mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
            candidate = self.control.fire_admission.pending
            self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
            self.step()
            self.assertFalse(self.fire())
            self.assertIs(candidate, self.control.fire_admission.pending)
            self.world[:] = []
            self.step()
            self.assertTrue(self.fire())
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_scattered_miss_proves_allies_beyond_the_target_plane(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        self.vehicle(43, (-15., 0., 150.), 1)
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.), \
                mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.control.fire_admission.pending['proof']
        self.assertTrue(proof['done'])
        self.assertNotIn('terminal_impact', proof)
        self.assertGreater(proof['path'][-1][2], 150.)
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        self.assertFalse(self.battle._projectile_meta)

    def test_real_native_target_contact_stops_the_proof_before_rear_ally(self):
        self.vehicle(43, (0., 0., 150.), 1)
        seen = []
        original = self.battle._preinstall_player_projectile
        def capture_proof(*args):
            seen.append(dict(self.control.fire_admission.pending['proof']))
            return original(*args)
        self.battle._preinstall_player_projectile = capture_proof
        self.assertTrue(self.fire(), self.control.fire_admission.receipt)
        self.assertEqual('vehicle', seen[0]['terminal_kind'])
        self.assertLess(seen[0]['terminal_impact'][2], 100.)
        self.assertGreater(seen[0]['target_queries'], 0)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_he_scattered_ground_impact_beyond_target_plane_checks_splash(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        shot = self.battle._gun_state.shots[0]
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        self.battle.client.effective_params['gun']['shots'][0]['source_shot']['shell'].update(
            kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        self.world = [((-18., -5., 149.), (-12., 5., 150.))]
        self.vehicle(43, (-20., 0., 149.), 1)
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.), \
                mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.control.fire_admission.pending['proof']
        self.assertEqual('world', proof['terminal_kind'])
        self.assertGreater(proof['terminal_impact'][2], 100.)
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_he_first_visible_enemy_not_selected_target_defines_splash(self):
        self.battle._config['perfect_accuracy'] = False
        self.battle._avatar.gunRotator._VehicleGunRotator__dispersionAngles[0] = .2
        shot = self.battle._gun_state.shots[0]
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        self.battle.client.effective_params['gun']['shots'][0]['source_shot']['shell'].update(
            kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        intervening = self.vehicle(44, (-5., 0., 50.), 2)
        self.vehicle(43, (-10., 0., 48.), 1)
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.), \
                mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.uniform', return_value=.25):
            self.assertFalse(self.fire())
        proof = self.control.fire_admission.pending['proof']
        self.assertEqual(intervening.id, proof['terminal_vehicle'])
        self.assertNotEqual(self.control.target_engine, proof['terminal_vehicle'])
        self.assertEqual('vehicle', proof['terminal_kind'])
        self.assertLess(proof['terminal_impact'][2], 50.)
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_oversized_collision_roster_cannot_silently_skip_native_actors(self):
        for identity in range(50, 80):
            self.vehicle(identity, (30., 0., 100.), 2)
        self.assertFalse(self.fire())
        self.assertEqual('auto_collision_roster_limit', self.control.last_fire_failure)
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_he_endpoint_splash_blocks_a_friend_outside_the_shell_lane(self):
        self.vehicle(43, (5., 0., 100.), 1)
        shot = self.battle._gun_state.shots[0]
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        source = self.battle.client.effective_params['gun']['shots'][0]['source_shot']['shell']
        source.update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_he_splash_is_checked_again_for_the_next_burst_round(self):
        shot = self.battle._gun_state.shots[0]
        shot.shell.kind, shot.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        source = self.battle.client.effective_params['gun']['shots'][0]['source_shot']['shell']
        source.update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        self.assertTrue(self.fire())
        self.vehicle(43, (5., 0., 100.), 1)
        self.step()
        self.assertFalse(self.battle._advance_local_player_burst())
        self.assertEqual('auto_friendly_splash', self.control.last_fire_failure)
        self.assertEqual(19, self.battle._gun_state.ammo[0])
        self.assertEqual(1, len(self.battle._projectile_meta))

    def test_fresh_dynamic_check_after_world_callback_prevents_launch(self):
        friend = self.vehicle(43, (20., 0., 50.), 1)
        def enter_lane():
            self.on_probe = None
            self.pose(friend, (0., 0., 50.))
        self.on_probe = enter_lane
        self.assertFalse(self.fire())
        self.assertEqual('auto_friendly_lane', self.control.last_fire_failure)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_preinstall_reentry_cannot_send_a_different_native_pose(self):
        original = self.battle._preinstall_player_projectile
        original_direction = self.direction
        def move_after_install(*args):
            result = original(*args)
            self.direction = (.2, 0., math.sqrt(.96))
            return result
        self.battle._preinstall_player_projectile = move_after_install
        self.assertFalse(self.fire())
        candidate = self.control.fire_admission.pending
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        self.battle._preinstall_player_projectile = original
        self.direction = original_direction
        self.step()
        self.assertTrue(self.fire(), self.control.fire_admission.receipt)
        self.assertIsNotNone(candidate)
        self.assertEqual(19, self.battle._gun_state.ammo[0])
        self.assertEqual(1, len(self.battle._projectile_meta))

    def test_last_plate_query_revocation_is_fenced_before_the_wire_send(self):
        original = self.battle._preinstall_player_projectile
        tester = self.target.typeDescriptor.hull.hitTester
        def stop():
            tester.on_hit = None
            self.control.stop('native_plate_callback')
        def revoke_on_final_plate_query(*args):
            result = original(*args)
            tester.on_hit = stop
            return result
        self.battle._preinstall_player_projectile = revoke_on_final_plate_query
        self.assertFalse(self.fire())
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        self.assertFalse(self.control.active)

    def test_preinstall_canonical_trajectory_cannot_replace_the_proven_velocity(self):
        original = self.battle._preinstall_player_projectile
        def replace_velocity(*args):
            result = original(*args)
            self.battle._projectile_meta[result]['velocity'] = (800., 0., 0.)
            return result
        self.battle._preinstall_player_projectile = replace_velocity
        self.assertFalse(self.fire())
        self.assertEqual('auto_launch_changed', self.control.last_fire_failure)
        self.assertFalse(self.battle._projectile_meta)
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        self.assertEqual('pending', self.control.fire_admission.receipt['status'])
        self.assertEqual('auto_launch_changed', self.control.fire_admission.receipt['reason'])

    def test_native_target_articulation_change_invalidates_terminal_proof(self):
        original = self.battle._preinstall_player_projectile
        def turn_turret_after_install(*args):
            result = original(*args)
            self.target.appearance.turretMatrix.setRotateY(.5)
            return result
        self.battle._preinstall_player_projectile = turn_turret_after_install
        self.assertFalse(self.fire())
        self.assertEqual('auto_target_changed', self.control.last_fire_failure)
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        self.assertFalse(self.battle._projectile_meta)
        self.assertIsNone(self.control.fire_admission.pending['proof'])

    def long_range(self):
        for shot in self.battle._gun_state.shots:
            shot.speed, shot.maxDistance = 100., 5000.
        for row in self.battle.client.effective_params['gun']['shots']:
            row['source_shot'].update(speed=100., maxDistance=5000.)
        self.pose(self.target, (0., 0., 800.))
        self.control.aiming.reset()
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
            self.assertEqual(20, self.battle._gun_state.ammo[0])
            self.assertFalse(self.battle._projectile_meta)
            if candidate is None:
                candidate = self.control.fire_admission.pending
            else:
                self.assertIs(candidate, self.control.fire_admission.pending)
            self.step()
        self.assertTrue(success, self.control.fire_admission.receipt)
        self.assertGreater(attempts, 1)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_continuously_moving_long_range_target_finishes_exact_proof(self):
        self.long_range()
        candidate, launches, attempts, totals = None, [], 0, []
        original = self.battle._preinstall_player_projectile
        def capture_proof(*args):
            launches.append(dict(self.control.fire_admission.pending['proof']))
            return original(*args)
        self.battle._preinstall_player_projectile = capture_proof
        with mock.patch('gui.mods.offline_lan_0922.player_control.fire_admission.random.gauss', return_value=1.) as gauss:
            for tick in range(60):
                # This is an actually changing native target pose and barrel,
                # not a constant-ray substitute for the tracking workload.
                self.pose(self.target, (float(tick+1), 0., 800.))
                self.step()
                planner, gun = self.control.aiming, self.battle._gun_state
                sample = shot_geometry.ordered_vehicle_aim_samples(self.target.typeDescriptor)[0]
                point = shot_geometry.vehicle_aim_point(sample, planner._pose(self.target))
                velocity = planner.observations[self.target.id]['velocity']
                intercept, pitch, unused = ballistics.ballistic_intercept(
                    self.origin, point, velocity, gun.shots[0].speed, gun.shots[0].gravity)
                yaw = math.atan2(intercept[0]-self.origin[0], intercept[2]-self.origin[2])
                self.direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch),
                                  math.cos(yaw)*math.cos(pitch))
                status, solution = planner.ordered(self.target, 0, None, self.now,
                    self.battle._tactical_ray_clear, physical=True)
                if status != 'ready':
                    continue
                self.control.weapon.aim_solution(self.target.id, solution, self.now)
                self.world_queries[:] = []
                success = self.fire()
                attempts += 1
                totals.append(len(self.world_queries))
                self.assertLessEqual(len(self.world_queries), MAX_PROOF_CHORDS)
                if success:
                    break
                if candidate is None:
                    candidate = self.control.fire_admission.pending
                else:
                    self.assertIs(candidate, self.control.fire_admission.pending)
                self.assertEqual(20, self.battle._gun_state.ammo[0])
            self.assertTrue(launches, self.control.fire_admission.receipt)
            self.assertEqual(1, sum(call.args == (0., 1.) for call in gauss.call_args_list))
        self.assertLessEqual(attempts, 4)
        self.assertTrue(any(total > WORLD_CHORDS_PER_ATTEMPT for total in totals))
        self.assertEqual('complete', launches[0]['mode'])
        self.assertAlmostEqual(10., launches[0]['target_velocity'][0])
        self.assertEqual('vehicle', launches[0]['terminal_kind'])
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_scene_revision_during_sliced_proof_restarts_same_random_shot(self):
        self.long_range()
        revision = [0]
        self.battle._destructibles = SimpleNamespace(_spatial_revision_1513=lambda: revision[0])
        self.assertFalse(self.fire())
        candidate = self.control.fire_admission.pending
        self.assertGreater(candidate['proof']['cursor'], 0)
        def add_blocking_scene():
            self.on_probe = None
            self.world = [((-20., -10., 5.), (20., 50., 6.))]
            revision[0] += 1
        self.on_probe = add_blocking_scene
        self.step()
        self.assertFalse(self.fire())
        self.assertIs(candidate, self.control.fire_admission.pending)
        self.assertIsNone(candidate['proof'])
        self.assertEqual('auto_world_changed', self.control.last_fire_failure)
        self.step()
        self.assertFalse(self.fire())
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_scene_revision_churn_between_slices_finishes_fresh_full_proof(self):
        self.long_range()
        revision = [0]
        self.battle._destructibles = SimpleNamespace(_spatial_revision_1513=lambda: revision[0])
        candidate = None
        for attempt in range(3):
            revision[0] += 1
            success = self.fire()
            if success:
                break
            if candidate is None:
                candidate = self.control.fire_admission.pending
            else:
                self.assertIs(candidate, self.control.fire_admission.pending)
            self.step()
        self.assertTrue(success, self.control.fire_admission.receipt)
        self.assertEqual(2, attempt)
        self.assertEqual('complete', self.control.fire_admission.receipt['proof_mode'])
        self.assertLessEqual(self.control.fire_admission.receipt['world_chords'], MAX_PROOF_CHORDS)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_completed_world_proof_expires_while_waiting_for_a_friend(self):
        friend = self.vehicle(43, (20., 0., 50.), 1)
        def enter_lane():
            self.on_probe = None
            self.pose(friend, (0., 0., 50.))
        self.on_probe = enter_lane
        self.assertFalse(self.fire())
        candidate = self.control.fire_admission.pending
        self.assertTrue(candidate['proof']['done'])
        self.pose(friend, (20., 0., 50.))
        self.world = [((-2., 0., 40.), (2., 3., 41.))]
        self.step(.3)
        self.assertFalse(self.fire())
        self.assertIs(candidate, self.control.fire_admission.pending)
        self.assertEqual('auto_world_blocked', self.control.last_fire_failure)
        self.assertEqual(20, self.battle._gun_state.ammo[0])

    def test_hydraulic_target_reaches_local_actuator_before_any_fire(self):
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
        self.pose(self.target, (0., 20., 100.))
        self.control.aiming.reset()
        solution = self.lay(move_barrel=False)
        self.assertTrue(solution['needs_hydraulic'])
        self.assertTrue(solution['source_verified'])
        self.assertFalse(self.control.weapon.ready(self.now+10., 1.))
        self.assertFalse(self.fire())
        self.assertEqual(20, self.battle._gun_state.ammo[0])
        echoes = []
        self.battle._binding = SimpleNamespace(update_vehicle_aim=lambda *args: echoes.append(args))
        # This is the real native mailbox track-world boundary used by the
        # installed point-source functor, not a write to private gun angles.
        self.assertTrue(self.battle._sender.send_avatar_input(self.entity.id, 'track_world',
            dict(point=self.control.weapon.shot_point())))
        self.assertTrue(echoes)
        self.assertTrue(self.battle._update_local_hull_aiming(self.entity, 2.))
        correction = self.battle._local_siege_aim_pitch
        self.assertLess(correction, 0.)
        self.body.setRotateYPR((0., correction, 0.))
        self.step()
        solution = self.lay()
        self.assertFalse(solution.get('needs_hydraulic', False))
        self.assertTrue(self.fire(), self.control.fire_admission.receipt)
        self.assertEqual(19, self.battle._gun_state.ammo[0])

    def test_disabled_hydraulics_does_not_publish_an_extended_aim_source(self):
        desc = self.entity.typeDescriptor
        desc.hasSiegeMode = True
        desc.gun.pitchLimits = HydraulicReachTests().descriptor().gun.pitchLimits
        desc.type.hullAimingParams = dict(pitch=dict(isAvailable=True, isEnabled=True,
            wheelsCorrectionAngles=dict(pitchMin=math.radians(-11.), pitchMax=math.radians(11.)),
            wheelsCorrectionSpeed=.1, wheelCorrectionCenterZ=0.))
        self.battle._local_siege_flat_body_matrix = Pose()
        self.entity.siegeState = 0
        own = self.control.aiming._own()
        self.assertIsNone(own['hydraulic'])
        self.entity.siegeState = 2
        own = self.control.aiming._own()
        self.assertIsNotNone(own['hydraulic'])

    def test_contact_hook_carries_real_sat_axis_not_centre_direction(self):
        receipts = []
        self.control.drive_contact = lambda *args, **kwargs: receipts.append((args, kwargs))
        own = dict(id=-1, kind='player', network_id=1, x=0., y=0., z=0.,
                   yaw=0., pitch=0., roll=0., shape=(1., 2., 0., 2.))
        peer = dict(id=42, kind='bot', network_id=42, x=1.5, y=0., z=1.,
                    yaw=0., pitch=0., roll=0., shape=(1., 2., 0., 2.),
                    _vehicle=self.target)
        self.battle._report_player_planar_contacts(own, [peer], 0., .1, self.now)
        self.assertEqual(1, len(receipts))
        witness = receipts[0][1]['contact']
        self.assertEqual((-1., -0.), witness['normal'])
        self.assertEqual('copied_planar_contact', witness['source'])
        self.assertEqual(42, witness['peer'])
        peer['x'] = 10.
        self.battle._report_player_planar_contacts(own, [peer], 0., .1, self.now)
        self.assertEqual(1, len(receipts))


class HydraulicReachTests(unittest.TestCase):
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

    def test_manual_point_command_also_waits_for_actual_hydraulic_laying(self):
        import test_player_manual_aim as manual_tests
        from test_player_weapon_migration import Matrix
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


class EngagementBurstLockTests(unittest.TestCase):
    def test_burst_updates_laying_but_never_changes_target_or_shell(self):
        import test_player_direct_engagement as engagement_tests
        fixture = engagement_tests.DirectEngagementTests()
        fixture.setUp()
        state, control = fixture.state, fixture.control
        stage = (0, engagement_tests.PENETRATION_FACTOR_65)
        state.adopt(21, stage)
        state.sample = 0
        control.owner._local_player_burst = dict(committed=1)
        fixture.verdicts[(21, 0, 0)] = 'armor'
        fixture.verdicts[(22, 0, 0)] = 'ready'
        for now in (0., 1., 2.):
            state.update(control, [fixture.first, fixture.second], now)
        self.assertEqual((21, stage), (state.target, state.stage))
        self.assertEqual([], fixture.calls)
        fixture.verdicts[(21, 0, 0)] = 'laying'
        state.update(control, [fixture.first, fixture.second], 3.)
        self.assertEqual((21, stage), (state.target, state.stage))
        state.update(control, [fixture.second], 4.)
        self.assertEqual((21, stage), (state.target, state.stage))
        self.assertEqual([], fixture.calls)


if __name__ == '__main__':
    unittest.main()
