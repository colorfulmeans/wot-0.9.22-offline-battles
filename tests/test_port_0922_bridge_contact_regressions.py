"""Report 175138: ledge projection, slope handback and falling roof admission."""
import contextlib
import io
import math
import types
import unittest
from unittest import mock
import test_port_0922_contact_support_navigation as fixtures
import test_port_0922_bot_runtime as bots
import test_port_0922_battle_runtime as battle_fixture
from gui.mods.offline_lan_0922 import vehicle_physics as vp


class LedgeRecoveryTests(unittest.TestCase):
    def test_recorded_bot9_penetration_is_not_a_new_climb(self):
        before=dict(height=.5250618174309358, pitch=-1.314603274514827,
                    roll=-1.0042512591213686)
        after=dict(height=1.5643090044391021, pitch=-1.7041184100008924,
                   roll=-.8777093039148895)
        params=dict(springs=tuple(dict(x=1.4403699517250061,y=0.,z=z)
            for z in (-.8839618563652039,0.,.8839618563652039,1.7679237127304077)))
        plane=dict(center_x=18.7163,center_z=86.5085,center_y=1.2159,
                   gradient_x=-.0413,gradient_z=-.0608)
        pos=(18.7163,before['height'],86.5085)
        ground=[1.158897876739502]*4
        self.assertTrue(vp.suspension_contact_recovery(
            params,before,after,ground,[],plane,pos,pos))
        # A translated wall climb, a new overhead storey and missing old
        # support must all retain the existing obstacle veto.
        for old_plane,origin,heights in ((plane,(pos[0]-.5,pos[1],pos[2]),ground),
                (dict(plane,center_y=-15.),pos,ground),(None,pos,ground)):
            self.assertFalse(vp.suspension_contact_recovery(
                params,before,after,heights,[],old_plane,pos,origin))

    def test_recorded_projection_passes_the_bot_commit_guard(self):
        self.module=bots._load()
        runtime,state,unused=bots.BotRuntimeTests._suspension_case(self,lambda x,z:1.159)
        state.update(x=18.7163,y=.5250618174,z=86.5085,yaw=1.04118,
            terrain_pitch=-1.3146032745,pitch=-1.3146032745,roll=-1.0042512591,
            speed=0.,movement_dir=0.,_edge_support_active=True)
        plane=dict(center_x=state['x'],center_z=state['z'],center_y=1.2159,
                   gradient_x=-.0413,gradient_z=-.0608)
        state['_suspension_ground_plane']=plane
        runtime.states={11:state}
        params=vp.derive_suspension_params(runtime._descriptors[11])
        params=dict(params,springs=tuple(dict(params['springs'][i],
            x=1.4403699517,y=0.,z=z) for i,z in enumerate((-.8839618564,0.,.8839618564,1.7679237127))))
        solved=dict(height=1.5643090044,vertical_velocity=-.9235671918,
            pitch=-1.70411841,pitch_velocity=-.392164548,
            roll=-.8777093039,roll_velocity=-.0128448909,
            contact_count=1,rigid_contact_count=0,airborne=False,
            left_flying=True,right_flying=False,impact_speed=None)
        pos=(state['x'],state['y'],state['z'])
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(vp,'suspension_pose_params',side_effect=lambda p,*args:p), \
                mock.patch.object(runtime,'_suspension_ground_samples',return_value=(1.159,)*4), \
                mock.patch.object(runtime,'_suspension_pseudo_ground_samples',return_value=()), \
                mock.patch.object(runtime,'_suspension_world_ground_plane',return_value=plane), \
                mock.patch.object(vp,'damper_suspension_step',return_value=solved):
            self.assertFalse(runtime._update_suspension_vertical_motion(state,.15,params,pos))
        self.assertAlmostEqual(solved['height'],state['y'])
        self.assertLess(state['vertical_speed'],0.)

    def test_tipped_edge_does_not_restore_the_same_pose_forever(self):
        self.module=bots._load()
        runtime,state,unused=bots.BotRuntimeTests._suspension_case(
            self,lambda x,z:1.159 if x<-.3 else -15.)
        state.update(x=.8,y=.525,terrain_pitch=-1.3146,pitch=-1.3146,
                     roll=-1.0043,yaw=1.0412,speed=0.,movement_dir=0,
                     _edge_support_active=True,alive=True,
                     collision_shape=(1.5,3.5,-.5,2.))
        runtime.states={11:state}
        runtime._apply_bot_landing_impact=mock.Mock()
        positions=[]
        with contextlib.redirect_stdout(io.StringIO()):
            for tick in range(240):
                runtime._contact_now=tick*.05
                old=(state['x'],state['y'],state['z'])
                runtime._update_vertical_motion(state,.05,old,state['yaw'])
                positions.append(state['y'])
        self.assertGreater(max(positions)-min(positions),5.)
        self.assertLess(state['y'],-10.)


