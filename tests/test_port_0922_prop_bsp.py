import sys
import math
import types
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor

class Vector:
    def __init__(self, x=0., y=0., z=0.): self.x,self.y,self.z=x,y,z
    def __getitem__(self,i): return (self.x,self.y,self.z)[i]
    def __add__(self,other): return Vector(*(self[i]+other[i] for i in range(3)))
    def __sub__(self,other): return Vector(*(self[i]-other[i] for i in range(3)))
    def scale(self,v): return Vector(*(self[i]*v for i in range(3)))
    @property
    def length(self): return math.sqrt(sum(self[i]**2 for i in range(3)))
class Matrix:
    def __init__(self, other=None): self.translation=Vector(0.,0.,5.)
    def invert(self): self.translation=self.translation.scale(-1.)
    def applyPoint(self, point): return point+self.translation

class PropBspTests(unittest.TestCase):
    def setUp(self):
        sensor.__dict__.pop('g_offh_shot_collision_models', None)
        self.model=types.SimpleNamespace(setModelName=mock.Mock(return_value=True),
            collideSegment=mock.Mock(return_value=[]))
        self.bw=types.SimpleNamespace(WGBspCollisionModel=mock.Mock(return_value=self.model),
            wg_getDestructibleMatrix=lambda *args: Matrix(),
            wg_getChunkMatrix=lambda *args: types.SimpleNamespace(translation=Vector(0.,0.,10.)))
        self.patcher=mock.patch.dict(sys.modules, {'BigWorld':self.bw,
            'Math':types.SimpleNamespace(Matrix=Matrix)})
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.addCleanup(sensor.__dict__.pop, 'g_offh_shot_collision_models', None)
        self.bounds=mock.patch.object(sensor,'_point_in_world_box',return_value=True)
        self.bounds.start();self.addCleanup(self.bounds.stop)
    def query(self):
        return sensor._catalog_precise_shot_distance_1513(1,(22,7),
            {'filename':'prop.model'},None,Vector(0.,0.,20.),Vector(0.,0.,40.))
    def test_bbox_candidate_with_a_bsp_hole_does_not_block(self):
        self.assertIsNone(self.query())
        args=self.model.collideSegment.call_args.args
        self.assertEqual(5.,args[0].z);self.assertEqual(25.,args[1].z)
    def test_native_none_miss_is_an_open_gap(self):
        self.model.collideSegment.return_value=None
        self.assertIsNone(self.query())
    def test_triangle_distance_owns_contact_and_model_is_cached(self):
        self.model.collideSegment.return_value=[(7.,Vector(),1.,73)]
        self.assertEqual(7.,self.query());self.assertEqual(7.,self.query())
        self.bw.WGBspCollisionModel.assert_called_once()
        self.model.setModelName.assert_called_once_with('prop.model')
    def test_unavailable_model_never_falls_back_to_solid_bbox(self):
        self.model.setModelName.return_value=False
        with self.assertRaisesRegex(RuntimeError,'collision model unavailable'):self.query()
        self.model.collideSegment.assert_not_called()
        self.assertEqual({},sensor.g_offh_shot_collision_models)
    def test_other_building_module_surface_does_not_inherit_this_owner(self):
        self.model.collideSegment.return_value=[(7.,Vector(),1.,73)]
        with mock.patch.object(sensor,'_point_in_world_box',return_value=False):
            self.assertIsNone(self.query())
