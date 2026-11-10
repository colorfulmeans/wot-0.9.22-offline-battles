"""Initial hints and native combat ownership without tactical retreat.

The planner-only cases verify observation and authored-route contracts, not
launch or combat-stop admission. The two OwnershipScene cases separately run
the native current-target and mounted-weapon consumers.
"""
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

    def assert_route_hint(self, order, identity=2):
        self.assertEqual(dict(target_kind='human', target_id=identity),
                         order['initial_target_hint'])
        self.assertEqual(('human', identity),
                         order['tactical_evidence']['selection']['selected'])
        self.assertEqual('initial_hint',
                         order['tactical_evidence']['selection']['owner'])
        self.assertEqual('route', order['combat_mode'])
        self.assertEqual('lane', order['route_id'])
        waypoint = self.fx.route['waypoints'][order['route_index']]
        self.assertEqual(dict((axis, waypoint[axis]) for axis in ('x', 'y', 'z')),
                         order['move_position'])
        self.assertIsNone(order['throttle_override'])
        self.assertIsNone(order['target_id'])
        self.assertIsNone(order['target_kind'])
        self.assertIsNone(order['aim_position'])
        self.assertFalse(order['fire_allowed'])

    def test_blocked_visible_hint_survives_without_launch_or_movement_authority(self):
        first = self.order()
        self.assert_route_hint(first)
        for now in (1.5, 3.1, 6., 9.):
            blocked = self.order(now, _contact(2, 0, 150, []))
            self.assert_route_hint(blocked)
            self.assertEqual(first['move_position'], blocked['move_position'])
            candidate = blocked['tactical_evidence']['selection']['candidates'][0]
            self.assertEqual(dict(x=0., y=0., z=150.), candidate['position'])
            self.assertFalse(candidate['local_lane'])
        clear = self.order(9.5, self.contact)
        self.assert_route_hint(clear)
        self.assertTrue(clear['tactical_evidence']['selection']['candidates'][0]['local_lane'])

    def test_lane_advisory_changes_cannot_alternate_macro_stop_and_approach(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], fire_seq=2, clip=1)
        self.assert_route_hint(self.order(1.))
        blocked = _contact(2, 0, 150, [])
        for now in (2., 4., 9., 13., 20.):
            order = self.order(now, blocked)
            self.assert_route_hint(order)
            self.assertFalse(order['tactical_evidence']['selection']['candidates'][0]['local_lane'])
            self.assertFalse(hasattr(self.planner, '_firing_holds'))
        clear = self.order(21., self.contact)
        self.assert_route_hint(clear)
        self.assertTrue(clear['tactical_evidence']['selection']['candidates'][0]['local_lane'])

    def test_reloading_cannot_turn_a_lost_lane_hint_into_a_movement_task(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], fire_seq=2, clip=1)
        self.order(1.)
        self.fx.states[0]['reload_time'] = 10.
        order = self.order(2., _contact(2, 0, 150, []))
        self.assert_route_hint(order)
        self.assertEqual(10., order['tactical_evidence']['selection']['weapon']['reload_time'])
        self.assertFalse(order['tactical_evidence']['weapon_ready'])
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
                self.assertFalse(released.get('initial_target_hint'))
                self.assertIsNone(released['tactical_evidence']['selection']['selected'])
                self.assertFalse(released['fire_allowed'])

    def test_role_distance_cannot_remove_a_visible_contact_from_native_review(self):
        self.order()
        distant = self.order(2., _contact(2, 0, 2000, []))
        self.assert_route_hint(distant)
        candidates = distant['tactical_evidence']['selection']['candidates']
        self.assertEqual(1, len(candidates))
        self.assertEqual(('human', 2), candidates[0]['target'])
        self.assertEqual('eligible', candidates[0]['reason'])
        self.assertEqual(2000., candidates[0]['distance'])
        self.assertFalse(candidates[0]['local_lane'])

    def test_health_loss_does_not_change_nearest_initial_hint_or_create_retreat(self):
        self.assert_route_hint(self.order())
        blocked_contact = _contact(3, 0, 80, [])
        self.players = self.fx._report(self.planner, [self.contact, blocked_contact])
        before = self.order(1.1)
        # The macro planner supplies a stateless nearest hint. It does not
        # own a second current target, and damage cannot add retaliation.
        self.assert_route_hint(before, 3)
        self.fx.states[0]['health'] -= 240
        self.assertFalse(hasattr(self.planner, 'report_damage'))
        self.assertFalse(hasattr(self.planner, '_target_assignments'))
        order = self.order(1.2)
        self.assert_route_hint(order, 3)
        for field in ('initial_target_hint', 'target_id', 'combat_mode', 'aim_position', 'move_position'):
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
        self.assertEqual(dict(target_kind='bot', target_id=2),
                         scene.original_order()['initial_target_hint'])
        self.assertIsNone(scene.original_order()['target_id'])
        self.assertEqual('route', scene.original_order()['combat_mode'])
        self.assertEqual('aim', policy.decision['action'])
        self.assertEqual(original_key, policy.decision['candidate']['key'])
        self.assertTrue(policy._executable_current(policy.decision['candidate']))
        self.assertTrue(scene.runtime.combat_stop.combat_owned)
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
        self.assertFalse(policy.navigation_receipt,
            'a cold out-of-mounted-range candidate has no accepted combat recovery')
        self.assertFalse(scene.runtime.combat_stop.combat_owned)
        self.assertFalse(scene.runtime.combat_stop.stop_allowed)
        self.assertEqual('route', scene.applied_order()['combat_mode'])
        self.assertIsNone(scene.applied_order()['target_id'])
        self.assertEqual(scene.original_order()['move_position'],
            dict(zip(('x', 'y', 'z'), scene.applied_order()['move_position'])))
        self.assertFalse(hasattr(policy, 'search_started'))

    def test_magazine_observations_preserve_hint_and_route_without_macro_fire_permission(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=2, clip_size=4,
            fire_seq=2)
        self.fx.states[0]['health'] = 200
        loaded = self.order()
        self.assert_route_hint(loaded)
        self.assertTrue(loaded['tactical_evidence']['weapon_ready'])
        self.assertNotIn('withdrawal', loaded['tactical_evidence'])
        self.fx.states[0].update(clip=1, reload_time=2., fire_seq=3)
        intershot = self.order(1.5)
        self.assert_route_hint(intershot)
        self.assertFalse(intershot['tactical_evidence']['weapon_ready'])
        self.assertEqual(loaded['move_position'], intershot['move_position'])
        self.fx.states[0].update(clip=0, reload_time=30., fire_seq=4)
        empty = self.order(2.)
        self.assert_route_hint(empty)
        self.assertFalse(empty['tactical_evidence']['weapon_ready'])
        self.assertEqual(loaded['move_position'], empty['move_position'])
        hold = self.order(3.)
        self.assert_route_hint(hold)
        self.assertFalse(hold['tactical_evidence']['weapon_ready'])
        self.assertEqual(loaded['move_position'], hold['move_position'])
        self.fx.states[0].update(clip=4, reload_time=0.)
        ready = self.order(4., self.contact)
        self.assert_route_hint(ready)
        self.assertTrue(ready['tactical_evidence']['weapon_ready'])
        self.assertFalse(hasattr(self.planner, '_retreat_states'))

    def test_initial_magazine_loading_does_not_create_a_retreat(self):
        self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
            fire_seq=0, reload_time=30.)
        order = self.order()
        self.assert_route_hint(order)
        self.assertFalse(order['tactical_evidence']['weapon_ready'])
        self.assertFalse(hasattr(self.planner, '_retreat_states'))

    def test_loading_does_not_override_empty_ammunition_task_or_lost_hint(self):
        for cause in ('ammunition_exhausted', 'target_gone'):
            with self.subTest(cause=cause):
                self.setUp()
                self.fx.states[0] = _weapon_state(self.fx.states[0], clip=0, clip_size=4,
                    fire_seq=4, reload_time=30.)
                self.assert_route_hint(self.order())
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
                    self.assertFalse(order.get('initial_target_hint'))


if __name__ == '__main__':
    unittest.main()
