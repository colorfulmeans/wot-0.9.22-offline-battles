"""Report 202110: lane publication, executed aiming and capture defence."""
import copy
import math
import unittest

import test_port_0922_server_bot_ai as ai
import test_port_0922_bot_runtime as runtime_fixtures
import test_port_0922_bot_state_codec as wire
from gui.mods.offline_lan_0922 import bot_state_codec as codec


class TargetEvidenceTests(unittest.TestCase):
    def setUp(self):
        ai.ServerBotTacticsTests.setUp(self)
        self.planner = ai.BotPlanner()
        self.planner._capable = lambda *args: True
        self.players = [dict(id=i, team=2, alive=True) for i in (2, 3)]
        self.contacts = [ai._contact(2, 0, 100, [11]), ai._contact(3, 10, 110, [11])]

    def orders(self, now, defense=None):
        self.planner.report_contacts(self.contacts,
            self.planner.known_targets(self.states, self.players), now)
        return self.planner.build_orders(self.manifest, self.states, self.players,
                                         now, defense)['orders'][0]

    def aim(self, error, aligned=False):
        self.states[0].update(aim_feedback_kind='human', aim_feedback_id=2,
            aim_feedback_error=error, aim_feedback_aligned=aligned)

    def test_damaged_turret_gets_time_for_actual_progress_then_timeout(self):
        self.assertEqual(2, self.orders(1)['target_id'])
        self.contacts[1]['health'] = 10
        for now, error in ((3.1, 2.6), (6, 1.5), (9, .4)):
            self.aim(error)
            self.assertEqual(2, self.orders(now)['target_id'])
        self.assertEqual(3, self.orders(15.1)['target_id'])

    def test_first_shot_releases_ordinary_aim_commitment(self):
        self.orders(1)
        self.aim(.1)
        self.contacts[1]['health'] = 10
        self.assertEqual(2, self.orders(3.1)['target_id'])
        self.states[0]['fire_seq'] = 1
        self.assertEqual(3, self.orders(5.2)['target_id'])

    def test_attacker_still_preempts_an_executed_aim(self):
        self.orders(1)
        self.aim(2.6)
        self.planner.report_damage(11, 'player', 3, 100, 1.1)
        self.assertEqual(3, self.orders(1.2)['target_id'])

    def test_idle_fire_timer_cannot_cancel_a_progressing_slow_aim(self):
        self.orders(1)
        bot = self.planner._alive_bots(self.manifest, self.states, self.planner.tactics)[0]
        bot['state'].update(aim_feedback_kind='human', aim_feedback_id=2,
            aim_feedback_error=2.6, aim_feedback_aligned=False)
        order = dict(combat_mode='engage', throttle_override=0.,
            target_kind='human', target_id=2, fire_allowed=True)
        self.planner._release_unproductive_firing_hold(order, bot,
            dict(x=0, y=0, z=100), dict(x=0, y=0, z=0), 3)
        self.assertEqual('executed_aim_in_progress',
            order['tactical_evidence']['firing_hold']['reason'])
        self.assertEqual('engage', order['combat_mode'])
        bot['state']['aim_feedback_error'] = .5
        self.planner._release_unproductive_firing_hold(order, bot,
            dict(x=0, y=0, z=100), dict(x=0, y=0, z=0), 8)
        self.assertNotIn(11, self.planner._firing_holds)
        self.planner._release_unproductive_firing_hold(order, bot,
            dict(x=0, y=0, z=100), dict(x=0, y=0, z=0), 15)
        self.assertIn(11, self.planner._firing_holds)

    def test_close_threat_still_preempts(self):
        self.orders(1)
        self.aim(2.6)
        self.contacts[1].update(x=0, z=20)
        self.assertEqual(3, self.orders(1.1)['target_id'])

    def test_lane_loss_is_bounded_and_never_grants_fire(self):
        self.orders(1)
        self.contacts[0]['shootable_by_bot_ids'] = []
        held = self.orders(1.1)
        self.assertEqual(2, held['target_id'])
        self.assertFalse(held['fire_allowed'])
        self.assertEqual(3, self.orders(3.2)['target_id'])

    def test_target_death_releases_aim_immediately(self):
        self.orders(1)
        self.aim(2.6)
        self.players[0]['alive'] = False
        self.contacts = self.contacts[1:]
        self.assertEqual(3, self.orders(1.2)['target_id'])

    def test_capturer_preempts_ordinary_target_and_diagnostic_matches(self):
        self.orders(1)
        bot = self.planner._alive_bots(self.manifest, self.states, self.planner.tactics)[0]
        contacts = self.planner._prune_contacts(
            self.planner.known_targets(self.states, self.players), 1)[1]
        defense = dict(contributors={'1': [dict(kind='human', id=3)]})
        result = self.planner._prioritize_base_invaders(1, [bot], contacts,
            {11: contacts[0]}, {11: dict(point=dict(x=0,y=0,z=0),radius=50)}, defense, 1.1)
        self.assertEqual(3, result[11]['id'])
        decision = self.planner._target_decisions[11]
        self.assertEqual(('human', 3), decision['selected'])
        self.assertEqual('base_capturer', decision['outcome'])
        self.assertGreater(self.planner._target_assignments[11]['until'], 1.1)
        lease = copy.deepcopy(self.planner._target_assignments[11])
        self.planner._prioritize_base_invaders(1, [bot], contacts, result,
            {11: dict(point=dict(x=0,y=0,z=0),radius=50)}, defense, 1.2)
        self.assertEqual(lease, self.planner._target_assignments[11])

    def test_capturer_does_not_bypass_wall_or_radio_expiry(self):
        self.orders(1)
        bot = self.planner._alive_bots(self.manifest, self.states, self.planner.tactics)[0]
        contacts = self.planner._prune_contacts(
            self.planner.known_targets(self.states, self.players), 1)[1]
        target = next(c for c in contacts if c['id'] == 3)
        target['shootable_by_bot_ids'] = []
        selected = next(c for c in contacts if c['id'] == 2)
        defense = dict(contributors={'1': [dict(kind='human', id=3)]})
        result = self.planner._prioritize_base_invaders(1, [bot], contacts,
            {11: selected}, {11: dict(point=dict(x=0,y=0,z=0),radius=50)}, defense, 1.1)
        self.assertEqual(2, result[11]['id'])

    def test_base_priority_preempts_recent_attacker_only_inside_own_circle(self):
        self.orders(1)
        self.planner.report_damage(11, 'player', 2, 100, 1.1)
        self.orders(1.2)
        bot = self.planner._alive_bots(self.manifest, self.states, self.planner.tactics)[0]
        contacts = self.planner._prune_contacts(
            self.planner.known_targets(self.states, self.players), 1.2)[1]
        current = next(c for c in contacts if c['id'] == 2)
        result = self.planner._prioritize_base_invaders(1, [bot], contacts, {11: current},
            {11: dict(point=dict(x=0,y=0,z=0),radius=50)}, dict(contributors={'1': [dict(kind='human', id=3)]}), 1.2)
        self.assertEqual(3, result[11]['id'])
        self.assertEqual('proved_capturer_lane',
            self.planner._target_decisions[11]['base_priority']['reason'])

    def test_working_defender_stays_but_idle_defender_is_eventually_replaced(self):
        manifest = [ai._bot(i, 1, i-11, self.route, 'mediumTank') for i in (11, 12, 13)]
        states = [ai._state(i, 1, 70 if i == 11 else 500+i, 0) for i in (11, 12, 13)]
        bots = self.planner._alive_bots(manifest, states, self.planner.tactics)
        state = bots[0]['state']
        defense = dict(bases={'1': [dict(id='1:0', x=0, y=0, z=0)]},
            states={'1': dict(invaders=1, time_left=60)},
            contributors={'1': [dict(kind='human', id=2)]})
        contacts = {1: [dict(id=2, target_kind='human', visible=True,
            position=dict(x=0, y=0, z=0), shootable_by_bot_ids=[11])], 2: []}
        update = lambda now: self.planner._update_base_defense(bots, contacts, defense, now)[1]
        self.assertIn(11, update(1))
        update(2)
        state.update(fire_seq=1, reload_time=10)
        self.assertIn(11, update(4))
        state['reload_time'] = 1
        self.assertIn(11, update(14))
        state['reload_time'] = 0
        self.assertNotIn(11, update(25))

    def test_defender_credits_shots_and_decreasing_reload_not_standing(self):
        self.orders(1)
        bot = self.planner._alive_bots(self.manifest, self.states, self.planner.tactics)[0]
        contact = dict(id=2, target_kind='human', visible=True,
            position=dict(x=0, y=0, z=100), shootable_by_bot_ids=[11])
        record = {}
        progress = lambda now: self.planner._defense_combat_progress(
            bot, record, [contact], {('human', 2)}, now)
        self.assertFalse(progress(1))
        bot['state'].update(fire_seq=1, reload_time=10)
        self.assertTrue(progress(2))
        bot['state']['reload_time'] = 5
        self.assertTrue(progress(7))
        self.assertFalse(progress(8))
        bot['state']['reload_time'] = 0
        self.assertFalse(progress(12))
        bot['state'].update(aim_feedback_kind='human', aim_feedback_id=2,
            aim_feedback_error=2.0)
        self.assertTrue(progress(13))
        self.assertFalse(progress(14))
        bot['state']['aim_feedback_error'] = 1.0
        self.assertTrue(progress(15))
        contact['position']['z'] = 2000
        bot['state']['fire_seq'] = 2
        self.assertFalse(progress(16))

    def test_real_aim_feedback_survives_wire_and_server_admission(self):
        runtime = runtime_fixtures._load()
        raw = wire._bot_state(burst_next_index=1)
        raw.update(turret_yaw=0., gun_pitch=.1,
            _diagnostic_aim_intent=dict(target_kind='bot', target_id=19,
                turret_yaw=2.6, gun_pitch=.2), gun_aligned=False)
        raw.update(runtime._aim_feedback_record(raw))
        decoded = codec.decode_row(codec.encode_row(raw), wire.STATIC)
        self.assertEqual(('bot', 19, False), tuple(decoded[k] for k in (
            'aim_feedback_kind', 'aim_feedback_id', 'aim_feedback_aligned')))
        self.assertAlmostEqual(2.6, decoded['aim_feedback_error'], places=4)
        identity = dict(id=17, team=1, slot=0, name='KV13', max_health=1200)
        admitted = ai.BattleState._sanitize_bot_state(decoded, identity, None, trusted=True)
        self.assertEqual(19, admitted['aim_feedback_id'])
        raw.update(alive=False)
        raw.update(runtime._aim_feedback_record(raw))
        dead = codec.decode_row(codec.encode_row(raw), wire.STATIC)
        self.assertEqual(('', 0, False), tuple(dead[k] for k in (
            'aim_feedback_kind', 'aim_feedback_id', 'aim_feedback_aligned')))


