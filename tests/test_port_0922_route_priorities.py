"""Per-class route priorities reach real initial allocation without new probes."""
import copy
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import bot_tactics as config, bot_tactics_runtime as planning
from gui.mods.offline_lan_0922.ai.planner import BattleDirector
from bot_tactics_store import graph_data


def profile():
    graph=graph_data('31_airfield');doc=config.empty()
    doc['maps']['31_airfield']=dict(mode='regular',resource_sha256=config.MAPS['31_airfield']['resource_sha256'],routes=[],positions=[],default_routes=[])
    return graph,doc


def edit(route,tag,priority):
    return dict(id=route['id'],team=1,class_tag=tag,priority=priority,
                points=[[p[0],p[1],int(bool(p[2]))] for p in route['waypoints']])


class RoutePriorityTests(unittest.TestCase):
    def test_priorities_are_class_scoped_and_bad_values_are_rejected(self):
        graph,doc=profile();e=edit(graph['routes']['1'][0],'lightTank',8)
        doc['maps']['31_airfield']['default_routes']=[e]
        self.assertEqual(8,config.canonical(doc)['maps']['31_airfield']['default_routes'][0]['priority'])
        for tag,value in (('all',8),('SPG',8),('lightTank',10),('lightTank',-1),('lightTank',1.5)):
            bad=copy.deepcopy(doc);bad['maps']['31_airfield']['default_routes'][0].update(class_tag=tag,priority=value)
            with self.assertRaises(config.TacticsError):config.canonical(bad)

    def test_default_allocation_prefers_class_priority_then_spills_at_capacity(self):
        graph,doc=profile();original=copy.deepcopy(graph)
        north,central,south=graph['routes']['1']
        doc['maps']['31_airfield']['default_routes']=[edit(north,'lightTank',9),edit(central,'heavyTank',9)]
        routes,status=planning.default_routes(config.canonical(doc),'31_airfield',graph)
        self.assertTrue(all(v=='baked_route_connected' for v in status.values()))
        director=BattleDirector('31_airfield',123,baked_routes=routes)
        preferred=next(r for r in director._routes_for(1) if r['id']==north['id'])
        # Capacity is per vehicle class, not the parent route's total.
        for i in range(3):
            agent=director.register_profile(i+1,1,dict(class_tag='lightTank',roles={'brawler':1.0},vehicle_name='test'))
            self.assertEqual(north['id'],agent['route']['id'])
        agent=director.register_profile(100,1,dict(class_tag='lightTank',roles={'brawler':1.0},vehicle_name='test'))
        self.assertNotEqual(north['id'],agent['route']['id'])
        heavy=BattleDirector('31_airfield',123,baked_routes=routes)
        self.assertEqual(central['id'],heavy.register_profile(1,1,dict(class_tag='heavyTank',roles={'scout':1.0},vehicle_name='test'))['route']['id'])
        self.assertEqual(original,graph)
        self.assertEqual(1,len([r for r in routes['1'] if r['id']==north['id']]))

    def test_implicit_default_five_outranks_four_but_explicit_six_wins(self):
        graph,doc=profile();central=graph['routes']['1'][1]
        for priority,expected in ((4,False),(6,True)):
            doc['maps']['31_airfield']['default_routes']=[edit(central,'lightTank',priority)]
            routes,unused=planning.default_routes(config.canonical(doc),'31_airfield',graph)
            director=BattleDirector('31_airfield',123,baked_routes=routes)
            chosen=director.register_profile(1,1,dict(class_tag='lightTank',roles={'scout':1.0}))['route']
            self.assertEqual(expected,chosen['id'] in (central['id'],'class_lt_'+central['id']))

    def test_custom_default_five_matches_a_current_baked_route_and_four_does_not(self):
        graph,doc=profile()
        route=dict(id='join',label='Join',team=1,classes=['lightTank'],slots=[],policy='preferred',
                   capacity=1,weight=1.,points=[[-100.,-100.,0],[100.,100.,0]])
        doc['maps']['31_airfield']['routes']=[route]
        states=[dict(id=1,team=1,slot=0,x=0.,y=0.,z=0.,profile=dict(class_tag='lightTank'),route={'id':'baked'})]
        with mock.patch.object(planning,'graph_view') as grid,mock.patch.object(planning,'validate_route',return_value=None),mock.patch.object(planning,'_route_reachable',return_value=True):
            grid.return_value.closest.return_value=1
            self.assertIn(1,planning.assign_routes(config.canonical(doc),'31_airfield',graph,states,1)[0])
            route['class_priorities']={'lightTank':4}
            self.assertEqual({},planning.assign_routes(config.canonical(doc),'31_airfield',graph,states,1)[0])

    def test_invalid_geometry_does_not_install_priority(self):
        graph,doc=profile();doc['maps']['31_airfield']['default_routes']=[edit(graph['routes']['1'][0],'lightTank',9)]
        graph=copy.deepcopy(graph);graph['links']=[0]*len(graph['links'])
        routes,status=planning.default_routes(config.canonical(doc),'31_airfield',graph)
        self.assertEqual(planning.default_routes(config.empty(),'31_airfield',graph)[0],routes)
        self.assertTrue(all(v=='waypoints_disconnected' for v in status.values()))

    def test_custom_priorities_rank_before_weight_and_preserve_class_and_capacity(self):
        graph,doc=profile();entry=doc['maps']['31_airfield']
        entry['routes']=[dict(id='low',label='Low',team=1,classes=['lightTank','heavyTank'],slots=[],policy='preferred',capacity=1,weight=10.,points=[[-100.,-100.,0],[100.,100.,0]],class_priorities={'lightTank':0,'heavyTank':9}),
                         dict(id='high',label='High',team=1,classes=['lightTank','heavyTank'],slots=[],policy='preferred',capacity=1,weight=.01,points=[[-100.,-100.,0],[100.,100.,0]],class_priorities={'lightTank':9,'heavyTank':0})]
        doc=config.canonical(doc)
        states=[dict(id=i,team=1,slot=i-1,x=0.,y=0.,z=0.,profile=dict(class_tag='lightTank')) for i in (1,2)]
        with mock.patch.object(planning,'graph_view') as grid,mock.patch.object(planning,'validate_route',return_value=None),mock.patch.object(planning,'_route_reachable',return_value=True):
            grid.return_value.closest.return_value=1
            plans,_=planning.assign_routes(doc,'31_airfield',graph,states,1)
            self.assertEqual('user_high',plans[1]['id']);self.assertEqual('user_low',plans[2]['id'])
            states[0]['profile']['class_tag']='heavyTank'
            plans,_=planning.assign_routes(doc,'31_airfield',graph,states[:1],1)
            self.assertEqual('user_low',plans[1]['id'])
            states[0]['route']={'class_priorities':{'heavyTank':9}}
            entry=config.canonical(doc)['maps']['31_airfield'];entry['routes']=entry['routes'][:1]
            entry['routes'][0]['class_priorities']['heavyTank']=0
            doc['maps']['31_airfield']=entry
            self.assertEqual({},planning.assign_routes(doc,'31_airfield',graph,states[:1],1)[0])

    def test_deleted_defaults_are_excluded_by_class_and_allow_empty_sides(self):
        graph,doc=profile();original=copy.deepcopy(graph);north=graph['routes']['1'][0]
        deletion=edit(north,'lightTank',0);deletion['disabled']=True
        doc['maps']['31_airfield']['default_routes']=[deletion]
        routes,status=planning.default_routes(config.canonical(doc),'31_airfield',graph)
        self.assertIn('route_deleted',status.values())
        director=BattleDirector('31_airfield',123,baked_routes=routes)
        self.assertNotIn(north['id'],[(director.register_profile(i,1,dict(class_tag='lightTank',roles={} ))['route'] or {}).get('id') for i in range(1,15)])
        source=next(r for r in director._routes_for(1) if r['id']==north['id'])
        self.assertEqual(0.,source['class_weights']['lightTank'])
        self.assertNotIn('heavyTank',source['_editor_disabled_classes'])
        entry=doc['maps']['31_airfield'];entry['default_routes']=[]
        for route in graph['routes']['1']:
            item=edit(route,'all',0);item.pop('priority');item['disabled']=True;entry['default_routes'].append(item)
        clean=config.canonical(doc);routes,_=planning.default_routes(clean,'31_airfield',graph)
        director=BattleDirector('31_airfield',123,baked_routes=routes)
        self.assertEqual((),director._routes_for(1))
        self.assertIsNone(director.register_profile(1,1,dict(class_tag='heavyTank',roles={}))['route'])
        self.assertEqual(original,graph)
        bad=copy.deepcopy(doc);bad['maps']['31_airfield']['default_routes'][0]['disabled']=1
        with self.assertRaises(config.TacticsError):config.canonical(bad)
