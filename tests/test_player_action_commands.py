"""Actual foreground action receipts; native presentation remains a boundary."""
import copy
import json
import types
import unittest
from unittest import mock

import test_player_control_completion as completion
import test_port_0922_battle_runtime as runtime_fixture

from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.missions import Mission
from gui.mods.offline_lan_0922.player_control.test_actions import MAX_WATCHERS, TestActions


class ObservedMissionNavigation(object):
    """Keep the real Mission lifecycle while omitting route-planner geometry."""
    def __init__(self, clock):
        self.clock = clock
        self.mission = None
        self.receipt = dict(status='test_navigation')

    def validate_mission(self, action, args, state):
        return Mission(args['command_id'], action, args, state, None, None).snapshot()

    def start_mission(self, action, args, state):
        if self.mission is not None:
            self.mission.finish('cancelled', 'replaced', state['now'])
        self.mission = Mission(args['command_id'], action, args, state, None, None)
        self.mission.observe(state, dict(supported=True), 0.)
        return self.mission_status()

    def mission_status(self):
        return self.mission.snapshot() if self.mission else dict(id=None, status='idle', phase='idle')

    def close(self):
        if self.mission is not None:
            self.mission.finish('cancelled', 'navigation_closed', self.clock())


class ActionHarness(object):
    def setUp(self):
        self.fixture = completion.ForegroundCompletionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.control = self.fixture.control(features=())
        self.actions = self.control.test_actions
        self.sequence = 0

    def submit(self, action, args, command_id=None, timeout=15.):
        self.sequence += 1
        command_id = command_id or 'action-%s' % self.sequence
        request = self.fixture.request(self.control, action, identity=command_id,
                                       args=args, timeout_seconds=timeout)
        return self.control.gateway.submit(request, self.fixture.now[0])

    def observe(self, now):
        self.fixture.now[0] = now
        self.actions.update(now)

    def receipt(self, command_id):
        return self.control.gateway.requests[command_id]['receipt']

    def admit_mission(self, command_id='mission-one', timeout=15.):
        self.control.features.add('drive')
        self.control.active = True
        if self.control.navigation is None:
            self.control.navigation = ObservedMissionNavigation(lambda: self.fixture.now[0])
        row = self.submit('hold_position', dict(position=(10., 0., 0.)), command_id, timeout)
        self.assertEqual('accepted', row['status'])
        return self.control.navigation.mission

    def fire_group(self, command_id, identities, completed=True, include_list=True):
        receipt = dict(self.control.identity(), type='command', id=command_id, action='fire',
                       status='completed' if completed else 'accepted', reason='shot_committed')
        if include_list:
            receipt['result'] = dict(projectile_ids=list(identities), stage='local_committed')
        self.control.gateway.requests[command_id] = dict(receipt=receipt)
        for identity in identities:
            self.control.shot_receipts.committed(dict(projectile_id=identity, shell_index=0),
                dict(burst_group_seq=7, burst_count=len(identities)),
                dict(command=command_id, target=42), 0., 0)


