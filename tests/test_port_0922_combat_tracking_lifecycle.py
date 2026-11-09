"""Initial hints and native combat ownership without tactical retreat."""
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
            self.assertFalse(hasattr(self.planner, '_firing_holds'))
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
        self.assertFalse(hasattr(self.planner, '_firing_holds'))

    def test_dead_hidden_and_expired_contacts_release_initial_hint(self):
        for reason in ('dead', 'hidden', 'expired'):
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
                released = self.order(now, contact)
                self.assertIsNone(released['target_id'])
                self.assertFalse(released['fire_allowed'])

    def test_role_distance_cannot_remove_a_visible_contact_from_native_review(self):
        self.order()
        distant = self.order(2., _contact(2, 0, 2000, []))
        self.assertEqual(2, distant['target_id'])
        self.assertEqual('advance_contact', distant['combat_mode'])
        self.assertFalse(distant['fire_allowed'])
        candidates = distant['tactical_evidence']['selection']['candidates']
        self.assertEqual(1, len(candidates))
        self.assertEqual(('human', 2), candidates[0]['target'])
        self.assertEqual('eligible', candidates[0]['reason'])
        self.assertEqual(2000., candidates[0]['distance'])
        self.assertFalse(candidates[0]['local_lane'])

    def test_health_loss_does_not_change_nearest_initial_hint_or_create_retreat(self):
        self.assertEqual(2, self.order()['target_id'])
        blocked_contact = _contact(3, 0, 80, [])
        self.players = self.fx._report(self.planner, [self.contact, blocked_contact])
        before = self.order(1.1)
        # The macro planner supplies a stateless nearest hint. It does not
        # own a second current target, and damage cannot add retaliation.
        self.assertEqual(3, before['target_id'])
        self.assertEqual('advance_contact', before['combat_mode'])
        self.fx.states[0]['health'] -= 240
        self.assertFalse(hasattr(self.planner, 'report_damage'))
        self.assertFalse(hasattr(self.planner, '_target_assignments'))
        order = self.order(1.2)
        for field in ('target_id', 'combat_mode', 'aim_position', 'move_position'):
            self.assertEqual(before[field], order[field])
        self.assertFalse(order['fire_allowed'])
        candidates = order['tactical_evidence']['selection']['candidates']
        self.assertEqual({2, 3}, set(row['target'][1] for row in candidates))
        self.assertTrue(all(row['reason'] == 'eligible' for row in candidates))
        self.assertNotIn(order['combat_mode'], ('under_fire_withdraw', 'crossfire_withdraw', 'withdraw'))
        self.assertNotIn('withdraw_after_hit', order['tactical_evidence'])

    def test_health_loss_and_nearer_blocked_hint_preserve_native_current_target(self):
        from test_player_combat_ownership import OwnershipScene
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=1, burst=1)
        scene.eligible_enemy(14, armor=10.)
        self.assertEqual({14: True}, scene.sample_original_lanes())
        for unused in range(20):
            scene.tick(.1)
            if scene.runtime.attack_policy.decision['action'] == 'aim':
                break
        policy = scene.runtime.attack_policy
        candidate = policy.decision['candidate']
        self.assertEqual(('bot', 14), candidate['target_key'])
        self.assertTrue(policy._executable_current(candidate))
        original_key = candidate['key']
        scene.obstructed_enemy(2)
        scene.entity.health = max(1, scene.entity.health - 240)
        scene.battle._records['player:1']['state']['health'] = scene.entity.health
        self.assertEqual({2: False, 14: True}, scene.sample_original_lanes())
        scene.runtime._strategic_due = 0.
        scene.tick(.1)
        self.assertEqual(2, scene.original_order()['target_id'])
        self.assertEqual('advance_contact', scene.original_order()['combat_mode'])
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(original_key, policy.decision['candidate']['key'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))
        self.assertEqual(14, scene.applied_order()['target_id'])
        self.assertEqual({2, 14}, set(row['network_id'] for row in scene.runtime.combat_targets()))

    def test_actual_mounted_range_still_blocks_launch_without_discarding_contact(self):
        from test_player_combat_ownership import OwnershipScene
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(clip=1, burst=1)
        for shot in scene.runtime.gun.shots:
            shot.maxDistance = 350.
        for row in scene.battle.client.effective_params['gun']['shots']:
            row['source_shot']['maxDistance'] = 350.
        target = scene.eligible_enemy(14, armor=10.)
        scene.pose(target, (0., 0., 400.))
        original_ammo = list(scene.battle._gun_state.ammo)
        for unused in range(30):
            scene.tick(.1)
            self.assertFalse(scene.launches())
            self.assertFalse(scene.applied_order()['fire_allowed'])
        policy = scene.runtime.attack_policy
        self.assertEqual({14}, set(row['network_id'] for row in scene.runtime.combat_targets()))
        self.assertTrue(policy.rows)
        self.assertFalse(any(policy._executable_current(row) for row in policy.rows.values()))
        self.assertEqual(original_ammo, scene.battle._gun_state.ammo)
        self.assertEqual('firing_position', policy.decision['action'])
        self.assertEqual('accepted', policy.navigation_receipt['status'])
        self.assertGreater(policy.navigation_receipt['throttle'], 0.)
        self.assertIsNone(policy.search_started)

    def test_magazine_finishes_then_loads_in_place_and_reengages(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=2, clip_size=4,
            fire_seq=2)
        self.fx.states[0]['health'] = 200
        loaded = self.order()
        self.assertTrue(loaded['fire_allowed'])
        self.assertEqual('engage', loaded['combat_mode'])
        self.assertNotIn('withdrawal', loaded['tactical_evidence'])
        self.fx.states[0].update(clip=1, reload_time=2., fire_seq=3)
        intershot = self.order(1.5)
        self.assertEqual('engage', intershot['combat_mode'])
        self.assertEqual(0., intershot['throttle_override'])
        self.assertEqual(loaded['move_position'], intershot['move_position'])
        self.assertEqual(2, intershot['target_id'])
        self.assertFalse(intershot['fire_allowed'])
        self.fx.states[0].update(clip=0, reload_time=30., fire_seq=4)
        empty = self.order(2.)
        self.assertEqual('engage', empty['combat_mode'])
        self.assertEqual(0., empty['throttle_override'])
        self.assertEqual(loaded['move_position'], empty['move_position'])
        self.assertEqual(2, empty['target_id'])
        self.assertFalse(empty['fire_allowed'])
        hold = self.order(3.)
        self.assertEqual('engage', hold['combat_mode'])
        self.assertEqual(0., hold['throttle_override'])
        self.assertEqual(loaded['move_position'], hold['move_position'])
        self.assertFalse(hold['fire_allowed'])
        self.fx.states[0].update(clip=4, reload_time=0.)
        ready = self.order(4., self.contact)
        self.assertEqual('engage', ready['combat_mode'])
        self.assertTrue(ready['fire_allowed'])
        self.assertFalse(hasattr(self.planner, '_retreat_states'))

    def test_initial_magazine_loading_does_not_create_a_retreat(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
            fire_seq=0, reload_time=30.)
        order = self.order()
        self.assertEqual('engage', order['combat_mode'])
        self.assertEqual(0., order['throttle_override'])
        self.assertFalse(order['fire_allowed'])
        self.assertFalse(hasattr(self.planner, '_retreat_states'))

    def test_loading_releases_combat_when_ammunition_exhausted_or_target_gone(self):
        for cause in ('ammunition_exhausted', 'target_gone'):
            with self.subTest(cause=cause):
                self.setUp()
                self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
                    fire_seq=4, reload_time=30.)
                self.assertEqual('engage', self.order()['combat_mode'])
                if cause == 'ammunition_exhausted':
                    self.fx.states[0]['ammo_remaining'] = [0]
                else:
                    self.players[0]['alive'] = False
                order = self.order(2.)
                self.assertNotEqual('engage', order['combat_mode'])
                self.assertNotIn(order['combat_mode'], ('magazine_reload_retreat', 'withdraw'))
                self.assertFalse(order['fire_allowed'])
                self.assertFalse(hasattr(self.planner, '_retreat_states'))
                if cause == 'ammunition_exhausted':
                    self.assertTrue(order['empty_ammo'])
                else:
                    self.assertIsNone(order['target_id'])


if __name__ == '__main__':
    unittest.main()
