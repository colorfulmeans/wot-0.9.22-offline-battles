"""Continuous support at the mode boundary and stock module refresh rollback."""
import contextlib
import io
import types
import unittest
from unittest import mock
import test_port_0922_contact_support_navigation as support
import test_port_0922_battle_runtime as battle_fixture


class SupportBoundaryTests(unittest.TestCase):
    scene=support.ContactSupportTests.scene

    def test_continuous_uphill_top_is_not_a_missing_point(self):
        runtime,state=self.scene(lambda x,z:.35*max(0.,z))
        # Reproduce a basic pose lagging behind an uphill front point. The
        # old +0.6m ceiling returned None although the terrain was continuous.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(runtime._suspension_params_for(11))
        points=runtime._basic_support_status(state)
        self.assertTrue(next(p for p in points if p['name']=='front')['continuous_rise'])
        self.assertTrue(all(p["valid"] for p in points))

    def test_isolated_upper_platform_does_not_count_as_continuous_ground(self):
        runtime,state=self.scene(lambda x,z:1.5 if z>2.5 else 0.)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNotNone(runtime._suspension_params_for(11))
        front=next(p for p in runtime._basic_support_status(state) if p['name']=='front')
        self.assertFalse(front['valid'])
        self.assertFalse(front['continuous_rise'])

    def test_handoff_retires_old_slope_target(self):
        runtime,state=self.scene(lambda x,z:0.)
        state.update(_edge_support_active=True,airborne=False,
            _slope_pose_target=(.5,.5),terrain_pitch=0.,roll=0.)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._release_detailed_support(state))
        self.assertEqual((0.,0.),state['_slope_pose_target'])
        self.assertEqual((state['x'],state['z'],state['yaw']),state['pose_sample'])


class NativeDeviceRefreshRollbackTests(unittest.TestCase):
    def test_no_periodic_or_forced_device_icon_writer_remains(self):
        import inspect
        cls = battle_fixture.BattleRuntime
        self.assertFalse(hasattr(cls, '_refresh_native_device_icons'))
        for method in (cls._tick_critical_states, cls._present_critical):
            source = inspect.getsource(method)
            self.assertNotIn('invalidateVehicleState', source)
            self.assertNotIn('_refresh_native_device_icons', source)
        # Existing event-owned stock notifications and presentation diagnostics
        # remain; removing the second writer must not remove damage/repair.
        source = inspect.getsource(cls._present_critical)
        self.assertIn('_show_damage_info', source)
        self.assertIn('_report_critical_presentation', source)


if __name__=='__main__':unittest.main()
