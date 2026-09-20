"""The 08:37 report aborts a battle while serializing EffectsList evidence."""
import io
import json
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as local
from gui.mods.offline_lan_0922 import bot_runtime, physics_diagnostics, world_collision


class EffectsList(object):
    def __repr__(self):
        return '<helpers.EffectsList.EffectsList object>'


def contact():
    return {'reason': 'catalog_rigid_contact', 'status': 'hard',
            'contacts': [{'identity': (32636, 24, 74),
                'reason': 'insufficient_contact_energy',
                'contact_speed': 1.776776868537801,
                'kinetic': {'instant_damage': 8.40534220802027,
                    'scaled_health': 15, 'descriptor': {
                        'modules': {74: {'health': 15, 'destroyedMat': 88,
                            'decayEffect': [EffectsList()]}}}}}]}


class ContactReportRegressionTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.multiple(physics_diagnostics, _last={}, _writer=None)
        patch.start()
        self.addCleanup(patch.stop)

    def player(self):
        battle = local.BattleRuntime(local._runtime())
        battle._local_motion_status = 'hard'
        battle._local_support_rise_blocked = False
        battle._local_speed = 6.522340757412616
        battle._sender = types.SimpleNamespace(forward=1., turn=-1., handbrake=False)
        return battle

    def report(self, battle):
        return battle._report_local_motion_stall(
            (17.99470768820443, 8.32891734947661, -274.92305550371555),
            (18.174413477753678, 8.32839127126921, -274.80644794881346),
            .031002044677734375, 1., 'deflect',
            5.306328861027747, 5.381583, .002934205, contact())

    def test_player_legacy_and_structured_reports_keep_native_effect_evidence(self):
        battle = self.player()
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertTrue(self.report(battle))
        records = out.getvalue().splitlines()
        legacy = json.loads(next(line.split('LOCAL HARD CONTACT ', 1)[1]
                                 for line in records if 'LOCAL HARD CONTACT ' in line))
        self.assertEqual(15, legacy['contacts'][0]['kinetic']['scaled_health'])
        self.assertIn('EffectsList', str(legacy))
        self.assertTrue(any('player_contact_frame' in line for line in records))
        self.assertEqual('hard', battle._local_motion_status)
        self.assertEqual(6.522340757412616, battle._local_speed)

    def test_bot_legacy_report_accepts_the_same_contact_payload(self):
        runtime = object.__new__(bot_runtime.BotRuntime)
        state = dict(id=11, x=0., y=0., z=0., yaw=0., speed=0.,
            _rotation_contact_trace=contact(), _motion_stall_pending={
                'legacy_text': True, 'movement_intent': True, 'start': (0., 0., 0.)})
        runtime.states = {11: state}
        runtime._turn_speeds, runtime._ram_contacts = {11: 0.}, {}
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            runtime._finish_motion_stall(state, False, False, (0., 0., 0.))
        record = json.loads(next(line.split('[BOT MOTION] ', 1)[1]
            for line in out.getvalue().splitlines() if '[BOT MOTION] ' in line))
        self.assertEqual('hard', record['rotation_contact']['status'])
        self.assertIn('EffectsList', str(record))

    def test_failed_legacy_stream_cannot_abort_player_motion(self):
        battle = self.player()
        with mock.patch('sys.stdout') as stream:
            stream.write.side_effect = IOError('closed client log')
            self.report(battle)
        self.assertEqual(6.522340757412616, battle._local_speed)

    def test_bot_catalog_block_delivers_the_contact_normal_to_its_response(self):
        runtime = local._runtime()
        battle = local.BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        state = {'id': 11, 'movement_dir': 1}
        battle._bots = types.SimpleNamespace(states={11: state}, _turn_speeds={})
        evidence = dict(contact(), normal=(.5443279025270304, 0., -.8388725377138793))
        battle._destructibles = types.SimpleNamespace(
            _catalog_motion_blocked=lambda *args, **kw: {
                'status': 'hard', 'kinds': 'structure', 'evidence': evidence})
        with mock.patch.object(world_collision, 'check_horizontal_collision', return_value='clear'), \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual('hard', battle._resolve_bot_motion(
                11, (18., 8.33, -275.), .65, 5.3, local._Descriptor(), .031, 10.))
        self.assertEqual(evidence['normal'], state['_world_contact_trace']['normal'])
        self.assertEqual('catalog_rigid_contact', state['_world_contact_trace']['reason'])


if __name__ == '__main__':
    unittest.main()
