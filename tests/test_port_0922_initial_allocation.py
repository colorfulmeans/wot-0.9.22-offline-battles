"""Priority lottery contracts; baked geometry is not native gameplay proof."""
import copy
import contextlib
import io
import json
import random
import unittest
from unittest import mock

from test_port_0922_bot_tactics_editor import profile
from test_port_0922_spg_initial_positions import _graph, _states
from gui.mods.offline_lan_0922 import bot_tactics as cfg, bot_tactics_runtime as planning
from gui.mods.offline_lan_0922 import initial_allocation as lottery, spg_positions
import test_port_0922_bot_tactics_editor as editor_tests


def actors(count=3, tag='lightTank'):
    return [dict(id=team*100+slot, team=team, slot=slot, profile={'class_tag':tag})
            for team in (1, 2) for slot in range(count)]


def lanes(capacity=3, priorities=(5,5,5), symmetric=True):
    return dict((team, [dict(id='lane_%d'%i, capacity=capacity,
                            waypoints=[(team*10+i,team*20+i,0)],
                            class_priorities={'lightTank':p},
                            class_weights={'lightTank':1}, _allocation_symmetric=symmetric)
                       for i,p in enumerate(priorities)]) for team in (1,2))


class InitialRouteLotteryTests(unittest.TestCase):
    def assign(self, catalog=None, states=None, seed=7, raw=None, graph=None):
        return planning.assign_initial_routes(raw or cfg.empty(), '08_ruinberg', graph or {},
                                             states or actors(), catalog or lanes(), seed)

    def test_symmetric_family_matches_class_ordinal_and_keeps_side_geometry(self):
        states=actors();states.reverse();states[0]['slot']=30
        plans,unused,usage=self.assign(states=states)
        for ordinal in range(3):
            a,b=plans[100+ordinal],plans[200+ordinal]
            self.assertEqual(a['id'],b['id'])
            self.assertNotEqual(a['waypoints'],b['waypoints'])
        self.assertEqual(6,sum(usage.values()))

    def test_draws_with_replacement_can_put_all_three_on_one_lane(self):
        results=[self.assign(seed=seed)[0] for seed in range(100)]
        self.assertTrue(any(len(set(p[i]['id'] for i in (100,101,102)))==1 for p in results))
        self.assertGreater(len(set(p[100]['id'] for p in results)),1)

    def test_higher_priority_fills_before_lower_and_full_means_auto(self):
        plans,outcomes,usage=self.assign(lanes(1,(9,5,5)),actors(10))
        self.assertEqual('lane_0',plans[100]['id'])
        self.assertEqual({None},set(plans[i] for i in (109,209)))
        self.assertEqual('full_or_unusable_routes_auto',outcomes[109])
        self.assertTrue(all(n==3 for n in usage.values()))
        self.assertEqual({'lane_1','lane_2'},set(plans[i]['id'] for i in (103,104,105,106,107,108)))

    def test_standalone_routes_can_differ_between_sides(self):
        catalog=lanes(symmetric=False)
        self.assertTrue(any(self.assign(catalog,seed=s)[0][100]['id'] !=
                            self.assign(catalog,seed=s)[0][200]['id'] for s in range(30)))

    def test_mixed_catalog_still_couples_a_selected_symmetric_family(self):
        catalog=lanes()
        for team in (1,2):catalog[team][-1]['_allocation_symmetric']=False
        for seed in range(50):
            plans,unused,unused_usage=self.assign(catalog,actors(1),seed)
            a,b=plans[100],plans[200]
            if a['_allocation_symmetric'] or b['_allocation_symmetric']:
                self.assertEqual(a['id'],b['id'])

    def test_one_sided_lane_does_not_remove_opponents_available_choices(self):
        catalog=lanes();catalog[2]=catalog[2][:1]
        plans,unused,unused_usage=self.assign(catalog)
        self.assertTrue(all(plans[i] is not None for i in (100,101,102,200,201,202)))

    def test_class_variants_have_independent_capacity(self):
        catalog=lanes(1)
        for team in (1,2):
            catalog[team]=catalog[team][:1]
            catalog[team][0]['class_weights']['heavyTank']=1
            variant=copy.deepcopy(catalog[team][0])
            variant.update(id='class_lt_lane_0',_editor_source='lane_0',_editor_class='lightTank')
            catalog[team].append(variant)
        states=actors(1)+actors(1,'heavyTank')
        for state in states[2:]:state['id']+=10
        plans,unused,usage=self.assign(catalog,states)
        self.assertEqual(4,sum(p is not None for p in plans.values()))
        self.assertEqual({(t,'lane_0',c):1 for t in (1,2) for c in ('lightTank','heavyTank')},usage)

    def test_mother_only_and_class_variants_each_allow_three_per_class(self):
        for variants in (False, True):
            catalog=lanes()
            tags=('lightTank','mediumTank','heavyTank','AT-SPG')
            for team in (1,2):
                base=catalog[team][0];base['class_weights']={tag:1 for tag in tags}
                catalog[team]=[base]
                if variants:
                    for tag in tags:
                        row=copy.deepcopy(base)
                        row.update(id='class_'+tag,_editor_source=base['id'],_editor_class=tag)
                        catalog[team].append(row)
            states=[]
            for index,tag in enumerate(tags):
                group=actors(4,tag)
                for state in group:state['id']+=index*10
                states.extend(group)
            plans,outcomes,usage=self.assign(catalog,states)
            self.assertEqual(24,sum(p is not None for p in plans.values()))
            self.assertEqual({(t,'lane_0',c):3 for t in (1,2) for c in tags},usage)
            for team in (1,2):
                for index,tag in enumerate(tags):
                    self.assertIsNone(plans[team*100+index*10+3])
                    self.assertTrue(all(plans[team*100+index*10+j] is not None for j in range(3)))

    def test_disabled_classes_and_spg_do_not_consume_front_lane_capacity(self):
        catalog=lanes(1)
        for team in (1,2):
            catalog[team]=catalog[team][:1]
            catalog[team][0]['class_weights']['SPG']=1
        states=actors(1)+actors(1,'SPG')
        for state in states[2:]:state['id']+=10
        plans,unused,usage=self.assign(catalog,states)
        self.assertTrue(all(p is not None for p in plans.values()))
        catalog[1][0]['_editor_disabled_classes']=['lightTank']
        self.assertIsNone(self.assign(catalog,actors(1))[0][100])

    def test_random_global_state_and_input_are_not_mutated(self):
        catalog=lanes();saved=copy.deepcopy(catalog);before=random.getstate()
        self.assertEqual(self.assign(catalog),self.assign(catalog))
        self.assertEqual(before,random.getstate());self.assertEqual(saved,catalog)

    def test_missing_class_uses_auto_without_treating_base_as_variant(self):
        states=actors(1)
        for state in states:state['profile']={}
        plans,unused,unused_usage=self.assign(states=states)
        self.assertTrue(all(p is None for p in plans.values()))

    def test_sparse_deletion_mask_does_not_disable_other_vehicle_classes(self):
        catalog=lanes(5)
        for team in (1,2):
            catalog[team]=catalog[team][:1]
            catalog[team][0]['class_weights']={'heavyTank':0.0}
            catalog[team][0]['_editor_disabled_classes']=['heavyTank']
        plans,unused,usage=self.assign(catalog,actors(2,'mediumTank'))
        self.assertTrue(all(route is not None for route in plans.values()))
        self.assertEqual({(t,'lane_0','mediumTank'):2 for t in (1,2)},usage)
        self.assertTrue(all(route is None for route in self.assign(catalog,actors(1,'heavyTank'))[0].values()))

    def test_custom_symmetric_mirror_identity_and_capacity(self):
        raw=profile();graph=_graph();states=_states(graph,3)
        route=raw['maps']['08_ruinberg']['routes'][0]
        route.update(classes=['lightTank'],capacity=2,symmetric=True,mirror_id='east')
        peer=copy.deepcopy(route);peer.update(id='east',team=2,mirror_id='west')
        peer['points']=list(reversed(peer['points']))
        raw['maps']['08_ruinberg']['routes'].append(peer)
        for state in states:state['profile']['class_tag']='lightTank'
        with mock.patch.object(planning,'_route_reachable',return_value=True):
            plans,outcomes,usage=planning.assign_initial_routes(raw,'08_ruinberg',graph,states,{},99)
        self.assertEqual('user_west',plans[10]['id']);self.assertEqual('user_east',plans[20]['id'])
        self.assertIsNone(plans[12]);self.assertIsNone(plans[22])
        self.assertEqual('full_or_unusable_routes_auto',outcomes[12])

    def test_custom_unreachable_route_is_never_admitted(self):
        raw=profile();graph=_graph();states=_states(graph,1)
        for state in states:state['profile']['class_tag']='heavyTank'
        with mock.patch.object(planning,'_route_reachable',return_value=False):
            plans,unused,unused_usage=planning.assign_initial_routes(raw,'08_ruinberg',graph,states,{},3)
        self.assertTrue(all(p is None for p in plans.values()))

    def test_real_maps_class_routes_capacity_and_default_symmetry_metadata(self):
        for name in ('13_erlenberg','31_airfield','08_ruinberg','04_himmelsdorf'):
            with self.subTest(map=name):
                graph=_graph(name);routes,unused=planning.default_routes(cfg.empty(),name,graph)
                states=_states(graph,6)
                for state in states:state['profile']['class_tag']='mediumTank'
                plans,outcomes,usage=planning.assign_initial_routes(cfg.empty(),name,graph,states,routes,83)
                for (team,identity,tag),count in usage.items():
                    route=next(r for r in routes[str(team)] if r['id']==identity)
                    self.assertLessEqual(count,3)
                for slot in range(6):
                    a,b=plans[10+slot],plans[20+slot]
                    if a and b and a.get('_allocation_symmetric') and b.get('_allocation_symmetric'):
                        self.assertEqual(a['id'],b['id'])