class ActionObservationTests(ActionHarness, unittest.TestCase):
    def test_assertion_reads_actual_gun_instead_of_cached_status_and_distinguishes_unknown(self):
        self.control.ammo_state = dict(available=True, empty=True, can_fire=False)
        ready = self.submit('assert_state', dict(condition='ammo_ready'))
        self.assertEqual('completed', ready['status'])
        not_empty = self.submit('assert_state', dict(condition='ammo_empty'))
        self.assertEqual('failed', not_empty['status'])
        self.assertTrue(not_empty['result']['known'])
        self.assertFalse(not_empty['result']['value'])
        self.control.owner._gun_state = None
        unknown = self.submit('assert_state', dict(condition='ammo_empty'))
        self.assertEqual('failed', unknown['status'])
        self.assertFalse(unknown['result']['known'])
        self.assertEqual('observation_unavailable', unknown['reason'])

    def test_readers_are_allowed_nonlive_without_stopping_or_sending_drive(self):
        self.control.owner._battle_live = False
        self.control.override = (20., 1., .3)
        self.control.stop = mock.Mock()
        initial = (self.control.owner._sender.forward, self.control.owner._sender.turn)
        row = self.submit('assert_state', dict(condition='active', value=False))
        self.assertEqual('completed', row['status'])
        self.submit('wait_state', dict(condition='active', value=True), 'wait', timeout=1.)
        self.observe(1.)
        self.assertEqual('failed', self.receipt('wait')['status'])
        self.control.stop.assert_not_called()
        self.control.owner._sender.send_current.assert_not_called()
        self.assertEqual(initial, (self.control.owner._sender.forward, self.control.owner._sender.turn))
        self.assertEqual((20., 1., .3), self.control.override)

    def test_waiter_observes_stop_without_binding_control_generation(self):
        self.control.active = True
        self.submit('wait_state', dict(condition='active', value=False), 'wait')
        self.control.stop('manual')
        self.assertIn('wait', self.actions.watchers)
        self.observe(.1)
        self.assertEqual('completed', self.receipt('wait')['status'])
        self.assertFalse(self.actions.watchers)

    def test_timeout_is_checked_before_a_newly_matching_observation(self):
        self.submit('wait_state', dict(condition='active', value=True), 'wait', timeout=1.)
        self.control.active = True
        self.observe(1.)
        self.assertEqual(('failed', 'command_timeout'),
                         (self.receipt('wait')['status'], self.receipt('wait')['reason']))
        self.control.gateway.tick(1.)
        self.assertEqual(1, sum(row.get('id') == 'wait' and row.get('status') == 'failed'
                                for row in self.fixture.rows))

    def test_limit_cancel_and_bounded_snapshot_do_not_grab_control(self):
        for index in range(MAX_WATCHERS):
            self.assertEqual('accepted', self.submit('wait_state',
                dict(condition='active', value=True), 'wait-%s' % index)['status'])
        rejected = self.submit('wait_state', dict(condition='active', value=True))
        self.assertEqual('observation_limit', rejected['reason'])
        asserted = self.submit('assert_state', dict(condition='active', value=False))
        self.assertEqual('completed', asserted['status'])
        command = self.control.gateway.requests['wait-0']['command']
        self.actions.cancel(command, 'test_cancel')
        self.assertEqual('cancelled', self.receipt('wait-0')['status'])
        self.assertEqual('accepted', self.submit('wait_state',
            dict(condition='active', value=True))['status'])
        snapshot = self.actions.snapshot()
        self.assertEqual(MAX_WATCHERS, snapshot['watcher_count'])
        self.assertLess(len(json.dumps(snapshot)), 3000)
        self.assertFalse(self.actions.busy)
        self.control.owner._sender.send_current.assert_not_called()

    def test_identity_is_frozen_and_late_new_round_state_cannot_complete_waiter(self):
        identity = dict(self.control.identity())
        self.control.identity = lambda: identity
        self.submit('wait_state', dict(condition='active', value=True), 'wait')
        identity['round_id'] = 'another-round'
        self.control.active = True
        self.observe(.1)
        self.assertEqual(('cancelled', 'identity_changed'),
                         (self.receipt('wait')['status'], self.receipt('wait')['reason']))
        self.assertFalse(self.actions.watchers)

    def test_close_cancels_all_waiters_and_prevents_new_admission(self):
        self.submit('wait_state', dict(condition='active', value=True), 'wait')
        self.actions.close(.1)
        self.assertEqual('cancelled', self.receipt('wait')['status'])
        self.assertEqual('controller_closed', self.submit('assert_state',
            dict(condition='active', value=False))['reason'])

    def test_halt_requires_current_supported_rest_not_a_stale_settled_flag(self):
        self.control.halted = True
        first = self.submit('assert_state', dict(condition='halted'))
        self.assertFalse(first['result']['matched'])
        self.fixture.now[0] = .6
        rested = self.submit('assert_state', dict(condition='halted'))
        self.assertEqual('completed', rested['status'])
        self.control.owner._local_vertical_speed = -5.
        self.fixture.now[0] = .7
        moving = self.submit('assert_state', dict(condition='halted'))
        self.assertEqual('failed', moving['status'])
        self.assertFalse(moving['result']['halt']['settled'])
        del self.control.owner._local_vertical_speed
        unavailable = self.submit('assert_state', dict(condition='halted'))
        self.assertFalse(unavailable['result']['known'])

    def test_mission_identity_cannot_be_satisfied_by_an_unrelated_replacement(self):
        mission = dict(id='replacement', status='completed', phase='holding')
        self.control.navigation = types.SimpleNamespace(mission_status=lambda: mission)
        row = self.submit('assert_state', dict(condition='mission_status',
                                              value='completed', command_id='original'))
        self.assertEqual('failed', row['status'])
        self.assertFalse(row['result']['known'])
        self.control.gateway.requests['original'] = dict(receipt=dict(self.control.identity(),
            action='hold_position', status='completed', result=dict(id='original',
            status='completed', phase='holding', reason='arrived_and_held')))
        row = self.submit('assert_state', dict(condition='mission_phase',
                                              value='holding', command_id='original'))
        self.assertEqual('completed', row['status'])
        self.assertEqual('original', row['result']['mission']['id'])

    def test_mission_without_identity_reads_current_idle_or_phase(self):
        self.assertEqual('completed', self.submit('assert_state',
            dict(condition='mission_status', value='idle'))['status'])
        self.control.navigation = types.SimpleNamespace(mission_status=lambda:
            dict(id='mission', status='running', phase='capturing'))
        self.assertEqual('completed', self.submit('assert_state',
            dict(condition='mission_phase', value='capturing'))['status'])

    def test_named_mission_status_observes_real_stop_without_final_snapshot(self):
        mission = self.admit_mission()
        self.submit('wait_state', dict(condition='mission_status', value='cancelled',
                                      command_id='mission-one'), 'wait')
        self.assertEqual('completed', self.submit('stop', {})['status'])
        self.observe(.1)
        self.assertEqual('cancelled', mission.status)
        self.assertNotIn('result', self.receipt('mission-one'))
        self.assertIsNone(self.control.navigation)
        result = self.receipt('wait')
        self.assertEqual('completed', result['status'])
        self.assertEqual('command_terminal', result['result']['source'])
        self.assertEqual('cancelled', result['result']['value'])
        self.assertNotIn('phase', result['result']['mission'])

    def test_named_mission_status_observes_real_timeout_and_replacement(self):
        mission = self.admit_mission(timeout=1.)
        self.submit('wait_state', dict(condition='mission_status', value='failed',
                                      command_id='mission-one'), 'timeout-wait')
        self.fixture.now[0] = 1.
        self.control.gateway.tick(1.)
        self.observe(1.)
        self.assertEqual('failed', self.receipt('mission-one')['status'])
        self.assertEqual('completed', self.receipt('timeout-wait')['status'])
        self.assertEqual('command_terminal', self.receipt('timeout-wait')['result']['source'])
        self.admit_mission('mission-two')
        self.submit('wait_state', dict(condition='mission_status', value='cancelled',
                                      command_id='mission-two'), 'replace-wait')
        replacement = self.admit_mission('mission-three')
        self.observe(1.1)
        self.assertEqual('completed', self.receipt('replace-wait')['status'])
        self.assertEqual('mission-two', self.receipt('replace-wait')['result']['mission']['id'])
        self.assertEqual('accepted', self.receipt('mission-three')['status'])
        self.assertEqual('running', replacement.status)

    def test_missing_terminal_phase_is_explicitly_unavailable_not_invented(self):
        self.admit_mission()
        self.submit('wait_state', dict(condition='mission_phase', value='cancelled',
                                      command_id='mission-one'), 'wait')
        self.submit('stop', {})
        self.observe(.1)
        row = self.receipt('wait')
        self.assertEqual(('failed', 'mission_phase_unavailable'), (row['status'], row['reason']))
        self.assertFalse(row['result']['known'])
        self.assertTrue(row['result']['impossible'])
        self.assertEqual('command_terminal', row['result']['source'])
        self.assertNotIn('phase', row['result']['mission'])

    def test_rejected_request_is_not_an_admitted_terminal_mission(self):
        rejected = self.submit('hold_position', dict(position=(10., 0., 0.)), 'not-admitted')
        self.assertEqual('rejected', rejected['status'])
        self.assertNotIn('command', self.control.gateway.requests['not-admitted'])
        row = self.submit('wait_state', dict(condition='mission_status', value='failed',
                                            command_id='not-admitted'))
        self.assertEqual(('failed', 'mission_not_admitted'), (row['status'], row['reason']))
        self.assertFalse(row['result']['known'])
        self.assertEqual('command_rejection', row['result']['source'])

    def test_terminal_mission_fallback_requires_the_bound_id_and_identity(self):
        self.admit_mission()
        self.submit('stop', {}, 'stop')
        for command_id in ('other-mission', 'stop'):
            row = self.submit('assert_state', dict(condition='mission_status',
                value='cancelled', command_id=command_id))
            self.assertFalse(row['result']['known'])
            self.assertEqual('mission_not_observed', row['result']['source'])
        self.control.owner._start_message['round_id'] = 'new-round'
        row = self.submit('assert_state', dict(condition='mission_status',
            value='cancelled', command_id='mission-one'))
        self.assertFalse(row['result']['known'])
        self.assertEqual('mission_not_observed', row['result']['source'])

    def test_terminal_before_combat_stays_unknown_until_a_real_effect(self):
        self.fire_group('fire', ['projectile'])
        self.control.shot_receipts.terminal(dict(projectile_id='projectile', hit_vehicle=True), .1)
        self.assertEqual('completed', self.submit('assert_state',
            dict(condition='shot_terminal', projectile_id='projectile'))['status'])
        unknown = self.submit('assert_state', dict(condition='shot_effect', command_id='fire'))
        self.assertFalse(unknown['result']['known'])
        self.assertEqual('combat_not_observed', unknown['reason'])
        self.submit('wait_state', dict(condition='shot_effect', command_id='fire', damage_min=100.), 'wait')
        event = dict(projectile_id='projectile', event_id=1, damage=120., shot_result=2)
        self.control.shot_receipts.hit(event, .2)
        self.control.shot_receipts.hit(event, .3)
        self.observe(.4)
        row = self.receipt('wait')
        self.assertEqual('completed', row['status'])
        self.assertEqual((120., 1), (row['result']['damage_total'], row['result']['hit_count']))

    def test_command_terminal_waits_for_final_actual_commit_list_not_seen_rows(self):
        self.fire_group('fire', ['first'], completed=False)
        self.control.shot_receipts.terminal(dict(projectile_id='first'), .1)
        self.submit('wait_state', dict(condition='shot_terminal', command_id='fire'), 'wait')
        self.observe(.2)
        self.assertEqual('accepted', self.receipt('wait')['status'])
        self.fire_group('fire', ['first', 'last'])
        self.observe(.3)
        self.assertEqual('accepted', self.receipt('wait')['status'])
        self.control.shot_receipts.terminal(dict(projectile_id='last'), .4)
        self.observe(.5)
        self.assertEqual('completed', self.receipt('wait')['status'])
        self.assertEqual(2, self.receipt('wait')['result']['projectile_count'])

    def test_missing_commit_list_and_uncommitted_tail_never_complete_aggregate(self):
        self.fire_group('fire', ['first'], include_list=False)
        self.control.shot_receipts.terminal(dict(projectile_id='first'), .1)
        row = self.submit('assert_state', dict(condition='shot_terminal', command_id='fire'))
        self.assertFalse(row['result']['known'])
        self.control.gateway.requests['fire']['receipt']['result'] = dict(projectile_ids=['first'])
        self.control.owner._local_player_burst = dict(committed=1, count=3,
                                                    player_control=dict(command='fire'))
        row = self.submit('assert_state', dict(condition='shot_terminal', command_id='fire'))
        self.assertEqual('fire_command_pending_tail', row['reason'])

    def test_rejection_is_explicit_and_a_mixed_burst_counts_only_real_effects(self):
        self.fire_group('fire', ['rejected', 'real'])
        self.control.shot_receipts.rejected('rejected', 'launch_rejected', .1)
        for condition in ('shot_terminal', 'shot_effect'):
            row = self.submit('wait_state', dict(condition=condition, projectile_id='rejected'))
            self.assertEqual(('failed', 'shot_rejected'), (row['status'], row['reason']))
            self.assertTrue(row['result']['known'])
        self.control.shot_receipts.hit(dict(projectile_id='real', damage=50., shot_result=2), .2)
        mixed = self.submit('assert_state', dict(condition='shot_effect', command_id='fire', damage_min=50.))
        self.assertEqual('completed', mixed['status'])
        self.assertEqual((1, 50.), (mixed['result']['rejected_count'], mixed['result']['damage_total']))

    def test_large_actual_burst_evidence_and_status_remain_bounded(self):
        identities = ['projectile-%s' % index for index in range(128)]
        self.fire_group('fire', identities)
        for identity in identities:
            self.control.shot_receipts.terminal(dict(projectile_id=identity), .1)
        row = self.submit('assert_state', dict(condition='shot_terminal', command_id='fire'))
        self.assertEqual('completed', row['status'])
        self.assertEqual(128, row['result']['projectile_count'])
        self.assertEqual(8, len(row['result']['projectiles']))
        self.assertTrue(row['result']['details_truncated'])
        self.assertLess(len(json.dumps(row)), 4000)
        self.assertLess(len(json.dumps(self.actions.snapshot())), 3000)

    def test_nonfinite_combat_observation_cannot_break_result_serialization(self):
        self.fire_group('fire', ['projectile'])
        self.control.shot_receipts.get('projectile')['damage_total'] = float('inf')
        row = self.submit('assert_state', dict(condition='shot_effect', projectile_id='projectile'))
        self.assertFalse(row['result']['known'])
        self.assertEqual('shot_observation_unavailable', row['reason'])
        json.dumps(row, allow_nan=False)

    def test_local_anonymous_assert_is_immediate_but_waiter_is_not_retained(self):
        command = dict(id=None, action='assert_state', args=dict(condition='active', value=False))
        self.assertEqual('condition_observed', self.actions.execute(command, 0.)['reason'])
        command.update(action='wait_state', args=dict(condition='active', value=True))
        self.assertEqual('command_id_required', self.actions.execute(command, 0.)['reason'])
        self.assertFalse(self.actions.watchers)


