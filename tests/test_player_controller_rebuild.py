"""Foreground ownership and actual full-runtime consumer regressions.

RuntimeBoundary isolates the wrapper protocol only. NativeRuntime and mission
cases use the complete copied loop with explicit native I/O observations;
neither fixture establishes Windows BigWorld physics acceptance.
"""
import ast
import copy
import itertools
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

import test_player_control_completion as completion
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.commands import MISSIONS


class NavigationObservation(object):
    def __init__(self):
        self.mission = dict(id=None, status='idle', phase='idle')
        self.finished = []

    def mission_status(self):
        return dict(self.mission)

    def finish_battle(self, result, now):
        self.finished.append((result, now))


class RuntimeBoundary(object):
    def __init__(self):
        self.navigation = NavigationObservation()
        self.active = self.closed = False
        self.weapon = None
        self.confirmed_facing = object()
        self.capture_pivot_circle = (1., 2., 3.)
        self.calls = []
        self.order = dict(throttle=1., turn=.25, combat_mode='copied')
        self.start_hook = self.update_hook = self.stop_hook = None
        self.authorizations = []

    def attach(self):
        self.calls.append(('attach',))
        return True

    def start(self, features, mission=None):
        self.calls.append(('start', frozenset(features), mission))
        self.active = True
        if self.start_hook:
            return self.start_hook()
        return True

    def stop(self, reason='manual'):
        self.calls.append(('stop', reason))
        self.active = False
        if self.stop_hook:
            return self.stop_hook()
        return True

    def close(self):
        self.calls.append(('close',))
        self.active = False
        self.closed = True

    def update(self, dt, now):
        self.calls.append(('update', dt, now))
        if self.update_hook:
            return self.update_hook(dt, now)
        return self.status()

    def status(self):
        return dict(order=dict(self.order), aim=dict(source='native'),
            target=dict(engine_id=42), navigation=dict(receipt='copied'),
            mission=self.navigation.mission_status())

    def set_mission(self, kind, payload=None):
        self.calls.append(('mission', kind, dict(payload or {})))
        self.navigation.mission = dict(id=payload['command_id'], action=kind,
            status='running', phase='travelling')
        return self.navigation.mission_status()

    def mission_preflight(self, kind, payload=None):
        return None

    def authorize_trigger(self, context, entity=None, gun=None, shot_ray=None):
        self.authorizations.append((context, entity, gun, shot_ray))
        return None

    def drive_contact(self, *args):
        self.calls.append(('contact',) + args)

    def attacked(self, *args):
        self.calls.append(('attacked',) + args)

    def shot_committed(self, *args):
        self.calls.append(('shot_committed',) + args)

    def shot_hit(self, *args):
        self.calls.append(('shot_hit',) + args)

    def shot_terminal(self, *args):
        self.calls.append(('shot_terminal',) + args)

    def fire_rejected(self, *args):
        self.calls.append(('fire_rejected',) + args)


class FullControllerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = completion.ForegroundCompletionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.control = self.fixture.control()
        self.owner = self.control.owner
        self.runtime = RuntimeBoundary()
        self.control.runtime = self.runtime

    def submit(self, action, identity='one', **values):
        request = self.fixture.request(self.control, action, identity=identity, **values)
        return self.control.gateway.submit(request, self.fixture.now[0])

    def test_wrapper_imports_no_legacy_automatic_policy(self):
        source = Path(__import__(PlayerControl.__module__, fromlist=['x']).__file__)
        tree = ast.parse(source.read_text())
        forbidden = {'navigation', 'weapon', 'aiming', 'ammunition', 'strategy',
            'traffic', 'targeting', 'tactics', 'hull_alignment', 'direct_engagement',
            'fire_admission', 'wrecks', 'pathfinding', 'parking', 'cover'}
        imports = {node.module for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.level == 1}
        self.assertFalse(imports & forbidden, imports & forbidden)
        self.assertIn('full_runtime', imports)

    def test_every_live_frame_reaches_full_loop_without_wrapper_cadence_or_dt_clamp(self):
        self.assertTrue(self.control.toggle())
        for dt, now in ((.007, .007), (.003, .010), (1.4, 1.410)):
            self.fixture.now[0] = now
            self.control.update(dt, now)
        calls = [row for row in self.runtime.calls if row[0] == 'update']
        self.assertEqual([('update', .007, .007), ('update', .003, .010),
                          ('update', 1.4, 1.410)], calls)
        self.assertEqual(self.runtime.order, self.control.last_order)
        self.assertEqual(42, self.control.target_engine)
        self.assertIs(self.runtime.navigation, self.control.navigation)
        self.assertIs(self.runtime.confirmed_facing, self.control.confirmed_facing)
        self.assertEqual(self.runtime.capture_pivot_circle, self.control.capture_pivot_circle)

    def test_all_mission_commands_reach_same_runtime_and_keep_actual_observation_pending(self):
        for index, action in enumerate(sorted(MISSIONS)):
            identity = 'mission-%d' % index
            row = self.submit(action, identity=identity)
            self.assertEqual('accepted', row['status'])
            self.assertEqual(identity, self.control.mission_command)
            self.assertEqual('running', self.control.navigation.mission_status()['status'])
        missions = [row for row in self.runtime.calls if row[0] == 'mission']
        self.assertEqual(sorted(MISSIONS), [row[1] for row in missions])
        self.assertEqual(1, sum(row[0] == 'start' for row in self.runtime.calls))
        last_id = self.control.mission_command
        self.runtime.navigation.mission.update(status='completed', phase='holding')
        self.fixture.now[0] = 1.
        self.control.update(.1, 1.)
        self.assertEqual('completed', self.control.gateway.requests[last_id]['receipt']['status'])

    def test_behavior_runtime_failure_stops_future_control_without_reduced_fallback(self):
        self.assertTrue(self.control.toggle())
        def fail(dt, now):
            raise RuntimeError('full_loop_probe_failed')
        self.runtime.update_hook = fail
        self.control.update(.3, .3)
        self.assertFalse(self.control.active)
        self.assertIn('full_loop_probe_failed', self.control.last_control_failure)
        self.assertEqual({}, self.control.last_order)
        self.assertEqual(1, sum(row[0] == 'update' for row in self.runtime.calls))
        self.control.update(.3, .6)
        self.assertEqual(1, sum(row[0] == 'update' for row in self.runtime.calls))

    def test_stop_during_native_update_cannot_publish_its_retired_order(self):
        self.assertTrue(self.control.toggle())
        def stop_then_return(dt, now):
            self.control.stop('query_reentry_stop')
            return dict(order=dict(throttle=1., turn=1.), target=999,
                        aim=dict(aligned=True))
        self.runtime.update_hook = stop_then_return
        self.control.update(.1, .1)
        self.assertFalse(self.control.active)
        self.assertEqual({}, self.control.last_order)
        self.assertIsNone(self.control.target_engine)
        self.assertEqual((0., 0.), (self.owner._sender.forward, self.owner._sender.turn))

    def test_start_reentered_by_stop_cannot_reacquire_native_ownership(self):
        def start():
            self.control.stop('source_setter_stop')
            return True
        self.runtime.start_hook = start
        self.assertFalse(self.control.toggle())
        self.assertFalse(self.control.active)
        self.assertIsNone(self.control.navigation)
        self.assertTrue(any(row[0] == 'stop' for row in self.runtime.calls))

    def test_failed_native_cleanup_blocks_new_start_and_retries_without_busy_loop(self):
        self.assertTrue(self.control.toggle())
        failures = [True]
        def stop():
            if failures:
                failures.pop()
                raise RuntimeError('native_source_busy')
            return True
        self.runtime.stop_hook = stop
        self.assertFalse(self.control.stop('test_stop'))
        self.assertFalse(self.control.toggle())
        self.control.update(.1, .5)
        self.assertEqual(1, sum(row[0] == 'stop' for row in self.runtime.calls))
        self.control.update(.1, 1.1)
        self.assertEqual(2, sum(row[0] == 'stop' for row in self.runtime.calls))
        self.assertFalse(self.control.release_pending)
        self.assertTrue(self.control.toggle())

    def test_native_contacts_and_damage_feedback_reach_full_runtime(self):
        self.assertTrue(self.control.toggle())
        contact = dict(collision=True, actor='ally')
        self.control.drive_contact((1., 2., 3.), .7, .1, True, contact)
        self.control.attacked(47, dict(damage=10))
        self.assertIn(('contact', (1., 2., 3.), .7, .1, True, contact), self.runtime.calls)
        self.assertIn(('attacked', 47, dict(damage=10)), self.runtime.calls)

    def test_team_observation_requires_existing_current_runtime_and_never_activates_it(self):
        callback = self.runtime.observe_team_observation = mock.Mock(return_value=True)
        self.control._runtime_binding = self.control._native_binding()
        message = dict(round_id=self.owner._start_message['round_id'], contacts=[])
        self.assertTrue(self.control.bot_observation(message, 1.))
        callback.assert_called_once_with(message, 1.)
        self.assertFalse(self.control.active)
        self.assertFalse(self.runtime.active)
        self.assertIsNone(self.control.navigation)
        callback.reset_mock()
        for invalid in ({}, dict(message, round_id='retired'), None):
            self.assertFalse(self.control.bot_observation(invalid, 2.))
        self.control.runtime = None
        self.assertFalse(self.control.bot_observation(message, 3.))
        self.assertIsNone(self.control.runtime)
        callback.assert_not_called()

    def test_team_observation_cannot_cross_native_replacement_or_turn_rejection_into_stop(self):
        self.assertTrue(self.control.toggle())
        callback = self.runtime.observe_team_observation = mock.Mock(
            side_effect=ValueError('invalid observed contact'))
        message = dict(round_id=self.owner._start_message['round_id'], contacts=[])
        self.assertFalse(self.control.bot_observation(message, 1.))
        self.assertTrue(self.control.active)
        callback.reset_mock()
        self.owner._gun_state = copy.copy(self.owner._gun_state)
        self.assertFalse(self.control.bot_observation(message, 2.))
        callback.assert_not_called()
        self.assertTrue(self.control.active)

    def test_invalid_local_drive_does_not_release_existing_full_runtime_owner(self):
        self.assertTrue(self.control.toggle())
        before = list(self.runtime.calls)
        for args in ({'seconds': 0}, {'forward': 2}, {'turn': float('nan')}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.control.command(dict(action='drive', **args), 0.)
        self.assertTrue(self.control.active)
        self.assertEqual(before, self.runtime.calls)
        self.assertEqual((1., .3), (self.owner._sender.forward, self.owner._sender.turn))

    def test_override_remains_owned_without_automatic_drive_feature(self):
        self.control.features = {'fire'}
        self.control.override = (3., 1., 0.)
        self.assertTrue(self.control.owns_drive())
        self.assertFalse(self.control.owns_automatic_drive())
        self.assertTrue(self.control.stop('explicit_drive_release'))
        self.assertEqual((0., 0., False), (self.owner._sender.forward,
            self.owner._sender.turn, self.owner._sender.handbrake))
        self.assertFalse(self.control.owns_drive())

    def test_cleanup_failure_cannot_latch_owned_movement_or_republish_old_target(self):
        self.assertTrue(self.control.toggle())
        self.control.update(.1, .1)
        failures = [True]
        def stop():
            if failures:
                failures.pop()
                raise RuntimeError('native close failed')
            return True
        self.runtime.stop_hook = stop
        self.assertFalse(self.control.stop('controller_error'))
        self.assertEqual((0., 0., False), (self.owner._sender.forward,
            self.owner._sender.turn, self.owner._sender.handbrake))
        self.assertFalse(self.control.owns_drive())
        self.control.publish_status(.2, force=True)
        self.assertIsNone(self.fixture.rows[-1]['aim'])
        self.assertIsNone(self.control.target_engine)
        self.assertEqual({}, self.control.last_order)
        self.control.retry_releases(1.2)
        self.assertFalse(self.control.release_pending)

    def test_rejected_fire_retry_cannot_become_an_unreported_later_shot(self):
        gun = self.owner._gun_state
        gun.reload_time = 5.
        request = self.fixture.request(self.control, 'fire', identity='rejected-fire')
        first = self.control.gateway.submit(request, 0.)
        self.assertEqual(('rejected', 'gun_not_ready'), (first['status'], first['reason']))
        gun.reload_time = 0.
        self.owner._avatar.shoot = mock.Mock()
        second = self.control.gateway.submit(request, 1.)
        self.assertEqual(first, second)
        self.owner._avatar.shoot.assert_not_called()

    def test_float_identity_and_full_history_cannot_steal_or_block_emergency_stop(self):
        self.assertTrue(self.control.toggle())
        bad = self.fixture.request(self.control, 'stop', identity='wrong-type', player_id=1.0)
        self.assertEqual('rejected', self.control.gateway.submit(bad, 0.)['status'])
        self.assertTrue(self.control.active)
        for index in range(2049):
            self.submit('status', identity='status-%d' % index)
        self.assertEqual('completed', self.submit('stop', identity='release')['status'])
        self.assertFalse(self.control.active)

    def test_real_journal_drains_oversize_before_executing_and_acknowledging_stop(self):
        self.assertTrue(self.control.toggle())
        with tempfile.TemporaryDirectory() as directory:
            command_path, result_path = Path(directory) / 'commands.jsonl', Path(directory) / 'results.jsonl'
            command_path.write_bytes(b'x' * 5000 + b'\n' + json.dumps(
                self.fixture.request(self.control, 'stop', identity='journal-stop')).encode('utf8') + b'\n')
            with mock.patch.dict(os.environ, dict(
                    WOT_OFFLINE_TEST_CONTROL_FILE=str(command_path),
                    WOT_OFFLINE_TEST_CONTROL_RESULT_FILE=str(result_path))):
                self.control.gateway.emit = lambda row: PlayerControl.emit_result(self.control, row)
                self.control.poll_commands(0.)
                rows = [json.loads(line) for line in result_path.read_text().splitlines()]
        self.assertFalse(self.control.active)
        self.assertEqual(['accepted', 'completed'],
            [row['status'] for row in rows if row.get('id') == 'journal-stop'])

    def test_keyboard_and_mouse_takeover_claim_only_live_enabled_input_channels(self):
        import gui.mods.offline_lan_0922.player_control as module
        class Handler(object):
            def handleKeyEvent(self, event):
                return 'manual'
        self.owner._avatar.inputHandler = handler = Handler()
        self.control.input_available = lambda: True
        modules = dict(Keys=types.SimpleNamespace(KEY_GRAVE=41, KEY_LEFTMOUSE=256, KEY_RIGHTMOUSE=257),
                       game=types.SimpleNamespace(convertKeyEvent=lambda value: value))
        with mock.patch.dict(sys.modules, modules), mock.patch.object(module, '_current', self.control):
            PlayerControl.bind_input(self.control)
            for active, fire in itertools.product((False, True), repeat=2):
                self.control.active, self.control.features = active, {'fire'} if fire else set()
                for key in (256, 257):
                    self.assertEqual(True if active and fire else 'manual',
                                     handler.handleKeyEvent((True, key, 0, False)))
            self.control.active = False
            self.control.features = {'fire'}
            self.owner._battle_live = False
            self.assertFalse(module.handle_key(True, 41))
            self.assertFalse(self.control.key_down)
            self.owner._battle_live = True
            self.assertTrue(module.handle_key(True, 41))
            self.assertTrue(self.control.active)
            self.assertTrue(module.handle_key(True, 41))
            self.assertTrue(self.control.active)
            module.handle_key(False, 41)
            module.handle_key(True, 41)
            self.assertFalse(self.control.active)
        self.control.close()
        self.assertEqual('manual', handler.handleKeyEvent(None))

    def test_native_mailbox_keeps_all_eight_masks_and_exact_automatic_trigger_token(self):
        from test_port_0922_battle_runtime import _LANInputSender
        control, owner = self.control, self.owner
        owner.shoot = mock.Mock(return_value=True)
        for enabled in itertools.product((False, True), repeat=3):
            names = {name for name, on in zip(('drive', 'fire', 'consumables'), enabled) if on}
            with self.subTest(features=names):
                control.active, control.features = True, names
                control.native_triggering, control.trigger_context = False, None
                sender = _LANInputSender(owner)
                sender.send_current = lambda: True
                sender.send_avatar_input(1, 'move', dict(flags=1))
                self.assertEqual(0 if 'drive' in names else 1, sender.forward)
                self.assertEqual('fire' not in names, sender.send_avatar_input(1, 'shoot', {}))
                control.native_triggering = True
                self.assertEqual('fire' not in names, sender.send_avatar_input(1, 'shoot', {}))
                control.trigger_context = {}
                self.assertTrue(sender.send_avatar_input(1, 'shoot', {}))

    def test_worker_and_replay_cannot_attach_foreground_decisions(self):
        import gui.mods.offline_lan_0922.player_control as module
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_PLAYER_AUTOCONTROL': 'drive,fire'}):
            for worker, replay in ((True, False), (False, True), (True, True)):
                self.assertIsNone(module.attach(types.SimpleNamespace(
                    _worker_mode=worker, _replay_mode=replay)))

    def test_conflicting_retry_keeps_original_terminal_in_real_producer_journal(self):
        from gui.mods.offline_lan_0922.player_control.commands import append_result
        with tempfile.TemporaryDirectory() as directory:
            commands, results = Path(directory) / 'commands.jsonl', Path(directory) / 'results.jsonl'
            commands.write_bytes(b'')
            identity = self.control.identity()
            append_result(str(results), dict(identity, type='status', live=True, active=False))
            transport = completion.PlayerControlTransport(str(commands), str(results),
                identity['session_id'], wall_clock=lambda: 1000.)
            self.control.gateway.emit = lambda row: append_result(str(results), row)
            command_id = transport.send('drive', dict(seconds=1., forward=1.))
            request = json.loads(commands.read_text())
            self.assertEqual('accepted', self.control.gateway.submit(request, 0.)['status'])
            conflict = dict(request, args=dict(seconds=1., forward=-1.))
            self.assertEqual('rejected', self.control.gateway.submit(conflict, .1)['status'])
            self.fixture.now[0] = 1.1
            self.control.update(.1, 1.1)
            transport.poll()
            self.assertEqual('completed', self.control.gateway.requests[command_id]['receipt']['status'])
            self.assertEqual('completed', transport.results[command_id]['status'])

    def test_stale_round_rejection_is_visible_to_real_request_producer(self):
        from gui.mods.offline_lan_0922.player_control.commands import append_result
        with tempfile.TemporaryDirectory() as directory:
            commands, results = Path(directory) / 'commands.jsonl', Path(directory) / 'results.jsonl'
            commands.write_bytes(b'')
            identity = self.control.identity()
            append_result(str(results), dict(identity, type='status', live=True, active=False))
            transport = completion.PlayerControlTransport(str(commands), str(results),
                identity['session_id'], wall_clock=lambda: 1000.)
            self.control.gateway.emit = lambda row: append_result(str(results), row)
            command_id = transport.send('stop')
            request = json.loads(commands.read_text())
            self.owner._start_message['round_id'] = 'next-round'
            self.assertEqual('stale_round_id', self.control.gateway.submit(request, 0.)['reason'])
            transport.poll()
            self.assertEqual('rejected', transport.results[command_id]['status'])
            self.assertEqual('stale_round_id', transport.results[command_id]['reason'])

    def _accepted_fire(self, committed=True, submitting=False):
        request = self.fixture.request(self.control, 'fire', identity='trigger')
        self.control.gateway.requests['trigger'] = dict(command=request,
            receipt=dict(self.control.identity(), id='trigger', action='fire',
                         status='accepted', reason='validated'), deadline=20.)
        self.control.fire_command = 'trigger'
        context = dict(command='trigger', projectiles=['p1'] if committed else [],
            generation=self.control.control_generation, trigger_sequence=1,
            submission_in_progress=submitting, target=42)
        burst = dict(group_seq=1, count=3, committed=1 if committed else 0,
                     player_control=context)
        self.owner._local_player_burst = burst
        self.control.owned_burst = burst
        self.control.trigger_context = context
        return burst, context

    def test_stop_keeps_committed_fire_command_and_physical_clock_owned_by_battle(self):
        burst, context = self._accepted_fire()
        original = dict(burst)
        self.control.stop('explicit_stop')
        self.assertIs(burst, self.owner._local_player_burst)
        self.assertEqual(original['committed'], burst['committed'])
        self.owner._cancel_local_player_burst.assert_not_called()
        self.assertTrue(context['controller_detached'])
        self.assertEqual('explicit_stop', context['stop_requested'])
        self.assertEqual('accepted', self.control.gateway.requests['trigger']['receipt']['status'])
        self.assertEqual('trigger', self.control.fire_command)

    def test_stop_during_submission_waits_for_real_acceptance_outcome(self):
        burst, context = self._accepted_fire(committed=False, submitting=True)
        self.control.stop('send_callback_stop')
        self.assertEqual('accepted', self.control.gateway.requests['trigger']['receipt']['status'])
        self.assertIs(burst, self.owner._local_player_burst)
        self.assertTrue(context['controller_detached'])
        context['submission_in_progress'] = False
        self.control.fire_rejected('launch_send_failed')
        self.assertEqual('failed', self.control.gateway.requests['trigger']['receipt']['status'])

    def test_stop_before_first_submission_cancels_only_uncommitted_request(self):
        self._accepted_fire(committed=False)
        self.control.stop('preflight_stop')
        self.assertEqual('cancelled', self.control.gateway.requests['trigger']['receipt']['status'])
        self.owner._cancel_local_player_burst.assert_not_called()

    def test_release_observation_never_cancels_or_debits_committed_trigger(self):
        burst, context = self._accepted_fire()
        ammo = copy.deepcopy(self.owner._gun_state.ammo)
        self.control.release_burst(burst)
        self.assertIs(burst, self.owner._local_player_burst)
        self.assertEqual(1, burst['committed'])
        self.assertEqual(ammo, self.owner._gun_state.ammo)
        self.owner._cancel_local_player_burst.assert_not_called()
        self.assertTrue(context['controller_detached'])

    def test_physical_failure_supplies_terminal_without_reclassifying_stop(self):
        burst, context = self._accepted_fire()
        self.control.stop('stop_future_control')
        self.control.trigger_terminated(burst, 'gun_unavailable')
        receipt = self.control.gateway.requests['trigger']['receipt']
        self.assertEqual(('failed', 'gun_unavailable'), (receipt['status'], receipt['reason']))
        self.assertEqual(1, receipt['result']['committed'])
        self.assertEqual(['p1'], receipt['result']['projectile_ids'])
        self.owner._cancel_local_player_burst.assert_not_called()

    def test_new_automatic_trigger_keeps_full_runtime_candidate_and_uses_native_avatar_entry(self):
        self.assertTrue(self.control.toggle())
        observed = []
        def native():
            observed.append(dict(self.control.trigger_context))
            return False
        candidate = dict(point=(1., 2., 3.), pose='current')
        with mock.patch.object(self.control, '_native_trigger', side_effect=native):
            self.assertFalse(self.control.issue_automatic_trigger(
                dict(target=dict(engine_id=42), candidate=candidate), 1.))
        self.assertEqual(1, len(observed))
        self.assertIs(candidate, observed[0]['candidate'])
        self.assertIs(self.runtime, observed[0]['runtime'])
        self.assertTrue(observed[0]['automatic'])
        self.assertIsNone(observed[0]['command'])
        self.assertIsNone(self.control.trigger_context)

    def test_admission_calls_forward_only_to_new_trigger_service(self):
        admission = mock.Mock()
        self.control.trigger_admission = admission
        context, entity, gun, ray, shot = {}, object(), object(), object(), object()
        self.control.prepare_trigger(context, entity, gun, ray, .02, shot, 5.,
                                     range_origin=(1., 2., 3.))
        admission.prepare.assert_called_once_with(context, entity, gun, ray, .02,
            shot, 5., range_origin=(1., 2., 3.))
        token, launch = object(), object()
        self.control.validate_trigger(token, context, entity, gun, 5., launch=launch)
        admission.validate.assert_called_once_with(token, context, entity, gun, 5., launch=launch)
        self.control.trigger_committed(token)
        admission.committed.assert_called_once_with(token)


class NativeRuntimeOwnershipTests(unittest.TestCase):
    """The real full runtime must also satisfy native release contracts."""
    def scene(self):
        import test_player_fire_admission_complete as fixture
        session = mock.patch.dict(os.environ, {'WOT_OFFLINE_TEST_CONTROL_SESSION': 'controller-rebuild'})
        session.start()
        self.addCleanup(session.stop)
        scene = fixture.AutomaticFireScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.battle._avatar.inputHandler.handleKeyEvent = lambda *args: None
        return scene

    def unbound_scene(self, features=('drive', 'fire')):
        from test_player_manual_aim import ObservedRotator
        scene = self.scene()
        self.assertTrue(scene.control.stop('install_native_boundary'))
        previous = scene.battle._avatar.gunRotator
        source = previous.shotPointSourceFunctor
        rotator = ObservedRotator(source)
        rotator.getCurShotPosition = previous.getCurShotPosition
        scene.battle._avatar.gunRotator = rotator
        scene.control.features = set(features)
        return scene, rotator, source

    def test_stop_during_each_native_install_edge_blocks_nested_restart_and_late_write(self):
        for boundary in ('auto_aim', 'source_before', 'source_after', 'mode_before'):
            with self.subTest(boundary=boundary):
                scene, rotator, source = self.unbound_scene()
                control = scene.control
                observations = []
                def stop_once(unused):
                    if boundary == 'auto_aim':
                        scene.battle._avatar.autoAim = lambda unused: None
                    else:
                        setattr(rotator, boundary, None)
                    observations.append((control.active, control.runtime.active))
                    control.stop('native_setter_stop')
                    observations.append(control.toggle())
                if boundary == 'auto_aim':
                    scene.battle._avatar.autoAim = stop_once
                else:
                    setattr(rotator, boundary, stop_once)
                self.assertFalse(control.toggle())
                self.assertEqual([(True, True), False], observations)
                self.assertFalse(control.active)
                self.assertFalse(control.runtime.active)
                self.assertIsNone(control.navigation)
                self.assertFalse(control.release_pending)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)

    def test_entity_gun_rotator_and_round_replacement_cannot_complete_native_start(self):
        for changed, boundary in itertools.product(
                ('entity', 'gun', 'rotator', 'round'),
                ('source_before', 'source_after', 'mode_before')):
            with self.subTest(changed=changed, boundary=boundary):
                scene, rotator, source = self.unbound_scene()
                control, owner = scene.control, scene.battle
                def replace_once(unused):
                    setattr(rotator, boundary, None)
                    if changed == 'entity':
                        owner._runtime.bigworld.entities[scene.entity.id] = copy.copy(scene.entity)
                    elif changed == 'gun':
                        owner._gun_state = copy.copy(owner._gun_state)
                    elif changed == 'rotator':
                        owner._avatar.gunRotator = copy.copy(rotator)
                    else:
                        owner._start_message = dict(owner._start_message, round_id='replaced-round')
                setattr(rotator, boundary, replace_once)
                self.assertFalse(control.toggle())
                self.assertFalse(control.active)
                self.assertFalse(control.runtime.active)
                self.assertIsNone(control.navigation)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                self.assertFalse(control.release_pending)

    def test_each_native_install_failure_releases_only_its_partial_source_and_mode(self):
        for boundary in ('auto_aim', 'source_before', 'source_after', 'mode_before'):
            with self.subTest(boundary=boundary):
                scene, rotator, source = self.unbound_scene()
                def fail_once(unused):
                    if boundary == 'auto_aim':
                        scene.battle._avatar.autoAim = lambda unused: None
                    else:
                        setattr(rotator, boundary, None)
                    raise RuntimeError('native install failure')
                if boundary == 'auto_aim':
                    scene.battle._avatar.autoAim = fail_once
                else:
                    setattr(rotator, boundary, fail_once)
                self.assertFalse(scene.control.toggle())
                self.assertFalse(scene.control.active)
                self.assertFalse(scene.runtime.active)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)
                self.assertFalse(scene.control.release_pending)

    def test_source_restore_failure_can_retry_mode_but_never_overwrite_foreign_owner(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                scene, rotator, source = self.unbound_scene()
                control = scene.control
                self.assertTrue(control.toggle())
                def fail_mode_once(value):
                    if not value:
                        rotator.mode_before = None
                        raise RuntimeError('native mode restore failed')
                rotator.mode_before = fail_mode_once
                self.assertFalse(control.stop())
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertTrue(rotator.clientMode)
                replacement = lambda: (7., 8., 9.)
                if foreign:
                    rotator.shotPointSourceFunctor = replacement
                scene.fixture.now += 1.1
                control.retry_releases(scene.now)
                self.assertFalse(control.release_pending)
                self.assertIs(replacement if foreign else source, rotator.shotPointSourceFunctor)
                self.assertEqual(foreign, rotator.clientMode)

    def test_cleanup_barrier_covers_input_and_native_source_release_callbacks(self):
        for boundary in ('input', 'source'):
            with self.subTest(boundary=boundary):
                scene, rotator, source = self.unbound_scene()
                control = scene.control
                self.assertTrue(control.toggle())
                attempts = []
                if boundary == 'input':
                    def send():
                        attempts.append(control.toggle())
                        return True
                    scene.battle._sender.send_current = send
                else:
                    def restore(value):
                        if value is source:
                            attempts.append(control.toggle())
                    rotator.source_after = restore
                self.assertTrue(control.stop('release_barrier'))
                self.assertTrue(attempts)
                self.assertFalse(any(attempts))
                self.assertFalse(control.active)
                self.assertFalse(control.release_pending)
                self.assertIs(source, rotator.shotPointSourceFunctor)
                self.assertFalse(rotator.clientMode)

    def test_fire_only_start_releases_explicit_halt_or_timed_drive_before_takeover(self):
        for previous in ('halt', 'drive'):
            with self.subTest(previous=previous):
                scene, unused_rotator, unused_source = self.unbound_scene(('fire',))
                control, owner = scene.control, scene.battle
                control.halted = previous == 'halt'
                control.override = (10., 1., 0.) if previous == 'drive' else None
                owner._sender.forward, owner._sender.turn = 1., .3
                owner._sender.handbrake = True
                self.assertTrue(control.owns_drive())
                self.assertTrue(control.toggle())
                self.assertIsNone(control.override)
                self.assertFalse(control.halted)
                self.assertFalse(control.owns_drive())
                self.assertEqual((0., 0., False), (owner._sender.forward,
                    owner._sender.turn, owner._sender.handbrake))

    def test_partial_source_release_retries_native_mode_without_losing_owner(self):
        import test_player_fire_admission_complete as fixture
        scene = self.scene()
        control = scene.control
        self.assertTrue(control.stop('install_native_fixture'))
        class FlakyMode(fixture.SourceRotator):
            def __init__(self, **values):
                self.refuse_restore = False
                super(FlakyMode, self).__init__(**values)

            def __setattr__(self, name, value):
                if name == 'clientMode' and not value and getattr(self, 'refuse_restore', False):
                    object.__setattr__(self, 'refuse_restore', False)
                    raise RuntimeError('native mode restoration busy')
                object.__setattr__(self, name, value)
        rotator = FlakyMode(**vars(scene.battle._avatar.gunRotator))
        rotator.clientMode = False
        saved_source = rotator.shotPointSourceFunctor
        scene.battle._avatar.gunRotator = rotator
        self.assertTrue(control.toggle())
        self.assertTrue(rotator.clientMode)
        rotator.refuse_restore = True
        self.assertFalse(control.stop('test_partial_native_release'))
        self.assertIs(saved_source, rotator.shotPointSourceFunctor)
        self.assertTrue(rotator.clientMode)
        self.assertTrue(control.release_pending)
        scene.fixture.now += 1.1
        control.update(.1, scene.now)
        self.assertFalse(control.release_pending)
        self.assertFalse(rotator.clientMode)
        self.assertIs(saved_source, rotator.shotPointSourceFunctor)

    def test_complete_runtime_start_stop_masks_preserve_unowned_manual_drive(self):
        scene = self.scene()
        control, owner = scene.control, scene.battle
        self.assertTrue(control.stop('reset_features'))
        saved_source = owner._avatar.gunRotator.shotPointSourceFunctor
        masks = ((), ('drive',), ('fire',), ('consumables',),
                 ('drive', 'fire'), ('drive', 'consumables'),
                 ('fire', 'consumables'), ('drive', 'fire', 'consumables'))
        for features in masks:
            with self.subTest(features=features):
                owner._sender.forward, owner._sender.turn = 1., .3
                owner._sender.handbrake = False
                control.features = set(features)
                if not features:
                    self.assertFalse(control.toggle())
                    self.assertEqual((1., .3), (owner._sender.forward, owner._sender.turn))
                    continue
                self.assertTrue(control.toggle(), control.last_control_failure)
                source = owner._avatar.gunRotator.shotPointSourceFunctor
                self.assertEqual('fire' in features, source is not saved_source)
                self.assertTrue(control.stop('test_mask'))
                self.assertIs(saved_source, owner._avatar.gunRotator.shotPointSourceFunctor)
                expected = (0., 0.) if 'drive' in features else (1., .3)
                self.assertEqual(expected, (owner._sender.forward, owner._sender.turn))

    def test_invalid_real_mission_does_not_preempt_existing_timed_drive(self):
        scene, unused_rotator, unused_source = self.unbound_scene(('drive',))
        control, owner = scene.control, scene.battle
        control.gateway.emit = lambda row: True
        control.gateway.wall_clock = lambda: 1000.
        control.override = (10., 1., 0.)
        previous = control.override
        owner._sender.forward, owner._sender.turn = 1., .3
        request = dict(control.identity(), id='invalid-goal', action='hold_position',
            args=dict(position=(1000., 0., 0.)), timeout_seconds=15.,
            replace=True, expires_at=1005.)
        receipt = control.gateway.submit(request, scene.now)
        self.assertEqual(('failed', 'destination_outside_arena'),
                         (receipt['status'], receipt['reason']))
        self.assertEqual(previous, control.override)
        self.assertFalse(control.active)
        self.assertIsNone(scene.runtime._mission)
        self.assertEqual((1., .3), (owner._sender.forward, owner._sender.turn))

    def test_native_identity_retirement_rebuilds_a_fresh_runtime_on_next_start(self):
        for changed in ('entity', 'gun', 'avatar', 'rotator', 'round'):
            with self.subTest(changed=changed):
                scene = self.scene()
                control, owner, previous = scene.control, scene.battle, scene.runtime
                old_engine, old_policy = previous.engine, previous.attack_policy
                old_policy.search_started = scene.now
                previous._move_episode = dict(legacy='retired-intent')
                if changed == 'entity':
                    owner._runtime.bigworld.entities[scene.entity.id] = copy.copy(scene.entity)
                elif changed == 'gun':
                    owner._gun_state = copy.copy(owner._gun_state)
                elif changed in ('avatar', 'rotator'):
                    old_rotator = owner._avatar.gunRotator
                    replacement = copy.copy(old_rotator)
                    replacement.shotPointSourceFunctor = lambda: (0., 2., 0.)
                    replacement.clientMode = False
                    if changed == 'avatar':
                        owner._avatar = copy.copy(owner._avatar)
                        owner._avatar.inputHandler = copy.copy(owner._avatar.inputHandler)
                        owner._avatar.inputHandler.handleKeyEvent = lambda *args: None
                    owner._avatar.gunRotator = replacement
                else:
                    owner._start_message = dict(owner._start_message, round_id='new-native-round')
                scene.fixture.now += .11
                control.update(.11, scene.now)
                self.assertFalse(control.active)
                self.assertFalse(previous.active)
                self.assertIsNone(control.navigation)
                self.assertIsNone(control.target_engine)
                self.assertEqual({}, control.last_order)
                self.assertTrue(control.toggle(), control.last_control_failure)
                current = control.runtime
                self.assertIsNot(previous, current)
                self.assertIsNot(old_engine, current.engine)
                self.assertIsNot(old_policy, current.attack_policy)
                self.assertIsNone(current.attack_policy.search_started)
                self.assertIsNone(current._move_episode)
                self.assertTrue(previous.closed)
                self.assertTrue(current.active)
                self.assertEqual(0, control.automatic_commits)

    def test_native_source_retirement_releases_wrapper_ownership_without_old_status(self):
        scene = self.scene()
        control = scene.control
        replacement = lambda: (9., 8., 7.)
        scene.battle._avatar.gunRotator.shotPointSourceFunctor = replacement
        scene.fixture.now += .11
        control.update(.11, scene.now)
        self.assertFalse(control.active)
        self.assertFalse(scene.runtime.active)
        self.assertFalse(control.owns_drive())
        self.assertIsNone(control.navigation)
        self.assertIsNone(control.target_engine)
        self.assertEqual({}, control.last_order)
        self.assertIs(replacement, scene.battle._avatar.gunRotator.shotPointSourceFunctor)
        self.assertEqual(0, control.automatic_commits)


    def test_stop_inside_real_attach_releases_late_planner_before_a_clean_restart(self):
        scene = self.scene()
        scene.control.close()
        control = PlayerControl(scene.battle, ('drive', 'fire'), notify=lambda unused: None)
        control.record = lambda *args, **kwargs: None
        control.emit_result = lambda *args, **kwargs: True
        scene.battle._player_control = control
        self.addCleanup(control.close)
        observed, original = [], scene.battle.local_pose
        def stop_during_pose():
            runtime = control.runtime
            if runtime is not None and runtime.engine is None and not observed:
                observed.append(runtime)
                control.stop('native_pose_during_attach')
            return original()
        scene.battle.local_pose = stop_during_pose
        self.assertFalse(control.toggle())
        self.assertEqual(1, len(observed))
        self.assertIsNotNone(observed[0].engine)
        self.assertTrue(observed[0].closed)
        self.assertFalse(control.active)
        self.assertIsNone(control.runtime)
        self.assertFalse(control.release_pending)
        self.assertTrue(control.toggle(), control.last_control_failure)
        self.assertIsNot(observed[0], control.runtime)
        self.assertTrue(control.active)
        self.assertTrue(control.runtime.active)

    def test_old_projectile_rejection_settles_after_restart_without_new_failure(self):
        scene = self.scene()
        control, battle = scene.control, scene.battle
        self.assertTrue(scene.fire())
        self.assertTrue(scene.advance(.1))
        self.assertTrue(scene.advance(.1))
        self.assertEqual(3, len(scene.launches()))
        self.assertTrue(control.active)
        launch = scene.launches()[0]
        projectile_id = launch['projectile_id']
        receipt = control.shot_receipts.get(projectile_id)
        old_generation = receipt['generation']
        self.assertTrue(control.stop('restart_before_launch_result'))
        self.assertTrue(control.toggle(), control.last_control_failure)
        self.assertNotEqual(old_generation, control.control_generation)
        self.assertIsNone(control.last_fire_failure)
        self.assertIsNone(control.runtime.status()['aim']['failure'])
        gun = battle._gun_state
        before = (list(gun.ammo), gun.clip, gun.reload_time)
        observed = []
        control.emit_result = observed.append

        self.assertTrue(battle.on_fire_intent_result(dict(
            round_id=battle._start_message['round_id'], accepted=False,
            projectile_id=projectile_id, intent_seq=launch['fire_intent_seq'],
            reason='old_launch_denied')))

        self.assertTrue(control.active)
        self.assertTrue(control.runtime.active)
        self.assertIsNone(control.last_fire_failure)
        self.assertIsNone(control.runtime.status()['aim']['failure'])
        self.assertEqual(before, (list(gun.ammo), gun.clip, gun.reload_time))
        self.assertEqual('rejected', receipt['flight_status'])
        self.assertEqual('old_launch_denied', receipt['reason'])
        self.assertEqual(scene.now, receipt['finished_at'])
        rejected = [event for event in observed if event.get('type') == 'shot'
                    and event.get('projectile_id') == projectile_id]
        self.assertEqual(['rejected'], [event['status'] for event in rejected])
        self.assertNotIn(projectile_id, battle._projectile_meta)
        self.assertEqual(2, len(scene.launches()))

    def test_current_projectile_rejection_updates_runtime_and_settles_receipt(self):
        scene = self.scene()
        control, battle = scene.control, scene.battle
        self.assertTrue(scene.fire())
        self.assertTrue(scene.advance(.1))
        self.assertTrue(scene.advance(.1))
        launch = scene.launches()[0]
        projectile_id = launch['projectile_id']
        receipt = control.shot_receipts.get(projectile_id)
        self.assertEqual(control.control_generation, receipt['generation'])
        self.assertEqual(control.trigger_sequence, receipt['trigger_sequence'])
        gun = battle._gun_state
        before = (list(gun.ammo), gun.clip, gun.reload_time)
        observed = []
        control.emit_result = observed.append

        self.assertTrue(battle.on_fire_intent_result(dict(
            round_id=battle._start_message['round_id'], accepted=False,
            projectile_id=projectile_id, intent_seq=launch['fire_intent_seq'],
            reason='current_launch_denied')))

        self.assertTrue(control.active)
        self.assertTrue(control.runtime.active)
        self.assertEqual('current_launch_denied', control.last_fire_failure)
        self.assertEqual('current_launch_denied', control.runtime.status()['aim']['failure'])
        self.assertEqual(before, (list(gun.ammo), gun.clip, gun.reload_time))
        self.assertEqual('rejected', receipt['flight_status'])
        self.assertEqual('current_launch_denied', receipt['reason'])
        self.assertEqual(scene.now, receipt['finished_at'])
        rejected = [event for event in observed if event.get('type') == 'shot'
                    and event.get('projectile_id') == projectile_id]
        self.assertEqual(['rejected'], [event['status'] for event in rejected])
        self.assertNotIn(projectile_id, battle._projectile_meta)
        self.assertEqual(2, len(scene.launches()))

    def test_delayed_physical_tail_observation_keeps_control_and_next_trigger_live(self):
        scene = self.scene()
        control, battle = scene.control, scene.battle
        gun = battle._gun_state
        generation = control.control_generation
        self.assertTrue(scene.fire())
        self.assertTrue(scene.advance(.3))
        self.assertEqual([0, 1, 2], [row['burst_index'] for row in scene.launches()])
        self.assertEqual([17, 10], gun.ammo)
        self.assertEqual(3, gun.clip)
        self.assertIsNone(battle._local_player_burst)
        self.assertTrue(control.active, control.last_control_failure)
        self.assertTrue(control.runtime.active)
        self.assertEqual(generation, control.control_generation)
        self.assertIsNone(control.last_control_failure)

        self.assertFalse(scene.advance(.6))
        scene.lay()
        self.assertTrue(scene.fire())
        self.assertTrue(scene.advance(.3))
        self.assertEqual([0, 1, 2, 0, 1, 2],
                         [row['burst_index'] for row in scene.launches()])
        self.assertEqual([14, 10], gun.ammo)
        self.assertEqual(0, gun.clip)
        self.assertIsNone(battle._local_player_burst)
        self.assertEqual(6, control.shot_commits)
        self.assertEqual(2, control.trigger_sequence)
        self.assertEqual(generation, control.control_generation)
        self.assertTrue(control.active, control.last_control_failure)
        self.assertTrue(control.runtime.active)
        self.assertIsNone(control.last_control_failure)


class FullRuntimeMissionOwnershipTests(unittest.TestCase):
    def scene(self, siege=False):
        import test_player_limited_traverse as fixture
        scene = fixture.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        if siege:
            scene.control.close()
            descriptor = scene.entity.typeDescriptor
            descriptor.type.name = 'sweden:S11_Strv_103B'
            descriptor.hasSiegeMode = True
            descriptor.siegeVehicleDescr = copy.deepcopy(descriptor)
            descriptor.defaultVehicleDescr = descriptor
            scene.entity.siegeState = 0
            for row in scene.battle._records.values():
                if row.get('local'):
                    row['vehicle'] = descriptor.type.name
                    row['state']['vehicle'] = descriptor.type.name
            scene.battle._runtime.constants.VEHICLE_SIEGE_STATE = types.SimpleNamespace(
                DISABLED=0, SWITCHING_ON=1, ENABLED=2, SWITCHING_OFF=3)
        scene.configure(rate=0., bearing=.7)
        scene.battle._local_support_rise_blocked = False
        scene.battle._last_snapshot = dict(capture_bases={
            '1': [dict(id='1:0', x=0., y=0., z=0., radius=12.)],
            '2': [dict(id='2:0', x=0., y=0., z=40., radius=12.)]})
        return scene

    def test_actual_return_arrival_brake_cannot_be_replaced_by_outer_hull_aiming(self):
        scene = self.scene()
        scene.battle._local_speed = .8
        scene.runtime.set_mission('return_base', dict(timeout=180.))
        for unused in range(6):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            mission = scene.runtime.mission_status()
            self.assertEqual(('running', 'arriving'), (mission['status'], mission['phase']))
            self.assertEqual((0., 0., True), row['sender'], row)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_status_reads_real_mission_terminal_after_stop_and_never_relabels_an_old_round(self):
        scene = self.scene()
        scene.runtime.set_mission('attack', dict(position=(0., 0., 24.)))
        scene.tick()
        self.assertEqual('running', scene.control.runtime_status['mission']['status'])
        self.assertTrue(scene.control.stop('manual_terminal'))
        rows = []
        scene.control.emit_result = rows.append
        scene.control.publish_status(scene.now, force=True)
        self.assertEqual('cancelled', rows[-1]['mission']['status'])
        self.assertEqual('manual_terminal', rows[-1]['mission']['reason'])
        self.assertFalse(rows[-1]['active'])
        self.assertIsNone(rows[-1]['aim'])
        self.assertIsNone(rows[-1]['navigation'])
        scene.battle._start_message = dict(scene.battle._start_message, round_id='new-round')
        scene.control.publish_status(scene.now, force=True)
        self.assertIsNone(rows[-1]['mission'])

    def test_actual_failed_mission_releases_firing_hull_owner_before_final_native_input(self):
        scene = self.scene()
        scene.runtime.set_mission('return_base', dict(timeout=.05))
        for unused in range(12):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            self.assertEqual('failed', scene.runtime.mission_status()['status'])
            self.assertEqual((0., 0., True), row['sender'], row)
            self.assertFalse(row['order'].get('fire_allowed'))
        self.assertEqual(0, scene.control.automatic_commits)

    def test_supported_running_and_completed_holds_reach_real_native_siege_request(self):
        for action, status in (('defend_base', 'running'), ('hold_position', 'completed')):
            with self.subTest(action=action):
                scene = self.scene(siege=True)
                request = mock.Mock(wraps=scene.battle._request_player_control_siege)
                scene.battle._request_player_control_siege = request
                scene.runtime.set_mission(action, dict(timeout=180.))
                for unused in range(16):
                    row = scene.tick()
                    self.assertIsNone(scene.control.last_control_failure, row)
                self.assertEqual(status, scene.runtime.mission_status()['status'])
                self.assertTrue(scene.runtime.mission_status()['holding'])
                request.assert_called_once_with(True, mock.ANY)
                self.assertTrue(scene.battle._local_siege_pending or scene.battle._local_siege_braking)

    def test_failed_or_cancelled_mission_cannot_admit_a_new_native_siege_transition(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                scene = self.scene(siege=True)
                request = mock.Mock(wraps=scene.battle._request_player_control_siege)
                scene.battle._request_player_control_siege = request
                scene.runtime.set_mission('return_base', dict(timeout=.05 if not cancelled else 180.))
                if cancelled:
                    scene.control.stop('cancelled_mission')
                for unused in range(16):
                    scene.tick()
                self.assertEqual('cancelled' if cancelled else 'failed',
                                 scene.runtime.mission_status()['status'])
                request.assert_not_called()
                self.assertIsNone(scene.battle._local_siege_pending)
                self.assertIsNone(scene.battle._local_siege_braking)

    def test_empty_clip_current_stock_and_total_inventory_remain_distinct(self):
        from gui.mods.offline_lan_0922.player_control.capabilities import ammunition_state
        scene = self.scene()
        gun = scene.battle._gun_state
        gun.clip, gun.reload_time = 0, 40.
        self.assertEqual('reloading', ammunition_state(gun)['state'])
        self.assertFalse(ammunition_state(gun)['empty'])
        gun.ammo = [0, 10]
        self.assertEqual('shell_empty', ammunition_state(gun)['state'])
        self.assertFalse(ammunition_state(gun)['empty'])
        gun.ammo = [0, 0]
        self.assertEqual('empty', ammunition_state(gun)['state'])
        self.assertTrue(ammunition_state(gun)['empty'])

    def test_unknown_native_inventory_never_becomes_empty_or_an_actual_shot(self):
        scene = self.scene()
        scene.battle._gun_state.ammo = None
        for unused in range(4):
            scene.tick()
        self.assertEqual('unknown', scene.control.ammo_state['state'])
        self.assertFalse(scene.control.ammo_state['empty'])
        self.assertFalse(scene.control.ammo_state['can_fire'])
        self.assertEqual(0, scene.control.automatic_commits)
        self.assertFalse(scene.launches())
        self.assertIsNone(scene.battle._gun_state.ammo)

    def test_real_total_exhaustion_leaves_combat_hold_for_copied_capture_navigation(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        gun.ammo, gun.clip = [0, 0], 0
        scene.runtime.set_mission('attack', dict(position=(0., 0., 24.)))
        moving = False
        for unused in range(10):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            moving = moving or bool(row['sender'][0] or row['sender'][1])
            self.assertFalse(row['order'].get('fire_allowed'))
        self.assertEqual('capture_base', scene.runtime.mission_status()['action'])
        self.assertEqual((0., 0., 40.), scene.runtime.mission_status()['destination'])
        self.assertEqual('empty', scene.control.ammo_state['state'])
        self.assertTrue(moving, scene.trace[-3:])
        self.assertIsNone(scene.runtime.attack_policy.decision.get('candidate'))
        self.assertEqual([0, 0], gun.ammo)
        self.assertEqual(0, scene.control.automatic_commits)

    def test_idle_native_barrel_follows_current_chassis_heading_without_a_fire_target(self):
        scene = self.scene()
        scene.target.health = 0
        scene.battle._records['bot:%s' % scene.target.id]['state'].update(health=0, alive=False)
        scene.rotator_enabled = True
        rotator = scene.battle._avatar.gunRotator
        scene.runtime.set_mission('hold_position', dict(timeout=180.))
        for heading in (1.1, -.8):
            scene.set_hull(heading)
            rotator.turretYaw, rotator.gunPitch = .15, .1
            for unused in range(15):
                row = scene.tick()
                self.assertIsNone(scene.control.last_control_failure, row)
            self.assertAlmostEqual(0., rotator.turretYaw, places=6)
            self.assertAlmostEqual(0., rotator.gunPitch, places=6)
            self.assertAlmostEqual(math.sin(heading), scene.direction[0], places=6)
            self.assertAlmostEqual(math.cos(heading), scene.direction[2], places=6)
            self.assertIsNone(scene.runtime.weapon.target)
            self.assertIsNotNone(scene.runtime.weapon.source_point)
            self.assertFalse(row['order'].get('fire_allowed'))
        self.assertEqual(0, scene.control.automatic_commits)

    def test_full_planner_preserves_observed_bank_pose_for_forward_and_reverse_heading_queries(self):
        from test_player_fire_admission_complete import Pose
        class BankPose(Pose):
            @property
            def roll(self):
                return math.atan2(self.rows[0][1], self.rows[1][1])
        for heading in (0., math.pi):
            with self.subTest(heading=heading):
                scene = self.scene()
                self.assertTrue(scene.control.stop('install_native_bank_fixture'))
                scene.control.features = set(('drive',))
                self.assertTrue(scene.control.toggle())
                scene.runtime = scene.control.runtime
                scene.target.health = 0
                scene.battle._records['bot:%s' % scene.target.id]['state'].update(health=0, alive=False)
                body, bank = BankPose(), BankPose()
                body.setRotateYPR((0., .3, 0.))
                bank.rows = ((math.cos(.2), math.sin(.2), 0.),
                             (-math.sin(.2), math.cos(.2), 0.), (0., 0., 1.))
                body.preMultiply(bank)
                scene.body = scene.entity.matrix = body
                scene.battle._local_matrix = scene.battle._local_pose_matrix = body
                scene.battle._local_terrain_pitch = scene.battle._local_pitch = .3
                scene.battle._local_roll = .2
                probe = mock.Mock(wraps=scene.runtime.engine.direction_probe)
                scene.runtime.engine.direction_probe = probe
                scene.runtime.set_mission('attack', dict(position=(
                    math.sin(heading) * 24., 0., math.cos(heading) * 24.)))
                # The native Matrix fixture must preserve all three measured
                # angles; the earlier admission fixture deliberately had no roll.
                with mock.patch.object(scene.battle._runtime.math, 'Matrix', BankPose):
                    scene.fixture.now += .11
                    scene.control.update(.11, scene.now)
                self.assertIsNone(scene.control.last_control_failure)
                matching = [call for call in probe.call_args_list
                            if abs(call.args[1] - heading) < 1.e-6]
                self.assertTrue(matching, probe.call_args_list)
                for call in matching:
                    self.assertEqual((0., .3, .2), call.args[7])
                self.assertEqual(0, scene.control.automatic_commits)


class FullRuntimeSiegeOwnershipTests(unittest.TestCase):
    scene = NativeRuntimeOwnershipTests.scene
    unbound_scene = NativeRuntimeOwnershipTests.unbound_scene

    def siege_scene(self):
        scene, unused_rotator, unused_source = self.unbound_scene(('drive',))
        control, owner = scene.control, scene.battle
        scene.entity.typeDescriptor.hasSiegeMode = True
        scene.entity.typeDescriptor.siegeVehicleDescr = copy.deepcopy(scene.entity.typeDescriptor)
        scene.entity.typeDescriptor.defaultVehicleDescr = scene.entity.typeDescriptor
        scene.entity.siegeState = 0
        owner._runtime.constants.VEHICLE_SIEGE_STATE = types.SimpleNamespace(
            DISABLED=0, ENABLED=1, SWITCHING_ON=2, SWITCHING_OFF=3)
        owner._local_siege_pending = owner._local_siege_braking = None
        owner._player_control_siege_observer = None
        owner._local_siege_request_token = None
        owner._local_speed, owner._local_turn_speed = 2., 0.
        owner._report_local_siege_edge = mock.Mock()
        self.assertTrue(control.toggle(), control.last_control_failure)
        scene.runtime = control.runtime
        return scene

    @staticmethod
    def request_mode(scene):
        return scene.runtime.engine._set_bot_siege_state(scene.runtime.state, 2)

    def test_previous_observer_stop_revokes_new_request_before_brake(self):
        scene = self.siege_scene()
        owner, control = scene.battle, scene.control
        owner._player_control_siege_observer = dict(token=object(), enabled=False,
            callback=lambda *args: control.stop('previous_observer_stop'))
        self.assertFalse(self.request_mode(scene))
        self.assertFalse(control.active)
        self.assertIsNone(owner._local_siege_braking)
        self.assertIsNone(owner._player_control_siege_observer)
        self.assertIsNone(scene.runtime._siege_pending)
        owner._report_local_siege_edge.assert_not_called()

    def test_native_braking_callback_stop_cannot_resurrect_automatic_owner(self):
        scene = self.siege_scene()
        scene.battle._report_local_siege_edge = lambda *args, **kwargs: (
            scene.control.stop('native_braking_stop'))
        self.request_mode(scene)
        self.assertFalse(scene.control.active)
        self.assertFalse(scene.runtime.active)
        self.assertIsNone(scene.runtime._siege_pending)
        self.assertIsNone(scene.battle._local_siege_braking)
        self.assertIsNone(scene.battle._player_control_siege_observer)

    def test_replacement_observer_and_brake_survive_retired_runtime_stop(self):
        scene = self.siege_scene()
        owner, replacement, replaced = scene.battle, mock.Mock(), []
        def report(*args, **kwargs):
            if not replaced:
                replaced.append(True)
                owner._request_player_control_siege(True, replacement)
        owner._report_local_siege_edge = report
        self.request_mode(scene)
        self.assertIs(replacement, owner._player_control_siege_observer['callback'])
        self.assertIs(owner._local_siege_braking, True)
        self.assertIsNone(scene.runtime._siege_pending)
        scene.control.stop('retired_siege_request')
        self.assertIs(replacement, owner._player_control_siege_observer['callback'])
        self.assertIs(owner._local_siege_braking, True)
        replacement.assert_not_called()

    def test_submitted_transition_remains_native_owned_after_stop(self):
        scene = self.siege_scene()
        owner = scene.battle
        owner._local_speed = 0.
        owner._sender.send_current = mock.Mock(return_value=17)
        self.assertTrue(self.request_mode(scene))
        owner._sender.send_current.assert_called_with(siege_enabled=True, sequence_result=True)
        self.assertEqual((True, 17), owner._local_siege_pending)
        self.assertTrue(scene.control.stop('submitted_native_siege'))
        self.assertEqual((True, 17), owner._local_siege_pending)
        self.assertIsNone(scene.runtime._siege_pending)
        self.assertFalse(scene.control.release_pending)

    def test_exact_observer_release_failure_is_retried_without_touching_new_owner(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                scene = self.siege_scene()
                owner = scene.battle
                self.request_mode(scene)
                callback = owner._player_control_siege_observer['callback']
                cancel, attempts = owner._cancel_player_control_siege, []
                def fail_once(observer):
                    attempts.append(observer)
                    if len(attempts) == 1:
                        raise RuntimeError('native cancellation unavailable')
                    return cancel(observer)
                owner._cancel_player_control_siege = fail_once
                self.assertFalse(scene.control.stop('retry_siege_observer'))
                self.assertTrue(scene.control.release_pending)
                self.assertIs(owner._local_siege_braking, True)
                replacement = mock.Mock()
                if foreign:
                    owner._request_player_control_siege(True, replacement)
                scene.fixture.now += 1.1
                scene.control.retry_releases(scene.now)
                self.assertFalse(scene.control.release_pending)
                self.assertIs(attempts[0], callback)
                if foreign:
                    self.assertIs(replacement, owner._player_control_siege_observer['callback'])
                    self.assertIs(owner._local_siege_braking, True)
                else:
                    self.assertEqual([callback, callback], attempts)
                    self.assertIsNone(owner._player_control_siege_observer)
                    self.assertIsNone(owner._local_siege_braking)


if __name__ == '__main__':
    unittest.main()
