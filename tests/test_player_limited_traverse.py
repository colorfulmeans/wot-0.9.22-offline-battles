"""Independent player hull laying retains a mechanically unlaid target.

Report 183205, WZ round 3, visible-client lines 20593/20594: the player has
ammunition and fifteen visible contacts while yaw_limit comparisons return
unavailable, no selected target reaches combat_facing, and capture holds the
tracks still. The report does not expose the mounted yaw limits. The bands
below are explicit narrow/fixed/limited-turret test descriptors, not invented
measurements of that WZ. Native angle and world probes are explicit seams;
Aiming, DirectEngagement, navigation, weapon readiness and the final player
sender are production consumers.
"""
import copy
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.aiming import (
    Aiming, NATIVE_ANGLE_TOLERANCE, _direction, mechanical_reach)
from gui.mods.offline_lan_0922.player_control.direct_engagement import (
    DirectEngagement, PENETRATION_FACTOR_65)
from gui.mods.offline_lan_0922.player_control.weapon import Weapon, hull_traverse_error
from gui.mods.offline_lan_0922.player_control.traffic import TurnClearance
from gui.mods.offline_lan_0922.player_control.ammunition import policy_from_gun
import test_player_control as control_tests
import test_player_fire_admission_complete as fire_tests
from gui.mods.offline_lan_0922 import gun_mechanics, shot_geometry
from test_player_navigation_migration import controller as navigation_controller
from test_player_weapon_migration import aiming_scene, descriptor


class LimitedTraverseScene(object):
    def __init__(self, test, limits=(-.2, .2), tag='AT-SPG', clip=1,
                 bearing=.7, capture=False):
        self.control, unused = control_tests.PlayerRegressionTests().aim_controller()
        control, owner = self.control, self.control.owner
        self.descriptor = descriptor(yaw_limits=limits)
        self.descriptor.maxHealth = 1000
        self.descriptor.type.tags = (tag,)
        self.entity = owner._server_entity(1)
        self.entity.typeDescriptor = self.descriptor
        native, self.target, shot, self.body = aiming_scene(
            speed=1000., own_descriptor=self.descriptor)
        self.now = 0.
        self.position = (0., 0., 100. if capture else 0.)
        self.target.position = (self.position[0] + math.sin(bearing)*100., 0.,
                                self.position[2] + math.cos(bearing)*100.)
        self.records = {self.target.id: self.target}
        owner._server_entity = lambda identity: (self.entity if identity == self.entity.id
                                                 else self.records.get(identity))
        owner._records = {'test-target': dict(engine_id=self.target.id, ready=True,
            spot_visible=True, state=dict(team=2, alive=True, health=1000))}
        owner._runtime = native._runtime
        owner._avatar = native._avatar
        owner._avatar.autoAim = lambda unused: None
        owner._avatar.gunRotator._VehicleGunRotator__shotPointSourceFunctor = lambda: None
        owner._vector = tuple
        owner._local_stabilised_pose = lambda: self.body
        owner._clock = lambda: self.now
        owner.local_pose = lambda: (self.position, self.body.yaw)
        owner._mutable_shot_ray = lambda: (
            (self.position[0], 1., self.position[2]),
            (math.sin(self.body.yaw), 0., math.cos(self.body.yaw)))
        owner._local_turn_speed = 0.
        owner._gun_state.shots = [shot]
        owner._gun_state.clip_size = owner._gun_state.clip = clip
        owner._gun_state.ammo = [10]
        control.weapon = Weapon(owner)
        control.aiming = Aiming(owner)
        control.direct_engagement = DirectEngagement(self.descriptor)
        control.ammo_policy = types.SimpleNamespace(main=0, context=lambda *args: None,
            shells=[dict(index=0, kind='ARMOR_PIERCING')])
        control.navigation = navigation_controller(tag)
        test.addCleanup(control.navigation.close)
        control.navigation.route = control.navigation.routes[0]
        control.navigation.index = 1
        control.emit_result = mock.Mock(return_value=True)
        control.publish_status = mock.Mock()
        control._contacts = lambda unused: ([], [], self.records)
        control.lane_from = lambda *args: True
        control.trigger = mock.Mock(return_value=False)
        control.rotation_clear = lambda *args: True
        if capture:
            control.navigation._automatic_capture(dict(position=self.position,
                speed=0., yaw=self.body.yaw, now=0.), 'route_terminal_capture')

    def step(self, now):
        self.now = now
        self.control.update(.1, now)
        return self.control.last_order


