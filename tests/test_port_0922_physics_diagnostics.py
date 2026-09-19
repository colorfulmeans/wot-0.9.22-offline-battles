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
