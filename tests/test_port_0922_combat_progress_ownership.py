"""Keep combat sub-actions within one physical progress and capture owner."""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'src/res/scripts/client')]
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from test_port_0922_server_bot_ai import BotPlanner
import test_port_0922_rear_limited_aim as rear_fixtures


class CombatProgressOwnershipTests(unittest.TestCase):
    def drive(self, driver, goal, identity=('combat', 'bot', 5), position=(0., 0., 0.),
              yaw=0., movement=True, dt=.1):
        return driver.drive(19, 0, position, yaw, 0., dt, goal, [],
            lambda *args: True, progress_target=goal, recovery_goal=goal,
            movement_intent=movement, progress_identity=identity,
            turn_speed_limit=.8)

    def test_enemy_approach_cannot_credit_stationary_vehicle(self):
        driver = LocalDriver(stuck_seconds=100.)
        self.drive(driver, (0., 0., 100.))
        progress = driver.states[19]['objective_progress']
        at = progress['at']
        for z in (99., 97., 95., 92.):
            self.drive(driver, (0., 0., z))
            self.assertIs(progress, driver.states[19]['objective_progress'])
            self.assertEqual(at, progress['at'])
            self.assertFalse(progress['translation_credit'])
        self.assertEqual((0., 0., 100.), progress['order_goal'])

    def test_mechanical_hold_pauses_but_does_not_erase_failed_travel(self):
        driver = LocalDriver(stuck_seconds=100.)
        self.drive(driver, (3., 0., 0.))
        progress = driver.states[19]['objective_progress']
        self.drive(driver, (3., 0., 0.), dt=3.)
        age = driver.states[19]['clock'] - progress['at']
        for unused in range(20):
            self.drive(driver, (0., 0., 0.), movement=False)
        self.assertIs(progress, driver.states[19]['objective_progress'])
        self.assertAlmostEqual(age, driver.states[19]['clock'] - progress['at'])
        self.drive(driver, (-3., 0., 0.))
        self.assertIs(progress, driver.states[19]['objective_progress'])
        self.assertGreater(driver.states[19]['clock'] - progress['at'], age)

    def test_reported_target_and_local_action_changes_cannot_postpone_recovery(self):
        # 022452 M4190/13 57/T54: near steering point, moving enemy,
        # and an intentional firing hold alternate in one stationary pocket.
        for actor in ('M4190', 'AMX1357', 'T54'):
            with self.subTest(actor=actor):
                driver = LocalDriver(stuck_seconds=100.)
                modes = []
                for frame in range(500):
                    held = frame % 6 == 0
                    angle = .9 if frame % 2 else -.9
                    goal = ((0., 0., 0.) if held else
                            (3.*math.sin(angle), 0., 3.*math.cos(angle)))
                    modes.append(self.drive(driver, goal, movement=not held,
                        yaw=.4 if frame % 2 else -.4)['recovery_mode'])
                self.assertTrue(any(mode in ('reverse_turn', 'pivot_recovery') for mode in modes))
                self.assertGreater(driver.states[19]['recovery_count'], 0)

    def test_different_enemy_and_noncombat_task_release_episode(self):
        driver = LocalDriver(stuck_seconds=100.)
        self.drive(driver, (0., 0., 100.))
        old = driver.states[19]['objective_progress']
        self.drive(driver, (0., 0., 100.), identity=('combat', 'bot', 6))
        self.assertIsNot(old, driver.states[19]['objective_progress'])
        self.drive(driver, (0., 0., 0.), identity=None, movement=False)
        self.assertNotIn('objective_progress', driver.states[19])

    def test_adapter_current_pose_mechanical_hold_pauses_old_failed_approach(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        adapter = BotAdapter('01_karelia', 7)
        state = dict(id=19, slot=0, position=(0., 0., 0.), yaw=0., speed=0.,
                     dt=.1, now=1., neighbours=())
        travel = dict(target_id=5, target_kind='bot', combat_mode='advance_contact',
                      move_position=(0., 0., 100.), aim_position=(0., 0., 100.))
        adapter.decide_with_order(dict(state), travel, lambda *args: True)
        dr = adapter.driver.states[19]; progress = dr['objective_progress']
        dr['clock'] = 20.; progress['at'] = 1.; dr['recovery_time'] = 1.3
        hold = dict(travel, combat_mode='engage', move_position=(0., 0., 0.))
        result = adapter.decide_with_order(dict(state), hold, lambda *args: True)
        self.assertEqual('arrived', result['recovery_mode'])
        self.assertEqual(0., result['throttle'])
        self.assertFalse(result['movement_intent'])
        self.assertTrue(result['control_trace']['mechanical_hold'])
        self.assertIs(progress, dr['objective_progress'])
        self.assertAlmostEqual(19., dr['clock']-progress['at'])
        self.assertEqual(1.3, dr['recovery_time'])

    def test_recorded_vehicle_inputs_keep_one_episode_for_same_enemy(self):
        import json
        fixture = json.loads((ROOT / 'tests/fixtures/combat_progress_20261020.json').read_text())
        for actor, rows in fixture['actors'].items():
            driver = LocalDriver(stuck_seconds=100.)
            previous_identity = previous = None
            last_at = rows[0]['at']-.1
            for row in rows:
                identity = ('combat', row['target_kind'], row['target_id'])
                driver.drive(int(actor), 0, row['position'], row['yaw'], 0.,
                    row['at']-last_at, row['local'], [], lambda *args: True,
                    progress_target=row['local'], recovery_goal=row['goal'],
                    movement_intent=row['movement'], progress_identity=identity,
                    turn_speed_limit=.8)
                current = driver.states[int(actor)].get('objective_progress')
                if previous is not None and identity == previous_identity:
                    self.assertIs(previous, current, (actor, row['at']))
                previous, previous_identity, last_at = current, identity, row['at']

    def test_actual_translation_and_curved_travel_keep_progress(self):
        driver = LocalDriver(stuck_seconds=100.)
        for frame in range(400):
            angle = frame*.015
            pos = (20.*math.sin(angle), 0., 20.*math.cos(angle))
            goal = (pos[0]+10.*math.cos(angle), 0., pos[2]-10.*math.sin(angle))
            self.drive(driver, goal, position=pos, yaw=math.pi/2+angle)
            self.assertEqual(0, driver.states[19]['recovery_count'])


class CaptureProtectionTests(unittest.TestCase):
    def bot(self, actor, team=1):
        return dict(id=actor, team=team, profile=dict(speed=12., class_tag='heavyTank'),
            state=dict(x=0., y=0., z=100., world_pose=True, health=1000., max_health=1000.))

    def context(self, contributors):
        return dict(bases={'1': [dict(x=0., y=0., z=0.)],
                           '2': [dict(x=0., y=0., z=100.)]},
            states={'1': dict(invaders=1, time_left=90.),
                    '2': dict(invaders=1, time_left=90.)}, contributors=contributors)

    def test_last_active_capturer_is_not_recalled_even_under_attack(self):
        planner = BotPlanner()
        result = planner._update_base_defense([self.bot(3)], {1: [], 2: []},
            self.context({'2': [dict(kind='bot', id=3)]}), 1.)
        self.assertEqual({}, result[1])
        receipt = planner._base_defense[1]['capture_protection']
        self.assertEqual([3], receipt['protected'])

    def test_enter_capture_releases_responder_and_exit_restores_eligibility(self):
        planner = BotPlanner(); bots = [self.bot(3)]
        free = self.context({})
        self.assertIn(3, planner._update_base_defense(bots, {1: [], 2: []}, free, 1.)[1])
        protected = self.context({2: [dict(kind='bot', id=3)]})
        self.assertEqual({}, planner._update_base_defense(bots, {1: [], 2: []}, protected, 2.)[1])
        self.assertEqual([3], planner._base_defense[1]['capture_protection']['released_responders'])
        self.assertIn(3, planner._update_base_defense(bots, {1: [], 2: []}, free, 3.)[1])

    def test_other_team_human_id_and_merely_being_in_ring_do_not_exclude_bot(self):
        for contributors in ({'1': [dict(kind='bot', id=3)]},
                             {'2': [dict(kind='human', id=3)]}, {}):
            with self.subTest(contributors=contributors):
                planner = BotPlanner()
                self.assertIn(3, planner._update_base_defense([self.bot(3)],
                    {1: [], 2: []}, self.context(contributors), 1.)[1])

    def test_exclusion_does_not_change_existing_responder_quota(self):
        planner = BotPlanner()
        context = self.context({'2': [dict(kind='bot', id=3)]})
        context['states']['1']['invaders'] = 2
        result = planner._update_base_defense([self.bot(3), self.bot(4), self.bot(5)],
            {1: [], 2: []}, context, 1.)
        self.assertEqual({4, 5}, set(result[1]))

    def test_both_teams_protect_capturers_and_use_remaining_responder_pool(self):
        planner = BotPlanner()
        bots = [self.bot(3), self.bot(4), self.bot(5, 2), self.bot(6, 2)]
        result = planner._update_base_defense(bots, {1: [], 2: []}, self.context(
            {'1': [dict(kind='bot', id=5)], '2': [dict(kind='bot', id=3)]}), 1.)
        self.assertEqual({4}, set(result[1]))
        self.assertEqual({6}, set(result[2]))


class RearApproachOwnershipTests(unittest.TestCase):
    setUp = rear_fixtures.RearTraverseRuntimeTests.setUp
    tearDown = rear_fixtures.RearTraverseRuntimeTests.tearDown
    # Reuse the exact descriptor/runtime fixture; retained rear-law tests run
    # in their own suite as well. These cases exercise native cache freshness.
    def test_blocked_approach_releases_episode_and_later_creation_gate(self):
        state = self.state
        target = dict(id=2, kind='human', alive=True, position=(0., 0., -100.))
        order = dict(target_id=2, combat_mode='advance_contact', move_position=(20., 0., 0.))
        state.update(_rear_aim_episode=dict(target_id=2, identity=('human', 2),
                     start=0., fire_seq=0))
        key = self.runtime._shot_los_key(state, target)
        self.runtime._shot_los_cache[key] = (2., False)
        self.assertIs(order, self.runtime._rear_laying_order(state, order, {2: target}, 2.))
        self.assertNotIn('_rear_aim_episode', state)
        self.assertNotIn('_rear_hull_aim', state)
        self.assertTrue(state['_rear_motion_blocked'])
        # The same production gate passed to combat_hull_aim cannot recreate
        # rear parking later in this update. Real final collision stays owner.
        from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
        self.assertEqual((.2, 1., False), combat_hull_aim(0., 2.9, -.1, .1,
            .2, 1., 'drive', True, combat_mode='advance_contact', movement_intent=True,
            allow_rear_start=not state['_rear_motion_blocked']))
        self.runtime._shot_los_cache[key] = (2.1, True)
        self.runtime._rear_laying_order(state, order, {2: target}, 2.1)
        self.assertFalse(state['_rear_motion_blocked'])

    def test_real_update_blocked_rear_approach_does_not_restart_episode(self):
        import contextlib
        import io
        import test_port_0922_bot_runtime as harness
        descriptor = harness._combat_descriptor(turret_yaw_limits=(-.1, .1), turret_speed=1.)
        runtime = self.fixture.module.BotRuntime(1,
            descriptor_resolver=lambda unused: descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            visibility_probe=lambda *unused: True, firing_lane_probe=lambda *unused: False,
            baked_graph=harness._flat_open_graph())
        runtime.battle_start(self.fixture.start)
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            id=11, team=2, combat_mode='advance_contact', target_kind='human', target_id=2,
            move_position=(30., 0., 0.), aim_position=(0., 0., -100.),
            face_position=(0., 0., -100.), fire_range=500., fire_allowed=False)]))
        player = harness._admit_player(dict(id=2, team=1, alive=True, x=0., y=0., z=-100.))
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 31):
                runtime.update(.05, frame*.05, players=[player])
        state = runtime.states[11]
        self.assertTrue(state['_rear_approach_receipt']['blocked'])
        self.assertNotIn('_rear_aim_episode', state)
        self.assertNotIn('_rear_hull_aim', state)
        self.assertEqual(0, state['fire_seq'])
        self.assertFalse(state['hull_aiming'])

    def test_blocked_authored_advance_releases_episode_and_later_creation_gate(self):
        state = self.state
        target = dict(id=2, kind='human', alive=True, position=(0., 0., -100.))
        order = dict(target_id=2, combat_mode='advance', move_position=(20., 0., 0.))
        state.update(_rear_aim_episode=dict(target_id=2, identity=('human', 2),
                     start=0., fire_seq=0))
        key = self.runtime._shot_los_key(state, target)
        self.runtime._shot_los_cache[key] = (2., False)
        self.assertIs(order, self.runtime._rear_laying_order(state, order, {2: target}, 2.))
        self.assertNotIn('_rear_aim_episode', state)
        self.assertNotIn('_rear_hull_aim', state)
        self.assertTrue(state['_rear_motion_blocked'])
        # The same production gate passed to combat_hull_aim cannot recreate
        # rear parking later in this update. Real final collision stays owner.
        from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
        self.assertEqual((.2, 1., False), combat_hull_aim(0., 2.9, -.1, .1,
            .2, 1., 'drive', True, combat_mode='advance', movement_intent=True,
            allow_rear_start=not state['_rear_motion_blocked']))
        self.runtime._shot_los_cache[key] = (2.1, True)
        self.runtime._rear_laying_order(state, order, {2: target}, 2.1)
        self.assertFalse(state['_rear_motion_blocked'])

    def test_real_update_blocked_authored_advance_does_not_restart_episode(self):
        import contextlib
        import io
        import test_port_0922_bot_runtime as harness
        descriptor = harness._combat_descriptor(turret_yaw_limits=(-.1, .1), turret_speed=1.)
        runtime = self.fixture.module.BotRuntime(1,
            descriptor_resolver=lambda unused: descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            visibility_probe=lambda *unused: True, firing_lane_probe=lambda *unused: False,
            baked_graph=harness._flat_open_graph())
        runtime.battle_start(self.fixture.start)
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            id=11, team=2, combat_mode='advance', target_kind='human', target_id=2,
            move_position=(30., 0., 0.), aim_position=(0., 0., -100.),
            face_position=(0., 0., -100.), fire_range=500., fire_allowed=False)]))
        player = harness._admit_player(dict(id=2, team=1, alive=True, x=0., y=0., z=-100.))
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 31):
                runtime.update(.05, frame*.05, players=[player])
        state = runtime.states[11]
        self.assertTrue(state['_rear_approach_receipt']['blocked'])
        self.assertNotIn('_rear_aim_episode', state)
        self.assertNotIn('_rear_hull_aim', state)
        self.assertEqual(0, state['fire_seq'])
        self.assertFalse(state['hull_aiming'])

    def test_unknown_expired_and_withdraw_keep_normal_rear_laying(self):
        target = dict(id=2, kind='human', alive=True, position=(0., 0., -100.))
        for mode, sample in (('advance', None), ('advance', (0., False)), ('advance', (2., True)),
                             ('advance_contact', None), ('advance_contact', (0., False)),
                             ('withdraw', (2., False)), ('advance_contact', (2., True))):
            with self.subTest(mode=mode, sample=sample):
                self.runtime._shot_los_cache.clear()
                if sample is not None:
                    self.runtime._shot_los_cache[self.runtime._shot_los_key(self.state, target)] = sample
                self.state['_rear_aim_episode'] = dict(target_id=2, identity=('human', 2),
                                                       start=0., fire_seq=0)
                order = dict(target_id=2, combat_mode=mode, move_position=(20., 0., 0.))
                held = self.runtime._rear_laying_order(self.state, order, {2: target}, 2.)
                self.assertEqual('engage', held['combat_mode'])
                self.assertFalse(self.state['_rear_motion_blocked'])


if __name__ == '__main__':
    unittest.main()
