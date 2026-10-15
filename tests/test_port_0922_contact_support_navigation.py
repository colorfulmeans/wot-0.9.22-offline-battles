"""Retained physical-support corrections and independent crush receipts."""
import io
import sys
import types
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bots
from test_port_0922_vehicle_physics import (
    vehicle_physics as vp, VehiclePhysicsSuspensionTrialTests as PhysicsFixture)
from test_port_0922_navigation_collision_bake import (
    baker, compiled, VFS, WALL)
from gui.mods.offline_lan_0922 import world_collision, destructibles_sensor


class ContactSupportTests(unittest.TestCase):
    def test_patch_height_preserves_actual_inboard_application_point(self):
        params = vp.derive_suspension_params(PhysicsFixture._descriptor())
        spring = dict(params['springs'][0], x=-0.04, z=0.0)
        params = dict(params, springs=(spring,), footprint_half_width=0.15)
        # Nominal carrier is beyond the lip. Only an inboard patch hits deck.
        height = vp.suspension_footprint_support(
            params, (-0.04, 0.0), None, (-0.04, 0.0, 0.0), 0.0,
            lambda x,z,low,high: 0.0 if x >= 0.0 else None,
            spring=spring)
        self.assertIsNotNone(height)
        height, unused = vp.retained_ground_contact(
            (-0.04,0.0), height, None, 0.2)
        adjusted = vp.suspension_contact_params(params, (height,))
        self.assertGreaterEqual(adjusted['springs'][0]['x'], 0.0)
        self.assertEqual(-0.04, params['springs'][0]['x'])
        self.assertIs(adjusted, vp.suspension_contact_params(adjusted, (height,)))

    def test_inboard_patch_cannot_invent_outboard_stable_polygon(self):
        params = vp.derive_suspension_params(PhysicsFixture._descriptor())
        source = params['springs'][0]
        params = dict(params, springs=tuple(dict(source,x=x,z=z)
            for x,z in ((-.05,-1.),(-.05,1.),(.15,-1.),(.15,1.))))
        ground = (vp.FootprintSupport(0.,.1,0.),
                  vp.FootprintSupport(0.,.1,0.),0.,0.)
        keys = tuple(('spring',i) for i in range(4))
        state = dict(pitch=0.,roll=0.)
        self.assertTrue(vp._suspension_has_stable_support(params,state,keys))
        adjusted = vp.suspension_contact_params(params,ground)
        self.assertFalse(vp._suspension_has_stable_support(adjusted,state,keys))

    def scene(self, terrain):
        runtime = bots._load().BotRuntime(1,
            physics_ground_probe=lambda x,z,h: terrain(x,z),
            wreck_ground_probe=lambda *args,**kwargs: None)
        state = dict(id=11,x=0.,y=0.,z=0.,yaw=0.,pitch=0.,roll=0.,
            alive=True,grounded_once=True,_contact_dynamics=True,
            _contact_edge_check=True,
            collision_shape=(1.5,3.5,-.5,2.))
        runtime.states={11:state}
        runtime._descriptors[11]=PhysicsFixture._descriptor()
        return runtime,state

    def test_flat_contact_keeps_cheap_support_but_shoved_edge_activates(self):
        runtime,state=self.scene(lambda x,z:0. if x <= .5 else None)
        with mock.patch('sys.stdout',new=io.StringIO()):
            self.assertIsNotNone(runtime._suspension_params_for(11))
        self.assertTrue(state['_edge_support_active'])
        self.assertTrue(runtime._contact_edge_support_needed(state))
        other,unused=self.scene(lambda x,z:0.)
        self.assertIsNone(other._suspension_params_for(11))

    def test_old_flat_contact_does_not_repeat_edge_queries_without_a_new_shove(self):
        runtime,state=self.scene(lambda x,z:0.)
        with mock.patch.object(runtime,'_ground_probe_at',return_value=0.) as probe:
            self.assertIsNone(runtime._suspension_params_for(11))
            self.assertEqual(4,probe.call_count)
            for unused in range(20):
                self.assertIsNone(runtime._suspension_params_for(11))
            self.assertEqual(4,probe.call_count)
            state['_contact_edge_check']=True
            self.assertIsNone(runtime._suspension_params_for(11))
            self.assertEqual(8,probe.call_count)

    def test_navigation_alone_does_not_enable_edge_dynamics(self):
        runtime,state=self.scene(lambda x,z:None)
        state.pop('_contact_dynamics')
        self.assertIsNone(runtime._suspension_params_for(11))
        self.assertNotIn('_edge_support_active',state)

    def test_shoved_hull_tips_off_remaining_track_and_lands_below_deck(self):
        self.module = bots._load()
        runtime,state,unused=bots.BotRuntimeTests._suspension_case(
            self,lambda x,z: 0.0 if x <= -.3 else -20.0)
        state.update(alive=True,collision_shape=(1.5,3.5,-.5,2.),
            _contact_dynamics=True,_contact_edge_check=True,speed=0.,movement_dir=0)
        runtime.states={11:state}
        runtime._contact_motion_bodies=lambda unused:[]
        runtime.motion_resolver=mock.Mock(return_value='clear')
        runtime._apply_bot_landing_impact=mock.Mock()
        tilted=False
        with mock.patch('sys.stdout',new=io.StringIO()):
            for tick in range(200):
                runtime._contact_now=tick*.05
                runtime._update_vertical_motion(state,.05,
                    (state['x'],state['y'],state['z']),state['yaw'])
                tilted=tilted or abs(state.get('roll',0.))>.2
        self.assertTrue(state['_edge_support_active'])
        self.assertTrue(tilted)
        self.assertLess(state['y'],-15.)
        self.assertFalse(runtime._suspension_param_failures)






class MultiModuleCrushTests(unittest.TestCase):
    def test_missing_diagnostic_descriptor_cannot_quarantine_collision_owner(self):
        area=types.SimpleNamespace(g_cache=types.SimpleNamespace(
            getDescByFilename=mock.Mock(side_effect=ValueError('diagnostic cache miss'))))
        with mock.patch.dict(sys.modules,{'AreaDestructibles':area,
                'DestructiblesCache':types.SimpleNamespace()}), \
                mock.patch.object(destructibles_sensor,'_isolate_destructible_1513') as isolate, \
                mock.patch('sys.stdout',new=io.StringIO()):
            destructibles_sensor._crush_gate_diagnostic_1513(
                (1,2,73,'house.model','structure',1.),1.,12.,object(),False,True,True,1.)
        isolate.assert_not_called()

    def test_later_lane_keeps_independently_proven_kinetic_module(self):
        for classified, expected in (('kinetic','kinetic'),(False,False),(True,True)):
            with self.subTest(classified=classified), mock.patch.object(
                    world_collision,'_catalog_soft_static_path',return_value=classified) as scan, \
                    mock.patch.object(world_collision,'_try_destroy_solid_hit') as destroy:
                result=world_collision._destroy_and_recast(
                    1,object(),object(),object(),0.,1.,object(),[True],True,12.)
                self.assertEqual(expected,result)
                self.assertTrue(scan.call_args.kwargs['allow_kinetic_first'])
                self.assertEqual(12.,scan.call_args.kwargs['kinetic_speed'])
                destroy.assert_not_called()
