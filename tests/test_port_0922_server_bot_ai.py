import json
from pathlib import Path
import sys
import unittest


PORT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PORT_ROOT / 'server'))
sys.path.insert(0, str(PORT_ROOT / 'src/res/scripts/client'))

from gui.mods.offline_lan_0922.vehicle_control.strategy import (  # noqa: E402
    BotPlanner,
    _order_signature,
)
from lan_battle_server import (  # noqa: E402
    BOT_PLANNER_INTERVAL_TICKS,
    CLIENT_BUILD_0922,
    PREBATTLE_SECONDS,
    SIMULATION_WORKER_AUTHORITY_ID,
    TICK_HZ,
    BattleState,
    Player,
    SimulationWorker,
)
from gui.mods.offline_lan_0922 import bot_gunnery  # noqa: E402
from gui.mods.offline_lan_0922.bot_runtime import (  # noqa: E402
    _overlay_live_target_pose,
    _server_order_signature,
)


def _profile(class_tag='SPG', roles=None):
    return {
        'class_tag': class_tag,
        'speed': 12.0,
        'dominant_role': ('artillery' if class_tag == 'SPG' else 'support'),
        'desired_range': 650.0 if class_tag == 'SPG' else 180.0,
        'fire_range': 1250.0 if class_tag == 'SPG' else 520.0,
        'roles': dict(roles or {}),
        'shells': [],
    }


def _route(route_id, points, capacity=None, class_weights=None,
           role_weights=None):
    result = {
        'id': route_id,
        'waypoints': [
            {'x': float(x), 'y': 0.0, 'z': float(z), 'hold': bool(hold)}
            for x, z, hold in points
        ],
    }
    if capacity is not None:
        result['capacity'] = int(capacity)
    if class_weights is not None:
        result['class_weights'] = dict(class_weights)
    if role_weights is not None:
        result['role_weights'] = dict(role_weights)
    return result


def _bot(bot_id, team, slot, route, class_tag='SPG', roles=None):
    return {
        'id': bot_id,
        'team': team,
        'slot': slot,
        'health': 1000,
        'profile': _profile(class_tag, roles),
        'route': route,
    }


def _state(bot_id, team, x, z):
    return {
        'id': bot_id,
        'team': team,
        'alive': True,
        'world_pose': True,
        'x': float(x),
        'y': 0.0,
        'z': float(z),
        'yaw': 0.0,
        'health': 1000,
        'max_health': 1000,
        'fire_seq': 0,
        'shell_index': 0,
        'next_shell_index': 0,
        'ammo_remaining': [20],
        'ammo_reload_pending': False,
        'reload_time': 0.0,
        'reload_duration': 20.0,
        'clip': 1,
        'clip_size': 1,
        'burst_active': False,
        'critical': {},
    }


def _weapon_state(raw, reload_time=0.0, clip=1, clip_size=1,
                  ammunition=(20,), reload_pending=False, fire_seq=0,
                  burst_active=False):
    raw.update({
        'fire_seq': int(fire_seq),
        'shell_index': 0,
        'next_shell_index': 0,
        'ammo_remaining': list(ammunition),
        'ammo_reload_pending': bool(reload_pending),
        'reload_time': float(reload_time),
        'reload_duration': 20.0,
        'clip': int(clip),
        'clip_size': int(clip_size),
        'burst_active': bool(burst_active),
    })
    return raw


def _contact(target_id, x, z, observers, class_tag='mediumTank'):
    return {
        'observing_team': 1,
        'target_kind': 'human',
        'target_id': target_id,
        'target_team': 2,
        'visible': True,
        'shootable_by_bot_ids': list(observers),
        'x': float(x),
        'y': 0.0,
        'z': float(z),
        'health': 1000,
        'max_health': 1000,
        'class_tag': class_tag,
    }


def _bot_contact(target_id, x, z, observers, class_tag='mediumTank'):
    result = _contact(target_id, x, z, observers, class_tag)
    result['target_kind'] = 'bot'
    return result


def _initial_hint(order):
    """Inspect macro candidates while rejecting accidental execution rights."""
    hint = order.get('initial_target_hint') or {}
    if hint:
        assert order.get('target_id') is None, order
        assert order.get('target_kind') is None, order
        assert order.get('fire_allowed') is False, order
    return dict(target_kind=hint.get('target_kind'), target_id=hint.get('target_id'))


def _capture_defense():
    return {
        'capture_bases': {
            '1': [{'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': -100.0}],
            '2': [{'id': '2:0', 'x': 123.5, 'y': 0.0, 'z': 456.25}],
        },
    }


class _CountingPlanner(BotPlanner):
    def __init__(self, state):
        BotPlanner.__init__(self)
        self.state = state
        self.build_ticks = []
        self.reset_count = 0
        self.reset_round_id = None

    def build_orders(self, *unused_args, **unused_kwargs):
        self.build_ticks.append(self.state.tick)
        return {"revision": len(self.build_ticks), "orders": []}

    def reset(self, round_id=None):
        BotPlanner.reset(self, round_id)
        self.reset_count += 1
        self.reset_round_id = round_id


