"""Independent waypoint parking leases through canonical server orders."""
import copy
import unittest
import test_port_0922_authored_route_waits as authored_waits
from test_port_0922_server_bot_ai import _bot, _state, _route
from test_port_0922_bot_tactics_editor import cfg
from gui.mods.offline_lan_0922.ai.driver import LocalDriver


class WaitParkingTests(unittest.TestCase):
    def test_map_check_reports_each_wait_slot_and_its_directed_exit(self):
        from gui.mods.offline_lan_0922 import bot_tactics_runtime as planning
        graph=dict(game_version=planning.spg_positions.CATALOG['game_version'],
            map='08_ruinberg',width=3,height=2,cell_size=4.,origin=[0,0],
            bounds=cfg.MAPS['08_ruinberg']['bounds'],heights_mm=[0,0,0,0,0,None],
            links=[5,1,0,0,0,0],hazards=[0]*6,
            directions=[[1,0],[1,1],[0,1],[-1,1],[-1,0],[-1,-1],[0,-1],[1,-1]])
        p,m=self.setup_parking([[0,4,10],[4,4,20],[8,4,30]])
        route=p.tactics['maps']['08_ruinberg']['routes'][0]
        route['points'][1]=[8,0,0]
        rows=planning.authoring_check(p.tactics,'08_ruinberg',graph,details=True)
        row=next(row for row in rows if row[0]==route['id'])
        self.assertEqual('wait_place_disconnected',row[1])
        self.assertEqual([(1,'wait_place_exit_disconnected'),
            (2,'wait_place_disconnected'),(2,'wait_place_exit_disconnected'),
            (3,'wait_place_unusable')],[(i['wait_slot'],i['status']) for i in row[2]])
        self.assertEqual([1,2],row[2][0]['nodes'])
        self.assertEqual([[0,4],[8,0]],row[2][0]['points'])
        # Admission remains unchanged; the additional directed exit is UI evidence.
        route['points'][0][4]=[[0,4,10]]
        row=next(row for row in planning.authoring_check(p.tactics,'08_ruinberg',graph,details=True)
                 if row[0]==route['id'])
        self.assertEqual('wait_place_exit_disconnected',row[1])
        self.assertIsNone(planning.validate_route(planning.graph_view('08_ruinberg',graph),route))

    def setup_parking(self, places=None):
        planner, manifest = authored_waits.AuthoredRouteWaitTests().setup_route('AT-SPG')
        route=planner.tactics['maps']['08_ruinberg']['routes'][0]
        route['points']=[[0,0,1,0,places if places is not None else [[0,0,10],[20,0,20],[40,0,30]]],[100,0,0]]
        planner.tactics=cfg.canonical(planner.tactics)
        wire=_route('user_'+route['id'],[(0,0,1),(100,0,0)])
        manifest=[_bot(i,1,i-11,copy.deepcopy(wire),'AT-SPG') for i in range(11,15)]
        return planner,manifest

    def orders(self, planner, manifest, states, now):
        return {o['id']:o for o in planner.build_orders(manifest,states,[],now)['orders']}

    def test_optional_heading_roundtrip_and_no_target_idle_order(self):
        p,m=self.setup_parking([[0,0,60,90]])
        order=self.orders(p,m[:1],[_state(11,1,0,0)],1)[11]
        self.assertEqual('waiting',order['parking_phase'])
        self.assertEqual(90,order['parking_heading'])
        self.assertAlmostEqual(20,order['face_position']['x'])
        self.assertAlmostEqual(0,order['face_position']['z'])
        self.assertEqual(0,order['throttle_override'])
        self.assertEqual(p.tactics,cfg.canonical(p.tactics))
        for bad in (181,float('nan'),float('inf'),True):
            raw=copy.deepcopy(p.tactics);raw['maps']['08_ruinberg']['routes'][0]['points'][0][4][0][3]=bad
            with self.assertRaises(cfg.TacticsError):cfg.canonical(raw)

    def test_auto_heading_is_next_gate_and_initial_preference_never_reasserts(self):
        p,m=self.setup_parking([[0,0,60]])
        states=[_state(11,1,0,0)]
        first=self.orders(p,m[:1],states,1)[11]
        self.assertEqual(90,first['parking_heading'])
        states[0]['yaw']=1.5707963267948966
        self.assertNotIn('parking_heading',self.orders(p,m[:1],states,2)[11])
        states[0]['yaw']=-1.5707963267948966
        self.assertNotIn('parking_heading',self.orders(p,m[:1],states,3)[11])
        self.assertEqual(0,self.orders(p,m[:1],states,3)[11]['throttle_override'])
        p,m=self.setup_parking([[0,0,60]])
        first=self.orders(p,m[:1],[_state(11,1,0,0)],1)[11]
        self.assertNotIn('parking_heading',self.orders(p,m[:1],[_state(11,1,0,0)],6)[11])

    def test_enemy_interrupts_initial_heading_and_final_gate_has_no_auto_heading(self):
        p,m=self.setup_parking([[0,0,60]])
        first=self.orders(p,m[:1],[_state(11,1,0,0)],1)[11]
        bot=p._alive_bots(m[:1],[_state(11,1,0,0)])[0]
        order=dict(first,target_id=7,face_position={'x':0,'y':0,'z':-100})
        order.pop('parking_heading',None)
        p._apply_authored_route_order(order,bot,{'x':0,'y':0,'z':0},2)
        self.assertNotIn('parking_heading',order)
        self.assertEqual(-100,order['face_position']['z'])
        self.assertNotIn('parking_heading',self.orders(p,m[:1],[_state(11,1,0,0)],3)[11])
        self.assertIsNone(cfg.waiting_heading([0,0,60],None))
        self.assertEqual(-90,cfg.waiting_heading([0,0,60],[-100,0,0]))
        self.assertEqual(180,cfg.waiting_heading([0,0,60,180],[100,0,0]))

    def test_idle_heading_never_overrides_live_target_facing(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        adapter=BotAdapter('08_ruinberg',1)
        state=dict(id=11,slot=0,team=1,yaw=0,speed=0,dt=.1)
        order=dict(parking_phase='waiting',parking_heading=90,combat_mode='hold',
                   move_position=(0,0,0),throttle_override=0)
        idle=adapter._drive_order(11,state,(0,0,0),order,lambda *args:True)
        self.assertAlmostEqual(1.5707963267948966,idle['target_yaw'])
        self.assertEqual(0,idle['throttle'])
        order.update(target_id=7,aim_position=(0,0,-100),face_position=(0,0,-100))
        attack=adapter._drive_order(11,state,(0,0,0),order,lambda *args:True)
        self.assertAlmostEqual(3.141592653589793,abs(attack['target_yaw']))
        self.assertEqual(0,attack['throttle'])

    def test_three_distinct_places_and_fourth_uses_parent_gate(self):
        p,m=self.setup_parking();states=[_state(i,1,-100-(i-11)*15,0) for i in range(11,15)]
        first=self.orders(p,m,states,1)
        self.assertEqual([0,20,40],[first[i]['move_position']['x'] for i in range(11,14)])
        self.assertNotIn('parking_phase',first[14])
        self.assertIsNone(first[14]['throttle_override'])
        self.assertEqual(0,first[14]['move_position']['x'])
        again=self.orders(p,m,list(reversed(states)),2)
        self.assertEqual([first[i]['move_position'] for i in range(11,15)],
                         [again[i]['move_position'] for i in range(11,15)])

    def test_one_metre_arrival_and_individual_clocks(self):
        p,m=self.setup_parking();m=m[:3]
        states=[_state(11,1,-1.01,0),_state(12,1,20,0),_state(13,1,40,0)]
        first=self.orders(p,m,states,10)
        self.assertEqual('approach',first[11]['parking_phase'])
        self.assertEqual(1,first[11]['arrival_radius'])
        self.assertEqual('waiting',first[12]['parking_phase'])
        self.assertEqual('waiting',first[13]['parking_phase'])
        states[0]['x']=-1
        self.assertEqual('waiting',self.orders(p,m,states,15)[11]['parking_phase'])
        self.assertEqual(0,self.orders(p,m,states,24.9)[11]['route_index'])
        at25=self.orders(p,m,states,25)
        self.assertEqual([1,0,0],[at25[i]['route_index'] for i in range(11,14)])
        at30=self.orders(p,m,states,30)
        self.assertEqual([1,1,0],[at30[i]['route_index'] for i in range(11,14)])
        self.assertEqual(1,self.orders(p,m,states,40)[13]['route_index'])

    def test_completed_hull_must_depart_before_slot_is_reused(self):
        p,m=self.setup_parking([[0,0,5]])
        states=[_state(11,1,0,0),_state(12,1,-40,0)]
        m=m[:2];self.orders(p,m,states,1)
        self.assertNotIn('parking_phase',self.orders(p,m,states,6)[12])
        self.assertNotIn('parking_phase',self.orders(p,m,states,7)[12])
        states[0]['x']=11
        m.append(dict(m[1],id=13,slot=2));states.append(_state(13,1,-80,0))
        self.assertEqual('approach',self.orders(p,m,states,8)[13]['parking_phase'])
        self.assertNotIn('parking_phase',self.orders(p,m,states,9)[12])

    def test_dead_owner_releases_lease_but_wreck_position_stays_occupied(self):
        p,m=self.setup_parking([[0,0,5]])
        states=[_state(11,1,0,0),_state(12,1,-40,0)]
        self.orders(p,m[:2],states,1);states[0]['alive']=False;states[0]['health']=0
        self.assertNotIn('parking_phase',self.orders(p,m[:2],states,2)[12])
        states[0]['x']=12
        states.append(_state(13,1,-80,0))
        self.assertEqual('approach',self.orders(p,m[:3],states,3)[13]['parking_phase'])
        p.reset();self.assertEqual({},p._wait_claims)

    def test_zero_small_slots_and_old_parent_duration_do_not_wait(self):
        p,m=self.setup_parking([])
        p.tactics['maps']['08_ruinberg']['routes'][0]['points'][0]=[0,0,1,120]
        states=[_state(11,1,-40,0)]
        order=self.orders(p,m[:1],states,1)[11]
        self.assertEqual(0,order['route_index'])
        self.assertEqual(0,order['move_position']['x'])
        self.assertNotIn('parking_phase',order)
        states[0]['x']=0
        self.assertEqual(1,self.orders(p,m[:1],states,2)[11]['route_index'])

    def test_full_parking_group_still_uses_blocked_parent_gate_timeout(self):
        p,m=self.setup_parking([[0,0,10]])
        states=[_state(11,1,-40,0)]
        states[0].update(world_pose=True,route_wreck_blocked=True)
        player=dict(_state(1,1,0,0),alive=False,health=0,world_pose=True)
        def order(now):
            return p.build_orders(m[:1],states,[player],now)['orders'][0]
        first=order(0)
        self.assertEqual(0,first['route_index'])
        self.assertEqual(0,first['move_position']['x'])
        self.assertNotIn('parking_phase',first)
        skipped=order(30)
        self.assertEqual(1,skipped['route_index'])
        self.assertEqual('blocked_timeout',skipped['route_point_skip_reason'])
        self.assertEqual(-40,skipped['route_anchor']['x'])

    def test_blocked_parking_approach_declines_slot_then_bounds_parent_gate(self):
        p,m=self.setup_parking([[0,20,120]])
        states=[dict(_state(11,1,-100,0),world_pose=True,route_wreck_blocked=True)]
        first=self.orders(p,m[:1],states,0)[11]
        self.assertEqual('parking_approach',first['combat_mode'])
        self.assertEqual(20,first['move_position']['z'])
        self.assertEqual('parking_approach',self.orders(p,m[:1],states,29.9)[11]['combat_mode'])
        declined=self.orders(p,m[:1],states,30)[11]
        self.assertEqual('blocked_approach_timeout',declined['parking_skip_reason'])
        self.assertEqual('route',declined['combat_mode'])
        self.assertIsNone(declined['parking_phase'])
        self.assertIsNone(declined['arrival_radius'])
        self.assertEqual(0,declined['move_position']['z'])
        self.assertFalse(any(c['bot_id']==11 for c in p._wait_claims.values()))
        # A vacated slot must not restart the failed parking approach.
        self.assertNotEqual('parking_approach',self.orders(p,m[:1],states,30)[11]['combat_mode'])
        skipped=self.orders(p,m[:1],states,60)[11]
        self.assertEqual(1,skipped['route_index'])
        self.assertEqual('blocked_timeout',skipped['route_point_skip_reason'])

    def test_arrived_wait_does_not_expire_from_old_blockage_evidence(self):
        p,m=self.setup_parking([[0,0,120]])
        states=[dict(_state(11,1,0,0),world_pose=True,route_wreck_blocked=True)]
        self.assertEqual('waiting',self.orders(p,m[:1],states,0)[11]['parking_phase'])
        held=self.orders(p,m[:1],states,30)[11]
        self.assertEqual('waiting',held['parking_phase'])
        self.assertEqual('hold',held['combat_mode'])
        self.assertNotIn('parking_skip_reason',held)

    def test_schema_rejects_four_slots_nonfinite_times_and_duplicate_positions(self):
        p,m=self.setup_parking();raw=p.tactics
        for slots in ([[0,0,1]]*4, [[0,0,float('nan')]], [[0,0,1],[0,0,2]]):
            changed=copy.deepcopy(raw);changed['maps']['08_ruinberg']['routes'][0]['points'][0][4]=slots
            with self.assertRaises(cfg.TacticsError):cfg.canonical(changed)

    def test_driver_does_not_claim_arrival_or_latch_brake_at_one_point_two_metres(self):
        driver=LocalDriver()
        result=driver.drive(11,0,(0,0,0),0,0,.1,(0,0,1.2),[],lambda *args:True,
            stopping_distance=0,arrival_radius=1)
        self.assertNotEqual('arrived',result['recovery_mode'])
        self.assertGreater(result['throttle'],0)


if __name__=='__main__':unittest.main()
