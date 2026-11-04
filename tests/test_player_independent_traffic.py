"""Foreground-owned traffic policies over real local collision geometry.

The world/pose predicates are explicit seams; these tests do not claim that
Linux exercises the Windows native movement or collision implementation.
"""
import ast
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.driving import Driver, angle
from gui.mods.offline_lan_0922.player_control.traffic import PlayerTraffic, Traffic, body
from gui.mods.offline_lan_0922.player_control.wrecks import WreckPush


SHAPE = (1., 2., 0., 2.)


def peer(identity, position, yaw=0., velocity=(0., 0., 0.), alive=True, team=1):
    return dict(id=identity, position=position, yaw=yaw, velocity=velocity,
                alive=alive, team=team, collision_shape=SHAPE)


def state(now=0., position=(0., 0., 0.), yaw=0., speed=0., identity=1):
    # The public network id is deliberately different from collision identity.
    return dict(id=identity+1000, engine_id=identity, position=position, yaw=yaw,
                speed=speed, now=now, half_length=2., half_width=1., decision_horizon=.1)


def order(mode='route', hold=False):
    return dict(throttle=0. if hold else 1., turn=0., brake=hold, holding=hold,
                combat_mode=mode, recovery_mode='hold' if hold else 'travel',
                travel_intent=not hold, local_target=(0., 0., 30.))


def apply(player, own, peers, command, clear=None, contact=None, stalled=False):
    traffic = Traffic(body(own['engine_id'], own['position'], own['yaw'], SHAPE), peers)
    if clear is None:
        clear = lambda heading, reach=6.: traffic.clear(heading, reach)
    player.apply(command, own, traffic, 1, clear, lambda: 0., 1./30., stalled,
                 None, contact=contact)
    return command