class NativeGunActionTests(ActionHarness, unittest.TestCase):
    # Replace the minimal owner with the actual runtime gun-setting,
    # HUD/checkpoint and GunState path.
    def setUp(self):
        super(NativeGunActionTests, self).setUp()
        self.runtime_case = runtime_fixture.BattleRuntimeContractTests()
        self.addCleanup(self.runtime_case.doCleanups)
        self.install_gun(clip_size=3, clip=2)

    def install_gun(self, clip_size=3, clip=2):
        owner, gun, settings, client, record = self.runtime_case._pending_fire_shell_change_battle(
            clip_size=clip_size, clip=clip)
        owner._clock = lambda: self.fixture.now[0]
        control = PlayerControl(owner, ('drive', 'fire'), notify=lambda unused: None)
        owner._player_control = control
        control.bind_input = lambda: None
        control.record = mock.Mock()
        control.emit_result = lambda row: self.fixture.rows.append(copy.deepcopy(row)) or True
        control.gateway.emit = control.emit_result
        control.gateway.wall_clock = lambda: 1000.
        owner.change_vehicle_setting = mock.Mock(wraps=owner.change_vehicle_setting)
        self.control, self.actions = control, control.test_actions
        self.owner, self.gun, self.settings = owner, gun, settings
        return control

    def finish_reload(self, now=None):
        descriptor = self.owner._server_entity(self.owner._server.vehicle_id).typeDescriptor
        remaining = self.gun.reload_time
        self.gun.tick(remaining, True, 0., 0., 0., descriptor)
        self.observe(self.fixture.now[0]+remaining+.01 if now is None else now)

    def test_select_shell_calls_real_setting_and_waits_for_actual_reload(self):
        before = list(self.gun.ammo)
        row = self.submit('select_shell', dict(compact_descr=102), 'select')
        self.assertEqual('accepted', row['status'])
        self.assertEqual((1, 0), (self.gun.shot_index, self.gun.clip))
        self.assertGreater(self.gun.reload_time, 0.)
        self.owner.change_vehicle_setting.assert_called_once_with(self.settings.CURRENT_SHELLS, 102)
        stock = self.actions.snapshot()['gun']['stock']
        self.assertEqual([(0, 101, 20), (1, 102, 10)],
                         [(s['index'], s['compact_descr'], s['ammo']) for s in stock])
        self.finish_reload()
        self.assertEqual(('completed', 'shell_ready'),
                         (self.receipt('select')['status'], self.receipt('select')['reason']))
        self.assertEqual(before, self.gun.ammo)
        self.assertFalse(self.actions.busy)

    def test_select_retry_never_restarts_reload_or_duplicates_native_setting(self):
        self.submit('select_shell', dict(compact_descr=102), 'select')
        remaining = self.gun.reload_time
        self.submit('select_shell', dict(compact_descr=102), 'select')
        self.assertEqual(remaining, self.gun.reload_time)
        self.assertEqual(1, self.owner.change_vehicle_setting.call_count)
        self.finish_reload()
        self.assertEqual('completed', self.submit('select_shell', dict(compact_descr=102), 'select')['status'])
        self.assertEqual(1, self.owner.change_vehicle_setting.call_count)

    def test_compact_descriptor_selection_uses_actual_mounted_shell_order(self):
        descriptor = self.owner._server_entity(self.owner._server.vehicle_id).typeDescriptor
        self.gun = runtime_fixture.gun_mechanics.GunState(descriptor,
            ammo_layout={101: 20, 102: 10}, shell_order=(102, 101))
        self.gun.clip, self.gun.reload_time = 3, 0.
        self.owner._gun_state = self.gun
        self.assertEqual([(0, 102), (1, 101)], [(row['index'], row['compact_descr'])
            for row in self.actions.snapshot()['gun']['stock']])
        self.submit('select_shell', dict(compact_descr=101), 'select')
        self.owner.change_vehicle_setting.assert_called_once_with(self.settings.CURRENT_SHELLS, 101)
        self.assertEqual(1, self.gun.shot_index)
        self.finish_reload()
        self.assertEqual('completed', self.receipt('select')['status'])

    def test_already_selected_loaded_or_reloading_round_never_restarts_cycle(self):
        self.assertEqual('completed', self.submit('select_shell', dict(compact_descr=101))['status'])
        self.owner.change_vehicle_setting.assert_not_called()
        self.gun.clip, self.gun.reload_time = 0, 2.
        self.submit('select_shell', dict(compact_descr=101), 'wait')
        self.owner.change_vehicle_setting.assert_not_called()
        self.assertEqual(2., self.gun.reload_time)
        self.finish_reload()
        self.assertEqual('completed', self.receipt('wait')['status'])

    def test_partial_clip_reload_preserves_inventory_and_finishes_at_full_clip(self):
        before = list(self.gun.ammo)
        row = self.submit('reload', {}, 'reload')
        self.assertEqual('accepted', row['status'])
        self.assertEqual(0, self.gun.clip)
        self.owner.change_vehicle_setting.assert_called_once_with(self.settings.RELOAD_PARTIAL_CLIP, 0)
        self.finish_reload()
        self.assertEqual('completed', self.receipt('reload')['status'])
        self.assertEqual(3, self.gun.clip)
        self.assertEqual(before, self.gun.ammo)

    def test_empty_running_reload_keeps_pending_next_shell_without_restart(self):
        self.gun.clip, self.gun.reload_time, self.gun.pending_index = 0, 2., 1
        row = self.submit('reload', {}, 'reload')
        self.assertEqual('accepted', row['status'])
        self.owner.change_vehicle_setting.assert_not_called()
        self.assertEqual((0, 2., 1), (self.gun.shot_index, self.gun.reload_time, self.gun.pending_index))
        self.finish_reload()
        self.assertEqual('completed', self.receipt('reload')['status'])
        self.assertEqual((0, 1), (self.gun.shot_index, self.gun.pending_index))

    def test_full_clip_is_idempotent_and_single_shot_reload_is_unsupported(self):
        self.gun.clip = 3
        self.assertEqual('completed', self.submit('reload', {})['status'])
        self.owner.change_vehicle_setting.assert_not_called()
        self.install_gun(clip_size=1, clip=1)
        self.assertEqual('reload_not_supported', self.submit('reload', {})['reason'])
        self.owner.change_vehicle_setting.assert_not_called()

    def test_automatic_fire_pending_fire_stock_and_concurrent_operation_are_fenced(self):
        self.control.active = True
        self.assertEqual('automatic_fire_active', self.submit('select_shell', dict(compact_descr=102))['reason'])
        self.control.active = False
        self.owner._local_fire_intent = {}
        self.assertEqual('gun_not_ready', self.submit('select_shell', dict(compact_descr=102))['reason'])
        self.owner._local_fire_intent = None
        self.gun.ammo[1] = 0
        self.assertEqual('shell_empty', self.submit('select_shell', dict(compact_descr=102))['reason'])
        self.assertEqual('shell_not_mounted', self.submit('select_shell', dict(compact_descr=999))['reason'])
        self.gun.ammo[1] = 10
        self.owner.change_vehicle_setting.assert_not_called()
        self.submit('select_shell', dict(compact_descr=102), 'select')
        self.assertEqual('gun_operation_busy', self.submit('reload', {})['reason'])
        self.assertEqual('gun_operation_busy', self.submit('fire', {})['reason'])
        self.assertEqual(1, self.owner.change_vehicle_setting.call_count)

    def test_stop_timeout_and_death_end_observation_without_undoing_native_setting(self):
        for end in ('stop', 'timeout', 'death', 'identity'):
            with self.subTest(end=end):
                self.install_gun()
                self.fixture.now[0] = 0.
                self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
                physical = (self.gun.shot_index, self.gun.clip, self.gun.reload_time, list(self.gun.ammo))
                if end == 'stop':
                    self.actions.stop('manual', .1)
                elif end == 'death':
                    self.owner._battle_live = False
                    self.observe(.1)
                elif end == 'identity':
                    self.owner._start_message['round_id'] = 8
                    self.observe(.1)
                else:
                    self.observe(1.)
                self.assertIn(self.receipt('select')['status'], ('failed', 'cancelled'))
                self.assertFalse(self.actions.busy)
                self.assertEqual(physical, (self.gun.shot_index, self.gun.clip,
                                           self.gun.reload_time, self.gun.ammo))

    def test_newly_ready_gun_at_deadline_is_timeout_not_completion(self):
        self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
        self.finish_reload(now=1.)
        self.assertEqual(('failed', 'command_timeout'),
                         (self.receipt('select')['status'], self.receipt('select')['reason']))

    def test_native_reentry_before_setting_cannot_misread_old_shell_as_failure(self):
        native = self.owner.change_vehicle_setting
        def reentrant(code, value):
            self.assertEqual('submitting', self.actions.gun_pending['phase'])
            self.actions.update(0.)
            self.assertEqual('accepted', self.receipt('select')['status'])
            return native(code, value)
        self.owner.change_vehicle_setting = reentrant
        self.assertEqual('accepted', self.submit('select_shell', dict(compact_descr=102), 'select')['status'])
        self.finish_reload()
        self.assertEqual('completed', self.receipt('select')['status'])

    def test_reentrant_stop_keeps_cancellation_even_if_native_call_finishes(self):
        native = self.owner.change_vehicle_setting
        def reentrant(code, value):
            self.actions.stop('manual', 0.)
            return native(code, value)
        self.owner.change_vehicle_setting = reentrant
        row = self.submit('select_shell', dict(compact_descr=102), 'select')
        self.assertEqual('cancelled', row['status'])
        self.assertEqual(1, self.gun.shot_index)
        self.assertFalse(self.actions.busy)

    def test_native_reentry_still_honours_deadline_during_submission(self):
        native = self.owner.change_vehicle_setting
        def reentrant(code, value):
            self.actions.update(1.)
            return native(code, value)
        self.owner.change_vehicle_setting = reentrant
        row = self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
        self.assertEqual(('failed', 'command_timeout'), (row['status'], row['reason']))
        self.assertEqual(1, self.gun.shot_index)
        self.assertFalse(self.actions.busy)

    def test_native_return_rechecks_deadline_without_reentrant_update(self):
        for returned_at in (1., 2.):
            with self.subTest(returned_at=returned_at):
                self.install_gun(clip_size=1, clip=1)
                self.fixture.now[0] = 0.
                self.owner._roll_loader_intuition = lambda: True
                before = list(self.gun.ammo)
                native = self.owner.change_vehicle_setting
                def delayed(code, value):
                    self.fixture.now[0] = returned_at
                    return native(code, value)
                self.owner.change_vehicle_setting = delayed
                row = self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
                self.assertEqual(('failed', 'command_timeout', returned_at),
                                 (row['status'], row['reason'], row['time']))
                self.assertEqual((1, 1, 0.), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
                self.assertEqual(before, self.gun.ammo)
                native.assert_called_once_with(self.settings.CURRENT_SHELLS, 102)
                self.assertFalse(self.actions.busy)
                self.control.gateway.tick(returned_at)
                self.assertEqual(row, self.receipt('select'))

    def test_native_return_rechecks_identity_without_reentrant_update(self):
        self.install_gun(clip_size=1, clip=1)
        self.owner._roll_loader_intuition = lambda: True
        identity = dict(self.control.identity())
        before = list(self.gun.ammo)
        native = self.owner.change_vehicle_setting
        def changed_owner(code, value):
            accepted = native(code, value)
            self.fixture.now[0] = .5
            self.owner._start_message['round_id'] = 'another-round'
            return accepted
        self.owner.change_vehicle_setting = changed_owner
        row = self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
        self.assertEqual(('cancelled', 'identity_changed', .5),
                         (row['status'], row['reason'], row['time']))
        self.assertEqual(identity['round_id'], row['round_id'])
        self.assertEqual((1, 1, 0.), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
        self.assertEqual(before, self.gun.ammo)
        native.assert_called_once_with(self.settings.CURRENT_SHELLS, 102)
        self.assertFalse(self.actions.busy)
        self.observe(2.)
        self.control.gateway.tick(2.)
        self.assertEqual(row, self.receipt('select'))

    def test_timely_native_completion_records_return_time_not_admission_time(self):
        self.install_gun(clip_size=1, clip=1)
        self.owner._roll_loader_intuition = lambda: True
        native = self.owner.change_vehicle_setting
        def delayed(code, value):
            self.fixture.now[0] = .5
            return native(code, value)
        self.owner.change_vehicle_setting = delayed
        row = self.submit('select_shell', dict(compact_descr=102), 'select', timeout=1.)
        self.assertEqual(('completed', 'shell_ready', .5),
                         (row['status'], row['reason'], row['time']))
        self.assertEqual((1, 1, 0.), (self.gun.shot_index, self.gun.clip, self.gun.reload_time))
        self.assertFalse(self.actions.busy)

    def test_ready_gun_cannot_complete_while_a_fire_intent_is_still_pending(self):
        self.submit('select_shell', dict(compact_descr=102), 'select')
        self.owner._local_fire_intent = {}
        self.finish_reload(now=1.)
        self.assertEqual('accepted', self.receipt('select')['status'])
        self.owner._local_fire_intent = None
        self.observe(1.1)
        self.assertEqual('completed', self.receipt('select')['status'])

    def test_rejected_setting_releases_only_its_own_observation(self):
        self.owner.change_vehicle_setting = mock.Mock(return_value=False)
        self.control.stop = mock.Mock()
        row = self.submit('select_shell', dict(compact_descr=102), 'select')
        self.assertEqual(('failed', 'gun_setting_rejected'), (row['status'], row['reason']))
        self.assertFalse(self.actions.busy)
        self.assertEqual(0, self.gun.shot_index)
        self.control.stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
