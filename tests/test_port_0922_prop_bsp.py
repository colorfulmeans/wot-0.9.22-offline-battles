"""Scene contacts must not be manufactured from authored original models."""
import math
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor


class Vector:
    def __init__(self, x=0., y=0., z=0.): self.x, self.y, self.z = x, y, z
    def __getitem__(self, i): return (self.x, self.y, self.z)[i]
    def __add__(self, other): return Vector(*(self[i] + other[i] for i in range(3)))
    def __sub__(self, other): return Vector(*(self[i] - other[i] for i in range(3)))
    def scale(self, v): return Vector(*(self[i] * v for i in range(3)))
    @property
    def length(self): return math.sqrt(sum(self[i] ** 2 for i in range(3)))


class PropSceneTests(unittest.TestCase):
    def setUp(self):
        self.bw = types.SimpleNamespace(
            wg_getMatInfoNearPoint=mock.Mock(return_value=(False, None, None, 0, '', 0, 0)),
            WGBspCollisionModel=mock.Mock(side_effect=AssertionError('intact model must not be loaded')))
        patcher = mock.patch.dict(sys.modules, {'BigWorld': self.bw})
        patcher.start(); self.addCleanup(patcher.stop)
        bounds = mock.patch.object(sensor, '_point_in_world_box', return_value=True)
        bounds.start(); self.addCleanup(bounds.stop)
        self.instance = {'filename': 'prop.model', 'kind': 'fragile'}
        self.evidence = {}

    def hit(self, point=None, item=7, chunk=22, material=73):
        self.bw.wg_getMatInfoNearPoint.return_value = (
            True, point or Vector(0., 0., 27.), Vector(0., 1., 0.),
            material, 'prop.model', item, chunk)

    def query(self):
        return sensor._catalog_precise_shot_distance_1513(
            1, (22, 7), self.instance, (None, None, 73),
            Vector(0., 0., 20.), Vector(0., 0., 40.), self.evidence)

    def test_absent_live_surface_does_not_resurrect_authored_model(self):
        self.assertIsNone(self.query())
        self.bw.WGBspCollisionModel.assert_not_called()

    def test_live_contact_owns_world_distance_without_model_transform(self):
        self.hit()
        self.assertEqual(7., self.query())
        args = self.bw.wg_getMatInfoNearPoint.call_args.args
        self.assertIs(args[1], args[3])
        self.assertFalse(args[4](73, 0, 7, 22))
        self.assertTrue(self.evidence['contact_proved'])
        self.assertEqual([22, 7], self.evidence['native_identity'])

    def test_neighbouring_prop_or_wall_never_inherits_candidate_wire(self):
        self.hit(item=8)
        self.assertIsNone(self.query())
        self.assertEqual([22, 8], self.evidence['native_identity'])

    def test_point_probe_must_prove_contact_on_the_actual_segment(self):
        for point in (Vector(0.01, 0., 27.), Vector(0., 0., 19.), Vector(0., 0., 41.)):
            self.hit(point)
            self.assertIsNone(self.query())

    def test_other_structure_material_does_not_inherit_module_owner(self):
        self.instance['kind'] = 'structure'
        self.hit(material=74)
        self.assertIsNone(self.query())

    def test_live_point_outside_candidate_envelope_is_not_admitted(self):
        self.hit()
        with mock.patch.object(sensor, '_point_in_world_box', return_value=False):
            self.assertIsNone(self.query())

    def test_one_chord_shares_scene_probe_across_module_candidates(self):
        self.hit()
        cache = {}
        for unused in range(3):
            self.assertEqual(7., sensor._catalog_precise_shot_distance_1513(
                1, (22, 7), self.instance, (None, None, 73),
                Vector(0., 0., 20.), Vector(0., 0., 40.), {}, cache))
        self.bw.wg_getMatInfoNearPoint.assert_called_once()

    def test_pending_identity_keeps_only_a_proved_scene_surface(self):
        box = (None, None, 73)
        baked = {'kind': 'fragile', 'filename': 'prop.model', 'boxes': [box],
                 'broad_phase_margin': 0.}
        catalog = {'baked_instances': {(22, 7): baked},
                   'baked_shot_bins': {(0, 0): {(22, 7)}}}
        authority = types.SimpleNamespace(is_destroyed=lambda *args: False)
        with mock.patch.object(sensor, '_destructible_catalog', catalog), \
                mock.patch.dict(sensor.__dict__, {'g_offh_destr_instances': {},
                    'g_offh_destr_contact_bins': {}}), \
                mock.patch.object(sensor, '_get_destr_authority', return_value=authority), \
                mock.patch.object(sensor, '_destructible_isolated_1513', return_value=False), \
                mock.patch.object(sensor, '_baked_bin_keys_for_bounds_1513', return_value=[(0, 0)]), \
                mock.patch.object(sensor, '_stream_baked_shot_instance_1513', return_value=None), \
                mock.patch.object(sensor, '_segment_world_box_interval', return_value=(0.25, 0.75)):
            self.assertIsNone(sensor._catalog_shot_intersection(
                1, Vector(0., 0., 20.), Vector(0., 0., 40.)))
            self.hit()
            result = sensor._catalog_shot_intersection(
                1, Vector(0., 0., 20.), Vector(0., 0., 40.))
            self.assertEqual(7., result['distance'])
            self.assertTrue(result['ambiguous'])
            self.assertIsNone(result['candidate'])

