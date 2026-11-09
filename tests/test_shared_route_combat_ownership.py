"""Route/combat movement ownership through both production actor bindings.

The planner, shared combat policy, native evaluator and final driver/input
adapters are real. Only the external native world and its observed poses are
fixtures. An evaluated contact is not itself a movement-task admission, and
an intermediate stop/approach overlay is not a final physical command.

These deterministic loops cannot establish exact-client Windows frame pacing
or prove that a particular AT7/STB1 playtest is repaired.
"""
import contextlib
import copy
import io
import math
import types
import unittest
from unittest import mock

from test_player_combat_ownership import OwnershipScene
from test_player_stationary_plan import install_plan_observations
from shared_multi_bot_scene import MultiBotScene
from gui.mods.offline_lan_0922.vehicle_control import stationary_plan
from gui.mods.offline_lan_0922.vehicle_control.geometry import SharedBattleGeometry


def point(value):
    if isinstance(value, dict):
        return tuple(float(value[axis]) for axis in ('x', 'y', 'z'))
    return None if value is None else tuple(value)


def movement(order):
    """Deliberately omit target hints: they have no movement authority."""
    return dict(mode=order.get('combat_mode'),
        destination=point(order.get('move_position')),
        throttle_override=order.get('throttle_override'),
        route_id=order.get('route_id'), route_index=order.get('route_index'))