class ServerBotTacticsTests(unittest.TestCase):
    def setUp(self):
        self.route = _route('lane', [
            (0, -100, False), (0, 100, False), (0, 500, False),
        ])
        self.manifest = [_bot(
            11, 1, 0, self.route, 'mediumTank', {'support': 1.0})]
        self.manifest[0]['profile'].update({
            'armor': 120.0,
            'dominant_role': 'support',
            'desired_range': 180.0,
            'fire_range': 520.0,
        })
        self.states = [_state(11, 1, 0, 0)]

    def _report(self, planner, contacts):
        players = [
            {'id': raw['target_id'], 'team': 2, 'alive': True}
            for raw in contacts
        ]
        self.assertEqual(len(contacts), planner.report_contacts(
            contacts, planner.known_targets(self.states, players), 1.0))
        return players

    def test_order_signature_ignores_live_target_pose_before_fire_permission(self):
        order = {
            'id': 11, 'target_kind': 'human', 'target_id': 2,
            'fire_allowed': False, 'shell_index': 0,
            'combat_mode': 'advance_contact',
            'aim_position': {'x': 0.0, 'y': 1.0, 'z': 80.0},
            'face_position': {'x': 0.0, 'y': 1.0, 'z': 80.0},
            'move_position': {'x': 0.0, 'y': 1.0, 'z': 80.0},
        }
        moved = dict(order)
        moved.update({
            'aim_position': {'x': 20.0, 'y': 1.0, 'z': 70.0},
            'face_position': {'x': 20.0, 'y': 1.0, 'z': 70.0},
            'move_position': {'x': 20.0, 'y': 1.0, 'z': 70.0},
        })

        self.assertEqual(_order_signature(order), _order_signature(moved))
        for field, value in (
                ('target_id', 3),
                ('fire_allowed', True),
                ('shell_index', 1),
                ('combat_mode', 'engage')):
            changed = dict(moved)
            changed[field] = value
            with self.subTest(field=field):
                self.assertNotEqual(
                    _order_signature(order), _order_signature(changed))

    def test_hint_changes_do_not_flush_movement_but_explicit_task_identity_does(self):
        planner = BotPlanner()
        contacts = [_contact(2, 0, 100, [11]), _contact(3, 0, 200, [11])]
        players = self._report(planner, contacts)
        first = planner.build_orders(self.manifest, self.states, players, 1.)
        contacts[1]['z'] = 30.
        planner.report_contacts(contacts, planner.known_targets(self.states, players), 1.1)
        following = planner.build_orders(self.manifest, self.states, players, 1.1)
        original, changed = first['orders'][0], following['orders'][0]
        self.assertEqual(2, _initial_hint(original)['target_id'])
        self.assertEqual(3, _initial_hint(changed)['target_id'])
        self.assertEqual(first['revision'], following['revision'])
        self.assertEqual(_server_order_signature(original), _server_order_signature(changed))
        explicit = dict(changed, team_command='ATTACKENEMY',
                        combat_task_target=dict(target_kind='human', target_id=3))
        self.assertNotEqual(_order_signature(changed), _order_signature(explicit))
        self.assertNotEqual(_server_order_signature(changed), _server_order_signature(explicit))

    def test_damage_cannot_preempt_the_nearest_initial_hint(self):
        planner = BotPlanner()
        contacts = [_contact(2, 0, 260, [11]), _contact(3, 0, 35, [11])]
        players = self._report(planner, contacts)
        first = planner.build_orders(self.manifest, self.states, players, 1.0)['orders'][0]
        self.assertEqual(3, _initial_hint(first)['target_id'])
        self.states[0]['health'] -= 240
        reaction = planner.build_orders(self.manifest, self.states, players, 1.1)['orders'][0]
        self.assertEqual(3, _initial_hint(reaction)['target_id'])
        self.assertEqual(first['move_position'], reaction['move_position'])
        self.assertFalse(reaction['fire_allowed'])
        self.assertFalse(hasattr(planner, 'report_damage'))
        self.assertFalse(hasattr(planner, '_recent_hits'))

    def test_recent_hit_never_starts_cover_or_peek_movement(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        first = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        self.states[0]['health'] -= 200
        for now in (1.1, 1.2, 5.0, 7.2, 20.0):
            planner.report_contacts(
                [contact], planner.known_targets(self.states, players), now)
            order = planner.build_orders(
                self.manifest, self.states, players, now)['orders'][0]
            self.assertEqual('route', order['combat_mode'])
            self.assertEqual(first['move_position'], order['move_position'])
            self.assertIsNone(order['throttle_override'])
            self.assertFalse(order['fire_allowed'])
            self.assertNotIn('cover_id', order)

    def test_low_health_vehicle_keeps_the_same_hint_and_route(self):
        orders=[]
        for health in (1000,200,1):
            planner=BotPlanner()
            self.states[0]['health']=health
            players=self._report(planner,[_contact(2,0,150,[11])])
            order=planner.build_orders(self.manifest,self.states,players,1.)['orders'][0]
            self.assertNotIn(order['combat_mode'],('low_health_retreat','low_health_defend'))
            self.assertFalse(order['fire_allowed'])
            orders.append({k:order[k]for k in ('combat_mode','move_position','target_id','face_position')})
        self.assertEqual(orders[0],orders[1])
        self.assertEqual(orders[0],orders[2])

    def test_low_health_has_no_retreat_state_or_handler_to_reactivate(self):
        planner = BotPlanner()
        players = self._report(planner, [_contact(2, 0, 150, [11])])
        self.states[0]['health'] = 200
        order = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        self.assertFalse(hasattr(planner, '_retreat_states'))
        self.assertFalse(hasattr(planner, '_apply_retreat_order'))
        self.assertEqual('route', order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertFalse(order['fire_allowed'])

    def test_lane_advisories_keep_candidate_without_taking_route_movement(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        first = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        self.assertFalse(first['fire_allowed'])

        pending = _contact(2, 0, 150, [])
        self.assertEqual(1, planner.report_contacts(
            [pending], planner.known_targets(self.states, players), 1.5))
        leased = planner.build_orders(
            self.manifest, self.states, players, 1.5)['orders'][0]

        self.assertEqual(2, _initial_hint(leased)['target_id'])
        self.assertEqual('route', leased['combat_mode'])
        self.assertEqual(first['move_position'], leased['move_position'])
        self.assertIsNone(leased['throttle_override'])
        self.assertNotIn('blocked_hold_handoff', leased['tactical_evidence'])
        self.assertNotIn('combat_handoff', leased['tactical_evidence'])
        self.assertFalse(leased['fire_allowed'])

        self.assertEqual(1, planner.report_contacts(
            [pending], planner.known_targets(self.states, players), 3.1))
        expired = planner.build_orders(
            self.manifest, self.states, players, 3.1)['orders'][0]
        self.assertEqual(2, _initial_hint(expired)['target_id'])
        self.assertEqual(first['aim_position'], expired['aim_position'])
        self.assertFalse(expired['fire_allowed'])

    def test_expired_positive_and_negative_lanes_never_change_macro_movement(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        first = planner.build_orders(self.manifest, self.states, players, 1.)['orders'][0]
        pending = dict(_contact(2, 0, 150, []), pending_lane_by_bot_ids=[11])
        for now in (1.5, 2., 3., 12., 13.):
            planner.report_contacts([pending], planner.known_targets(self.states, players), now)
            held = planner.build_orders(self.manifest, self.states, players, now)['orders'][0]
            self.assertEqual(first['combat_mode'], held['combat_mode'])
            self.assertEqual(first['move_position'], held['move_position'])
            self.assertIsNone(held['throttle_override'])
            self.assertFalse(held['fire_allowed'])
            self.assertNotIn('blocked_hold_handoff', held['tactical_evidence'])
            self.assertNotIn('firing_hold', held['tactical_evidence'])
        planner.report_contacts([contact], planner.known_targets(self.states, players), 13.2)
        restored = planner.build_orders(self.manifest, self.states, players, 13.2)['orders'][0]
        self.assertFalse(restored['fire_allowed'])
        blocked = _contact(2, 0, 150, [])
        planner.report_contacts([blocked], planner.known_targets(self.states, players), 13.5)
        approach = planner.build_orders(self.manifest, self.states, players, 13.5)['orders'][0]
        self.assertEqual('route', approach['combat_mode'])
        self.assertFalse(approach['fire_allowed'])

    def test_pending_lane_cannot_restore_a_legacy_macro_approach(self):
        planner = BotPlanner()
        bot = dict(id=11, state=self.states[0])
        focus = dict(target_kind='human', id=2, position=dict(x=0., y=0., z=150.),
                     pending_lane_by_bot_ids=[11])
        planner._last_orders = dict(orders=[dict(id=11, target_kind='human', target_id=2,
            combat_mode='advance_contact', move_position=focus['position'], throttle_override=None)])
        players = self._report(planner, [dict(_contact(2, 0, 150, []),
            pending_lane_by_bot_ids=[11])])
        order = planner.build_orders(self.manifest, self.states, players, 1.)['orders'][0]
        self.assertFalse(hasattr(planner, '_apply_leased_movement_order'))
        self.assertEqual('route', order['combat_mode'])
        self.assertEqual(dict(x=0., y=0., z=100.), order['move_position'])
        self.assertIsNone(order['throttle_override'])
        self.assertFalse(order['fire_allowed'])

    def test_pending_lane_cannot_restore_a_legacy_hold_or_hull_angling(self):
        planner = BotPlanner()
        bot = dict(id=11, state=self.states[0])
        focus = dict(target_kind='human', id=2, pending_lane_by_bot_ids=[11])
        previous = dict(id=11, target_kind='human', target_id=2, combat_mode='engage',
            move_position=dict(x=1.,y=0.,z=2.), face_position=dict(x=40.,y=0.,z=150.),
            hull_angle_degrees=20., stable_hull_face=True, throttle_override=0.)
        planner._last_orders = dict(orders=[previous])
        players = self._report(planner, [dict(_contact(2, 0, 150, []),
            pending_lane_by_bot_ids=[11])])
        order = planner.build_orders(self.manifest, self.states, players, 1.)['orders'][0]
        self.assertFalse(hasattr(planner, '_apply_leased_movement_order'))
        self.assertEqual(dict(x=0., y=0., z=100.), order['move_position'])
        self.assertIsNone(order['face_position'])
        self.assertNotIn('hull_angle_degrees', order)
        self.assertNotIn('stable_hull_face', order)
        self.assertFalse(order['fire_allowed'])

    def test_reload_does_not_reserve_or_steal_another_actors_target(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(_state(11, 1, 0, 0)),
            _weapon_state(_state(12, 1, 20, 0)),
        ]
        contact = _contact(2, 0, 240, [11, 12])
        contact.update({'health': 500, 'max_health': 1000})
        players = self._report(planner, [contact])

        first = dict((order['id'], order) for order in
                     planner.build_orders(
                         manifest, states, players, 1.0)['orders'])
        self.assertEqual(2, _initial_hint(first[11])['target_id'])
        self.assertEqual(2, _initial_hint(first[12])['target_id'])
        self.assertFalse(first[12]['fire_allowed'])

        states[0].update({
            'reload_time': 8.0,
            'ammo_reload_pending': True,
        })
        # Reload alone must not invalidate the still-proved local lane.
        ready_only = _contact(2, 0, 240, [11, 12])
        ready_only.update({'health': 500, 'max_health': 1000})
        self.assertEqual(1, planner.report_contacts(
            [ready_only], planner.known_targets(states, players), 1.5))
        reallocated = dict((order['id'], order) for order in
                           planner.build_orders(
                               manifest, states, players, 1.5)['orders'])

        self.assertEqual(2, _initial_hint(reallocated[11])['target_id'])
        self.assertFalse(reallocated[11]['fire_allowed'])
        self.assertEqual(first[11]['combat_mode'],
                         reallocated[11]['combat_mode'])
        self.assertEqual(first[11]['move_position'],
                         reallocated[11]['move_position'])
        self.assertEqual(2, _initial_hint(reallocated[12])['target_id'])
        self.assertFalse(reallocated[12]['fire_allowed'])

    def test_unavailable_weapons_do_not_consume_focus_capacity(self):
        unavailable_states = (
            (True, _weapon_state(
                _state(11, 1, 0, 0), reload_time=8.0,
                reload_pending=True)),
            (True, _weapon_state(
                _state(11, 1, 0, 0), reload_time=20.0,
                clip=0, clip_size=3, reload_pending=True)),
            (True, _weapon_state(
                _state(11, 1, 0, 0), ammunition=(0,))),
            (True, _weapon_state(_state(11, 1, 0, 0))),
        )
        unavailable_states[-1][1]['critical'] = {
            'destroyed': ['gunHealth'],
        }

        for keeps_movement_target, unavailable in unavailable_states:
            with self.subTest(state=unavailable):
                planner = BotPlanner()
                manifest = [
                    _bot(11, 1, 0, self.route, 'mediumTank'),
                    _bot(12, 1, 1, self.route, 'mediumTank'),
                ]
                states = [
                    unavailable,
                    _weapon_state(_state(12, 1, 20, 0)),
                ]
                contact = _contact(2, 0, 240, [11, 12])
                contact.update({'health': 500, 'max_health': 1000})
                players = self._report(planner, [contact])

                orders = dict((order['id'], order) for order in
                              planner.build_orders(
                                  manifest, states, players, 1.0)['orders'])

                if keeps_movement_target:
                    if orders[11].get('empty_ammo'):
                        self.assertEqual(2, orders[11]['target_id'])
                    else:
                        self.assertEqual(2, _initial_hint(orders[11])['target_id'])
                    self.assertFalse(orders[11]['fire_allowed'])
                else:
                    self.assertIsNone(_initial_hint(orders[11])['target_id'])
                    self.assertEqual('route', orders[11]['combat_mode'])
                    self.assertNotEqual(
                        {'x': 0.0, 'y': 0.0, 'z': 0.0},
                        orders[11]['move_position'])
                self.assertEqual(2, _initial_hint(orders[12])['target_id'])
                self.assertFalse(orders[12]['fire_allowed'])

    def test_reloading_vehicle_keeps_close_threat_hint_without_route_override(self):
        planner = BotPlanner()
        states = [_weapon_state(
            _state(11, 1, 0, 0), reload_time=8.0,
            reload_pending=True)]
        contact = _contact(2, 0, 20, [11])
        players = self._report(planner, [contact])

        order = planner.build_orders(
            self.manifest, states, players, 1.0)['orders'][0]

        self.assertEqual(2, _initial_hint(order)['target_id'])
        self.assertEqual('route', order['combat_mode'])
        self.assertFalse(order['fire_allowed'])

    def test_exhausted_weapon_keeps_its_explicit_empty_ammo_owner(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(_state(11, 1, 0, 0)),
            _weapon_state(_state(12, 1, 20, 0)),
        ]
        contact = _contact(2, 0, 240, [11, 12])
        contact.update({'health': 500, 'max_health': 1000})
        players = self._report(planner, [contact])
        first = dict((order['id'], order) for order in
                     planner.build_orders(
                         manifest, states, players, 1.0)['orders'])
        self.assertEqual(2, _initial_hint(first[11])['target_id'])

        states[0].update({
            'ammo_remaining': [0],
            'clip': 0,
        })
        ready_only = _contact(2, 0, 240, [12])
        ready_only.update({'health': 500, 'max_health': 1000})
        self.assertEqual(1, planner.report_contacts(
            [ready_only], planner.known_targets(states, players), 1.5))
        orders = dict((order['id'], order) for order in
                      planner.build_orders(
                          manifest, states, players, 1.5)['orders'])

        self.assertEqual(2, orders[11]['target_id'])
        self.assertTrue(orders[11]['empty_ammo'])
        self.assertFalse(orders[11]['fire_allowed'])
        self.assertIsNone(orders[11]['throttle_override'])
        self.assertFalse(hasattr(planner, '_target_assignments'))
        self.assertEqual(2, _initial_hint(orders[12])['target_id'])
        self.assertFalse(orders[12]['fire_allowed'])

    def test_pending_lane_hint_does_not_reserve_a_firing_slot(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(_state(11, 1, 0, 0)),
            _weapon_state(_state(12, 1, 20, 0)),
        ]
        initial = dict(_contact(2, 0, 150, [11]),
                       health=500, max_health=1000)
        players = self._report(planner, [initial])
        first = dict((order['id'], order) for order in
                     planner.build_orders(
                         manifest, states, players, 1.0)['orders'])
        self.assertEqual('route', first[11]['combat_mode'])
        for now in (2.0, 4.0):
            pending = dict(_contact(2, 0, 150, [12]),
                           health=500, max_health=1000,
                           pending_lane_by_bot_ids=[11])
            planner.report_contacts(
                [pending], planner.known_targets(states, players), now)
            orders = dict((order['id'], order) for order in
                          planner.build_orders(
                              manifest, states, players, now)['orders'])
            self.assertEqual('route', orders[11]['combat_mode'])
            self.assertEqual(first[11]['move_position'],
                             orders[11]['move_position'])
            self.assertIsNone(orders[11]['throttle_override'])
            self.assertFalse(orders[11]['fire_allowed'])
            self.assertEqual(2, _initial_hint(orders[12])['target_id'])
            self.assertFalse(orders[12]['fire_allowed'])

    def test_destroyed_gun_keeps_its_evaluation_hint_until_repaired(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(_state(11, 1, 0, 0)),
            _weapon_state(_state(12, 1, 20, 0)),
        ]
        contact = _contact(2, 0, 240, [11, 12])
        contact.update({'health': 500, 'max_health': 1000})
        players = self._report(planner, [contact])
        first = dict((order['id'], order) for order in
                     planner.build_orders(
                         manifest, states, players, 1.0)['orders'])
        self.assertEqual(2, _initial_hint(first[11])['target_id'])

        states[0]['critical'] = {'destroyed': ['gunHealth']}
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets(states, players), 1.5))
        destroyed = dict((order['id'], order) for order in
                         planner.build_orders(
                             manifest, states, players, 1.5)['orders'])
        self.assertEqual(2, _initial_hint(destroyed[11])['target_id'])
        self.assertFalse(destroyed[11]['fire_allowed'])
        self.assertEqual(first[11]['move_position'],
                         destroyed[11]['move_position'])
        self.assertEqual(2, _initial_hint(destroyed[12])['target_id'])
        self.assertFalse(destroyed[12]['fire_allowed'])

        states[0]['critical'] = {'destroyed': []}
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets(states, players), 19.6))
        repaired = dict((order['id'], order) for order in
                        planner.build_orders(
                            manifest, states, players, 19.6)['orders'])
        self.assertEqual(2, _initial_hint(repaired[11])['target_id'])
        self.assertFalse(repaired[11]['fire_allowed'])
        self.assertEqual(2, _initial_hint(repaired[12])['target_id'])
        self.assertFalse(repaired[12]['fire_allowed'])

    def test_active_burst_keeps_focus_while_reload_is_pending(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(
                _state(11, 1, 0, 0), reload_time=1.0,
                clip=2, clip_size=3, reload_pending=True,
                fire_seq=1, burst_active=True),
            _weapon_state(_state(12, 1, 20, 0)),
        ]
        contact = _contact(2, 0, 240, [11, 12])
        contact.update({'health': 500, 'max_health': 1000})
        players = self._report(planner, [contact])

        orders = dict((order['id'], order) for order in
                      planner.build_orders(
                          manifest, states, players, 1.0)['orders'])

        self.assertEqual(2, _initial_hint(orders[11])['target_id'])
        self.assertFalse(orders[11]['fire_allowed'])
        self.assertEqual(2, _initial_hint(orders[12])['target_id'])
        self.assertFalse(orders[12]['fire_allowed'])

    def test_minor_answerable_hit_does_not_force_withdrawal(self):
        planner = BotPlanner()
        self.states[0] = _weapon_state(self.states[0])
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        self.states[0]['health'] -= 1

        order = planner.build_orders(
            self.manifest, self.states, players, 1.1)['orders'][0]

        self.assertEqual(2, _initial_hint(order)['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertNotIn(order['combat_mode'], (
            'under_fire_withdraw', 'under_fire_hold'))

    def test_minor_unanswerable_hit_does_not_order_a_retreat(self):
        contact = _contact(2, 0, 50, [12])
        players = [{'id': 2, 'team': 2, 'alive': True}]

        unsupported = BotPlanner()
        solo_states = [_weapon_state(_state(11, 1, 0, 0))]
        self.assertEqual(1, unsupported.report_contacts(
            [contact], unsupported.known_targets(solo_states, players), 1.0))
        solo_states[0]['health'] -= 1
        solo = unsupported.build_orders(
            self.manifest, solo_states, players, 1.1)['orders'][0]
        self.assertNotEqual('under_fire_withdraw', solo['combat_mode'])

        supported = BotPlanner()
        manifest = [
            _bot(11, 1, 0, self.route, 'mediumTank'),
            _bot(12, 1, 1, self.route, 'mediumTank'),
        ]
        states = [
            _weapon_state(_state(11, 1, 0, 0)),
            _weapon_state(_state(12, 1, 0, 0)),
        ]
        self.assertEqual(1, supported.report_contacts(
            [contact], supported.known_targets(states, players), 1.0))
        states[0]['health'] -= 1
        orders = dict((order['id'], order) for order in
                      supported.build_orders(
                          manifest, states, players, 1.1)['orders'])

        self.assertEqual('route', orders[11]['combat_mode'])
        self.assertEqual(2, _initial_hint(orders[11])['target_id'])
        self.assertFalse(orders[11]['fire_allowed'])
        self.assertEqual(2, _initial_hint(orders[12])['target_id'])
        self.assertFalse(orders[12]['fire_allowed'])

        for unavailable in ('no_lane', 'empty', 'destroyed'):
            with self.subTest(unavailable=unavailable):
                planner = BotPlanner()
                ally = _weapon_state(_state(12, 1, 0, 0))
                shooters = [12]
                if unavailable == 'no_lane':
                    shooters = []
                elif unavailable == 'empty':
                    ally.update({'ammo_remaining': [0], 'clip': 0})
                else:
                    ally['critical'] = {'destroyed': ['gunHealth']}
                blocked_contact = _contact(2, 0, 50, shooters)
                blocked_states = [
                    _weapon_state(_state(11, 1, 0, 0)), ally,
                ]
                self.assertEqual(1, planner.report_contacts(
                    [blocked_contact], planner.known_targets(
                        blocked_states, players), 1.0))
                blocked_states[0]['health'] -= 1

                blocked = dict((order['id'], order) for order in
                               planner.build_orders(
                                   manifest, blocked_states, players,
                                   1.1)['orders'])

                self.assertNotEqual(
                    'under_fire_withdraw', blocked[11]['combat_mode'])

    def test_dead_target_is_cleared_before_ordering(self):
        planner = BotPlanner()
        players = self._report(planner, [_contact(2, 0, 150, [11])])
        first = planner.build_orders(self.manifest, self.states, players, 1.0)['orders'][0]
        self.assertEqual(2, _initial_hint(first)['target_id'])
        players[0]['alive'] = False
        order = planner.build_orders(self.manifest, self.states, players, 1.2)['orders'][0]
        self.assertIsNone(_initial_hint(order)['target_id'])
        self.assertFalse(hasattr(planner, '_target_assignments'))
        self.assertEqual('route', order['combat_mode'])

    def test_magazine_and_reload_do_not_override_macro_route_progress(self):
        planner = BotPlanner()
        self.states[0] = _weapon_state(
            self.states[0], clip=3, clip_size=3)
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        first = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        baseline = BotPlanner()
        baseline.build_orders(self.manifest, self.states, players, 1.)
        # Cover return used to be attached to these magazine states.
        # Their weapon readiness remains authoritative, not their movement.
        samples = (
            (2.0, dict(reload_time=10.0, ammo_reload_pending=True), False),
            (4.1, dict(reload_time=0.0, ammo_reload_pending=False), True),
            (4.3, dict(fire_seq=1, clip=2, ammo_remaining=[19],
                       reload_time=0.8, reload_duration=1.0,
                       ammo_reload_pending=True), False),
            (4.4, dict(fire_seq=2, clip=1, ammo_remaining=[18],
                       burst_active=True), True),
            (4.5, dict(fire_seq=3, clip=0, ammo_remaining=[17],
                       reload_time=20.0, reload_duration=20.0,
                       burst_active=False), False),
            (24.5, dict(clip=3, reload_time=0.0,
                        ammo_reload_pending=False), True),
        )
        for now, updates, ready in samples:
            with self.subTest(now=now, ready=ready):
                self.states[0].update(updates)
                planner.report_contacts(
                    [contact], planner.known_targets(self.states, players), now)
                order = planner.build_orders(
                    self.manifest, self.states, players, now)['orders'][0]
                route = baseline.build_orders(self.manifest, self.states, players, now)['orders'][0]
                self.assertEqual('route', order['combat_mode'])
                self.assertEqual(route['move_position'], order['move_position'])
                self.assertIsNone(order['throttle_override'])
                self.assertEqual(2, _initial_hint(order)['target_id'])
                self.assertEqual(ready, order['tactical_evidence']['weapon_ready'])
                self.assertFalse(order['fire_allowed'])

    def test_ready_without_shot_cannot_start_a_macro_combat_deadline(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        first = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        baseline = BotPlanner()
        baseline.build_orders(self.manifest, self.states, players, 1.)
        for now in (2.0, 8.1, 11.5, 30.0, 120.0):
            planner.report_contacts(
                [contact], planner.known_targets(self.states, players), now)
            order = planner.build_orders(
                self.manifest, self.states, players, now)['orders'][0]
            route = baseline.build_orders(self.manifest, self.states, players, now)['orders'][0]
            self.assertEqual('route', order['combat_mode'])
            self.assertEqual(route['move_position'], order['move_position'])
            self.assertIsNone(order['throttle_override'])
            self.assertFalse(order['fire_allowed'])
        self.assertFalse(hasattr(planner, '_firing_holds'))
        self.assertFalse(hasattr(planner, '_release_unproductive_firing_hold'))

    def test_cover_candidate_reporting_and_retry_storage_are_deleted(self):
        planner = BotPlanner()
        for name in ('report_affordances', '_cover_candidate',
                     '_apply_cover_order', '_cover_states',
                     '_cover_failures', '_cover_reservations', '_affordances'):
            with self.subTest(name=name):
                self.assertFalse(hasattr(planner, name))

    def test_contact_free_capturer_follows_lane_before_enemy_base(self):
        planner = BotPlanner()
        defense = _capture_defense()

        approach = planner.build_orders(
            self.manifest, self.states, [], 1.0, defense)['orders'][0]

        self.assertEqual('route', approach['combat_mode'])
        self.assertEqual({'x': 0.0, 'y': 0.0, 'z': 100.0},
                         approach['move_position'])
        self.assertNotIn('capture_base_id', approach)

        self.states[0]['z'] = 100.0
        intermediate = planner.build_orders(
            self.manifest, self.states, [], 1.5, defense)['orders'][0]
        self.assertEqual('route', intermediate['combat_mode'])
        self.states[0]['z'] = 500.0
        order = planner.build_orders(
            self.manifest, self.states, [], 2.0, defense)['orders'][0]

        self.assertEqual('base_capture', order['combat_mode'])
        self.assertEqual('2:0', order['capture_base_id'])
        self.assertEqual({'x': 123.5, 'y': 0.0, 'z': 456.25},
                         order['move_position'])
        self.assertEqual(order['move_position'], order['aim_position'])
        self.assertEqual(order['move_position'], order['face_position'])


    def test_capture_screen_does_not_stop_at_an_intermediate_waypoint(self):
        planner = BotPlanner()
        route = _route('long-lane', [
            (0, -100, False), (0, 0, False), (0, 100, False),
            (0, 200, False), (0, 300, False), (0, 500, False),
        ])
        manifest = [
            _bot(401 + index, 1, index, route, 'mediumTank')
            for index in range(4)
        ]
        states = [
            _state(401, 1, 0, 300),
            _state(402, 1, 0, 300),
            _state(403, 1, 0, 300),
            _state(404, 1, 0, 50),
        ]
        defense = _capture_defense()

        first = dict((order['id'], order) for order in
                     planner.build_orders(
                         manifest, states, [], 1.0, defense)['orders'])
        self.assertEqual('route', first[404]['combat_mode'])
        self.assertEqual(2, first[404]['route_index'])

        # The route advances at 13 metres, while screen arrival uses 15. A
        # vehicle inside that two-metre band at an intermediate point must
        # keep driving instead of accepting a permanent intentional hold.
        states[3]['z'] = 86.0
        intermediate = dict((order['id'], order) for order in
                            planner.build_orders(
                                manifest, states, [], 2.0,
                                defense)['orders'])
        self.assertEqual('route', intermediate[404]['combat_mode'])
        self.assertEqual(2, intermediate[404]['route_index'])
        self.assertEqual(100.0, intermediate[404]['move_position']['z'])
        self.assertIsNone(intermediate[404]['throttle_override'])

        states[3]['z'] = 100.0
        planner.build_orders(manifest, states, [], 3.0, defense)
        states[3]['z'] = 200.0
        planner.build_orders(manifest, states, [], 4.0, defense)
        states[3]['z'] = 286.0
        staged = dict((order['id'], order) for order in
                      planner.build_orders(
                          manifest, states, [], 5.0, defense)['orders'])
        self.assertEqual('route', staged[404]['combat_mode'])
        self.assertEqual(4, staged[404]['route_index'])
        self.assertIsNone(staged[404]['throttle_override'])

    def test_malinovka_shared_connector_advances_through_forward_corridor(self):
        graph = json.loads(
            (PORT_ROOT / 'navgraphs' / '02_malinovka.json').read_text())
        baked = next(
            route for route in graph['routes']['2']
            if route['id'] == 'central_field')
        route = _route(
            baked['id'],
            [(point[0], point[1], point[2])
             for point in baked['waypoints']])
        bot = _bot(24, 2, 0, route, 'AT-SPG')
        bot['state'] = _state(24, 2, -360.68, 104.85)
        planner = BotPlanner()
        planner._route_states[24] = {
            'index': 1,
            'route_id': 'central_field',
            'join_index': 1,
            'join_anchor': {'x': -374.0, 'y': 0.0, 'z': 110.0},
        }

        route_id, index, point, anchor, route_join = planner._route(bot, 1.0)

        self.assertEqual('central_field', route_id)
        self.assertEqual(3, index)
        self.assertEqual({k: round(route['waypoints'][3][k], 3) for k in ('x', 'y', 'z')}, point)
        self.assertEqual({'x': -362.0, 'y': 0.0, 'z': 106.0}, anchor)
        self.assertFalse(route_join)

    def _malinovka_east_hill_bot(self, speed):
        """The shipped 02_malinovka team-1 slot 2 line-up and its lane.

        That slot parks at (70, -366) facing -0.73 rad while its authored first
        connector lies 184 m away at 1.83 rad off the hull - one of 246 shipped
        spawn slots, across 33 of the 41 baked maps, where the rear-facing
        filter discarded the reviewed egress.
        """
        graph = json.loads(
            (PORT_ROOT / 'navgraphs' / '02_malinovka.json').read_text())
        baked = next(
            route for route in graph['routes']['1']
            if route['id'] == 'east_hill_loop')
        route = _route(
            baked['id'],
            [(point[0], point[1], point[2])
             for point in baked['waypoints']])
        bot = _bot(24, 1, 2, route, 'mediumTank')
        bot['state'] = _state(24, 1, 70.0, -366.0)
        bot['state']['yaw'] = -0.7306
        bot['state']['speed'] = speed
        return bot

    def test_parked_spawn_yaw_keeps_the_authored_first_connector(self):
        """A parking orientation is not a travel direction."""
        planner = BotPlanner()

        bot = self._malinovka_east_hill_bot(0.0)
        route_id, index, point, unused_anchor, route_join = planner._route(bot, 1.0)

        self.assertEqual('east_hill_loop', route_id)
        self.assertEqual(1, index)
        self.assertEqual({k: round(bot['route']['waypoints'][1][k], 3) for k in ('x', 'y', 'z')}, point)
        self.assertTrue(route_join)

    def test_a_moving_hull_still_skips_a_rear_facing_connector(self):
        """Once under way the hull yaw is a real travel direction again."""
        planner = BotPlanner()

        bot = self._malinovka_east_hill_bot(6.0)
        route_id, index, point, unused_anchor, unused_join = planner._route(bot, 1.0)

        self.assertEqual('east_hill_loop', route_id)
        self.assertEqual(3, index)
        self.assertEqual({k: round(bot['route']['waypoints'][3][k], 3) for k in ('x', 'y', 'z')}, point)

    def test_reverse_recovery_keeps_the_nearest_connector_after_reset(self):
        """Negative speed is recovery, not a strategic travel heading."""
        planner = BotPlanner()
        bot = self._malinovka_east_hill_bot(6.0)
        unused_route, first_index, unused_point, unused_anchor, unused_join = \
            planner._route(bot, 1.0)
        self.assertEqual(3, first_index)

        planner._route_states.pop(bot['id'])
        bot['state']['speed'] = -6.0
        route_id, index, point, unused_anchor, route_join = planner._route(
            bot, 2.0)

        self.assertEqual('east_hill_loop', route_id)
        self.assertEqual(1, index)
        self.assertEqual({k: round(bot['route']['waypoints'][1][k], 3) for k in ('x', 'y', 'z')}, point)
        self.assertTrue(route_join)

    def test_route_corridor_does_not_accept_lateral_or_distant_bypasses(self):
        route = _route('bounded-corridor', [
            (0, -20, False), (0, 0, False), (12, 0, False),
            (80, 80, False),
        ])
        planner = BotPlanner()

        for bot_id, x, z in ((25, 8.0, 13.1), (26, 40.0, 0.0)):
            bot = _bot(bot_id, 1, 0, route, 'mediumTank')
            bot['state'] = _state(bot_id, 1, x, z)
            planner._route_states[bot_id] = {
                'index': 1,
                'route_id': 'bounded-corridor',
                'join_index': 1,
                'join_anchor': {'x': 0.0, 'y': 0.0, 'z': -20.0},
            }

            unused_route_id, index, point, unused_anchor, unused_join = (
                planner._route(bot, 1.0))

            self.assertEqual(1, index)
            self.assertEqual({'x': 0.0, 'y': 0.0, 'z': 0.0}, point)








    def test_known_enemy_admits_contact_review_instead_of_starting_base_capture(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 400, [])
        players = self._report(planner, [contact])
        defense = _capture_defense()

        order = planner.build_orders(
            self.manifest, self.states, players, 1.0, defense)['orders'][0]

        self.assertEqual('route', order['combat_mode'])
        self.assertEqual(2, _initial_hint(order)['target_id'])
        self.assertFalse(order['fire_allowed'])
        self.assertNotIn('capture_base_id', order)

    def test_initial_hint_does_not_block_capture_after_completed_terminal(self):
        planner = BotPlanner()
        route = _route('short', [(0, -100, False), (0, 100, False)])
        manifest = [_bot(11, 1, 0, route, 'mediumTank')]
        states = [_state(11, 1, 0., 100.)]
        players = [dict(id=2, team=2, alive=True)]
        contact = _contact(2, 0., 400., [])
        defense = _capture_defense()
        planner.report_contacts([contact], planner.known_targets(states, players), 1.)
        for now, z in ((1., 100.), (1.2, 140.)):
            states[0]['z'] = z
            order = planner.build_orders(manifest, states, players, now, defense)['orders'][0]
            self.assertEqual(2, _initial_hint(order)['target_id'])
            self.assertEqual('base_capture', order['combat_mode'])
            self.assertEqual(defense['capture_bases']['2'][0]['id'], order['capture_base_id'])
            self.assertIsNone(order['target_id'])
            self.assertFalse(order['fire_allowed'])
        players[0]['alive'] = False
        released = planner.build_orders(manifest, states, players, 1.4, defense)['orders'][0]
        self.assertEqual('base_capture', released['combat_mode'])
        self.assertEqual(defense['capture_bases']['2'][0]['id'], released['capture_base_id'])

    def test_two_wide_enemy_lanes_do_not_trigger_crossfire_withdrawal(self):
        planner = BotPlanner()
        contacts = [
            _contact(2, -130, 130, [11]),
            _contact(3, 130, 130, [11]),
        ]
        for contact in contacts:
            contact['threatened_bot_ids'] = [11]
        players = self._report(planner, contacts)

        order = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]

        self.assertEqual('route', order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertFalse(hasattr(planner, '_crossfire_risk'))
        self.assertFalse(order['fire_allowed'])

    def test_outgoing_firing_lanes_do_not_claim_incoming_crossfire(self):
        planner = BotPlanner()
        contacts = [
            _contact(2, -130, 130, [11]),
            _contact(3, 130, 130, [11]),
        ]
        players = self._report(planner, contacts)

        order = planner.build_orders(
            self.manifest, self.states, players, 1.0)['orders'][0]
        self.assertEqual('route', order['combat_mode'])
        self.assertIsNone(order['throttle_override'])
        self.assertFalse(order['fire_allowed'])

    def test_unready_or_blocked_ally_cannot_override_another_actors_route(self):
        contact = _contact(2, 0, 380, [12], 'heavyTank')
        player = {'id': 2, 'team': 2, 'alive': True}
        manifest = [
            _bot(12, 1, 0, self.route, 'mediumTank', {'support': 1.0}),
            _bot(13, 1, 1, self.route, 'mediumTank', {'support': 1.0}),
        ]
        for bot in manifest:
            bot['profile'].update({
                'dominant_role': 'support', 'desired_range': 200.0,
                'fire_range': 520.0,
            })

        for reason in ('no_lane', 'reloading'):
            with self.subTest(reason=reason):
                planner = BotPlanner()
                states = [
                    _weapon_state(_state(12, 1, 0, 0)),
                    _weapon_state(_state(13, 1, 5, 0)),
                ]
                sample = dict(contact)
                if reason == 'reloading':
                    sample['shootable_by_bot_ids'] = [12, 13]
                    states[1].update({
                        'reload_time': 8.0,
                        'ammo_reload_pending': True,
                    })
                self.assertEqual(1, planner.report_contacts(
                    [sample], planner.known_targets(states, [player]), 1.0))

                orders = dict((value['id'], value) for value in
                              planner.build_orders(
                                  manifest, states, [player], 1.0)['orders'])

                self.assertEqual('route', orders[12]['combat_mode'])
                self.assertIsNone(orders[12]['throttle_override'])
                self.assertFalse(orders[12]['fire_allowed'])
                self.assertFalse(orders[13]['fire_allowed'])

    def test_shell_damage_does_not_limit_the_number_of_actors_admitted(self):
        planner = BotPlanner()
        manifest = [
            _bot(bot_id, 1, bot_id, self.route, 'mediumTank')
            for bot_id in (11, 12, 13, 14)
        ]
        for bot in manifest:
            bot['profile']['shells'] = [{
                'index': 0,
                'kind': 'ARMOR_PIERCING',
                'penetration': 200.0,
                'damage': 800.0,
            }]
        states = [
            _weapon_state(_state(bot['id'], 1, 0, 0))
            for bot in manifest
        ]
        contact = _contact(2, 0, 200, [11, 12, 13, 14])
        contact.update({
            'health': 1600,
            'max_health': 2000,
            'armor': 100.0,
        })
        player = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets(states, [player]), 1.0))

        orders = planner.build_orders(
            manifest, states, [player], 1.0)['orders']

        self.assertEqual(4, sum(_initial_hint(order)['target_id'] == 2
                                for order in orders))

    def test_flanker_role_cannot_replace_route_with_a_candidate_position(self):
        planner = BotPlanner()
        manifest = [
            _bot(12, 1, 0, self.route, 'mediumTank', {
                'support': 1.0, 'flanker': 0.1,
            }),
            _bot(14, 1, 1, self.route, 'mediumTank', {
                'support': 0.1, 'flanker': 1.0,
            }),
        ]
        for bot in manifest:
            bot['profile'].update({
                'dominant_role': 'support', 'desired_range': 160.0,
                'fire_range': 520.0,
            })
        states = [
            _weapon_state(_state(12, 1, -80, -180)),
            _weapon_state(_state(14, 1, 0, -230)),
        ]
        contact = _contact(2, 0, 0, [12, 14])
        contact.update({'health': 2000, 'max_health': 2000})
        player = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets(states, [player]), 1.0))

        orders = dict((order['id'], order) for order in
                      planner.build_orders(
                          manifest, states, [player], 1.0)['orders'])

        for state in states:
            order = orders[state['id']]
            self.assertEqual('route', order['combat_mode'])
            self.assertEqual(dict(x=0., y=0., z=100.),
                             order['move_position'])
            self.assertIsNone(order['throttle_override'])
            self.assertFalse(order['fire_allowed'])

    def test_radio_enemy_task_identity_is_distinct_from_nearest_hint_and_lane(self):
        planner = BotPlanner()
        contacts = [
            _contact(2, 0, 35, [11]),
            _contact(3, 0, 180, [11]),
        ]
        players = self._report(planner, contacts)
        team_order = {
            'command_id': '1:1:1',
            'command': 'ATTACKENEMY',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
            'target_kind': 'player',
            'target_id': 3,
        }

        commanded = planner.build_orders(
            self.manifest, self.states, players, 1.0,
            team_orders=[team_order])['orders'][0]
        self.assertEqual(2, _initial_hint(commanded)['target_id'])
        self.assertEqual('ATTACKENEMY', commanded['team_command'])
        self.assertEqual(dict(target_kind='human', target_id=3),
                         commanded['combat_task_target'])
        self.assertNotIn('player_command_cancelled', commanded)

        blocked = dict(contacts[1])
        blocked['shootable_by_bot_ids'] = []
        self.assertEqual(1, planner.report_contacts(
            [blocked], planner.known_targets(self.states, players), 1.1))
        fallback = planner.build_orders(
            self.manifest, self.states, players, 1.1,
            team_orders=[team_order])['orders'][0]

        self.assertEqual(2, _initial_hint(fallback)['target_id'])
        self.assertEqual(commanded['combat_task_target'], fallback['combat_task_target'])
        self.assertEqual(commanded['move_position'], fallback['move_position'])
        self.assertFalse(fallback['fire_allowed'])

    def test_radio_movement_orders_use_validated_live_positions(self):
        issuer = {
            'id': 1, 'team': 1, 'alive': True, 'world_pose': True,
            'x': 45.0, 'y': 2.0, 'z': 60.0,
        }
        base_order = {
            'command_id': '1:1:1',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
        }
        cases = (
            ('FOLLOWME', 'team_follow',
             {'x': 45.0, 'y': 2.0, 'z': 42.0}),
            ('STOP', 'team_stop',
             {'x': 0.0, 'y': 0.0, 'z': 0.0}),
        )

        for command, mode, point in cases:
            with self.subTest(command=command):
                planner = BotPlanner()
                team_order = dict(base_order, command=command)
                order = planner.build_orders(
                    self.manifest, self.states, [issuer], 1.0,
                    team_orders=[team_order])['orders'][0]

                self.assertEqual(mode, order['combat_mode'])
                self.assertEqual(point, order['move_position'])

    def test_radio_order_cannot_cross_team_or_invalid_tick_window(self):
        invalid_orders = [{
            'command_id': '1:1:1',
            'command': 'STOP',
            'team': team,
            'issuer_id': 1,
            'issued_tick': issued,
            'expires_tick': expires,
            'recipient_bot_ids': [11],
        } for team, issued, expires in ((2, 100, 200), (1, 200, 200))]

        order = BotPlanner().build_orders(
            self.manifest, self.states, [], 1.0,
            team_orders=invalid_orders)['orders'][0]

        self.assertEqual('route', order['combat_mode'])
        self.assertNotIn('team_command', order)

    def test_radio_back_to_base_uses_the_canonical_capture_base(self):
        team_order = {
            'command_id': '1:1:1',
            'command': 'BACKTOBASE',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
        }
        defense = {
            'capture_bases': {
                '1': [{'id': '1:0', 'x': -25.0, 'y': 0.0, 'z': -450.0}],
            },
        }

        planner = BotPlanner()
        order = planner.build_orders(
            self.manifest, self.states, [], 1.0, defense,
            team_orders=[team_order])['orders'][0]

        self.assertEqual('team_back_to_base', order['combat_mode'])
        self.assertEqual(dict(x=0.,y=0.,z=-100.), order['move_position'])
        self.assertEqual(dict(x=-25.,y=0.,z=-450.),
                         planner._travel_tasks[11]['base']['point'])

    def test_radio_cell_order_is_forwarded_without_inventing_a_world_point(self):
        team_order = {
            'command_id': '1:1:1',
            'command': 'ATTENTIONTOCELL',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
            'cell_index': 38,
        }

        order = BotPlanner().build_orders(
            self.manifest, self.states, [], 1.0,
            team_orders=[team_order])['orders'][0]

        self.assertEqual('ATTENTIONTOCELL', order['team_command'])
        self.assertEqual(38, order['team_command_cell_index'])
        self.assertEqual('route', order['combat_mode'])

    def test_radio_cell_order_moves_to_the_proved_grid_cell_center(self):
        team_order = {
            'command_id': '1:1:1',
            'command': 'ATTENTIONTOCELL',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
            'cell_index': 38,
        }
        defense = {'arena_bounds': [-500.0, -500.0, 500.0, 500.0]}

        order = BotPlanner().build_orders(
            self.manifest, self.states, [], 1.0, defense,
            team_orders=[team_order])['orders'][0]

        self.assertEqual('team_attention_cell', order['combat_mode'])
        self.assertEqual(
            {'x': -150.0, 'y': 0.0, 'z': -350.0},
            order['move_position'])
        self.assertEqual(
            [-200.0, -400.0, -100.0, -300.0],
            order['move_area_bounds'])

    def test_radio_navigation_orders_replace_every_autonomous_mode(self):
        base_team_order = {
            'command_id': '1:1:1', 'team': 1, 'issuer_id': 1,
            'issued_tick': 100, 'expires_tick': 200,
            'recipient_bot_ids': [11],
        }
        issuer = {
            'id': 1, 'team': 1, 'alive': True, 'world_pose': True,
            'x': 45.0, 'y': 2.0, 'z': 60.0, 'yaw': 0.0,
        }
        defense = {
            'capture_bases': {'1': [
                {'id': '1:0', 'x': -25.0, 'y': 0.0, 'z': -450.0},
            ]},
            'arena_bounds': [-500.0, -500.0, 500.0, 500.0],
        }
        bot = {
            'id': 11, 'team': 1,
            'state': {'x': 4.0, 'y': 0.0, 'z': 6.0},
        }
        modes = (
            'route', 'advance', 'engage', 'advance_contact', 'base_defense',
        )
        route_point = {'x': 0.0, 'y': 0.0, 'z': 100.0}
        route_anchor = {'x': 0.0, 'y': 0.0, 'z': -100.0}
        cases = (
            ('ATTACK', 'team_attack', route_point, None),
            ('FOLLOWME', 'team_follow',
             {'x': 45.0, 'y': 2.0, 'z': 42.0}, None),
            ('HELPME', 'team_follow',
             {'x': 45.0, 'y': 2.0, 'z': 42.0}, None),
            ('HELPMEEX', 'team_follow',
             {'x': 45.0, 'y': 2.0, 'z': 42.0}, None),
            ('STOP', 'team_stop',
             {'x': 4.0, 'y': 0.0, 'z': 6.0}, 0.0),
            ('BACKTOBASE', 'team_back_to_base',
             {'x': -25.0, 'y': 0.0, 'z': -450.0}, None),
            ('ATTENTIONTOCELL', 'team_attention_cell',
             {'x': -150.0, 'y': 0.0, 'z': -350.0}, None),
        )

        for mode in modes:
            for command, expected_mode, point, throttle in cases:
                with self.subTest(mode=mode, command=command):
                    team_order = dict(
                        base_team_order, command=command, cell_index=38)
                    order = {
                        'combat_mode': mode, 'target_id': 2,
                        'aim_position': {'x': 18.0, 'y': 0.0, 'z': 4.0},
                        'route_anchor': dict(route_anchor),
                        'move_position': {'x': 12.0, 'y': 0.0, 'z': 0.0},
                        'face_position': {'x': 18.0, 'y': 0.0, 'z': 4.0},
                        'throttle_override': 0.0, 'fire_allowed': True,
                    }

                    BotPlanner._apply_team_order(
                        order, bot, team_order, [issuer], defense,
                        route_point)

                    self.assertEqual(expected_mode, order['combat_mode'])
                    self.assertEqual(point, order['move_position'])
                    self.assertEqual(throttle, order['throttle_override'])
                    self.assertEqual(2, order['target_id'])
                    self.assertTrue(order['fire_allowed'])
                    if command == 'ATTACK':
                        self.assertEqual(
                            {'x': 18.0, 'y': 0.0, 'z': 4.0},
                            order['face_position'])

    def test_radio_enemy_commands_keep_base_defense_priority(self):
        protected_modes = ('base_defense',)
        bot = {
            'id': 11, 'team': 1,
            'state': {'x': 4.0, 'y': 0.0, 'z': 6.0},
        }
        for mode in protected_modes:
            for command in ('ATTACKENEMY', 'SUPPORTMEWITHFIRE'):
                with self.subTest(mode=mode, command=command):
                    team_order = {
                        'command_id': '1:1:1', 'command': command,
                        'team': 1, 'issuer_id': 1,
                        'issued_tick': 100, 'expires_tick': 200,
                        'recipient_bot_ids': [11],
                    }
                    original = {'x': 12.0, 'y': 0.0, 'z': 0.0}
                    order = {
                        'combat_mode': mode,
                        'route_anchor': {'x': 0.0, 'y': 0.0, 'z': -100.0},
                        'move_position': dict(original),
                        'throttle_override': 0.0,
                    }
                    BotPlanner._apply_team_order(
                        order, bot, team_order, [], None)
                    self.assertEqual(mode, order['combat_mode'])
                    self.assertEqual(original, order['move_position'])
                    self.assertEqual(0.0, order['throttle_override'])
                    self.assertEqual(command, order['team_command'])

    def test_retired_turnback_cannot_move_any_vehicle_to_a_previous_waypoint(self):
        route = _route('turnback-lane', [
            (0, -100, False), (0, 100, False),
            (0, 300, False), (0, 500, False),
        ])
        team_order = {
            'command_id': '1:1:1', 'command': 'TURNBACK',
            'team': 1, 'issuer_id': 1,
            'issued_tick': 100, 'expires_tick': 200,
            'recipient_bot_ids': [11],
        }
        for class_tag in (
                'lightTank', 'mediumTank', 'heavyTank', 'AT-SPG', 'SPG'):
            with self.subTest(class_tag=class_tag):
                planner = BotPlanner()
                manifest = [_bot(11, 1, 0, route, class_tag)]
                states = [_state(11, 1, 0, 400)]
                planner._route_states[11] = {
                    'index': 3, 'route_id': route['id'],
                    'join_index': 1,
                    'join_anchor': {'x': 0.0, 'y': 0.0, 'z': 100.0},
                }
                baseline = BotPlanner()
                baseline._route_states[11] = dict(planner._route_states[11])
                ordinary = baseline.build_orders(
                    manifest, states, [], 1.0)['orders'][0]
                order = planner.build_orders(
                    manifest, states, [], 1.0,
                    team_orders=[team_order])['orders'][0]
                self.assertNotIn('team_command', order)
                # Preserve SPG staging as well as ordinary forward route work.
                for key in ('combat_mode', 'move_position', 'route_index',
                            'throttle_override'):
                    self.assertEqual(ordinary[key], order[key], key)
                self.assertNotIn('_route_position', order)
                self.assertNotIn('_turnback_position', order)

    def test_radio_stop_is_not_cancelled_by_an_evaluation_hint(self):
        planner = BotPlanner()
        contact = _contact(2, 0, 150, [11])
        players = self._report(planner, [contact])
        self.states[0]['health'] = 100
        team_order = {
            'command_id': '1:1:1',
            'command': 'STOP',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
        }

        order = planner.build_orders(
            self.manifest, self.states, players, 1.0,
            team_orders=[team_order])['orders'][0]

        self.assertEqual('team_stop',order['combat_mode'])
        self.assertEqual('STOP',order['team_command'])
        self.assertEqual(dict(x=0., y=0., z=0.), order['move_position'])
        self.assertEqual(0., order['throttle_override'])
        self.assertNotIn('player_command_cancelled',order)

    def test_radio_stop_cannot_override_an_urgent_base_responder(self):
        defense = {
            'bases': {'1': [
                {'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': -100.0},
            ]},
            'states': {'1': {
                'points': 20, 'time_left': 60.0,
                'invaders': 1, 'stopped': False,
            }},
            'contributors': {'1': []},
            'capture_bases': {'1': [
                {'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': -100.0},
            ]},
        }
        team_order = {
            'command_id': '1:1:1',
            'command': 'STOP',
            'team': 1,
            'issuer_id': 1,
            'issued_tick': 100,
            'expires_tick': 200,
            'recipient_bot_ids': [11],
        }

        order = BotPlanner().build_orders(
            self.manifest, self.states, [], 1.0, defense,
            team_orders=[team_order])['orders'][0]

        self.assertNotEqual('team_stop',order['combat_mode'])
        self.assertNotIn('team_command',order)
        self.assertTrue(order['player_command_cancelled'])

    def test_nearby_ally_cannot_start_preferred_range_advance(self):
        contact = _contact(2, 0, 380, [12, 13], 'heavyTank')
        player = {'id': 2, 'team': 2, 'alive': True}
        cautious = _bot(
            12, 1, 0, self.route, 'mediumTank', {'support': 1.0})
        cautious['profile'].update({
            'dominant_role': 'support', 'desired_range': 200.0,
            'fire_range': 520.0,
        })
        cautious_state = _state(12, 1, 0, 0)

        solo = BotPlanner()
        self.assertEqual(1, solo.report_contacts(
            [contact], solo.known_targets([cautious_state], [player]), 1.0))
        solo_order = solo.build_orders(
            [cautious], [cautious_state], [player], 1.0)['orders'][0]
        self.assertEqual('route', solo_order['combat_mode'])
        self.assertIsNone(solo_order['throttle_override'])

        ally = _bot(13, 1, 1, self.route, 'mediumTank', {'support': 1.0})
        ally_state = _state(13, 1, 5, 0)
        supported = BotPlanner()
        self.assertEqual(1, supported.report_contacts(
            [contact], supported.known_targets(
                [cautious_state, ally_state], [player]), 1.0))
        orders = dict((value['id'], value) for value in
                      supported.build_orders(
                          [cautious, ally], [cautious_state, ally_state],
                          [player], 1.0)['orders'])
        self.assertEqual('route', orders[12]['combat_mode'])
        self.assertEqual(solo_order['move_position'], orders[12]['move_position'])
        self.assertIsNone(orders[12]['throttle_override'])
        self.assertFalse(orders[12]['fire_allowed'])
        self.assertFalse(hasattr(supported, '_ally_support_score'))

    def test_role_ranges_do_not_exclude_a_visible_initial_contact(self):
        planner = BotPlanner()
        cautious = _bot(
            12, 1, 0, self.route, 'mediumTank', {'support': 1.0})
        cautious['profile'].update({
            'armor': 120.0,
            'dominant_role': 'support',
            'desired_range': 150.0,
            'fire_range': 340.0,
        })
        state = _state(12, 1, 0, 0)
        contact = _contact(2, 0, 400, [12], 'heavyTank')
        player = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets([state], [player]), 1.0))

        order = planner.build_orders(
            [cautious], [state], [player], 1.0)['orders'][0]

        self.assertEqual('route', order['combat_mode'])
        self.assertEqual(2, _initial_hint(order)['target_id'])
        self.assertEqual(100.0, order['move_position']['z'])
        self.assertIsNone(order['throttle_override'])
        self.assertEqual('eligible', order['tactical_evidence']['selection']['candidates'][0]['reason'])
        self.assertFalse(order['fire_allowed'])

    def test_preferred_range_boundaries_cannot_replace_the_ordinary_route(self):
        planner = BotPlanner()
        cautious = _bot(
            12, 1, 0, self.route, 'mediumTank', {'support': 1.0})
        cautious['profile'].update({
            'armor': 120.0,
            'dominant_role': 'support',
            'desired_range': 200.0,
            'fire_range': 520.0,
        })
        state = _state(12, 1, 0, 0)
        player = {'id': 2, 'team': 2, 'alive': True}
        far_limit = 200.0 * (
            1.08 + planner._personality(12)['caution'] * 0.18)

        def order_at(now, distance):
            contact = _contact(2, 0, distance, [12], 'heavyTank')
            self.assertEqual(1, planner.report_contacts(
                [contact], planner.known_targets([state], [player]), now))
            return planner.build_orders(
                [cautious], [state], [player], now)['orders'][0]

        outside = order_at(1.0, far_limit + 0.5)
        inside_band = order_at(2.1, far_limit - 0.5)
        inside = order_at(3.2, far_limit - 25.0)
        outside_band = order_at(4.3, far_limit + 0.5)

        self.assertEqual('route', outside['combat_mode'])
        self.assertEqual('route', inside_band['combat_mode'])
        self.assertEqual('route', inside['combat_mode'])
        self.assertEqual('route', outside_band['combat_mode'])
        self.assertEqual(outside['move_position'], inside['move_position'])
        self.assertEqual(outside['aim_position'], outside['face_position'])
        self.assertEqual(inside['aim_position'], inside['face_position'])
        self.assertNotIn('stable_hull_face', outside)
        self.assertNotIn('stable_hull_face', inside)

    def test_candidate_hint_cannot_supply_tactical_hull_aim(self):
        for class_tag, armor in (('mediumTank', 120.0), ('heavyTank', 240.0), ('AT-SPG', 240.0)):
            with self.subTest(class_tag=class_tag):
                planner = BotPlanner()
                manifest = [_bot(11, 1, 0, self.route, class_tag)]
                manifest[0]['profile'].update(armor=armor, desired_range=180.0, fire_range=520.0)
                players = self._report(planner, [_contact(2, 0, 150, [11])])
                order = planner.build_orders(manifest, self.states, players, 1.0)['orders'][0]
                self.assertEqual('route', order['combat_mode'])
                self.assertIsNone(order['throttle_override'])
                self.assertNotIn('hull_angle_degrees', order)
                self.assertNotIn('stable_hull_face', order)
                self.assertEqual(order['aim_position'], order['face_position'])
                moved = dict(alive=True, visible=True, position=(30.0, 0.0, 170.0))
                live = _overlay_live_target_pose(order, moved, (0.0, 0.0, 0.0))
                self.assertIsNone(live['aim_position'])
                self.assertIsNone(live['face_position'])
                committed = dict(order, target_kind='human', target_id=2)
                live = _overlay_live_target_pose(committed, moved, (0.0, 0.0, 0.0))
                self.assertEqual(moved['position'], live['aim_position'])
                self.assertEqual(live['aim_position'], live['face_position'])

    def test_server_damage_accounting_never_dispatches_a_retaliation_policy(self):
        clock = lambda: 12.5
        state = BattleState(clock=clock)
        state.players[1] = Player(
            1, None, ('test', 0), team=2, connected=True)
        state.bot_states[11] = {'id': 11, 'team': 1}
        received = []
        state.bot_planner.report_damage = lambda *values: received.append(
            values) or True

        state._record_damage(
            ('player', 1), ('bot', 11), 175, {})

        self.assertEqual([], received)
        self.assertEqual(175, state.enemy_damage_received[('bot', 11)])
        self.assertEqual(175, state._statistics_row('player', 1)['damage_dealt'])
        self.assertEqual(175, state._statistics_row('bot', 11)['damage_received'])

    def test_global_planning_runs_at_one_hz_while_worker_snapshots_stay_30_hz(self):
        state = BattleState()
        state.client_build = CLIENT_BUILD_0922
        state.phase = 'battle'
        state.bot_authority_id = SIMULATION_WORKER_AUTHORITY_ID
        planner = _CountingPlanner(state)
        state.bot_planner = planner
        snapshots = []
        worker = SimulationWorker(None, ('test', 0))
        worker.offer_reliable = (
            lambda message: snapshots.append(message) or True)
        worker.offer_snapshot = (
            lambda message: snapshots.append(message) or True)
        state.simulation_worker = worker

        for unused in range(BOT_PLANNER_INTERVAL_TICKS + 1):
            state.tick_once(1.0 / TICK_HZ)

        self.assertEqual([1, 31], planner.build_ticks)
        self.assertEqual(BOT_PLANNER_INTERVAL_TICKS + 1, state.tick)
        self.assertEqual(
            list(range(1, BOT_PLANNER_INTERVAL_TICKS + 2)),
            [message['server_tick'] for message in snapshots])

    def test_first_live_tick_replans_immediately_after_round_reset(self):
        state = BattleState()
        state.client_build = CLIENT_BUILD_0922
        state.phase = 'battle'
        planner = _CountingPlanner(state)
        state.bot_planner = planner

        state.tick_once(1.0 / TICK_HZ)
        for unused in range(BOT_PLANNER_INTERVAL_TICKS - 1):
            state.tick_once(1.0 / TICK_HZ)
        self.assertEqual([1], planner.build_ticks)

        state._reset_round()
        state.phase = 'battle'
        state.tick_once(1.0 / TICK_HZ)

        self.assertEqual(1, planner.reset_count)
        self.assertEqual([1, 1], planner.build_ticks)

    def test_observation_and_damage_accounting_survive_skipped_plan_ticks(self):
        state = BattleState()
        state.client_build = CLIENT_BUILD_0922
        state.phase = 'battle'
        prebattle_ticks = int(round(PREBATTLE_SECONDS * TICK_HZ))
        state.tick = prebattle_ticks
        state.bot_authority_id = SIMULATION_WORKER_AUTHORITY_ID
        state.bot_manifest_authority_id = SIMULATION_WORKER_AUTHORITY_ID
        state.bot_manifest = list(self.manifest)
        state.bot_states = {11: dict(self.states[0])}
        target = Player(
            2, None, ('test', 0), team=2, connected=True,
            participating=True)
        target.offer_reliable = lambda unused_message: True
        target.offer_snapshot = lambda unused_message: True
        state.players[2] = target
        build_ticks = []
        build_orders = state.bot_planner.build_orders

        def record_build(*args, **kwargs):
            build_ticks.append(state.tick)
            return build_orders(*args, **kwargs)

        state.bot_planner.build_orders = record_build
        state.tick_once(1.0 / TICK_HZ)
        relay = state.update_bot_observation(
            SIMULATION_WORKER_AUTHORITY_ID, {
                'type': 'bot_observation', 'round_id': state.round_id,
                'contacts': [{
                    'observing_team': 1, 'target_kind': 'human',
                    'target_id': 2, 'target_team': 2,
                    'visible': True, 'fresh': True, 'time_left': 10.0,
                    'visible_by_bot_ids': [11],
                    'visible_by_player_ids': [],
                    'shootable_by_bot_ids': [11],
                    'x': 0.0, 'y': 0.0, 'z': 150.0,
                    'health': 1000, 'max_health': 1000,
                }],
                'affordances': [],
            })
        state._record_damage(
            ('player', 2), ('bot', 11), 75, {})

        self.assertIsInstance(relay, dict)
        self.assertIn(('human', 2), state.bot_planner._contacts[1])
        self.assertFalse(hasattr(state.bot_planner, '_recent_hits'))
        self.assertEqual(75, state.enemy_damage_received[('bot', 11)])
        for unused in range(BOT_PLANNER_INTERVAL_TICKS - 1):
            state.tick_once(1.0 / TICK_HZ)
        self.assertEqual([prebattle_ticks + 1], build_ticks)

        state.tick_once(1.0 / TICK_HZ)

        self.assertEqual(
            [prebattle_ticks + 1,
             prebattle_ticks + 1 + BOT_PLANNER_INTERVAL_TICKS],
            build_ticks)
        order = next(
            order for order in state.bot_orders['orders']
            if order['id'] == 11)
        self.assertEqual(2, _initial_hint(order)['target_id'])


