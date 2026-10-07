"""Editable defaults retain their identities through allocation and manifests."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import bot_tactics as config
from gui.mods.offline_lan_0922 import bot_tactics_runtime as planning
from bot_tactics_store import graph_data, Store
from server_bot_ai import BotPlanner
import test_port_0922_bot_runtime as native


def edited_profile(graph, team=1):
    source=graph['routes'][str(team)][0]
    profile=config.empty('Edited defaults')
    points=[[p[0],p[1],int(bool(p[2]))] for p in source['waypoints']]
    # Node removal is intentionally supported; no allocation metadata changes.
    del points[1]
    profile['maps'][graph['map']]=dict(mode='regular',
        resource_sha256=config.MAPS[graph['map']]['resource_sha256'],
        routes=[],positions=[],default_routes=[dict(id=source['id'],team=team,points=points)])
    return config.canonical(profile)


class DefaultRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=graph_data('31_airfield')

    def test_persistence_and_round_document_keep_defaults_without_custom_routes(self):
        import tempfile
        profile=edited_profile(self.graph)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.save(profile,True)
            self.assertEqual(profile,store.active())
            self.assertEqual(profile,store.read(profile['name']))
        self.assertEqual(profile,config.for_round(profile,'31_airfield'))
        self.assertEqual({},config.for_round(profile,'08_ruinberg')['maps'])
        self.assertEqual([],profile['maps']['31_airfield']['routes'])

    def test_unknown_duplicates_nonfinite_overflow_and_metadata_changes_rejected(self):
        for kind in ('unknown','duplicate','nan','too_many','empty','metadata','wait'):
            with self.subTest(kind=kind):
                profile=edited_profile(self.graph)
                edits=profile['maps']['31_airfield']['default_routes'];edit=edits[0]
                if kind=='unknown':edit['id']='invented_lane'
                if kind=='duplicate':edits.append(copy.deepcopy(edit))
                if kind=='nan':edit['points'][0][0]=float('nan')
                if kind=='too_many':edit['points']*=2
                if kind=='empty':edit['points']=[]
                if kind=='metadata':edit['capacity']=15
                if kind=='wait':edit['points'][0].append(-0.5)
                with self.assertRaises(config.TacticsError):config.canonical(profile)

    def test_independent_team_edits_retain_allocation_metadata_and_source(self):
        source=copy.deepcopy(self.graph);profile=edited_profile(self.graph)
        routes,status=planning.default_routes(profile,'31_airfield',self.graph)
        first=source['routes']['1'][0];edit=profile['maps']['31_airfield']['default_routes'][0]
        self.assertEqual(edit['points'],routes['1'][0]['waypoints'])
        self.assertEqual({k:v for k,v in first.items() if k!='waypoints'},
                         {k:v for k,v in routes['1'][0].items() if k not in ('waypoints','_allocation_symmetric')})
        self.assertFalse(routes['1'][0]['_allocation_symmetric'])
        unedited,unused=planning.default_routes(config.empty(),'31_airfield',self.graph)
        self.assertEqual(unedited['2'],routes['2'])
        self.assertEqual(source,self.graph)
        self.assertEqual({'1:'+first['id']:'baked_route_connected'},status)

    def test_disconnected_edit_falls_back_without_overriding_other_routes(self):
        graph=copy.deepcopy(self.graph);graph['links']=[0]*len(graph['links'])
        profile=edited_profile(self.graph)
        routes,status=planning.default_routes(profile,'31_airfield',graph)
        self.assertEqual(planning.default_routes(config.empty(),'31_airfield',graph)[0],routes)
        self.assertEqual(['waypoints_disconnected'],list(status.values()))

    def test_worker_installs_edits_before_assignment_and_host_catalog_receives_geometry(self):
        module=native._load();runtime=module.BotRuntime(1)
        runtime.baked_graph=self.graph;runtime._bot_tactics=edited_profile(self.graph)
        factory=mock.Mock(return_value=object());runtime.adapter_factory=factory
        runtime._new_adapter('31_airfield',5)
        route=factory.call_args.kwargs['baked_routes']['1'][0]
        expected=runtime._bot_tactics['maps']['31_airfield']['default_routes'][0]['points']
        self.assertEqual(expected,route['waypoints'])
        runtime.adapter_factory=module.BotAdapter
        adapter=runtime._new_adapter('31_airfield',5)
        assigned=[adapter.director.register_profile(i,1,dict(class_tag='mediumTank',
                  roles={'flanker':1.0},vehicle_name='test'))['route'] for i in range(11,25)]
        edited=[r for r in assigned if r['id']==route['id']]
        self.assertTrue(edited)
        for selected in edited:
            self.assertEqual([tuple(p) for p in expected],list(selected['waypoints']))
        runtime._publish_equipment_state=mock.Mock()
        # The ordinary manifest serializer is shared by first load and handoff.
        state={k:0 for k in ('id','team','slot','name','vehicle','health','max_health','x','y','z','yaw',
            'fire_seq','shell_index','next_shell_index','ammo_remaining','ammo_reload_pending',
            'reload_time','reload_duration','clip','clip_size','siege_state','siege_time_left_ms',
            'siege_transition_total_ms','equipment_states','stun_end_server_time_ms')}
        state.update(id=11,team=1,profile={},route=route,half_length=6,half_width=2.5)
        manifest=runtime._manifest_entry(state)
        from lan_battle_server import BattleState
        self.assertEqual(6.5,manifest['profile']['parking_radius'])
        self.assertEqual(6.5,BattleState._sanitize_bot_profile(manifest['profile'])['parking_radius'])
        self.assertNotIn('parking_radius',state['profile'])
        catalog=BotPlanner._route_catalog([manifest])
        self.assertEqual([(p[0],p[1]) for p in expected],
                         [(p['x'],p['z']) for p in catalog[route['id']]['waypoints']])
        self.assertFalse(route['id'].startswith('user_'))
        # The next round with no override must use the unmodified graph again.
        runtime.adapter_factory=factory
        runtime._bot_tactics=config.empty();runtime._new_adapter('31_airfield',6)
        self.assertEqual(planning.default_routes(config.empty(),'31_airfield',self.graph)[0],
                         factory.call_args.kwargs['baked_routes'])

    def test_editor_registry_matches_every_shipped_default_id(self):
        root=Path(__file__).resolve().parents[1]
        for name,meta in config.MAPS.items():
            graph=json.loads((root/'navgraphs'/ (name+'.json')).read_bytes())
            self.assertEqual(meta['route_ids'],{team:[r['id'] for r in routes]
                                               for team,routes in graph['routes'].items()})
            profile=config.empty()
            edits=[dict(id=r['id'],team=int(team),points=[[p[0],p[1],int(bool(p[2]))] for p in r['waypoints']])
                   for team,routes in graph['routes'].items() for r in routes]
            profile['maps'][name]=dict(mode='regular',resource_sha256=meta['resource_sha256'],
                                       routes=[],positions=[],default_routes=edits)
            with self.subTest(map=name):
                self.assertEqual(len(edits),len(config.canonical(profile)['maps'][name]['default_routes']))

    def test_scoped_defaults_reach_matching_priority_selected_bots_and_restore_wire_geometry(self):
        module=native._load();runtime=module.BotRuntime(1)
        runtime.baked_graph=self.graph
        profile=edited_profile(self.graph)
        edit=profile['maps']['31_airfield']['default_routes'][0]
        edit['class_tag']='heavyTank';edit['priority']=9;edit['points'][0].append(12.5)
        runtime._bot_tactics=config.canonical(profile)
        runtime.adapter=runtime._new_adapter('31_airfield',5)
        for actor,tag in ((11,'heavyTank'),(12,'mediumTank')):
            assigned=runtime.adapter.director.register_profile(actor,1,dict(class_tag=tag,
                roles={'frontline':1.0},vehicle_name='test'))
            source=next(r for r in runtime.adapter.director.map_data['routes'][1] if r['id']==edit['id'])
            runtime.states[actor]=dict(id=actor,team=1,slot=actor-11,profile={'class_tag':tag},route=source)
        runtime._prepare_user_routes(dict(map='31_airfield'),False)
        self.assertEqual(config.default_route_id(edit),runtime.states[11]['route']['id'])
        medium=runtime.states[12]['route']
        source=next(r for r in self.graph['routes']['1'] if r['id']==medium['id'])
        self.assertEqual([tuple(p[:3]) for p in source['waypoints']],list(medium['waypoints']))
        self.assertTrue(all(len(p)==3 for p in runtime.states[11]['route']['waypoints']))
        cfg=config.route_config(runtime._bot_tactics,'31_airfield',runtime.states[11]['route']['id'],1)
        self.assertEqual(12.5,cfg['points'][0][3])
        self.assertIsNone(config.route_config(runtime._bot_tactics,'31_airfield',cfg['id'],2))
        restored=[dict(id=actor,team=1,route=dict(id=runtime.states[actor]['route']['id'],
                  waypoints=[dict(x=p[0],z=p[1],hold=bool(p[2]))
                             for p in runtime.states[actor]['route']['waypoints']])) for actor in (11,12)]
        runtime._prepare_user_routes(dict(map='31_airfield',bot_manifest=restored),True)
        self.assertEqual(cfg['id'],runtime.states[11]['route']['id'])

    def test_symmetry_metadata_and_waits_roundtrip_with_independent_team_lookup(self):
        profile=edited_profile(self.graph)
        own=profile['maps']['31_airfield']['default_routes'][0]
        own.update(symmetric=True,class_tag='SPG');own['points'][1].append(-1)
        peer=copy.deepcopy(own);peer.update(team=2,points=list(reversed(own['points'])))
        profile['maps']['31_airfield']['default_routes'].append(peer)
        canonical=config.canonical(profile)
        for team,expected in ((1,own),(2,peer)):
            route=config.route_config(canonical,'31_airfield',config.default_route_id(own),team)
            self.assertEqual(expected['points'],route['points'])
        self.assertEqual(canonical,config.canonical(json.loads(config.dumps(canonical))))

    def test_rejected_default_waits_cannot_attach_to_original_fallback_geometry(self):
        profile=edited_profile(self.graph)
        edit=profile['maps']['31_airfield']['default_routes'][0]
        edit['points'][0].append(30)
        self.assertIsNone(config.route_config(profile,'31_airfield',edit['id'],1,
            self.graph['routes']['1'][0]['waypoints']))
        self.assertIsNotNone(config.route_config(profile,'31_airfield',edit['id'],1,edit['points']))
