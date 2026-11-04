"""Independent producer/controller lifecycle regressions found during integration review.

These exercise real admission, mission validation, cleanup, and launcher readback;
engine stubs model only the unavailable native boundary.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
sys.path.insert(0, str(ROOT / 'launcher'))
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.commands import CommandGateway, append_result
from gui.mods.offline_lan_0922.player_control.navigation import PlayerNavigation
from player_control_transport import PlayerControlTransport


class PlayerControlIntegrationReviewTests(unittest.TestCase):
    def setUp(self):
        self.environ = mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'review-session'})
        self.environ.start()
        self.addCleanup(self.environ.stop)
        self.rows = []

    def control(self):
        entity = types.SimpleNamespace(id=1, isAlive=lambda: True,
            typeDescriptor=types.SimpleNamespace(maxHealth=1000), health=1000)
        sender = types.SimpleNamespace(forward=1., turn=.3, handbrake=False,
                                       send_current=mock.Mock())
        gun = types.SimpleNamespace(shots=[{}], ammo=[10], clip=1, clip_size=1,
                                    reload_time=0., shot_index=0)
        gun.can_fire = lambda unused: gun.reload_time <= 0 and gun.clip > 0 and gun.ammo[0] > 0
        owner = types.SimpleNamespace(_server=types.SimpleNamespace(vehicle_id=1),
            _server_entity=lambda unused: entity, _sender=sender, _gun_state=gun,
            state='running', _battle_live=True, _battle_result=None,
            _worker_mode=False, _replay_mode=False, _clock=lambda: 1.,
            _start_message={'round_id': 'round-a'},
            client=types.SimpleNamespace(player_id=1, team=1),
            _avatar=types.SimpleNamespace(isWaitingForShot=False),
            _local_fire_intent=None, _local_player_burst=None,
            _cancel_local_player_burst=mock.Mock(), _local_speed=0.,
            local_pose=lambda: ((0., 0., 0.), 0.),
            _collision_shape=lambda unused: (1., 3., 0., 2.))
        controller = PlayerControl(owner, ('drive', 'fire'), notify=lambda text: None)
        owner._player_control = controller
        controller.record = mock.Mock()
        controller.emit_result = lambda row: self.rows.append(dict(row)) or True
        controller.gateway.emit = controller.emit_result
        controller.gateway.wall_clock = lambda:1000.
        return controller

    @staticmethod
    def request(controller, action, command_id='one', **overrides):
        request = dict(controller.identity(), id=command_id, action=action,
                       args={}, timeout_seconds=15., replace=True, expires_at=1005.)
        request.update(overrides)
        return request

    def test_rejected_fire_retry_never_creates_a_later_unreported_shot(self):
        controller = self.control()
        gun = controller.owner._gun_state
        gun.reload_time = 5.
        request = self.request(controller, 'fire')
        first = controller.gateway.submit(request, 0.)
        self.assertEqual(('rejected', 'gun_not_ready'), (first['status'], first['reason']))
        gun.reload_time = 0.
        def shoot():
            controller.owner._local_fire_intent = {'projectile_id': 'late-shot'}
        controller.owner._avatar.shoot = mock.Mock(side_effect=shoot)
        second = controller.gateway.submit(request, 1.)
        controller.owner._avatar.shoot.assert_not_called()
        self.assertEqual(first, second)

    def test_cleanup_error_cannot_latch_an_automatic_movement_input(self):
        controller = self.control()
        controller.active = True
        controller.navigation = types.SimpleNamespace(
            close=mock.Mock(side_effect=[RuntimeError('native close failed'), None]))
        try:
            controller.stop('controller_error')
        except RuntimeError:
            pass
        # The battle loop also retries stop after a controller exception.
        controller.stop('controller_error')
        sender = controller.owner._sender
        self.assertEqual((0., 0., False), (sender.forward, sender.turn, sender.handbrake))
        self.assertFalse(controller.owns_drive())

    def test_invalid_mission_destination_does_not_preempt_a_running_timed_drive(self):
        controller = self.control()
        controller.override = (10., 1., 0.)
        previous = controller.override
        navigation = PlayerNavigation.__new__(PlayerNavigation)
        navigation.mission_sequence = 0
        navigation.home_area = {'point': (0., 0.), 'radius': 25., 'team': 1}
        navigation.enemy_area = {'point': (50., 50.), 'radius': 25., 'team': 2}
        navigation.bounds = (-100., -100., 100., 100.)
        navigation.mission = None
        def start_takeover():
            controller.active = True
            controller.navigation = navigation
            return True
        controller.toggle = mock.Mock(side_effect=start_takeover)
        request = self.request(controller, 'hold_position', args={'position': (1000., 0., 0.)})
        with mock.patch('gui.mods.offline_lan_0922.player_control.navigation.PlayerNavigation',
                        return_value=navigation):
            receipt = controller.gateway.submit(request, 0.)
        self.assertEqual('failed', receipt['status'])
        self.assertEqual('objective_outside_arena', receipt['reason'])
        self.assertEqual(previous, controller.override)
        self.assertFalse(controller.active)

    def test_stop_status_does_not_republish_the_released_automatic_target(self):
        controller = self.control()
        controller.active = True
        controller.target_engine = 202
        controller.aim_receipt = {'target': 202, 'aligned': True, 'fire_clear': True}
        controller.stop('manual')
        controller.publish_status(1., force=True)
        status = self.rows[-1]
        self.assertFalse(status['active'])
        self.assertIsNone(status['aim'])

    def transport_and_gateway(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        command_path = os.path.join(directory.name, 'commands.jsonl')
        result_path = os.path.join(directory.name, 'results.jsonl')
        for path in (command_path, result_path):
            Path(path).write_bytes(b'')
        identity = dict(session_id='review-session', round_id='round-a', player_id=1)
        transport = PlayerControlTransport(command_path, result_path, identity['session_id'])
        append_result(result_path, dict(identity, type='status', live=True, active=True))
        gateway = CommandGateway(lambda: dict(identity),
            lambda row: append_result(result_path, row), lambda request, now: None,
            lambda request: None, lambda request, reason: None)
        return transport, gateway, identity, command_path

    def test_conflicting_retry_does_not_poison_the_original_request_terminal_result(self):
        transport, gateway, unused_identity, command_path = self.transport_and_gateway()
        command_id = transport.send('drive', {'seconds': 1., 'forward': 1.})
        request = json.loads(Path(command_path).read_text())
        gateway.submit(request, 0.)
        conflict = dict(request, args={'seconds': 1., 'forward': -1.})
        gateway.submit(conflict, .1)
        gateway.finish(command_id, 'completed', 'drive_completed', 1.)
        transport.poll()
        self.assertEqual('completed', gateway.requests[command_id]['receipt']['status'])
        self.assertEqual('completed', transport.results[command_id]['status'])

    def test_stale_round_rejection_is_observable_by_the_request_producer(self):
        transport, gateway, identity, command_path = self.transport_and_gateway()
        command_id = transport.send('stop')
        request = json.loads(Path(command_path).read_text())
        identity['round_id'] = 'round-b'
        receipt = gateway.submit(request, 0.)
        self.assertEqual('stale_round_id', receipt['reason'])
        transport.poll()
        self.assertEqual('rejected', transport.results[command_id]['status'])
        self.assertEqual('stale_round_id', transport.results[command_id]['reason'])

    def test_float_player_identity_is_not_admitted_as_an_integer_player(self):
        controller = self.control()
        controller.active = True
        receipt = controller.gateway.submit(self.request(controller, 'stop', player_id=1.0), 0.)
        self.assertEqual('rejected', receipt['status'])
        self.assertTrue(controller.active)

    def test_request_history_limit_never_blocks_releasing_control(self):
        controller = self.control()
        controller.active = True
        for index in range(2049):
            controller.gateway.submit(self.request(controller, 'status', command_id='status-%d' % index), 0.)
        receipt = controller.gateway.submit(self.request(controller, 'stop', command_id='release'), 0.)
        self.assertEqual('completed', receipt['status'])
        self.assertFalse(controller.active)

    def test_fire_timeout_cancels_only_future_rounds_of_its_owned_burst(self):
        controller = self.control()
        now = [0.]
        controller.owner._clock = lambda: now[0]
        burst = {'group_seq': 12, 'count': 3, 'committed': 1}
        def shoot():
            controller.owner._local_player_burst = burst
            controller.shot_committed({'projectile_id': 'first-round', 'shell_index': 0},
                {'player_burst': burst, 'burst_group_seq': 12, 'burst_count': 3, 'reload_factor': 1.})
        controller.owner._avatar.shoot = shoot
        controller.owner._cancel_local_player_burst.side_effect = lambda **unused: setattr(
            controller.owner, '_local_player_burst', None)
        request = self.request(controller, 'fire', timeout_seconds=.1)
        receipt = controller.gateway.submit(request, 0.)
        self.assertEqual('accepted', receipt['status'])
        self.assertIs(burst, controller.owner._local_player_burst)
        now[0] = .2
        controller.gateway.tick(.2)
        self.assertEqual('failed', controller.gateway.requests['one']['receipt']['status'])
        self.assertEqual(1, controller.automatic_commits)
        self.assertIsNone(controller.owner._local_player_burst)

    def test_mission_arrival_and_failure_brakes_survive_outer_combat_facing(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller as navigation_controller, state
        for failure in (False, True):
            with self.subTest(task_failed=failure):
                control, target = PlayerRegressionTests().aim_controller()
                control.navigation = navigation_controller()
                control.owner.local_pose = lambda: ((-85., 0., 0.), 0.)
                control.owner._mutable_shot_ray = lambda: ((-85., 2., 0.), (0., 0., 1.))
                control.owner._local_speed = 0. if failure else .8
                target.position = (-50., 0., 50.)
                control.firing_lane = lambda unused: True
                control.navigation.start_mission('return_base',
                    {'command_id': 'return', 'timeout': .5 if failure else 180.}, state())
                with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned', return_value=True):
                    control.update(.1, 1.)
                mission = control.navigation.mission_status()
                self.assertEqual('failed' if failure else 'running', mission['status'])
                self.assertEqual('failed' if failure else 'arriving', mission['phase'])
                self.assertTrue(control.last_order['holding'])
                self.assertEqual('mission_hold', control.last_order['combat_mode'])
                # Native navigation requested a brake, but the caller must also
                # preserve it until arrival settles, or while the task failed.
                sender = control.owner._sender
                self.assertEqual((0., 0., True), (sender.forward, sender.turn, sender.handbrake))


    def test_final_blockage_requests_a_new_firing_position_on_next_update(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller as navigation_controller
        control, target = PlayerRegressionTests().aim_controller()
        control.navigation = navigation_controller()
        control.owner.local_pose = lambda: ((-85., 0., 0.), 0.)
        control.owner._mutable_shot_ray = lambda: ((-85., 2., 0.), (0., 0., 1.))
        target.position = (-85., 0., 40.)
        control.firing_lane = lambda unused: True
        control.lane_from = lambda *args: True
        control.dynamic_path_clear = mock.Mock(return_value=True)
        def admission(*args, **kwargs):
            control.fire_admission.receipt = dict(status='pending', reason='auto_friendly_lane')
            return False
        control.trigger = mock.Mock(side_effect=admission)

        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned',
                        return_value=True):
            control.update(.1, 1.)
            self.assertEqual(target.id, control.blocked_fire_target)
            control.update(.1, 1.2)
        self.assertEqual('firing_position', control.last_order['combat_mode'])
        control.dynamic_path_clear.assert_called()
        control.weapon.trigger.assert_not_called()


    def test_blocked_target_releases_combat_hold_without_a_side_position(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller as navigation_controller
        control, target = PlayerRegressionTests().aim_controller()
        control.navigation = navigation_controller()
        control.owner.local_pose = lambda: ((-85., 0., 0.), 0.)
        control.owner._mutable_shot_ray = lambda: ((-85., 2., 0.), (0., 0., 1.))
        target.position = (-85., 0., 40.)
        control.firing_lane = lambda unused: True
        control.navigation.firing_position = mock.Mock(return_value=None)
        control.combat_tactics.movement = mock.Mock(return_value=None)
        control.navigation.decide = mock.Mock(return_value=dict(
            throttle=1., turn=0., brake=False, recovery_mode='travel', combat_mode='route'))
        control.blocked_fire_target = target.id
        control.trigger = mock.Mock(return_value=False)
        control.fire_admission.receipt = dict(status='pending', reason='auto_friendly_lane')

        with mock.patch('gui.mods.offline_lan_0922.player_control.weapon.barrel_aligned',
                        return_value=True):
            control.update(.1, 1.)
        self.assertFalse(control.navigation.context['fire_clear'])
        self.assertFalse(control.navigation.decide.call_args.kwargs['hold'])

    def test_automatic_shell_requests_cannot_immediately_override_each_other(self):
        from test_player_control import PlayerRegressionTests
        control, unused = PlayerRegressionTests().aim_controller()
        clock = [1.]
        owner = control.owner
        owner._clock = lambda: clock[0]
        owner._local_fire_intent = None
        from types import SimpleNamespace
        owner._runtime = SimpleNamespace(constants=SimpleNamespace(
            VEHICLE_SETTING=SimpleNamespace(CURRENT_SHELLS=1, NEXT_SHELLS=2)))
        owner._gun_state.shots = [dict(shell=dict(compactDescr=i)) for i in range(3)]
        owner.change_vehicle_setting = mock.Mock()
        control.direct_engagement = object()
        control.queue_automatic_shell(2)
        clock[0] = 1.1
        control.queue_automatic_shell(1)
        clock[0] = 1.4
        control.queue_automatic_shell(1)
        self.assertEqual([mock.call(1, 2), mock.call(1, 1)],
                         owner.change_vehicle_setting.call_args_list)


    def test_turret_returns_forward_after_an_unusable_lock_persists(self):
        from test_player_control import PlayerRegressionTests
        from types import SimpleNamespace
        control, target = PlayerRegressionTests().aim_controller()
        control.direct_engagement = SimpleNamespace(target=target.id,
            update=lambda *args: (None, None, False))
        control.update(.1, 1.)
        control.update(.1, 2.)
        control.weapon.forward.assert_not_called()
        control.update(.1, 2.6)
        control.weapon.forward.assert_called_once()


    def test_pending_direct_scan_preserves_turret_and_leaves_route_in_control(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller as navigation_controller
        from types import SimpleNamespace
        control, target = PlayerRegressionTests().aim_controller()
        control.navigation = navigation_controller()
        control.direct_engagement = SimpleNamespace(target=target.id, checking=True,
            retreat=False, seek=False, update=lambda *args: (None, None, False))
        control.navigation.firing_position = mock.Mock(return_value=None)
        control.navigation.decide = mock.Mock(return_value=dict(
            throttle=1., turn=.4, brake=False, recovery_mode='travel', combat_mode='route'))
        control.update(.1, 1.)
        control.update(.1, 3.)
        control.weapon.forward.assert_not_called()
        self.assertFalse(control.navigation.decide.call_args.kwargs['hold'])
        self.assertEqual((1., .4, False),
            (control.last_order['throttle'], control.last_order['turn'], control.last_order['brake']))


    def test_established_engagement_stays_parked_through_scan_gap_then_expires(self):
        from test_player_control import PlayerRegressionTests
        from test_player_navigation_migration import controller as navigation_controller
        from types import SimpleNamespace
        control, target = PlayerRegressionTests().aim_controller()
        control.navigation = navigation_controller()
        control.navigation.firing_position = mock.Mock(return_value=None)
        control.navigation.decide = mock.Mock(side_effect=lambda *a, **kw:
            dict(throttle=0. if kw['hold'] else 1., turn=0., brake=kw['hold'],
                 holding=kw['hold'], recovery_mode='hold' if kw['hold'] else 'travel',
                 combat_mode='engage' if kw['hold'] else 'route'))
        control.combat_tactics.movement = mock.Mock(return_value=None)
        control.direct_engagement = SimpleNamespace(target=target.id, checking=True,
            retreat=False, seek=False, update=lambda *args: (None, None, False))
        control.engagement_hold = (target, 5.)
        control.update(.1, 2.)
        self.assertTrue(control.navigation.decide.call_args.kwargs['hold'])
        self.assertEqual((0., True), (control.last_order['throttle'], control.last_order['brake']))
        control.update(.1, 5.1)
        self.assertFalse(control.navigation.decide.call_args.kwargs['hold'])
        self.assertIsNone(control.engagement_hold)

    def test_front_contact_adopts_front_vehicle_and_defers_rear_sample(self):
        from test_player_control import PlayerRegressionTests
        from types import SimpleNamespace
        control, rear = PlayerRegressionTests().aim_controller()
        front = SimpleNamespace(id=rear.id + 1, position=rear.position)
        records = {rear.id: rear, front.id: front}
        control._contacts = lambda unused: ([], [], records)
        engagement = SimpleNamespace(target=rear.id, seek=False, retreat=False,
            update=lambda *args: (None, None, False))
        engagement.adopt = lambda identity: setattr(engagement, 'target', identity)
        control.direct_engagement = engagement
        control.aiming.defer_front_point = mock.Mock()
        solution = dict(sample=2)
        control.fire_admission.front_contact = (rear, front.id, solution, 1.)
        control.update(.1, 1.1)
        control.aiming.defer_front_point.assert_called_once_with(rear, front, solution)
        self.assertEqual(front.id, engagement.target)


    def test_combat_facing_brakes_then_turns_and_waits_for_rotation_to_stop(self):
        from gui.mods.offline_lan_0922.player_control.tactics import CombatFacing
        facing = CombatFacing()
        clear = mock.Mock(return_value=True)
        state = dict(position=(0., 0., 0.), now=1., speed=2.)
        order = {}
        self.assertTrue(facing.apply(order, state, 8, 1., .2, 0., clear, lambda: ()))
        self.assertTrue(order['brake'])
        clear.assert_not_called()
        state.update(now=1.5, speed=0.)
        self.assertTrue(facing.apply(order, state, 8, 1., .2, 0., clear, lambda: ()))
        self.assertEqual((0., 1., False), (order['throttle'], order['turn'], order['brake']))
        state['now'] = 2.
        self.assertTrue(facing.apply(order, state, 8, .1, .2, .25, clear, lambda: ()))
        self.assertEqual('settling', order['combat_facing']['state'])
        state['now'] = 2.2
        self.assertFalse(facing.apply(order, state, 8, .1, .2, 0., clear, lambda: ()))
        self.assertEqual('aligned', order['combat_facing']['state'])

    def test_blocked_combat_facing_releases_fire_and_does_not_keep_pivoting(self):
        from gui.mods.offline_lan_0922.player_control.tactics import CombatFacing
        facing = CombatFacing()
        clear = mock.Mock(return_value=False)
        state = dict(position=(0., 0., 0.), now=1., speed=0.)
        obstacles = ['ally']
        order = {}
        self.assertFalse(facing.apply(order, state, 8, .8, .2, 0., clear, lambda: tuple(obstacles)))
        self.assertEqual('blocked', order['combat_facing']['state'])
        self.assertEqual((0., 0., True), (order['throttle'], order['turn'], order['brake']))
        state['now'] = 3.
        self.assertFalse(facing.apply(order, state, 8, .8, .2, 0., clear, lambda: tuple(obstacles)))
        clear.assert_called_once()
        obstacles[:] = []
        clear.return_value = True
        self.assertTrue(facing.apply(order, state, 8, .8, .2, 0., clear, lambda: tuple(obstacles)))
        self.assertEqual('turning', order['combat_facing']['state'])


if __name__ == '__main__':
    unittest.main()
