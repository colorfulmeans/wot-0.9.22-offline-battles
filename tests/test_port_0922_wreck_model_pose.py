"""Corpse refresh contracts; native #1513 rendering remains acceptance work."""
import gc
import types
import unittest
import weakref
from unittest import mock

from gui.mods.offline_lan_0922 import compat, wreck_model_pose as pose


class Matrix:
    def __init__(self, source=None):
        self.yaw = self.pitch = self.roll = 0.0
        if source is not None:
            source = source.target if isinstance(source, Provider) else source
            if source is not None:
                self.yaw, self.pitch, self.roll = source.yaw, source.pitch, source.roll

    def setRotateYPR(self, angles):
        self.yaw, self.pitch, self.roll = angles


class Provider:
    def __init__(self):
        self.target = None


class Appearance:
    def __init__(self):
        self.turretMatrix, self.gunMatrix = Provider(), Provider()

    def setupGunMatrixTargets(self, aim):
        self.turretMatrix.target, self.gunMatrix.target = aim.turretMatrix, aim.gunMatrix


class Vehicle:
    pass


class WreckPoseTests(unittest.TestCase):
    def setUp(self):
        self.appearance = Appearance()
        self.vehicle = Vehicle()
        self.vehicle.id, self.vehicle.health = 23, 0
        self.vehicle.isTurretDetached = False
        self.vehicle.appearance = self.appearance
        self.appearance._CompoundAppearance__vehicle = self.vehicle
        self.owner = types.SimpleNamespace(_battle_active=True,
            _battle_player_vehicle_id=23, _wreck_pose_battle=object(),
            _compound_refresh_token=object(), _compound_refreshing_models=self.appearance,
            _original_compound_getattribute=object.__getattribute__,
            _runtime=types.SimpleNamespace(math=types.SimpleNamespace(Matrix=Matrix),
                bigworld=types.SimpleNamespace(entity=lambda unused: self.vehicle, time=lambda: 1.0)))
        self.context = self.context_for_refresh()

    def context_for_refresh(self):
        return (self.owner._wreck_pose_battle, self.owner._compound_refresh_token, id(self.vehicle))

    def restore(self, yaw=-.83278477, pitch=-.05432706, context=None):
        return pose.restore(self.owner, self.appearance, context or self.context, yaw, pitch)

    def test_stock_snapshot_restores_display_and_proxy_never_calls_native_sync(self):
        native = mock.Mock()
        proxy = compat._OfflineVehicleFilterSyncProxy(native,
            wreck_restore=(self.owner, self.appearance, self.context))
        self.assertIsNone(proxy.syncGunAngles(-.83, -.054))
        native.syncGunAngles.assert_not_called()
        self.assertEqual(-.83, Matrix(self.appearance.turretMatrix).yaw)
        self.assertEqual(-.054, Matrix(self.appearance.gunMatrix).pitch)

    def test_repeated_refresh_uses_owned_snapshot_after_provider_reset(self):
        self.assertTrue(self.restore())
        target = self.owner._local_wreck_aim
        self.appearance.turretMatrix.target = self.appearance.gunMatrix.target = None
        self.owner._compound_refresh_token = object()
        self.assertTrue(self.restore(0., 0., self.context_for_refresh()))
        self.assertIs(target, self.owner._local_wreck_aim)
        self.assertEqual(-.83278477, Matrix(self.appearance.turretMatrix).yaw)

    def test_live_remote_detached_missing_identity_and_inactive_are_untouched(self):
        changes = [('health', 1), ('isTurretDetached', True), ('_offlineNativeRemote', True)]
        for attribute, value in changes:
            with self.subTest(attribute=attribute), mock.patch.object(self.vehicle, attribute, value, create=True):
                self.assertFalse(self.restore())
        for attribute, value in [('_battle_active', False), ('_battle_player_vehicle_id', 24),
                                 ('_compound_refreshing_models', object())]:
            with self.subTest(attribute=attribute), mock.patch.object(self.owner, attribute, value):
                self.assertFalse(self.restore())
        with mock.patch.object(self.vehicle, 'appearance', Appearance()):
            self.assertFalse(self.restore())
        with mock.patch.object(self.owner._runtime.bigworld, 'entity', return_value=Vehicle()):
            self.assertFalse(self.restore())
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertFalse(hasattr(self.owner, '_local_wreck_aim'))

    def test_stale_round_refresh_and_entity_context_cannot_write_or_clear_current_pose(self):
        self.assertTrue(self.restore())
        target = self.owner._local_wreck_aim
        for context in [(object(), self.context[1], self.context[2]),
                        (self.context[0], object(), self.context[2])]:
            self.assertFalse(self.restore(context=context))
            self.assertIs(target, self.owner._local_wreck_aim)
        # A stale entity context must not clear a newer accepted owner either.
        self.assertFalse(self.restore(context=(self.context[0], self.context[1], -1)))
        self.assertIs(target, self.owner._local_wreck_aim)

    def test_detachment_and_revival_release_owned_targets(self):
        for attribute, value in [('isTurretDetached', True), ('health', 100)]:
            with self.subTest(attribute=attribute):
                self.assertTrue(self.restore())
                with mock.patch.object(self.vehicle, attribute, value):
                    self.assertFalse(self.restore())
                self.assertIsNone(self.owner._local_wreck_aim)
                self.assertIsNone(self.appearance.turretMatrix.target)

    def test_failed_native_readback_rolls_back_both_targets(self):
        old = Matrix(); old.yaw = .2
        self.appearance.turretMatrix.target = old
        with mock.patch.object(self.owner._runtime.math, 'Matrix', side_effect=lambda source=None: Matrix()):
            self.assertFalse(self.restore())
        self.assertIs(old, self.appearance.turretMatrix.target)
        self.assertIsNone(self.appearance.gunMatrix.target)
        self.assertIsNone(getattr(self.owner, '_local_wreck_aim', None))

    def test_partial_setup_failure_preserves_previous_targets(self):
        def fail(aim):
            self.appearance.turretMatrix.target = aim.turretMatrix
            raise RuntimeError('partial native setup')
        with mock.patch.object(self.appearance, 'setupGunMatrixTargets', side_effect=fail):
            self.assertFalse(self.restore())
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertIsNone(self.appearance.gunMatrix.target)

    def test_repeated_readback_failure_does_not_leave_unowned_old_targets(self):
        self.assertTrue(self.restore())
        with mock.patch.object(self.owner._runtime.math, 'Matrix', side_effect=RuntimeError('retired provider')):
            self.assertFalse(self.restore())
        self.assertIsNone(self.owner._local_wreck_aim)
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertIsNone(self.appearance.gunMatrix.target)

    def test_basic_diagnostic_builder_is_lazy(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        with mock.patch.object(logs, 'detailed_enabled', return_value=False):
            builder = mock.Mock(side_effect=AssertionError('constructed payload'))
            pose._record(self.owner, 'test', builder)
        builder.assert_not_called()

    def test_nonfinite_angles_never_bind(self):
        for value in [float('nan'), float('inf'), -float('inf')]:
            self.assertFalse(self.restore(yaw=value))
            self.assertFalse(self.restore(pitch=value))
        self.assertIsNone(self.appearance.turretMatrix.target)

    def test_cleanup_is_idempotent_and_preserves_a_new_writer(self):
        self.assertTrue(self.restore())
        replacement = Matrix()
        self.appearance.gunMatrix.target = replacement
        pose.clear(self.owner, 'deactivate', self.appearance)
        pose.clear(self.owner, 'deactivate', self.appearance)
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertIs(replacement, self.appearance.gunMatrix.target)

    def test_owner_keeps_no_entity_appearance_or_rotator_reference(self):
        self.assertTrue(self.restore())
        vehicle, appearance = weakref.ref(self.vehicle), weakref.ref(self.appearance)
        self.owner._compound_refreshing_models = None
        self.owner._runtime.bigworld.entity = lambda unused: None
        self.vehicle = self.appearance = None
        gc.collect()
        self.assertIsNone(vehicle())
        self.assertIsNone(appearance())
        pose.clear(self.owner, 'retired_entity')
        self.assertIsNone(self.owner._local_wreck_aim)

    def test_basic_entry_does_not_build_diagnostic_payload(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        with mock.patch.object(logs, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'battle_review_record') as record:
            self.assertTrue(self.restore())
            pose.clear(self.owner, 'exit')
        record.assert_not_called()


class WreckPoseIntegrationTests(unittest.TestCase):
    """Exercise installed wrappers with #1513's nested filter ownership."""
    def setUp(self):
        import test_port_0922 as harness
        self.fixture = harness.OfflineCompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        runtime, self.operations = self.fixture._runtime()
        self.runtime = runtime
        self.appearance_type = runtime.compound_appearance_module.CompoundAppearance

        def deactivate(appearance, stopEffects=True):
            appearance.turretMatrix.target = appearance.gunMatrix.target = None
            appearance._CompoundAppearance__vehicle = None

        def activate(appearance, vehicle):
            # This nested read must remain the real filter, never our proxy.
            vehicle.filter = appearance._CompoundAppearance__filter
            appearance._CompoundAppearance__vehicle = vehicle

        def refresh(appearance, state, resources):
            vehicle = appearance._CompoundAppearance__vehicle
            yaw, pitch = Matrix(appearance.turretMatrix).yaw, Matrix(appearance.gunMatrix).pitch
            appearance.deactivate(False)
            appearance.activate(vehicle)
            appearance._CompoundAppearance__filter.syncGunAngles(yaw, pitch)
            if resources == 'fail':
                raise RuntimeError('stock refresh failed')
            return 'stock-result'

        self.appearance_type.deactivate = deactivate
        self.appearance_type.activate = activate
        self.appearance_type._CompoundAppearance__onModelsRefresh = refresh
        runtime.math.Matrix = Matrix
        self.owner = harness._load_port_source('compat').OfflineCompatibility(runtime)
        self.owner.configure_battle()
        self.addCleanup(self.owner.fini)
        self.native = mock.Mock()
        self.appearance = self.appearance_type(self.native)
        self.appearance.turretMatrix, self.appearance.gunMatrix = Provider(), Provider()
        self.appearance.setupGunMatrixTargets = types.MethodType(Appearance.setupGunMatrixTargets, self.appearance)
        self.vehicle = Vehicle()
        self.vehicle.id, self.vehicle.health, self.vehicle.isTurretDetached = 23, 0, False
        self.vehicle.appearance = self.appearance
        self.appearance._CompoundAppearance__vehicle = self.vehicle
        runtime.bigworld.entity = lambda unused: self.vehicle
        self.owner._battle_player_vehicle_id = 23
        self.appearance.setupGunMatrixTargets(pose._WreckAim(MatrixModule, (), -.83, -.054))

    def refresh(self, resources=None):
        return self.appearance._CompoundAppearance__onModelsRefresh('destroyed', resources)

    def test_actual_stock_restore_uses_candidate_and_nested_activate_keeps_filter(self):
        self.assertEqual('stock-result', self.refresh())
        self.assertEqual(-.83, Matrix(self.appearance.turretMatrix).yaw)
        self.assertIs(self.native, self.vehicle.filter)
        self.native.syncGunAngles.assert_not_called()
        self.assertIsNone(self.owner._compound_refreshing_models)
        self.assertIsNone(self.owner._compound_refresh_token)
        self.assertEqual('stock-result', self.refresh())
        self.assertEqual(-.83, Matrix(self.appearance.turretMatrix).yaw)

    def test_actual_final_deactivate_and_battle_exit_release_targets(self):
        self.refresh()
        self.appearance.deactivate()
        self.assertIsNone(self.owner._local_wreck_aim)
        self.appearance._CompoundAppearance__vehicle = self.vehicle
        self.appearance.setupGunMatrixTargets(pose._WreckAim(MatrixModule, (), .4, .1))
        self.refresh()
        self.owner.deactivate_map()
        self.assertIsNone(self.owner._local_wreck_aim)
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertIsNone(self.owner._wreck_pose_battle)

    def test_actual_refresh_failure_cleans_candidate_and_preserves_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'stock refresh failed'):
            self.refresh('fail')
        self.assertIsNone(self.owner._local_wreck_aim)
        self.assertIsNone(self.appearance.gunMatrix.target)
        self.assertIsNone(self.owner._compound_refresh_token)

    def test_actual_next_battle_discards_previous_snapshot(self):
        self.refresh()
        previous = self.owner._wreck_pose_battle
        self.owner.configure_battle()
        self.assertIsNone(self.owner._local_wreck_aim)
        self.assertIsNone(self.appearance.turretMatrix.target)
        self.assertIsNot(previous, self.owner._wreck_pose_battle)

    def test_actual_basic_entry_restores_without_diagnostics(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
        with mock.patch.object(logs, 'detailed_enabled', return_value=False), \
                mock.patch.object(logs, 'battle_review_record') as record:
            self.refresh()
        self.assertEqual(-.83, Matrix(self.appearance.turretMatrix).yaw)
        record.assert_not_called()


MatrixModule = types.SimpleNamespace(Matrix=Matrix)


if __name__ == '__main__':
    unittest.main()