class IndependentTrafficTests(unittest.TestCase):
    def test_crossing_coordination_covers_every_travel_intent_and_spg(self):
        for mode in ('route', 'advance', 'return_to_base', 'base_capture',
                     'base_defence', 'artillery_deploy', 'artillery_relocate',
                     'withdraw', 'firing_position', 'td_parking', 'assault'):
            with self.subTest(mode=mode):
                own = state(position=(0., 0., -5.), speed=5., identity=2)
                own['class_tag'] = 'SPG'
                crossing = peer(1, (-5., 0., 0.), math.pi/2., (5., 0., 0.))
                command = apply(PlayerTraffic(), own, [crossing], order(mode))
                self.assertEqual('yield', command['traffic_mode'])
                self.assertTrue(command['brake'])
                self.assertEqual(0., command['throttle'])

    def test_two_local_clients_choose_one_backer_without_shared_orders(self):
        first, second = PlayerTraffic(), PlayerTraffic()
        commands = []
        for now in (0., 1.6):
            commands = []
            for player, identity, z, yaw, other_id, other_z, other_yaw in (
                    (first, 1, 0., 0., 2, 4.1, math.pi),
                    (second, 2, 4.1, math.pi, 1, 0., 0.)):
                own = state(now, (0., 0., z), yaw, identity=identity)
                other = peer(other_id, (0., 0., other_z), other_yaw)
                # Both lateral ways and the occupied forward corridor are
                # world-blocked. Each independently sees a free rear exit.
                clear = lambda heading, reach=6., yaw=yaw: abs(angle(heading-yaw)) > 2.
                commands.append(apply(player, own, [other], order('return_to_base'), clear))
        self.assertEqual([0., -.7], [command['throttle'] for command in commands])
        self.assertEqual([1, 1], [command['traffic_control']['priority'] for command in commands])
        self.assertEqual([2, 2], [command['traffic_control']['retreat'] for command in commands])
        self.assertIsNot(first.pairs[2], second.pairs[1])
        exhausted = apply(second, state(8., (0., 0., 4.1), math.pi, identity=2),
                          [peer(1, (0., 0., 0.))], order('return_to_base'),
                          lambda heading, reach=6.: True)
        self.assertTrue(exhausted['traffic_control']['exhausted'])
        self.assertTrue(exhausted['brake'])
        self.assertEqual(0., exhausted['throttle'])

    def test_real_driver_zero_throttle_blockage_still_enters_coordination(self):
        player = PlayerTraffic()
        own = state(identity=2)
        other = peer(1, (0., 0., 4.1), math.pi)
        traffic = Traffic(body(2, own['position'], own['yaw'], SHAPE), [other])
        def clear(heading, reach=6.):
            return abs(angle(heading-math.pi)) < .1 and traffic.clear(heading, reach)
        command = Driver().drive(own['position'], 0., 0., (0., 0., 30.), 0., clear)
        self.assertEqual(0., command['throttle'])
        command.update(travel_intent=True, combat_mode='return_to_base')
        apply(player, own, [other], command, clear)
        self.assertEqual('head_on_blocked', command['traffic_mode'])
        own['now'] = 1.6
        command = Driver().drive(own['position'], 0., 0., (0., 0., 30.), 1.6, clear)
        command.update(travel_intent=True, combat_mode='return_to_base')
        apply(player, own, [other], command, clear)
        self.assertEqual(-.7, command['throttle'])

    def test_priority_client_advances_after_backer_has_created_real_space(self):
        player = PlayerTraffic()
        for now in (0., 1.6):
            apply(player, state(now), [peer(2, (0., 0., 4.1), math.pi)],
                  order(), lambda *args: False)
        command = apply(player, state(2.), [peer(2, (0., 0., 10.5), math.pi)], order())
        self.assertEqual(.7, command['throttle'])
        self.assertFalse(command['brake'])

    def test_reverse_steering_checks_the_physical_intent_sign(self):
        from gui.mods.offline_lan_0922 import tank_collision
        traffic = Traffic(body(1, (0., 0., 0.), 0., SHAPE), [])
        with mock.patch.object(tank_collision, 'rotation_fraction', return_value=1.) as rotation:
            self.assertTrue(traffic.can_steer(-1., .5, 0.))
        self.assertLess(rotation.call_args_list[0].args[2], 0.)
        self.assertLess(rotation.call_args.args[2], rotation.call_args_list[0].args[2])

    def test_automatic_stationary_ally_yields_once_then_resumes_original_task(self):
        player = PlayerTraffic()
        follower = peer(2, (0., 0., -4.2), velocity=(0., 0., .3))
        first = apply(player, state(), [follower], order('engage', hold=True))
        self.assertEqual('hold', first['recovery_mode'])
        follower['velocity'] = (0., 0., 0.)
        yielded = apply(player, state(1.6), [follower], order('engage', hold=True))
        self.assertEqual('friendly_yield', yielded['recovery_mode'])
        self.assertEqual(.7, yielded['throttle'])
        self.assertTrue(yielded['suppress_fire'])
        self.assertFalse(yielded['fire_allowed'])
        resumed = apply(player, state(5.7), [follower], order('engage', hold=True))
        self.assertEqual('engage', resumed['combat_mode'])
        self.assertEqual('hold', resumed['recovery_mode'])
        follower['movement_intent'] = 1.
        for now in (6., 8., 20.):
            again = apply(player, state(now), [follower], order('engage', hold=True))
            self.assertEqual('hold', again['recovery_mode'])
        follower['position'] = (0., 0., -8.)
        apply(player, state(21.), [follower], order('engage', hold=True))
        follower['position'] = (0., 0., -4.2)
        apply(player, state(22.), [follower], order('engage', hold=True))
        self.assertEqual('friendly_yield', apply(player, state(24.), [follower],
                         order('engage', hold=True))['recovery_mode'])

    def test_explicit_hold_author_wait_arrival_and_burst_never_courtesy_move(self):
        for policy in ('explicit', 'mission', 'parking', 'arrival', 'burst'):
            with self.subTest(policy=policy):
                player = PlayerTraffic()
                follower = peer(2, (0., 0., -4.2))
                follower['movement_intent'] = 1.
                for now in (0., 2., 5.):
                    own, command = state(now), order('engage', hold=True)
                    if policy == 'explicit':
                        command['traffic_hold_protected'] = True
                    elif policy == 'mission':
                        command['mission'] = dict(name='hold', status='running')
                    elif policy == 'parking':
                        command['parking_phase'] = 'waiting'
                    elif policy == 'arrival':
                        command['recovery_mode'] = 'arrival_brake'
                    else:
                        own['burst_active'] = True
                    result = apply(player, own, [follower], command, stalled=True)
                    self.assertEqual(0., result['throttle'])
                    self.assertNotIn('suppress_fire', result)

    def test_stationary_or_other_level_peer_does_not_invent_a_yield_request(self):
        for follower in (peer(2, (0., 0., -4.2)),
                         peer(2, (0., 10., -4.2), velocity=(0., 0., .3))):
            player = PlayerTraffic()
            for now in (0., 2., 5.):
                command = apply(player, state(now), [follower], order('artillery_hold', hold=True))
                self.assertEqual('hold', command['recovery_mode'])

    def test_side_contact_uses_nearest_longitudinal_end_and_retains_attempt(self):
        player = PlayerTraffic()
        side = peer(2, (2., 0., 1.))
        contact = dict(peer=2, normal=(-1., 0.), at=1., source='copied_planar_contact')
        command = apply(player, state(1.), [side], order('engage', hold=True), contact=contact)
        self.assertEqual('contact_escape', command['recovery_mode'])
        self.assertEqual(-1., command['throttle'])
        self.assertEqual(0., command['turn'])
        self.assertTrue(command['suppress_fire'])
        retained = apply(player, state(1.2), [side], order('engage', hold=True))
        self.assertEqual('contact_escape', retained['recovery_mode'])
        self.assertEqual(-1., retained['throttle'])

    def test_contact_failures_survive_replanning_yaw_jitter_and_contact_gaps(self):
        player = PlayerTraffic()
        side = peer(2, (2., 0., 1.))
        for now, expected in ((1., -1.), (9.1, 1.), (17.2, 0.), (18., 0.)):
            command = apply(player, state(now), [side], order('engage', hold=True),
                contact=dict(peer=2, normal=(-1., 0.), at=now))
            self.assertEqual(expected, command['throttle'])
        failed = set(player.contact_memory['failed'])
        apply(player, state(25., yaw=.01), [side], order('engage', hold=True))
        self.assertEqual(failed, player.contact_memory['failed'])
        side['position'] = (2., 0., 2.1)
        renewed = apply(player, state(26.), [side], order('engage', hold=True),
                        contact=dict(peer=2, normal=(-1., 0.), at=26.))
        self.assertEqual(-1., renewed['throttle'])

    def test_unproved_contact_cannot_start_a_motion(self):
        side = peer(2, (2., 0., 1.))
        for contact in (dict(peer=2, normal=(-1., 0.), at=0.),
                        dict(peer=99, normal=(-1., 0.), at=1.),
                        dict(peer=2, normal=(1., 0.), at=1.),
                        dict(peer=2, normal=(float('nan'), 0.), at=1.),
                        dict(peer=None, normal=(-1., 0.), at=1., source='world_collision')):
            command = apply(PlayerTraffic(), state(1.), [side], order('engage', hold=True), contact=contact)
            self.assertEqual('hold', command['recovery_mode'])
            self.assertEqual(0., command['throttle'])

    def test_contact_endpoint_requires_the_full_static_and_vehicle_sweep(self):
        player = PlayerTraffic()
        side = peer(2, (2., 0., 1.))
        clear = mock.Mock(return_value=False)
        command = apply(player, state(1.), [side], order('engage', hold=True), clear,
                        dict(peer=2, normal=(-1., 0.), at=1.))
        self.assertEqual('hold', command['recovery_mode'])
        self.assertEqual(2, clear.call_count)
        self.assertAlmostEqual(3.45, clear.call_args_list[0].args[1])
        self.assertAlmostEqual(5.45, clear.call_args_list[1].args[1])


