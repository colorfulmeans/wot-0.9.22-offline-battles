"""Player-owned weapon migration regressions, with native boundaries explicit."""
import ast
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import ballistics, shot_geometry
from gui.mods.offline_lan_0922.player_control.ammunition import (
    Ammunition, mounted_shell_roles, mounted_shells, policy_from_gun)
from gui.mods.offline_lan_0922.player_control.aiming import Aiming, mechanical_reach
from gui.mods.offline_lan_0922.player_control.weapon import (
    Weapon, artillery_path, barrel_aligned, hull_traverse_error)


class AmmoMigrationTests(unittest.TestCase):
    def policy(self, clip=1, kinds=None):
        kinds = kinds or ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR', 'HIGH_EXPLOSIVE')
        result = Ammunition([dict(index=i, kind=kind) for i, kind in enumerate(kinds)],
                            0, 0, clip)
        result.protected = False
        self.inventory = [100] * len(kinds)
        result.choose(self.inventory)
        return result

    def launch(self, policy, identity, shell=0, target=42, position=(0., 0., 0.),
               group=None, count=1):
        policy.launch(identity, shell, target, 0., position=position, group=group, count=count)

    def resolve(self, policy, identity, damage=0., hit=True, known=True, penetrated=False):
        if known and hit:
            policy.hit(dict(projectile_id=identity, damage=damage,
                            shot_result=2 if penetrated else 1))
        policy.terminal(dict(projectile_id=identity, hit_vehicle=hit), 0.)
        return policy.settle(self.inventory, 0. if known else 2.1)

    def test_apcr_last_round_cannot_overwrite_latched_he(self):
        p = self.policy(clip=4)
        selected = []
        for index, shell in enumerate((0, 0, 0, 0, 1, 1, 1, 1)):
            self.launch(p, str(index), shell)
            self.resolve(p, str(index))
            selected.append(p.choose(self.inventory))
        self.assertEqual([0, 1, 1, 1, 1, 2, 2, 2], selected)
        self.assertEqual(2, p.desired)

    def test_policy_sequences_match_independent_bot_oracle_without_runtime_dependency(self):
        from gui.mods.offline_lan_0922.ammo_policy import ShotPolicy
        cases = (
            (4, [(0, 0)]*4 + [(1, 0)]*4 + [(2, 50)]*4),
            (1, [(0, 0), (0, 10), (0, 0), (0, 0), (1, 0), (1, 0), (2, 0), (2, 0)]),
            (3, [(0, 0), (0, 10), (0, 0), (0, 0), (0, 10)]),
        )
        for clip, sequence in cases:
            p = self.policy(clip)
            bot = ShotPolicy(dict(clip_size=clip, class_tag='mediumTank',
                                  shells=[dict(row, name='') for row in p.shells]))
            state = dict(ammo_remaining=self.inventory)
            bot.choose(state)
            for index, (shell, damage) in enumerate(sequence):
                self.launch(p, str(index), shell)
                self.resolve(p, str(index), damage=damage)
                bot.launch(index, shell, index, 1, dict(x=0, z=0), 42)
                bot.resolve(index, True, damage, False)
                self.assertEqual(bot.choose(state), p.choose(self.inventory),
                                 (clip, index, shell, damage))

    def test_zero_damage_burst_waits_for_all_rounds_then_counts_one_trigger(self):
        p = self.policy(clip=12)
        self.launch(p, 'a', group=7, count=3)
        self.resolve(p, 'a')
        self.assertEqual(0, p.desired)
        self.launch(p, 'b', group=7, count=3)
        self.resolve(p, 'b', hit=False)
        self.assertEqual(0, p.desired)
        self.launch(p, 'c', group=7, count=3)
        self.resolve(p, 'c', hit=False)
        self.assertEqual(1, p.desired)
        self.assertTrue(p.idle)

    def test_one_positive_burst_round_prevents_upgrade(self):
        p = self.policy(clip=12)
        for index, damage in enumerate((0, 1, 0)):
            self.launch(p, str(index), group=7, count=3)
            self.resolve(p, str(index), damage)
        self.assertEqual(0, p.desired)
        self.assertEqual(0, p.failures)

    def test_cancelled_tail_closes_at_actual_committed_count(self):
        p = self.policy(clip=12)
        self.launch(p, 'a', group=7, count=3)
        self.resolve(p, 'a')
        self.assertFalse(p.idle)
        p.close_group(7, 1)
        self.assertEqual(1, p.desired)
        self.assertTrue(p.idle)
        p.close_group(7, 1)
        self.assertEqual(1, p.desired)

    def test_cancelled_group_can_close_before_its_terminal_feedback(self):
        p = self.policy(clip=12)
        self.launch(p, 'a', group=7, count=3)
        self.launch(p, 'b', group=7, count=3)
        p.close_group(7, 2)
        self.resolve(p, 'b')
        self.assertFalse(p.idle)
        self.resolve(p, 'a')
        self.assertEqual(1, p.desired)
        self.assertTrue(p.idle)

    def test_first_round_of_next_group_closes_prior_admitted_tail(self):
        p = self.policy(clip=12)
        self.launch(p, 'a', group=7, count=3)
        self.resolve(p, 'a')
        self.launch(p, 'b', group=8, count=1)
        self.assertEqual(1, p.desired)
        self.resolve(p, 'b', damage=100)
        self.assertTrue(p.idle)
        self.assertEqual(1, p.desired)

    def test_failure_streak_does_not_cross_clip_boundary(self):
        p = self.policy(clip=3)
        for index, damage in enumerate((0, 100, 0, 0)):
            self.launch(p, str(index))
            self.resolve(p, str(index), damage)
        self.assertEqual(0, p.desired)
        self.assertEqual(1, p.failures)
        self.assertEqual(2, p.magazine)

    def test_takeover_mid_clip_keeps_native_magazine_boundaries(self):
        p = self.policy(clip=4)
        # Two manual rounds were spent before control was enabled. The first
        # accepted automatic round leaves one round in that same native clip.
        for identity, remaining, damage in (('a', 1, 100), ('b', 0, 0), ('c', 3, 0)):
            p.launch(identity, 0, 42, 0., clip_remaining=remaining)
            self.resolve(p, identity, damage=damage)
        self.assertEqual(2, p.magazine)
        self.assertEqual(1, p.used)
        self.assertEqual(1, p.failures)
        self.assertEqual(0, p.desired)

    def test_alternate_phase_returns_at_native_clip_end_after_mid_clip_takeover(self):
        p = self.policy(clip=4)
        p.phase = p.desired = 1
        p.launch('a', 1, 42, 0., clip_remaining=1)
        self.resolve(p, 'a', damage=100)
        self.assertEqual(1, p.choose(self.inventory))
        p.launch('b', 1, 42, 0., clip_remaining=0)
        self.resolve(p, 'b', damage=100)
        self.assertEqual(0, p.choose(self.inventory))

    def test_phase_identity_rejects_delayed_receipts_after_returning_to_ap(self):
        p = self.policy()
        self.launch(p, 'old')
        self.launch(p, 'he', 2)
        self.launch(p, 'new')
        self.resolve(p, 'new')
        self.resolve(p, 'he', damage=10)
        self.resolve(p, 'old')
        self.assertEqual(0, p.desired)
        self.assertEqual(1, p.failures)
        self.assertEqual(2, p.phase_id)

    def test_target_and_position_epochs_reject_old_feedback(self):
        for next_position, next_target in (((4., 0., 0.), 42), ((0., 0., 0.), 43),
                                            ((0., 0., 0.), None)):
            p = self.policy()
            self.launch(p, 'old-a')
            self.launch(p, 'old-b')
            p.context(next_position, next_target)
            self.resolve(p, 'old-a')
            self.resolve(p, 'old-b')
            self.assertEqual(0, p.desired)
            self.assertEqual(0, p.failures)

    def test_context_displacement_threshold_and_latched_choice(self):
        p = self.policy()
        self.launch(p, 'a')
        self.resolve(p, 'a')
        for x, z in ((1, 0), (0, 1), (-1, 0), (0, -1), (3, 0)):
            p.context((x, 0., z), 42)
        self.assertEqual(1, p.failures)
        p.context((3.01, 0., 0.), 42)
        self.assertEqual(0, p.failures)
        for identity in ('b', 'c'):
            self.launch(p, identity, position=(3.01, 0., 0.))
            self.resolve(p, identity)
        p.context((9., 0., 0.), 43)
        self.assertEqual(1, p.choose(self.inventory))

    def test_unknown_round_makes_the_whole_burst_unknown(self):
        p = self.policy(clip=12)
        self.launch(p, 'a', group=7, count=2)
        self.launch(p, 'b', group=7, count=2)
        self.resolve(p, 'a')
        self.resolve(p, 'b', known=False)
        self.assertTrue(p.idle)
        self.assertEqual(0, p.desired)
        self.assertEqual(0, p.failures)

    def test_loaded_silver_he_remains_protected_while_premium_he_is_available(self):
        p = Ammunition([dict(index=0, kind='ARMOR_PIERCING'),
                        dict(index=1, kind='HIGH_EXPLOSIVE'),
                        dict(index=2, kind='HIGH_EXPLOSIVE', premium=True)], 0, 1)
        self.assertEqual(1, p.choose([10, 10, 10]))
        self.assertTrue(p.protected)
        p.launch('first', 1, 42, 0.)
        self.assertEqual(0, p.choose([10, 9, 10]))

    def test_actual_mounted_slots_determine_special_gun_roles_and_main(self):
        from gui.mods.offline_lan_0922.default_loadouts import GUN_AMMUNITION
        names = GUN_AMMUNITION['ussr:_122mm_cannon_U-11']
        raw = [dict(shell=dict(name=names[0], kind='HIGH_EXPLOSIVE', compactDescr=101)),
               dict(shell=dict(name=names[1], kind='HOLLOW_CHARGE', compactDescr=102))]
        descriptor = types.SimpleNamespace(type=types.SimpleNamespace(name='ussr:test', tags=()),
            gun=types.SimpleNamespace(name='_122mm_cannon_U-11', shots=raw))
        shots = [raw[1], raw[0]]
        gun = types.SimpleNamespace(shots=shots, shot_index=0, clip_size=1, ammo=[10, 10])
        self.assertEqual({1: 'standard', 0: 'premium'}, mounted_shell_roles(descriptor, shots))
        rows = mounted_shells(descriptor, shots)
        self.assertEqual([1, 0], [row['index'] for row in rows])
        policy = policy_from_gun(gun, descriptor)
        self.assertEqual(1, policy.main)
        self.assertEqual(0, policy.choose(gun.ammo))
        policy.launch('manual-loaded', 0, 42, 0.)
        self.assertEqual(1, policy.choose(gun.ammo))

    def test_artillery_prefers_he_but_protects_loaded_ap_and_uses_last_stock(self):
        desc = types.SimpleNamespace(type=types.SimpleNamespace(name='test:spg', tags=('SPG',)),
                                     gun=types.SimpleNamespace(name='unlisted'))
        shots = [dict(shell=dict(name='ap', kind='ARMOR_PIERCING')),
                 dict(shell=dict(name='he', kind='HIGH_EXPLOSIVE'))]
        gun = types.SimpleNamespace(shots=shots, shot_index=0, clip_size=1, ammo=[10, 10])
        p = policy_from_gun(gun, desc)
        self.inventory = gun.ammo
        self.assertEqual(1, p.main)
        self.assertEqual(0, p.choose(gun.ammo))
        self.launch(p, 'manual', shell=0)
        self.resolve(p, 'manual', hit=False)
        self.assertEqual(1, p.choose(gun.ammo))
        for index in range(3):
            self.launch(p, str(index), shell=1)
            self.resolve(p, str(index), hit=False)
            self.assertEqual(1, p.choose(gun.ammo))
        self.assertEqual(0, p.choose([10, 0]))

    def test_ordinary_premium_penetration_stage_precedes_he(self):
        descriptor = types.SimpleNamespace(type=types.SimpleNamespace(name='germany:test'),
            gun=types.SimpleNamespace(name='unlisted'))
        shots = [dict(shell=dict(name='standard', kind='ARMOR_PIERCING')),
                 dict(shell=dict(name='silver_he', kind='HIGH_EXPLOSIVE')),
                 dict(shell=dict(name='_Gr_38_HL_A', kind='HOLLOW_CHARGE'))]
        self.assertEqual([0, 2, 1], [s['index'] for s in mounted_shells(descriptor, shots)])


