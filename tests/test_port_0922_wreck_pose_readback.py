"""A dead model can copy its provider while final pose events are deduplicated."""
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922.entities.native_remote_vehicle import _NativeRemoteState


def vector(value):
    return types.SimpleNamespace(x=value[0], y=value[1], z=value[2])


class Matrix:
    def __init__(self, source=None):
        self.translation = vector((0., 0., 0.)) if source is None else vector(
            (source.translation.x, source.translation.y, source.translation.z))
        self.axes = tuple(source.axes) if source is not None else (
            (1., 0., 0.), (0., 1., 0.), (0., 0., 1.))

    def applyToAxis(self, index):
        return vector(self.axes[index])


class CopyingModel:
    def __init__(self, matrix):
        self.writes = 0
        self.value = Matrix(matrix)

    @property
    def matrix(self):
        return Matrix(self.value)

    @matrix.setter
    def matrix(self, value):
        self.writes += 1
        self.value = Matrix(value)


class WreckReadbackTests(unittest.TestCase):
    def scene(self):
        state = object.__new__(_NativeRemoteState)
        state._math = types.SimpleNamespace(Matrix=Matrix)
        state.provider = Matrix()
        state.provider.translation = vector((9.0036, -14.6673, 87.2514))
        copied = Matrix(state.provider)
        copied.translation.y = -12.1909
        state.entity = types.SimpleNamespace(id=12, isAlive=lambda: False,
            model=CopyingModel(copied))
        state._engine_owns_entity = lambda: True
        return state

    def test_captured_248cm_death_copy_is_rebound_to_final_provider(self):
        state = self.scene()
        with mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.write_json_record') as log:
            self.assertTrue(state.reconcile_wreck_pose(10.))
            self.assertAlmostEqual(-14.6673, state.entity.model.matrix.translation.y)
            receipt = log.call_args.args[1]
            self.assertAlmostEqual(2.4764, receipt['position_error'])
            self.assertTrue(receipt['verified'])
            self.assertFalse(state.reconcile_wreck_pose(10.1))
            self.assertFalse(state.reconcile_wreck_pose(10.6))
        self.assertEqual(1, state.entity.model.writes)

    def test_late_replacement_and_rotation_only_copy_are_detected(self):
        state = self.scene()
        with mock.patch('gui.mods.offline_lan_0922.native_input_diagnostics.write_json_record'):
            state.reconcile_wreck_pose(10.)
            replacement = Matrix(state.provider)
            replacement.axes = ((0., 0., 1.), (0., 1., 0.), (-1., 0., 0.))
            state.entity.model = CopyingModel(replacement)
            self.assertTrue(state.reconcile_wreck_pose(10.01))
            self.assertEqual(state.provider.axes, state.entity.model.matrix.axes)

    def test_live_or_released_entity_never_reads_a_native_model(self):
        state = self.scene()
        state.entity = types.SimpleNamespace(isAlive=lambda: True)
        self.assertFalse(state.reconcile_wreck_pose(1.))
        state.entity = None
        state._engine_owns_entity = lambda: False
        self.assertFalse(state.reconcile_wreck_pose(1.))

    def test_final_duplicate_pose_still_checks_a_dead_compound(self):
        from test_port_0922_battle_runtime import BattleRuntime, _runtime
        battle = BattleRuntime(_runtime())
        battle._binding = mock.Mock()
        vehicle = types.SimpleNamespace(reconcile_wreck_pose=mock.Mock(return_value=True),
            settle_motion=mock.Mock(return_value=True))
        battle._remote_factory = types.SimpleNamespace(get=lambda ident: vehicle)
        battle._update_bot_tracks = mock.Mock(return_value=True)
        record = dict(engine_id=12,kind='bot',native_remote=True,
            state=dict(health=0,alive=False,speed=0.))
        pose = dict(x=9.0036,y=-14.6673,z=87.2514,yaw=2.07556,pitch=-.11725,roll=.15309)
        battle._apply_record_pose(record,pose)
        battle._apply_record_pose(record,pose)
        self.assertEqual(1,battle._binding.set_vehicle_pose.call_count)
        self.assertEqual([True,False],
            [call.args[1] for call in vehicle.reconcile_wreck_pose.call_args_list])
        record['state'].update(alive=True,health=1)
        battle._apply_record_pose(record,pose)
        self.assertEqual(2,vehicle.reconcile_wreck_pose.call_count)


if __name__ == '__main__':
    unittest.main()