class ServerBotFittingRatingTests(unittest.TestCase):
    """Rating changes real fittings, not combat capability."""

    def setUp(self):
        self.route = _route('lane', [
            (0, -100, False), (0, 100, False), (0, 500, False),
        ])
        self.manifest = [_bot(
            11, 1, 0, self.route, 'mediumTank', {'support': 1.0})]
        self.manifest[0]['profile'].update({
            'armor': 120.0,
            'dominant_role': 'support',
            'desired_range': 180.0,
            'fire_range': 520.0,
        })
        self.states = [_state(11, 1, 0, 0)]

    def _rate(self, rating):
        self.manifest[0]['skill_rating'] = rating

    def _report(self, planner, contacts):
        players = [
            {'id': raw['target_id'], 'team': 2, 'alive': True}
            for raw in contacts
        ]
        self.assertEqual(len(contacts), planner.report_contacts(
            contacts, planner.known_targets(self.states, players), 1.0))
        return players






    def test_unrated_manifest_does_not_invent_a_strategy_competence(self):
        row = BotPlanner()._alive_bots(self.manifest, self.states)[0]
        self.assertNotIn('rating', row)
        self.assertNotIn('skill_rating', self.manifest[0])

    def test_published_fitting_rating_stays_in_manifest_not_strategy_row(self):
        self._rate(0.25)
        row = BotPlanner()._alive_bots(self.manifest, self.states)[0]
        self.assertNotIn('rating', row)
        self.assertEqual(0.25, self.manifest[0]['skill_rating'])

    def test_fitting_tier_does_not_create_a_strategy_score(self):
        self.manifest[0]['skill'] = 'rookie'
        row = BotPlanner()._alive_bots(self.manifest, self.states)[0]
        self.assertNotIn('rating', row)
        self.assertEqual('rookie', self.manifest[0]['skill'])

    def test_every_fitting_rating_uses_the_same_hint_and_route_policy(self):
        results = []
        for rating in (0.0, 0.05, 0.25, 0.5, 0.75, 1.0):
            planner = BotPlanner()
            self._rate(rating)
            players = self._report(planner, [_contact(2, 0, 260, [11]), _contact(3, 0, 150, [11])])
            self.states[0]['health'] = 200
            order = planner.build_orders(self.manifest, self.states, players, 1.0)['orders'][0]
            self.assertEqual('route', order['combat_mode'])
            self.assertFalse(order['fire_allowed'])
            self.assertIsNone(order['throttle_override'])
            self.assertNotIn('hull_angle_degrees', order)
            results.append(tuple(order[key] for key in ('target_id', 'move_position', 'face_position')))
        self.assertTrue(all(row == results[0] for row in results))

    def test_strategy_does_not_override_the_actual_loaded_round(self):
        for rating in (0.0, 1.0):
            planner = BotPlanner()
            self._rate(rating)
            self.manifest[0]['profile']['shells'] = [
                dict(index=0, kind='armor_piercing', penetration=100.0, damage=250.0),
                dict(index=1, kind='armor_piercing_cr', penetration=250.0, damage=250.0)]
            self.states[0]['ammo_remaining'] = [20, 10]
            players = self._report(planner, [dict(_contact(2, 0, 150, [11]), armor=200.0)])
            order = planner.build_orders(self.manifest, self.states, players, 1.0)['orders'][0]
            self.assertEqual(0, order['shell_index'])

    def test_initial_hints_have_no_timer_or_independent_current_target_state(self):
        planner = BotPlanner()
        self._rate(0.5)
        contacts = [_contact(2, 0, 260, [11]), _contact(3, 0, 200, [11])]
        players = self._report(planner, contacts)
        for now in (1.0, 1.25, 3.0, 8.0, 30.0, 120.0):
            planner.report_contacts(contacts, planner.known_targets(self.states, players), now)
            order = planner.build_orders(self.manifest, self.states, players, now)['orders'][0]
            self.assertEqual(3, _initial_hint(order)['target_id'])
        self.assertFalse(hasattr(planner, '_target_assignments'))
        self.assertEqual('initial_hint', planner._target_decisions[11]['owner'])

    def test_round_or_reconstruction_does_not_roll_combat_capabilities(self):
        targets = []
        for round_id in range(30):
            planner = BotPlanner()
            planner.reset(round_id)
            self._rate(0.5)
            players = self._report(planner, [_contact(2, 0, 260, [11]), _contact(3, 0, 150, [11])])
            order = planner.build_orders(self.manifest, self.states, players, 1.0)['orders'][0]
            targets.append(_initial_hint(order)['target_id'])
            self.assertFalse(hasattr(planner, '_capable'))
            self.assertFalse(hasattr(planner, 'report_damage'))
            self.assertFalse(hasattr(planner, '_recent_hits'))
        self.assertEqual({3}, set(targets))


