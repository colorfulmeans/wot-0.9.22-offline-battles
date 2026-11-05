"""Foreground policy completeness, native-budget and local-LAN isolation.

These are executable source contracts, not Windows #1513 gameplay evidence.
The recorded support case uses the real player grid/local-height algorithms.
"""
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.player_control.artillery import Artillery
from gui.mods.offline_lan_0922.player_control.observations import public_allies
from gui.mods.offline_lan_0922.player_control.strategy import CombatPolicy, Strategy
from gui.mods.offline_lan_0922.player_control.targeting import TargetSelection
from gui.mods.offline_lan_0922.player_control.tactics import CombatTactics


def state(now=0., position=(0., 0., 0.), identity=1, **fields):
    result = dict(id=identity, engine_id=identity, position=position, now=now,
                  yaw=0., speed=0., half_length=2., half_width=1.,
                  health=1000, max_health=1000)
    result.update(fields)
    return result


def contact(identity, position, **fields):
    result = dict(id=identity, position=position, health=1000, max_health=1000,
                  alive=True, visible=True, class_tag='heavyTank')
    result.update(fields)
    return result


class TargetSelectionTests(unittest.TestCase):
    def test_fresh_acquisition_values_remaining_health_not_only_distance(self):
        policy = TargetSelection()
        ids, interrupt = policy.rank([contact(8, (0., 0., 200.)),
            contact(9, (0., 0., 220.), health=100)], (0., 0., 0.), None, 0.)
        self.assertEqual([9, 8], ids)
        self.assertFalse(interrupt)

    def test_close_threat_interrupts_a_valid_distant_lock(self):
        policy = TargetSelection()
        ids, interrupt = policy.rank([contact(8, (0., 0., 200.)),
            contact(9, (0., 0., 25.))], (0., 0., 0.), 8, 0.)
        self.assertEqual(9, ids[0])
        self.assertTrue(interrupt)
        self.assertEqual('close_threat', policy.receipt['reason'])

    def test_accepted_attacker_is_prioritised_only_while_visible_and_recent(self):
        policy = TargetSelection()
        policy.attacked(9, 1.)
        rows = [contact(8, (0., 0., 180.)), contact(9, (0., 0., 200.))]
        self.assertEqual(([9, 8], True), policy.rank(rows, (0., 0., 0.), 8, 2.))
        rows[1]['visible'] = False
        self.assertEqual(([8], False), policy.rank(rows, (0., 0., 0.), 8, 3.))
        rows[1]['visible'] = True
        self.assertEqual(([8, 9], False), policy.rank(rows, (0., 0., 0.), 8, 8.))

    def test_base_invader_preempts_incidental_target_during_alarm(self):
        policy = TargetSelection()
        rows = [contact(8, (200., 0., 100.)), contact(9, (10., 0., 10.))]
        ids, interrupt = policy.rank(rows, (0., 0., 300.), 8, 0., home=(0., 0.),
                                     base=dict(points=35, invaders=1))
        self.assertEqual(9, ids[0])
        self.assertTrue(interrupt)
        self.assertEqual('base_invader', policy.receipt['reason'])

    def test_ordinary_score_improvement_does_not_discard_ordered_point_lock(self):
        policy = TargetSelection()
        rows = [contact(8, (0., 0., 300.)), contact(9, (0., 0., 130.), health=1)]
        self.assertEqual(([8, 9], False), policy.rank(rows, (0., 0., 0.), 8, 0.))
        self.assertEqual('preserve_ordered_lock', policy.receipt['reason'])

    def test_two_players_do_not_share_recent_hits_or_priority_state(self):
        first, second = TargetSelection(), TargetSelection()
        first.attacked(9, 0.)
        rows = [contact(8, (0., 0., 150.)), contact(9, (0., 0., 160.))]
        self.assertEqual([9, 8], first.rank(rows, (0., 0., 0.), 8, 1.)[0])
        self.assertEqual([8, 9], second.rank(rows, (0., 0., 0.), 8, 1.)[0])
        self.assertFalse(second.recent_hits)


