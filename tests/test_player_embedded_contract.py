"""Engine-free contracts executed in both Python 3 and the real 2.7 gate.

Load the exact helper sources without requiring stock #1513 GUI packages.
This is interpreter/logic evidence, not a native-client acceptance run.
"""
from __future__ import print_function
import os
import types
import unittest


BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'src', 'res', 'scripts', 'client', 'gui', 'mods',
                    'offline_lan_0922', 'player_control')


def load_helper(name):
    module = types.ModuleType('foreground_contract_' + name)
    path = os.path.join(BASE, name + '.py')
    with open(path, 'rb') as source:
        eval(compile(source.read(), path, 'exec'), module.__dict__)
    return module


commands = load_helper('commands')
receipts = load_helper('shot_receipts')
settling = load_helper('settling')


class EmbeddedForegroundContractTests(unittest.TestCase):
    def test_explicit_native_command_schema_and_unicode_holder_on_python27(self):
        self.assertEqual(42, commands.validate_action('aim_target',
            dict(target_id=42))['target_id'])
        point = commands.validate_action('aim_point',
            dict(position=[20., 1., 100.], tolerance_deg=.5))
        self.assertEqual([20., 1., 100.], list(point['position']))
        holder = commands.validate_action('release_aim', dict(command_id=u'\u6301\u6709'))
        self.assertEqual(u'\u6301\u6709', holder['command_id'])
        self.assertEqual('engineHealth', commands.validate_action('use_equipment',
            dict(equipment_id=4, target='engineHealth'))['target'])
        self.assertIs(True, commands.validate_action('set_siege', dict(enabled=True))['enabled'])
        for action, args in (
                ('aim_target', dict(target_id=True)),
                ('aim_point', dict(position=[float('nan'), 1., 2.])),
                ('use_equipment', dict(equipment_id=False)),
                ('use_equipment', dict(equipment_id=4, target='unknown')),
                ('set_siege', dict(enabled=1))):
            with self.assertRaises(ValueError):
                commands.validate_action(action, args)

    def test_explicit_command_default_deadlines_are_not_admission_deadlines(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        for action, args, timeout in (
                ('aim_target', dict(target_id=42), 30.),
                ('aim_point', dict(position=[20., 1., 100.]), 30.),
                ('release_aim', {}, 10.),
                ('use_equipment', dict(equipment_id=12, active=True), 30.),
                ('set_siege', dict(enabled=False), 30.)):
            gateway = commands.CommandGateway(lambda: identity, lambda row: True,
                lambda command, now: None, lambda command: None,
                lambda command, reason: None, wall_clock=lambda: 1000.)
            request = dict(identity, id=action, action=action, args=args, expires_at=1002.)
            result = gateway.submit(request, 3.)
            self.assertEqual('accepted', result['status'])
            self.assertEqual(3. + timeout, gateway.requests[action]['deadline'])
            gateway.tick(3. + timeout)
            self.assertEqual('command_timeout', gateway.requests[action]['receipt']['reason'])

    def test_identity_is_rechecked_after_native_preflight_on_python27(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        executed = []
        def preflight(command):
            identity['round_id'] = 2
        gateway = commands.CommandGateway(lambda: identity, lambda row: True,
            lambda command, now: executed.append(command), preflight,
            lambda command, reason: None, wall_clock=lambda: 1000.)
        request = dict(identity, id='mode', action='set_siege',
                       args=dict(enabled=True), expires_at=1002.)
        result = gateway.submit(request, 0.)
        self.assertEqual(('rejected', 'identity_changed'), (result['status'], result['reason']))
        self.assertEqual([], executed)
        self.assertFalse(commands.same_identity(dict(player_id=1), dict(player_id=True)))
        self.assertFalse(commands.same_identity(dict(player_id=1), dict(player_id=1.)))

    def test_unicode_native_failure_keeps_the_original_error_and_terminal_cleanup(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        cancelled = []
        failure = RuntimeError(u'\u539f\u751f\u9519\u8bef')
        def execute(command, now):
            raise failure
        gateway = commands.CommandGateway(lambda: identity, lambda row: True,
            execute, lambda command: None,
            lambda command, reason: cancelled.append(reason), wall_clock=lambda: 1000.)
        request = dict(identity, id='fire', action='fire', args={}, expires_at=1002.)
        with self.assertRaises(RuntimeError) as raised:
            gateway.submit(request, 0.)
        self.assertIs(failure, raised.exception)
        self.assertEqual('execution_error', gateway.requests['fire']['receipt']['reason'])
        self.assertEqual(['execution_error'], cancelled)

    def test_unicode_lookup_and_effect_ids_are_not_ascii_coerced(self):
        args = commands.validate_action('assert_state',
            dict(condition='shot_terminal', projectile_id=u'\u4e2d'))
        ledger = receipts.ShotReceipts()
        self.assertIsNone(ledger.get(args['projectile_id']))
        ledger.committed(dict(projectile_id=u'\u4e2d'), {}, {}, 0., 1)
        event = dict(projectile_id=u'\u4e2d', event_id=u'\u6548\u679c', damage=10)
        self.assertEqual(10., ledger.hit(event, 1.)['damage_total'])
        self.assertIsNone(ledger.hit(event, 1.))
        self.assertEqual(u'\u62d2\u7edd', ledger.rejected(u'\u4e2d', u'\u62d2\u7edd', 2.)['reason'])

    def test_unicode_readonly_request_is_acknowledged_without_callback_failure(self):
        identity = dict(session_id='s', round_id=1, player_id=1)
        rows = []
        ledger = receipts.ShotReceipts()
        def emit(row):
            rows.append(row)
            return True
        def execute(command, now):
            self.assertIsNone(ledger.get(command['args']['projectile_id']))
            return dict(status='failed', reason='observation_unavailable')
        gateway = commands.CommandGateway(lambda: identity, emit, execute,
            lambda command: None, lambda command, reason: None, wall_clock=lambda: 1000.)
        request = dict(identity, id=u'\u67e5\u8be2', action='assert_state',
            args=dict(condition='shot_terminal', projectile_id=u'\u4e2d'), expires_at=1002.)
        result = gateway.submit(request, 0.)
        self.assertEqual('observation_unavailable', result['reason'])
        self.assertEqual(['accepted', 'failed'], [row['status'] for row in rows])
        self.assertEqual(result, gateway.submit(request, 1.))

    def test_suspension_motion_prevents_false_full_body_rest(self):
        owner = types.ModuleType('observed_body')
        owner._local_speed = owner._local_turn_speed = owner._local_vertical_speed = 0.
        owner._local_pitch = owner._local_roll = 0.
        owner._local_suspension_pitch_velocity = owner._local_suspension_roll_velocity = 0.
        owner._local_air_lateral = (0., 0.)
        owner._local_airborne = owner._local_support_rise_blocked = False
        owner._overturn_level = 0
        owner.local_pose = lambda: ((0., 0., 0.), 0.)
        rest = settling.HaltObservation()
        self.assertFalse(rest.observe(owner, 0.))
        owner._local_pitch, owner._local_roll = .15, .12
        self.assertFalse(rest.observe(owner, .6))
        owner._local_suspension_pitch_velocity = .1
        self.assertFalse(rest.observe(owner, 1.2))
        owner._local_suspension_pitch_velocity = 0.
        self.assertFalse(rest.observe(owner, 1.3))
        self.assertTrue(rest.observe(owner, 1.9))


if __name__ == '__main__':
    unittest.main()
