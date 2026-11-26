"""Per-class route priorities reach real initial allocation without new probes."""
import copy
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import bot_tactics as config, bot_tactics_runtime as planning
from bot_tactics_store import graph_data


def profile():
    graph=graph_data('31_airfield');doc=config.empty()
    doc['maps']['31_airfield']=dict(mode='regular',resource_sha256=config.MAPS['31_airfield']['resource_sha256'],routes=[],positions=[],default_routes=[])
    return graph,doc


def sources():
    """Team one's shared Default routes, the baseline every edit varies."""
    return config.baseline_routes('31_airfield')['1']


def round_document(doc):
    return config.for_round(config.canonical(doc),'31_airfield')


def edit(route,tag,priority):
    return dict(id=route['id'],team=1,class_tag=tag,priority=priority,
                points=[[p[0],p[1],int(bool(p[2]))] for p in route['waypoints']])


class RoutePriorityTests(unittest.TestCase):
    def test_priorities_are_class_scoped_and_bad_values_are_rejected(self):
        graph,doc=profile();e=edit(sources()[0],'lightTank',8)
        doc['maps']['31_airfield']['default_routes']=[e]
        self.assertEqual(8,config.canonical(doc)['maps']['31_airfield']['default_routes'][0]['priority'])
        for tag,value in (('all',8),('SPG',8),('lightTank',10),('lightTank',-1),('lightTank',1.5)):
            bad=copy.deepcopy(doc);bad['maps']['31_airfield']['default_routes'][0].update(class_tag=tag,priority=value)
            with self.assertRaises(config.TacticsError):config.canonical(bad)

    def test_class_priority_edits_install_variants_without_changing_the_graph(self):
        graph,doc=profile();original=copy.deepcopy(graph)
        north,central,south=sources()
        doc['maps']['31_airfield']['default_routes']=[edit(north,'lightTank',9),edit(central,'heavyTank',9)]
        routes,status=planning.default_routes(round_document(doc),'31_airfield',graph)
        self.assertTrue(all(v=='baked_route_connected' for v in status.values()))
        self.assertEqual(original,graph)
        self.assertEqual(1,len([r for r in routes['1'] if r['id']==north['id']]))

    def test_implicit_default_five_outranks_four_but_explicit_six_wins(self):
        graph,doc=profile();central=sources()[1]
        state=dict(id=1,team=1,slot=0,x=0.,y=0.,z=0.,profile=dict(class_tag='lightTank'))
        for priority,expected in ((4,False),(6,True)):
            doc['maps']['31_airfield']['default_routes']=[edit(central,'lightTank',priority)]
            canonical=round_document(doc)
            catalog,unused=planning.route_catalog(canonical,'31_airfield',graph)
            plans,unused,unused_usage=planning.assign_initial_routes(
                canonical,'31_airfield',graph,[state],catalog,7)
            self.assertEqual(expected,plans[1]['id'] in (central['id'],'class_lt_'+central['id']))

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
        graph,doc=profile();north=sources()[0]
        doc['maps']['31_airfield']['default_routes']=[edit(north,'lightTank',9)]
        document=round_document(doc)
        scoped=next(r for r in document['maps']['31_airfield']['default_routes']
                    if r['team']==1 and r['id']==north['id'] and r.get('class_tag')=='lightTank')
        def check(unused_grid,route):
            return 'waypoints_disconnected' if route is scoped else None
        with mock.patch.object(planning,'validate_route',side_effect=check):
            routes,status=planning.default_routes(document,'31_airfield',graph)
        shared=next(r for r in routes['1'] if r['id']==north['id'])
        self.assertNotIn('lightTank',shared.get('class_priorities',{}))
        self.assertFalse(any(r.get('_editor_source')==north['id'] and r.get('_editor_class')=='lightTank'
                             for r in routes['1']))
        self.assertEqual('waypoints_disconnected',status['1:class_lt_'+north['id']])
        self.assertEqual('baked_route_connected',status['1:'+north['id']])

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
        graph,doc=profile();original=copy.deepcopy(graph);north=sources()[0]
        deletion=edit(north,'lightTank',0);deletion['disabled']=True
        doc['maps']['31_airfield']['default_routes']=[deletion]
        routes,status=planning.default_routes(round_document(doc),'31_airfield',graph)
        variant=next(r for r in routes['1'] if r.get('_editor_source')==north['id'] and
                     r.get('_editor_class')=='lightTank')
        self.assertEqual('reserve',variant['_route_tier'])
        self.assertEqual('lightTank',variant['_editor_class'])
        self.assertIn('baked_route_connected',status.values())
        entry=doc['maps']['31_airfield'];entry['default_routes']=[]
        for route in sources():
            item=edit(route,'all',0);item.pop('priority');item['disabled']=True;entry['default_routes'].append(item)
        clean=round_document(doc);catalog,_=planning.route_catalog(clean,'31_airfield',graph)
        self.assertEqual((),catalog[1])
        self.assertEqual([r['id'] for r in config.baseline_routes('31_airfield')['2']],
                         [r['id'] for r in catalog[2] if not r.get('_editor_source')])
        plans,unused,unused_usage=planning.assign_initial_routes(
            clean,'31_airfield',graph,[dict(id=1,team=1,slot=0,profile=dict(class_tag='heavyTank'))],catalog,7)
        self.assertIsNone(plans[1])
        self.assertEqual(original,graph)
        bad=copy.deepcopy(doc);bad['maps']['31_airfield']['default_routes'][0]['disabled']=1
        with self.assertRaises(config.TacticsError):config.canonical(bad)
