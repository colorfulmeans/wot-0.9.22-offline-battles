"""Timed and permanent authored waypoint orders through the real server."""
import copy
import unittest

from test_port_0922_bot_tactics_editor import cfg, planning, profile
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state, _bot_contact
from gui.mods.offline_lan_0922.ai.planner import build_vehicle_profile


class AuthoredRouteWaitTests(unittest.TestCase):
    def test_finished_wait_restores_combat_then_resumes_authored_route(self):
        planner,manifest=self.setup_route('AT-SPG',5)
        route=planner.tactics['maps']['08_ruinberg']['routes'][0]
        route['points'][1]=[300,0,0]
        planner.tactics=cfg.canonical(planner.tactics)
        wire=planning.route_value(route)
        manifest[0]['route']=_route(wire['id'],wire['waypoints'])
        manifest.append(_bot(7,2,0,_route('enemy',[(150,0,0),(300,0,0)]),'mediumTank'))
        own=_state(11,1,0,0);enemy=_state(7,2,150,0)
        contact=_bot_contact(7,150,0,[11])
        def order(now):
            planner.report_contacts([contact],planner.known_targets([own,enemy],[]),now)
            return next(row for row in planner.build_orders(
                manifest,[own,enemy],[],now)['orders'] if row['id']==11)
        self.assertEqual('hold',order(1)['combat_mode'])
        released=order(6)
        self.assertEqual(1,released['route_index'])
        self.assertIsNone(released.get('parking_phase'))
        self.assertEqual('engage',released['combat_mode'])
        self.assertEqual(7,released['target_id'])
        self.assertTrue(released['fire_allowed'])
        self.assertEqual(0.,released['throttle_override'])
        self.assertEqual(0.,released['move_position']['x'])
        # Combat does not reset the completed parking timer or erase the
        # next waypoint. Loss of the firing target resumes the same route.
        contact.update(visible=False,time_left=0.)
        resumed=order(7)
        self.assertEqual('route',resumed['combat_mode'])
        self.assertEqual(1,resumed['route_index'])
        self.assertEqual(300.,resumed['move_position']['x'])
        self.assertIsNone(resumed['throttle_override'])
        self.assertFalse(resumed['fire_allowed'])

    def test_armoured_td_wait_can_fire_at_reported_el_halluf_distance(self):
        # Tortoise's relative target position in report 20261005-200028.
        # Build the production profile rather than hiding its range reduction
        # behind the server fixture's generic 520 m profile.
        planner, manifest = self.setup_route('AT-SPG', 60)
        manifest[0]['profile'] = build_vehicle_profile(dict(
            type=dict(name='Tortoise', tags=('AT-SPG',)),
            physics=dict(speedLimits=(5.56, 2.78)),
            hull=dict(primaryArmor=228.6), turret=dict(primaryArmor=0.),
            gun=dict(shots=())))
        self.assertEqual(115., manifest[0]['profile']['desired_range'])
        contact=_bot_contact(7,308.966,136.48,[11])
        manifest.append(_bot(7,2,0,_route('enemy',[(0,0,0),(100,0,0)]),'mediumTank'))
        enemy=_state(7,2,308.966,136.48)
        state=_state(11, 1, 0, 0)
        def order(now):
            planner.report_contacts([contact],planner.known_targets([state,enemy],[]),now)
            return next(row for row in planner.build_orders(
                manifest, [state,enemy], [], now)['orders'] if row['id']==11)
        waiting=order(1)
        self.assertEqual('hold', waiting['combat_mode'])
        self.assertEqual(0., waiting['throttle_override'])
        self.assertEqual(7, waiting['target_id'])
        self.assertTrue(waiting['fire_allowed'])
        self.assertEqual(450., manifest[0]['profile']['fire_range'])
        self.assertEqual(450., waiting['fire_range'])
        # This profile correction neither bypasses lane/readiness gates nor
        # turns the existing TD envelope into unlimited firing reach.
        contact['shootable_by_bot_ids']=[]
        self.assertFalse(order(2)['fire_allowed'])
        contact['shootable_by_bot_ids']=[11]
        state['reload_time']=5.
        self.assertFalse(order(3)['fire_allowed'])
        state['reload_time']=0.
        contact.update(x=490., z=0.)
        enemy.update(x=490., z=0.)
        self.assertFalse(order(4)['fire_allowed'])

    def test_el_halluf_tortoise_reinforcement_joins_without_returning_to_base(self):
        planner=BotPlanner()
        south=dict(id='south_valley',team=2,class_tag='AT-SPG',points=[
            [-338,-322,0],[-250.9676,-285.2171,0],
            [-166.1757,-261.7527,1,0,[[-166.0415,-267.8015,60]]],
            [-12.0186,-147.7669,0],[302,318,0]])
        north=dict(id='north_ridge',team=2,class_tag='AT-SPG',points=[
            [-338,-322,0],[-346,-254,0],[-410,-158,0],[-450,-58,0],
            [-427.1585,268.6057,1,0,[[-414.2972,251.824,60]]],[302,318,0]])
        raw=cfg.empty()
        raw['maps']['29_el_hallouf']=dict(mode='regular',
            resource_sha256=cfg.MAPS['29_el_hallouf']['resource_sha256'],
            default_routes=[south,north],routes=[],positions=[])
        planner.tactics=cfg.canonical(raw);planner.tactics_map='29_el_hallouf'
        def wire(edit):
            return _route(cfg.default_route_id(edit),[(round(p[0],3),round(p[1],3),p[2]) for p in edit['points']])
        bot=_bot(24,2,8,wire(south),'AT-SPG')
        bot['state']=_state(24,2,-338,-322)
        self.assertEqual(1,planner._route(bot,1)[1])
        bot['state'].update(x=-166.766416,z=-267.885747)
        self.assertEqual(2,planner._route(bot,10)[1])
        self.assertEqual('waiting',planner._route_states[24]['parking_phase'])
        self.assertEqual(3,planner._route(bot,70)[1])
        planner._route_assignments[24]=dict(route=wire(north),until=110.)
        planner._route_states.pop(24)
        joined=planner._route(bot,74)
        self.assertEqual(('class_td_north_ridge',1),joined[:2])
        self.assertEqual(-346,joined[2]['x'])
        planner._route_assignments[24]=dict(route=wire(south),until=0.)
        planner._route_states.pop(24)
        resumed=planner._route(bot,110)
        self.assertEqual(('class_td_south_valley',3),resumed[:2])
        self.assertNotIn('parking_phase',planner._route_states[24])
        self.assertEqual({2},planner._route_states[24]['parking_completed'])
        planner.reset(2)
        self.assertEqual({},planner._route_history)
        bot['state'].update(x=-338,z=-322)
        self.assertEqual(1,planner._route(bot,1)[1])

    def test_distant_known_enemy_cannot_pin_completed_withdrawal_forever(self):
        planner = BotPlanner()
        bot = _bot(11, 2, 0, _route('lane', [(0, 0, 0), (100, 0, 0)]), 'lightTank')
        bot['state'] = _state(11, 2, 0, 0)
        bot['profile']['fire_range'] = 320.0
        def order(now, enemy=400):
            value = dict(target_id=15, combat_mode='route',
                         move_position={'x':100,'y':0,'z':0}, throttle_override=None)
            return planner._apply_retreat_order(value, bot,
                {'x':0,'y':0,'z':0}, {'x':enemy,'y':0,'z':0}, now,
                'low_health_retreat', 'low_health_defend')
        self.assertEqual('low_health_retreat', order(0)['combat_mode'])
        self.assertEqual('route', order(15)['combat_mode'])
        self.assertEqual('route', order(16)['combat_mode'])
        self.assertEqual('low_health_retreat', order(17, 100)['combat_mode'])

    def test_unfinished_wait_does_not_count_time_spent_on_another_assignment(self):
        planner,manifest=self.setup_route('AT-SPG',30)
        bot=dict(manifest[0],state=_state(11,1,0,0))
        planner._route(bot,10)
        self.assertEqual(10,planner._route_states[11]['parking_arrived'][0])
        planner._route_states.pop(11)
        planner._route(bot,100)
        self.assertEqual('waiting',planner._route_states[11]['parking_phase'])
        self.assertEqual(100,planner._route_states[11]['parking_arrived'][0])
        planner._route(bot,130)
        self.assertEqual({0},planner._route_states[11]['parking_completed'])
        planner._prune_tactical_state([],{},131)
        self.assertEqual({},planner._route_history)

    def setup_route(self, class_tag='heavyTank', seconds=30):
        raw = profile()
        route = raw['maps']['08_ruinberg']['routes'][0]
        route.update(classes=[class_tag], points=[
            [0, 0, 1, seconds], [100, 0, 1, -1]])
        planner = BotPlanner()
        planner.tactics = cfg.canonical(raw)
        planner.tactics_map = '08_ruinberg'
        wire = planning.route_value(route)
        self.assertTrue(all(len(point) == 3 for point in wire['waypoints']))
        manifest = [_bot(11, 1, 0, _route(wire['id'], wire['waypoints']), class_tag)]
        return planner, manifest

    def order(self, planner, manifest, x, now):
        return planner.build_orders(
            manifest, [_state(11, 1, x, 0)], [], now)['orders'][0]

    def test_wait_starts_at_arrival_then_moves_to_permanent_hold(self):
        planner, manifest = self.setup_route()
        approaching = self.order(planner, manifest, -100, 1)
        self.assertEqual(0, approaching['route_index'])
        arrived = self.order(planner, manifest, 0, 10)
        self.assertEqual(('hold', 0.0), (
            arrived['combat_mode'], arrived['throttle_override']))
        self.assertEqual(0, self.order(planner, manifest, 0, 39.9)['route_index'])
        released = self.order(planner, manifest, 0, 40)
        self.assertEqual(1, released['route_index'])
        self.assertEqual(100, released['move_position']['x'])
        self.assertIsNone(released['throttle_override'])
        self.assertEqual('hold', self.order(planner, manifest, 100, 50)['combat_mode'])
        self.assertEqual('hold', self.order(planner, manifest, 100, 5000)['combat_mode'])

    def test_spg_follows_authored_route_instead_of_returning_to_initial_position(self):
        planner, manifest = self.setup_route('SPG', 5)
        self.order(planner, manifest, 0, 1)
        released = self.order(planner, manifest, 0, 6)
        self.assertEqual(('parking_approach', 100), (
            released['combat_mode'], released['move_position']['x']))
        self.assertIsNone(released['throttle_override'])

    def test_a_passed_corridor_cannot_skip_the_opening_parking_instruction(self):
        planner, manifest = self.setup_route()
        passed = self.order(planner, manifest, 50, 1)
        self.assertEqual(0, passed['route_index'])
        self.assertEqual(0, passed['move_position']['x'])
        self.assertIsNone(passed['throttle_override'])

    def test_condition_roundtrip_and_invalid_waits(self):
        raw = profile()
        raw['maps']['08_ruinberg']['routes'][0]['points'][0].append(12.5)
        self.assertEqual(raw, cfg.canonical(raw))
        for seconds in (float('nan'), float('inf'), -0.5, -2, 3601, True):
            changed = copy.deepcopy(raw)
            changed['maps']['08_ruinberg']['routes'][0]['points'][0][3] = seconds
            with self.subTest(seconds=seconds), self.assertRaises(cfg.TacticsError):
                cfg.canonical(changed)

    def test_default_scoped_route_waits_without_custom_route_prefix(self):
        planner,manifest=self.setup_route()
        route=planner.tactics['maps']['08_ruinberg']['routes'].pop()
        edit=dict(id=cfg.MAPS['08_ruinberg']['route_ids']['1'][0],team=1,
                  class_tag='heavyTank',points=route['points'])
        planner.tactics['maps']['08_ruinberg']['default_routes']=[edit]
        planner.tactics=cfg.canonical(planner.tactics)
        manifest[0]['route']['id']=cfg.default_route_id(edit)
        self.order(planner,manifest,0,10)
        self.assertEqual('hold',self.order(planner,manifest,0,39.9)['combat_mode'])
        self.assertEqual(1,self.order(planner,manifest,0,40)['route_index'])

    def test_rounded_manifest_keeps_scoped_default_waits(self):
        planner, manifest = self.setup_route('AT-SPG', 120)
        route = planner.tactics['maps']['08_ruinberg']['routes'].pop()
        route['points'] = [[0.1234, 0.2345, 1, 120], [100.5678, 0.3456, 0]]
        edit = dict(id=cfg.MAPS['08_ruinberg']['route_ids']['1'][0], team=1,
                    class_tag='AT-SPG', points=route['points'])
        planner.tactics['maps']['08_ruinberg']['default_routes'] = [edit]
        planner.tactics = cfg.canonical(planner.tactics)
        manifest[0]['route'] = _route(cfg.default_route_id(edit),
            [(round(p[0], 3), round(p[1], 3), p[2]) for p in edit['points']])
        self.assertEqual('hold', self.order(planner, manifest, 0, 10)['combat_mode'])
        self.assertEqual('hold', self.order(planner, manifest, 0, 129.9)['combat_mode'])
        self.assertEqual(1, self.order(planner, manifest, 0, 130)['route_index'])
        manifest[0]['route']['waypoints'][0]['x'] += 0.01
        self.assertIsNone(cfg.route_config(planner.tactics, '08_ruinberg',
            cfg.default_route_id(edit), 1, manifest[0]['route']['waypoints']))


if __name__ == '__main__':
    unittest.main()