class ServerBotInitialSelectionTests(unittest.TestCase):
    """Initial acquisition is deterministic; local armor policy owns firing."""

    def setUp(self):
        self.route = _route('lane', [
            (0, -100, False), (0, 100, False), (0, 500, False),
        ])
        self.manifest = [_bot(
            11, 1, 0, self.route, 'mediumTank', {'support': 1.0})]
        self.manifest[0]['profile'].update({
            'armor': 120.0,
            'dominant_role': 'support',
            'desired_range': 180.0,
            'fire_range': 520.0,
        })
        self.states = [_state(11, 1, 0, 0)]

    def _rate(self, rating):
        self.manifest[0]['skill_rating'] = rating

    def _report(self, planner, contacts, enemy_bots=()):
        """Report contacts of either kind and return the player roster."""
        players = [
            {'id': raw['target_id'], 'team': 2, 'alive': True}
            for raw in contacts if raw['target_kind'] == 'human'
        ]
        states = list(self.states) + [
            _state(bot_id, 2, 0.0, 0.0) for bot_id in enemy_bots
        ]
        self.states = states
        self.assertEqual(len(contacts), planner.report_contacts(
            contacts, planner.known_targets(states, players), 1.0))
        return players

    def _order(self, planner, players, now=1.0):
        return next(
            order for order in planner.build_orders(
                self.manifest, self.states, players, now)['orders']
            if order['id'] == 11)

    def _target(self, planner, players, now=1.0):
        order = self._order(planner, players, now)
        return _initial_hint(order)['target_kind'], _initial_hint(order)['target_id']


    def test_nearest_without_identity_class_or_health_bonus(self):
        for rating in (0.0, 0.25, 0.5, 0.75, 1.0):
            planner = BotPlanner()
            self._rate(rating)
            contacts = [dict(_contact(2, 0, 250, [11], 'SPG'), health=1),
                        dict(_bot_contact(3, 0, 150, [11]), health=1000)]
            players = self._report(planner, contacts, enemy_bots=(3,))
            self.assertEqual(('bot', 3), self._target(planner, players))

    def test_exact_distance_tie_uses_lower_armor(self):
        planner = BotPlanner()
        contacts = [dict(_contact(2, 0, 150, [11]), armor=240.0),
                    dict(_contact(3, 90, 120, [11]), armor=60.0)]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 3), self._target(planner, players))

    def test_distance_is_not_binned_to_promote_a_farther_soft_target(self):
        planner = BotPlanner()
        contacts = [dict(_contact(2, 0, 150, [11]), armor=240.0),
                    dict(_contact(3, 0, 150.001, [11]), armor=20.0)]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 2), self._target(planner, players))

    def test_missing_or_invalid_armor_is_not_invented_as_zero_at_an_exact_tie(self):
        for armor in (None, float('nan'), float('inf'), -5.):
            with self.subTest(armor=armor):
                planner = BotPlanner()
                contacts = [dict(_contact(2, 0, 150, [11]), armor=armor),
                            dict(_contact(3, 90, 120, [11]), armor=80.)]
                players = self._report(planner, contacts)
                self.assertEqual(('human', 3), self._target(planner, players))
                self.assertIsNone(planner._contacts[1][('human', 2)]['armor'])

    def test_initial_armor_fact_can_come_from_the_observed_vehicle_profile(self):
        planner = BotPlanner()
        contacts = [dict(_contact(2, 0, 150, [11]), armor=240.),
                    dict(_contact(3, 90, 120, [11]), armor=None, profile=dict(armor=60.))]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 3), self._target(planner, players))
        self.assertEqual(60., planner._contacts[1][('human', 3)]['armor'])

    def test_exact_equal_distance_and_armor_are_deterministic(self):
        for reverse in (False, True):
            planner = BotPlanner()
            contacts = [dict(_contact(2, 0, 150, [11]), armor=120.0),
                        dict(_contact(3, 0, 150, [11]), armor=120.0)]
            players = self._report(planner, list(reversed(contacts)) if reverse else contacts)
            self.assertEqual(('human', 2), self._target(planner, players))

    def test_macro_hint_updates_without_owning_the_current_attack(self):
        planner = BotPlanner()
        contacts = [_contact(2, 0, 150, [11]), _contact(3, 0, 250, [11])]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 2), self._target(planner, players))
        contacts[1]['z'] = 30.0
        for now in (2.0, 8.0, 120.0):
            planner.report_contacts(contacts, planner.known_targets(self.states, players), now)
            self.assertEqual(('human', 3), self._target(planner, players, now))
        self.assertFalse(hasattr(planner, '_target_assignments'))

    def test_dead_current_target_is_replaced_and_never_selected_as_a_wreck(self):
        planner = BotPlanner()
        contacts = [_contact(2, 0, 50, [11]), _contact(3, 0, 150, [11])]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 2), self._target(planner, players))
        players[0]['alive'] = False
        self.assertEqual(('human', 3), self._target(planner, players, 1.2))

    def test_zero_health_contact_is_not_an_enemy_candidate(self):
        planner = BotPlanner()
        contacts = [dict(_contact(2, 0, 50, [11]), health=0), _contact(3, 0, 150, [11])]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 3), self._target(planner, players))

    def test_no_retaliation_or_focus_quota_entrypoint_remains(self):
        planner = BotPlanner()
        for name in ('report_damage', '_recent_hit', '_recent_threat_contact',
                     '_desired_focus', '_focus_limit', '_reserve_focus',
                     '_focus_saturated', '_capable', '_apply_stationary_angling',
                     '_target_assignments', '_assign_targets', '_new_target_record'):
            self.assertFalse(hasattr(planner, name), name)

    def test_all_known_candidates_remain_available_to_local_armor_selection(self):
        planner = BotPlanner()
        contacts = [_contact(2, 0, 100, [11]), _contact(3, 0, 150, []), _contact(4, 0, 220, [11])]
        players = self._report(planner, contacts)
        self.assertEqual(('human', 2), self._target(planner, players))
        rows = planner._target_decisions[11]['candidates']
        self.assertEqual({('human', 2), ('human', 3), ('human', 4)},
                         {row['target'] for row in rows if row['reason'] == 'eligible'})

    def test_no_nominal_damage_or_identity_quota_limits_admitted_actors(self):
        bot_ids = list(range(11, 26))
        self.manifest = [_bot(bot_id, 1, slot, self.route, 'mediumTank') for slot, bot_id in enumerate(bot_ids)]
        baseline = [_state(bot_id, 1, slot * 4.0, 0) for slot, bot_id in enumerate(bot_ids)]
        for damage in (None, 40.0, 250.0, 2000.0):
            for entry in self.manifest:
                entry['profile']['shells'] = ([] if damage is None else [dict(index=0, kind='ARMOR_PIERCING', penetration=200.0, damage=damage)])
            for kind in ('human', 'bot'):
                with self.subTest(damage=damage, kind=kind):
                    planner = BotPlanner()
                    self.states = list(baseline)
                    contact = _contact(2, 0, 150, bot_ids) if kind == 'human' else _bot_contact(2, 0, 150, bot_ids)
                    players = self._report(planner, [contact], () if kind == 'human' else (2,))
                    orders = planner.build_orders(self.manifest, self.states, players, 1.0)['orders']
                    self.assertEqual(15, sum(_initial_hint(order)['target_id'] == 2 and _initial_hint(order)['target_kind'] == kind and not order['fire_allowed'] for order in orders))


