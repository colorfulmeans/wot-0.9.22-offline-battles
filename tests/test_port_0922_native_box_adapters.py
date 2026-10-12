import math
import types
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922 import native_destructibles as native
from gui.mods.offline_lan_0922 import native_math
from gui.mods.offline_lan_0922 import native_input_diagnostics as diagnostics


class Vector:
    def __init__(self, x, y=0., z=0.):
        self.x, self.y, self.z = x, y, z

    def __sub__(self, other):
        return Vector(self.x-other.x, self.y-other.y, self.z-other.z)

    @property
    def length(self):
        return math.sqrt(self.x*self.x+self.y*self.y+self.z*self.z)


class NativeBoxAdapterTests(unittest.TestCase):
    def test_box_rejection_evidence_names_the_actual_native_opcode(self):
        with mock.patch.dict(diagnostics.__dict__, {'_counts': {}, '_reported': set(), '_reports_by_method': {}}), \
                mock.patch.object(diagnostics, '_write_record') as write:
            diagnostics.record('destr_box_geometry', (0, ((), None, None, None, .05, 7)))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 0},
                             write.call_args.args[0]['native_profile'])
            diagnostics.record('destr_box_geometry', (1, ()))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 1},
                             write.call_args.args[0]['native_profile'])

    def test_custom_vector_and_helper_protocols_do_not_enter_native(self):
        box = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), None)
        with mock.patch.object(native_math, 'call') as call:
            self.assertIsNone(native.box_probe(sensor, (box,), Vector(0.)))
            call.assert_not_called()
        with mock.patch.object(sensor, '_vector_dot', lambda *args: 0.), \
                mock.patch.object(native, '_native_box_point') as point, \
                mock.patch.object(native_math, 'call') as call:
            self.assertIsNone(native.box_probe(sensor, (box,), Vector(0.)))
            point.assert_not_called()
            call.assert_not_called()

    def test_envelope_keeps_original_box_identity_cache_and_none_semantics(self):
        axes = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
        boxes = [((0., 0., 0.), axes, 73)]
        instance = {'boxes': boxes}
        with mock.patch.object(native, 'box_envelope', return_value=(((0., 0., 0.), axes),)) as envelope:
            first = sensor._instance_motion_envelope_1513(instance)
            self.assertIs(first, sensor._instance_motion_envelope_1513(instance))
            envelope.assert_called_once()
            instance['boxes'] = list(boxes)
            self.assertEqual(first, sensor._instance_motion_envelope_1513(instance))
            self.assertEqual(2, envelope.call_count)
        with mock.patch.object(native, 'box_envelope', return_value=(None,)):
            self.assertIsNone(sensor._instance_motion_envelope_1513({'boxes': boxes}))

    def test_owned_broken_module_uses_one_batch_and_keeps_authority_checks(self):
        axes = ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.))
        boxes = [((20., 0., 0.), axes, 73), ((5., 0., 0.), axes, 74)]
        authority = types.SimpleNamespace(is_destroyed=mock.Mock(side_effect=lambda chunk, item, material: material == 74))
        rows = ((0, (.9, 1.), None), (1, (.1, .8), None))
        with mock.patch.dict(sensor.__dict__, {
                'g_offh_destr_instances': {(22, 7): {'kind': 'structure', 'boxes': boxes}},
                'g_offh_destr_speculative': set()}), \
                mock.patch.object(sensor, '_destructible_isolated_1513', return_value=False), \
                mock.patch.object(sensor, '_layout_repair_pending_1513', return_value=False), \
                mock.patch.object(sensor, '_get_destr_authority', return_value=authority), \
                mock.patch.object(native, 'box_probe', return_value=rows) as probe:
            result = sensor._owned_component_skin_1513(
                Vector(3.), Vector(0.), Vector(10.), {(73, 0, 7, 22)})
        self.assertEqual((8., {(73, 0, 7, 22)}), result)
        probe.assert_called_once()
        self.assertEqual(3, probe.call_args.args[-1])
        self.assertEqual([mock.call(22, 7, 74), mock.call(22, 7, 73), mock.call(22, 7, 74)],
                         authority.is_destroyed.call_args_list)

    def test_native_interval_no_hit_does_not_call_the_reference_again(self):
        box = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), None)
        with mock.patch.object(native, 'box_probe', return_value=((0, None, None),)), \
                mock.patch.object(sensor, '_box_face_axes', side_effect=AssertionError('reference re-entered')):
            self.assertFalse(sensor._point_in_world_box(Vector(100.), box))
            self.assertIsNone(sensor._segment_world_box_interval(Vector(100.), Vector(200.), box))
            self.assertIsNone(sensor._projected_box_interval_1513(Vector(100.), Vector(200.), box))