class RosterOwnershipTests(unittest.TestCase):
    def owner(self, players=None, bots=None):
        return SimpleNamespace(client=SimpleNamespace(player_id=7, team=1),
            _start_message=dict(round_id=4, players=players or [dict(id=7, team=1)],
                                bots=[] if bots is None else bots),
            _records={}, _bots_ready_reported=False, _pending_bot_create_order=[],
            _pending_bot_creates={}, _last_snapshot={})

    def test_zero_bot_room_does_not_wait_for_a_bot_creation_callback(self):
        owner = self.owner()
        rows, complete = public_allies(owner, [dict(id=5007, alive=True, class_tag='SPG')])
        self.assertTrue(complete)
        artillery = Artillery([], 1, None)
        self.assertFalse(artillery._endgame(state(0., identity=5007),
            dict(allies=rows, allies_complete=complete)))
        self.assertTrue(artillery._endgame(state(5., identity=5007),
            dict(allies=rows, allies_complete=complete)))
        self.assertFalse(owner._bots_ready_reported)

    def test_missing_human_presentation_cannot_be_inferred_dead_or_artillery(self):
        owner = self.owner(players=[dict(id=7, team=1), dict(id=8, team=1)])
        rows, complete = public_allies(owner, [dict(id=5007, alive=True, class_tag='SPG')])
        self.assertTrue(complete)
        unknown = next(row for row in rows if row['id'] == 'player:8')
        self.assertTrue(unknown['alive'])
        self.assertIsNone(unknown['class_tag'])
        artillery = Artillery([], 1, None)
        for now in (0., 10., 100.):
            self.assertFalse(artillery._endgame(state(now, identity=5007),
                dict(allies=rows, allies_complete=complete)))

    def test_same_round_public_death_can_complete_endgame_without_hidden_position(self):
        owner = self.owner(bots=[dict(id=3, team=1, alive=True)])
        owner._last_snapshot = dict(round_id=4, bots=[dict(id=3, health=0, alive=False,
                                                        x=100., z=200.)])
        rows, complete = public_allies(owner, [])
        self.assertTrue(complete)
        self.assertFalse(rows[0]['alive'])
        self.assertNotIn('position', rows[0])
        owner._last_snapshot['round_id'] = 3
        self.assertTrue(public_allies(owner, [])[0][0]['alive'])

    def test_pending_presentation_does_not_gate_a_valid_public_roster(self):
        owner = self.owner()
        owner._pending_bot_create_order = ['bot:1']
        self.assertTrue(public_allies(owner, [])[1])
        owner._pending_bot_create_order = []
        del owner._start_message['bots']
        self.assertFalse(public_allies(owner, [])[1])


class ArtilleryBudgetTests(unittest.TestCase):
    def scene(self):
        artillery = Artillery([dict(id='park', team=1, point=(0., 0.), radius=2.)], 1, None)
        context = dict(allies=[contact(8, (100., 0., 100.))], allies_complete=True)
        return artillery, context

    def test_footprint_retains_positive_prefix_across_finite_native_budgets(self):
        artillery, context = self.scene()
        receipt = dict(status='connected', generation=1)
        remaining = [4]
        calls = []
        def height(point, hint):
            calls.append(point)
            if remaining[0] <= 0:
                receipt['status'] = 'query_budget'
                return None
            remaining[0] -= 1
            receipt['status'] = 'connected'
            return 0.
        for now in (0., .1):
            remaining[0] = 4
            artillery.update(state(now), context, height, evidence=lambda: receipt)
            self.assertEqual('checking_parking_geometry', artillery.receipt['reason'])
            self.assertIsNone(artillery.current)
        remaining[0] = 4
        artillery.update(state(.2), context, height, evidence=lambda: receipt)
        self.assertEqual('park:0', artillery.current['id'])
        self.assertEqual((0., 0., 0.), artillery.current['goal'])
        self.assertLessEqual(len(calls), 16)

    def test_unknown_candidate_is_bounded_but_not_reported_as_a_valid_goal(self):
        artillery, context = self.scene()
        height = lambda *args: None
        evidence = lambda: dict(status='query_budget', generation=1)
        artillery.update(state(0.), context, height, evidence)
        self.assertIsNone(artillery.current)
        self.assertEqual('deploying', artillery.mode)
        artillery.update(state(30.), context, height, evidence)
        self.assertEqual('fallback', artillery.mode)
        self.assertEqual('parking_evidence_timeout', artillery.receipt['reason'])

    def test_many_parking_candidates_cannot_expire_a_budget_limited_prefix(self):
        artillery = Artillery([dict(id='park-%02d' % index, team=1,
            point=(index*.01, 0.), radius=2.) for index in range(64)], 1, None)
        context = dict(allies=[contact(8, (100., 0., 100.))], allies_complete=True)
        receipt = dict(status='connected', generation=1)
        remaining = [0]
        def height(point, hint):
            if remaining[0] <= 0:
                receipt['status'] = 'query_budget'
                return None
            remaining[0] -= 1
            receipt['status'] = 'connected'
            return 0.
        for now in (0., .1, .2):
            remaining[0] = 4
            artillery.update(state(now), context, height, lambda: receipt)
        self.assertIsNotNone(artillery.current)
        self.assertEqual('park-00:0', artillery.current['id'])

    def test_moved_pose_or_changed_surface_restarts_cached_prefix(self):
        artillery, unused = self.scene()
        scan = {}
        receipt = dict(generation=1, status='connected')
        remaining = [3]
        def height(point, hint):
            remaining[0] -= 1
            return 0. if remaining[0] >= 0 else None
        artillery._parking_height((0., 0.), state(), height, lambda: receipt, scan)
        self.assertEqual(2, scan['verified'])
        for own in (state(.1, (.4, 0., 0.)), state(.2, (.4, 0., 0.))):
            remaining[0] = 2
            receipt['generation'] += 1
            artillery._parking_height((0., 0.), own, height, lambda: receipt, scan)
            self.assertEqual(1, scan['verified'])

    def test_recorded_multilayer_native_grid_completes_spg_footprint(self):
        import test_player_navigation_completion as fixture
        harness = fixture.RealNavigationCase()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        columns, calls = harness.columns()
        nav = harness.navigation('37_caucasus', 'SPG', ground=lambda *args: fixture.FLOOR,
                                 columns=columns)
        nav.artillery = Artillery([dict(id='lower-road', team=1,
            point=(fixture.ORIGIN[0], fixture.ORIGIN[2]), radius=2.)], 1, nav.home_area)
        nav.set_context(dict(supported=True, allies=[contact(77, (200., 0., 200.))],
                             allies_complete=True))
        for now in (0., .1, .2, .3):
            nav.movement_policy(fixture.pose(now))
            self.assertLessEqual(nav.support.native_queries, 64)
            if nav.artillery.current is not None:
                break
        self.assertIsNotNone(nav.artillery.current)
        self.assertAlmostEqual(fixture.FLOOR, nav.artillery.current['goal'][1])
        self.assertTrue(calls)