class LanePublicationTests(unittest.TestCase):
    def setUp(self):
        self.module = runtime_fixtures._load()
        self.runtime = self.module.BotRuntime(1)
        self.runtime.states = {11: dict(id=11, team=1, alive=True)}
        self.key = (1, 'bot', 19)
        self.target = dict(id=19, network_id=19, kind='bot', team=2,
            alive=True, x=0., y=0., z=100., health=500, max_health=1000)
        self.runtime._renew_team_spot(self.key, 1.)
        self.runtime._visible_target_poses[self.key] = dict(self.target)
        self.runtime._server_orders[11] = dict(target_kind='bot', target_id=19)
        self.radio_left = 5.
        self.runtime._radio_network = type('Radio', (), {
            'actors': {('bot', 11): (1,)},
            'summaries': lambda unused, pairs, now, include_sources=False: tuple(
                (self.radio_left, False, ()) if include_sources else (self.radio_left, False)
                for pair in pairs),
            'contact': lambda *args: (self.radio_left, False, None)})()
        self.runtime._shot_los_cache[(11, 'bot', 19)] = (1.1, True)

    def pack(self, now=1.2, direct=False):
        aggregate = {self.key: [False, set(), dict(self.target), set(),
                               {11} if direct else set()]}
        self.runtime._merge_observation_shot_lanes(aggregate, {}, now)
        return self.runtime._pack_observations(aggregate, now)[0]

    def test_fresh_native_lane_does_not_require_half_second_direct_spot(self):
        row = self.pack()
        self.assertFalse(row['fresh'])
        self.assertEqual([11], row['shootable_by_bot_ids'])
        self.assertEqual('published', self.runtime.states[11]['_lane_publication_evidence']['reason'])

    def test_all_negative_gates_have_terminal_publication_reasons(self):
        for cause in ('radio', 'native', 'expired', 'unspotted'):
            with self.subTest(cause=cause):
                self.setUp()
                now = 1.2
                if cause == 'radio': self.radio_left = 0.
                if cause == 'native': self.runtime._shot_los_cache[(11, 'bot', 19)] = (1.1, False)
                if cause == 'expired': now = 4.
                if cause == 'unspotted': now = 30.
                row = self.pack(now)
                self.assertEqual([], row['shootable_by_bot_ids'])
                self.assertNotEqual('published', self.runtime.states[11]['_lane_publication_evidence']['reason'])

    def test_mechanical_retry_cooldown_is_not_a_negative_native_lane(self):
        self.runtime._gun_angle_rejected = lambda *args: True
        row = self.pack()
        self.assertEqual([11], row['shootable_by_bot_ids'])
        self.assertEqual('published',self.runtime.states[11]['_lane_publication_evidence']['reason'])
        self.assertTrue(self.runtime.states[11]['_lane_publication_evidence']['mechanical_retry_suppressed'])

    def test_expiry_publishes_pending_only_for_selected_positive_lane(self):
        row = self.pack(4.)
        self.assertEqual([], row['shootable_by_bot_ids'])
        self.assertEqual([11], row['pending_lane_by_bot_ids'])
        self.runtime._shot_los_cache[(11, 'bot', 19)] = (3.9, False)
        self.assertEqual([], self.pack(4.)['pending_lane_by_bot_ids'])
        self.runtime._shot_los_cache[(11, 'bot', 19)] = (1.1, True)
        self.radio_left = 0.
        self.assertEqual([], self.pack(4.)['pending_lane_by_bot_ids'])
        self.radio_left = 5.
        self.assertEqual([], self.pack(30.)['pending_lane_by_bot_ids'])
        self.runtime._server_orders.clear()
        self.assertEqual([], self.pack(4.)['pending_lane_by_bot_ids'])

    def test_final_native_fire_veto_remains_authoritative(self):
        self.runtime._shot_los_cache[(11, 'bot', 19)] = (1.2, False)
        command, target = self.runtime._apply_blocked_direct_aim(
            self.runtime.states[11], dict(target_id=19, fire_allowed=True), self.target, 1.2)
        self.assertFalse(command['fire_allowed'])
        self.assertIs(target, self.target)

    def test_server_relay_retains_independent_lane_without_direct_observer(self):
        fixture = runtime_fixtures.ServerBotObservationRelayTests
        state, unused, unused2 = fixture._server()
        message = fixture._message(state.round_id)
        contact = message['contacts'][0]
        contact.update(visible_by_bot_ids=[], visible_by_player_ids=[],
            shootable_by_bot_ids=[11], fresh=False,
            radio_recipients=[dict(kind='bot', id=11, time_left=4.)])
        result = state.update_bot_observation(ai.SIMULATION_WORKER_AUTHORITY_ID, message)
        self.assertIsInstance(result, dict)
        self.assertEqual([11], result['contacts'][0]['shootable_by_bot_ids'])
        self.assertFalse(result['contacts'][0]['fresh'])
        self.assertEqual([11], state.bot_planner._contacts[2][('human', 2)]['shootable_by_bot_ids'])
        contact.update(shootable_by_bot_ids=[], pending_lane_by_bot_ids=[11, -1, 'bad', 999])
        result = state.update_bot_observation(ai.SIMULATION_WORKER_AUTHORITY_ID, message)
        self.assertIsInstance(result, dict)
        self.assertEqual([11], state.bot_planner._contacts[2][('human', 2)]['pending_lane_by_bot_ids'])
        self.assertEqual([], state.bot_planner._contacts[2][('human', 2)]['shootable_by_bot_ids'])

    def test_absent_contact_replaces_old_publication_diagnostic(self):
        self.pack()
        self.runtime._pack_observations({}, 2.)
        self.assertEqual('no_observation_row',
            self.runtime.states[11]['_lane_publication_evidence']['reason'])

    def test_aim_feedback_malformed_groups_are_contained(self):
        for fields in (dict(aim_feedback_kind='bot'),
                       dict(aim_feedback_kind='other', aim_feedback_id=2,
                            aim_feedback_aligned=False, aim_feedback_error=0),
                       dict(aim_feedback_kind='bot', aim_feedback_id=2,
                            aim_feedback_aligned=False, aim_feedback_error=-1)):
            with self.subTest(fields=fields), self.assertRaises(codec.BotStateCodecError):
                codec.encode_row(wire._bot_state(**fields))

    def test_diagnostics_do_not_change_execution_or_call_native_probes(self):
        state = dict(id=11, x=0., y=0., z=0.)
        command = dict(recovery_mode='short_reverse_escape', move_position=(4., 0., 0.))
        for now, x in ((1., 0.), (2., .2), (3., 0.), (10., .1)):
            state['x'] = x
            self.runtime._record_execution_window(state, command, -1., .5, now)
        previous = state['_previous_execution_window']
        self.assertEqual(3, previous['samples'])
        self.assertAlmostEqual(.4, previous['travel'])
        self.assertAlmostEqual(0., previous['net'])
        self.assertEqual(3, previous['reverse'])
        self.assertEqual('short_reverse_escape', command['recovery_mode'])


if __name__ == '__main__':
    unittest.main()