class Matrix(object):
    """Only the native Matrix snapshot boundary used by the tested planner."""
    def __init__(self, value=None):
        self.yaw = getattr(value, 'yaw', 0.)
        self.pitch = getattr(value, 'pitch', 0.)
        self.roll = getattr(value, 'roll', 0.)
        self.translation = getattr(value, 'translation', (0., 0., 0.))



class PresentedMatrix(object):
    def __init__(self, target):
        self.target = target
        self.yaw = self.pitch = self.roll = 0.
        self.offset = (0., 0., 0.)

    @property
    def translation(self):
        return tuple(self.target.position[i] + self.offset[i] for i in range(3))

def descriptor(minimum=-1.5, maximum=.5, yaw_limits=None):
    box = lambda lo, hi: types.SimpleNamespace(bbox=(lo, hi))
    return types.SimpleNamespace(
        type=types.SimpleNamespace(tags=(), name='test:tank'),
        chassis=types.SimpleNamespace(hullPosition=(0., 0., 0.)),
        hull=types.SimpleNamespace(turretPositions=((0., 2., 0.),),
            hitTester=box((-1., .5, -2.), (1., 1.5, 2.))),
        turret=types.SimpleNamespace(gunPosition=(0., 0., 0.),
            hitTester=box((-.7, 0., -.7), (.7, 1., .7))),
        gun=types.SimpleNamespace(turretYawLimits=yaw_limits, staticTurretYaw=None,
            pitchLimits=dict(minPitch=((0., minimum), (2.*math.pi, minimum)),
                             maxPitch=((0., maximum), (2.*math.pi, maximum)))))


