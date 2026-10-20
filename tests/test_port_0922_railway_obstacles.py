"""Stock railway identities agree in cold/warm planning and kinetic gates."""
import collections,json,sys,types,unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src/res/scripts/client')]
import test_port_0922_destructibles as fixture
from gui.mods.offline_lan_0922 import destructibles_sensor as sensor
from gui.mods.offline_lan_0922.scenery_policy import railway_vehicle_resource

class RailwayTests(unittest.TestCase):
    def setUp(self):
        owner=fixture.DestructiblesCompatibilityTests();owner.setUp()
        self.addCleanup(owner.tearDown);self.addCleanup(owner.doCleanups)

    def test_all_catalog_maps_keep_railway_native_ids_before_streaming(self):
        maps=0;total=0
        for path in (ROOT/'destructibles').glob('*.json'):
            catalog=json.loads(path.read_text());resources=catalog.get('resources',{})
            if not isinstance(resources,dict):continue
            trains={name for name in resources if railway_vehicle_resource(name)}
            if not trains:continue
            sensor.set_catalog(catalog);maps+=1
            keep=sensor.prepare_navigation_collision_filter(fixture._Vector(),fixture._Vector(0,0,10))
            self.assertFalse(getattr(sensor,'g_offh_destr_instances',{}))
            for row in catalog['instances']:
                expected=row[12] in trains
                for material in (71,73,85):self.assertEqual(expected,keep(material,0,row[15],row[14]),(path.name,row[12]))
                if expected:
                    total+=1;self.assertTrue(sensor._soft_static_original_filter_1513({(row[14],row[15],None)})(73,0,row[15],row[14]))
            for material in (0,70,86,87,100):self.assertTrue(keep(material,0,0,0))
        self.assertEqual(11,maps);self.assertGreater(total,800)

    def test_registered_railway_and_extreme_speed_never_authorize_crushing(self):
        name='CONTENT\\Railway\\RW004_Carriage\\normal\\lod0\\rw004_Carriage3.model'
        sensor.g_offh_destr_instances={(22,3):dict(filename=name)}
        keep=sensor.prepare_navigation_collision_filter(None,None)
        self.assertTrue(keep(73,0,3,22))
        decoded=(None,None,22,3,73,name)
        with mock.patch.object(sensor,'_decode_mat_info_1513',return_value=decoded):
            for speed in (0.,3.,-10.,1000.):self.assertIs(False,sensor._stock_crushable_1513(None,speed,object(),1.))

    def test_broken_train_cannot_use_the_broken_prop_clearance_shortcut(self):
        catalog=json.loads((ROOT/'destructibles/06_ensk.json').read_text())
        sensor.set_catalog(catalog)
        name=next(k for k in catalog['resources'] if railway_vehicle_resource(k))
        candidate=(22,3,None,name,'fragile',1.)
        start,end=fixture._Vector(0.,1.,0.),fixture._Vector(0.,1.,10.)
        hit=(fixture._Vector(0.,1.,4.),fixture._Vector(0.,0.,-1.));trace={}
        with mock.patch.dict(sys.modules,{'BigWorld':types.SimpleNamespace(),'Math':types.SimpleNamespace()}), \
                mock.patch.object(sensor,'_planning_catalog_candidate_1513',return_value=candidate), \
                mock.patch.object(sensor,'_get_destr_authority',return_value=types.SimpleNamespace(is_destroyed=lambda *a:True)):
            self.assertIs(False,sensor._catalog_soft_static_path(1,start,end,hit,100.,object(),kinetic_speed=100.,trace=trace))
        self.assertEqual('solid_railway_vehicle',trace['reason'])
        self.assertEqual(name,trace['objects'][0]['model'])

    def test_railway_family_does_not_include_tracks_signs_or_town_trucks(self):
        for name in ('rw002_Sleepers','rw008_Semafor','rw604_Rwsign','rw010_RailStrelki','ve008_GazMM'):
            self.assertFalse(railway_vehicle_resource('content/Railway/'+name+'/normal/lod0/model.model'))
        self.assertFalse(railway_vehicle_resource('content/Fake/rw004_Carriage_sign/model.model'))

class RailwayGraphMaskTests(unittest.TestCase):
    def test_railway_mask_preserves_unrelated_one_way_ingress(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import repair_railway_navigation_0922 as repair
        field=types.SimpleNamespace(cells={},raster_size=1.,blocked=lambda *a,**k:False)
        layer=dict(width=2,height=1,cell_size=8.,origin=[-4.,0.],heights_mm=[0,0],links=[1,0],hazards=[0,0])
        repair.mask_layer(layer,[(1,0),(-1,0)],field,types.SimpleNamespace(VEHICLE_HALF_WIDTH=2.15))
        self.assertEqual([1,0],layer['links'])
        self.assertEqual([0,0],layer['heights_mm'])

    def test_link_crossing_carriage_is_cut_even_when_endpoints_are_clear(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import repair_railway_navigation_0922 as repair
        field=types.SimpleNamespace(cells={(0,0):True},raster_size=1.,blocked=lambda x,z,y,margin:abs(x)<.2)
        layer=dict(width=2,height=1,cell_size=8.,origin=[-4.,0.],heights_mm=[0,0],links=[1,2],hazards=[0,0])
        result=repair.mask_layer(layer,[(1,0),(-1,0)],field,types.SimpleNamespace(VEHICLE_HALF_WIDTH=2.15))
        self.assertEqual([0,0],layer['links'])
        self.assertEqual([0,0],layer['heights_mm'])
        self.assertEqual(2,result['removed_directed_links'])

    def test_repair_is_idempotent_and_retains_initial_mask_evidence(self):
        import repair_railway_navigation_0922 as repair
        field=types.SimpleNamespace(cells={(0,0):True},raster_size=1.,blocked=lambda x,z,y,margin:abs(x)<.2)
        legacy=types.SimpleNamespace(VEHICLE_HALF_WIDTH=2.15,validate_graph=lambda *a:{'ok':True})
        graph=dict(width=2,height=1,cell_size=8.,origin=[-4.,0.],heights_mm=[0,0],links=[1,2],hazards=[0,0],directions=[(1,0),(-1,0)],routes={},bases=[[-4.,0.],[4.,0.]],bake={})
        first=repair.repair(graph,field,legacy)
        self.assertEqual(first,repair.repair(first,field,legacy))

if __name__=='__main__':unittest.main()
