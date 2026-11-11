"""Live-report liveness at the shared planner/driver/native fire boundaries.

These are deterministic #1513-shaped observation fixtures, not a Windows
physics replay. Native matrices, world boxes and query cost are supplied;
the shared policy, original driver, trigger admission and ammunition ledger
are production code. No candidate, penetration result or fire permission is
injected by these regressions.
"""
import contextlib
import io
import math
import os
import unittest
from unittest import mock

from test_player_combat_ownership import OwnershipScene
from test_player_combat_stop import Scene
from test_player_rebuilt_attack_policy import Observations
from test_player_stationary_plan import install_plan_observations
from gui.mods.offline_lan_0922 import native_input_diagnostics as logs
from gui.mods.offline_lan_0922.vehicle_control.attack_policy import _planning_pose


class LiveReportLivenessTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def scene(self, features=('drive', 'fire'), limited=False):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(features=features, limited=limited, clip=10, burst=1)
        return scene

    def test_blocked_opening_keeps_final_route_controls_during_yaw_changes(self):
        traces = []
        for features in (('drive',), ('drive', 'fire')):
            scene = self.scene(features=features, limited=True)
            scene.obstructed_enemy(2)
            self.assertEqual({2: False}, scene.sample_original_lanes())
            trace = []
            for index in range(30):
                # Route-only rotation may schedule a fresh observation. It
                # cannot itself prove an executable combat recovery.
                scene.native_position((0., 0., 0.), yaw=.13 * index)
                scene.tick(.1)
                command = scene.control.last_order
                trace.append(tuple(command.get(key) for key in
                    ('throttle', 'turn', 'brake', 'movement_intent',
                     'move_position', 'face_position', 'combat_mode')))
                self.assertFalse(scene.runtime.combat_stop.combat_owned,
                    (index, scene.runtime.combat_stop.receipt))
                self.assertEqual('class_mt_rim_east', scene.applied_order()['route_id'])
                self.assertFalse(scene.launches())
            traces.append(trace)
            scene.doCleanups()
        self.assertEqual(traces[0], traces[1],
            'pending combat inspection must not change the final route inputs')
        self.assertTrue(any(row[0] != 0. for row in traces[0]),
                        'the baseline must actually ask the original driver to travel')

    def test_ten_round_he_clip_promotes_ranked_ap_on_native_reload(self):
        scene = self.scene(features=('fire',))
        scene.set_he(piercing=1.)
        target = scene.eligible_enemy(50, armor=30.)
        scene.pose(target, (0., 0., 40.))
        for identity in range(70, 84):
            scene.obstructed_enemy(identity)
        gun = scene.battle._gun_state
        gun.shots[1].piercingPower = (160., 160.)
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot']['piercingPower'] = (160., 160.)
        initial_ammo = tuple(gun.ammo)
        for step in range(320):
            scene.native_position((0., .00001 * (step % 4), 0.))
            scene.battle._advance_local_gun_to(scene.entity, scene.now + .125)
            scene.tick(.125)
            if len(scene.launches()) == 10:
                break
        self.assertEqual([0] * 10, [row['shell_index'] for row in scene.launches()],
                         scene.runtime.attack_policy.status())
        self.assertEqual((initial_ammo[0] - 10, initial_ammo[1]), tuple(gun.ammo))
        self.assertEqual(1, gun.shot_index, scene.runtime.attack_policy.status())
        self.assertGreater(gun.reload_time, 0.)
        self.assertFalse(scene.runtime.attack_policy.fallback)

    def test_manual_native_ap_change_clears_he_before_loaded_ap_shot(self):
        scene = self.scene(features=('fire',))
        scene.set_he(piercing=1.)
        target = scene.eligible_enemy(50, armor=30.)
        scene.pose(target, (0., 0., 40.))
        gun = scene.battle._gun_state
        gun.shots[1].piercingPower = (160., 160.)
        scene.battle.client.effective_params['gun']['shots'][1]['source_shot']['piercingPower'] = (160., 160.)
        policy = scene.runtime.attack_policy
        for unused in range(40):
            scene.tick(.125)
            if scene.launches():
                break
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertTrue(policy.fallback)
        # User input follows the ordinary native setter and manual observer.
        settings = scene.battle._runtime.constants.VEHICLE_SETTING
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, settings.CURRENT_SHELLS, 102))
        self.assertEqual((1, 0), (gun.shot_index, gun.clip))
        self.assertFalse(policy.fallback)
        for unused in range(160):
            scene.battle._advance_local_gun_to(scene.entity, scene.now + .125)
            scene.tick(.125)
            if len(scene.launches()) > 1:
                break
        self.assertEqual([0, 1], [shot['shell_index'] for shot in scene.launches()], policy.status())

    def test_checkbox_controls_new_evidence_on_the_same_real_he_shot(self):
        for enabled in ('0', '1'):
            with self.subTest(enabled=enabled):
                scene = self.scene(features=('fire',))
                scene.set_he(piercing=1.)
                target = scene.eligible_enemy(50, armor=30.)
                scene.pose(target, (0., 0., 40.))
                with mock.patch.dict(os.environ, {logs.DETAIL_ENV: '1',
                        logs.COMBAT_DETAIL_ENV: enabled}), \
                        mock.patch.object(logs, 'write_json_record') as record:
                    for unused in range(80):
                        scene.tick(.125)
                        if scene.launches():
                            break
                self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
                stages = {call.args[1].get('stage') for call in record.call_args_list
                          if len(call.args) > 1 and isinstance(call.args[1], dict)}
                self.assertEqual(enabled == '1', 'auto_fire_gate' in stages)
                self.assertEqual(enabled == '1', 'auto_native_trigger' in stages)
                self.assertEqual(enabled == '1', 'ordered_attack' in stages)
                scene.doCleanups()

    def test_loaded_he_commits_with_source_jitter_and_fourteen_blocked_enemies(self):
        for features in (('fire',), ('drive', 'fire')):
            with self.subTest(features=features):
                scene = self.scene(features=features)
                scene.set_he(piercing=1.)
                scene.battle._gun_state.ammo[1] = 0
                scene.battle.client.effective_params['ammo'][1][1] = 0
                target = scene.eligible_enemy(50, armor=30.)
                scene.pose(target, (0., 0., 40.))
                for identity in range(70, 84):
                    scene.obstructed_enemy(identity)
                lanes = scene.sample_original_lanes()
                self.assertTrue(lanes[50])
                self.assertEqual(14, sum(not value for value in lanes.values()))
                policy = scene.runtime.attack_policy
                clock, queries, commits = [0.], [], []
                policy.atomic_clock = lambda: clock[0]
                original_evaluate = policy._evaluate
                original_commit = policy.shot_committed

                def costed_query(job, now, channel, *args, **kwargs):
                    result = original_evaluate(job, now, channel, *args, **kwargs)
                    queries.append((channel, job[4], job[0][1]))
                    clock[0] += .001
                    return result

                def record_commit(event, pending):
                    candidate = ((pending.get('player_control') or {}).get('candidate') or
                                 policy.trigger or policy.decision.get('candidate') or {})
                    commits.append((candidate.get('target_key'), candidate.get('mode'),
                                    candidate.get('sample')))
                    return original_commit(event, pending)

                policy._evaluate = costed_query
                policy.shot_committed = record_commit
                initial_ammo = tuple(scene.battle._gun_state.ammo)
                for index in range(60):
                    height = 1.e-8 if index % 2 else 0.
                    scene.native_position((0., height, 0.))
                    scene.tick(.1)
                    self.assertLessEqual(policy._used['foreground'], policy.foreground_budget)
                    self.assertLessEqual(policy._used['background'], policy.background_budget)
                    self.assertEqual(2, policy.foreground_budget)
                    self.assertEqual(.008, policy.atomic_time_budget)
                    if scene.launches():
                        break
                self.assertTrue(scene.launches(), policy.status())
                self.assertEqual(1, len(scene.launches()))
                self.assertEqual([(('bot', 50), 'he_fallback', 0)], commits)
                self.assertEqual(0, policy.proof_revocations['source'],
                                 'numerical settling must preserve the one-point planning cache')
                self.assertEqual({('bot', 50)}, {target for _, _, target in queries})
                self.assertTrue(any(channel == 'foreground' and mode == 'he_fallback'
                                    for channel, mode, unused_target in queries))
                self.assertEqual(initial_ammo[0] - 1, scene.battle._gun_state.ammo[0])
                self.assertEqual(9, scene.battle._gun_state.clip)
                self.assertEqual(0, scene.battle._gun_state.shot_index)
                self.assertFalse(hasattr(policy, 'search_started'))
                scene.doCleanups()