class ForegroundStoppingTests(unittest.TestCase):
    def test_terminal_stopping_distance_includes_held_decision_horizon(self):
        driver = Driver()
        result = driver.drive((0., 0., 0.), 0., 10., (0., 0., 7.4), 0.,
                              lambda *args: True, stopping_distance=5.,
                              decision_horizon=.1, terminal=True)
        self.assertEqual('arrival_brake', result['recovery_mode'])
        self.assertEqual(6., driver.receipt['stopping_envelope'])
        self.assertTrue(result['brake'])
        waypoint = Driver().drive((0., 0., 0.), 0., 10., (0., 0., 7.4), 0.,
                                  lambda *args: True, stopping_distance=5.,
                                  decision_horizon=.1, terminal=False)
        self.assertEqual('travel', waypoint['recovery_mode'])
        self.assertGreater(waypoint['throttle'], 0.)

    def test_exact_terminal_endpoint_with_zero_radius_does_not_creep(self):
        result = Driver().drive((0., 0., 0.), 0., 0., (0., 0., 0.), 0.,
                                lambda *args: True, terminal=True, arrival_radius=0.)
        self.assertEqual('hold', result['recovery_mode'])
        self.assertEqual(0., result['throttle'])

    def test_allied_brake_uses_decision_time_not_only_one_physics_slice(self):
        own = state(speed=10.)
        own['decision_horizon'] = .2
        follower = peer(2, (0., 0., 5.8))
        command = apply(PlayerTraffic(), own, [follower], order(), lambda *args: True)
        self.assertEqual('vehicle_brake', command['traffic_mode'])
        self.assertEqual(0., command['throttle'])