class MovingTraverseScene(object):
    """Real controller/fire chain with an explicit native pose/rotator seam.

    The chassis advances by commanded yaw at the supplied mounted rate. The
    native rotator reads the installed point source and clamps its local yaw
    to the installed arc. This does not model Windows track dynamics. Native
    world/vehicle hit-test seams are the geometric adapters already used by
    the full physical-shot tests; no player readiness or admission is mocked.
    """
    def __init__(self, test, limits=(-.2, .2), tag='AT-SPG', clip=1,
                 bearing=.7, rate=.75, burst=1):
        self.native = fire_tests.AutomaticFireAdmissionTests()
        self.native.setUp()
        test.addCleanup(self.native.doCleanups)
        self.control, self.owner = self.native.control, self.native.battle
        self.entity, self.target = self.native.entity, self.native.target
        self.body = self.native.body
        # The native report's strongest failure is a settled automatic
        # capture. Hold that real navigation owner while the target scan
        # finishes, so incidental route steering cannot lay the gun first.
        self.position = (0., 0., 100.)
        self.native.origin = (0., 2., 100.)
        self.rate, self.rotator_enabled, self.source_enabled = rate, False, True
        descriptor = self.entity.typeDescriptor
        descriptor.type.tags = (tag,)
        descriptor.gun.turretYawLimits = limits
        descriptor.gun.clip = (clip, .5) if clip > 1 else (1,)
        descriptor.gun.burst = (burst, .1)
        self.owner._gun_state = gun_mechanics.GunState(descriptor,
                                                      ammo_layout={101: 20, 102: 10})
        self.owner._gun_state.reload_time = 0.
        self.owner._gun_state.clip = clip
        self.native.pose(self.target, (self.position[0] + math.sin(bearing)*100., 0.,
                                      self.position[2] + math.cos(bearing)*100.))
        self.records = {self.target.id: self.target}
        self.owner.local_pose = lambda: (self.position, self.body.yaw)
        self.owner._local_speed = self.owner._local_turn_speed = 0.
        self.owner._local_physics = dict(rotSpd=rate)
        self.owner._local_pitch = self.owner._local_roll = 0.
        self.owner._rules_state = {}
        self.control.features.add('drive')
        self.control.bind_input = lambda: None
        self.control.poll_commands = lambda unused: None
        self.control.publish_status = mock.Mock()
        self.control.select_ammo = lambda unused: None
        self.control._contacts = lambda unused: ([], [], self.records)
        self.control.direction_clear = lambda *args: True
        self.control.rotation_clear = mock.Mock(return_value=True)
        self.control.strategy = types.SimpleNamespace(mode='front', decide=lambda *args, **kw: None)
        self.control.turn_clearance = TurnClearance()
        self.control.navigation = navigation_controller(tag)
        test.addCleanup(self.control.navigation.close)
        self.control.navigation.route = self.control.navigation.routes[0]
        self.control.navigation.index = 1
        self.control.navigation._automatic_capture(dict(position=self.position,
            speed=0., yaw=0., now=self.native.now), 'route_terminal_capture')
        self.control.emit_result = mock.Mock(return_value=True)
        self.control.weapon.close()
        self.control.weapon = Weapon(self.owner)
        self.control.aiming = Aiming(self.owner)
        self.control.direct_engagement = DirectEngagement(descriptor)
        self.control.ammo_policy = policy_from_gun(self.owner._gun_state, descriptor)
        self.trigger = mock.Mock(wraps=self.control.trigger)
        self.control.trigger = self.trigger
        self.source_queries = []
        def source_angles(desc, body, previous, point):
            self.source_queries.append((self.native.now, body.yaw, tuple(point)))
            if not self.source_enabled:
                raise ValueError('native angle source unavailable')
            return self.native.get_angles(desc, body, previous, point)
        self.owner._runtime.get_shot_angles = source_angles
        self.trace = []

    def step(self, seconds=.11):
        sender = self.owner._sender
        turn = 0. if sender.handbrake else sender.turn
        yaw = self.body.yaw + turn*self.rate*seconds
        self.body.setRotateYPR((yaw, 0., 0.))
        self.body.translation = self.position
        self.entity.matrix = fire_tests.Pose(self.body)
        self.entity.position = self.owner._vector(self.position)
        self.owner._local_turn_speed = turn*self.rate
        self.native.fixture.now += seconds
        if self.rotator_enabled and self.control.weapon.point is not None:
            rotator = self.owner._avatar.gunRotator
            point = rotator.shotPointSourceFunctor()
            local_yaw, pitch = self.native.get_angles(self.entity.typeDescriptor,
                self.body, (rotator.turretYaw, rotator.gunPitch), point)
            limits = self.entity.typeDescriptor.gun.turretYawLimits
            local_yaw = max(limits[0], min(limits[1], local_yaw)) if limits is not None else local_yaw
            rotator.turretYaw, rotator.gunPitch = local_yaw, pitch
            self.native.direction = _direction(self.body.yaw + local_yaw, pitch)
        self.control.update(seconds, self.native.now)
        self.trace.append(dict(time=self.native.now, yaw=self.body.yaw,
            sender=(sender.forward, sender.turn, sender.handbrake),
            facing=self.control.last_order.get('combat_facing'),
            aim=self.control.aim_receipt,
            ammo=tuple(self.owner._gun_state.ammo)))
        return self.control.last_order