class LocalCombatTests(unittest.TestCase):
    @staticmethod
    def descriptor(tag='mediumTank', armour=80., **fields):
        result = dict(type=SimpleNamespace(tags=(tag,)), hull=dict(primaryArmor=(armour, 40., 30.)),
                      turret=dict(primaryArmor=armour))
        result.update(fields)
        return SimpleNamespace(**result)

    def context(self):
        return dict(target=contact(99, (0., 0., 160.)), fire_clear=True, supported=True,
                    allies=[contact(2, (-30., 0., 30.))])

    def test_one_observed_supporter_allows_only_one_local_mobile_flanker(self):
        first, second = CombatTactics(), CombatTactics()
        context = self.context()
        context['allies'][0]['class_tag'] = 'mediumTank'
        movement = first.movement(state(), context, self.descriptor(), True,
                                  lambda *args: 0., lambda *args: True)
        self.assertEqual('flank', movement['phase'])
        other_context = dict(context, allies=[contact(1, (0., 0., 0.), class_tag='mediumTank')])
        self.assertIsNone(second.movement(state(identity=2), other_context, self.descriptor(), True,
                                         lambda *args: 0., lambda *args: True))
        self.assertIsNone(second.flank)

    def test_flank_needs_support_geometry_and_available_movement_ownership(self):
        for changes, allowed, native in ((dict(allies=[]), True, True),
                (dict(burst_active=True), True, True), ({}, False, True), ({}, True, False)):
            tactics = CombatTactics()
            context = dict(self.context(), **changes)
            self.assertIsNone(tactics.movement(state(), context, self.descriptor(), allowed,
                                               lambda *args: 0., lambda *args: native))
        tactics = CombatTactics()
        self.assertIsNone(tactics.movement(state(), self.context(), self.descriptor(), True,
                                           lambda *args: None, lambda *args: True))

    def test_flank_progress_timeout_does_not_reset_on_repeated_decisions(self):
        tactics = CombatTactics()
        context, descriptor = self.context(), self.descriptor()
        self.assertIsNotNone(tactics.movement(state(), context, descriptor, True,
                                              lambda *args: 0., lambda *args: True))
        self.assertIsNone(tactics.movement(state(8.), context, descriptor, True,
                                           lambda *args: 0., lambda *args: True))
        self.assertEqual('flank_progress_timeout', tactics.receipt['reason'])
        self.assertIsNone(tactics.movement(state(9.), context, descriptor, True,
                                           lambda *args: 0., lambda *args: True))

    def test_armour_angle_stays_on_one_side_and_excludes_fixed_and_hydraulic_guns(self):
        tactics = CombatTactics()
        target = contact(99, (0., 0., 100.))
        first = tactics.facing(state(), target, self.descriptor())
        self.assertAlmostEqual(math.radians(22.), abs(first))
        for now in (1., 10., 100.):
            self.assertEqual(first, tactics.facing(state(now), target, self.descriptor()))
        for descriptor, limited in ((self.descriptor('AT-SPG'), False),
                (self.descriptor('SPG'), False), (self.descriptor(armour=30.), False),
                (self.descriptor(hasSiegeMode=True), False), (self.descriptor(), True)):
            self.assertIsNone(tactics.facing(state(), target, descriptor, limited=limited))

    def test_range_mode_has_hysteresis_instead_of_boundary_oscillation(self):
        policy = CombatPolicy('mediumTank')
        context = dict(target=contact(9, (0., 0., 150.)), fire_clear=True, gun_ready=False)
        self.assertTrue(policy.update(state(), context))
        for now, span in ((3., 156.), (4., 151.), (5., 160.)):
            context['target']['position'] = (0., 0., span)
            self.assertTrue(policy.update(state(now), context))
        context['target']['position'] = (0., 0., 190.)
        self.assertFalse(policy.update(state(6.), context))

    def test_td_support_hold_is_released_when_visible_support_enables_advance(self):
        policy = CombatPolicy('AT-SPG')
        context = dict(target=contact(9, (0., 0., 360.)), fire_clear=True, gun_ready=False)
        self.assertTrue(policy.update(state(), context))
        self.assertEqual('support_hold', policy.receipt['phase'])
        context['allies'] = [contact(2, (0., 0., 300.)), contact(3, (20., 0., 300.))]
        self.assertFalse(policy.update(state(3.), context))