class ParkingLotteryTests(unittest.TestCase):
    def test_deleted_default_positions_roundtrip_and_do_not_reappear(self):
        import bot_tactics_store as store
        graph=_graph();raw=profile();entry=raw['maps']['08_ruinberg']
        defaults=store.default_spg_positions('08_ruinberg',graph,raw)
        deleted=[p['id'] for p in defaults if p['team']==1]
        entry['deleted_positions']=deleted
        canonical=cfg.canonical(raw)
        self.assertEqual(sorted(deleted),canonical['maps']['08_ruinberg']['deleted_positions'])
        self.assertEqual(canonical,cfg.canonical(json.loads(cfg.dumps(canonical))))
        self.assertEqual([], [p for p in store.default_spg_positions('08_ruinberg',graph,canonical) if p['team']==1])
        plans,unused=spg_positions.assign_initial_positions('08_ruinberg',graph,_states(graph,1),
                                             allocation_seed=7,deleted_positions=deleted)
        self.assertNotIn(10,plans);self.assertIn(20,plans)

    def test_deleting_last_baked_parking_leaves_no_authored_spg_route(self):
        raw=cfg.empty();graph=_graph('31_airfield')
        routes,unused=planning.default_routes(raw,'31_airfield',graph)
        raw['maps']['31_airfield']=dict(deleted_positions=['spg_1_'+r['id'] for r in routes['1']])
        plans,unused,unused_usage=planning.assign_initial_routes(raw,'31_airfield',graph,_states(graph,1),routes,4)
        self.assertIsNone(plans[10]);self.assertIsNotNone(plans[20])

    def test_default_parking_shared_family_draws_use_each_sides_own_points(self):
        raw=profile();graph=_graph();entry=raw['maps']['08_ruinberg'];entry['positions']=[]
        for team in (1,2):
            for family,x in (('lane_0',-106.),('lane_1',-78.)):
                entry['positions'].append(dict(id='spg_%d_%s'%(team,family),label=family,team=team,
                    point=[x,346. if team==1 else -346.],radius=34,heading=0,priority=5))
        catalog=lanes();states=_states(graph,1)
        for seed in range(15):
            plans,unused=planning.assign_manual_positions(raw,'08_ruinberg',graph,states,
                allocation_seed=seed,paired_routes=catalog)
            self.assertEqual(plans[10]['zone'][6:],plans[20]['zone'][6:])
            self.assertNotEqual(plans[10]['point'],plans[20]['point'])

    def test_zone_tickets_are_not_multiplied_by_candidate_cells(self):
        a=(5,'a',False,'a');b=(5,'b',False,'b')
        for seed in range(30):
            self.assertEqual(lottery.choose(seed,'spg','SPG',0,[a,b],1),
                             lottery.choose(seed,'spg','SPG',0,[a]*100+[b],1))

    def test_manual_priorities_safe_reservations_and_relocation_override(self):
        raw=profile();graph=_graph();states=_states(graph,3)
        zone=copy.deepcopy(raw['maps']['08_ruinberg']['positions'][0])
        zone.update(id='alternative',point=[-78.,346.],priority=8)
        raw['maps']['08_ruinberg']['positions'].append(zone)
        selections=[]
        for seed in range(20):
            plans,unused=planning.assign_manual_positions(raw,'08_ruinberg',graph,states,
                                                        allocation_seed=seed)
            selections.append(plans[10]['zone'])
            for team in (1,2):
                side=[p for p in plans.values() if p['side']=='team%d'%team]
                for i,a in enumerate(side):
                    for b in side[i+1:]:
                        distance=((a['point']['x']-b['point']['x'])**2+(a['point']['z']-b['point']['z'])**2)**.5
                        self.assertGreaterEqual(distance,a['clearance']+b['clearance']+3)
        self.assertEqual({'north','alternative'},set(selections))
        zone['priority']=1;raw['maps']['08_ruinberg']['positions'][-1]=zone
        for seed in range(5):
            plans,unused=planning.assign_manual_positions(raw,'08_ruinberg',graph,states[:1],allocation_seed=seed)
            self.assertEqual('north',plans[10]['zone'])
        plans,unused=planning.assign_manual_positions(raw,'08_ruinberg',graph,states[:1],
                          preferred_zone='alternative',allocation_seed=9)
        self.assertEqual('alternative',plans[10]['zone'])

    def test_full_manual_positions_have_no_plan_to_queue_at(self):
        raw=profile();graph=_graph();states=_states(graph,1)
        with mock.patch.object(spg_positions,'parking_point_available',return_value=False):
            plans,outcomes=planning.assign_manual_positions(raw,'08_ruinberg',graph,states,allocation_seed=0)
        self.assertEqual({},plans)
        self.assertEqual({'manual_no_reachable_parking_space'},set(outcomes.values()))

    def test_stock_source_catalog_preserves_validity_and_three_spg_limit(self):
        for name in ('08_ruinberg','35_steppes'):
            graph=_graph(name);states=_states(graph,4)
            before=random.getstate()
            plans,outcomes=spg_positions.assign_initial_positions(name,graph,states,allocation_seed=52)
            self.assertEqual(before,random.getstate())
            self.assertTrue(plans)
            for actor,plan in plans.items():
                state=next(s for s in states if s['id']==actor)
                self.assertIsNotNone(spg_positions.canonical_plan(plan,name,state['vehicle'],team=state['team']))
            self.assertEqual('outside_three_spg_initial_capacity',outcomes[13])
            self.assertEqual('outside_three_spg_initial_capacity',outcomes[23])


