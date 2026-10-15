"""Recovery and projectile evidence ownership; engine acceptance remains separate."""
import unittest
import types
import json
import io
import contextlib
from pathlib import Path
from unittest import mock
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
from test_port_0922_world_collision import _Vector
from lan_battle_server import _server_event_log_message

class RecoveryEvidenceTests(unittest.TestCase):
    def test_pivot_names_the_proved_rear_blocker(self):
        driver = LocalDriver()
        state = driver._state(6, 5, (0., 0., 0.))
        state.update(recovery_time=1., recovery_side=1.)
        neighbour = dict(id=4, position=(0., 0., -7.), yaw=0.,
                         half_width=1.5, half_length=3.5)
        order = driver.drive(6, 5, (0., 0., 0.), 0., 0., .1,
                             (0., 0., 30.), [neighbour], lambda *args: True,
                             pose_clear=lambda *args: True)
        self.assertEqual('pivot_recovery', order['recovery_mode'])
        self.assertEqual(4, order.get('reverse_blocked_by'))
        self.assertEqual(0., order['throttle'])

    def test_repeated_recovery_retries_after_a_new_recovery_and_deadline(self):
        driver = LocalDriver()
        state = driver._state(6, 5, (0., 0., 0.))
        state.update(clock=10., recovery_count=2)
        self.assertFalse(driver.recovery_replan(6, (0., 0., 0.), 3.5))
        state.update(clock=19., recovery_count=5)
        self.assertTrue(driver.recovery_replan(6, (.2, 0., -.2), 3.5))
        state.update(clock=26., recovery_count=10)
        self.assertFalse(driver.recovery_replan(6, (.1, 0., .1), 3.5))
        state.update(clock=30., recovery_count=10)
        self.assertTrue(driver.recovery_replan(6, (.1, 0., .1), 3.5))
        for clock in (60., 100.):
            state.update(clock=clock, recovery_count=10)
            self.assertFalse(driver.recovery_replan(6, (.1, 0., .1), 3.5))
        self.assertFalse(driver.recovery_replan(6, (0., 0., 10.), 3.5))
        state.update(clock=109., recovery_count=12)
        self.assertTrue(driver.recovery_replan(6, (0., 0., 10.), 3.5))

    def test_reported_430_pocket_requests_are_bounded_by_recovery_and_time(self):
        rows = json.loads((Path(__file__).parent / 'fixtures' /
                           'object430_203324_recovery.json').read_text())
        self.assertGreaterEqual(len(rows), 3)
        driver = LocalDriver()
        state = driver._state(6, 5, rows[0]['position'])
        requests = []
        for row in rows:
            state.update(clock=row['clock'], recovery_count=row['recovery_count'])
            requests.append(driver.recovery_replan(6, row['position'], 3.5))
        issued = [row for row, requested in zip(rows, requests) if requested]
        self.assertTrue(issued)
        for previous, current in zip(issued, issued[1:]):
            self.assertGreaterEqual(current['clock'] - previous['clock'], 8.)
            self.assertGreater(current['recovery_count'], previous['recovery_count'])

    def test_252u_logged_pocket_retries_instead_of_latching_first_request(self):
        driver = LocalDriver()
        state = driver._state(17, 0, (-72.232603355, 13., -56.584238809))
        state.update(clock=133.491210938, recovery_count=1)
        self.assertFalse(driver.recovery_replan(17, (-72.232603355, 13., -56.584238809), 3.5))
        # Windows 231147, 23:05:02 and 23:05:26: hull remains in the same
        # pocket while the completed recovery count advances from 2 to 4.
        state.update(clock=173.259155273, recovery_count=2)
        self.assertTrue(driver.recovery_replan(17, (-73.6572376756, 13., -56.4854850002), 3.5))
        state.update(clock=196.514160156, recovery_count=4)
        self.assertTrue(driver.recovery_replan(17, (-73.4781987861, 13., -56.8242426368), 3.5))

    def test_admitted_pocket_retries_when_instantaneous_contact_is_gone(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        adapter = BotAdapter('test', 1)
        state = dict(id=17, slot=0, team=1, position=(0., 0., 0.),
                     yaw=0., speed=0., dt=.1, neighbours=[])
        driver_state = adapter.driver._state(17, 0, state['position'])
        driver_state['recovery_replan_episode'] = {'issued': True, 'origin': state['position']}
        order = dict(throttle=0., turn=1., target_yaw=.85, recovery_mode='pivot_recovery')
        with mock.patch.object(adapter, '_hull_contact', return_value=None), \
             mock.patch.object(adapter, '_wreck_push_plan', return_value=None), \
             mock.patch.object(adapter.driver, 'drive', return_value=order), \
             mock.patch.object(adapter.driver, 'recovery_replan', return_value=True) as replan:
            result = adapter._drive_order_controls(17, state, state['position'],
                dict(combat_mode='route', move_position=(0., 0., 40.)), lambda *a: True)
        self.assertTrue(result.get('navigation_replan'))
        replan.assert_called_once()

    def test_adapter_requires_vehicle_evidence_and_does_not_interrupt_navigation_wait(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        for named, waiting in ((True, False), (False, False), (True, True)):
            with self.subTest(named=named, waiting=waiting):
                adapter = BotAdapter('test', 1)
                state = dict(id=6, slot=5, team=1, position=(0., 0., 0.),
                             yaw=0., speed=0., dt=.1, neighbours=[])
                order = dict(throttle=0., turn=1., target_yaw=.85,
                             recovery_mode='pivot_recovery')
                if named: order['reverse_blocked_by'] = 4
                if waiting:
                    state['navigation_status'] = 'pending'
                    adapter.navigation_target = lambda *args: (0., 0., 0.)
                with mock.patch.object(adapter, '_hull_contact', return_value=None), \
                     mock.patch.object(adapter, '_wreck_push_plan', return_value=None), \
                     mock.patch.object(adapter.driver, 'drive', side_effect=lambda *a, **kw: dict(order)), \
                     mock.patch.object(adapter.driver, 'wait_for_navigation', side_effect=lambda *a, **kw: dict(order)), \
                     mock.patch.object(adapter.driver, 'recovery_replan', return_value=True) as replan:
                    result = adapter._drive_order_controls(6, state, state['position'],
                        dict(combat_mode='route', move_position=(0., 0., 40.)), lambda *a: True)
                if named and not waiting:
                    self.assertTrue(result.get('navigation_replan'))
                    replan.assert_called_once()
                else:
                    self.assertFalse(result.get('navigation_replan', False))
                    replan.assert_not_called()

    def test_progressing_recovery_does_not_replan_each_small_step(self):
        driver = LocalDriver()
        state = driver._state(6, 5, (0., 0., 0.))
        for tick in range(40):
            state.update(clock=tick*.25, recovery_count=1)
            self.assertFalse(driver.recovery_replan(6, (0., 0., tick*.3), 3.5))

class ProjectileEvidenceTests(unittest.TestCase):
    def test_world_effect_keeps_projectile_identity(self):
        battle = BattleRuntime.__new__(BattleRuntime)
        battle._projectile_meta = {'1:b:8:1': dict(hit_vehicle=False, terminal_velocity=(1., -.1, 0.))}
        battle._projectile_visual_meta = {}
        battle._runtime = types.SimpleNamespace(vehicles=types.SimpleNamespace(
            g_cache=types.SimpleNamespace(shotEffects={14: object()})))
        battle._projectile_shot = lambda meta: dict(shell=dict(effectsIndex=14))
        battle._surface_effect_material = lambda point: 'ground'
        battle._vector = lambda xyz: _Vector(*xyz)
        battle._report_effect = mock.Mock()
        self.assertIsNotNone(battle._projectile_explosion('1:b:8:1', (10., 0., 0.)))
        self.assertEqual('1:b:8:1', battle._report_effect.call_args.kwargs['event']['projectile_id'])

    def test_unbounced_bot_terminal_is_observable(self):
        battle = BattleRuntime.__new__(BattleRuntime)
        battle._worker_mode = True
        battle._owns_projectile = lambda meta: True
        battle.client = types.SimpleNamespace(send_projectile_resolve=lambda *args, **kwargs: True)
        battle._report_projectile_interface = mock.Mock()
        wire = dict(authority_epoch=1, projectile_id='1:b:8:1', base_checked_ms=0,
                    outcome='impact', resolved_time_ms=155, impact=[120., 0., 0.],
                    direct=None, splash=[], checked_distance=120., piercing_loss=0.,
                    penetration_factor=1., hit_vehicle=False, wreck_hit=None, destructibles=[])
        meta = dict(projectile_id='1:b:8:1', ricochet_count=0,
                    origin=[0., 2., 0.], velocity=[950., -15., 0.],
                    pending_resolution=dict(wire=wire, state={}))
        self.assertTrue(battle._submit_projectile_resolution(meta))
        args = battle._report_projectile_interface.call_args.args
        self.assertEqual('terminal_queued', args[1])
        self.assertEqual(wire, args[2]['wire'])
        self.assertEqual(meta['origin'], args[2]['launch']['origin'])
        self.assertFalse(battle._submit_projectile_resolution(meta))
        battle._report_projectile_interface.assert_called_once()

    def test_unresolved_material_probe_keeps_its_identity_and_status(self):
        from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
        def resolve(bigworld, space, start, end, direction, shot, observer):
            observer.call('native.projectile.material',
                          lambda: (True, start, direction, 111, '', 96, 32127))
            return dict(world_distance=1.)
        with mock.patch.object(sensor, '_shot_world_distance_impl_1513', side_effect=resolve):
            result = sensor.shot_world_distance(None, 1, _Vector(0, 0, 0),
                _Vector(1, 0, 0), _Vector(1, 0, 0), shot={})
        row = result['collision_evidence'][0]
        self.assertEqual('missing_resource', row['identity_status'])
        self.assertEqual((32127, 96, 111), (row['chunk'], row['item'], row['material']))
        self.assertEqual('', row['filename'])

    def test_distinct_world_contacts_are_retained_and_duplicates_are_bounded(self):
        battle = BattleRuntime.__new__(BattleRuntime)
        battle._start_message = dict(round_id=1)
        meta = dict(projectile_id='1:b:8:1')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            for key in ([32127, 35], [32127, 96], [32127, 35]):
                battle._report_projectile_interface(meta, 'world_contact', dict(contact_key=key))
        rows = [json.loads(line.split('PROJECTILE INTERFACE ', 1)[1])
                for line in output.getvalue().splitlines()]
        self.assertEqual(2, len(rows))
        self.assertEqual([32127, 96], rows[1]['contact_key'])
        self.assertTrue(all(row['projectile']=='1:b:8:1' for row in rows))

    def test_exhausted_diagnostic_budget_is_explicit_and_reported_once(self):
        battle = BattleRuntime.__new__(BattleRuntime)
        battle._start_message = dict(round_id=1)
        battle._projectile_interface_budget = [1, 512]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            for unused in range(2):
                battle._report_projectile_interface(dict(projectile_id='1:b:8:1'), 'world_contact', {})
        rows = [json.loads(line.split('PROJECTILE INTERFACE ', 1)[1])
                for line in output.getvalue().splitlines()]
        self.assertEqual(1, len(rows))
        self.assertEqual('diagnostic_budget_exhausted', rows[0]['phase'])

    def test_canonical_bot_terminal_is_logged(self):
        event = dict(kind='projectile_impact', shooter_kind='bot', shooter_id=8,
                     projectile_id='1:b:8:1', outcome='impact', resolved_time_ms=155,
                     impact=[120., 0., 0.], hit_vehicle=False)
        line = _server_event_log_message(event, {}, {})
        self.assertIn('id=1:b:8:1', line)
        self.assertIn('shooter=bot:8', line)
        self.assertIn('hit_vehicle=False', line)
