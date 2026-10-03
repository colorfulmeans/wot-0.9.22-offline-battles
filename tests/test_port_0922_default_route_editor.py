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
                if kind=='wait':edit['points'][0].append(30)
                with self.assertRaises(config.TacticsError):config.canonical(profile)

    def test_independent_team_edits_retain_allocation_metadata_and_source(self):
        source=copy.deepcopy(self.graph);profile=edited_profile(self.graph)
        routes,status=planning.default_routes(profile,'31_airfield',self.graph)
        first=source['routes']['1'][0];edit=profile['maps']['31_airfield']['default_routes'][0]
        self.assertEqual(edit['points'],routes['1'][0]['waypoints'])
        self.assertEqual({k:v for k,v in first.items() if k!='waypoints'},
                         {k:v for k,v in routes['1'][0].items() if k!='waypoints'})
        self.assertEqual(source['routes']['2'],routes['2'])
        self.assertEqual(source,self.graph)
        self.assertEqual({'1:'+first['id']:'baked_route_connected'},status)

    def test_disconnected_edit_falls_back_without_overriding_other_routes(self):
        graph=copy.deepcopy(self.graph);graph['links']=[0]*len(graph['links'])
        profile=edited_profile(self.graph)
        routes,status=planning.default_routes(profile,'31_airfield',graph)
        self.assertEqual(graph['routes'],routes)
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
        state.update(id=11,team=1,profile={},route=route)
        manifest=runtime._manifest_entry(state)
        catalog=BotPlanner._route_catalog([manifest])
        self.assertEqual([(p[0],p[1]) for p in expected],
                         [(p['x'],p['z']) for p in catalog[route['id']]['waypoints']])
        self.assertFalse(route['id'].startswith('user_'))
        # The next round with no override must use the unmodified graph again.
        runtime.adapter_factory=factory
        runtime._bot_tactics=config.empty();runtime._new_adapter('31_airfield',6)
        self.assertEqual(self.graph['routes'],factory.call_args.kwargs['baked_routes'])

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
