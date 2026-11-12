"""Timed and permanent authored waypoint orders through the real server.

These planner/driver cases preserve authored stops and candidate observations;
a lane report is not shared native combat admission or a launch certificate.
"""
import copy
import math
import unittest

from test_port_0922_bot_tactics_editor import cfg, planning, profile
from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state, _bot_contact
from gui.mods.offline_lan_0922.ai.planner import build_vehicle_profile
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim


class AuthoredRouteWaitTests(unittest.TestCase):
    def assert_candidate_hint(self, order, identity=7):
        self.assertEqual(dict(target_kind='bot', target_id=identity),
                         order['initial_target_hint'])
        self.assertIsNone(order['target_id'])
        self.assertIsNone(order['target_kind'])
        self.assertIsNone(order['aim_position'])
        self.assertFalse(order['fire_allowed'])

    def test_armoured_td_observes_distant_candidate_without_leaving_authored_stop(self):
        planner, manifest = self.setup_route('AT-SPG', 60)
        manifest[0]['profile'] = build_vehicle_profile(dict(
            type=dict(name='Tortoise', tags=('AT-SPG',)),
            physics=dict(speedLimits=(5.56, 2.78)),
            hull=dict(primaryArmor=(273.1, 152.4, 101.6)),
            turret=dict(primaryArmor=0.), gun=dict(shots=())))
        manifest.append(_bot(7, 2, 0,
            _route('enemy', [(400, 0, 0), (500, 0, 0)]), 'mediumTank'))
        own = _state(11, 1, 0, 0)
        enemy = _state(7, 2, 400, 0)
        contact = _bot_contact(7, 400, 0, [11])
        def order(now):
            planner.report_contacts([contact],
                planner.known_targets([own, enemy], []), now)
            return next(row for row in planner.build_orders(
                manifest, [own, enemy], [], now)['orders'] if row['id'] == 11)
        self.assertEqual('hold', order(1)['combat_mode'])
        waiting = order(2)
        self.assert_candidate_hint(waiting)
        self.assertEqual('waiting', waiting['parking_phase'])
        self.assertEqual(0., waiting['throttle_override'])
        self.assertEqual(0., waiting['move_position']['x'])
        candidate = waiting['tactical_evidence']['selection']['candidates'][0]
        self.assertEqual(400., candidate['position']['x'])
        self.assertTrue(candidate['local_lane'])
        command = BotAdapter('08_ruinberg', 1).decide_with_order(dict(
            id=11, slot=0, team=1, position=(0., 0., 0.), yaw=0.,
            speed=0., dt=.1, neighbours=[], half_width=1.5,
            half_length=3.5, pose_clear=lambda yaw: True), waiting,
            lambda *args: True)
        self.assertFalse(command['movement_intent'])
        inactive = combat_hull_aim(
            0., math.pi/2, -.3491, .3491, command['turn'],
            command['throttle'], command['recovery_mode'],
            has_target=waiting['target_id'] is not None,
            combat_mode=command['combat_mode'], movement_intent=False)
        self.assertEqual((command['turn'], command['throttle'], False), inactive)
        # Separate physical-law boundary: a genuinely accepted downstream
        # target may still lay the limited-traverse hull at this same stop.
        # Supplying has_target here does not claim macro/native admission.
        turn, throttle, active = combat_hull_aim(
            0., math.pi/2, -.3491, .3491, command['turn'],
            command['throttle'], command['recovery_mode'],
            has_target=True, combat_mode=command['combat_mode'], movement_intent=False)
        self.assertTrue(active)
        self.assertNotEqual(0., turn)
        self.assertEqual(0., throttle)
        # Losing the advisory lane changes observations, not the authored stop.
        contact['shootable_by_bot_ids'] = []
        blocked = order(3)
        self.assert_candidate_hint(blocked)
        self.assertEqual(waiting['move_position'], blocked['move_position'])
        self.assertEqual(0., blocked['throttle_override'])
        self.assertFalse(blocked['tactical_evidence']['selection']['candidates'][0]['local_lane'])

    def test_td_defense_response_estimate_is_the_same_during_travel_and_parking(self):
        planner, manifest = self.setup_route('AT-SPG', 60)
        bot = manifest[0]
        bot['profile'] = build_vehicle_profile(dict(
            type=dict(tags=('AT-SPG',)), physics=dict(speedLimits=(5.56, 2.78)),
            hull=dict(primaryArmor=273.1), turret=dict(primaryArmor=0.),
            gun=dict(shots=())))
        for phase in (None, 'approach', 'waiting', 'queue'):
            planner._route_states[11] = dict(parking_phase=phase)
            # This remaining estimate belongs to defense task allocation;
            # it is not a mounted-shell limit or an ordinary target filter.
            self.assertEqual(534., planner._engagement_range(bot, dict(visible=True)))
            self.assertAlmostEqual(399.3, planner._engagement_range(bot, dict(visible=False)))

    def test_td_armour_changes_no_sniper_roles_or_distance_policy(self):
        # Exercise both sides of the old threshold and hull/turret armour
        # sources at slow, ordinary, and fast descriptor speeds.
        for speed in (5.56, 10., 16.67):
            def profile_for(hull, turret):
                return build_vehicle_profile(dict(type=dict(tags=('AT-SPG',)),
                    physics=dict(speedLimits=(speed, 2.78)),
                    hull=dict(primaryArmor=hull), turret=dict(primaryArmor=turret),
                    gun=dict(shots=())))
            reference = profile_for(80., 0.)
            for hull, turret in ((119.9, 0.), (120., 0.),
                                 ((273.1, 152.4, 101.6), 0.), (80., 200.)):
                value = profile_for(hull, turret)
                self.assertEqual(reference['roles'], value['roles'])
                self.assertEqual('sniper', value['dominant_role'])
                self.assertEqual(255., value['desired_range'])
                self.assertEqual(450., value['fire_range'])
                self.assertGreaterEqual(value['armor'], 119.9)

    def test_turreted_classes_keep_their_existing_armour_preferences(self):
        for tag, preferred, fire in (('heavyTank',72.,260.),
                                     ('mediumTank',135.,340.),
                                     ('lightTank',175.,320.)):
            def profile_for(armor):
                return build_vehicle_profile(dict(type=dict(tags=(tag,)),
                    physics=dict(speedLimits=(10., 2.78)),
                    hull=dict(primaryArmor=armor), turret=dict(primaryArmor=0.),
                    gun=dict(shots=())))
            light = profile_for(80.)
            heavy = profile_for(200.)
            self.assertEqual((preferred, fire),
                (heavy['desired_range'], heavy['fire_range']))
            self.assertAlmostEqual(min(1., light['roles']['brawler'] + .18),
                                   heavy['roles']['brawler'])
            self.assertAlmostEqual(max(0., light['roles']['sniper'] - .08),
                                   heavy['roles']['sniper'])

    def test_finished_wait_resumes_authored_route_while_contact_remains_only_a_hint(self):
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
        self.assertEqual(1., planner._route_states[11]['parking_arrived'][0])
        self.assertEqual('hold', order(5.99)['combat_mode'])
        released=order(6)
        self.assertEqual(1,released['route_index'])
        self.assertIsNone(released.get('parking_phase'))
        self.assertEqual('route',released['combat_mode'])
        self.assert_candidate_hint(released)
        self.assertIsNone(released['throttle_override'])
        self.assertEqual(300.,released['move_position']['x'])
        self.assertIn(0, planner._route_states[11]['parking_completed'])
        # A contact cannot reset the completed parking timer or take over
        # the next waypoint. Losing that hint leaves the same route active.
        contact.update(visible=False,time_left=0.)
        resumed=order(7)
        self.assertEqual('route',resumed['combat_mode'])
        self.assertEqual(1,resumed['route_index'])
        self.assertEqual(300.,resumed['move_position']['x'])
        self.assertIsNone(resumed['throttle_override'])
        self.assertFalse(resumed['fire_allowed'])
        self.assertFalse(resumed.get('initial_target_hint'))

    def test_armoured_td_wait_retains_el_halluf_contacts_beyond_role_range_as_hints(self):
        # Tortoise's relative target position in report 20261005-200028.
        # Keep the real production role profile distinct from mounted-shell
        # range, which the shared native evaluator proves downstream.
        planner, manifest = self.setup_route('AT-SPG', 60)
        manifest[0]['profile'] = build_vehicle_profile(dict(
            type=dict(name='Tortoise', tags=('AT-SPG',)),
            physics=dict(speedLimits=(5.56, 2.78)),
            hull=dict(primaryArmor=228.6), turret=dict(primaryArmor=0.),
            gun=dict(shots=())))
        self.assertEqual(255., manifest[0]['profile']['desired_range'])
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
        self.assert_candidate_hint(waiting)
        self.assertEqual(450., manifest[0]['profile']['fire_range'])
        self.assertEqual(450., waiting['fire_range'])
        # Lane and weapon readiness remain observations for native review,
        # never macro fire permission or a veto from the role's range.
        contact['shootable_by_bot_ids']=[]
        blocked = order(2)
        self.assert_candidate_hint(blocked)
        self.assertFalse(blocked['tactical_evidence']['selection']['candidates'][0]['local_lane'])
        contact['shootable_by_bot_ids']=[11]
        state['reload_time']=5.
        loading = order(3)
        self.assert_candidate_hint(loading)
        self.assertFalse(loading['tactical_evidence']['weapon_ready'])
        state['reload_time']=0.
        contact.update(x=490., z=0.)
        enemy.update(x=490., z=0.)
        farther=order(4)
        self.assert_candidate_hint(farther)
        candidate = farther['tactical_evidence']['selection']['candidates'][0]
        self.assertEqual(490., candidate['position']['x'])
        self.assertEqual('eligible', candidate['reason'])
        self.assertTrue(farther['tactical_evidence']['weapon_ready'])
        self.assertEqual('hold',farther['combat_mode'])
        self.assertEqual('waiting',farther['parking_phase'])
        self.assertEqual(waiting['route_index'],farther['route_index'])
        self.assertEqual(waiting['move_position'],farther['move_position'])
        self.assertEqual(0.,farther['throttle_override'])

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

    def test_low_health_does_not_create_a_retreat_or_expiry_on_authored_route(self):
        planner = BotPlanner()
        bot = _bot(11, 2, 0, _route('lane', [(0, 0, 0), (100, 0, 0)]), 'lightTank')
        bot['state'] = _state(11, 2, 0, 0)
        bot['state'].update(health=10, max_health=1000)
        bot['profile']['fire_range'] = 320.0
        focus = dict(id=15, target_kind='bot', visible=True,
                     shootable_by_bot_ids=[11], position=dict(x=400., y=0., z=0.))
        self.assertFalse(hasattr(planner, '_apply_retreat_order'))
        for now in (0., 15., 16., 17., 60.):
            order = planner._order_for(bot, 0, 1, focus, [focus], now)
            self.assertEqual('route', order['combat_mode'])
            self.assertEqual('lane', order['route_id'])
            self.assertEqual(1, order['route_index'])
            self.assertEqual(dict(x=100., y=0., z=0.), order['_route_position'])
            self.assertEqual(dict(x=100., y=0., z=0.), order['move_position'])
            self.assertIsNone(order['throttle_override'])
            self.assert_candidate_hint(order, 15)
            self.assertNotIn('withdraw_after_hit', order['tactical_evidence'])
            self.assertFalse(hasattr(planner, '_retreat_states'))
        # Low health and an initial contact cannot expire the authored route
        # or replace it with a combat stop, approach or tactical retreat.
        resumed = planner._order_for(bot, 0, 1, None, [], 61.)
        self.assertEqual('route', resumed['combat_mode'])
        self.assertEqual('lane', resumed['route_id'])
        self.assertEqual(1, resumed['route_index'])
        self.assertEqual(dict(x=100., y=0., z=0.), resumed['move_position'])
        self.assertIsNone(resumed['target_id'])
        self.assertIsNone(resumed['throttle_override'])
        self.assertFalse(resumed['fire_allowed'])

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
            [0, 0, 1, 0, [[0, 0, seconds]]], [100, 0, 1, 0, [[100, 0, -1]]]])
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
        self.assertEqual(cfg.canonical(profile()), cfg.canonical(raw))
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
        route['points'] = [[0.1234, 0.2345, 1, 0, [[0.1234, 0.2345, 120]]], [100.5678, 0.3456, 0]]
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
