"""The confirmed tactical deletions cannot reappear through old entry points.

These tests define the replacement contract: valid local shots stay owned by
aim/fire; only actual range or lane failure changes combat movement. Physical
route recovery and the separately owned eight-second penetration policy are
not reimplemented here.
"""
import random
import unittest

from test_port_0922_server_bot_ai import (
    BotPlanner, _bot, _contact, _profile, _route, _state,
)
from gui.mods.offline_lan_0922.ai.planner import (
    BattleDirector, make_personality,
)


class RetiredTacticalEntryPointTests(unittest.TestCase):
    def test_server_deleted_strategy_methods_and_storage_stay_absent(self):
        planner = BotPlanner()
        retired = (
            'report_affordances', '_affordances', '_cover_states',
            '_cover_failures', '_cover_reservations', '_cover_candidate',
            '_begin_cover_phase', '_cover_phase_timed_out',
            '_reject_cover_candidate', '_apply_cover_order',
            '_retreat_states', '_apply_retreat_order', '_retreat_point',
            '_crossfire_risk', '_mark_flank_suppressors', '_flank_shooters',
            '_should_flank', '_flank_point', '_stable_range_mode',
            '_combat_states', '_ally_support_score', '_firing_holds',
            '_release_unproductive_firing_hold',
        )
        for action in (lambda: None, lambda: planner.reset(2),
                       planner.clear_observations):
            action()
            for name in retired:
                with self.subTest(name=name):
                    self.assertFalse(hasattr(planner, name))

    def test_local_director_has_no_withdraw_flank_or_force_balance_helpers(self):
        director = BattleDirector('04_himmelsdorf', 'retired-tactics')
        for name in ('_fallback_position', '_flank_position',
                     '_local_force_balance'):
            self.assertFalse(hasattr(director, name), name)

    def test_removing_jiggle_does_not_reshuffle_authored_route_allocations(self):
        for seed in range(30):
            traits = make_personality(seed)
            self.assertNotIn('jiggle', traits)
            self.assertNotIn('hold_jitter', traits)
            # The existing allocation draw followed seven trait draws.
            # Deleting a combat trait must not change unrelated route choice.
            rng = random.Random(seed)
            for unused in range(7):
                rng.random()
            self.assertEqual(rng.uniform(-4.0, 4.0), traits['route_jitter'])


class CurrentShootingPositionTests(unittest.TestCase):
    def test_server_holds_across_health_range_personality_and_magazine_states(self):
        route = _route('authored', [(45, -240, False), (45, 300, False)])
        for class_tag in ('lightTank', 'mediumTank', 'heavyTank', 'AT-SPG'):
            for health in (1000, 200, 1):
                for distance in (3.0, 150.0, 410.0):
                    for clip, reload_time, ready in ((3, 0.0, True),
                                                      (2, 0.8, False),
                                                      (0, 20.0, False)):
                        with self.subTest(class_tag=class_tag, health=health,
                                          distance=distance, clip=clip):
                            planner = BotPlanner()
                            bot = _bot(11, 1, 0, route, class_tag,
                                       {'flanker': 1.0, 'support': 1.0})
                            bot['profile'].update(desired_range=180.0,
                                                  fire_range=450.0)
                            state = _state(11, 1, 45.0, -180.0)
                            state.update(health=health, clip=clip, clip_size=3,
                                         reload_time=reload_time,
                                         ammo_reload_pending=not ready)
                            bot['state'] = state
                            focus = dict(target_kind='human', id=2,
                                position=dict(x=45.0, y=0.0, z=-180.0+distance),
                                visible=True, shootable_by_bot_ids=[11],
                                health=1000, max_health=1000)
                            order = planner._order_for(
                                bot, 0, 1, focus, [focus], 1.0)
                            self.assertEqual('engage', order['combat_mode'])
                            self.assertEqual(dict(x=45.0, y=0.0, z=-180.0),
                                             order['move_position'])
                            self.assertEqual(0.0, order['throttle_override'])
                            self.assertEqual(2, order['target_id'])
                            self.assertEqual(ready, order['fire_allowed'])

    def test_local_director_stays_when_outnumbered_damaged_or_too_close(self):
        profile = _profile('mediumTank', {'flanker': 1.0, 'support': 1.0})
        profile.update(desired_range=180.0, fire_range=450.0)
        for health in (1000, 200, 1):
            for distance in (3.0, 150.0, 410.0):
                with self.subTest(health=health, distance=distance):
                    director = BattleDirector('04_himmelsdorf', 45)
                    agent = director.register_profile(11, 1, profile, 'Bot')
                    agent['personality'].update(caution=0.95, aggression=0.05,
                                                initiative=0.95)
                    position = (45.0, 0.0, -180.0)
                    for target_id in (2, 3, 4, 5):
                        director.update_contact(1, target_id, 2,
                            (45.0+target_id-2, 0.0, -180.0+distance),
                            1000, 1000, 'mediumTank', True, 1.0)
                    order = director.order_for(
                        11, position, 0.0, 0.0, health, 1000, 1.0)
                    self.assertEqual('engage', order['combat_mode'])
                    self.assertEqual(position, order['move_position'])
                    self.assertEqual(0.0, order['throttle_override'])
                    self.assertTrue(order['fire_allowed'])
                    self.assertNotIn('force_balance', order)

    def test_actual_range_limit_still_requires_approach(self):
        route = _route('authored', [(45, -240, False), (45, 300, False)])
        bot = _bot(11, 1, 0, route, 'mediumTank')
        bot['profile'].update(desired_range=180.0, fire_range=340.0)
        state = _state(11, 1, 45.0, -180.0)
        bot['state'] = state
        # 355 m is outside the 340 m gun range, but inside the unchanged
        # local director's 360 m contact-selection envelope for this profile.
        focus = dict(target_kind='human', id=2,
            position=dict(x=45.0, y=0.0, z=175.0), visible=True,
            shootable_by_bot_ids=[11], health=1000, max_health=1000)
        server_order = BotPlanner()._order_for(bot, 0, 1, focus, [focus], 1.0)
        self.assertEqual('advance', server_order['combat_mode'])
        self.assertEqual(dict(x=45.0, y=0.0, z=300.0),
                         server_order['move_position'])
        self.assertFalse(server_order['fire_allowed'])
        self.assertEqual(1.0, server_order['throttle_override'])
        director = BattleDirector('04_himmelsdorf', 45)
        director.register_profile(11, 1, bot['profile'], 'Bot')
        director.update_contact(1, 2, 2, (45.0, 0.0, 175.0),
                                1000, 1000, 'mediumTank', True, 1.0)
        local_order = director.order_for(
            11, (45.0, 0.0, -180.0), 0.0, 0.0, 1000, 1000, 1.0)
        self.assertEqual('advance', local_order['combat_mode'])
        self.assertFalse(local_order['fire_allowed'])

    def test_current_blocked_lane_still_hands_off_to_position_recovery(self):
        route = _route('authored', [(0, -100, False), (0, 500, False)])
        bot = _bot(11, 1, 0, route, 'mediumTank')
        state = _state(11, 1, 0.0, 0.0)
        player = dict(id=2, team=2, alive=True)
        planner = BotPlanner()
        clear = _contact(2, 0.0, 150.0, [11])
        planner.report_contacts([clear], planner.known_targets([state], [player]), 1.0)
        first = planner.build_orders([bot], [state], [player], 1.0)['orders'][0]
        self.assertTrue(first['fire_allowed'])
        blocked = _contact(2, 0.0, 150.0, [])
        planner.report_contacts([blocked], planner.known_targets([state], [player]), 1.5)
        order = planner.build_orders([bot], [state], [player], 1.5)['orders'][0]
        self.assertEqual('advance_contact', order['combat_mode'])
        self.assertEqual(2, order['target_id'])
        self.assertEqual(first['aim_position'], order['move_position'])
        self.assertFalse(order['fire_allowed'])
        self.assertEqual('stationary_lane_lost',
                         order['tactical_evidence']['blocked_hold_handoff']['reason'])


