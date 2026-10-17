"""Exact support query reuse: geometry parity, lifetime, and physical time."""
import types
import unittest
from unittest import mock
import test_port_0922_battle_runtime as engine
from gui.mods.offline_lan_0922.support_queries import SupportQueries
from gui.mods.offline_lan_0922.entities import remote_vehicle

class SupportReuseTests(unittest.TestCase):
    def test_exact_cache_keeps_none_and_does_not_merge_different_rays(self):
        batch=SupportQueries(lambda:1.)
        query=mock.Mock(return_value=None)
        self.assertIsNone(batch.get('terrain',(0.,1.),query))
        self.assertIsNone(batch.get('terrain',(0.,1.),query))
        batch.get('terrain',(0.,1.0000000001),query)
        self.assertEqual(2,query.call_count)
        self.assertEqual(1,batch.calls['terrain_cache_hit'])
        SupportQueries(lambda:1.).get('terrain',(0.,1.),query)
        self.assertEqual(3,query.call_count)

    def test_failed_query_is_not_cached_and_time_is_recorded(self):
        time=[0.]
        batch=SupportQueries(lambda:time[0])
        def failing():
            time[0]+=.002
            raise RuntimeError('unavailable')
        for unused in range(2):
            with self.assertRaises(RuntimeError):batch.get('terrain',1,failing)
        self.assertEqual(2,batch.calls['terrain'])
        self.assertAlmostEqual(4.,batch.milliseconds['terrain'])

    def test_prepared_collision_preserves_rays_hits_normals_and_components(self):
        math=types.SimpleNamespace(Matrix=engine._Matrix,Vector3=engine._Vector)
        descriptor=engine._Descriptor()
        for component in (descriptor.chassis,descriptor.hull,descriptor.turret,descriptor.gun):
            component.hitTester=types.SimpleNamespace(localHitTest=mock.Mock(return_value=[
                (1.,engine._Vector(0.,1.,0.),.5,21)]))
            component.materials={21:types.SimpleNamespace(armor=20.)}
        vehicle=engine._Vehicle(11,descriptor,engine._Vector(),(0.,0.,0.),{'health':500})
        matrix,chassis=engine._Matrix(),engine._Matrix()
        matrix.translation=engine._Vector(2.,3.,4.)
        chassis.translation=engine._Vector(2.,2.8,4.)
        prepared=remote_vehicle.prepare_vehicle_collision_at_matrix(vehicle,matrix,math,chassis)
        for offset in (0.,1.,-1.):
            start,end=engine._Vector(offset,8.,0.),engine._Vector(offset,-5.,0.)
            args=(vehicle,matrix,start,end,math)
            plain=remote_vehicle._collide_vehicle_evidence_at_matrix(*args,chassis_matrix=chassis,capture_query=False)
            with mock.patch.object(remote_vehicle,'_pose_components',side_effect=AssertionError('must reuse transforms')):
                reused=remote_vehicle._collide_vehicle_evidence_at_matrix(*args,chassis_matrix=chassis,capture_query=False,prepared=prepared)
            self.assertEqual([h.collision for h in plain],[h.collision for h in reused])
            self.assertEqual([h.localPoint for h in plain],[h.localPoint for h in reused])
            self.assertEqual([tuple(h.worldNormal) for h in plain],[tuple(h.worldNormal) for h in reused])
            for component in (descriptor.chassis,descriptor.hull,descriptor.turret,descriptor.gun):
                calls=component.hitTester.localHitTest.call_args_list
                self.assertEqual(tuple(calls[-1].args[0]),tuple(calls[-2].args[0]))
                self.assertEqual(tuple(calls[-1].args[1]),tuple(calls[-2].args[1]))

    def test_twenty_five_distinct_rays_reuse_inverses_without_skipping_bsp(self):
        inversions=[0]
        class Matrix(engine._Matrix):
            def invert(self):
                inversions[0]+=1
                return super().invert()
        math=types.SimpleNamespace(Matrix=Matrix,Vector3=engine._Vector)
        descriptor=engine._Descriptor()
        tester=mock.Mock(return_value=[])
        descriptor.chassis.hitTester=types.SimpleNamespace(localHitTest=tester)
        for part in (descriptor.hull,descriptor.turret,descriptor.gun):part.hitTester=None
        vehicle=engine._Vehicle(11,descriptor,engine._Vector(),(0.,0.,0.),{'health':500})
        matrix=Matrix()
        for i in range(25):
            remote_vehicle._collide_vehicle_evidence_at_matrix(vehicle,matrix,engine._Vector(i*.01,1.,0.),engine._Vector(i*.01,-1.,0.),math,capture_query=False)
        original=inversions[0]
        self.assertEqual(25,tester.call_count)
        tester.reset_mock();inversions[0]=0
        prepared=remote_vehicle.prepare_vehicle_collision_at_matrix(vehicle,matrix,math)
        for i in range(25):
            remote_vehicle._collide_vehicle_evidence_at_matrix(vehicle,matrix,engine._Vector(i*.01,1.,0.),engine._Vector(i*.01,-1.,0.),math,capture_query=False,prepared=prepared)
        self.assertEqual(25,tester.call_count)
        self.assertEqual(50,original)
        self.assertEqual(2,inversions[0])

    def test_runtime_memoizes_terrain_only_inside_one_support_context(self):
        battle=engine.BattleRuntime(engine._runtime())
        battle._collide_static_down=mock.Mock(return_value=None)
        battle._stack_ground_hit=lambda start,end,ground:ground
        battle._stack_candidates=lambda actor:iter(())
        actor=dict(id=1,kind='player',x=0.,y=0.,z=0.)
        start,end=engine._Vector(0.,1.,0.),engine._Vector(0.,-1.,0.)
        previous=battle._stack_support_context(actor)
        for unused in range(10):battle._collide_down(start,end,None)
        self.assertEqual(1,battle._collide_static_down.call_count)
        batch=battle._stack_context['queries']
        self.assertEqual(9,batch.calls['terrain_cache_hit'])
        battle._finish_stack_support_context(previous)
        previous=battle._stack_support_context(actor)
        battle._collide_down(start,end,None)
        self.assertEqual(2,battle._collide_static_down.call_count)
        battle._finish_stack_support_context(previous)

    def test_roof_hits_reuse_prepared_pose_and_exact_ray_without_losing_carrier(self):
        battle=engine.BattleRuntime(engine._runtime())
        state=dict(id=12,x=0.,y=0.,z=0.,yaw=0.,collision_shape=(1.5,3.,0.,2.))
        entity=types.SimpleNamespace(typeDescriptor=engine._Descriptor())
        actor=dict(id=1,kind='player',x=0.,y=2.,z=0.,yaw=0.,pitch=0.,roll=0.)
        battle._stack_candidates=lambda unused:iter([(('bot',12),state,entity)])
        previous=battle._stack_support_context(actor)
        evidence=types.SimpleNamespace(collision=types.SimpleNamespace(dist=.1,compName='vehicleHull'),worldNormal=engine._Vector(0.,1.,0.))
        with mock.patch.object(engine.battle_runtime_module,'_collide_vehicle_evidence_at_matrix',return_value=[evidence]) as query, mock.patch.object(battle,'_prepare_stack_target',wraps=battle._prepare_stack_target) as prepare:
            for unused in range(10):
                actor.pop('_stack_carrier',None)
                hit=battle._stack_ground_hit(engine._Vector(0.,2.1,0.),engine._Vector(0.,1.9,0.),None)
                self.assertIsNotNone(hit)
                self.assertEqual(['bot',12],actor['_stack_carrier'])
            self.assertEqual(1,query.call_count)
            self.assertEqual(1,prepare.call_count)
            self.assertEqual(10,len(battle._stack_context['hits']))
            # Changing a real ray endpoint and a pose must not reuse old evidence.
            state['pitch']=.1
            battle._stack_ground_hit(engine._Vector(0.,2.1,0.),engine._Vector(0.,1.8,0.),None)
            self.assertEqual(2,query.call_count)
            self.assertEqual(2,prepare.call_count)
        battle._finish_stack_support_context(previous)

    def test_profile_emits_split_costs_counts_and_simulated_time(self):
        battle=engine.BattleRuntime(engine._runtime())
        battle.client=types.SimpleNamespace(round_id=7,authority_epoch=1)
        now=[0.]
        battle._clock=lambda:now[0]
        battle._stack_candidates=lambda unused:iter(())
        actor=dict(id=1,kind='player',x=0.,y=0.,z=0.)
        with mock.patch.object(engine.battle_runtime_module.native_input_diagnostics,'write_json_record') as write:
            for dt in (.1,.2):
                previous=battle._stack_support_context(actor)
                battle._stack_context['physics_dt']=dt
                batch=battle._stack_context['queries']
                batch.call('terrain',lambda:None)
                now[0]+=1.1
                battle._finish_stack_support_context(previous)
            row=write.call_args.args[1]
            self.assertEqual('SUPPORT QUERY PERF',write.call_args.args[0])
            self.assertEqual(7,row['round'])
            self.assertEqual(.3,round(row['physics_dt_s'],1))
            self.assertEqual(2,row['calls']['terrain'])
            self.assertIn('terrain',row['wall_ms'])
            self.assertIn('context_total',row['wall_ms'])
            self.assertIsNone(battle._stack_context)

    def test_elapsed_physics_time_is_fully_consumed(self):
        battle=engine.BattleRuntime(engine._runtime())
        battle._sender=mock.Mock();battle._server=mock.Mock()
        steps=[]
        battle._drive_local_step=lambda dt:steps.append(dt) or False
        battle._local_siege_braking=None
        battle._pending_landing_impacts=[]
        battle._local_damage_report=None;battle._drown_level=0;battle._overturn_level=0
        battle._drive_local(1.37)
        self.assertAlmostEqual(1.37,sum(steps))
        self.assertEqual(14,len(steps))

if __name__=='__main__':unittest.main()