class LimitedTraverseGeometryTests(unittest.TestCase):
    def compare(self, limits=(-.2, .2), bearing=.7, lane=True,
                pitch_limits=(-1.5, .5), height=0., tag='AT-SPG'):
        own = descriptor(*pitch_limits, yaw_limits=limits)
        own.type.tags = (tag,)
        owner, target, unused_shot, unused_body = aiming_scene(
            speed=1000., own_descriptor=own)
        target.position = (math.sin(bearing)*100., height, math.cos(bearing)*100.)
        planner = Aiming(owner)
        planner.begin([target], 0.)
        verdict, solution = planner.compare_direct(target, 0, 0, 0.,
            lambda *args: lane, PENETRATION_FACTOR_65)
        return verdict, solution, planner

    def test_completed_yaw_only_proof_survives_the_direct_comparison_boundary(self):
        for limits, bearing in (((-.2, .2), .7), ((-.2, .2), -.7),
                ((-.8, .8), 1.2), ((-.1, .6), -.5), ((0., 0.), .2)):
            with self.subTest(limits=limits, bearing=bearing):
                verdict, solution, planner = self.compare(limits, bearing)
                self.assertEqual('needs_hull', verdict)
                self.assertEqual('yaw_limit', solution['reason'])
                self.assertTrue(solution['geometry_clear'])
                self.assertTrue(solution['needs_hull'])
                self.assertFalse(solution['reachable'])
                self.assertFalse(solution['source_verified'])
                self.assertFalse(solution['clear'])
                self.assertNotIn('penetration_ok', solution)
                self.assertEqual(0, solution['sample'])
                self.assertEqual(12, planner._angles)

    def test_wall_or_pitch_refusal_is_not_a_hull_laying_candidate(self):
        for fields in (dict(lane=False),
                       dict(pitch_limits=(-.01, .01), height=50.),
                       dict(limits=None, pitch_limits=(-.01, .01), height=50.)):
            with self.subTest(fields=fields):
                verdict, solution, unused = self.compare(**fields)
                self.assertEqual('unavailable', verdict)
                self.assertFalse(solution['needs_hull'])
                self.assertFalse(solution['clear'])

    def test_full_or_already_in_arc_gun_does_not_acquire_a_hull_request(self):
        # Native armour is unavailable in this geometry-only fixture. That
        # may withhold fire, but it must not become a hull turning request.
        for limits, bearing in ((None, .7), ((-.8, .8), .7)):
            with self.subTest(limits=limits):
                verdict, solution, unused = self.compare(limits, bearing)
                self.assertNotEqual('needs_hull', verdict)
                self.assertTrue(solution['reachable'])
                self.assertFalse(solution['needs_hull'])

    def test_spg_direct_comparison_and_generic_candidate_contracts_are_unchanged(self):
        verdict, solution, unused = self.compare(tag='SPG')
        self.assertEqual('unavailable', verdict)
        self.assertTrue(solution['needs_hull'])
        self.assertFalse(solution['reachable'])
        owner, target, unused_shot, unused_body = aiming_scene(
            speed=1000., own_descriptor=descriptor(yaw_limits=(-.2, .2)))
        target.position = (100., 0., 0.)
        planner = Aiming(owner)
        planner.begin([target], 0.)
        generic = planner.update(target, 0., lambda *args: True, artillery=True)
        self.assertTrue(generic['needs_hull'])
        self.assertFalse(generic['clear'])

    def test_unfinished_world_proof_cannot_admit_the_hull_request(self):
        owner, target, unused_shot, unused_body = aiming_scene(
            speed=1000., own_descriptor=descriptor(yaw_limits=(-.2, .2)))
        target.position = (100., 0., 0.)
        planner = Aiming(owner)
        planner.begin([target], 0.)
        planner._segments = 0
        self.assertEqual(('pending', None), planner.compare_direct(target, 0, 0, 0.,
            lambda *args: True, PENETRATION_FACTOR_65))

    def test_actual_hull_change_rebuilds_native_source_before_firing_proof(self):
        verdict, unlaid, planner = self.compare()
        self.assertEqual('needs_hull', verdict)
        owner = planner.owner
        target = next(iter(planner.targets.values()))
        getter = owner._runtime.get_shot_angles
        owner._runtime.get_shot_angles = mock.Mock(wraps=getter)
        owner._local_stabilised_pose().yaw = .58
        planner.begin([target], .1)
        verdict, laid = planner.compare_direct(target, 0, 0, .1,
            lambda *args: True, PENETRATION_FACTOR_65)
        self.assertNotEqual('needs_hull', verdict)
        self.assertTrue(laid['reachable'])
        self.assertTrue(laid['source_verified'])
        self.assertFalse(laid['needs_hull'])
        self.assertEqual(unlaid['point'], laid['point'])
        self.assertGreater(owner._runtime.get_shot_angles.call_count, 0)

    def test_nonfiring_hull_proposal_cannot_pass_weapon_or_fresh_barrel_admission(self):
        verdict, solution, planner = self.compare()
        self.assertEqual('needs_hull', verdict)
        owner = planner.owner
        target = next(iter(planner.targets.values()))
        owner._avatar.autoAim = lambda unused: None
        owner._avatar.gunRotator._VehicleGunRotator__shotPointSourceFunctor = lambda: None
        weapon = Weapon(owner)
        weapon.aim_solution(target.id, solution, 0.)
        self.assertFalse(weapon.ready(100., 1.))
        reason, fresh = planner.fire_preflight(target, solution, owner._mutable_shot_ray(),
                                              owner._gun_state.shots[0], 0.)
        self.assertIsNotNone(reason)
        self.assertIsNone(fresh)

    def test_required_hull_error_obeys_installed_asymmetric_and_zero_width_arcs(self):
        owner, unused_target, unused_shot, body = aiming_scene()
        for limits, relative, expected in (
                ((-.2, .4), .5, .18), ((-.2, .4), -.3, -.18),
                ((0., 0.), .015, .015), ((-.2, .4), .35, 0.)):
            with self.subTest(limits=limits, relative=relative):
                desc = descriptor(yaw_limits=limits)
                direction = (math.sin(relative), 0., math.cos(relative))
                actual = hull_traverse_error(owner, desc, None, relative,
                                             solution=dict(direction=direction))
                self.assertAlmostEqual(expected, actual)
        self.assertIsNone(hull_traverse_error(owner, descriptor(), None, .7))

    def test_zero_width_gun_accepts_its_exact_transformed_heading(self):
        # sin/cos plus the inverse body transform produces a residual
        # 2.78e-17 rad here, despite the world ray and body having one yaw.
        # A zero-width installed arc must not ask the hull to chase that.
        owner, unused_target, unused_shot, body = aiming_scene()
        desc = descriptor(yaw_limits=(0., 0.))
        desc.type.tags = ('AT-SPG',)
        body.yaw = .2
        direction = _direction(body.yaw, -.07)
        reach = mechanical_reach(desc, direction, (.2, 0., 0.))
        self.assertTrue(reach['reachable'], reach)
        self.assertFalse(reach['needs_hull'])
        self.assertEqual(0., hull_traverse_error(owner, desc, None, 0.,
                                                dict(direction=direction)))

    def test_yaw_precision_matches_source_solver_without_widening_pitch_or_spg(self):
        owner, unused_target, unused_shot, unused_body = aiming_scene()
        tolerance = NATIVE_ANGLE_TOLERANCE
        for limits in ((0., 0.), (-.2, .4)):
            for edge, sign in ((limits[0], -1.), (limits[1], 1.)):
                for tag in ('AT-SPG', 'heavyTank', 'SPG'):
                    for residual in (tolerance*.5, tolerance*2.):
                        with self.subTest(limits=limits, edge=edge, tag=tag,
                                          residual=residual):
                            desc = descriptor(yaw_limits=limits)
                            desc.type.tags = (tag,)
                            relative = edge + sign*residual
                            direction = _direction(relative, 0.)
                            reach = mechanical_reach(desc, direction, (0., 0., 0.))
                            expected = tag != 'SPG' and residual < tolerance
                            self.assertEqual(expected, reach['reachable'], reach)
                            self.assertEqual(not expected, reach['needs_hull'])
                            error = hull_traverse_error(owner, desc, None, relative,
                                                        dict(direction=direction))
                            self.assertEqual(expected, error == 0., error)
        desc = descriptor(-.01, .01, yaw_limits=(0., 0.))
        reach = mechanical_reach(desc, _direction(tolerance*.5, .02), (0., 0., 0.))
        self.assertFalse(reach['reachable'])
        self.assertFalse(reach['needs_hull'])
        self.assertEqual('pitch_limit', reach['reason'])


