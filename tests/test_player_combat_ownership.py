"""Shared combat admission preserves physical and navigation boundaries.

Regressions for the 2026-11-08 AMX AC mle. 48 / STB-1 reports.  The worlds
below deliberately separate a visible enemy from a locally shootable enemy.
They execute PlayerControl, FullPlayerRuntime, the shared BotPlanner/driver,
NativeAttackEvaluator and native trigger admission. Ordinary strategy hints
retain the route; the shared native combat task separately admits movement.
Only native terrain,
poses, component armour and collision observations are fixtures.  In
particular, neither the planner order nor an AttackPolicy decision is mocked.

These are deterministic control-loop tests, not a Windows physics play test.
"""
import copy
import math
from types import SimpleNamespace
import unittest
from unittest import mock

from test_player_fire_admission_complete import (
    AutomaticFireScene, PlayerControl, f, gun_mechanics, shot_geometry)


NAVIGATION_FIELDS = (
    'combat_mode', 'target_id', 'target_kind', 'move_position',
    'face_position', 'aim_position', 'throttle_override', 'fire_allowed',
    'route_id', 'route_index', 'route_anchor', 'route_join', 'parking_phase')
POINT_FIELDS = ('move_position', 'face_position', 'aim_position', 'route_anchor')


def navigation_view(order):
    """The copied wire consumer only converts x/y/z objects into tuples."""
    result = dict((key, copy.deepcopy(order.get(key))) for key in NAVIGATION_FIELDS)
    for key in POINT_FIELDS:
        value = result[key]
        if isinstance(value, dict):
            result[key] = tuple(float(value[axis]) for axis in ('x', 'y', 'z'))
        elif value is not None:
            result[key] = tuple(value)
    return result


def initial_hint(order):
    """A strategic candidate is deliberately not the execution target."""
    hint = order.get('initial_target_hint') or {}
    return hint.get('target_kind'), hint.get('target_id')