def aiming_scene(speed=300., gravity=10., distance=100., own_descriptor=None, native='ballistic'):
    own_descriptor = own_descriptor or descriptor()
    shot = dict(speed=speed, gravity=gravity, maxDistance=5000., piercingPower=(150., 150.),
                shell=dict(kind='ARMOR_PIERCING', damage=(100., 0.), caliber=100.))
    origin = (0., 1., 0.)
    body = Matrix()
    own_entity = types.SimpleNamespace(id=1, typeDescriptor=own_descriptor)
    target = types.SimpleNamespace(id=42, position=(0., 0., distance),
        typeDescriptor=descriptor(), matrix=Matrix(), isStarted=True,
        isAlive=lambda: True, appearance=types.SimpleNamespace(turretMatrix=Matrix()))
    target.matrix = PresentedMatrix(target)
    rotator = types.SimpleNamespace(turretYaw=0., gunPitch=0., clientMode=True)
    owner = types.SimpleNamespace(_server=types.SimpleNamespace(vehicle_id=1),
        _server_entity=lambda unused: own_entity,
        _gun_state=types.SimpleNamespace(shots=[shot], shot_index=0),
        _mutable_shot_ray=lambda: (origin, (0., 0., 1.)),
        _local_stabilised_pose=lambda: body,
        _vector=tuple, _collision_shape=lambda unused: (1., 2., .5, 3.),
        _avatar=types.SimpleNamespace(gunRotator=rotator))

    def get_angles(desc, matrix, current, point):
        # This is a physical boundary oracle, not a stored expected answer:
        # the endpoint always selects the LOW ballistic root. High-arc tests
        # therefore require the player's source inversion to do real work.
        dx, dy, dz = (point[i]-origin[i] for i in range(3))
        yaw = math.atan2(dx, dz)
        if native == 'ballistic' and gravity > .01:
            roots = ballistics.ballistic_solutions(origin, point, speed, gravity)
            if not roots:
                raise ValueError('unreachable native source')
            pitch = roots[0][0]
        else:
            pitch = -math.atan2(dy, math.hypot(dx, dz))
        direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch),
                     math.cos(yaw)*math.cos(pitch))
        return shot_geometry.world_direction_to_local_gun_angles(
            direction, matrix.yaw, matrix.pitch, matrix.roll)

    owner._runtime = types.SimpleNamespace(math=types.SimpleNamespace(Matrix=Matrix),
                                            get_shot_angles=get_angles)
    return owner, target, shot, body


