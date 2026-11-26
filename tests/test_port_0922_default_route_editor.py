"""Editable defaults retain their identities through allocation and manifests."""
import copy
import json
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import bot_tactics as config
from gui.mods.offline_lan_0922 import bot_tactics_runtime as planning
from bot_tactics_store import graph_data, Store
from server_bot_ai import BotPlanner
import test_port_0922_bot_runtime as native


def baseline_source(name, team=1):
    """The built-in Default's first shared route for one team."""
    return config.baseline_routes(name)[str(team)][0]


def edited_profile(graph, team=1):
    source=baseline_source(graph['map'],team)
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
        # The round completes every route the profile leaves out from the Default.
        round_entry=config.for_round(profile,'31_airfield')['maps']['31_airfield']
        edit=profile['maps']['31_airfield']['default_routes'][0]
        self.assertIn(edit,round_entry['default_routes'])
        self.assertEqual(config.effective_default_routes(profile,'31_airfield'),round_entry['default_routes'])
        self.assertEqual(len(config.MAPS['31_airfield']['route_ids']['1'])+
                         len(config.MAPS['31_airfield']['route_ids']['2']),
                         sum(1 for r in round_entry['default_routes'] if r.get('class_tag','all')=='all'))
        absent=config.for_round(profile,'08_ruinberg')['maps']['08_ruinberg']
        self.assertEqual(config.default_map('08_ruinberg')['default_routes'],absent['default_routes'])
        self.assertEqual(([],[]),(absent['routes'],absent['positions']))
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

    def test_independent_team_edits_keep_the_default_for_every_other_route(self):
        source=copy.deepcopy(self.graph);profile=edited_profile(self.graph)
        routes,status=planning.default_routes(config.for_round(profile,'31_airfield'),'31_airfield',self.graph)
        first=baseline_source('31_airfield');edit=profile['maps']['31_airfield']['default_routes'][0]
        self.assertEqual(first['id'],routes['1'][0]['id'])
        self.assertEqual(edit['points'],routes['1'][0]['waypoints'])
        # Routes carry no lane capacity, risk or role affinity.
        self.assertFalse(set(('capacity','risk','role_weights'))&set(routes['1'][0]))
        self.assertFalse(routes['1'][0]['_allocation_symmetric'])
        # Every row the profile leaves out keeps the Default's row, class
        # variants included, exactly as the editor shows it.
        unedited,unused=planning.default_routes(config.for_round(config.empty(),'31_airfield'),'31_airfield',self.graph)
        self.assertEqual(unedited['2'],routes['2'])
        self.assertEqual([r for r in unedited['1'] if r['id']!=first['id']],
                         [r for r in routes['1'] if r['id']!=first['id']])
        self.assertEqual(source,self.graph)
        self.assertEqual('baked_route_connected',status['1:'+first['id']])

    def test_unusable_route_is_left_out_without_other_geometry(self):
        profile=config.for_round(edited_profile(self.graph),'31_airfield')
        edit=next(r for r in profile['maps']['31_airfield']['default_routes']
                  if r['team']==1 and r['id']==baseline_source('31_airfield')['id'] and
                  r.get('class_tag','all')=='all')
        def check(unused_grid,route):
            return 'waypoints_disconnected' if route is edit else None
        with mock.patch.object(planning,'validate_route',side_effect=check):
            routes,status=planning.default_routes(profile,'31_airfield',self.graph)
        # The shared route and the class variants that vary it are not used.
        self.assertFalse([r for r in routes['1'] if edit['id'] in (r['id'],r.get('_editor_source'))])
        self.assertEqual('waypoints_disconnected',status['1:'+edit['id']])
        others=planning.default_routes(profile,'31_airfield',self.graph)[0]
        self.assertEqual([r for r in others['1'] if edit['id'] not in (r['id'],r.get('_editor_source'))],
                         routes['1'])
        self.assertEqual(others['2'],routes['2'])

    def test_worker_installs_edits_before_assignment_and_host_catalog_receives_geometry(self):
        module=native._load();runtime=module.BotRuntime(1)
        runtime.baked_graph=self.graph
        runtime._bot_tactics=config.for_round(edited_profile(self.graph),'31_airfield')
        factory=mock.Mock(return_value=object());runtime.adapter_factory=factory
        runtime._new_adapter('31_airfield',5)
        factory.assert_called_once_with('31_airfield',5)
        route=runtime._route_catalog[1][0]
        self.assertEqual(baseline_source('31_airfield')['id'],route['id'])
        expected=next(r for r in runtime._bot_tactics['maps']['31_airfield']['default_routes']
                      if r['team']==1 and r['id']==route['id'] and r.get('class_tag','all')=='all')['points']
        self.assertEqual([(float(p[0]),float(p[1]),bool(p[2])) for p in expected],list(route['waypoints']))
        states=[dict(id=i,team=1,slot=i-11,profile=dict(class_tag='mediumTank')) for i in range(11,25)]
        plans,unused,unused_usage=planning.assign_initial_routes(
            runtime._bot_tactics,'31_airfield',self.graph,states,runtime._route_catalog,5)
        edited=[r for r in plans.values() if r is not None and r['id']==route['id']]
        self.assertTrue(edited)
        for selected in edited:
            self.assertEqual(route['waypoints'],selected['waypoints'])
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
        # The next round with no override uses the unmodified Default again.
        runtime._bot_tactics=config.for_round(config.empty(),'31_airfield');runtime._new_adapter('31_airfield',6)
        self.assertEqual(planning.route_catalog(config.for_round(config.empty(),'31_airfield'),
                                                '31_airfield',self.graph)[0],
                         runtime._route_catalog)

    def test_editor_registry_matches_every_shipped_default_id(self):
        for name,meta in config.MAPS.items():
            rows=config.default_map(name)['default_routes']
            with self.subTest(map=name):
                self.assertEqual({team:set(ids) for team,ids in meta['route_ids'].items()},
                                 {team:{r['id'] for r in rows if str(r['team'])==team and
                                        r.get('class_tag','all')=='all'} for team in ('1','2')})
                self.assertEqual({team:[r['id'] for r in routes] for team,routes in
                                  config.baseline_routes(name).items()},meta['route_ids'])

    def test_scoped_defaults_reach_matching_priority_selected_bots_and_restore_wire_geometry(self):
        module=native._load();runtime=module.BotRuntime(1)
        runtime.baked_graph=self.graph
        profile=edited_profile(self.graph)
        edit=profile['maps']['31_airfield']['default_routes'][0]
        edit['class_tag']='heavyTank';edit['priority']=9
        edit['points'][0][2:]=[1,0,[[edit['points'][0][0],edit['points'][0][1],12.5]]]
        runtime._bot_tactics=config.for_round(config.canonical(profile),'31_airfield')
        runtime.adapter=runtime._new_adapter('31_airfield',5)
        for actor,tag in ((11,'heavyTank'),(12,'mediumTank')):
            source=next(r for r in runtime._route_catalog[1] if r['id']==edit['id'])
            runtime.states[actor]=dict(id=actor,team=1,slot=actor-11,profile={'class_tag':tag},route=source)
        runtime._prepare_user_routes(dict(map='31_airfield'),False)
        self.assertEqual(config.default_route_id(edit),runtime.states[11]['route']['id'])
        # The medium tank keeps the row this round uses for it, from the Default.
        medium=runtime.states[12]['route']
        source=next(r for r in runtime._bot_tactics['maps']['31_airfield']['default_routes']
                    if r['team']==1 and config.default_route_id(r)==medium['id'])
        self.assertEqual([tuple(p[:3]) for p in source['points']],list(medium['waypoints']))
        self.assertTrue(all(len(p)==3 for p in runtime.states[11]['route']['waypoints']))
        cfg=config.route_config(runtime._bot_tactics,'31_airfield',runtime.states[11]['route']['id'],1)
        self.assertEqual(12.5,cfg['points'][0][4][0][2])
        self.assertIsNone(config.route_config(runtime._bot_tactics,'31_airfield',cfg['id'],2))
        restored=[dict(id=actor,team=1,route=dict(id=runtime.states[actor]['route']['id'],
                  waypoints=[dict(x=p[0],z=p[1],hold=bool(p[2]))
                             for p in runtime.states[actor]['route']['waypoints']])) for actor in (11,12)]
        runtime._prepare_user_routes(dict(map='31_airfield',bot_manifest=restored),True)
        self.assertEqual(cfg['id'],runtime.states[11]['route']['id'])

    def test_symmetry_metadata_and_waits_roundtrip_with_independent_team_lookup(self):
        profile=edited_profile(self.graph)
        own=profile['maps']['31_airfield']['default_routes'][0]
        own.update(symmetric=True,class_tag='SPG')
        own['points'][1][2:]=[1,0,[[own['points'][1][0],own['points'][1][1],-1]]]
        peer=copy.deepcopy(own);peer.update(team=2,points=list(reversed(own['points'])))
        profile['maps']['31_airfield']['default_routes'].append(peer)
        canonical=config.canonical(profile)
        for team,expected in ((1,own),(2,peer)):
            route=config.route_config(canonical,'31_airfield',config.default_route_id(own),team)
            self.assertEqual(expected['points'],route['points'])
        self.assertEqual(canonical,config.canonical(json.loads(config.dumps(canonical))))

    def test_rejected_default_waits_cannot_attach_to_the_default_geometry(self):
        profile=edited_profile(self.graph)
        edit=profile['maps']['31_airfield']['default_routes'][0]
        edit['points'][0].append(30)
        self.assertIsNone(config.route_config(profile,'31_airfield',edit['id'],1,
            baseline_source('31_airfield')['waypoints']))
        self.assertIsNotNone(config.route_config(profile,'31_airfield',edit['id'],1,edit['points']))