class ForegroundWreckTests(unittest.TestCase):
    def run_push(self, push, now, wreck=None, proof=None, world=True, extras=()):
        own = state(now)
        wreck = wreck or peer(4, (0., 0., 5.), alive=False)
        traffic = Traffic(body(1, own['position'], 0., SHAPE), [wreck]+list(extras))
        command = order('base_capture')
        active = push.apply(command, own, traffic, lambda *args: world, pose_clear=proof)
        return active, command

    def test_steering_starts_after_eight_seconds_and_keeps_fourteen_second_budget(self):
        push, proof = WreckPush(), mock.Mock(return_value=True)
        active, command = self.run_push(push, 0., proof=proof)
        self.assertTrue(active)
        self.assertEqual(0., command['turn'])
        proof.assert_not_called()
        active, command = self.run_push(push, 8., proof=proof)
        self.assertTrue(active)
        self.assertEqual(.7, abs(command['turn']))
        self.assertEqual(4, proof.call_count)
        self.assertTrue(command['suppress_fire'])
        self.assertFalse(self.run_push(push, 14., proof=proof)[0])
        self.assertEqual('own_stalled', push.receipt['phase'])

    def test_side_touching_wreck_can_be_turned_into_only_after_pose_proof(self):
        wreck = peer(4, (2., 0., 0.), alive=False)
        active, command = self.run_push(WreckPush(), 0., wreck, lambda yaw: True)
        self.assertTrue(active)
        self.assertGreater(command['turn'], 0.)
        self.assertFalse(self.run_push(WreckPush(), 0., wreck, None)[0])
        self.assertFalse(self.run_push(WreckPush(), 0., wreck, lambda yaw: False)[0])

    def test_rejected_native_rotation_keeps_front_push_straight(self):
        push = WreckPush()
        self.run_push(push, 0., proof=lambda yaw: False)
        active, command = self.run_push(push, 8., proof=lambda yaw: False)
        self.assertTrue(active)
        self.assertEqual(0., command['turn'])

    def test_only_selected_wreck_is_excluded_from_push_planning_sweep(self):
        for alive in (True, False):
            blocker = peer(5, (0., 0., 8.), alive=alive)
            active, command = self.run_push(WreckPush(), 0., proof=lambda yaw: True,
                                            extras=(blocker,))
            self.assertFalse(active)
            self.assertNotEqual('wreck_push', command['recovery_mode'])

    def test_owned_modules_do_not_import_bot_policy_or_adapter(self):
        base = ROOT / 'src/res/scripts/client/gui/mods/offline_lan_0922/player_control'
        for name in ('driving.py', 'traffic.py', 'traffic_laws.py', 'wrecks.py'):
            module = ast.parse((base / name).read_text())
            imports = [node.module for node in ast.walk(module) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(module) if isinstance(node, ast.Import)
                        for alias in node.names]
            self.assertFalse(any(value and ('ai.driver' in value or 'ai.traffic' in value or
                                           'ai.adapter' in value) for value in imports), name)