class LimitedTraverseConsumerTests(unittest.TestCase):
    def test_loaded_casemate_and_limited_turret_clip_variants_reach_final_sender(self):
        for limits, tag, bearing in (((-.2, .2), 'AT-SPG', .7),
                ((-.8, .8), 'heavyTank', 1.2), ((0., 0.), 'AT-SPG', .015)):
            for clip in (1, 4):
                with self.subTest(limits=limits, tag=tag, clip=clip):
                    scene = LimitedTraverseScene(self, limits, tag, clip, bearing)
                    evidence = []
                    for tick in range(60):
                        order = scene.step(tick*.11)
                        sender = scene.control.owner._sender
                        evidence.append((scene.control.target_engine, sender.forward,
                                         sender.turn, order.get('combat_facing')))
                        if order.get('combat_facing', {}).get('state') == 'turning':
                            break
                    self.assertTrue(any(row[0] == scene.target.id and row[1] == 0. and
                                        row[2] * bearing > 0. and row[3] for row in evidence), evidence[-5:])
                    scene.control.trigger.assert_not_called()
                    self.assertFalse(scene.control.weapon.ready(scene.now+20., 1.))

    def test_automatic_capture_hold_can_lay_limited_gun_without_a_fireable_target(self):
        scene = LimitedTraverseScene(self, capture=True)
        evidence = []
        for tick in range(60):
            order = scene.step(tick*.11)
            sender = scene.control.owner._sender
            evidence.append((order.get('combat_mode'), sender.forward, sender.turn,
                             order.get('combat_facing')))
            if order.get('combat_facing', {}).get('state') == 'turning':
                break
        self.assertTrue(any(mode == 'base_capture' and forward == 0. and turn > 0. and facing
                            for mode, forward, turn, facing in evidence), evidence[-5:])
        self.assertFalse(scene.control.navigation.mission.explicit)
        scene.control.trigger.assert_not_called()


