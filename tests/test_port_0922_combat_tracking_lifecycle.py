"""Tracking, launch admission and magazine retreat have separate lifetimes."""
import unittest
import test_port_0922_server_bot_ai as fixtures

from test_port_0922_server_bot_ai import (
    BotPlanner, _contact, _weapon_state)


class CombatTrackingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.ServerBotTacticsTests()
        self.fx.setUp()
        self.planner = BotPlanner()
        self.contact = _contact(2, 0, 150, [11])
        self.players = self.fx._report(self.planner, [self.contact])

    def order(self, now=1., contact=None):
        if contact is not None:
            self.planner.report_contacts([contact], self.planner.known_targets(
                self.fx.states, self.players), now)
        return self.planner.build_orders(self.fx.manifest, self.fx.states,
            self.players, now)['orders'][0]

    def test_blocked_visible_target_outlives_firing_lease_without_launch(self):
        first = self.order()
        for now in (1.5, 3.1, 6., 9.):
            blocked = self.order(now, _contact(2, 0, 150, []))
            self.assertEqual(2, blocked['target_id'])
            self.assertEqual(first['aim_position'], blocked['aim_position'])
            self.assertFalse(blocked['fire_allowed'])
        clear = self.order(9.5, self.contact)
        self.assertEqual(2, clear['target_id'])
        self.assertTrue(clear['fire_allowed'])

    def test_blocked_lane_releases_stop_immediately_and_keeps_tracking(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], fire_seq=2, clip=1)
        self.assertEqual('engage', self.order(1.)['combat_mode'])
        blocked = _contact(2, 0, 150, [])
        for now in (2., 4., 9., 13., 20.):
            order = self.order(now, blocked)
            self.assertEqual('advance_contact', order['combat_mode'])
            self.assertEqual(order['aim_position'], order['move_position'])
            self.assertEqual(2, order['target_id'])
            self.assertIsNone(order['throttle_override'])
            self.assertFalse(order['fire_allowed'])
            self.assertNotIn(11, self.planner._firing_holds)
        clear = self.order(21., self.contact)
        self.assertEqual('engage', clear['combat_mode'])
        self.assertTrue(clear['fire_allowed'])

    def test_reloading_does_not_pin_a_lost_lane(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], fire_seq=2, clip=1)
        self.order(1.)
        self.fx.states[0]['reload_time'] = 10.
        order = self.order(2., _contact(2, 0, 150, []))
        self.assertEqual('advance_contact', order['combat_mode'])
        self.assertEqual(2, order['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertNotIn(11, self.planner._firing_holds)

    def test_dead_hidden_expired_and_out_of_range_contacts_release_tracking(self):
        for reason in ('dead', 'hidden', 'expired', 'range'):
            with self.subTest(reason=reason):
                self.setUp()
                self.order()
                contact = _contact(2, 0, 150, [])
                now = 2.
                if reason == 'dead':
                    self.players[0]['alive'] = False
                elif reason == 'hidden':
                    contact['visible'] = False
                elif reason == 'expired':
                    now = 20.
                    contact = None
                else:
                    contact = _contact(2, 0, 2000, [])
                released = self.order(now, contact)
                self.assertIsNone(released['target_id'])
                self.assertFalse(released['fire_allowed'])

    def test_hit_branch_cannot_replace_eligible_target_with_blocked_attacker(self):
        blocked_attacker = _contact(3, 0, 80, [])
        self.players = self.fx._report(self.planner, [self.contact, blocked_attacker])
        self.order()
        self.planner.report_damage(11, 'human', 3, 240, 1.1)
        order = self.order(1.2)
        self.assertEqual(2, order['target_id'])
        self.assertTrue(order['fire_allowed'])
        self.assertNotIn(order['combat_mode'], ('under_fire_withdraw', 'crossfire_withdraw', 'withdraw'))
        self.assertFalse(order['tactical_evidence']['withdraw_after_hit'])

    def test_magazine_finishes_then_withdraws_reload_and_reengages(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=2, clip_size=4,
            fire_seq=2)
        self.fx.states[0]['health'] = 200
        loaded = self.order()
        self.assertTrue(loaded['fire_allowed'])
        self.assertNotEqual('low_health_retreat', loaded['combat_mode'])
        self.assertTrue(loaded['tactical_evidence']['withdrawal']['deferred_for_magazine'])
        self.fx.states[0].update(clip=1, reload_time=2., fire_seq=3)
        intershot = self.order(1.5)
        self.assertNotIn(intershot['combat_mode'], ('low_health_retreat', 'magazine_reload_retreat'))
        self.assertEqual(2, intershot['target_id'])
        self.fx.states[0].update(clip=0, reload_time=30., fire_seq=4)
        empty = self.order(2.)
        self.assertEqual('magazine_reload_retreat', empty['combat_mode'])
        self.assertEqual(2, empty['target_id'])
        self.assertFalse(empty['fire_allowed'])
        self.fx.states[0].update(empty['move_position'])
        hold = self.order(3.)
        self.assertEqual('magazine_reload_hold', hold['tactical_phase'])
        self.assertEqual(0., hold['throttle_override'])
        self.fx.states[0].update(clip=4, reload_time=0.)
        ready = self.order(4., self.contact)
        self.assertNotIn(ready['combat_mode'], ('low_health_retreat', 'magazine_reload_retreat'))
        self.assertTrue(ready['fire_allowed'])
        self.assertNotIn(11, self.planner._retreat_states)

    def test_initial_magazine_loading_does_not_create_a_retreat(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
            fire_seq=0, reload_time=30.)
        self.assertNotEqual('magazine_reload_retreat', self.order()['combat_mode'])

    def test_magazine_reload_releases_when_ammunition_exhausted_or_target_gone(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
            fire_seq=4, reload_time=30.)
        self.assertEqual('magazine_reload_retreat', self.order()['combat_mode'])
        self.fx.states[0]['ammo_remaining'] = [0]
        order = self.order(2.)
        self.assertNotEqual('magazine_reload_retreat', order['combat_mode'])
        self.assertNotIn(11, self.planner._retreat_states)


if __name__ == '__main__':
    unittest.main()