class AimingMigrationTests(unittest.TestCase):
    def setUp(self):
        # Only native collision is replaced; candidates, trajectory equations,
        # mechanical limits, point-source inversion and armour laws are real.
        self.collision = mock.patch(
            'gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',
            return_value=())
        self.collision_mock = self.collision.start()
        self.addCleanup(self.collision.stop)

    def tick(self, planner, target, now, lane=lambda a, b: True, artillery=False):
        planner.begin([target], now)
        return planner.update(target, now, lane, artillery)

    def test_direct_solution_has_real_native_source_and_barrel_proof(self):
        owner, target, shot, body = aiming_scene()
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertTrue(result['clear'])
        self.assertTrue(result['reachable'])
        self.assertTrue(result['source_verified'])
        self.assertGreater(result['flight_time'], 0.)
        self.assertTrue(p.confirm(target, result, result['direction'], 0., lambda a, b: True))
        self.assertLessEqual(p.receipt['segments'], 12)

    def test_observed_motion_leads_target_and_disappearance_erases_velocity(self):
        owner, target, shot, body = aiming_scene(distance=300.)
        p = Aiming(owner)
        self.tick(p, target, 0.)
        target.position = (1.2, 0., 300.)
        result = self.tick(p, target, .1)
        self.assertAlmostEqual(12., result['velocity'][0])
        self.assertGreater(result['point'][0], 12.)
        sample = shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)[result['sample']]
        observed = shot_geometry.vehicle_aim_point(sample, dict(position=target.position))
        self.assertAlmostEqual(observed[0]+12.*result['flight_time'], result['point'][0], places=3)
        p.begin([], .2)
        rejected = p.update(target, .2, lambda a, b: True)
        self.assertEqual('not_observed', rejected['reason'])
        self.assertFalse(p.observations)
        p.begin([target], .3)
        self.assertEqual((0., 0., 0.), p.observations[target.id]['velocity'])

    def test_hidden_roster_velocity_cannot_supply_target_prediction(self):
        owner, target, shot, body = aiming_scene()
        owner._records = {'hidden': dict(state=dict(velocity=(1000., 0., 0.)))}
        target.velocity = (1000., 0., 0.)
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertEqual((0., 0., 0.), result['velocity'])
        self.assertAlmostEqual(0., result['point'][0])

    def test_fully_occluded_hull_finds_exposed_turret_part(self):
        owner, target, shot, body = aiming_scene(speed=1000.)
        p = Aiming(owner)
        def lane(a, b):
            return b[2] < 99. or b[1] > 2.
        result = None
        for index in range(8):
            result = self.tick(p, target, index*.1, lane)
            if result['clear']:
                break
        self.assertTrue(result['clear'])
        self.assertEqual('turret', result['part'])
        self.assertGreater(result['point'][1], 2.)

    def test_nominal_native_armor_score_prefers_penetrable_exposed_part(self):
        def collision(target, matrix, start, end, math_module):
            armor = 300. if end[1] < 2. else 40.
            return (types.SimpleNamespace(dist=1., hitAngleCos=1., compName='vehicleHull',
                    matInfo=types.SimpleNamespace(armor=armor, vehicleDamageFactor=1.)),)
        self.collision_mock.side_effect = collision
        owner, target, shot, body = aiming_scene(speed=1000.)
        p = Aiming(owner)
        scores = []
        for index in range(9):
            result = self.tick(p, target, index*.1)
            if result['clear']:
                scores.append(result['score'])
        self.assertIn(0., scores)
        self.assertEqual(100., result['score'])
        self.assertEqual('turret', result['part'])

    def test_yaw_limited_gun_has_geometry_for_hull_facing_without_fire_permission(self):
        own = descriptor(yaw_limits=(-.2, .2))
        owner, target, shot, body = aiming_scene(speed=1000., own_descriptor=own)
        target.position = (100., 0., 0.)
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertEqual('yaw_limit', result['reason'])
        self.assertTrue(result['needs_hull'])
        self.assertTrue(result['geometry_clear'])
        self.assertFalse(result['reachable'])
        self.assertFalse(result['clear'])

    def test_pitch_limit_is_distinct_from_a_hull_traverse_request(self):
        own = descriptor(minimum=-.05, maximum=.05)
        owner, target, shot, body = aiming_scene(speed=1000., own_descriptor=own)
        target.position = (0., 50., 100.)
        result = self.tick(Aiming(owner), target, 0.)
        self.assertEqual('pitch_limit', result['reason'])
        self.assertFalse(result['needs_hull'])
        self.assertFalse(result['reachable'])
        self.assertTrue(result['geometry_clear'])

    def test_cross_slope_uses_full_stabilised_body_rotation(self):
        desc = descriptor(minimum=-.1, maximum=.1)
        level = mechanical_reach(desc, (1., 0., 0.), (0., 0., 0.))
        tilted = mechanical_reach(desc, (1., 0., 0.), (0., 0., .3))
        self.assertTrue(level['reachable'])
        self.assertFalse(tilted['reachable'])
        self.assertEqual('pitch_limit', tilted['reason'])

    def test_observed_part_and_velocity_share_the_native_presentation_matrix(self):
        owner, target, shot, body = aiming_scene(speed=1000.)
        target.matrix.offset = (0., .4, 0.)
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        sample = shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)[result['sample']]
        expected = shot_geometry.vehicle_aim_point(sample, dict(position=target.matrix.translation))
        self.assertEqual(expected, result['point'])
        self.assertEqual(target.matrix.translation, p.observations[target.id]['position'])

    def test_high_arc_hull_facing_uses_launch_direction_on_a_cross_slope(self):
        desc = descriptor(yaw_limits=(-.2, .2))
        owner, target, shot, body = aiming_scene(own_descriptor=desc)
        body.roll = .3
        direction = (0., math.sin(1.), math.cos(1.))
        expected_yaw, unused_pitch = shot_geometry.world_direction_to_local_gun_angles(
            direction, 0., 0., .3)
        error = hull_traverse_error(owner, desc, (0., 1., 100.), 0.,
                                   solution=dict(direction=direction))
        self.assertGreater(expected_yaw, .2)
        self.assertAlmostEqual(expected_yaw-(.2-.08), error)
        self.assertEqual(0., hull_traverse_error(owner, desc, (0., 1., 100.), 0.))

    def test_blocked_yaw_limited_candidate_does_not_request_a_combat_hold(self):
        desc = descriptor(yaw_limits=(-.2, .2))
        owner, target, shot, body = aiming_scene(speed=1000., own_descriptor=desc)
        target.position = (100., 0., 0.)
        result = self.tick(Aiming(owner), target, 0., lambda a, b: False)
        self.assertEqual('yaw_limit', result['reason'])
        self.assertFalse(result['geometry_clear'])
        self.assertFalse(result['needs_hull'])

    def test_missing_pitch_curves_and_native_source_fail_closed(self):
        owner, target, shot, body = aiming_scene(speed=1000.)
        owner._server_entity(1).typeDescriptor.gun.pitchLimits = dict(absolute=(-1., 1.))
        result = self.tick(Aiming(owner), target, 0.)
        self.assertEqual('pitch_limits_unavailable', result['reason'])
        self.assertFalse(result['reachable'])
        owner._server_entity(1).typeDescriptor.gun.pitchLimits = descriptor().gun.pitchLimits
        owner._runtime.get_shot_angles = lambda *args: (2., 1.)
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertFalse(result['clear'])
        self.assertFalse(result['source_verified'])
        self.assertEqual('native_source_unverified', result['reason'])
        self.assertLessEqual(p.receipt['native_angles'], 12)

    def test_high_arc_is_actually_reproduced_by_low_root_native_point_solver(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        p = Aiming(owner)
        # A sixty-metre ridge near midflight stops the shallow root but leaves
        # the physically higher arc. The sampling budget must finish over ticks.
        def lane(a, b):
            return not (a[2] <= 100. <= b[2] and max(a[1], b[1]) < 60.)
        result = None
        for index in range(40):
            result = self.tick(p, target, index*.1, lane, artillery=True)
            self.assertLessEqual(p.receipt['segments'], 12)
            self.assertLessEqual(p.receipt['candidates'], 2)
            self.assertLessEqual(p.receipt['native_angles'], 12)
            if result['clear'] and result['arc'] == 'high':
                break
        self.assertTrue(result['clear'], result)
        self.assertEqual('high', result['arc'])
        native_yaw, native_pitch = owner._runtime.get_shot_angles(
            owner._server_entity(1).typeDescriptor, body, (0., 0.), result['source_point'])
        # The ordinary endpoint still requests the LOW root; the verified
        # alternate source is what makes the native high barrel possible.
        unused_yaw, endpoint_pitch = owner._runtime.get_shot_angles(
            owner._server_entity(1).typeDescriptor, body, (0., 0.), result['point'])
        self.assertLess(native_pitch, endpoint_pitch-.2)
        landed = ballistics.ballistic_position(
            result['origin'], native_yaw, native_pitch, shot['speed'], shot['gravity'],
            result['flight_time'])
        for actual, expected in zip(landed, result['point']):
            self.assertAlmostEqual(expected, actual, delta=.3)
        self.assertTrue(barrel_aligned(result['origin'], result['direction'],
            shot['speed'], shot['gravity'], result['point'], .01))

    def test_high_arc_omitted_when_installed_elevation_cannot_reach_it(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.,
                                               own_descriptor=descriptor(minimum=-.7))
        p = Aiming(owner)
        results = []
        for index in range(20):
            result = self.tick(p, target, index*.1, lambda a, b: False, artillery=True)
            results.append(result)
        self.assertFalse(any(r['clear'] for r in results))
        high = [j['solution'] for j in p.entries[target.id]['jobs'].values()
                if j['solution']['arc'] == 'high']
        self.assertTrue(high)
        self.assertTrue(all(not r['reachable'] for r in high))

    def test_global_candidate_and_segment_budget_does_not_reset_per_enemy(self):
        owner, first, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        targets = [types.SimpleNamespace(**dict(first.__dict__, id=42+i)) for i in range(8)]
        p = Aiming(owner)
        lane = mock.Mock(return_value=True)
        for tick in range(4):
            p.begin(targets, tick*.1)
            before = lane.call_count
            for target in targets:
                p.update(target, tick*.1, lane, artillery=True)
            p.begin(targets, tick*.1)
            p.update(targets[0], tick*.1, lane, artillery=True)
            self.assertLessEqual(lane.call_count-before, 12)
            self.assertLessEqual(p.receipt['candidates'], 2)
        self.assertTrue(all(entry['jobs'] for entry in p.entries.values()))

    def test_actual_barrel_proof_rejects_geometry_nominal_arc_did_not_test(self):
        owner, target, shot, body = aiming_scene()
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertTrue(result['clear'])
        self.assertFalse(p.confirm(target, result, result['direction'], 0., lambda a, b: False))
        self.assertFalse(p.entries[target.id]['jobs'][result['key']]['clear'])

    def test_long_actual_path_is_verified_in_current_frame_with_hard_budget(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        p = Aiming(owner)
        result = None
        for index in range(20):
            result = self.tick(p, target, index*.1, artillery=True)
            if result['clear']:
                break
        self.assertTrue(result['clear'])
        ready = False
        for index in range(20, 35):
            now = index*.1
            result = self.tick(p, target, now, artillery=True)
            if not result['clear']:
                continue
            ready = p.confirm(target, result, result['direction'], now, lambda a, b: True)
            self.assertLessEqual(p.receipt['segments'], 12)
            if ready:
                break
        self.assertTrue(ready)
        self.assertGreater(p.receipt['final_segments'], 12)
        self.assertLessEqual(p.receipt['final_segments'], 167)
        self.assertEqual(1, p.receipt['final_attempts'])

    def test_pending_arc_proof_keeps_aiming_at_current_observed_intercept(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        p = Aiming(owner)
        first = self.tick(p, target, 0., artillery=True)
        self.assertFalse(first['clear'])
        target.position = (.1, 0., 200.)
        second = self.tick(p, target, .1, artillery=True)
        self.assertEqual(.1, second['created'])
        self.assertGreater(second['point'][0], first['point'][0]+1.)
        self.assertTrue(any(j['solution']['created'] == 0.
                            for j in p.entries[target.id]['jobs'].values()))

    def test_moving_artillery_target_lead_has_no_obsolete_probe_delay(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        p = Aiming(owner)
        ready = False
        for index in range(70):
            now = index*.1
            target.position = (3.*now, 0., 200.)
            result = self.tick(p, target, now, artillery=True)
            if not result['clear']:
                continue
            ready = p.confirm(target, result, result['direction'], now, lambda a, b: True)
            self.assertLessEqual(p.receipt['segments'], 12)
            if ready:
                break
        self.assertTrue(ready)
        self.assertEqual(0., result['lead_delay'])
        sample = shot_geometry.ordered_vehicle_aim_samples(target.typeDescriptor)[result['sample']]
        current = shot_geometry.vehicle_aim_point(sample, dict(position=target.position))
        expected = tuple(current[i] + result['velocity'][i]*result['flight_time'] for i in range(3))
        self.assertLess(math.sqrt(sum((result['point'][i]-expected[i])**2 for i in range(3))), .3)

    def test_continuous_millimetre_muzzle_jitter_keeps_current_exact_final_path(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        muzzle = [(0., 1., 0.)]
        owner._mutable_shot_ray = lambda: (muzzle[0], (0., 0., 1.))
        def get_angles(desc, matrix, current, point):
            pitch, unused_time = ballistics.ballistic_solutions(muzzle[0], point, 50., 10.)[0]
            return math.atan2(point[0]-muzzle[0][0], point[2]-muzzle[0][2]), pitch
        owner._runtime.get_shot_angles = get_angles
        p = Aiming(owner)
        accepted = []
        seen_origins = set()
        for index in range(100):
            now = index*.1
            # Continuously changing, non-repeated measured positions: an
            # exact-key cache of two alternating poses cannot pass this test.
            muzzle[0] = (.002*math.sin(index*.73), 1.+.001*math.sin(index*.37), 0.)
            seen_origins.add(muzzle[0])
            result = self.tick(p, target, now, artillery=True)
            if not result['clear']:
                continue
            pitch, unused_time = ballistics.ballistic_solutions(
                muzzle[0], result['point'], shot['speed'], shot['gravity'])[0]
            yaw = math.atan2(result['point'][0]-muzzle[0][0], result['point'][2]-muzzle[0][2])
            direction = (math.sin(yaw)*math.cos(pitch), -math.sin(pitch),
                         math.cos(yaw)*math.cos(pitch))
            checked = []
            def static_lane(first, last):
                checked.append((first, last))
                return True
            if p.confirm(target, result, direction, now, static_lane, lambda path: True):
                accepted.append(now)
                current_path = artillery_path(muzzle[0], result['point'], shot, direction)
                self.assertEqual(list(zip(current_path, current_path[1:])), checked)
                self.assertEqual(muzzle[0], checked[0][0])
                self.assertGreater(len(checked), 12)
            self.assertLessEqual(p.receipt['segments'], 12)
            self.assertLessEqual(p.receipt['candidates'], 2)
            self.assertLessEqual(p.receipt['native_angles'], 12)
            self.assertLessEqual(p.receipt['final_segments'], 167)
        self.assertEqual(100, len(seen_origins))
        self.assertGreater(len(accepted), 1)
        self.assertTrue(all(last-first >= .5-1.e-9 for first, last in zip(accepted, accepted[1:])))

    def test_friend_entering_already_planned_chord_blocks_before_static_final_cost(self):
        owner, target, shot, body = aiming_scene(speed=50., gravity=10., distance=200.)
        p = Aiming(owner)
        bounds = [None]
        def combined_lane(first, last):
            return bounds[0] is None or shot_geometry.segment_box_entry_distance(
                first, last, bounds[0]) is None
        self.tick(p, target, 0., combined_lane, artillery=True)
        cached = p.entries[target.id]['jobs'][(0, 'low')]
        self.assertGreater(cached['next'], 0)
        self.assertFalse(cached['done'])
        path = cached['solution']['path']
        centre = tuple((path[0][i]+path[1][i])*.5 for i in range(3))
        bounds[0] = (tuple(v-.05 for v in centre), tuple(v+.05 for v in centre))
        result = None
        for index in range(1, 25):
            now = index*.1
            result = self.tick(p, target, now, combined_lane, artillery=True)
            if result['clear'] and result['arc'] == 'low':
                break
        self.assertTrue(result['clear'])
        def dynamic_clear(path):
            return all(combined_lane(first, last) for first, last in zip(path, path[1:]))
        static = mock.Mock(return_value=True)
        self.assertFalse(p.confirm(target, result, result['direction'], now, static, dynamic_clear))
        static.assert_not_called()
        self.assertEqual('dynamic_blocked', p.receipt['final_reason'])
        self.assertEqual(0, p.receipt['final_segments'])
        self.assertEqual(0, p.receipt['final_attempts'])
        bounds[0] = None
        now += .1
        result = self.tick(p, target, now, combined_lane, artillery=True)
        self.assertTrue(p.confirm(target, result, result['direction'], now, static, dynamic_clear))
        self.assertGreater(static.call_count, 12)
        self.assertEqual(2, p.receipt['dynamic_checks'])

    def test_dynamic_path_is_read_again_immediately_after_final_static_queries(self):
        owner, target, shot, body = aiming_scene()
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        obstructed = [False]
        def static_lane(first, last):
            obstructed[0] = True
            return True
        dynamic = mock.Mock(side_effect=lambda path: not obstructed[0])
        self.assertFalse(p.confirm(target, result, result['direction'], 0., static_lane, dynamic))
        self.assertEqual(2, dynamic.call_count)
        self.assertEqual('dynamic_blocked', p.receipt['final_reason'])
        self.assertGreater(p.receipt['final_segments'], 0)

    def test_expensive_final_gate_has_shared_half_second_cooldown(self):
        owner, target, shot, body = aiming_scene()
        p = Aiming(owner)
        static = mock.Mock(return_value=True)
        dynamic = mock.Mock(return_value=True)
        for now, permitted in ((0., True), (.1, False), (.49, False), (.5, True)):
            result = self.tick(p, target, now)
            before = static.call_count
            self.assertEqual(permitted,
                p.confirm(target, result, result['direction'], now, static, dynamic))
            self.assertEqual(permitted, static.call_count > before)
            self.assertEqual(1 if permitted else 0, p.receipt['final_attempts'])
        self.assertEqual(4, dynamic.call_count)

    def test_high_arc_lifetime_limit_caps_final_gate_at_167_chords(self):
        owner, target, shot, body = aiming_scene(speed=100., gravity=10., distance=100.,
                                               own_descriptor=descriptor(minimum=-1.57))
        p = Aiming(owner)
        def lane(first, last):
            return not (first[2] <= 50. <= last[2] and max(first[1], last[1]) < 50.)
        result = None
        for index in range(40):
            now = index*.1
            result = self.tick(p, target, now, lane, artillery=True)
            if result['clear'] and result['arc'] == 'high':
                break
        self.assertTrue(result['clear'])
        self.assertEqual('high', result['arc'])
        static = mock.Mock(return_value=True)
        self.assertTrue(p.confirm(target, result, result['direction'], now, static, lambda path: True))
        self.assertEqual(167, static.call_count)
        self.assertEqual(167, p.receipt['final_segments'])
        self.assertLessEqual(p.receipt['segments'], 12)
        self.assertLessEqual(p.receipt['native_angles'], 12)

    def test_shell_change_invalidates_old_ballistic_proof(self):
        owner, target, shot, body = aiming_scene()
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        owner._gun_state.shots.append(dict(shot, speed=150.))
        owner._gun_state.shot_index = 1
        self.assertFalse(p.confirm(target, result, result['direction'], 0., lambda a, b: True))

    def test_zero_gravity_and_negative_gravity_use_physical_paths(self):
        owner, target, shot, body = aiming_scene(speed=300., gravity=0.)
        p = Aiming(owner)
        result = self.tick(p, target, 0.)
        self.assertEqual('direct', result['arc'])
        self.assertTrue(result['clear'])
        self.assertTrue(p.confirm(target, result, result['direction'], 0., lambda a, b: True))
        shot = dict(shot, gravity=-10.)
        positive = artillery_path((0., 1., 0.), (0., 1., 100.), dict(shot, gravity=10.))
        negative = artillery_path((0., 1., 0.), (0., 1., 100.), shot)
        self.assertEqual(positive, negative)
        self.assertFalse(artillery_path((0., 1., 0.), (0., 1., 100.), dict(shot, maxDistance=10.)))

    def test_weapon_uses_verified_source_without_losing_impact_point(self):
        owner, target, shot, body = aiming_scene()
        weapon = Weapon(owner)
        weapon.bind = lambda: None
        result = dict(point=(0., 1., 100.), source_point=(0., 10., 5.),
                      reachable=True, source_verified=True, arc='high', sample=1)
        weapon.aim_solution(42, result, 0.)
        self.assertEqual(result['source_point'], weapon.shot_point())
        self.assertEqual(result['point'], weapon.point)
        self.assertFalse(weapon.ready(.1, 1.))
        self.assertTrue(weapon.ready(.3, 1.))
        weapon.fired = True
        weapon.aim_solution(42, dict(result, reachable=False), 1.)
        self.assertFalse(weapon.ready(100., 1.))
        weapon.aim_solution(42, dict(result, arc='low'), 2.)
        self.assertFalse(weapon.fired)
        self.assertFalse(weapon.ready(2.1, 1.))
        weapon.forward((0., 0., 0.), 0., 1.)
        self.assertEqual(weapon.point, weapon.shot_point())
        self.assertIsNone(weapon.solution)

    def test_weapon_does_not_count_an_unrelated_existing_intent_as_accepted(self):
        owner = types.SimpleNamespace(_local_fire_intent={'old': True},
            _avatar=types.SimpleNamespace(shoot=lambda: None, isWaitingForShot=True))
        self.assertFalse(Weapon(owner).trigger())

    def test_player_weapon_modules_have_no_bot_decision_or_pose_force_dependency(self):
        package = ROOT/'src/res/scripts/client/gui/mods/offline_lan_0922/player_control'
        denied = ('bot_runtime', 'bot_gunnery', 'ammo_policy', 'artillery_controller',
                  'ShotPolicy', 'forceGunParams', 'setGunAngles')
        for name in ('ammunition.py', 'aiming.py', 'weapon.py'):
            text = (package/name).read_text()
            tree = ast.parse(text)
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                           for alias in node.names)
            for forbidden in denied:
                self.assertFalse(any(forbidden in (entry or '') for entry in imports))
                self.assertNotIn('.'+forbidden+'(', text)


if __name__ == '__main__':
    unittest.main()