class ServerBotArtilleryTests(unittest.TestCase):
    def test_spg_keeps_a_client_proved_target_beyond_direct_fire_range(self):
        planner = BotPlanner()
        route = _route('field', [
            (0, 0, False), (0, 60, False), (0, 1200, False),
        ])
        manifest = [_bot(11, 1, 0, route)]
        states = [_state(11, 1, 0, 60)]
        enemy = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts([{
            'observing_team': 1,
            'target_kind': 'human',
            'target_id': 2,
            'target_team': 2,
            'visible': True,
            'shootable_by_bot_ids': [11],
            'x': 0.0,
            'y': 0.0,
            'z': 1050.0,
            'health': 1000,
            'max_health': 1000,
        }], planner.known_targets(states, [enemy]), 1.0))

        order = planner.build_orders(
            manifest, states, [enemy], 1.0)['orders'][0]

        self.assertEqual(2, order['target_id'])
        self.assertTrue(order['fire_allowed'])
        self.assertEqual('artillery_hold', order['combat_mode'])
        self.assertEqual(1250.0, order['fire_range'])

    def test_mirrored_spgs_choose_stable_rear_non_hold_anchors(self):
        planner = BotPlanner()
        manifest = [
            _bot(11, 1, 0, _route('field', [
                (0, 0, False), (0, 60, False),
                (0, 160, True), (0, 600, False),
            ])),
            _bot(26, 2, 0, _route('field', [
                (0, 600, False), (0, 540, False),
                (0, 440, True), (0, 0, False),
            ])),
        ]
        states = [_state(11, 1, 0, 0), _state(26, 2, 0, 600)]

        deploying = dict((order['id'], order) for order in
                         planner.build_orders(
                             manifest, states, [], 1.0)['orders'])

        self.assertEqual('artillery_deploy', deploying[11]['combat_mode'])
        self.assertEqual('artillery_deploy', deploying[26]['combat_mode'])
        self.assertEqual(1, deploying[11]['route_index'])
        self.assertEqual(1, deploying[26]['route_index'])
        self.assertEqual(60.0, deploying[11]['move_position']['z'])
        self.assertEqual(540.0, deploying[26]['move_position']['z'])
        self.assertEqual(
            600.0,
            deploying[11]['move_position']['z'] +
            deploying[26]['move_position']['z'])
        self.assertFalse(manifest[0]['route']['waypoints'][1]['hold'])
        self.assertFalse(manifest[1]['route']['waypoints'][1]['hold'])

        states[0]['z'] = 60.0
        states[1]['z'] = 540.0
        holding = dict((order['id'], order) for order in
                       planner.build_orders(
                           manifest, states, [], 2.0)['orders'])

        self.assertEqual('artillery_hold', holding[11]['combat_mode'])
        self.assertEqual('artillery_hold', holding[26]['combat_mode'])
        self.assertEqual(0.0, holding[11]['throttle_override'])
        self.assertEqual(0.0, holding[26]['throttle_override'])
        self.assertEqual(deploying[11]['move_position'],
                         holding[11]['move_position'])
        self.assertEqual(deploying[26]['move_position'],
                         holding[26]['move_position'])

    def test_target_does_not_pull_spg_off_anchor(self):
        planner = BotPlanner()
        route = _route('field', [
            (0, 0, False), (0, 60, False),
            (0, 160, False), (0, 600, False),
        ])
        manifest = [_bot(11, 1, 0, route)]
        states = [_state(11, 1, 0, 60)]
        enemy = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts([{
            'observing_team': 1,
            'target_kind': 'human',
            'target_id': 2,
            'target_team': 2,
            'visible': True,
            'shootable_by_bot_ids': [11],
            'x': 0.0,
            'y': 0.0,
            'z': 500.0,
            'health': 1000,
            'max_health': 1000,
        }], planner.known_targets(states, [enemy]), 1.0))

        order = planner.build_orders(
            manifest, states, [enemy], 1.0)['orders'][0]

        self.assertEqual(2, order['target_id'])
        self.assertTrue(order['fire_allowed'])
        self.assertEqual('artillery_hold', order['combat_mode'])
        self.assertEqual({'x': 0.0, 'y': 0.0, 'z': 60.0},
                         order['move_position'])
        self.assertNotIn(order['combat_mode'], (
            'advance_contact', 'take_cover', 'cover_hold',
            'cover_peek', 'cover_return', 'flank'))

    def test_base_defense_preempts_artillery_hold(self):
        planner = BotPlanner()
        manifest = [_bot(11, 1, 0, _route('field', [
            (0, 0, False), (0, 60, False), (0, 600, False),
        ]))]
        states = [_state(11, 1, 0, 60)]
        defense = {
            'bases': {'1': [
                {'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': 0.0},
            ]},
            'states': {'1': {
                'points': 20,
                'time_left': 30.0,
                'invaders': 1,
                'stopped': False,
            }},
            'contributors': {'1': []},
        }

        order = planner.build_orders(
            manifest, states, [], 1.0, defense)['orders'][0]

        self.assertEqual('base_defense', order['combat_mode'])
        self.assertEqual('1:0', order['defense_base_id'])
        self.assertEqual({'x': 0.0, 'y': 0.0, 'z': 0.0},
                         order['move_position'])

    def test_base_defense_releases_one_excess_responder_per_delay(self):
        planner = BotPlanner()
        route = _route('defense-lane', [
            (0, -100, False), (0, 100, False), (0, 500, False),
        ])
        manifest = [
            _bot(11 + index, 1, index, route, 'mediumTank')
            for index in range(4)
        ]
        states = [
            _state(bot['id'], 1, index * 20, 0)
            for index, bot in enumerate(manifest)
        ]
        defense = {
            'bases': {'1': [
                {'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': -100.0},
            ]},
            'states': {'1': {
                'points': 20,
                'time_left': 60.0,
                'invaders': 3,
                'stopped': False,
            }},
            'contributors': {'1': []},
        }

        first = planner.build_orders(
            manifest, states, [], 1.0, defense)['orders']
        first_ids = {order['id'] for order in first
                     if order.get('defense_base_id') is not None}
        self.assertEqual(3, len(first_ids))

        defense['states']['1']['invaders'] = 1
        delayed = planner.build_orders(
            manifest, states, [], 2.0, defense)['orders']
        delayed_ids = {order['id'] for order in delayed
                       if order.get('defense_base_id') is not None}
        self.assertEqual(first_ids, delayed_ids)

        reduced_once = planner.build_orders(
            manifest, states, [], 5.1, defense)['orders']
        reduced_once_ids = {order['id'] for order in reduced_once
                            if order.get('defense_base_id') is not None}
        self.assertEqual(2, len(reduced_once_ids))
        self.assertTrue(reduced_once_ids < first_ids)

        reduced_twice = planner.build_orders(
            manifest, states, [], 8.2, defense)['orders']
        reduced_twice_ids = {order['id'] for order in reduced_twice
                             if order.get('defense_base_id') is not None}
        self.assertEqual(1, len(reduced_twice_ids))
        self.assertTrue(reduced_twice_ids < reduced_once_ids)

    def test_base_defense_keeps_an_arrived_responder_firing_on_capturer(self):
        planner = BotPlanner()
        route = _route('defense-lane', [
            (0, -100, False), (0, 100, False), (0, 500, False),
        ])
        manifest = [
            _bot(11 + index, 1, index, route, 'mediumTank')
            for index in range(3)
        ]
        states = [
            _weapon_state(_state(bot['id'], 1, 0, -100))
            for bot in manifest
        ]
        defense = {
            'bases': {'1': [
                {'id': '1:0', 'x': 0.0, 'y': 0.0, 'z': -100.0},
            ]},
            'states': {'1': {
                'points': 20,
                'time_left': 60.0,
                'invaders': 2,
                'stopped': False,
            }},
            'contributors': {'1': [
                {'kind': 'human', 'id': 2},
            ]},
        }
        initial = planner.build_orders(
            manifest, states, [], 1.0, defense)['orders']
        initial_ids = {order['id'] for order in initial
                       if order.get('defense_base_id') is not None}
        self.assertEqual({11, 12}, initial_ids)

        player = {'id': 2, 'team': 2, 'alive': True}
        contact = _contact(2, 0, -80, [11])
        self.assertEqual(1, planner.report_contacts(
            [contact], planner.known_targets(states, [player]), 2.0))
        defense['states']['1']['invaders'] = 1
        planner.build_orders(manifest, states, [player], 2.0, defense)
        reduced = planner.build_orders(
            manifest, states, [player], 5.1, defense)['orders']
        retained_ids = {order['id'] for order in reduced
                        if order.get('defense_base_id') is not None}

        self.assertEqual({11}, retained_ids)
        retained = next(order for order in reduced if order['id'] == 11)
        self.assertEqual(2, retained['target_id'])
        self.assertTrue(retained['fire_allowed'])

    def test_spg_is_never_a_pressured_route_donor(self):
        planner = BotPlanner()
        route_a = _route('a', [
            (-100, 0, False), (-100, 80, False),
            (-100, 500, False),
        ])
        route_b = _route('b', [
            (100, 0, False), (100, 80, False),
            (100, 500, False),
        ])
        manifest = [
            _bot(11, 1, 0, route_a, 'SPG', {
                'support': 1.0, 'flanker': 1.0, 'scout': 1.0,
            }),
            _bot(12, 1, 1, route_a, 'mediumTank', {
                'support': 0.0, 'flanker': 0.0, 'scout': 0.0,
                'brawler': 1.0,
            }),
            _bot(13, 1, 2, route_b, 'mediumTank', {
                'support': 0.5,
            }),
            _bot(14, 1, 3, route_a, 'mediumTank', {
                'support': 1.0, 'flanker': 1.0,
            }),
        ]
        states = [
            _state(11, 1, -100, 0),
            _state(12, 1, -100, 0),
            _state(13, 1, 100, 0),
            _state(14, 1, -100, 0),
        ]
        enemy = {'id': 2, 'team': 2, 'alive': True}
        self.assertEqual(1, planner.report_contacts([{
            'observing_team': 1,
            'target_kind': 'human',
            'target_id': 2,
            'target_team': 2,
            'visible': True,
            'shootable_by_bot_ids': [],
            'x': 100.0,
            'y': 0.0,
            'z': 250.0,
            'health': 1000,
            'max_health': 1000,
        }], planner.known_targets(states, [enemy]), 1.0))

        orders = dict((order['id'], order) for order in
                      planner.build_orders(
                          manifest, states, [enemy], 1.0)['orders'])

        self.assertEqual('a', orders[11]['route_id'])
        self.assertEqual('b', orders[13]['route_id'])
        self.assertEqual(1, sum(
            (planner._travel_tasks.get(bot_id,{}).get('target_route') or {}).get('id') == 'b' for bot_id in (12, 14)))

    def test_immobile_line_holders_count_but_cannot_be_route_donors(self):
        source = _route('source', [
            (-100, 0, False), (-100, 100, False), (-100, 500, False),
        ])
        target = _route('target', [
            (100, 0, False), (100, 100, False), (100, 500, False),
        ])
        enemy = {'id': 2, 'team': 2, 'alive': True}
        conditions = (
            ('no_pose', {'world_pose': False}, [11], None),
            ('engine', {'critical': {'destroyed': ['engineHealth']}},
             [11], 12),
            ('left_track', {
                'critical': {'destroyed': ['leftTrackHealth']}},
             [11], 12),
            ('right_track', {
                'critical': {'destroyed': ['rightTrackHealth']}},
             [11], 12),
            ('damaged_engine', {'critical': {
                'destroyed': [],
                'devices': [{
                    'name': 'engineHealth', 'state': 'critical',
                }],
            }}, [11], 11),
            ('damaged_track', {'critical': {
                'destroyed': [],
                'devices': [{
                    'name': 'rightTrackHealth', 'state': 'critical',
                }],
            }}, [11], 11),
            ('track_without_lane', {
                'critical': {'destroyed': ['leftTrackHealth']}},
             [], None),
        )

        for unused_name, state_change, observers, donor_id in conditions:
            with self.subTest(condition=unused_name):
                planner = BotPlanner()
                manifest = [
                    _bot(11, 1, 0, source, 'mediumTank', {
                        'support': 1.0, 'flanker': 1.0,
                    }),
                    _bot(12, 1, 1, source, 'heavyTank', {
                        'support': 0.0, 'flanker': 0.0,
                        'brawler': 1.0,
                    }),
                    _bot(13, 1, 2, target, 'mediumTank', {
                        'support': 0.5,
                    }),
                ]
                states = [
                    _weapon_state(_state(11, 1, -100, 0)),
                    _weapon_state(_state(12, 1, -100, 0)),
                    _weapon_state(_state(13, 1, 100, 0)),
                ]
                states[0].update(state_change)
                contact = _contact(2, 100, 250, observers)
                self.assertEqual(1, planner.report_contacts(
                    [contact], planner.known_targets(states, [enemy]), 1.0))

                orders = dict((order['id'], order) for order in
                              planner.build_orders(
                                  manifest, states, [enemy], 1.0)['orders'])

                self.assertEqual(
                    'target' if donor_id == 11 else 'source',
                    (planner._travel_tasks.get(11,{}).get('target_route') or {}).get('id',orders[11]['route_id']))
                self.assertEqual(
                    'target' if donor_id == 12 else 'source',
                    (planner._travel_tasks.get(12,{}).get('target_route') or {}).get('id',orders[12]['route_id']))

    def test_rebalance_keeps_scouts_off_an_incompatible_heavy_lane(self):
        planner = BotPlanner()
        middle = _route('middle', [
            (0, 0, False), (0, 100, False), (0, 500, False),
        ], capacity=4,
            class_weights={'lightTank': 1.0, 'heavyTank': 0.02},
            role_weights={'scout': 1.0})
        heavy = _route('heavy', [
            (100, 0, False), (100, 100, False), (100, 500, False),
        ], capacity=6,
            class_weights={'lightTank': 0.12, 'heavyTank': 1.0},
            role_weights={'brawler': 1.0})
        manifest = [
            _bot(20 + value, 1, value, middle, 'lightTank', {'scout': 1.0})
            for value in range(4)
        ] + [
            _bot(30 + value, 1, 4 + value, heavy, 'heavyTank',
                 {'brawler': 1.0})
            for value in range(5)
        ]
        states = [
            _state(bot['id'], 1,
                   0 if bot['profile']['class_tag'] == 'lightTank' else 100,
                   0)
            for bot in manifest
        ]
        bots = planner._alive_bots(manifest, states)
        contacts = [{
            'position': {'x': 100.0, 'y': 0.0, 'z': 250.0},
            'health': 1000.0,
            'max_health': 1000.0,
        } for unused in range(4)]

        planner._rebalance_routes(1, bots, contacts, 1.0)

        self.assertTrue(all(
            planner._route_assignments[bot_id]['route']['id'] == 'middle'
            for bot_id in range(20, 24)))

    def test_rebalance_reserves_target_lane_without_class_hard_cap(self):
        for target_tag, expected_move in (('heavyTank', True), ('mediumTank', True)):
            planner=BotPlanner()
            source=_route('source',[(-100,0,False),(-100,100,False),(-100,500,False)],capacity=3)
            target=_route('target',[(100,0,False),(100,100,False),(100,500,False)],capacity=3)
            manifest=[_bot(41,1,0,source,'mediumTank',{'support':1.0}),
                      _bot(42,1,1,source,'mediumTank',{'support':0.9})]
            manifest.extend(_bot(i,1,i-41,target,target_tag,{'support':1.0}) for i in (43,44,45))
            states=[_state(i,1,-100 if i<43 else 100,0) for i in range(41,46)]
            bots=planner._alive_bots(manifest,states)
            contacts=[{'position':{'x':100.0,'y':0.0,'z':250.0},'health':1000.0,'max_health':1000.0} for _ in range(4)]
            planner._rebalance_routes(1,bots,contacts,1.0)
            moved=any((planner._travel_tasks.get(i,{}).get('target_route') or {}).get('id')=='target' for i in (41,42))
            self.assertEqual(expected_move,moved)

    def test_spg_does_not_fill_frontline_capacity_during_rebalance(self):
        planner = BotPlanner()
        source = _route('source', [
            (-100, 0, False), (-100, 100, False), (-100, 500, False),
        ], capacity=4)
        target = _route('target', [
            (100, 0, False), (100, 100, False), (100, 500, False),
        ], capacity=1)
        manifest = [
            _bot(41, 1, 0, source, 'mediumTank', {'support': 1.0}),
            _bot(42, 1, 1, source, 'mediumTank', {'support': 0.9}),
            _bot(43, 1, 2, target, 'SPG', {'artillery': 1.0}),
        ]
        states = [
            _state(41, 1, -100, 0),
            _state(42, 1, -100, 0),
            _state(43, 1, 100, 0),
        ]
        bots = planner._alive_bots(manifest, states)
        contacts = [{
            'position': {'x': 100.0, 'y': 0.0, 'z': 250.0},
            'health': 1000.0,
            'max_health': 1000.0,
        }]

        planner._rebalance_routes(1, bots, contacts, 1.0)
        donor_id = next(
            bot_id for bot_id in (41, 42)
            if (planner._travel_tasks.get(bot_id,{}).get('target_route') or {}).get('id') == 'target')
        donor = next(bot for bot in bots if bot['id'] == donor_id)
        planner._route(donor, 1.1)
        planner._route_states.setdefault(donor_id,{})['index'] = 1
        planner._rebalance_routes(1, bots, contacts, 5.0)
        planner._rebalance_routes(1, bots, contacts, 9.0)

        assigned = dict((bot_id, value['route']['id'])
                        for bot_id, value in
                        planner._route_assignments.items())
        self.assertEqual('target', assigned[43])
        self.assertEqual(1, sum(
            (planner._travel_tasks.get(bot_id,{}).get('target_route') or {}).get('id') == 'target' for bot_id in (41,42)))
        self.assertEqual(1, planner._route_states[donor_id]['index'])
        self.assertGreater(
            planner._travel_tasks[donor_id]['until'], 9.0)