class SharedRouteCombatOwnershipTests(unittest.TestCase):
    def player(self, limited=False):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure(limited=limited, clip=1, burst=1)

    def workers(self):
        scene = MultiBotScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        return scene.configure_workers(2, diverse=False, schedule='worker10')

    def player_route_trace(self, blocked, limited):
        scene = self.player(limited=limited)
        try:
            if blocked:
                target = scene.eligible_enemy(2)
                scene.pose(target, (-30., 0., -220.))
                # Discovery is an observed fact, independently of the actual
                # world obstruction. This wall misses the authored route.
                scene.world[:] = [((-200., -20., -30.), (200., 20., -20.))]
                self.assertEqual({2: False}, scene.sample_original_lanes())
            trace = []
            evaluate = scene.runtime.attack_policy.evaluator.evaluate
            with mock.patch.object(scene.runtime.attack_policy.evaluator,
                                   'evaluate', wraps=evaluate) as native_evaluate:
                for index in range(12):
                    # Identical external poses avoid fabricating a player physics
                    # solver merely to compare the actual native input outputs.
                    scene.native_position((.3 * index, 0., .2 * index), .35)
                    scene.tick(.1)
                    sender = scene.battle._sender
                    trace.append(dict(
                        raw=movement(scene.original_order()),
                        applied=movement(scene.applied_order()),
                        final_mode=scene.runtime._last_order.get('combat_mode'),
                        inputs=(sender.forward, sender.turn, sender.handbrake),
                        gates=copy.deepcopy(scene.runtime.state.get('_motion_control_gates'))))
                if blocked:
                    self.assertGreater(native_evaluate.call_count, 0,
                        'keeping the route must not remove the enemy from native evaluation')
                    self.assertEqual({2}, {row['network_id'] for row in
                                           scene.runtime.combat_targets()})
                    self.assertTrue(scene.runtime.attack_policy.rows)
                    self.assertFalse(any(scene.runtime.attack_policy._executable_current(row)
                        for row in scene.runtime.attack_policy.rows.values()))
            self.assertIsNone(scene.runtime.attack_policy.search_started,
                'a wall is not an all-enemies armour-failure certificate')
            self.assertFalse(scene.launches())
            return trace
        finally:
            scene.doCleanups()

    def test_initial_blocked_candidate_keeps_authored_route_and_final_player_inputs(self):
        for limited in (False, True):
            with self.subTest(limited=limited), contextlib.redirect_stdout(io.StringIO()):
                baseline = self.player_route_trace(False, limited)
                blocked = self.player_route_trace(True, limited)
                for row in blocked:
                    self.assertEqual('route', row['raw']['mode'], row)
                    self.assertEqual((30., 0., 20.), row['raw']['destination'], row)
                    self.assertEqual(row['raw'], row['applied'], row)
                    self.assertEqual('route', row['final_mode'], row)
                self.assertEqual(baseline, blocked,
                    'a candidate with no accepted combat task changed final player motion')
                self.assertTrue(any(row['inputs'][0] or row['inputs'][1]
                                    for row in baseline),
                    'the baseline must really reach the final drive actuator')

    def test_initial_blocked_candidate_keeps_each_workers_authored_destination(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.workers()
            scene.world[:] = [((-200., -20., -3.), (200., 20., 3.))]
            trace = []
            for unused in range(6):
                scene.step(.1)
                for actor in scene.actor_ids:
                    binding = scene.engine._actor_controls[actor]
                    final = binding._last_order
                    trace.append(dict(actor=actor,
                        route=copy.deepcopy(scene.routes[actor]),
                        raw=movement(scene.latest_orders[actor]),
                        final_mode=final.get('combat_mode'),
                        final_destination=point(final.get('move_position')),
                        inputs=tuple(final.get(key) for key in ('throttle', 'turn', 'brake')),
                        control_trace=copy.deepcopy(final.get('control_trace'))))
            self.assertTrue(scene.evaluations,
                'BOT review must still use the native evaluator while route owns motion')
            self.assertFalse(scene.launches_observed)
        for row in trace:
            route_point = row['route']['waypoints'][1]
            destination = route_point[0], 0., route_point[1]
            self.assertEqual('route', row['raw']['mode'], row)
            self.assertEqual(destination, row['raw']['destination'], row)
            self.assertEqual('route', row['final_mode'], row)
            self.assertEqual(destination, row['final_destination'], row)
            self.assertEqual('route', row['control_trace']['action_owner'], row)
            self.assertEqual(row['inputs'][0], row['control_trace']['pedal']['throttle'], row)
            self.assertEqual(row['inputs'][1], row['control_trace']['pedal']['turn'], row)
        self.assertTrue(any(row['inputs'][0] or row['inputs'][1] for row in trace))
        for binding in scene.engine._actor_controls.values():
            self.assertIsNone(binding.attack_policy.search_started)
            self.assertEqual(1, len(binding.combat_targets()))
            self.assertTrue(binding.attack_policy.rows)

    def test_native_shot_admits_one_task_then_obstruction_keeps_it_until_target_death(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.player()
            scene.tick()
            original_route = movement(scene.original_order())
            target = scene.eligible_enemy(5)
            self.assertEqual({5: True}, scene.sample_original_lanes())
            for unused in range(20):
                scene.tick()
                if scene.runtime.attack_policy.decision['action'] == 'aim':
                    break
            runtime, policy = scene.runtime, scene.runtime.attack_policy
            self.assertEqual('aim', policy.decision['action'])
            self.assertTrue(policy._executable_current(policy.decision['candidate']))
            self.assertTrue(runtime.combat_stop.combat_owned)
            self.assertTrue(runtime.combat_stop.stop_allowed)
            self.assertEqual('engage', scene.applied_order()['combat_mode'])
            self.assertEqual(5, scene.applied_order()['target_id'])
            self.assertEqual(0., scene.battle._sender.forward)
            self.assertTrue(scene.battle._sender.handbrake)
            # A genuine later geometry change invalidates the shot proof,
            # but must not give the route task a chance to steal movement.
            scene.world[:] = [((-20., -20., 15.), (40., 20., 25.))]
            for unused in range(12):
                scene.tick()
                if policy.decision['action'] == 'firing_position':
                    break
            self.assertEqual('firing_position', policy.decision['action'])
            self.assertIsNone(policy.search_started)
            owner_episode = runtime.combat_stop.receipt['episode']
            trace = []
            with mock.patch.object(policy, 'reset', wraps=policy.reset) as reset:
                for unused in range(40):
                    scene.tick()
                    sender = scene.battle._sender
                    final = runtime._last_order
                    physical = runtime.combat_stop._physical_recovery or {}
                    marker = runtime.state.get('_gun_angle_adjustment') or {}
                    trace.append(dict(raw=movement(scene.original_order()),
                        applied=movement(scene.applied_order()),
                        final_mode=final.get('combat_mode'),
                        inputs=(sender.forward, sender.turn, sender.handbrake),
                        command=tuple(final.get(key) for key in ('throttle', 'turn', 'brake')),
                        phase_started=physical.get('started'),
                        marker_started=marker.get('start'),
                        checked_destination=marker.get('destination'),
                        owner_receipt=copy.deepcopy(runtime.combat_stop.receipt),
                        evidence_reason=policy.decision['reason'],
                        owned=runtime.combat_stop.combat_owned))
                    if sum(row['final_mode'] == 'gun_angle_adjust' for row in trace) >= 3:
                        break
                self.assertEqual(0, reset.call_count,
                    'ordinary route callbacks restarted the active combat task')
            for row in trace:
                self.assertEqual(original_route, row['raw'], row)
                self.assertTrue(row['owned'], row)
                self.assertNotEqual('route', row['applied']['mode'], row)
                self.assertNotEqual(original_route['destination'], row['applied']['destination'], row)
                self.assertEqual(row['inputs'], row['command'], row)
                self.assertEqual(owner_episode, row['owner_receipt']['episode'], row)
                self.assertEqual('retained_combat_task', row['owner_receipt']['reason'], row)
                self.assertNotEqual('advance_contact', row['final_mode'], row)
                self.assertEqual(trace[0]['phase_started'], row['phase_started'], row)
                self.assertEqual(trace[0]['marker_started'], row['marker_started'], row)
            # The retained original physical law faces first, then selects a
            # checked local goal. These are phases of one recovery, not a
            # licence to pursue the enemy centre or alternate with the route.
            moving = [row for row in trace if row['final_mode'] == 'gun_angle_adjust']
            self.assertGreaterEqual(len(moving), 3, trace)
            for row in moving:
                self.assertEqual(moving[0]['checked_destination'], row['checked_destination'], row)
                self.assertNotEqual(tuple(target.position), row['checked_destination'], row)
                self.assertEqual(moving[0]['inputs'], row['inputs'], row)
            self.assertTrue(any(row['inputs'][0] or row['inputs'][1] for row in trace))
            self.assertIsNone(policy.search_started)
            scene.battle._records['bot:5']['state'].update(alive=False, health=0)
            target.health = 0
            runtime._strategic_due = 0.
            scene.tick()
            self.assertFalse(runtime.combat_stop.combat_owned)
            self.assertFalse(runtime.combat_stop.stop_allowed)
            self.assertEqual(original_route, movement(scene.original_order()))
            self.assertEqual(original_route, movement(scene.applied_order()))
            self.assertEqual('route', runtime._last_order['combat_mode'])
            self.assertIsNone(policy.current_target_key())
            self.assertIsNone(policy.search_started)

    def test_explicit_attack_destination_is_not_rejected_as_an_initial_hint(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.player()
            target = scene.eligible_enemy(2)
            destination = (-30., 0., -40.)
            scene.pose(target, destination)
            scene.world[:] = [((-200., -20., -30.), (200., 20., -20.))]
            self.assertEqual({2: False}, scene.sample_original_lanes())
            result = scene.runtime.set_mission('attack', dict(position=destination))
            self.assertEqual('running', result['status'])
            for unused in range(8):
                scene.tick()
                order = scene.applied_order()
                self.assertEqual('team_attack', order['combat_mode'])
                self.assertEqual(destination, point(order['move_position']))
                self.assertIsNone(order.get('throttle_override'))
                self.assertEqual('team_attack', scene.runtime._last_order['combat_mode'])
                self.assertFalse(scene.runtime.combat_stop.stop_allowed)
                self.assertFalse(scene.launches())

    def test_radio_task_target_is_not_a_forced_lock_over_an_owned_native_current(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.player()
            scene.eligible_enemy(14, armor=10.)
            self.assertEqual({14: True}, scene.sample_original_lanes())
            for unused in range(20):
                scene.tick(.1)
                if scene.runtime.attack_policy.decision['action'] == 'aim':
                    break
            runtime, policy = scene.runtime, scene.runtime.attack_policy
            self.assertEqual('aim', policy.decision['action'])
            self.assertEqual(('bot', 14), policy.current_target_key())
            self.assertTrue(runtime.combat_stop.combat_owned)
            scene.obstructed_enemy(2)
            self.assertEqual({2: False, 14: True}, scene.sample_original_lanes())
            scene.tick(.1)
            current_key = policy.decision['candidate']['key']
            owner_episode = runtime.combat_stop.receipt['episode']
            current_inputs = (scene.battle._sender.forward, scene.battle._sender.turn,
                              scene.battle._sender.handbrake)
            self.assertEqual(0., current_inputs[0])
            self.assertTrue(current_inputs[2])
            # Supply an admitted server radio observation through its actual
            # snapshot/planner boundary, not a policy decision or shot proof.
            # Its named task contact is not a second gun-selection authority.
            request = dict(command_id='radio-task-2', command='ATTACKENEMY',
                team=1, issuer_id=1, issued_tick=100, expires_tick=200,
                recipient_bot_ids=[runtime.actor_id], target_kind='bot', target_id=2)
            scene.battle._last_snapshot = dict(
                round_id=scene.battle._start_message['round_id'],
                team_commands=[request])
            runtime._strategic_due = 0.
            with mock.patch.object(policy, 'reset', wraps=policy.reset) as reset:
                for unused in range(3):
                    scene.tick(.1)
                    original, applied = scene.original_order(), scene.applied_order()
                    self.assertEqual('ATTACKENEMY', original['team_command'])
                    self.assertEqual(dict(target_kind='bot', target_id=2),
                                     original['combat_task_target'])
                    self.assertNotIn('player_command_cancelled', original)
                    self.assertIsNone(original['target_id'])
                    self.assertEqual(('bot', 14), policy.current_target_key())
                    self.assertEqual(current_key, policy.decision['candidate']['key'])
                    self.assertTrue(policy._executable_current(policy.decision['candidate']))
                    self.assertEqual(14, applied['target_id'])
                    self.assertEqual(14, runtime._last_order['target_id'])
                    self.assertEqual('engage', runtime._last_order['combat_mode'])
                    self.assertEqual(current_inputs,
                        (scene.battle._sender.forward, scene.battle._sender.turn,
                         scene.battle._sender.handbrake))
                    self.assertEqual(owner_episode, runtime.combat_stop.receipt['episode'])
                    self.assertTrue(runtime.combat_stop.combat_owned)
                self.assertEqual(0, reset.call_count)

    def test_native_query_wait_does_not_release_the_previously_admitted_task(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.player(limited=True)
            scene.position = (0., 0., 0.)
            install_plan_observations(scene)
            geometry = scene.runtime.geometry
            geometry._probe_bot_local_motion = types.MethodType(
                SharedBattleGeometry._probe_bot_local_motion, geometry)
            scene.runtime.engine.local_sweep_probe = geometry._probe_bot_local_motion
            target = scene.eligible_enemy(5)
            scene.pose(target, (0., 0., 40.))
            self.assertEqual({5: True}, scene.sample_original_lanes())
            scene.tick()
            runtime, policy = scene.runtime, scene.runtime.attack_policy
            self.assertEqual('aim', policy.decision['action'])
            self.assertTrue(runtime.combat_stop.combat_owned)
            selected = policy.selected
            # The target moves outside the mounted gun's actual yaw limits.
            # Saturate only the native sweep work budget; do not supply a
            # policy decision, candidate, ray proof or ready-to-fire result.
            scene.pose(target, (math.sin(.7) * 40., 0., math.cos(.7) * 40.))
            observations = []
            with mock.patch.object(stationary_plan, 'SLICES_PER_TICK', 0), \
                    mock.patch.object(policy, 'reset', wraps=policy.reset) as reset:
                for unused in range(8):
                    scene.tick()
                    observations.append(dict(
                        raw=movement(scene.original_order()),
                        action=policy.decision['action'], reason=policy.decision['reason'],
                        candidate=policy.decision.get('candidate'), selected=policy.selected,
                        wait_since=policy._evidence_wait_since,
                        owned=runtime.combat_stop.combat_owned,
                        final_mode=runtime._last_order['combat_mode'],
                        inputs=(scene.battle._sender.forward, scene.battle._sender.turn,
                                scene.battle._sender.handbrake)))
                self.assertEqual(0, reset.call_count)
            self.assertTrue(observations)
            wait_since = observations[0]['wait_since']
            self.assertIsNotNone(wait_since)
            for row in observations:
                self.assertEqual('route', row['raw']['mode'], row)
                self.assertEqual(('wait', 'stationary_domain_review_pending'),
                    (row['action'], row['reason']), row)
                self.assertIsNone(row['candidate'], row)
                self.assertEqual(selected, row['selected'], row)
                self.assertEqual(wait_since, row['wait_since'], row)
                self.assertTrue(row['owned'], row)
                self.assertNotEqual('route', row['final_mode'], row)
                self.assertEqual((0., 0., True), row['inputs'], row)
            self.assertIsNone(policy.search_started)
            self.assertFalse(scene.launches())

    def test_native_safe_turn_can_admit_combat_before_a_current_executable_shot(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.player(limited=True)
            scene.position = (0., 0., 0.)
            install_plan_observations(scene)
            geometry = scene.runtime.geometry
            geometry._probe_bot_local_motion = types.MethodType(
                SharedBattleGeometry._probe_bot_local_motion, geometry)
            scene.runtime.engine.local_sweep_probe = geometry._probe_bot_local_motion
            target = scene.eligible_enemy(5)
            scene.pose(target, (math.sin(.7) * 40., 0., math.cos(.7) * 40.))
            self.assertEqual({5: True}, scene.sample_original_lanes())
            runtime, policy = scene.runtime, scene.runtime.attack_policy
            unowned = []
            for unused in range(30):
                scene.tick()
                if runtime.combat_stop.combat_owned:
                    break
                unowned.append((movement(scene.applied_order()),
                                scene.battle._sender.forward, scene.battle._sender.turn))
            self.assertTrue(unowned, 'the bounded native turn review must actually run')
            for order, unused_throttle, unused_turn in unowned:
                self.assertEqual('route', order['mode'])
                self.assertEqual((30., 0., 20.), order['destination'])
            candidate = policy.decision.get('candidate')
            self.assertIsNotNone(candidate, policy.status())
            self.assertEqual('firing_position', policy.decision['action'])
            self.assertEqual('current_penetration_after_stationary_turn',
                             policy.decision['reason'])
            self.assertTrue(policy._plannable(candidate))
            self.assertFalse(policy._executable(candidate))
            self.assertTrue(runtime.combat_stop.combat_owned)
            self.assertTrue(runtime.combat_stop.stop_allowed)
            self.assertEqual(('bot', 5), policy.current_target_key())
            self.assertEqual('route', scene.original_order()['combat_mode'])
            self.assertEqual(5, scene.applied_order()['target_id'])
            self.assertEqual(0., scene.battle._sender.forward)
            self.assertNotEqual(0., scene.battle._sender.turn)
            self.assertFalse(scene.launches())

    def test_worker_accepted_combat_recovery_and_death_preserve_route_task(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.workers()
            for unused in range(20):
                scene.step(.1)
                binding = scene.engine._actor_controls[11]
                if binding.attack_policy.decision['action'] == 'aim':
                    break
            policy = binding.attack_policy
            self.assertEqual('aim', policy.decision['action'])
            self.assertTrue(policy._executable_current(policy.decision['candidate']))
            self.assertTrue(binding.combat_stop.combat_owned)
            self.assertEqual('engage', binding._last_order['combat_mode'])
            self.assertEqual(0., binding._last_order['throttle'])
            self.assertTrue(binding._last_order['brake'])
            scene.world[:] = [((-200., -20., -3.), (200., 20., 3.))]
            for unused in range(12):
                scene.step(.1)
                if policy.decision['action'] == 'firing_position':
                    break
            self.assertEqual('firing_position', policy.decision['action'])
            owner_episode = binding.combat_stop.receipt['episode']
            trace = []
            with mock.patch.object(policy, 'reset', wraps=policy.reset) as reset:
                for unused in range(40):
                    scene.step(.1)
                    command = binding._last_order
                    physical = binding.combat_stop._physical_recovery or {}
                    marker = binding.state.get('_gun_angle_adjustment') or {}
                    trace.append(dict(raw=movement(scene.latest_orders[11]),
                        mode=command['combat_mode'],
                        goal=point(command['move_position']),
                        inputs=tuple(command[key] for key in ('throttle', 'turn', 'brake')),
                        action_owner=command['control_trace']['action_owner'],
                        phase_started=physical.get('started'),
                        marker_started=marker.get('start'),
                        checked_destination=marker.get('destination'),
                        owner_receipt=copy.deepcopy(binding.combat_stop.receipt),
                        evidence_reason=policy.decision['reason'],
                        owned=binding.combat_stop.combat_owned))
                    if sum(row['mode'] == 'gun_angle_adjust' for row in trace) >= 3:
                        break
                self.assertEqual(0, reset.call_count)
            for row in trace:
                self.assertEqual('route', row['raw']['mode'], row)
                self.assertEqual((8., 0., -25.), row['raw']['destination'], row)
                self.assertTrue(row['owned'], row)
                self.assertNotEqual('route', row['mode'], row)
                self.assertNotEqual((8., 0., -25.), row['goal'], row)
                self.assertEqual(row['mode'], row['action_owner'], row)
                self.assertEqual(owner_episode, row['owner_receipt']['episode'], row)
                self.assertEqual('retained_combat_task', row['owner_receipt']['reason'], row)
                self.assertNotEqual('advance_contact', row['mode'], row)
                self.assertEqual(trace[0]['phase_started'], row['phase_started'], row)
                self.assertEqual(trace[0]['marker_started'], row['marker_started'], row)
            moving = [row for row in trace if row['mode'] == 'gun_angle_adjust']
            self.assertGreaterEqual(len(moving), 3, trace)
            for row in moving:
                self.assertEqual(moving[0]['checked_destination'], row['checked_destination'], row)
                self.assertEqual(row['checked_destination'], row['goal'], row)
                self.assertEqual(1., row['inputs'][0], row)
                self.assertFalse(row['inputs'][2], row)
            self.assertIsNone(policy.search_started)
            scene.engine.states[12].update(alive=False, health=0)
            scene.native_entities[12].health = 0
            scene.next_plan = 0.
            scene.step(.1)
            self.assertFalse(binding.combat_stop.combat_owned)
            self.assertFalse(binding.combat_stop.stop_allowed)
            self.assertEqual('route', scene.latest_orders[11]['combat_mode'])
            self.assertEqual('route', binding._last_order['combat_mode'])
            self.assertEqual((8., 0., -25.), point(binding._last_order['move_position']))
            self.assertEqual(scene.routes[11], binding.state['route'])
            self.assertIsNone(policy.current_target_key())


if __name__ == '__main__':
    unittest.main()