class RuntimeLotteryTests(unittest.TestCase):
    setUp = editor_tests.RealRuntimeIntegrationTests.setUp
    tearDown = editor_tests.RealRuntimeIntegrationTests.tearDown
    runtime = editor_tests.RealRuntimeIntegrationTests.runtime
    message = editor_tests.RealRuntimeIntegrationTests.message

    def test_fresh_round_draw_is_shared_with_both_spg_allocators_and_handoff_does_not_draw(self):
        rt=self.runtime();message=self.message()
        implementation=self.module.bot_tactics_runtime.assign_manual_positions
        source_impl=self.module.spg_positions.assign_initial_positions
        with mock.patch.object(self.module.random,'SystemRandom') as entropy, \
                mock.patch.object(self.module.bot_tactics_runtime,'assign_manual_positions',wraps=implementation) as manual, \
                mock.patch.object(self.module.spg_positions,'assign_initial_positions',wraps=source_impl) as source, \
                contextlib.redirect_stdout(io.StringIO()):
            entropy.return_value.getrandbits.return_value=178
            published=rt.battle_start(message)[0]
            self.assertEqual(178,manual.call_args.kwargs['allocation_seed'])
            self.assertEqual(178,source.call_args.kwargs['allocation_seed'])
            restored=dict(message,bot_manifest=published['bots'])
            rt._prepare_user_routes(restored,True)
            rt._prepare_initial_spg_positions(restored,True)
            entropy.return_value.getrandbits.assert_called_once_with(64)
            self.assertEqual(1,manual.call_count);self.assertEqual(1,source.call_count)
            rt._prepare_user_routes(message,False)
            self.assertEqual(2,entropy.return_value.getrandbits.call_count)

    def test_handoff_preserves_empty_route_and_exact_published_geometry(self):
        rt=self.runtime();message=self.message()
        with contextlib.redirect_stdout(io.StringIO()):
            published=rt.battle_start(message)[0]
            heavy=next(b for b in published['bots'] if b['id']==12)
            heavy['route']['waypoints'][0]['x']+=2
            expected=heavy['route']['waypoints'][0]['x']
            rt._prepare_user_routes(dict(message,bot_manifest=published['bots']),True)
            self.assertEqual(expected,rt.states[12]['route']['waypoints'][0][0])
            heavy['route']['waypoints']=[]
            rt._prepare_user_routes(dict(message,bot_manifest=published['bots']),True)
            self.assertIsNone(rt.states[12]['route'])
            self.assertIsNone(rt.adapter.director.agents[12]['route'])
            self.assertEqual([],rt._manifest_entry(rt.states[12])['route']['waypoints'])
