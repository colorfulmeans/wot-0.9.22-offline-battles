"""Replay the observed 141918 reload/face conflict through production control.

Evidence: report SHA256 f41ee02b4ffef147cc787cded6514a7b6be1e21e9d28277431d3cc0a26bbb052,
build colorfulmeans-42567988322-1 (59930fcc). Visible-client lines 11536-12491
show actor 1000001 / STB-1 at (-36.915, .261, -82.059), target14 at
(-6., .25, -98.), alternating assigned/-23.7-degree face and
movement_lease/direct face across three HE shot/reload cycles. Actor10 is the
dead KV-2 at (-30., .25, -98.); earlier native rays really hit this wreck.

This is a reduced control regression, not a complete BigWorld replay. Native
poses, actuator observations, support, and component boxes are analytic
fixtures. The blocker is moved across the shot lane as a controlled perturbation
and returned to its reported location; the report does not say it moved there.
PlayerControl, common strategy/driver, AttackPolicy, NativeAttackEvaluator,
TriggerAdmission, battle.shoot, and GunState reload/debit are production code.
No order, policy decision, ready gate, or launch result is prescribed by a mock.
"""
import contextlib
import copy
import io
import math
import unittest

from test_player_combat_ownership import OwnershipScene
from test_player_fire_admission_complete import PlayerControl, f, gun_mechanics


SOURCE_POSITION = (-36.9152523505638, .26000010305917853, -82.05887457205792)
TARGET_POSITION = (-6., .25, -98.)
WRECK_POSITION = (-30., .25, -98.)
ROUTE_ID = 'class_mt_rim_west'
REPORT_RELOAD_SECONDS = 6.372287170252084


def point(value):
    if isinstance(value, dict):
        return tuple(value[axis] for axis in ('x', 'y', 'z'))
    return tuple(value)


def angle(value):
    return (value + math.pi) % (2. * math.pi) - math.pi