class SupportHandbackTests(unittest.TestCase):
    scene=fixtures.ContactSupportTests.scene

    def test_steep_supported_plane_is_not_flattened_after_handback(self):
        for grade in (.75,1.,1.2):
            runtime,state=self.scene(lambda x,z:grade*z)
            state.update(terrain_pitch=-math.atan(grade),pitch=-math.atan(grade),
                _edge_support_active=True,airborne=False,y=.15,speed=0.)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(runtime._release_detailed_support(state))
                for frame in range(1,30):
                    state['z']+=.03;state['y']=.15+grade*state['z']
                    state.pop('pose_sample',None)
                    runtime._contact_now=frame*.15
                    runtime._update_slope_pose(state)
                    self.assertFalse(runtime._contact_edge_support_needed(state))
                    self.assertAlmostEqual(-math.atan(grade),state['terrain_pitch'])

    def test_mode_change_cannot_reuse_projected_basic_point_rows(self):
        runtime,state=self.scene(lambda x,z:0.)
        runtime._contact_now=1.
        with contextlib.redirect_stdout(io.StringIO()):
            basic=runtime._basic_support_status(state)
            state['_edge_support_active']=True
            detailed=runtime._basic_support_status(state)
        self.assertIsNot(basic,detailed)


class SlopeRotationTests(unittest.TestCase):
    def test_native_rotation_slices_preserve_the_world_support_plane(self):
        runtime=battle_fixture._runtime();battle=battle_fixture.BattleRuntime(runtime)
        battle._avatar=runtime.bigworld.avatar
        battle._destructibles=types.SimpleNamespace(_vehicle_body_bbox=lambda unused:
            ((-1.7,-.4,-3.5),(1.7,1.8,3.2),None))
        pitch,roll=.6,-.08
        calls=[]
        def world(*args,**kw):
            calls.append((args[4],kw['pitch'],kw['roll']))
            wanted=battle_fixture.battle_runtime_module.ground_pose_for_yaw(pitch,roll,0.,args[4])
            return 'clear' if max(abs(kw['pitch']-wanted[0]),abs(kw['roll']-wanted[1]))<1.e-8 else 'hard'
        with mock.patch.object(battle_fixture.battle_runtime_module.world_collision,
                               'check_horizontal_collision',side_effect=world):
            self.assertTrue(battle._native_world_rotation_is_clear((0.,0.,0.),0.,.16,
                battle_fixture._Descriptor(),pitch=pitch,roll=roll,
                include_static=True,follow_ground=True))
        self.assertGreaterEqual(len(calls),4)


class RoofApproachTests(unittest.TestCase):
    def scene(self):
        runtime=battle_fixture._runtime();battle=battle_fixture.BattleRuntime(runtime)
        battle._local_airborne=True;battle._local_vertical_speed=-17.
        battle._local_pitch=battle._local_roll=0.
        battle.client=types.SimpleNamespace(player_id=1)
        battle._collision_shape=lambda unused:(1.5,3.,0.,2.)
        target=types.SimpleNamespace(typeDescriptor=object())
        lower=dict(x=0.,y=-3.,z=0.,yaw=0.,collision_shape=(1.5,3.,0.,2.))
        def context(actor):
            old=getattr(battle,'_stack_context',None)
            battle._stack_context=dict(actor=actor,hits=[],candidates=[(('bot',12),lower,target)])
            return old
        battle._stack_support_context=context
        return battle,target

    def test_native_roof_below_falling_foot_delays_planar_response_only(self):
        battle,target=self.scene()
        def hit(start,end,ground):
            battle._stack_context['hits'].append((('bot',12),{},(start.x,-1.,start.z)))
        battle._stack_ground_hit=hit
        peers=[dict(kind='bot',network_id=12)]
        self.assertEqual({('bot',12)},battle._falling_roof_approaches(target,(0.,0.,0.),0.,peers))
        self.assertIsNone(battle._stack_context)
        self.assertFalse(getattr(battle,'_local_stack_carrier',None))
        battle._local_airborne=False
        self.assertEqual(set(),battle._falling_roof_approaches(target,(0.,0.,0.),0.,peers))

    def test_roof_miss_or_side_contact_never_disables_planar_response(self):
        for height in (None,1.):
            battle,target=self.scene()
            def hit(start,end,ground):
                if height is not None:
                    battle._stack_context['hits'].append((('bot',12),{},(start.x,height,start.z)))
            battle._stack_ground_hit=hit
            self.assertEqual(set(),battle._falling_roof_approaches(target,(0.,0.,0.),0.,
                [dict(kind='bot',network_id=12)]))
