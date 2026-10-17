"""Round-boundary collection and a bounded update-fixture regression."""

import gc
import os
import sys
import types
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CLIENT_ROOT = ROOT / 'src' / 'res' / 'scripts' / 'client'
sys.path.insert(0, str(CLIENT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.mods.offline_lan_0922 import gc_sweep


class _Sink(object):
    def __init__(self):
        self.text = ''

    def write(self, value):
        self.text += value


class GcSweepTest(unittest.TestCase):
    def setUp(self):
        self._enabled = gc.isenabled()
        self._stdout = sys.stdout
        self.addCleanup(setattr, sys, 'stdout', self._stdout)

    def tearDown(self):
        # The engine's choice about the collector is not ours to change.
        self.assertEqual(self._enabled, gc.isenabled())

    def _leak_cycles(self, count):
        for index in range(count):
            record = {'id': index, 'rows': []}
            holder = [record]
            record['self'] = holder

    def test_a_cycle_is_collected_and_reported(self):
        gc.collect()
        self._leak_cycles(500)
        sys.stdout = _Sink()
        collected = gc_sweep.sweep('round_end', 4)
        text = sys.stdout.text
        sys.stdout = self._stdout
        self.assertGreater(collected, 0)
        self.assertIn('PYSWEEP phase=round_end round=4', text)
        self.assertIn('unreachable=%d' % collected, text)
        self.assertIn('elapsed_ms=', text)
        self.assertIn('gc_enabled=', text)

    def test_it_never_enables_the_collector(self):
        # Enabling it would change the engine's decision for every frame
        # rather than once per round.
        sys.stdout = _Sink()
        gc_sweep.sweep('round_end', 1)
        sys.stdout = self._stdout
        self.assertEqual(self._enabled, gc.isenabled())

    def test_a_broken_collector_never_raises_into_the_round(self):
        original = gc_sweep.gc.collect
        gc_sweep.gc.collect = lambda *args: (_ for _ in ()).throw(
            RuntimeError('no collector'))
        self.addCleanup(setattr, gc_sweep.gc, 'collect', original)
        sys.stdout = _Sink()
        self.assertEqual(-1, gc_sweep.sweep('round_end', 1))
        self.assertIn('PYSWEEP phase=round_end round=1 error=collection_failed',
                      sys.stdout.text)

    def test_sweep_preserves_an_existing_saveall_session(self):
        existing = {'owned_by_debugger': True}
        garbage = [existing]
        collect = mock.Mock(side_effect=lambda: garbage.append({}) or 1)
        collector = types.SimpleNamespace(
            DEBUG_SAVEALL=gc.DEBUG_SAVEALL, garbage=garbage,
            get_debug=lambda: gc.DEBUG_SAVEALL, collect=collect,
            isenabled=lambda: False)
        sys.stdout = _Sink()
        with mock.patch.object(gc_sweep, 'gc', collector):
            self.assertEqual(-1, gc_sweep.sweep('round_end', 2))
        collect.assert_not_called()
        self.assertEqual([existing], garbage)
        self.assertIn('skipped=debug_saveall', sys.stdout.text)


class BotUpdateCollectionRegressionTest(unittest.TestCase):
    """Check manual reclamation after controlled update batches.

    The Python 3 fixture exercises two batches of 200 updates with four Bots and a
    human player on the non-fixed-control path while retaining the runtime.
    Current runtime permits transient cycles and owns manual collection at
    teardown. Check that collection reaches a fixed point, keeps live actor
    state and does not enable automatic GC. This engine-free fixture cannot
    prove native traversal safety or real frame pacing.

    Run it in a subprocess because BotRuntime changes process-global logging
    state that unrelated loadout tests also exercise.
    """

    DRIVER = r"""
import contextlib, gc, io, sys, json
from pathlib import Path
root=Path(sys.argv[1])
sys.path[:0]=[str(root/'tests'),str(root/'server'),str(root/'src/res/scripts/client')]
from unittest import mock
import test_port_0922_bot_runtime as driver
import effective_params_fixture as fixture
from gui.mods.offline_lan_0922 import gc_sweep

case = driver.BotRuntimeTests('run')
case.setUp()
with mock.patch.object(case.module.native_simulation.NativeSimulation,
                       'create', return_value=None):
    runtime = case._roster_runtime()
player = fixture.wire_player(5)
player.setdefault('team', 1)
player.setdefault('position', [0.0, 0.0, 0.0])
player.setdefault('yaw', 0.0)

gc.collect()
gc.disable()
sink = io.StringIO()
observations=[]
with contextlib.redirect_stdout(sink):
    for batch in range(2):
        for tick in range(200):
            runtime.update(0.05, 1.0 + (batch*200+tick) * 0.05, [player])
        actors={key:id(value) for key,value in runtime.states.items()}
        reclaimed=gc_sweep.sweep('round_end_fixture',batch)
        empty=gc.collect()
        assert actors=={key:id(value) for key,value in runtime.states.items()}
        observations.append(dict(reclaimed=reclaimed,empty=empty,enabled=gc.isenabled(),actors=len(actors)))
sys.stderr.write('SWEEPS=%s\n' % json.dumps(observations))
"""

    def test_update_batches_are_reclaimed_at_manual_sweeps_without_losing_live_state(self):
        import subprocess

        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment['PYTHONDONTWRITEBYTECODE'] = '1'
        environment['PYTHONPATH'] = os.pathsep.join((
            str(root / 'src' / 'res' / 'scripts' / 'client'),
            str(root / 'tests'),
        ))
        finished = subprocess.run(
            [sys.executable, '-c', self.DRIVER, str(root)],
            cwd=str(root), env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=300)
        report = finished.stderr.decode('utf-8', 'replace')
        self.assertEqual(
            0, finished.returncode,
            'the Bot update driver failed:\n%s' % report[-2000:])
        marker = [line for line in report.splitlines()
                  if line.startswith('SWEEPS=')]
        self.assertTrue(marker, 'driver reported no sweep outcomes:\n%s'
                        % report[-2000:])
        import json
        observations=json.loads(marker[-1].split('=',1)[1])
        self.assertEqual(2,len(observations))
        for row in observations:
            self.assertGreaterEqual(row['reclaimed'],0)
            self.assertEqual(0,row['empty'])
            self.assertFalse(row['enabled'])
            self.assertEqual(observations[0]['actors'],row['actors'])
            self.assertGreater(row['actors'],0)


if __name__ == '__main__':
    unittest.main()
