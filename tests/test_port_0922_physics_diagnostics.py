"""Always-on collision evidence independent of the optional text debug queue."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import physics_diagnostics as diagnostics


class PhysicsDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.lines = []
        patch = mock.patch.multiple(diagnostics, _writer=self.lines.append, _last={})
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self):
        return [json.loads(line[len(diagnostics.PREFIX):]) for line in self.lines]

    def test_every_changed_component_survives_old_session_caps(self):
        for item in range(100):
            diagnostics.emit('catalog_contact', {'item': item, 'normal': [1,0,0],
                             'reason': 'insufficient_contact_energy'}, now=10.)
        self.assertEqual(list(range(100)), [row['data']['item'] for row in self.rows()])

    def test_changed_unknown_native_contact_is_immediately_recorded(self):
        for x in (1.,1.001):
            diagnostics.emit('world_contact', {'hit': [x,0,0],
                'identity': None, 'candidates': [[73,131,61072,1762732]],
                'identity_source': 'callback_candidates_not_nearest_identity'}, now=10.)
        self.assertEqual(2,len(self.rows()))
        self.assertIsNone(self.rows()[1]['data']['identity'])
        self.assertIn('candidates',self.rows()[1]['data'])

    def test_identical_repeat_count_is_explicit(self):
        for time in (10.,10.1,10.2,11.1):
            diagnostics.emit('contact', {'item': 4}, now=time)
        self.assertEqual([0,3],[row['identical_repeats'] for row in self.rows()])

    def test_bot_first_blocked_frame_is_not_lost_to_legacy_stall_cadence(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        runtime = object.__new__(BotRuntime)
        runtime.native_motion = False
        state = dict(id=11, x=0., y=0., z=0., yaw=0., speed=0.)
        runtime.states = {11: state}
        runtime._turn_speeds = {11: 0.}
        runtime._ram_contacts = {}
        for material, now in ((73, 10.), (74, 10.01)):
            runtime._log_motion_stall(state,
                dict(movement_intent=True, move_position=(0., 0., 20.)),
                1., 0., False, dict(collision=True), now)
            trace = state['_motion_stall_pending']
            trace.update(hard_contact=True, world_status='hard',
                         world_contact=dict(material=material), dt=.01)
            runtime._finish_motion_stall(state, False, False, (0., 0., 0.))
        rows = [row['data'] for row in self.rows() if row['event'] == 'bot_motion_frame']
        self.assertEqual([73, 74], [row['world_contact']['material'] for row in rows])
        self.assertEqual([11, 11], [row['id'] for row in rows])
        self.assertTrue(all('final' in row and 'rotation_contact' in row for row in rows))

    def test_failed_log_stream_cannot_raise_into_physics(self):
        def fail(line):
            raise IOError('closed stream')
        with mock.patch.object(diagnostics,'_writer',fail):
            diagnostics.emit('contact', {'item': 4})

    def test_native_payload_is_snapshotted_once_and_kept_in_full(self):
        calls = []
        class NativeEffect(object):
            def __repr__(self):
                calls.append(1)
                return '<EffectsList snapshot %d>' % len(calls)
        diagnostics.emit('catalog_contact', {'identity': [32636, 24, 74],
            'kinetic': {'health': 15, 'damage': 8.40534220802027},
            'effects': [NativeEffect()]}, now=10.)
        self.assertEqual(1, len(calls))
        data = self.rows()[0]['data']
        self.assertEqual([32636, 24, 74], data['identity'])
        self.assertEqual(8.40534220802027, data['kinetic']['damage'])
        self.assertEqual(['<EffectsList snapshot 1>'], data['effects'])

    def test_unprintable_native_object_keeps_other_contact_fields(self):
        class BrokenEffect(object):
            def __repr__(self):
                raise RuntimeError('detached native object')
        diagnostics.emit('contact', {'item': 24, 'effect': BrokenEffect()})
        self.assertEqual(24, self.rows()[0]['data']['item'])
        self.assertIn('BrokenEffect', self.rows()[0]['data']['effect'])

    def test_reused_encoder_observes_mutation_and_recovers_after_invalid_data(self):
        payload = {'contact': {'item': 24, 'health': 15}}
        first = diagnostics.encode(payload, compact=True)
        payload['contact']['health'] = 0
        payload['cycle'] = payload
        with self.assertRaises(ValueError):
            diagnostics.encode(payload, compact=True)
        del payload['cycle']
        second = diagnostics.encode(payload, compact=True)
        self.assertEqual(15, json.loads(first)['contact']['health'])
        self.assertEqual(0, json.loads(second)['contact']['health'])