class ControllerIntegrationTests(unittest.TestCase):
    def test_disabling_fire_retires_pending_cover_without_stopping_route(self):
        from test_player_independent_traffic import ForegroundControllerTrafficIntegrationTests
        from gui.mods.offline_lan_0922.player_control.cover import PlayerCover
        control, nav, unused = ForegroundControllerTrafficIntegrationTests().controller()
        nav.cover_search = PlayerCover(control.owner)
        nav.cover_search.job = {'old_candidate': True}
        nav.cover_search.episode = ('old_target', 0.)
        nav.cover_move = {'goal': (0., 0., -5.)}
        nav.reload_route = {'goal': (0., 0., -10.)}
        control.update(.1, 1.)
        self.assertIsNone(nav.cover_search.job)
        self.assertIsNone(nav.cover_search.episode)
        self.assertIsNone(nav.cover_move)
        self.assertIsNone(nav.reload_route)
        self.assertTrue(control.active)
        self.assertGreater(control.owner._sender.forward, 0.)

    def test_main_loop_sends_burst_and_turret_observations_before_navigation(self):
        import test_player_control as fixture
        control, unused = fixture.PlayerRegressionTests().aim_controller()
        control.features = {'drive'}
        control.owner._local_player_burst = dict(committed=1)
        control.owner._start_message = dict(round_id=4, players=[dict(id=1, team=1)], bots=[])
        turret = (17, 3., 4., 0., 1., .5)
        control.owner._turret_navigation_hulls = lambda: (turret,)
        control.update(.1, 1.)
        context = control.navigation.set_context.call_args.args[0]
        own = control.navigation.decide.call_args.args[0]
        self.assertTrue(context['burst_active'])
        self.assertEqual((turret,), context['turret_hulls'])
        self.assertTrue(context['allies_complete'])
        self.assertEqual(.1, own['decision_horizon'])
        self.assertIn('stopping_distance', own)

    def test_spg_drive_contact_reaches_independent_recovery(self):
        import test_player_control as fixture
        control, unused = fixture.PlayerRegressionTests().aim_controller()
        control.navigation.tag = 'SPG'
        control.navigation.report_drive_blockage = mock.Mock()
        receipt = dict(peer=8, normal=(1., 0.), position=(0., 0., 0.), at=0.)
        control.drive_contact((0., 0., 0.), 0., .1, static=True, contact=receipt)
        self.assertEqual(((0., 0., 0.), 0.), control.drive_failure)
        self.assertEqual(receipt, control.drive_contact_receipt)
        control.navigation.report_drive_blockage.assert_called_once()


if __name__ == '__main__':
    unittest.main()
