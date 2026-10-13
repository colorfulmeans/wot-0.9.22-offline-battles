"""Recovery and projectile evidence ownership; engine acceptance remains separate."""
import unittest
import types
import json
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

    def test_repeated_recovery_requests_one_replan_until_actual_escape(self):
        driver = LocalDriver()
        state = driver._state(6, 5, (0., 0., 0.))
        state.update(clock=10., recovery_count=2)
        self.assertFalse(driver.recovery_replan(6, (0., 0., 0.), 3.5))
        state.update(clock=19., recovery_count=5)
        self.assertTrue(driver.recovery_replan(6, (.2, 0., -.2), 3.5))
        for clock in (30., 60., 100.):
            state.update(clock=clock, recovery_count=10)
            self.assertFalse(driver.recovery_replan(6, (.1, 0., .1), 3.5))
        self.assertFalse(driver.recovery_replan(6, (0., 0., 10.), 3.5))
        state.update(clock=109., recovery_count=12)
        self.assertTrue(driver.recovery_replan(6, (0., 0., 10.), 3.5))

    def test_reported_430_pocket_emits_a_single_fresh_follower_request(self):
        rows = json.loads((Path(__file__).parent / 'fixtures' /
                           'object430_203324_recovery.json').read_text())
        self.assertGreaterEqual(len(rows), 3)
        driver = LocalDriver()
        state = driver._state(6, 5, rows[0]['position'])
        requests = []
        for row in rows:
            state.update(clock=row['clock'], recovery_count=row['recovery_count'])
            requests.append(driver.recovery_replan(6, row['position'], 3.5))
        self.assertEqual(1, sum(requests))

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

    def test_canonical_bot_terminal_is_logged(self):
        event = dict(kind='projectile_impact', shooter_kind='bot', shooter_id=8,
                     projectile_id='1:b:8:1', outcome='impact', resolved_time_ms=155,
                     impact=[120., 0., 0.], hit_vehicle=False)
        line = _server_event_log_message(event, {}, {})
        self.assertIn('id=1:b:8:1', line)
        self.assertIn('shooter=bot:8', line)
        self.assertIn('hit_vehicle=False', line)
