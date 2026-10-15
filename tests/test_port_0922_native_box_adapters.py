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
    def test_spatial_signature_uses_native_cells_but_reads_current_generations(self):
        generations = {(-1, 2): 7}
        with mock.patch.dict(sensor.__dict__, {
                'g_offh_destr_spatial_cell_generations': generations,
                'g_offh_destr_spatial_global_generation': 3}), \
                mock.patch.object(native_math, 'call', return_value=((-1, 2), (0, 2))) as call:
            rectangles = ((-1, 0, 2, 2),)
            self.assertEqual((3, (((-1, 2), 7), ((0, 2), 0))),
                             sensor._spatial_cell_signature_1513(rectangles))
            generations[(0, 2)] = 8
            self.assertEqual((3, (((-1, 2), 7), ((0, 2), 8))),
                             sensor._spatial_cell_signature_1513(rectangles))
            call.assert_called_with('destr_box_geometry', 3, rectangles)

    def test_box_rejection_evidence_names_the_actual_native_opcode(self):
        with mock.patch.dict(diagnostics.__dict__, {'_counts': {}, '_reported': set(), '_reports_by_method': {}}), \
                mock.patch.object(diagnostics, '_write_record') as write:
            diagnostics.record('destr_box_geometry', (0, ((), None, None, None, .05, 7)))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 0},
                             write.call_args.args[0]['native_profile'])
            diagnostics.record('destr_box_geometry', (1, ()))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 1},
                             write.call_args.args[0]['native_profile'])
            diagnostics.record('destr_box_geometry', (3, ((-9, -9, 14, 15),)))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 3},
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


class MotionWitnessTests(unittest.TestCase):
    box = ((0., 0., 0.), ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), 73)

    def test_complete_row_is_reused_only_within_one_contact(self):
        row = (0, None, (.2, .8), 1, 1)
        with mock.patch.object(native, 'motion_witnesses', return_value=(row,)) as call:
            query = sensor._MotionSkinWitnesses1513(Vector(0.), Vector(-2.), Vector(2.), Vector(1.))
            query.prime((self.box,))
            query.prime((self.box,))
            self.assertFalse(query.inside(self.box))
            self.assertIsNone(query.interval(self.box))
            self.assertEqual((.2, .8), query.projected(self.box))
            self.assertTrue(query.footprint(self.box))
            self.assertTrue(query.side(self.box))
            call.assert_called_once()
            fresh = sensor._MotionSkinWitnesses1513(Vector(3.), Vector(-2.), Vector(2.), None)
            fresh.prime((self.box,))
            self.assertEqual(2, call.call_count)

    def test_mutable_or_custom_geometry_keeps_reference_evaluation(self):
        class Number:
            def __float__(self):
                raise AssertionError('coercion')
        mutable = ([0., 0., 0.], self.box[1], 73)
        custom = ((Number(), 0., 0.), self.box[1], 73)
        with mock.patch.object(native, 'motion_witnesses') as call:
            query = sensor._MotionSkinWitnesses1513(Vector(0.), Vector(-2.), Vector(2.), None)
            query.prime((mutable,))
            query.prime((custom,))
            self.assertFalse(query.rows)
            call.assert_not_called()

    def test_changed_helper_retains_its_callbacks_and_no_native_batch(self):
        with mock.patch.object(sensor, '_point_in_world_box', return_value=True) as point, \
                mock.patch.object(native, 'motion_witnesses') as call:
            query = sensor._MotionSkinWitnesses1513(Vector(0.), Vector(-2.), Vector(2.), None)
            query.prime((self.box,))
            self.assertTrue(query.inside(self.box))
            point.assert_called_once()
            call.assert_not_called()

    def test_native_rejection_does_not_turn_into_negative_witness(self):
        query = sensor._MotionSkinWitnesses1513(Vector(0.), Vector(-2.), Vector(2.), None)
        with mock.patch.object(native, 'motion_witnesses', return_value=None):
            query.prime((self.box,))
        self.assertTrue(query.inside(self.box))
        self.assertIsNotNone(query.interval(self.box))

    def test_motion_witness_rejection_logs_opcode_two(self):
        with mock.patch.dict(diagnostics.__dict__, {'_counts': {}, '_reported': set(), '_reports_by_method': {}}), \
                mock.patch.object(diagnostics, '_write_record') as write:
            diagnostics.record('destr_box_geometry', (2, ((), None, None, None, .05, None)))
            self.assertEqual({'family': 'destr_box_geometry', 'opcode': 2}, write.call_args.args[0]['native_profile'])