class StableRouteAttackTests(unittest.TestCase):
    def scene(self):
        scene = Scene(admitted=False)
        scene.runtime.actor_kind = 'human'
        scene.raw_order.update(combat_mode='route', move_position=(20., 0., -30.),
                               throttle_override=None, fire_allowed=False)
        scene.candidate.update(key=(0, ('bot', 2), 0, 'penetration'),
                               armor='passed', line='clear', mechanical='hull_laying')
        scene.candidate['solution'].update(yaw=.7)
        return scene

    def test_flashes_and_blocker_never_accumulate_route_confirmation(self):
        scene = self.scene()
        for step in range(81):
            scene.candidate['line'] = 'world_blocked' if step % 3 == 2 else 'clear'
            order = scene.apply(step * .125)
            self.assertEqual('route', order['combat_mode'])
            self.assertEqual(scene.raw_order['move_position'], order['move_position'])
            self.assertFalse(order['fire_allowed'])
        self.assertEqual(0, scene.owner._episode)

    def test_stable_lay_admits_once_and_blocked_lay_requires_a_new_full_window(self):
        scene = self.scene()
        for step in range(40):
            self.assertEqual('route', scene.apply(step * .125)['combat_mode'])
        self.assertEqual('engage', scene.apply(5.)['combat_mode'])
        self.assertEqual(1, scene.owner._episode)
        self.assertIsNotNone(scene.owner.pivot)
        scene.candidate['line'] = 'world_blocked'
        scene.policy.retained_lay_candidate = lambda key, now: dict(
            status='blocked', candidate=dict(scene.candidate))
        order = scene.apply(5.125)
        self.assertFalse(order['fire_allowed'])
        self.assertTrue(order['stable_hull_face'])
        self.assertEqual('route', scene.apply(6.125)['combat_mode'])
        scene.candidate['line'] = 'clear'
        self.assertEqual('route', scene.apply(6.25)['combat_mode'])
        scene.candidate['line'] = 'world_blocked'
        self.assertEqual('route', scene.apply(6.375)['combat_mode'])
        self.assertEqual(1, scene.owner._episode)

    def test_clear_unknown_armour_does_not_qualify_even_after_five_seconds(self):
        scene = self.scene()
        scene.candidate['armor'] = 'unknown'
        for step in range(50):
            self.assertEqual('route', scene.apply(step * .125)['combat_mode'])
        self.assertEqual(0, scene.owner._episode)

    def test_no_he_cooldown_overlaps_a_fresh_five_second_route_confirmation(self):
        scene = self.scene()
        for step in range(41):
            scene.apply(step * .125)
        self.assertTrue(scene.owner.combat_owned)
        scene.decide('navigate', candidate=False, reason='ordered_no_he')
        self.assertEqual('route', scene.apply(5.125)['combat_mode'])
        self.assertEqual(10.125, scene.owner.cooldown_until)
        scene.decide('firing_position')
        for step in range(40):
            self.assertEqual('route', scene.apply(5.25 + step * .125)['combat_mode'])
            self.assertEqual(1, scene.owner._episode)
        self.assertEqual('engage', scene.apply(10.25)['combat_mode'])
        self.assertEqual(2, scene.owner._episode)

    def test_moving_limited_vehicle_qualifies_proved_ap_or_ordinary_he_lay(self):
        for he in (False, True):
            with self.subTest(he=he), contextlib.redirect_stdout(io.StringIO()):
                scene = OwnershipScene()
                scene.setUp()
                self.addCleanup(scene.doCleanups)
                scene.configure(limited=True, clip=10, burst=1)
                if he:
                    scene.set_he(piercing=1.)
                scene.position = (0., 0., 0.)
                install_plan_observations(scene)
                target = scene.eligible_enemy(50, armor=30.)
                scene.pose(target, (math.sin(.7) * 45., 0., math.cos(.7) * 45.))
                for step in range(41):
                    scene.native_position((step * .04, 0., 0.))
                    scene.battle._local_speed = .32
                    order = scene.tick(.125)
                    self.assertFalse(scene.launches())
                    if step < 40:
                        self.assertEqual('route', order['combat_mode'])
                owner = scene.runtime.combat_stop
                self.assertEqual(5., owner.receipt['confirmation_seconds'])
                self.assertEqual('native_lay', owner.receipt['reason'])
                candidate = scene.runtime.attack_policy.decision['candidate']
                self.assertEqual('hull_laying', candidate['mechanical'])
                if he:
                    self.assertEqual('failed', candidate['armor'])
                    self.assertGreater(candidate['route_he_damage'], 0.)
                    self.assertIsNone(candidate['contact'])
                else:
                    self.assertEqual('passed', candidate['armor'])

    def moving_scene(self, position, limited, clip):
        scene = OwnershipScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure(limited=limited, clip=clip, burst=1)
        scene.position = position
        scene.native_position(position)
        install_plan_observations(scene)
        return scene

    def assert_moving_handoff_and_launch(self, scene, task_modes, bearing, dx=0., dz=.01):
        x, y, z = scene.position
        target = scene.eligible_enemy(50, armor=30.)
        scene.pose(target, (x + math.sin(bearing) * 45., y, z + math.cos(bearing) * 45.))
        owner = scene.runtime.combat_stop
        initial_clip = scene.battle._gun_state.clip
        observed_modes = []
        for step in range(105):
            position = (x + step * dx, y, z + step * dz)
            scene.native_position(position)
            scene.battle._local_speed = math.hypot(dx, dz) / .125
            order = scene.tick(.125)
            self.assertFalse(scene.launches())
            self.assertEqual(initial_clip, scene.battle._gun_state.clip)
            mode = owner.task_order['combat_mode']
            if not observed_modes or observed_modes[-1] != mode:
                observed_modes.append(mode)
            if owner.stop_allowed:
                self.assertGreaterEqual(owner.receipt['confirmation_seconds'], 5.)
                self.assertEqual('engage', order['combat_mode'])
                break
            self.assertEqual(mode, order['combat_mode'])
        else:
            self.fail(scene.runtime.attack_policy.status())
        self.assertEqual(task_modes, tuple(observed_modes))
        self.assertEqual(('bot', 50), owner.receipt['selected'])
        if bearing > .15:
            candidate = scene.runtime.attack_policy.decision['candidate']
            self.assertEqual('hull_laying', candidate['mechanical'])
            self.assertEqual('clear', candidate['line'])
            self.assertFalse(scene.runtime.state['gun_aligned'])
        scene.native_position(position, yaw=bearing)
        scene.battle._local_speed = 0.
        for unused in range(35):
            scene.tick(.125)
            if scene.launches():
                break
        self.assertEqual(1, len(scene.launches()), scene.runtime.attack_policy.status())
        self.assertEqual(0, scene.launches()[0]['shell_index'])
        self.assertEqual(50, scene.runtime.weapon.target['network_id'])
        self.assertEqual(initial_clip - 1, scene.battle._gun_state.clip)

    def test_moving_vehicle_checks_clear_enemy_beyond_nearest_blocked_enemy(self):
        for limited, clip, bearing in ((True, 10, .05), (True, 10, .7), (False, 1, .05)):
            with self.subTest(clip=clip, bearing=bearing), contextlib.redirect_stdout(io.StringIO()):
                scene = self.moving_scene((0., 0., 0.), limited, clip)
                closest = scene.eligible_enemy(5, armor=30.)
                scene.pose(closest, (-7., 0., 14.))
                scene.world[:] = [((-7., -5., 3.), (-1., 8., 8.))]
                self.assert_moving_handoff_and_launch(scene, ('route',), bearing)

    def test_automatic_capture_approach_keeps_confirming_before_circle_entry(self):
        with contextlib.redirect_stdout(io.StringIO()):
            scene = self.moving_scene((33., 0., 40.), limited=True, clip=10)
            self.assert_moving_handoff_and_launch(
                scene, ('route', 'base_capture'), .7, dx=.04, dz=0.)
            self.assertFalse(scene.runtime.combat_stop.task_order.get('capture_area'))
            self.assertTrue(scene.runtime.combat_stop.task_order.get('capture_objective'))

    def test_full_runtime_drives_before_sustained_current_proof(self):
        scene = OwnershipScene()
        with contextlib.redirect_stdout(io.StringIO()):
            scene.setUp()
            self.addCleanup(scene.doCleanups)
            scene.configure(clip=10, burst=1)
            target = scene.eligible_enemy(50, armor=20.)
            scene.pose(target, (0., 0., 40.))
            first = None
            for unused in range(75):
                order = scene.tick(.125)
                owner = scene.runtime.combat_stop
                since = owner.receipt.get('confirmation_since')
                if since is not None and first is None:
                    first = since
                if owner.stop_allowed:
                    self.assertGreaterEqual(scene.now - first, 5.)
                    self.assertEqual('engage', order['combat_mode'])
                    break
                self.assertEqual('route', order['combat_mode'])
            else:
                self.fail(scene.runtime.attack_policy.status())