class Report141918Scene(OwnershipScene):
    def configure_report(self, extra_contacts=()):
        # Expand only the analytic support graph so the original report's
        # negative coordinates can be retained without translating the scene.
        graph = self.battle._navigation_graph
        graph.update(origin=(-120., -120.), bounds=(-124., -124., 124., 124.),
                     cell_size=8., map='100_thepit')
        self.battle._arena_bounds = graph['bounds']
        self.battle._start_message['map'] = '100_thepit'
        self.configure(clip=1, burst=1)
        self.source_yaw = math.atan2(TARGET_POSITION[0] - SOURCE_POSITION[0],
                                     TARGET_POSITION[2] - SOURCE_POSITION[2])
        self.native_position(SOURCE_POSITION, self.source_yaw)
        # Real three-slot GunState: AP/APCR are empty, slot2 is ordinary HE.
        descriptor = self.entity.typeDescriptor
        descriptor.gun.reloadTime = REPORT_RELOAD_SECONDS
        third = copy.deepcopy(descriptor.gun.shots[0])
        third.shell.compactDescr = 103
        third.shell.kind = 'HIGH_EXPLOSIVE'
        third.shell.explosionRadius = 5.
        third.piercingPower = (1., 1.)
        descriptor.gun.shots = list(descriptor.gun.shots[:2]) + [third]
        descriptor.activeGunShotIndex = 2
        params = self.battle.client.effective_params
        params['ammo'] = [[101, 0], [102, 0], [103, 10]]
        source = copy.deepcopy(params['gun']['shots'][0])
        source['compact_descr'] = 103
        source['source_shot']['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        source['source_shot']['piercingPower'] = (1., 1.)
        params['gun']['shots'] = list(params['gun']['shots'][:2]) + [source]
        self.battle._gun_state = gun_mechanics.GunState(descriptor,
            ammo_layout={101: 0, 102: 0, 103: 10})
        self.battle._gun_state.reload_time = 0.
        self.battle._gun_state.clip = 1
        self.battle._gun_last_tick = self.now
        self.reload_completions = []
        gun = self.battle._gun_state
        native_tick = gun.tick

        def observe_native_tick(*args, **kwargs):
            before = gun.reload_time
            result = native_tick(*args, **kwargs)
            if before > 0. and gun.reload_time <= 0. and gun.clip > 0:
                self.reload_completions.append((self.now, len(self.launches()), gun.clip))
            return result

        # Observe the real completion even if a native fire callback advances
        # the gun before the outer control tick. No clock/result is replaced.
        gun.tick = observe_native_tick

        self.target = self.vehicle(14, TARGET_POSITION, team=2)
        self.target.typeDescriptor.name = 'germany:G98_Waffentrager_E100_P'
        for component in ('chassis', 'hull', 'turret', 'gun'):
            getattr(self.target.typeDescriptor, component).materials[0].armor = 30.
        for identity, position, armour in extra_contacts:
            other = self.vehicle(identity, position, team=2)
            for component in ('chassis', 'hull', 'turret', 'gun'):
                getattr(other.typeDescriptor, component).materials[0].armor = armour

        # Network actor10 is the wreck; engine id1010 avoids colliding with
        # this native boundary fixture's local player entity id10.
        self.wreck = self.vehicle(1010, WRECK_POSITION, team=2)
        self.wreck.typeDescriptor.name = 'ussr:R77_KV2'
        record = self.battle._records.pop('bot:1010')
        record.update(network_id=10, native_remote=True)
        record['state'].update(id=10, alive=False, health=0)
        self.battle._records['bot:10'] = record
        self.wreck.health = 0
        self.wreck.typeDescriptor.hull.hitTester.bbox = (
            f._Vector(-1.7, -.2, -3.5), f._Vector(1.7, 2.8, 3.5))
        self.wreck_queries = []
        for component in ('chassis', 'hull', 'turret', 'gun'):
            tester = getattr(self.wreck.typeDescriptor, component).hitTester
            tester.on_hit = lambda name=component: self.wreck_queries.append(name)
        # A control binding belongs to an actual GunState lifetime. Reattach
        # after initial fixture assembly; never spoof its identity fence.
        self.control.close()
        self.control = PlayerControl(self.battle, ('drive', 'fire'), notify=lambda text: None)
        self.control.record = lambda *args, **kwargs: None
        self.control.emit_result = lambda *args, **kwargs: True
        self.control.gateway.emit = self.control.emit_result
        self.battle._player_control = self.control
        self.assertTrue(self.control.toggle(), self.control.last_control_failure)
        self.addCleanup(self.control.close)
        self.runtime = self.control.runtime
        self.admission = self.control._admission()
        self.runtime.state['route'] = dict(id=ROUTE_ID,
            waypoints=[(SOURCE_POSITION[0], SOURCE_POSITION[2], False),
                       (-34.68, -100.709, False)], capacity=4,
            role_weights=dict(frontline=1.))
        self.trace = []
        return self

    def block_lane(self, blocked):
        position = (tuple((SOURCE_POSITION[i] + TARGET_POSITION[i]) / 2.
                          for i in range(3)) if blocked else WRECK_POSITION)
        self.pose(self.wreck, position)
        self.fixture.now += .001
        self.observe()
        # Advance the real lane query at this observed geometry change. This
        # does not inject a ready/clear result or replace any collision method.
        return self.sample_original_lanes()

    def step_control(self):
        gun = self.battle._gun_state
        self.battle._advance_local_gun_to(self.entity, self.now)
        native_before = dict(clip=gun.clip, reload=gun.reload_time,
                             ammo=tuple(gun.ammo), shell=gun.shot_index)
        self.tick(.1)
        original, applied = copy.deepcopy(self.original_order()), copy.deepcopy(self.applied_order())
        sender = self.battle._sender
        row = dict(at=self.now, original=original, applied=applied,
                   native_before=native_before, clip=gun.clip, reload=gun.reload_time,
                   ammo=tuple(gun.ammo), shots=len(self.launches()),
                   forward=sender.forward, turn=sender.turn,
                   policy=copy.deepcopy(self.runtime.attack_policy.status()))
        self.trace.append(row)
        return row


class Report141918ControlRegressionTests(unittest.TestCase):
    def scene(self, extra_contacts=()):
        scene = Report141918Scene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure_report(extra_contacts)

    def assert_task_and_domain(self, scene, row):
        for order in (row['original'], row['applied']):
            self.assertEqual(14, order.get('target_id'))
            self.assertEqual(ROUTE_ID, order.get('route_id'))
            self.assertNotIn('hull_angle_degrees', order)
        self.assertEqual((14,), tuple(t['network_id'] for t in scene.runtime.combat_targets()))
        candidate = scene.runtime.attack_policy.decision.get('candidate')
        if candidate is not None:
            self.assertEqual(14, candidate['target']['network_id'])
        self.assertIsNone(scene.runtime.attack_policy.search_started,
            'blocked geometry or already loaded HE must not manufacture eight-second armor failure')
        self.assertFalse(any(domain.get('all_failed') for domain in row['policy']['failure_domains']))
        self.assertEqual(2, scene.battle._gun_state.shot_index)

    def assert_clear_hull_owner(self, scene, row):
        for order in (row['original'], row['applied']):
            if order.get('combat_mode') != 'engage':
                continue
            face = point(order['face_position'])
            dx, dz = face[0] - SOURCE_POSITION[0], face[2] - SOURCE_POSITION[2]
            if math.hypot(dx, dz) < .001:
                # The common pending-review hold explicitly preserves the
                # current body orientation by facing its own position.
                continue
            facing = math.atan2(dx, dz)
            self.assertLess(abs(angle(facing - scene.source_yaw)), .002,
                'reload edge replaced direct target facing with an artificial hull angle')
        self.assertLess(abs(row['turn']), .002,
            'aligned stationary HE control must not alternate positive/negative hull commands')
        self.assertEqual(0., row['forward'])

    def test_three_he_reload_cycles_preserve_hull_owner_and_wreck_evidence(self):
        # stdout carries large production diagnostic records; failures retain
        # the actual policy/order in assertions and do not replace that code.
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.scene()
            route = copy.deepcopy(scene.runtime.state['route'])
            self.assertEqual({14: True}, scene.block_lane(False))
            for unused in range(180):
                row = scene.step_control()
                self.assert_task_and_domain(scene, row)
                self.assert_clear_hull_owner(scene, row)
                if scene.launches():
                    break
            self.assertEqual(1, len(scene.launches()), scene.runtime.status())
            self.assertGreater(scene.battle._gun_state.reload_time, 0.)

            # A real analytic dead hull blocks the live target while the first
            # native reload runs to completion. Hold it longer than eight
            # seconds: no invented negative armor proof or corpse target.
            scene.wreck_queries[:] = []
            scene.block_lane(True)
            for unused in range(95):
                row = scene.step_control()
                self.assert_task_and_domain(scene, row)
                self.assertEqual(1, len(scene.launches()))
            self.assertTrue(scene.wreck_queries, 'actual component collision fixture was not queried')
            self.assertEqual(1, scene.battle._gun_state.clip)
            self.assertEqual(0., scene.battle._gun_state.reload_time)
            self.assertEqual('firing_position', row['policy']['action'])
            self.assertEqual('he_contact_evidence_incomplete', row['policy']['reason'])
            self.assertIn(row['policy']['line'], ('unknown', 'world_blocked', 'friendly_blocked'))
            # Ordinary HE may retain its already proved one-point plate
            # failure. The new wreck is unresolved line geometry, and must
            # not turn that local fact into a global all-enemy failure.

            self.assertEqual({14: True}, scene.block_lane(False))
            for unused in range(400):
                row = scene.step_control()
                self.assert_task_and_domain(scene, row)
                # Allow the ordinary movement handoff its first two callbacks;
                # thereafter both ready and reloading states must face target14.
                if unused >= 2:
                    self.assert_clear_hull_owner(scene, row)
                if len(scene.launches()) >= 4:
                    break
            self.assertEqual(4, len(scene.launches()), scene.runtime.status())
            self.assertGreaterEqual(len(scene.reload_completions), 3,
                'four launches must cross three actual GunState reload completions')
            self.assertEqual([2] * 4, [launch['shell_index'] for launch in scene.launches()])
            self.assertEqual([0, 0, 6], scene.battle._gun_state.ammo)
            self.assertEqual(route, scene.runtime.state['route'])
            self.assertEqual({'assigned', 'movement_lease'}, set(
                row['original']['tactical_evidence']['selection']['outcome']
                for row in scene.trace))

    def test_initial_tracker_cannot_reclaim_valid_he_execution_on_lane_and_health_changes(self):
        # The report distinguishes macro target from AttackPolicy target.
        # Here initial nearest actor1 is an analytically impenetrable IS-7;
        # the physically proved HE contact on actor14 must own execution.
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.scene(((1, (-34., .25, -110.), 10000.),))
            self.assertEqual({1: True, 14: True}, scene.sample_original_lanes())
            for unused in range(120):
                row = scene.step_control()
                if row['policy']['action'] == 'aim' and row['policy']['target'] == ('bot', 14):
                    break
            self.assertEqual(('bot', 14), row['policy']['target'], row['policy'])
            self.assertEqual(1, row['original']['target_id'])
            preserved = 0
            for index in range(100):
                # Actual native blocking changes only actor1's lane. It must
                # remain in the armor domain, not disappear as in the report's
                # old no_local_lane admission. Health changes formerly fed old
                # target scores, but cannot replace actor14's valid execution.
                blocked = (index // 10) % 2 == 0
                scene.pose(scene.wreck,
                    (-35.45, .25, -96.) if blocked else WRECK_POSITION)
                other = scene.battle._runtime.bigworld.entities[1]
                other.health = 20 if blocked else 500
                scene.battle._records['bot:1']['state']['health'] = other.health
                row = scene.step_control()
                self.assertEqual(1, row['original']['target_id'])
                self.assertEqual({1, 14}, set(t['network_id'] for t in scene.runtime.combat_targets()))
                self.assertEqual(ROUTE_ID, row['applied']['route_id'])
                self.assertIsNone(scene.runtime.attack_policy.search_started)
                self.assertNotIn('hull_angle_degrees', row['applied'])
                if row['policy']['action'] == 'aim':
                    self.assertEqual(('bot', 14), row['policy']['target'])
                    self.assertEqual(14, row['applied']['target_id'],
                        'macro tracker reclaimed an already proved HE execution target')
                    self.assertLess(abs(row['turn']), .002,
                        'macro target rotation leaked into the new target execution')
                    preserved += 1
            self.assertGreater(preserved, 50)
            self.assertGreaterEqual(len(scene.launches()), 2,
                'ownership checks must include real first-edge commits and native reload')


if __name__ == '__main__':
    unittest.main(verbosity=2)