class OwnershipScene(AutomaticFireScene):
    def lay(self, *args, **kwargs):
        """Do not preselect fixture42 before the original planner admits it.

        AutomaticFireScene primes a native point for its low-level firing
        tests.  Ownership tests deliberately start from an unselected task,
        hide42 and build a fresh controller in configure; they must not use
        that shortcut.  Real aiming is exercised only by tick's full loop.
        """
        return None

    def configure(self, features=('drive', 'fire'), limited=False, clip=6, burst=3,
                  player_id=1):
        self.control.close()
        if player_id != self.battle.client.player_id:
            # Player identity is an ordinary session input. Keep the native
            # record and planner identity together when testing another owner.
            record = self.battle._records.pop('player:%s' % self.battle.client.player_id)
            record['network_id'] = record['state']['id'] = player_id
            self.battle.client.player_id = player_id
            self.battle._records['player:%s' % player_id] = record
        self.battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        # An actual off-origin capture circle avoids the unrelated synthetic
        # arena fallback treating the spawn point itself as the enemy base.
        self.battle._spawn_planner = SimpleNamespace(capture_bases={
            '1': [dict(x=0., z=-45., radius=6.)],
            '2': [dict(x=45., z=45., radius=6.)]})
        name = ('france:F36_AMX_AC_Mle1948' if limited else 'japan:J16_ST_B1')
        descriptor = self.entity.typeDescriptor
        descriptor.name = descriptor.type.name = name
        descriptor.type.tags = ('AT-SPG',) if limited else ('mediumTank',)
        if limited:
            descriptor.gun.turretYawLimits = (-.15, .15)
        descriptor.gun.clip = (clip, .5)
        descriptor.gun.burst = (burst, .1)
        self.battle._gun_state = gun_mechanics.GunState(
            descriptor, ammo_layout={101: 20, 102: 10})
        self.battle._gun_state.reload_time = 0.
        self.battle._gun_state.clip = clip
        self.battle._records['player:%s' % player_id]['vehicle'] = name
        self.battle._records['bot:42']['spot_visible'] = False
        self.control = PlayerControl(self.battle, features, notify=lambda text: None)
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: True
        self.control.gateway.emit = self.control.emit_result
        self.battle._player_control = self.control
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime = self.control.runtime
        self.admission = self.control._admission()
        # The route is supplied through the same public manifest seam as the
        # current map catalogue, not injected as a planner output.
        self.runtime.state['route'] = dict(id='class_mt_rim_east',
            waypoints=[(0., 0., False), (30., 20., False), (40., 40., False)],
            capacity=4, role_weights=dict(frontline=1.))
        self.world_queries[:] = []
        return self

    def obstructed_enemy(self, identity=2):
        target = self.vehicle(identity, (-30., 0., -30.), team=2)
        self.world[:] = [((-35., -20., -25.), (-5., 20., -5.))]
        return target

    def eligible_enemy(self, identity=5, armor=10.):
        target = self.vehicle(identity, (20., 0., 40.), team=2)
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(target.typeDescriptor, component).materials[0].armor = armor
        return target

    def sample_original_lanes(self):
        """Run the original physical lane query; do not fabricate receipts."""
        self.observe()
        return dict((target['network_id'], self.runtime.engine._shot_clear(
            self.runtime.state, target, self.now, force=True))
            for target in self.runtime._targets)

    def original_order(self):
        return next(row for row in self.runtime._strategic_result['orders']
                    if row['id'] == self.runtime.actor_id)

    def applied_order(self):
        return self.runtime.engine._server_orders[self.runtime.actor_id]

    def native_position(self, point, yaw=0.):
        self.body.setRotateYPR((yaw, 0., 0.))
        self.body.translation = point
        self.battle._local_matrix = self.battle._local_pose_matrix = self.body
        self.battle._local_position = point
        self.battle._local_yaw = yaw
        self.entity.matrix = self.body
        self.entity.position = f._Vector(point)
        self.origin = (point[0], point[1] + 2., point[2])

    def tick(self, seconds=.1):
        self.fixture.now += seconds
        rotator = self.battle._avatar.gunRotator
        source = rotator.shotPointSourceFunctor
        if callable(source) and source() is not None:
            yaw, pitch = self.get_angles(self.entity.typeDescriptor, self.body,
                (rotator.turretYaw, rotator.gunPitch), source())
            # Native actuator observation consumes the real installed aim
            # source; the authorization/readiness checks are not replaced.
            rotator.turretYaw, rotator.gunPitch = yaw, pitch
            self.direction = shot_geometry.transform_vehicle_vector(
                (math.sin(yaw) * math.cos(pitch), -math.sin(pitch),
                 math.cos(yaw) * math.cos(pitch)),
                self.body.yaw, self.body.pitch, self.body.roll)
        self.battle._last_frame_time = self.now
        self.control.update(seconds, self.now)
        self.assertIsNone(self.control.last_control_failure)
        self.assertTrue(self.runtime.active)
        return self.applied_order()


