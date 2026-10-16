"""Continuous support at the mode boundary and stock module refresh."""
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


class NativeDeviceRefreshTests(unittest.TestCase):
    def scene(self):
        runtime=battle_fixture._runtime()
        runtime.vehicle_view_state=types.SimpleNamespace(DEVICES=99)
        battle=battle_fixture.BattleRuntime(runtime)
        provider=types.SimpleNamespace(invalidateVehicleState=mock.Mock(),
            shared=types.SimpleNamespace(vehicleState=object(),messages=object()))
        battle._avatar=types.SimpleNamespace(guiSessionProvider=provider)
        battle._damage_info_is_serviceable=lambda:True
        battle._record_alive=lambda *args:True
        battle._clock=mock.Mock(return_value=1.)
        record=dict(local=True,engine_id=10)
        entity=types.SimpleNamespace(_destroyed_devices={'leftTrackHealth','rightTrackHealth'},_critical_devices=set())
        battle._report_critical_presentation=mock.Mock()
        return battle,record,entity,provider

    def test_destroyed_sides_repaint_through_stock_controller_without_sound(self):
        battle,record,entity,provider=self.scene()
        self.assertTrue(battle._refresh_native_device_icons(record,entity))
        self.assertEqual([mock.call(99,('leftTrack','destroyed','destroyed')),
            mock.call(99,('rightTrack','destroyed','destroyed'))],provider.invalidateVehicleState.call_args_list)
        self.assertFalse(battle._refresh_native_device_icons(record,entity))
        battle._clock.return_value=2.1
        self.assertTrue(battle._refresh_native_device_icons(record,entity))

    def test_repair_one_side_keeps_other_side_destroyed(self):
        battle,record,entity,provider=self.scene()
        battle._refresh_native_device_icons(record,entity)
        provider.invalidateVehicleState.reset_mock()
        entity._destroyed_devices.remove('leftTrackHealth')
        battle._refresh_native_device_icons(record,entity)
        self.assertEqual([mock.call(99,('leftTrack','normal','normal')),
            mock.call(99,('rightTrack','destroyed','destroyed'))],provider.invalidateVehicleState.call_args_list)

    def test_retiring_native_controller_failure_is_bounded_and_retryable(self):
        battle,record,entity,provider=self.scene()
        battle._warn_optional_failure=mock.Mock()
        provider.invalidateVehicleState.side_effect=RuntimeError('retiring controller')
        self.assertFalse(battle._refresh_native_device_icons(record,entity))
        self.assertNotIn('native_device_icons',record)
        calls=provider.invalidateVehicleState.call_count
        self.assertFalse(battle._refresh_native_device_icons(record,entity))
        self.assertEqual(calls,provider.invalidateVehicleState.call_count)
        battle._clock.return_value=2.1
        provider.invalidateVehicleState.side_effect=None
        self.assertTrue(battle._refresh_native_device_icons(record,entity))

    def test_remote_vehicle_never_repaints_player_devices(self):
        battle,record,entity,provider=self.scene();record['local']=False
        self.assertFalse(battle._refresh_native_device_icons(record,entity))
        provider.invalidateVehicleState.assert_not_called()


if __name__=='__main__':unittest.main()
