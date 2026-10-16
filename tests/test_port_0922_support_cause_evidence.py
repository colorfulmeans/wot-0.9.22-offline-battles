"""Support transition receipts must explain existing samples without new casts."""
import contextlib
import io
import json
import unittest
from unittest import mock

import test_port_0922_contact_support_navigation as fixtures


class SupportCauseEvidenceTests(unittest.TestCase):
    scene = fixtures.ContactSupportTests.scene

    def test_sample_preserves_input_plane_and_does_not_add_ground_queries(self):
        runtime,state = self.scene(lambda x,z:0.)
        runtime._contact_now = 1.
        basis = (0.,0.,0.,0.,0.)
        state.update(x=1.,_support_mode_basis=basis)
        with mock.patch.object(runtime,'_ground_probe_at',return_value=0.) as probe:
            first = runtime._basic_support_status(state)
            self.assertIs(first,runtime._basic_support_status(state))
            self.assertEqual(5,probe.call_count)
        receipt = state['_support_mode_receipt']
        self.assertEqual(basis,receipt['basis_before'])
        self.assertTrue(receipt['projected'])
        self.assertEqual('projected',receipt['projection_reason'])
        self.assertEqual(1.,state['_support_mode_basis'][0])

    def test_airborne_sample_reports_why_previous_plane_was_not_projected(self):
        runtime,state = self.scene(lambda x,z:0.)
        state.update(x=1.,airborne=True,_support_mode_basis=(0.,0.,0.,0.,0.))
        runtime._basic_support_status(state)
        self.assertFalse(state['_support_mode_receipt']['projected'])
        self.assertEqual('airborne',state['_support_mode_receipt']['projection_reason'])

    @staticmethod
    def records(text):
        return [json.loads(line.split('BOT SUPPORT MODE ',1)[1])
                for line in text.splitlines() if 'BOT SUPPORT MODE ' in line]

    def test_height_settle_and_actual_ground_return_are_distinguishable(self):
        for actual_return in (False,True):
            terrain = [0.]
            runtime,state = self.scene(lambda x,z:terrain[0])
            runtime._contact_now = 1.
            state.update(y=1.,airborne=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(runtime._contact_edge_support_needed(state))
                if actual_return: terrain[0] = 1.
                else: state['y'] = 0.
                state['airborne'] = False
                runtime._contact_now = 1.15
                self.assertTrue(runtime._release_detailed_support(state))
            records = self.records(output.getvalue())
            opening,closing = records[0],records[-1]
            self.assertEqual(opening['episode'],closing['episode'])
            self.assertEqual(1,closing['episode'])
            point = closing['point_changes'][0]
            self.assertEqual(0. if actual_return else -1.,point['expected_delta'])
            self.assertEqual(1. if actual_return else 0.,point['ground_delta'])
            self.assertEqual(1.,closing['opening']['position'][1])

    def test_new_episode_cannot_report_an_old_solver(self):
        runtime,state = self.scene(lambda x,z:0.)
        state.update(y=1.,airborne=True,_support_mode_solver_receipt={'stale':True})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertTrue(runtime._contact_edge_support_needed(state))
            self.assertNotIn('_support_mode_solver_receipt',state)
            state.update(y=0.,airborne=False)
            self.assertTrue(runtime._release_detailed_support(state))
        self.assertIsNone(self.records(output.getvalue())[-1]['solver'])


if __name__ == '__main__':
    unittest.main()