class OriginalCombatOwnershipTests(unittest.TestCase):
    def scene(self, features=('drive', 'fire'), limited=False, clip=6, burst=3,
              player_id=1):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure(features, limited, clip, burst, player_id)

    def assert_original_navigation(self, scene):
        original = navigation_view(scene.original_order())
        actual = navigation_view(scene.applied_order())
        self.assertEqual(original, actual)
        self.assertEqual('class_mt_rim_east', actual['route_id'])

    def assert_route_hint(self, scene, identity):
        order = scene.original_order()
        self.assertEqual('route', order['combat_mode'])
        self.assertIsNone(order.get('target_id'))
        self.assertIsNone(order.get('target_kind'))
        self.assertEqual(('bot', identity), initial_hint(order))
        self.assertEqual('class_mt_rim_east', order['route_id'])

    def test_visible_blocked_contact_enters_shared_review_without_fire_authority(self):
        for limited in (False, True):
            with self.subTest(limited=limited):
                scene = self.scene(limited=limited)
                try:
                    scene.obstructed_enemy()
                    self.assertEqual({2: False}, scene.sample_original_lanes())
                    for step in range(12):
                        scene.native_position((.3 * step, 0., .2 * step))
                        scene.tick()
                        raw = scene.original_order()
                        selection = raw['tactical_evidence']['selection']
                        self.assertEqual('evaluation_pending', selection['outcome'])
                        self.assertEqual('initial_distance_armor', selection['selection_law'])
                        self.assertEqual('eligible', selection['candidates'][0]['reason'])
                        self.assertFalse(selection['candidates'][0]['local_lane'])
                        self.assert_route_hint(scene, 2)
                        owner = scene.runtime.combat_stop
                        if owner.stop_allowed:
                            self.assertTrue(owner.combat_owned)
                            self.assertEqual(2, scene.applied_order()['target_id'])
                            self.assertIn(scene.applied_order()['combat_mode'],
                                          ('engage', 'gun_angle_adjust'))
                            self.assertTrue(owner.physical_recovery_active())
                        else:
                            self.assert_original_navigation(scene)
                        self.assertEqual((2,), tuple(row['network_id'] for row in
                            scene.runtime.combat_targets()))
                        self.assertEqual('class_mt_rim_east', scene.applied_order()['route_id'])
                        self.assertFalse(scene.applied_order()['fire_allowed'])
                        self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
                        self.assertFalse(scene.launches())
                finally:
                    scene.doCleanups()

    def test_no_visible_enemy_retains_authored_route_without_combat_braking(self):
        scene = self.scene()
        for step in range(12):
            scene.native_position((.3 * step, 0., .2 * step))
            scene.tick()
            self.assertFalse(scene.runtime.visible_targets())
            self.assertEqual('route', scene.original_order()['combat_mode'])
            self.assert_original_navigation(scene)
            self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
            self.assertFalse(scene.launches())

    def test_visible_blocked_contact_reaches_point_validation_not_armour_failure_search(self):
        scene = self.scene()
        scene.obstructed_enemy()
        self.assertEqual({2: False}, scene.sample_original_lanes())
        evaluator = scene.runtime.attack_policy.evaluator
        checked_proposals = 0
        with mock.patch.object(evaluator, 'evaluate', wraps=evaluator.evaluate) as evaluate:
            for step in range(15):
                scene.native_position((.4 * step, 0., .25 * step))
                scene.tick()
                self.assert_route_hint(scene, 2)
                if scene.runtime.combat_stop.stop_allowed:
                    self.assertTrue(scene.runtime.combat_stop.physical_recovery_active())
                    self.assertEqual(2, scene.applied_order()['target_id'])
                else:
                    self.assert_original_navigation(scene)
                self.assertFalse(scene.applied_order()['fire_allowed'])
                self.assertFalse(scene.launches())
                decision = scene.runtime.attack_policy.decision
                if decision['action'] == 'firing_position':
                    self.assertEqual('world_blocked', decision['candidate']['line'])
                    checked_proposals += 1
            # Native line obstruction is now a shared point-review input,
            # not an old strategic exclusion or a penetration failure.
            self.assertGreater(evaluate.call_count, 0)
        self.assertGreater(checked_proposals, 0,
            'source-position refresh must not restart the finite inspection forever')
        self.assertIn(scene.runtime.attack_policy.decision['action'], ('wait', 'firing_position'))
        self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))

    def test_enabling_fire_keeps_route_until_same_point_recovery_is_checked(self):
        traces = []
        for features in (('drive',), ('drive', 'fire')):
            scene = self.scene(features=features)
            try:
                scene.obstructed_enemy()
                self.assertEqual({2: False}, scene.sample_original_lanes())
                trace = []
                for step in range(15):
                    # Identical externally observed poses make a drive-output
                    # comparison independent of a fabricated physics solver.
                    scene.native_position((.4 * step, 0., .25 * step), .35)
                    scene.tick()
                    sender = scene.battle._sender
                    movement = navigation_view(scene.applied_order())
                    movement.pop('aim_position')
                    trace.append((movement,
                        sender.forward, sender.turn, sender.handbrake))
                traces.append(trace)
            finally:
                scene.doCleanups()
        self.assertEqual(traces[0], traces[1],
            'checking a blocked point cannot stop or steer a route-owned hull')
        self.assertTrue(all(row[0]['combat_mode'] == 'route' for row in traces[0]))
        self.assertTrue(all(row[0]['combat_mode'] == 'route' for row in traces[1]))
        self.assertTrue(any(row[1] or row[2] for row in traces[0]),
                        'baseline must actually operate the drive actuator')

    def test_nearest_blocked_contact_and_armored_alternative_share_one_review_domain(self):
        scene = self.scene()
        scene.obstructed_enemy(2)
        scene.eligible_enemy(5, armor=10000.)
        self.assertEqual({2: False, 5: True}, scene.sample_original_lanes())
        for unused in range(12):
            scene.tick()
            raw = scene.original_order()
            self.assert_route_hint(scene, 2)
            candidates = dict((row['target'][1], row) for row in
                              raw['tactical_evidence']['selection']['candidates'])
            self.assertEqual('eligible', candidates[5]['reason'])
            self.assertEqual('eligible', candidates[2]['reason'])
            self.assertTrue(candidates[5]['local_lane'])
            self.assertFalse(candidates[2]['local_lane'])
            self.assertEqual({2, 5}, set(row['network_id'] for row in
                scene.runtime.combat_targets()))
            if scene.runtime.combat_stop.stop_allowed:
                self.assertEqual(2, scene.applied_order()['target_id'])
                self.assertTrue(scene.runtime.combat_stop.physical_recovery_active())
            else:
                self.assertIsNone(scene.applied_order().get('target_id'))
                self.assert_original_navigation(scene)
            candidate = scene.runtime.attack_policy.decision.get('candidate')
            if candidate is not None:
                self.assertEqual(2, candidate['target']['network_id'])
                self.assertNotEqual('passed', candidate['armor'])
            self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'),
                'a blocked unknown contact prevents an all-enemies armour failure')
            self.assertFalse(scene.applied_order()['fire_allowed'])
            self.assertFalse(scene.launches())
        self.assertTrue(any(row['target']['network_id'] == 5 and row['armor'] == 'failed'
                            for row in scene.runtime.attack_policy.rows.values()))

    def test_role_range_cannot_prevent_native_selection_and_launch_of_another_contact(self):
        scene = self.scene()
        harder = scene.eligible_enemy(5, armor=10000.)
        # Both enemies exceed the old 340m role value but are within the
        # mounted projectile's actual 500m reach. The macro hint stays nearest;
        # only native armour/path proof can choose the executed gun target.
        scene.pose(harder, (0., 0., 360.))
        softer = scene.eligible_enemy(2, armor=10.)
        scene.pose(softer, (40., 0., 380.))
        self.assertEqual({5: True, 2: True}, scene.sample_original_lanes())
        alternative_reviewed = False
        for unused in range(60):
            scene.tick()
            raw = scene.original_order()
            self.assert_route_hint(scene, 5)
            self.assertGreater(360., raw['fire_range'])
            self.assertEqual({2, 5}, set(row['target'][1] for row in
                raw['tactical_evidence']['selection']['candidates']
                if row['reason'] == 'eligible'))
            self.assertTrue(scene.runtime.combat_stop.active)
            self.assertEqual(raw['route_id'], scene.applied_order()['route_id'])
            self.assertEqual(raw['route_index'], scene.applied_order()['route_index'])
            policy = scene.runtime.attack_policy
            candidates = [row for row in policy.rows.values()
                if row['target']['network_id'] == 2 and row.get('armor') == 'passed'
                and row.get('line') == 'clear']
            if candidates:
                alternative_reviewed = True
                self.assertTrue(policy._executable_current(candidates[0]))
                self.assertTrue(scene.runtime.combat_stop.stop_allowed)
                self.assertEqual(2, scene.applied_order()['target_id'])
                self.assertEqual(500., scene.applied_order()['fire_range'])
            if scene.launches():
                break
        self.assertTrue(alternative_reviewed)
        self.assertTrue(scene.launches())
        self.assertEqual(1, len(scene.launches()))

    def test_original_clear_lane_can_still_enter_combat_and_launch_a_projectile(self):
        scene = self.scene()
        scene.eligible_enemy(5)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        for unused in range(80):
            scene.tick()
            if scene.launches():
                break
        raw = scene.original_order()
        self.assert_route_hint(scene, 5)
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual(5, scene.applied_order().get('target_id'))
        self.assertEqual(0., scene.applied_order().get('throttle_override'))

    def test_original_lane_observation_can_acquire_combat_without_policy_bootstrap(self):
        scene = self.scene()
        scene.eligible_enemy(5)
        # No primed cache, candidate, forced policy aim, or synthetic planner
        # order. Native point review must eventually admit the combat task.
        admitted = False
        for unused in range(100):
            scene.tick()
            raw = scene.original_order()
            self.assert_route_hint(scene, 5)
            if not scene.runtime.combat_stop.combat_owned:
                self.assert_original_navigation(scene)
            elif scene.applied_order().get('target_id') == 5:
                admitted = True
            if scene.launches():
                break
        self.assertTrue(admitted, 'gating must not deadlock original lane acquisition')
        self.assertTrue(scene.launches(), scene.runtime.status())

    def test_admitted_current_he_clip_retains_legal_fallback_and_native_launch(self):
        scene = self.scene()
        scene.eligible_enemy(5, armor=30.)
        scene.set_he(piercing=1.)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        saw_fallback = False
        for unused in range(80):
            scene.tick()
            raw = scene.original_order()
            self.assert_route_hint(scene, 5)
            policy = scene.runtime.attack_policy
            self.assertFalse(hasattr(policy, 'search_started'),
                'an already loaded HE clip does not need the eight-second gate')
            candidate = policy.decision.get('candidate')
            if candidate and candidate.get('mode') == 'he_fallback':
                saw_fallback = True
                self.assertIn(policy.decision['reason'],
                    ('current_he_fallback_contact', 'current_he_clip_fallback',
                     'he_fallback_contact'))
                self.assertEqual(5, candidate['target']['network_id'])
                self.assertGreater(candidate['expected_damage'], 0.)
                self.assertEqual(0., scene.applied_order()['throttle_override'])
            if scene.launches():
                break
        self.assertTrue(saw_fallback, scene.runtime.attack_policy.status())
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual([0], [row['shell_index'] for row in scene.launches()])

    def test_admitted_all_armour_failure_switches_to_he_without_search_delay(self):
        scene = self.scene(clip=1, burst=1)
        scene.eligible_enemy(5, armor=30.)
        gun = scene.battle._gun_state
        for index, shot in enumerate(gun.shots):
            shot.piercingPower = (1., 1.)
            source = scene.battle.client.effective_params['gun']['shots'][index]['source_shot']
            source['piercingPower'] = shot.piercingPower
        gun.shots[1].shell.kind = 'HIGH_EXPLOSIVE'
        gun.shots[1].shell.explosionRadius = 5.
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot']['shell'].update(
            kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        scene.battle._advance_local_gun_to(scene.entity, scene.now)
        began = scene.now
        fallback_at = None
        for unused in range(250):
            scene.battle._advance_local_gun_to(scene.entity, scene.now)
            scene.tick()
            policy = scene.runtime.attack_policy
            self.assertFalse(hasattr(policy, 'search_started'))
            candidate = policy.decision.get('candidate')
            if candidate and candidate.get('mode') == 'he_fallback':
                if fallback_at is None:
                    fallback_at = scene.now
                self.assertEqual(5, candidate['target']['network_id'])
            if scene.launches():
                break
        self.assertIsNotNone(fallback_at, scene.runtime.attack_policy.status())
        self.assertLess(fallback_at - began, 8.)
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual([1], [row['shell_index'] for row in scene.launches()])

    def test_observed_health_changes_do_not_reorder_domain_or_delay_he_fallback(self):
        scene = self.scene(clip=1, burst=1)
        primary = scene.eligible_enemy(5, armor=30.)
        primary.health = 50
        second = scene.eligible_enemy(2, armor=30.)
        scene.pose(second, (-25., 0., 40.))
        second.health = 400
        third = scene.eligible_enemy(6, armor=30.)
        scene.pose(third, (30., 0., 35.))
        third.health = 450
        gun = scene.battle._gun_state
        for index, shot in enumerate(gun.shots):
            shot.piercingPower = (1., 1.)
            scene.battle.client.effective_params['gun']['shots'][index]['source_shot'][
                'piercingPower'] = shot.piercingPower
        gun.shots[1].shell.kind = 'HIGH_EXPLOSIVE'
        gun.shots[1].shell.explosionRadius = 5.
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot']['shell'].update(
            kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        self.assertEqual({5: True, 2: True, 6: True}, scene.sample_original_lanes())
        began = scene.now
        fallback_at = None
        ranks = set()
        for step in range(180):
            if step and step % 11 == 0:
                # Observed health must not recreate the removed low-health
                # priority, change membership, or restart the global timer.
                if second.health > third.health:
                    second.health = third.health - 20
                else:
                    third.health = second.health - 20
            scene.battle._advance_local_gun_to(scene.entity, scene.now)
            scene.tick()
            raw = scene.original_order()
            self.assert_route_hint(scene, 5)
            self.assertEqual({2, 5, 6}, set(row['target'][1] for row in
                raw['tactical_evidence']['selection']['candidates']
                if row['reason'] == 'eligible'))
            rank = tuple(target['network_id'] for target in scene.runtime.combat_targets())
            self.assertEqual(5, rank[0])
            ranks.add(rank)
            policy = scene.runtime.attack_policy
            self.assertFalse(hasattr(policy, 'search_started'))
            candidate = policy.decision.get('candidate')
            if candidate and candidate.get('mode') == 'he_fallback' and fallback_at is None:
                fallback_at = scene.now
            if scene.launches():
                break
        self.assertEqual({(5, 6, 2)}, ranks)
        self.assertIsNotNone(fallback_at, scene.runtime.attack_policy.status())
        self.assertLess(fallback_at - began, 8.)
        self.assertTrue(scene.launches(), scene.runtime.status())
        self.assertEqual([1], [row['shell_index'] for row in scene.launches()])

    def test_late_siege_motion_matches_the_driver_contact_even_when_its_lane_is_blocked(self):
        from test_player_siege_engagement import SiegeScene
        scene = SiegeScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(enabled=True)
        scene.target.health = 1
        scene.vehicle(7, (25., 12., 90.), team=2)
        scene.observe()
        lanes = dict((target['network_id'], scene.runtime.engine._shot_clear(
            scene.runtime.state, target, scene.now, force=True))
            for target in scene.runtime.visible_targets())
        self.assertEqual({42: True, 7: True}, lanes)
        scene.runtime._strategic_due = 0.
        motion = None
        for unused in range(25):
            scene.tick(actuate=False)
            motion = scene.runtime.siege_aim_candidate()
            if motion is not None:
                break
        self.assertIsNotNone(motion, scene.trace[-3:])
        self.assertEqual(42, motion['target']['network_id'])
        self.assertTrue(motion['solution']['needs_hydraulic'])
        self.assertFalse(motion['solution']['source_verified'])
        self.assertEqual({42, 7}, set(target['network_id']
                                    for target in scene.runtime.combat_targets()))
        runtime, engine = scene.runtime, scene.runtime.engine
        # The late mechanical consumer receives the post-policy execution
        # order, not the independent initial macro hint.
        raw = engine._server_orders[runtime.actor_id]
        self.assertEqual(42, raw['target_id'])

        # Exercise the late consumer's incoming driver-contact contract.
        # Both enemies were admitted by the real planner; a motion point
        # already computed for42 still cannot replace this frame's7 or None.
        # Native hydraulics, the policy and the copied blocked-lane law are
        # all real. No fake candidate or passed armour/line proof is used.
        other = next(target for target in runtime.combat_targets()
                     if target['network_id'] == 7)
        command = dict(raw, target_kind='bot', target_id=7,
            face_position=other['position'], aim_position=other['position'],
            fire_allowed=False)
        result, target = engine._apply_blocked_direct_aim(
            runtime.state, command, other, scene.now)
        self.assertEqual(7, result['target_id'])
        self.assertEqual(other['position'], result['face_position'])
        self.assertIsNone(result['aim_position'])
        self.assertFalse(result.get('_player_motion_only'))
        self.assertIsNone(target)
        self.assertFalse(result['fire_allowed'])
        result, target = engine._apply_blocked_direct_aim(runtime.state,
            dict(raw, target_kind=None, target_id=None, aim_position=None),
            None, scene.now)
        self.assertIsNone(target)
        self.assertIsNone(result['aim_position'])
        self.assertFalse(result.get('_player_motion_only'))
        self.assertFalse(result['fire_allowed'])

        # A real new wall receipt blocks fire, not the already selected
        # same-target hydraulic input. This must not be fixed by globally
        # disabling the motion-only path whenever the original gun refuses.
        selected = next(target for target in runtime.combat_targets()
                        if target['network_id'] == 42)
        scene.world[:] = [((-5., -20., 45.), (5., 30., 55.))]
        self.assertFalse(engine._shot_clear(runtime.state, selected, scene.now, force=True))
        result, target = engine._apply_blocked_direct_aim(
            runtime.state, dict(raw), selected, scene.now)
        self.assertEqual('current_lane_blocked',
                         runtime.state['_target_execution_evidence']['reason'])
        self.assertEqual(42, target['network_id'])
        self.assertEqual(42, result['target_id'])
        self.assertEqual(motion['solution']['point'], result['aim_position'])
        self.assertTrue(result['_player_motion_only'])
        self.assertFalse(result['fire_allowed'])
        self.assertFalse(scene.launches())

    def test_genuine_combat_stop_uses_checked_same_point_friendly_recovery(self):
        scene = self.scene()
        scene.eligible_enemy(5)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        scene.tick()
        self.assert_route_hint(scene, 5)
        self.assertEqual(('engage', 5), (scene.applied_order()['combat_mode'],
                                        scene.applied_order()['target_id']))
        self.assertEqual(0., scene.applied_order()['throttle_override'])
        friend = scene.vehicle(3, (10., 0., 20.), team=1)
        engine = scene.runtime.engine
        with mock.patch.object(scene.runtime, 'point_recovery_probe',
                wraps=scene.runtime.point_recovery_probe) as checked_recovery:
            for unused in range(12):
                scene.tick()
                phase = scene.runtime.combat_stop._physical_recovery
                if phase is not None and phase.get('goal') is not None:
                    break
            self.assertTrue(checked_recovery.called)
        self.assertEqual('firing_position', scene.runtime.attack_policy.decision['action'])
        self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'),
                          'a blocked lane is not an all-enemies armour failure')
        marker = scene.runtime.combat_stop._physical_recovery
        self.assertIsNotNone(marker)
        self.assertEqual(('bot', 5), marker['target'])
        self.assertEqual('friendly_blocked', marker['candidate']['line'])
        self.assertEqual(scene.runtime.attack_policy.decision['candidate']['key'], marker['key'])
        self.assertIsNotNone(marker['goal'])
        self.assertNotEqual((0., 0., 0.), marker['goal'])
        self.assertTrue(all(call.args[0]['key'] == marker['key']
                            for call in checked_recovery.call_args_list))
        self.assertFalse(hasattr(engine, '_friendly_repositions'))
        self.assertFalse(hasattr(engine, '_friendly_reposition_order'))
        command = scene.control.last_order
        self.assertEqual('gun_angle_adjust', command['combat_mode'])
        self.assertEqual(marker['goal'], command['move_position'])
        self.assertTrue(command['movement_intent'])
        self.assertFalse(command['fire_allowed'])
        self.assertFalse(scene.launches())
        # Removing the actual blocker makes the same admitted attack return
        # to its own stop.  It must not cancel an unrelated route/hold task.
        scene.pose(friend, (35., 0., 0.))
        for unused in range(12):
            scene.tick()
            if scene.runtime.attack_policy.decision['action'] == 'aim':
                break
        self.assertEqual('aim', scene.runtime.attack_policy.decision['action'])
        phase = scene.runtime.combat_stop._physical_recovery
        self.assertTrue(phase is None or phase.get('ready'), phase)
        self.assertEqual(0., scene.applied_order()['throttle_override'])
        self.assertEqual(5, scene.applied_order()['target_id'])

    def test_hold_and_capture_stops_keep_navigation_control_with_blocked_enemy(self):
        for mission, point in (
                ('hold_position', (0., 0., 0.)),
                ('capture_base', (45., 0., 45.))):
            with self.subTest(mission=mission):
                traces = []
                for features in (('drive',), ('drive', 'fire')):
                    scene = self.scene(features=features)
                    try:
                        scene.obstructed_enemy()
                        scene.native_position(point)
                        self.assertEqual({2: False}, scene.sample_original_lanes())
                        scene.runtime.set_mission(mission, {})
                        trace = []
                        for unused in range(10):
                            scene.tick()
                            order = scene.applied_order()
                            self.assertEqual('hold' if mission == 'hold_position' else
                                             'base_capture', order['combat_mode'])
                            if 'fire' not in features:
                                self.assertIsNone(order.get('target_id'))
                            else:
                                self.assertIn(order.get('target_id'), (None, 2))
                            self.assertEqual(point, order['move_position'])
                            self.assertEqual(0., order['throttle_override'])
                            self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
                            self.assertFalse(scene.runtime.combat_stop.stop_allowed)
                            self.assertFalse(order['fire_allowed'])
                            self.assertFalse(scene.launches())
                            sender = scene.battle._sender
                            movement = navigation_view(order)
                            movement.pop('aim_position')
                            movement.pop('target_id', None)
                            movement.pop('target_kind', None)
                            movement.pop('face_position', None)
                            trace.append((movement, sender.forward,
                                          sender.turn, sender.handbrake))
                        traces.append(trace)
                    finally:
                        scene.doCleanups()
                self.assertEqual(traces[0], traces[1])
                self.assertTrue(all(row[1] == 0. for row in traces[0]))

    def test_base_return_keeps_original_travel_control_with_visible_enemy(self):
        traces = []
        for features in (('drive',), ('drive', 'fire')):
            scene = self.scene(features=features)
            try:
                scene.eligible_enemy(5)
                self.assertEqual({5: True}, scene.sample_original_lanes())
                scene.runtime.set_mission('return_base', {})
                trace = []
                for step in range(15):
                    scene.native_position((0., 0., -.5 * step), math.pi)
                    scene.tick()
                    order = scene.applied_order()
                    self.assertEqual('team_return_base', order['combat_mode'])
                    self.assertEqual((0., 0., -45.), order['move_position'])
                    self.assertIsNone(order.get('throttle_override'))
                    self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
                    sender = scene.battle._sender
                    trace.append((navigation_view(order), sender.forward,
                                  sender.turn, sender.handbrake))
                traces.append(trace)
            finally:
                scene.doCleanups()
        self.assertEqual(traces[0], traces[1])

    def test_lost_enemy_releases_combat_to_original_route_not_old_firing_point(self):
        scene = self.scene()
        scene.eligible_enemy(5)
        self.assertEqual({5: True}, scene.sample_original_lanes())
        scene.tick()
        self.assert_route_hint(scene, 5)
        self.assertTrue(scene.runtime.combat_stop.combat_owned)
        scene.battle._records['bot:5']['spot_visible'] = False
        resumed = False
        for step in range(15):
            scene.native_position((.4 * step, 0., .25 * step))
            scene.tick()
            if not scene.runtime.combat_stop.active:
                resumed = True
                self.assert_original_navigation(scene)
                self.assertIsNone(scene.applied_order().get('target_id'))
                self.assertFalse(hasattr(scene.runtime.attack_policy, 'search_started'))
        self.assertTrue(resumed, 'original planner must resume its route after the contact expires')


if __name__ == '__main__':
    unittest.main()
