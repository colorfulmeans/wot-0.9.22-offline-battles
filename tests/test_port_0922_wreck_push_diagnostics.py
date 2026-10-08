"""Wreck push terminal reasons and movement beyond the original death pose."""
import contextlib
import io
import json
import unittest

import test_port_0922_bot_runtime as bots


class WreckPushDiagnosticTests(unittest.TestCase):
    setUp = bots.ShovedWreckTests.setUp
    tearDown = bots.ShovedWreckTests.tearDown
    _runtime = bots.ShovedWreckTests._runtime
    _wreck = bots.ShovedWreckTests._wreck

    @staticmethod
    def records(output):
        return [json.loads(line.split('WRECK PUSH ', 1)[1])
                for line in output.getvalue().splitlines()
                if 'WRECK PUSH ' in line]

    def test_repeated_push_uses_current_pose_and_stops_at_a_new_world_wall(self):
        runtime=self._runtime();state=self._wreck(runtime);starts=[];wall_z=20.
        def motion(bot_id,position,yaw,speed,descriptor,step,now,commit,**kwargs):
            starts.append(tuple(position))
            return 'hard' if position[2]+abs(speed)*step>=wall_z else 'clear'
        runtime.motion_resolver=motion
        for tick in range(120):
            runtime._contact_now=tick*.1
            runtime._apply_wreck_contact_response(state,dict(
                delta_velocity=(0.,2.),correction=(0.,.05)),.1)
        self.assertGreater(state['z'],10.)
        self.assertLess(state['z'],wall_z)
        self.assertGreater(max(pos[2] for pos in starts),10.)
        self.assertEqual(0.,state['y'])

    def test_world_wall_holds_but_missing_or_lower_support_starts_a_physical_fall(self):
        runtime=self._runtime(clear=False,ground=0.);state=self._wreck(runtime)
        self.assertFalse(runtime._apply_wreck_contact_response(state,dict(
            delta_velocity=(0.,2.),correction=(0.,.05)),.1))
        self.assertEqual((0.,0.,0.),(state['x'],state['y'],state['z']))
        self.assertEqual((0.,0.),(state['push_x'],state['push_z']))
        for ground in (None,-40.):
            with self.subTest(ground=ground):
                runtime=self._runtime(ground=ground);state=self._wreck(runtime)
                self.assertTrue(runtime._apply_wreck_contact_response(state,dict(
                    delta_velocity=(0.,2.),correction=(0.,.05)),.1))
                self.assertTrue(state['airborne'])
                self.assertLess(state['vertical_speed'],0.)
                self.assertGreater(state['y'],-1.)
                self.assertLess(state['y'],0.)
                self.assertLess(state['z'],1.)

    def test_track_hold_does_not_move_the_wreck_or_log_each_contact(self):
        runtime=self._runtime();state=self._wreck(runtime);output=io.StringIO()
        with contextlib.redirect_stdout(output):
            for tick in range(300):
                runtime._contact_now=tick/30.
                runtime._apply_wreck_contact_response(state,dict(
                    delta_velocity=(0.,.001),correction=(0.,.01)),1./30.)
        self.assertEqual(0.,state['z'])
        self.assertNotIn('WRECK motion',output.getvalue())
        self.assertLessEqual(output.getvalue().count('SUSPENSION bot trial'),1)


class SustainedWreckDriveTests(unittest.TestCase):
    setUp = bots.WreckPushMassTests.setUp
    tearDown = bots.WreckPushMassTests.tearDown
    _travel = bots.WreckPushMassTests._travel

    def test_powered_contact_continues_after_the_first_ten_metres(self):
        with contextlib.redirect_stdout(io.StringIO()):
            first_six_seconds = self._travel(68000.0, 1050.0, 32000.0, ticks=180)
            twelve_seconds = self._travel(68000.0, 1050.0, 32000.0, ticks=360)
        self.assertGreater(first_six_seconds, 10.0)
        self.assertGreater(twelve_seconds, first_six_seconds + 10.0)