class ForegroundControllerTrafficIntegrationTests(unittest.TestCase):
    def controller(self, tag='mediumTank'):
        from gui.mods.offline_lan_0922.player_control import PlayerControl
        from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
        from gui.mods.offline_lan_0922.player_control.traffic import TurnClearance
        entity = types.SimpleNamespace(id=7, isAlive=lambda: True, health=1000,
            typeDescriptor=types.SimpleNamespace(maxHealth=1000,
                type=types.SimpleNamespace(tags=(tag,))))
        sender = types.SimpleNamespace(forward=0., turn=0., handbrake=False, send_current=mock.Mock())
        owner = types.SimpleNamespace(_sender=sender,
            _server=types.SimpleNamespace(vehicle_id=7), _server_entity=lambda identity:entity,
            _gun_state=types.SimpleNamespace(ammo=[10], shots=[{}], clip=1, clip_size=1,
                shot_index=0, reload_time=0., can_fire=lambda unused:True),
            _clock=lambda:1., _local_speed=0., _local_pitch=0., _local_roll=0.,
            _local_player_burst=None, _local_fire_intent=None, _records={}, _rules_state={},
            _start_message=dict(round_id='r', players=[dict(id=101, team=1)], bots=[]),
            client=types.SimpleNamespace(player_id=101, team=1),
            local_pose=lambda:((0., 0., 0.), 0.), _collision_shape=lambda descriptor:SHAPE)
        controller = PlayerControl(owner, ('drive',), notify=lambda text:None)
        owner._player_control = controller
        controller.active = True
        controller.live = lambda:True
        controller.bind_input = lambda:None
        controller.poll_commands = lambda now:None
        controller.record = mock.Mock()
        controller.publish_status = mock.Mock()
        controller._contacts = lambda entity:([], [], {})
        controller.direction_clear = lambda *args:True
        controller.turn_clearance = TurnClearance()
        controller.strategy = types.SimpleNamespace(mode='front')
        nav = PlayerNavigation.__new__(PlayerNavigation)
        nav.routes, nav.route, nav.home, nav.receipt, nav.tag = [], None, None, {}, tag
        nav.cover_move = nav.firing_move = None
        nav.driver = Driver()
        nav._height = lambda point, hint=None:0.
        nav.close = mock.Mock()
        nav.mission_status = lambda:None
        nav.report_drive_blockage = mock.Mock()
        nav.set_context = lambda context:setattr(nav, 'context', context)
        nav.movement_policy = lambda state:dict(force_move=True, allow_strategy=False,
            allow_withdrawal=False, allow_firing_position=False)
        nav.decide = lambda state, clear, hold=False:dict(order(), driving=nav.driver.receipt)
        controller.navigation = nav
        return controller, nav, entity

    def test_real_update_passes_elapsed_decision_horizon_and_collision_identity(self):
        for tag in ('mediumTank', 'SPG'):
            controller, nav, unused_entity = self.controller(tag)
            captured = []
            original = nav.decide
            def capture(state, clear, hold=False):
                captured.append(dict(state))
                return original(state, clear, hold)
            nav.decide = capture
            with mock.patch.object(controller.player_traffic, 'apply',
                                   wraps=controller.player_traffic.apply) as traffic:
                controller.update(.02, 1.)
                controller.update(.02, 1.45)
            self.assertEqual(2, traffic.call_count)
            self.assertEqual(101, captured[-1]['id'])
            self.assertEqual(7, captured[-1]['engine_id'])
            self.assertEqual(7, traffic.call_args.args[2].current['id'])
            self.assertAlmostEqual(.45, captured[-1]['decision_horizon'])

    def test_stop_during_decision_cannot_republish_old_drive_controls(self):
        controller, nav, unused_entity = self.controller()
        def revoked(state, clear, hold=False):
            controller.stop('native_callback_stop')
            return order()
        nav.decide = revoked
        controller.update(.1, 1.)
        self.assertFalse(controller.active)
        self.assertEqual((0., 0., False), (controller.owner._sender.forward,
            controller.owner._sender.turn, controller.owner._sender.handbrake))
        self.assertEqual({}, controller.last_order)

    def test_courtesy_movement_exits_siege_even_if_original_task_was_engage(self):
        controller, unused_nav, entity = self.controller('AT-SPG')
        entity.typeDescriptor.hasSiegeMode = True
        entity.siegeState = 1
        states = types.SimpleNamespace(DISABLED=0, ENABLED=1, SWITCHING_ON=2, SWITCHING_OFF=3)
        owner = controller.owner
        owner._runtime = types.SimpleNamespace(constants=types.SimpleNamespace(VEHICLE_SIEGE_STATE=states))
        owner._local_siege_pending = owner._local_siege_braking = None
        owner._request_player_control_siege = mock.Mock(return_value=True)
        # The outer siege travel guard already brakes the pedals. The original
        # movement intent and suppression flag must still request travel mode.
        command = dict(order('engage'), throttle=0., brake=True, holding=False,
            recovery_mode='siege_wait_travel', suppress_fire=True, fire_allowed=False)
        controller.update_siege(entity, command, True, 0.)
        controller.update_siege(entity, command, True, 1.)
        owner._request_player_control_siege.assert_called_once_with(False, mock.ANY)

    def test_wreck_steering_retains_the_same_progressing_governor_lease(self):
        from gui.mods.offline_lan_0922.player_control.capabilities import Governor
        governor = Governor()
        self.assertTrue(governor.wanted(0., 0., 0., True, False,
            dict(peer=4, phase='pushing', progress=0.)))
        self.assertTrue(governor.wanted(1., 0., 0., True, False,
            dict(peer=4, phase='steering', progress=0.)))
        self.assertFalse(governor.wanted(2.1, 0., 0., True, False,
            dict(peer=4, phase='steering', progress=0.)))

    def test_real_update_terminal_brake_revokes_a_preceding_latched_pivot(self):
        controller, nav, unused_entity = self.controller()
        controller.owner._local_speed = 5.
        controller.owner._local_physics = {}
        controller.turn_clearance.heading = 1.
        controller.turn_clearance.sign = 1.
        def parking(state, clear, hold=False):
            goal = (math.sin(1.)*8., 0., math.cos(1.)*8.)
            command = nav.driver.drive(state['position'], state['yaw'], state['speed'],
                goal, state['now'], clear, stopping_distance=state['stopping_distance'],
                decision_horizon=state['decision_horizon'], terminal=True)
            self.assertEqual('arrival_brake', command['recovery_mode'])
            return dict(command, combat_mode='hold_position', travel_intent=True,
                        local_target=goal, driving=dict(nav.driver.receipt))
        nav.decide = parking
        with mock.patch('gui.mods.offline_lan_0922.player_control.traffic_laws.traffic_stopping_distance',
                        return_value=10.):
            controller.update(.1, 1.)
        self.assertEqual((0., 0., True), (controller.owner._sender.forward,
            controller.owner._sender.turn, controller.owner._sender.handbrake))
        self.assertEqual('arrival_brake', controller.last_order['recovery_mode'])

    def test_real_update_wreck_steering_reaches_read_only_native_pose_proof(self):
        controller, unused_nav, unused_entity = self.controller()
        owner = controller.owner
        wreck = peer(4, (0., 0., 5.), alive=False)
        controller._contacts = lambda entity:([], [wreck], {})
        owner._destructibles = types.SimpleNamespace(
            _vehicle_body_bbox=lambda descriptor:((-1., 0., -2.), (1., 2., 2.)))
        owner._native_world_rotation_is_clear = mock.Mock(return_value=True)
        owner._arena_rotation_is_clear = mock.Mock(return_value=True)
        owner._turret_pose_is_clear = mock.Mock(return_value=True)
        owner._destructible_pose_sweep = mock.Mock(return_value=dict(status='clear', requires_commit=False))
        controller.update(.1, 0.)
        self.assertEqual(0., owner._sender.turn)
        owner._native_world_rotation_is_clear.assert_not_called()
        controller.update(.1, 8.)
        self.assertEqual(.7, abs(owner._sender.turn))
        self.assertEqual(1., owner._sender.forward)
        self.assertEqual('steering', controller.last_order['wreck_push']['phase'])
        self.assertTrue(controller.last_order['suppress_fire'])
        self.assertEqual(4, owner._native_world_rotation_is_clear.call_count)
        self.assertTrue(owner._native_world_rotation_is_clear.call_args.kwargs['include_static'])
        self.assertFalse(owner._native_world_rotation_is_clear.call_args.kwargs['record_local'])
        self.assertFalse(owner._destructible_pose_sweep.call_args.kwargs['commit_enabled'])
        controller.update(.1, 14.)
        self.assertEqual('own_stalled', controller.last_order['wreck_push']['phase'])

    def test_real_spg_update_consumes_physical_contact_with_engine_identity(self):
        controller, nav, unused_entity = self.controller('SPG')
        side = peer(2, (2., 0., 1.))
        controller._contacts = lambda entity:([], [side], {})
        nav.decide = lambda state, clear, hold=False:order('artillery_hold', hold=True)
        controller.drive_contact((0., 0., 0.), 0., .1, static=False,
            contact=dict(peer=2, normal=(-1., 0.), at=1., source='copied_planar_contact'))
        controller.update(.1, 1.)
        self.assertEqual(-1., controller.owner._sender.forward)
        self.assertEqual('contact_escape', controller.last_order['recovery_mode'])
        self.assertEqual(2, controller.last_order['traffic_control']['peer'])
        self.assertIsNone(controller.drive_contact_receipt)

    def test_cover_driver_terminal_brake_survives_main_withdrawal_dispatch(self):
        controller, nav, unused_entity = self.controller()
        controller.features.add('fire')
        controller.aiming = types.SimpleNamespace(begin=lambda *args:None)
        controller.weapon = types.SimpleNamespace(forward=mock.Mock(), point=(0., 0., 0.))
        owner = controller.owner
        owner._avatar = types.SimpleNamespace(gunRotator=types.SimpleNamespace(clientMode=True))
        owner._tactical_ray_clear = lambda *args:True
        owner._local_speed, owner._local_physics = 5., {}
        controller.turn_clearance.heading, controller.turn_clearance.sign = 1., 1.
        nav.cover_move = dict(goal=(math.sin(1.)*8., 0., math.cos(1.)*8.))
        nav.movement_policy = lambda state:dict(force_move=True, allow_strategy=False,
            allow_withdrawal=True, allow_firing_position=False)
        def retreat(state, target, entity, gun, clear, terrain_ray):
            return nav._cover_motion(state, clear, nav.cover_move['goal'], 'return')
        nav.withdrawal = retreat
        with mock.patch('gui.mods.offline_lan_0922.player_control.traffic_laws.traffic_stopping_distance',
                        return_value=10.):
            controller.update(.1, 1.)
        self.assertEqual('cover_return', controller.last_order['combat_mode'])
        self.assertEqual('arrival_brake', controller.last_order['recovery_mode'])
        self.assertEqual((0., 0., True), (owner._sender.forward, owner._sender.turn, owner._sender.handbrake))

    def test_stop_from_native_wreck_rotation_query_cannot_republish_push(self):
        controller, unused_nav, unused_entity = self.controller()
        owner = controller.owner
        controller._contacts = lambda entity:([], [peer(4, (0., 0., 5.), alive=False)], {})
        owner._destructibles = types.SimpleNamespace(
            _vehicle_body_bbox=lambda descriptor:((-1., 0., -2.), (1., 2., 2.)))
        owner._arena_rotation_is_clear = lambda *args:True
        owner._turret_pose_is_clear = lambda *args:True
        owner._destructible_pose_sweep = lambda *args, **kwargs:dict(status='clear', requires_commit=False)
        def revoked(*args, **kwargs):
            controller.stop('native_rotation_stop')
            return True
        owner._native_world_rotation_is_clear = revoked
        controller.update(.1, 0.)
        self.assertEqual(1., owner._sender.forward)
        controller.update(.1, 8.)
        self.assertFalse(controller.active)
        self.assertEqual((0., 0., False), (owner._sender.forward, owner._sender.turn, owner._sender.handbrake))
        self.assertEqual({}, controller.last_order)


if __name__ == '__main__':
    unittest.main()
