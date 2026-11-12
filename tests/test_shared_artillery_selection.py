"""Shared SPG target acquisition and real bounded-arc/contact adapters."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.vehicle_control import artillery_selection as selection
from gui.mods.offline_lan_0922.artillery_controller import ArtilleryController
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import NativeAttackEvaluator
from gui.mods.offline_lan_0922.vehicle_control.geometry import SharedBattleGeometry


def target(identity, distance, armor=100., **values):
    return dict(dict(kind='bot', network_id=identity, team=2, alive=True,
                     visible=True, health=1000, armor=armor,
                     position=(0., 0., float(distance))), **values)


class PolicyScene:
    def __init__(self):
        self.targets = [target(2, 100.), target(3, 200.)]
        self.values = {2: 100., 3: 400.}
        self.calls = []
        self.frame = dict(source=dict(id=11, team=1, position=(0., 0., 0.)),
            shell=dict(index=0, is_he=True), identity=('actor', 'gun', 0),
            fire_seq=0, trigger_active=False, intent_active=False,
            ammo=10, clip=1, reloading=False)
        self.runtime = SimpleNamespace(visible_targets=lambda: self.targets)
        self.selector = selection.ArtillerySelection()
        self.selector._frame = lambda runtime: self.frame
        self.selector._review = self.review
        self.order = dict(target_kind='bot', target_id=2, fire_allowed=True,
            move_position=(0., 0., 0.), face_position=(0., 0., 100.),
            throttle_override=0., combat_mode='artillery_hold', shell_index=0)
        self.now = 1.

    def review(self, runtime, frame, raw, now):
        self.calls.append(raw['network_id'])
        value = self.values[raw['network_id']]
        return dict(status=value, reason=value) if isinstance(value, str) else dict(
            status='ready', reason='reachable_he_contact', damage=value)

    def tick(self):
        self.now += .05
        return self.selector.select(self.runtime, self.order, self.now)

    def choose(self):
        result = None
        for unused in range(40):
            result = self.tick()
            if result.get('target_id') is not None:
                return result
        raise AssertionError(self.selector.receipt)


class SharedArtilleryPolicyTests(unittest.TestCase):
    def test_highest_proved_he_damage_not_distance_or_raw_armor(self):
        scene = PolicyScene()
        scene.targets[1]['armor'] = 300.
        chosen = scene.choose()
        self.assertEqual(3, chosen['target_id'])
        self.assertEqual(400., scene.selector.receipt['expected_he_damage'])
        self.assertEqual(scene.order['move_position'], chosen['move_position'])
        self.assertEqual(scene.order['throttle_override'], chosen['throttle_override'])
        self.assertEqual(0, chosen['shell_index'])
        self.assertTrue(chosen['fire_allowed'])

    def test_pending_candidate_is_not_pretended_to_have_zero_damage(self):
        scene = PolicyScene()
        scene.values[3] = 'pending'
        for unused in range(8):
            order = scene.tick()
            self.assertIsNone(order['target_id'])
            self.assertFalse(order['fire_allowed'])
        scene.values[3] = 900.
        self.assertEqual(3, scene.choose()['target_id'])

    def test_final_recheck_reranks_decreased_damage_before_acquiring_a_lock(self):
        scene = PolicyScene()
        self.assertIsNone(scene.tick()['target_id'])
        scene.values[3] = 10.
        before = len(scene.calls)
        chosen = scene.tick()
        self.assertEqual(2, chosen['target_id'])
        self.assertEqual(100., scene.selector.receipt['expected_he_damage'])
        self.assertEqual([3, 2], scene.calls[before:])
        self.assertEqual(2, scene.selector.receipt['reviewed'])
        self.assertTrue(chosen['fire_allowed'])

    def test_pending_final_recheck_does_not_prematurely_acquire_the_old_winner(self):
        scene = PolicyScene()
        self.assertIsNone(scene.tick()['target_id'])
        scene.values[3] = 'pending'
        order = scene.tick()
        self.assertIsNone(scene.selector.current)
        self.assertIsNone(order['target_id'])
        self.assertFalse(order['fire_allowed'])
        scene.values[3] = 10.
        self.assertEqual(2, scene.choose()['target_id'])

    def test_changing_maxima_use_existing_budget_and_do_not_authorize_unproved_successor(self):
        scene = PolicyScene()
        scene.targets.append(target(4, 250.))
        scene.values[4] = 300.
        scene.selector.reviews_per_step = 1
        for unused in range(3):
            before = len(scene.calls)
            self.assertIsNone(scene.tick()['target_id'])
            self.assertEqual(1, len(scene.calls) - before)
        scene.values.update({3: 10., 4: 20.})
        for expected_recheck in (3, 4):
            before = len(scene.calls)
            order = scene.tick()
            self.assertEqual([expected_recheck], scene.calls[before:])
            self.assertIsNone(scene.selector.current)
            self.assertIsNone(order['target_id'])
            self.assertFalse(order['fire_allowed'])
        before = len(scene.calls)
        chosen = scene.tick()
        self.assertEqual([2], scene.calls[before:])
        self.assertEqual(2, chosen['target_id'])
        self.assertTrue(chosen['fire_allowed'])

    def test_dead_and_zero_health_targets_never_enter_the_queue(self):
        scene = PolicyScene()
        scene.targets.extend([target(4, 1., health=0), target(5, 1., alive=False),
                              target(6, 1., team=1), target(7, 1., visible=False)])
        self.assertEqual(3, scene.choose()['target_id'])
        self.assertEqual({2, 3}, set(scene.calls))

    def test_valid_aim_does_not_switch_when_another_estimate_changes(self):
        scene = PolicyScene()
        self.assertEqual(3, scene.choose()['target_id'])
        scene.values[2] = 5000.
        for unused in range(20):
            self.assertEqual(3, scene.tick()['target_id'])

    def test_committed_trigger_reopens_rank_only_after_its_group_finishes(self):
        scene = PolicyScene()
        self.assertEqual(3, scene.choose()['target_id'])
        scene.values[2] = 5000.
        scene.frame.update(trigger_active=True, fire_seq=1)
        for unused in range(4):
            self.assertEqual(3, scene.tick()['target_id'])
        scene.frame.update(trigger_active=False, fire_seq=3)
        self.assertEqual(2, scene.choose()['target_id'])

    def test_existing_frozen_intent_keeps_its_identity_when_controller_is_adopted(self):
        scene = PolicyScene()
        scene.frame['intent_active'] = True
        order = scene.tick()
        self.assertEqual(2, order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual([], scene.calls)

    def test_dead_current_contact_releases_lock(self):
        scene = PolicyScene()
        self.assertEqual(3, scene.choose()['target_id'])
        scene.targets[1]['alive'] = False
        self.assertEqual(2, scene.choose()['target_id'])

    def test_blocked_or_unknown_contact_does_not_get_nominal_damage_fallback(self):
        for reason in ('blocked', 'unknown'):
            scene = PolicyScene()
            scene.values[3] = reason
            self.assertEqual(2, scene.choose()['target_id'])
            self.assertEqual(100., scene.selector.receipt['expected_he_damage'])

    def test_reload_keeps_identity_without_fire_permission(self):
        scene = PolicyScene()
        self.assertEqual(3, scene.choose()['target_id'])
        scene.frame['reloading'] = True
        order = scene.tick()
        self.assertEqual(3, order['target_id'])
        self.assertFalse(order['fire_allowed'])

    def test_non_he_uses_existing_ammunition_owner_unchanged(self):
        scene = PolicyScene()
        scene.frame['shell']['is_he'] = False
        self.assertIs(scene.order, scene.tick())
        self.assertEqual([], scene.calls)
        self.assertEqual('loaded_shell_is_not_he', scene.selector.receipt['reason'])

    def test_shared_reviewer_has_a_per_step_material_budget(self):
        scene = PolicyScene()
        scene.targets = [target(identity, identity * 10.) for identity in range(2, 16)]
        scene.values = dict((identity, identity * 40.) for identity in range(2, 16))
        for unused in range(20):
            before = len(scene.calls)
            order = scene.tick()
            self.assertLessEqual(len(scene.calls) - before, 2)
            if order.get('target_id') is not None:
                self.assertEqual(15, order['target_id'])
                break
        else:
            self.fail(scene.selector.receipt)

    def test_original_noncombat_permission_and_navigation_face_are_preserved(self):
        for mode in ('artillery_deploy', 'base_defense', 'route', 'empty_ammo'):
            scene = PolicyScene()
            scene.order.update(combat_mode=mode, fire_allowed=False,
                face_position=(20., 0., 30.), move_position=(20., 0., 30.), throttle_override=1.)
            order = scene.choose()
            self.assertFalse(order['fire_allowed'])
            for key in ('combat_mode', 'move_position', 'face_position', 'throttle_override'):
                self.assertEqual(scene.order[key], order[key])


class SharedArtilleryNativeReviewTests(unittest.TestCase):
    def scene(self):
        tester = SimpleNamespace(localHitTest=lambda *args: None)
        part = SimpleNamespace(hitTester=tester)
        target_descriptor = SimpleNamespace(chassis=part, hull=part, turret=part, gun=part)
        entity = SimpleNamespace(id=2, typeDescriptor=target_descriptor, isAlive=lambda: True)
        matrix = SimpleNamespace(translation=(0., 0., 560.), yaw=0., pitch=0., roll=0.)
        shot = dict(speed=425., gravity=143., maxDistance=10000.,
                    shell=dict(kind='HIGH_EXPLOSIVE', explosionRadius=6.))
        descriptor = SimpleNamespace(gun=SimpleNamespace(shots=[shot], pitchLimits={'absolute': (-1.5, .15)}))
        source = dict(id=11, team=1, x=0., y=0., z=0.)
        raw = target(2, 560., velocity=(8., 0., 0.))
        controller = ArtilleryController(origin_resolver=lambda state, desc: (0., 1.5, 0.))
        lane = mock.Mock(return_value=dict(clear=True))
        geometry = SimpleNamespace(_artillery=controller, _bot_artillery_friendly_lane=lane)
        owner = SimpleNamespace(_collision_shape=lambda desc: (2., 2., 2.),
            _vector=lambda value: value, _runtime=SimpleNamespace(math=object()))
        evaluator = NativeAttackEvaluator.__new__(NativeAttackEvaluator)
        evaluator.owner = owner
        evaluator.armour_rays = {}
        evaluator.cache_observations = dict(armour_batches=0, armour_ray_reuses=0)
        evaluator._he_damage = mock.Mock(return_value=dict(contact=True, expected_damage=731.))
        runtime = SimpleNamespace(owner=owner, geometry=geometry,
            attack_policy=SimpleNamespace(evaluator=evaluator), target_entity=lambda row: entity)
        frame = dict(source=source, descriptor=descriptor,
            shell=dict(index=0, is_he=True, shot=shot), identity=('actor',))
        return SimpleNamespace(runtime=runtime, frame=frame, target=raw, controller=controller,
            lane=lane, matrix=matrix, entity=entity, evaluator=evaluator)

    def test_real_arc_must_complete_before_native_he_is_consulted(self):
        scene = self.scene()
        with mock.patch.object(selection, 'native_target_pose', return_value=('pose', scene.matrix, scene.matrix)):
            row = selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.)
            self.assertEqual('pending', row['status'])
            self.assertFalse(scene.lane.called)
            self.assertFalse(scene.evaluator._he_damage.called)
            scene.controller.advance(1.01, 1, lambda start, end: None)
            row = selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.02)
            self.assertEqual('pending', row['status'])
            self.assertFalse(scene.evaluator._he_damage.called)

    def test_real_arc_obstruction_cannot_become_attackable(self):
        scene = self.scene()
        with mock.patch.object(selection, 'native_target_pose', return_value=('pose', scene.matrix, scene.matrix)):
            selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.)
            scene.controller.advance(1.01, 1000, lambda start, end: False)
            row = selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.02)
            self.assertEqual('blocked', row['status'])
            self.assertFalse(scene.evaluator._he_damage.called)

    def test_proved_arc_passes_actual_terminal_incidence_to_shared_native_resolver(self):
        scene = self.scene()
        module = 'gui.mods.offline_lan_0922'
        hit = SimpleNamespace(dist=3.)
        with mock.patch.object(selection, 'native_target_pose', return_value=('pose', scene.matrix, scene.matrix)), \
                mock.patch(module + '.entities.remote_vehicle.collide_vehicle_at_matrix', return_value=[hit]) as collide, \
                mock.patch(module + '.combat_rules.vehicle_material_trace_end', return_value=20.), \
                mock.patch(module + '.combat_rules.vehicle_material_hits', return_value=[hit]), \
                mock.patch(module + '.combat_rules.resolve_armor_contact', return_value=dict(layer='structural', result=2)):
            selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.)
            scene.controller.advance(1.01, 1000, lambda start, end: None)
            row = selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.02)
            self.assertEqual('ready', row['status'], row)
            self.assertEqual(731., row['damage'])
            solution = row['solution']
            self.assertEqual(solution, scene.lane.call_args.args[4])
            self.assertEqual(scene.frame['shell'], scene.evaluator._he_damage.call_args.args[0])
            native_contact = scene.evaluator._he_damage.call_args.args[2]
            yaw, pitch, flight = solution['yaw'], solution['pitch'], solution['flight_time']
            arrival = (math.sin(yaw) * math.cos(pitch) * 425. - 8.,
                       -math.sin(pitch) * 425. - 143. * flight,
                       math.cos(yaw) * math.cos(pitch) * 425.)
            length = math.sqrt(sum(value * value for value in arrival))
            for actual, expected in zip(native_contact['direction'], arrival):
                self.assertAlmostEqual(expected / length, actual)
            self.assertLess(native_contact['direction'][1], 0.)
            self.assertTrue(collide.called)

    def test_current_friendly_or_wreck_blockage_rejects_a_proved_world_arc(self):
        scene = self.scene()
        scene.lane.return_value = dict(clear=False, blocker_kind='bot', blocker_id=17)
        with mock.patch.object(selection, 'native_target_pose', return_value=('pose', scene.matrix, scene.matrix)):
            selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.)
            scene.controller.advance(1.01, 1000, lambda start, end: None)
            row = selection.ArtillerySelection._review(scene.runtime, scene.frame, scene.target, 1.02)
            self.assertEqual('blocked', row['status'])
            self.assertEqual('friendly_or_wreck_blocked', row['reason'])
            self.assertFalse(scene.evaluator._he_damage.called)

    def test_completed_controller_solution_satisfies_real_shared_lane_contract(self):
        scene = self.scene()
        source, descriptor = scene.frame['source'], scene.frame['descriptor']
        scene.controller.request(source, scene.target, descriptor, 0, 1.)
        scene.controller.advance(1.01, 1000, lambda start, end: None)
        solution = scene.controller.solution(source, scene.target, descriptor, 0, 1.02)
        self.assertIsNotNone(solution)
        verdict = mock.Mock(return_value=dict(clear=True))
        owner = SimpleNamespace(_descriptor_shot=SharedBattleGeometry._descriptor_shot,
                                _bot_friendly_path_verdict=verdict)
        result = SharedBattleGeometry._bot_artillery_friendly_lane(
            owner, source, scene.target, descriptor, 0, solution)
        self.assertEqual(dict(clear=True), result)
        self.assertEqual(source, verdict.call_args.args[0])
        self.assertEqual(list(solution['path']), verdict.call_args.args[1])
        self.assertEqual(6., verdict.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