class MovingTraverseConsumerTests(unittest.TestCase):
    def advance_until(self, scene, predicate, limit=160):
        for unused in range(limit):
            scene.step()
            if predicate():
                return
        self.fail('state did not complete: %r' % scene.trace[-3:])

    def test_pose_enters_arc_then_source_barrel_and_armor_gate_the_real_shot(self):
        for limits, tag, bearing, clip in (((-.2, .2), 'AT-SPG', .7, 1),
                                         ((-.2, .2), 'AT-SPG', .7, 4),
                                         ((-.8, .8), 'heavyTank', -1.2, 1),
                                         ((-.8, .8), 'heavyTank', -1.2, 4)):
            with self.subTest(limits=limits, clip=clip):
                scene = MovingTraverseScene(self, limits, tag, clip, bearing)
                initial_ammo = tuple(scene.owner._gun_state.ammo)
                scene.source_enabled = False
                self.advance_until(scene, lambda: bool(scene.source_queries))
                self.assertTrue(any(row['facing'] and row['facing']['state'] == 'turning'
                                    for row in scene.trace))
                self.assertGreater(scene.body.yaw*bearing, 0.)
                self.assertEqual(initial_ammo, tuple(scene.owner._gun_state.ammo))
                self.assertEqual(0, scene.control.automatic_commits)
                self.assertFalse(scene.owner._projectile_meta)
                scene.trigger.assert_not_called()

                # The hull is mechanically in range. Native source failure
                # still forbids fire, then an unlaid physical barrel must too.
                queries = len(scene.source_queries)
                scene.source_enabled = True
                self.advance_until(scene, lambda: bool(scene.control.weapon.solution and
                    scene.control.weapon.solution.get('source_verified') and
                    scene.control.weapon.solution.get('reachable')))
                self.assertGreater(len(scene.source_queries), queries)
                self.assertFalse(scene.control.aim_receipt['aligned'])
                self.assertEqual(initial_ammo, tuple(scene.owner._gun_state.ammo))
                scene.trigger.assert_not_called()

                def unavailable_hit_tester():
                    raise RuntimeError('native target hit tester unavailable')
                for component in ('chassis', 'hull', 'turret', 'gun'):
                    getattr(scene.target.typeDescriptor, component).hitTester.on_hit = unavailable_hit_tester
                scene.rotator_enabled = True
                for unused in range(4):
                    scene.step()
                self.assertEqual(initial_ammo, tuple(scene.owner._gun_state.ammo))
                self.assertFalse(scene.owner._projectile_meta)
                scene.trigger.assert_not_called()
                for component in ('chassis', 'hull', 'turret', 'gun'):
                    getattr(scene.target.typeDescriptor, component).hitTester.on_hit = None
                self.advance_until(scene, lambda: scene.control.automatic_commits == 1)
                self.assertEqual(initial_ammo[0]-1, scene.owner._gun_state.ammo[0])
                self.assertEqual(1, len(scene.owner._projectile_meta))
                self.assertGreater(scene.trigger.call_count, 0)
                proof = scene.control.fire_admission.receipt
                self.assertEqual('committed', proof['status'])
                self.assertEqual(scene.target.id, proof['terminal_vehicle'])
                self.assertEqual('structural', proof['terminal_layer'])
                self.assertGreater(proof['world_chords'], 0)
                self.assertFalse(scene.control.weapon.solution['needs_hull'])

    def test_slow_zero_width_gun_can_finish_its_actual_pose_alignment(self):
        for clip in (1, 4):
            with self.subTest(clip=clip):
                scene = MovingTraverseScene(self, limits=(0., 0.), clip=clip, bearing=.015, rate=.2)
                scene.rotator_enabled = True
                self.advance_until(scene, lambda: scene.control.automatic_commits == 1, limit=250)
                self.assertFalse(any(row['facing'] and row['facing']['state'] == 'stalled'
                                     for row in scene.trace), scene.trace[-3:])
                self.assertEqual(1, len(scene.owner._projectile_meta))

    def test_limited_clip_burst_lays_once_then_commits_exactly_three_physical_rounds(self):
        for limits, tag, bearing in (((-.2, .2), 'AT-SPG', .7),
                                     ((-.8, .8), 'heavyTank', -1.2)):
            with self.subTest(limits=limits, tag=tag):
                scene = MovingTraverseScene(self, limits, tag, clip=6, bearing=bearing, burst=3)
                scene.rotator_enabled = True
                gun = scene.owner._gun_state
                initial_ammo, initial_clip = tuple(gun.ammo), gun.clip
                self.advance_until(scene, lambda: scene.control.automatic_commits == 1)
                self.assertTrue(any(row['facing'] and row['facing']['state'] == 'turning'
                                    for row in scene.trace))
                burst = scene.owner._local_player_burst
                self.assertIsNotNone(burst)
                self.assertEqual(1, burst['committed'])
                trigger_calls = scene.trigger.call_count
                laid_yaw = scene.body.yaw
                for committed in (2, 3):
                    scene.step()
                    self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
                    self.assertAlmostEqual(laid_yaw, scene.body.yaw)
                    self.assertEqual(trigger_calls, scene.trigger.call_count)
                    self.assertIs(gun, scene.owner._gun_state)
                    self.assertEqual(0, gun.shot_index)
                    self.assertIsNone(gun.pending_index)
                    self.assertTrue(scene.owner._advance_local_player_burst(),
                                    scene.control.fire_admission.receipt)
                    self.assertEqual(committed, scene.control.automatic_commits)
                self.assertIsNone(scene.owner._local_player_burst)
                self.assertEqual(initial_ammo[0]-3, gun.ammo[0])
                self.assertEqual(initial_ammo[1:], tuple(gun.ammo[1:]))
                self.assertEqual(initial_clip-3, gun.clip)
                launches = sorted(scene.owner._projectile_meta.values(),
                                  key=lambda row: row['shot_seq'])
                self.assertEqual([0, 1, 2], [row['burst_index'] for row in launches])
                self.assertEqual([0, 0, 0], [row['shell_index'] for row in launches])
                self.assertEqual(1, len({row['burst_group_seq'] for row in launches}))

    def test_target_replacement_during_rotation_query_cannot_publish_old_turn(self):
        scene = MovingTraverseScene(self)
        original = scene.target
        replaced = []
        def replace_during_native_query(*unused):
            replacement = scene.native.vehicle(original.id, (-80., 0., 60.), team=2)
            scene.records[original.id] = replacement
            replaced.append(replacement)
            return True
        scene.control.rotation_clear.side_effect = replace_during_native_query
        self.advance_until(scene, lambda: bool(replaced))
        self.assertIs(scene.owner._server_entity(original.id), replaced[-1])
        self.assertEqual(0., scene.owner._sender.turn, scene.trace[-1])
        self.assertEqual(0., scene.owner._sender.forward)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_pending_geometry_brakes_the_old_turn_until_same_point_is_reproved(self):
        scene = MovingTraverseScene(self)
        self.advance_until(scene, lambda: scene.control.last_order.get(
            'combat_facing', {}).get('state') == 'turning')
        key = scene.control.last_order['combat_facing']['key']
        with mock.patch('gui.mods.offline_lan_0922.player_control.aiming.SEGMENTS_PER_TICK', 0):
            scene.step()
        self.assertTrue(scene.control.direct_engagement.locked_wait)
        self.assertEqual('checking', scene.control.last_order['combat_facing']['state'])
        self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
        scene.step()
        self.assertEqual(key, scene.control.last_order['combat_facing']['key'])
        self.assertEqual('turning', scene.control.last_order['combat_facing']['state'])
        self.assertGreater(scene.owner._sender.turn, 0.)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_world_blocked_candidates_do_not_acquire_capture_hull_owner(self):
        scene = MovingTraverseScene(self)
        scene.native.world = [((-100., -100., 110.), (100., 100., 190.))]
        for unused in range(25):
            scene.step()
        self.assertTrue(scene.native.world_queries)
        self.assertFalse(any(row['facing'] for row in scene.trace))
        self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
        self.assertIsNone(scene.control.hull_alignment.attempt)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_rotation_sweep_requires_all_existing_native_pose_guards(self):
        for blocked in ('static', 'arena', 'turret', 'destructible', 'missing'):
            with self.subTest(blocked=blocked):
                scene = MovingTraverseScene(self)
                owner = scene.owner
                owner._native_world_rotation_is_clear = mock.Mock(return_value=blocked != 'static')
                owner._arena_rotation_is_clear = mock.Mock(return_value=blocked != 'arena')
                owner._turret_pose_is_clear = mock.Mock(return_value=blocked != 'turret')
                owner._destructible_pose_sweep = mock.Mock(return_value=dict(
                    status='clear', requires_commit=blocked == 'destructible'))
                owner._destructibles = types.SimpleNamespace(
                    _vehicle_body_bbox=lambda unused: ((-1., 0., -3.), (1., 2., 3.)))
                if blocked == 'missing':
                    owner._native_world_rotation_is_clear = None
                scene.control.rotation_clear = types.MethodType(
                    type(scene.control).rotation_clear, scene.control)
                self.advance_until(scene, lambda: scene.control.last_order.get(
                    'combat_facing', {}).get('state') == 'blocked')
                self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
                self.assertEqual(0, scene.control.automatic_commits)
                if blocked == 'static':
                    owner._native_world_rotation_is_clear.assert_called_once()
                    self.assertTrue(owner._native_world_rotation_is_clear.call_args.kwargs['include_static'])

    def test_explicit_move_retires_the_limited_hull_owner(self):
        scene = MovingTraverseScene(self)
        self.advance_until(scene, lambda: scene.control.last_order.get(
            'combat_facing', {}).get('state') == 'turning')
        scene.control.navigation.start_mission('hold_position', dict(position=(0., 0., 140.)),
            dict(now=scene.native.now, position=scene.position, speed=0., yaw=scene.body.yaw))
        scene.step()
        self.assertEqual('hold_position', scene.control.navigation.mission_status()['action'])
        self.assertIsNone(scene.control.hull_alignment.attempt)
        self.assertNotIn('combat_facing', scene.control.last_order)
        self.assertTrue(scene.owner._sender.forward or scene.owner._sender.turn)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_stop_during_native_rotation_query_cannot_restore_turn_or_source(self):
        scene = MovingTraverseScene(self)
        stopped = []
        def stop_during_native_query(*unused):
            scene.control.stop('test_stop_during_hull_query')
            stopped.append(True)
            return True
        scene.control.rotation_clear.side_effect = stop_during_native_query
        self.advance_until(scene, lambda: bool(stopped))
        self.assertFalse(scene.control.active)
        self.assertIsNone(scene.control.hull_alignment.attempt)
        self.assertIsNone(scene.control.weapon)
        self.assertEqual((0., 0.), scene.trace[-1]['sender'][:2])
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertFalse(scene.owner._projectile_meta)

    def test_descriptor_or_gun_replacement_during_query_retires_old_laying(self):
        for changed in ('descriptor', 'gun'):
            for already_turning in (False, True):
                with self.subTest(changed=changed, already_turning=already_turning):
                    scene = MovingTraverseScene(self)
                    if already_turning:
                        self.advance_until(scene, lambda: scene.control.last_order.get(
                            'combat_facing', {}).get('state') == 'turning')
                        self.assertGreater(scene.owner._sender.turn, 0.)
                    replaced = []
                    def replace_during_native_query(*unused):
                        descriptor = copy.deepcopy(scene.entity.typeDescriptor)
                        descriptor.gun.turretYawLimits = (-.1, .1)
                        if changed == 'descriptor':
                            scene.entity.typeDescriptor = descriptor
                        else:
                            scene.owner._gun_state = gun_mechanics.GunState(descriptor,
                                ammo_layout={101: 20, 102: 10})
                        replaced.append(True)
                        return True
                    scene.control.rotation_clear.side_effect = replace_during_native_query
                    self.advance_until(scene, lambda: bool(replaced))
                    self.assertEqual((0., 0.), scene.trace[-1]['sender'][:2], scene.trace[-1])
                    self.assertEqual(0, scene.control.automatic_commits)

    def test_unchanged_actual_pose_cannot_renew_the_alignment_progress_lease(self):
        scene = MovingTraverseScene(self)
        self.advance_until(scene, lambda: scene.control.last_order.get(
            'combat_facing', {}).get('state') == 'turning')
        acquired = scene.native.now
        # A clear proposed turn is not observed movement. Keep the native
        # body fixed while the controller keeps requesting a turn.
        scene.rate = 0.
        self.advance_until(scene, lambda: scene.control.last_order.get(
            'combat_facing', {}).get('state') == 'stalled', limit=30)
        receipt = scene.control.last_order['combat_facing']
        self.assertGreaterEqual(receipt['progress_age'], 2.4)
        self.assertLess(scene.native.now-acquired, 2.6)
        self.assertEqual((0., 0., True), scene.trace[-1]['sender'])
        self.assertIsNone(scene.control.hull_alignment.attempt)
        self.assertTrue(scene.control.aiming.comparison_deferrals)
        self.assertEqual(0, scene.control.automatic_commits)


if __name__ == '__main__':
    unittest.main()