class ServerHumanRamNormalTests(unittest.TestCase):
    @staticmethod
    def _body(player_id, z):
        return {
            'id': player_id, 'vehicle': 'ussr:R11_MS-1',
            'x': 0.0, 'y': 0.0, 'z': float(z), 'yaw': 0.0,
            'pitch': 0.0, 'roll': 0.0,
            'shape': (1.5, 3.5, -0.8, 2.0),
        }

    def test_worker_probe_freezes_first_impact_normal(self):
        state = BattleState()

        request = state._queue_human_ram_probe(
            (1, 2), self._body(1, 0.0), self._body(2, 0.5),
            123000, (0.0, -2.0, 6.5))

        self.assertEqual([0.0, -1.0], request['contact_normal'])
        self.assertEqual([0.0, -1.0],
                         state._human_ram_probe_snapshot()[0][
                             'contact_normal'])

    def test_worker_probe_rejects_a_normal_facing_away_from_first_body(self):
        state = BattleState()

        request = state._queue_human_ram_probe(
            (1, 2), self._body(1, 0.0), self._body(2, 0.5),
            123000, (0.0, 1.0, 6.5))

        self.assertIsNone(request)

    def test_player_receipt_preserves_frozen_first_impact_normal(self):
        state = BattleState()
        state.bot_states[11] = {'id': 11}
        state.bot_state_revision = 1
        state.bot_state_time_us = 123000
        state.human_collision_profiles[1] = {
            'shape': (1.5, 3.5, -0.8, 2.0),
            'ram_profile': {
                'spall_coefficient': 1.0, 'ramming_bonus': 0.0},
        }
        player = Player(
            1, object(), ('127.0.0.1', 1), team=1, slot=0)
        raw = {
            'seq': 1, 'bot_id': 11, 'bot_state_revision': 1,
            'presentation_time_us': 123000,
            'native_contact_time_us': 123000,
            'contact_x': 0.0, 'contact_y': 0.0, 'contact_z': 3.0,
            'contact_normal_x': 0.0, 'contact_normal_z': -1.0,
            'contact_armor_player': 80.0, 'contact_armor_bot': 100.0,
            'contact_spall_player': 1.0, 'contact_bonus_player': 0.0,
            'contact_screened_player': False,
            'contact_screened_bot': False,
            'x': 0.0, 'y': 0.0, 'z': 0.0, 'yaw': 0.0,
            'pitch': 0.0, 'roll': 0.0,
            'vx': 0.0, 'vy': 0.0, 'vz': 10.0,
            'bot_vx': 0.0, 'bot_vy': 0.0, 'bot_vz': 0.0,
        }

        normalized, reason = state._validate_ram_contact(player, raw)

        self.assertIsNone(reason)
        self.assertEqual((0.0, -1.0), (
            normalized['contact_normal_x'],
            normalized['contact_normal_z']))

    def test_player_receipt_allows_one_frame_contact_point_pose_skew(self):
        state = BattleState()
        state.bot_states[11] = {'id': 11}
        state.bot_state_revision = 1
        state.bot_state_time_us = 123000
        state.human_collision_profiles[1] = {
            'shape': (1.5, 3.5, -0.8, 2.0),
            'ram_profile': {
                'spall_coefficient': 1.0, 'ramming_bonus': 0.0},
        }
        player = Player(
            1, object(), ('127.0.0.1', 1), team=1, slot=0)
        raw = {
            'seq': 1, 'bot_id': 11, 'bot_state_revision': 1,
            'presentation_time_us': 123000,
            'native_contact_time_us': 123000,
            'contact_x': 0.0, 'contact_y': 0.0, 'contact_z': 4.0,
            'contact_normal_x': 0.0, 'contact_normal_z': -1.0,
            'contact_armor_player': 80.0, 'contact_armor_bot': 100.0,
            'contact_spall_player': 1.0, 'contact_bonus_player': 0.0,
            'contact_screened_player': False,
            'contact_screened_bot': False,
            'x': 0.0, 'y': 0.0, 'z': 0.0, 'yaw': 0.0,
            'pitch': 0.0, 'roll': 0.0,
            'vx': 0.0, 'vy': 0.0, 'vz': 10.0,
            'bot_vx': 0.0, 'bot_vy': 0.0, 'bot_vz': 0.0,
        }

        normalized, reason = state._validate_ram_contact(player, raw)
        self.assertIsNone(reason)
        self.assertIsNotNone(normalized)

        remote = dict(raw, contact_z=4.5)
        normalized, reason = state._validate_ram_contact(player, remote)
        self.assertIsNone(normalized)
        self.assertEqual('contact_outside_player_body', reason)

    def test_player_receipt_rejects_flipped_or_perpendicular_normal(self):
        state = BattleState()
        state.bot_states[11] = {'id': 11}
        state.bot_state_revision = 1
        state.bot_state_time_us = 123000
        state.human_collision_profiles[1] = {
            'shape': (1.5, 3.5, -0.8, 2.0),
            'ram_profile': {
                'spall_coefficient': 1.0, 'ramming_bonus': 0.0},
        }
        player = Player(
            1, object(), ('127.0.0.1', 1), team=1, slot=0)
        raw = {
            'seq': 1, 'bot_id': 11, 'bot_state_revision': 1,
            'presentation_time_us': 123000,
            'native_contact_time_us': 123000,
            'contact_x': 0.0, 'contact_y': 0.0, 'contact_z': 3.0,
            'contact_normal_x': 0.0, 'contact_normal_z': -1.0,
            'contact_armor_player': 80.0, 'contact_armor_bot': 100.0,
            'contact_spall_player': 1.0, 'contact_bonus_player': 0.0,
            'contact_screened_player': False,
            'contact_screened_bot': False,
            'x': 0.0, 'y': 0.0, 'z': 0.0, 'yaw': 0.0,
            'pitch': 0.0, 'roll': 0.0,
            'vx': 0.0, 'vy': 0.0, 'vz': 10.0,
            'bot_vx': 0.0, 'bot_vy': 0.0, 'bot_vz': 0.0,
        }

        for normal in ((0.0, 1.0), (1.0, 0.0)):
            candidate = dict(
                raw, contact_normal_x=normal[0],
                contact_normal_z=normal[1])
            normalized, reason = state._validate_ram_contact(
                player, candidate)

            self.assertIsNone(normalized)
            self.assertEqual('contact_normal_mismatch', reason)


if __name__ == '__main__':
    unittest.main()