class ReportAmmunitionTests(unittest.TestCase):
    @staticmethod
    def pose(scene, origin, enemy_offset=0.):
        pose = ((0., origin, 0.), (origin, 0., 0.), (0., 2. + origin, 0.),
                (0., 0.), 1, 2, (0., origin, 0.))
        scene.frame.update(pose=pose, origin=pose[2], planning_pose=_planning_pose(pose))
        for row in scene.frame['targets']:
            point = row['value']['position']
            matrix = ((point[0] + enemy_offset, point[1], point[2]), 0., 0., 0.)
            local = ((0., 0., 0.), 0., 0., 0.)
            row.update(pose=(row['key'], 1, matrix, matrix, local, local),
                       sample_identity=(row['key'], 1))

    def test_next_ranks_ap_through_micro_motion_and_rechecks_the_winner(self):
        scene = Observations(clips=10, targets=14, points=3, he_validation='single_point')
        scene.frame.update(loaded=2, ammo=(40, 40, 40))
        scene.allow_atomic = False
        for target in range(1, 15):
            scene.value(2, target=target, line='world_blocked', armor='unknown',
                        blocker=dict(kind='world'))
        scene.passed(0, target=14, sample=2)
        policy = scene.policy
        for step in range(1, 100):
            self.pose(scene, step * .00001, step * .0001)
            scene.tick(step * .125)
            plan, reason = policy.next_at_edge()
            if plan is not None:
                break
        self.assertEqual('verified', reason, policy.status())
        self.assertEqual((0, ('bot', 14), 2, 'penetration'), plan['key'])
        self.assertTrue(any(proof['pose_stamp'][1] != plan['pose_stamp'][1]
                            for proof in policy.next_proofs))
        self.assertIs(policy.current_row(plan), plan)
        self.assertGreater(policy.proof_revocations['source'], 0)
        self.pose(scene, .01, .02)
        scene.tick(13., background=False)
        self.assertIsNone(policy.next_at_edge()[0], 'the old winner cannot queue without refresh')
        self.pose(scene, .45, .30)
        scene.tick(14.)
        self.assertEqual('higher_rank_pending', policy.next_status)

    def test_manual_current_ap_clears_loaded_he_fallback_and_recovers_ap(self):
        scene = Observations(clips=10, targets=2, points=2, he_validation='single_point')
        scene.frame.update(loaded=2)
        scene.allow_atomic = False
        scene.he(20., target=1)
        scene.value(2, target=2, line='pending', armor='unknown')
        scene.value(2, target=2, mode='he_fallback', line='pending', armor='unknown')
        scene.value(0, target=1, line='clear', mechanical='hull_laying', armor='unknown')
        for step in range(1, 11):
            scene.tick(step * .125)
        policy = scene.policy
        self.assertTrue(policy.fallback)
        policy.load_started(0)
        scene.frame.update(loaded=0, clip=10)
        self.assertFalse(policy.fallback)
        decision = scene.tick(1.375, background=False)
        self.assertEqual('firing_position', decision['action'])
        self.assertEqual(0, decision['candidate']['shell_index'])


if __name__ == '__main__':
    unittest.main()
