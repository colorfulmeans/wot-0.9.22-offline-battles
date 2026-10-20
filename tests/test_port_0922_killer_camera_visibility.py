"""Exercise darkness before and during the stock five-second killer vision."""
import types
import unittest
from unittest import mock

from test_port_0922_battle_runtime import (
    BattleRuntime, _runtime, _Vehicle, _Descriptor, _Vector)


class StockDelayFixture:
    """The reviewed #1513 leave callback copies, rather than retains, a provider."""
    def __init__(self, camera, killer):
        self._PostmortemDelay__arcadeCamera = camera
        self._PostmortemDelay__killerVehicleID = killer
        self._PostmortemDelay__bActive = True
        self._PostmortemDelay__bKillerVisionActive = True
        self.timer = object()
        self.notifications = 0

    def _PostmortemDelay__onVehicleLeaveWorld(self, vehicle):
        if (self._PostmortemDelay__bActive and
                vehicle.id == self._PostmortemDelay__killerVehicleID and
                self._PostmortemDelay__bKillerVisionActive):
            camera = self._PostmortemDelay__arcadeCamera
            camera.vehicleMProv = types.SimpleNamespace(x=camera.vehicleMProv.x)
            self.notifications += 1

    def finish(self, wreck):
        # Stock __onKillerVisionFinished restores the local vehicle provider.
        self._PostmortemDelay__bKillerVisionActive = False
        self._PostmortemDelay__arcadeCamera.vehicleMProv = wreck


class KillerCameraVisibilityTests(unittest.TestCase):
    def setUp(self):
        runtime = _runtime()
        self.battle = BattleRuntime(runtime)
        self.battle._avatar = runtime.bigworld.avatar
        self.vehicle = _Vehicle(11, _Descriptor(), _Vector(), (0, 0, 0),
                                {'health': 500})
        self.vehicle.model = object()
        self.vehicle.appearance = types.SimpleNamespace(changeVisibility=mock.Mock())
        self.battle._remote_factory = types.SimpleNamespace(get=lambda key: self.vehicle)
        self.battle._sync_fire_effect = mock.Mock()
        self.battle._sync_remote_visual_components = mock.Mock()
        self.record = dict(engine_id=11, ready=True, presentation=True,
                           spot_visible=True, state=dict(team=2, health=500, alive=True))
        self.live = types.SimpleNamespace(x=100)
        self.camera = types.SimpleNamespace(vehicleMProv=self.live)
        self.delay = StockDelayFixture(self.camera, 11)
        self.battle._avatar.inputHandler._AvatarInputHandler__curCtrl = (
            types.SimpleNamespace(curPostmortemDelay=self.delay))

    def present(self, visible, marker=None):
        return self.battle._set_record_spot_visibility(self.record, visible, marker)

    def test_darkness_freezes_once_and_stock_timer_returns_to_wreck(self):
        timer = self.delay.timer
        self.present(True)
        self.live.x = 120
        self.assertEqual(120, self.camera.vehicleMProv.x)
        self.present(False)
        frozen = self.camera.vehicleMProv
        self.live.x = 200
        self.present(False)
        self.assertIs(frozen, self.camera.vehicleMProv)
        self.assertEqual(120, frozen.x)
        self.assertEqual(1, self.delay.notifications)
        self.assertIs(timer, self.delay.timer)
        self.assertTrue(self.delay._PostmortemDelay__bActive)
        # A new reveal must not rebind the already completed leave-world edge.
        self.present(True)
        self.assertIs(frozen, self.camera.vehicleMProv)
        wreck = types.SimpleNamespace(x=10)
        self.delay.finish(wreck)
        self.present(False)
        self.assertIs(wreck, self.camera.vehicleMProv)

    def test_darkness_during_fade_is_reconciled_after_vision_starts(self):
        self.delay._PostmortemDelay__bKillerVisionActive = False
        self.present(False)
        self.assertEqual(0, self.delay.notifications)
        self.delay._PostmortemDelay__bKillerVisionActive = True
        self.live.x = 130
        # Presentation signature is unchanged; the camera edge must still run.
        self.present(False)
        self.live.x = 200
        self.assertEqual(130, self.camera.vehicleMProv.x)
        self.assertEqual(1, self.delay.notifications)

    def test_marker_memory_does_not_keep_the_camera_following(self):
        self.present(False, True)
        self.assertEqual(1, self.delay.notifications)
        self.assertFalse(self.record['spot_visible'])
        self.assertTrue(self.record['spot_marker_visible'])
        self.vehicle.appearance.changeVisibility.assert_called_once_with(False)

    def test_other_hidden_vehicles_and_visible_wrecks_do_not_freeze(self):
        self.delay._PostmortemDelay__killerVehicleID = 99
        self.present(False)
        self.assertEqual(0, self.delay.notifications)
        self.delay._PostmortemDelay__killerVehicleID = 11
        self.record['state'].update(health=0, alive=False)
        self.present(False)
        self.assertEqual(0, self.delay.notifications)

    def test_new_death_delay_has_its_own_visibility_edge(self):
        self.present(False)
        self.camera.vehicleMProv = self.live
        replacement = StockDelayFixture(self.camera, 11)
        self.battle._avatar.inputHandler._AvatarInputHandler__curCtrl.curPostmortemDelay = replacement
        self.present(False)
        self.assertEqual(1, replacement.notifications)

    def test_inactive_delay_does_not_touch_camera_or_timer(self):
        self.delay._PostmortemDelay__bActive = False
        self.present(False)
        self.assertIs(self.live, self.camera.vehicleMProv)
        self.assertEqual(0, self.delay.notifications)


if __name__ == '__main__':
    unittest.main()