class NoSyntheticRouteFallbackTests(unittest.TestCase):
    def test_missing_route_never_invents_old_three_lane_coordinates(self):
        for team in (1, 2):
            for actor in (11, 12, 13):
                for x, y, z in ((270.0, 7.0, -350.0), (-210.0, 3.0, 240.0)):
                    with self.subTest(team=team, actor=actor, position=(x, y, z)):
                        planner = BotPlanner()
                        bot = _bot(actor, team, actor, {}, 'mediumTank')
                        state = _state(actor, team, x, z)
                        state['y'] = y
                        bot['state'] = state
                        route_id, index, move, anchor, join = planner._route(bot, 1.0)
                        self.assertEqual('', route_id)
                        self.assertEqual(0, index)
                        self.assertEqual(dict(x=x, y=y, z=z), move)
                        self.assertEqual(move, anchor)
                        self.assertFalse(join)
                        self.assertNotIn(actor, planner._route_states)
                        order = planner.build_orders([bot], [state], [], 1.0)['orders'][0]
                        self.assertEqual(move, order['move_position'])
                        self.assertEqual('', order['route_id'])

    def test_missing_route_does_not_remove_explicit_base_task(self):
        planner = BotPlanner()
        bot = _bot(11, 1, 0, {}, 'mediumTank')
        bot['state'] = _state(11, 1, 270.0, -350.0)
        base = dict(id='home', base_id='home', point=dict(x=300.0, y=2.0, z=-450.0))
        task = planner._task_begin(bot, 'guard', base, now=1.0)
        self.assertEqual([base['point']], task['points'])
        self.assertEqual(base['point'], planner._route(bot, 1.0)[2])

    def test_missing_route_keeps_real_out_of_range_contact_navigation(self):
        planner = BotPlanner()
        bot = _bot(11, 1, 0, {}, 'mediumTank')
        bot['profile'].update(desired_range=180.0, fire_range=340.0)
        bot['state'] = _state(11, 1, 270.0, -350.0)
        focus = dict(target_kind='human', id=2,
            position=dict(x=270.0, y=0.0, z=40.0), visible=True,
            shootable_by_bot_ids=[11], health=1000, max_health=1000)
        order = planner._order_for(bot, 0, 1, focus, [focus], 1.0)
        self.assertEqual('advance_contact', order['combat_mode'])
        self.assertEqual(focus['position'], order['move_position'])
        self.assertFalse(order['fire_allowed'])


if __name__ == '__main__':
    unittest.main()
