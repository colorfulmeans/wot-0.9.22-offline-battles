import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import test_port_0922_destructibles as prop
import test_port_0922_battle_runtime as motion


class SpawnPropClearanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=prop.DestructiblesCompatibilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_pilsen_spawn_slab_is_cleared_at_rest_but_neighbours_and_structures_remain(self):
        sensor=prop.destructibles_sensor
        sensor.xrange=range
        source=json.loads((Path(__file__).resolve().parents[1]/'destructibles/114_czech.json').read_text())
        filename='content/Environment/env_114_18_ConcreteSlab/normal/lod0/env_114_18_ConcreteSlab_02.model'
        resource=source['resources'][filename]
        wall='content/test/solid_building.model'
        sensor.set_catalog(prop._catalog({filename:resource,wall:{'kind':'structure',
                           'boxes':[[-1,-1,-1,1,1,1,73]]}}))
        instances={};bins={}
        for item,name,point in [(18,filename,(-3.096,13.177,316.845)),
                                (19,filename,(9.301,13.021,312.485)),
                                (20,wall,(-2.0,13.4,318.0))]:
            record=sensor._destructible_catalog['resources'][name.lower()]
            boxes=sensor._world_catalog_boxes(record,prop._ItemMatrix(prop._Vector(point)),
                                              prop._Vector(),types.SimpleNamespace(Vector3=prop._Vector))
            instance=dict(filename=name.lower(),kind=record['kind'],boxes=boxes,item_scale=1.0)
            instances[(32386,item)]=instance
            sensor._index_catalog_instance_1513(bins,(32386,item),instance)
        sensor.g_offh_destr_instances=instances;sensor.g_offh_destr_contact_bins=bins
        area=types.ModuleType('AreaDestructibles')
        area.g_destructiblesManager=object();area.DESTR_TYPE_FRAGILE=3
        area.DESTR_TYPE_STRUCTURE=4;area.DESTR_TYPE_FALLING_ATOM=2
        area.DESTRUCTIBLE_HIDING_DELAY=0.2
        area.g_cache=types.SimpleNamespace(unitVehicleMass=10000.0,
            getDescByFilename=lambda name:{'type':3,'health':5,'kineticDamageCorrection':1.0})
        cache=types.ModuleType('DestructiblesCache')
        cache.scaledDestructibleHealth=lambda scale,health:scale*health
        math_module=types.ModuleType('Math');math_module.Vector3=prop._Vector
        descriptor=prop._Strict1513Component(physics={'weight':40000.0},
            hull=prop._Strict1513Component(hitTester=types.SimpleNamespace(
                bbox=((-1.6,0,-3.6),(1.6,1,3.6),None))))
        calls=[];destroyed=set()
        def destroy(space,chunk,item,point,shot):
            calls.append((chunk,item));destroyed.add((chunk,item));return True
        authority=types.SimpleNamespace(is_destroyed=lambda chunk,item,*args:(chunk,item) in destroyed,
                                         destroy_fragile=destroy)
        sensor.set_event_sink(lambda event:True)
        with mock.patch.dict(sys.modules,{'Math':math_module,'AreaDestructibles':area,
                                         'DestructiblesCache':cache}), \
             mock.patch.object(sensor,'_get_destr_authority',return_value=authority), \
             mock.patch.object(sensor,'_stream_baked_motion_instances_1513',return_value=()):
            position=prop._Vector(-2,13.729,318)
            # Actual zero-speed kinetic energy cannot crush the slab.
            before=sensor._catalog_motion_blocked(1,position,-3.13,0,descriptor,1,
                return_detail=True,spawn_overlap=True)
            self.assertEqual('hard',before['status']);self.assertEqual([],calls)
            result=sensor._catalog_motion_blocked(1,position,-3.13,0,descriptor,2,
                return_detail=True,spawn_overlap=True,kinetic_speed=13.889,
                kinetic_commit=True,travel_reach=0)
            self.assertTrue(result['accepted_now'])
            self.assertEqual([(32386,18)],calls)
            self.assertEqual({(32386,18,None)},set(result['token']))
            with self.assertRaises(ValueError):
                sensor._catalog_motion_blocked(1,position,0,1,descriptor,3,spawn_overlap=True)

    def test_worker_placement_clearance_retries_streaming_and_never_runs_after_departure(self):
        battle=motion.BattleRuntime.__new__(motion.BattleRuntime)
        battle._worker_mode=True;battle._generation=7;battle._battle_live=False
        battle._avatar=types.SimpleNamespace(spaceID=1);battle._vector=lambda value:value
        battle._formation_pose=lambda team,slot:((-2,13.4,318),-3.13)
        resolver=mock.Mock(side_effect=[{'status':'clear'},
            {'status':'crushed','accepted_now':True,'token':[(32386,18,None)]}])
        battle._destructibles=types.SimpleNamespace(_catalog_motion_blocked=resolver)
        state={'id':1,'team':1,'slot':0};descriptor=object()
        with mock.patch.object(motion.vehicle_physics,'derive_params',return_value={'speedFwd':13.889,'speedBwd':4.167}):
            self.assertFalse(battle._clear_spawn_destructible_overlap(state,descriptor,(-2,13.729,318),-3.13,1))
            self.assertFalse(battle._clear_spawn_destructible_overlap(state,descriptor,(-2,13.729,318),-3.13,1.5))
            self.assertTrue(battle._clear_spawn_destructible_overlap(state,descriptor,(-2,13.729,318),-3.13,2.1))
            self.assertFalse(battle._clear_spawn_destructible_overlap(state,descriptor,(-2,13.729,318),-3.13,4))
            self.assertEqual(2,resolver.call_count)
            self.assertEqual(0.0,resolver.call_args.args[3])
            self.assertTrue(resolver.call_args.kwargs['spawn_overlap'])
            state['id']=2
            self.assertFalse(battle._clear_spawn_destructible_overlap(state,descriptor,(2,13.729,318),-3.13,5))
            self.assertEqual(2,resolver.call_count)
            battle._worker_mode=False;state['id']=3
            self.assertFalse(battle._clear_spawn_destructible_overlap(state,descriptor,(-2,13.729,318),-3.13,6))
            self.assertEqual(2,resolver.call_count)

    def test_first_live_human_pose_can_finish_spawn_clearance_after_countdown(self):
        battle=motion.BattleRuntime.__new__(motion.BattleRuntime)
        battle._worker_mode=True;battle._generation=7;battle._battle_live=True
        battle._spawn_overlap_done=set();battle._spawn_overlap_retry={}
        battle._avatar=types.SimpleNamespace(spaceID=1);battle._vector=lambda value:value
        battle._formation_pose=lambda team,slot:((-2,13.4,318),-3.13)
        state={'id':1,'team':1,'slot':0,'x':-2,'y':13.729,'z':318,'yaw':-3.13}
        battle._authority_players=lambda:[state]
        battle._resolve_player_descriptor=lambda state:object()
        prewarm=mock.Mock(return_value={'status':'ready'})
        resolver=mock.Mock(return_value={'status':'crushed','accepted_now':True,'token':[(32386,18,None)]})
        battle._destructibles=types.SimpleNamespace(prewarm_tree_registry=prewarm,_catalog_motion_blocked=resolver)
        with mock.patch.object(motion.vehicle_physics,'derive_params',return_value={'speedFwd':13.889,'speedBwd':4.167}):
            self.assertEqual(1,battle._prewarm_player_tree_registries(2))
            self.assertEqual(0,battle._prewarm_player_tree_registries(3))
            prewarm.assert_called_once();resolver.assert_called_once()


if __name__=='__main__':unittest.main()
