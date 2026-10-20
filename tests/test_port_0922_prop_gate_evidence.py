"""Fragile truck diagnostics use the same mass correction as the stock gate."""
import contextlib
import io
import json
import math
import sys
import types
import unittest
from unittest import mock
from test_port_0922_destructibles import destructibles_sensor as sensor


class PropGateEvidenceTests(unittest.TestCase):
    def test_fragile_gate_reports_corrected_energy_and_is_bounded(self):
        desc = dict(type=2, health=100., kineticDamageCorrection=.5)
        area = types.SimpleNamespace(g_cache=types.SimpleNamespace(
            getDescByFilename=lambda name: desc, unitVehicleMass=40000.))
        cache = types.SimpleNamespace(scaledDestructibleHealth=lambda scale,hp: scale*hp)
        candidate = (32897,121,None,'content/truck.model','fragile',1.)
        td = dict(physics=dict(weight=32000.))
        before = dict(desc)
        output = io.StringIO()
        with mock.patch.dict(sys.modules, AreaDestructibles=area, DestructiblesCache=cache), \
                mock.patch.dict(sensor.__dict__, g_offh_destr_crush_gate_times={}), \
                contextlib.redirect_stdout(output):
            sensor._crush_gate_diagnostic_1513(candidate,2.,10.,td,False,True,True,5.)
            sensor._crush_gate_diagnostic_1513(candidate,2.,10.,td,False,True,True,5.1)
        lines = output.getvalue().splitlines()
        self.assertEqual(1,len(lines))
        row = json.loads(lines[0][lines[0].index('{'):])
        self.assertEqual('directional_cap',row['gate'])
        self.assertEqual('fragile',row['kind'])
        self.assertEqual(100.,row['scaled_health'])
        self.assertAlmostEqual(.5*32000.*4.*.00015*math.sqrt(.8),row['energy'])
        self.assertAlmostEqual(.5*32000.*100.*.00015*math.sqrt(.8),row['cap_energy'])
        self.assertEqual(before,desc)


if __name__ == '__main__':
    unittest.main()
