"""Foreground shell plans cross the real native-setting and gun boundary.

The scene has observed native bodies/barrels, flat support and component BSPs.
NEXT/CURRENT/R are never replaced with test reload logic: FullPlayerRuntime
calls BattleRuntime.change_vehicle_setting, which owns the real GunState and
_LANInputSender checkpoint. Direct intent tests isolate that consumer boundary.
The global-failure/unknown cases retain NativeAttackEvaluator and AttackPolicy;
the withdrawal check also executes the complete copied retreat state machine.
These tests do not establish Windows native or BigWorld physics acceptance.
"""
import copy
from types import SimpleNamespace
import unittest
from unittest import mock

import test_player_limited_traverse as fixtures
from gui.mods.offline_lan_0922.battle_runtime import _LANInputSender
from gui.mods.offline_lan_0922.gun_mechanics import GunState
from gui.mods.offline_lan_0922.player_control import attack_policy
from gui.mods.offline_lan_0922.player_control.copied import server_bot_ai


class FullShellSettingsTests(unittest.TestCase):
    def scene(self, clip=6, burst=3, third=False):
        scene = fixtures.TraverseScene()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        # These are combat/reload boundary tests, not capture parking tests.
        # Supply actual off-origin bases so the spawn is not interpreted as
        # an enemy capture circle by the synthetic arena's fallback metadata.
        scene.battle._spawn_planner = SimpleNamespace(capture_bases={
            '1': [dict(x=0., z=-45., radius=6.)],
            '2': [dict(x=45., z=45., radius=6.)]})
        scene.configure(limits=None, tag='mediumTank', clip=clip,
                        burst=burst, bearing=0., rate=0.)
        self.assertIsInstance(scene.battle._sender, _LANInputSender)
        if third:
            gun = scene.battle._gun_state
            extra = copy.deepcopy(gun.shots[1])
            extra.shell.compactDescr = 103
            scene.entity.typeDescriptor.gun.shots.append(extra)
            gun.shots = tuple(gun.shots) + (extra,)
            gun.ammo.append(10)
            row = copy.deepcopy(scene.battle.client.effective_params['gun']['shots'][1])
            row['compact_descr'] = 103
            scene.battle.client.effective_params['gun']['shots'].append(row)
        scene.settings = scene.battle._runtime.constants.VEHICLE_SETTING
        scene.setting_calls = []
        actual = scene.battle.change_vehicle_setting

        def setting(code, value):
            scene.setting_calls.append((code, value))
            return actual(code, value)

        scene.battle.change_vehicle_setting = setting
        scene.observe()
        # The isolated shell consumer still needs a real prior combat grant.
        # This runs native lane observation and the unchanged BOT planner;
        # it does not fabricate an active flag or a tactical decision.
        scene.admit()
        self.assertTrue(scene.runtime.combat_stop.stop_allowed)
        # The native battle owns the reload clock. Establish its first sample
        # before testing elapsed time; a first-ever sample has no prior gap.
        scene.battle._advance_local_gun_to(scene.entity, scene.now)
        return scene

    @staticmethod
    def move_from_previous_route_point(scene):
        """Supply an observed pose ahead of the original spawn route point.

        The unchanged planner already owns a proved route anchor at spawn.
        A non-arrived retreat test must actually be away from that anchor;
        an arbitrary -24 movement argument cannot replace route history.
        """
        point = (0., 0., 12.)
        scene.battle._local_position = point
        if hasattr(scene, 'set_hull'):
            scene.position = point
            scene.origin = (0., 2., 12.)
            scene.set_hull(0.)
        else:
            scene.flat_body.translation = scene.body.translation = point
            scene.entity.matrix = scene.body
            scene.entity.position = scene.battle._runtime.math.Vector3(point)
            scene.battle.local_pose = lambda: (
                scene.battle._local_position, scene.body.yaw)
            scene.update_barrel_observation()
        scene.observe()

    @staticmethod
    def input_checkpoint(scene):
        rows = [row[2] for row in scene.battle.client.sent if row[0] == 'input']
        return rows[-1] if rows else None

    @staticmethod
    def queue(scene, index):
        scene.runtime.attack_policy.next_shell = index
        scene.runtime._apply_next_shell()

    @staticmethod
    def intent(scene, action, index=None, early=False):
        # This is a supplied decision at the native consumer boundary, not a
        # proof of how tactical evidence authorizes that decision.
        decision = dict(action=action, reason='supplied_consumer_intent',
                        candidate=None, early_reload=early)
        if index is not None:
            decision['shell_index'] = index
        scene.runtime.attack_policy.decision = decision

    def tick_weapon(self, scene):
        scene.battle._advance_local_gun_to(scene.entity, scene.now)
        row = scene.tick()
        self.assertIsNone(scene.control.last_control_failure, row)
        return row

    def test_exhausted_ap_steers_to_the_next_point_during_reload_and_fires_again(self):
        for clip_size in (1, 2):
            with self.subTest(clip_size=clip_size):
                scene = self.scene(clip=clip_size, burst=1)
                gun = scene.battle._gun_state
                gun.ammo[0], gun.clip = 1, 1
                gun.reload = 3.
                scene.rotator_enabled = True
                for unused in range(100):
                    self.tick_weapon(scene)
                    if scene.launches():
                        break
                self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
                self.assertEqual((1, 0), (gun.shot_index, gun.clip))
                old_point = scene.runtime.weapon.point
                scene.pose(scene.target, (9., 0., 40.))
                preaim, resumed = None, False
                for unused in range(160):
                    self.tick_weapon(scene)
                    policy = scene.runtime.attack_policy
                    if gun.reload_time > 0. and len(scene.launches()) == 1:
                        if policy.decision.get('phase') == 'preaiming' and scene.runtime.weapon.verified:
                            if scene.runtime.weapon.point != old_point:
                                preaim = policy.decision['candidate']['key']
                                self.assertEqual(1, preaim[0])
                        self.assertFalse(scene.control.last_order['fire_allowed'])
                    if gun.reload_time == 0. and preaim is not None and len(scene.launches()) == 1:
                        if scene.runtime.combat_stop.active:
                            self.assertEqual(preaim, policy.decision['candidate']['key'])
                        else:
                            # The native reload clock may finish before the
                            # original one-hertz planner hands its retreat
                            # hold back to combat. The new policy cannot
                            # manufacture that handoff to preserve a preaim.
                            task = scene.runtime.combat_stop.task_order
                            self.assertEqual('magazine_reload_retreat', task['combat_mode'])
                            self.assertEqual('magazine_reload_hold', task['tactical_phase'])
                            self.assertEqual('movement_lease',
                                task['tactical_evidence']['selection']['outcome'])
                            self.assertIsNone(policy.decision['candidate'])
                            self.assertFalse(scene.control.last_order['fire_allowed'])
                    if preaim is not None and len(scene.launches()) == 2:
                        self.assertTrue(scene.runtime.combat_stop.active)
                        self.assertEqual(preaim, policy.decision['candidate']['key'])
                        resumed = True
                    if len(scene.launches()) >= 3:
                        break
                self.assertIsNotNone(preaim, scene.trace[-3:])
                self.assertTrue(resumed, 'the original planner must restore the proved loading point')
                self.assertEqual([0, 1, 1], [shot['shell_index'] for shot in scene.launches()])
                self.assertEqual([0, 8], gun.ammo)
                self.assertFalse(scene.runtime.attack_policy.search_started)

    def test_proved_single_round_replacement_can_apply_during_loading(self):
        scene = self.scene(clip=1, burst=1)
        gun = scene.battle._gun_state
        gun.reload = 4.
        scene.rotator_enabled = True
        for unused in range(100):
            self.tick_weapon(scene)
            if scene.launches():
                break
        self.assertEqual([0], [shot['shell_index'] for shot in scene.launches()])
        self.assertGreater(gun.reload_time, 0.)
        gun.shots[0].piercingPower = (1., 1.)
        scene.battle.client.effective_params['gun']['shots'][0]['source_shot']['piercingPower'] = (1., 1.)
        switched = None
        for unused in range(120):
            was_loading = gun.reload_time > 0.
            self.tick_weapon(scene)
            if gun.shot_index == 1 and switched is None:
                switched = dict(scene.runtime._shell_receipt)
                self.assertTrue(was_loading)
                self.assertEqual(('CURRENT_SHELLS', True),
                                 (switched['setting'], switched['accepted']))
            if len(scene.launches()) == 2:
                break
        self.assertIsNotNone(switched, scene.trace[-3:])
        self.assertEqual([0, 1], [shot['shell_index'] for shot in scene.launches()])
        self.assertEqual([(scene.settings.CURRENT_SHELLS, 102)],
            [call for call in scene.setting_calls if call[0] == scene.settings.CURRENT_SHELLS])

    def test_manual_current_ap_still_accepts_a_verified_he_for_the_very_next_load(self):
        scene = self.scene(clip=1, burst=1, third=True)
        gun = scene.battle._gun_state
        he = gun.shots[2]
        he.shell.kind, he.shell.explosionRadius = 'HIGH_EXPLOSIVE', 5.
        he.piercingPower = (1000., 1000.)
        source = scene.battle.client.effective_params['gun']['shots'][2]['source_shot']
        source['shell'].update(kind='HIGH_EXPLOSIVE', explosionRadius=5.)
        source['piercingPower'] = he.piercingPower
        gun.reload = 1.5
        self.assertTrue(gun.sync_shell_index(1, instant=True))
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.CURRENT_SHELLS, 101))
        self.assertEqual((0, None), (gun.shot_index, gun.pending_index))
        scene.rotator_enabled = True
        for unused in range(100):
            self.tick_weapon(scene)
            if scene.launches():
                break
        self.assertEqual([0], [row['shell_index'] for row in scene.launches()])
        self.assertEqual((2, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertEqual(2, scene.runtime.attack_policy.loading_plan['shell_index'])
        self.assertIn((scene.settings.NEXT_SHELLS, 103), scene.setting_calls)
        for unused in range(100):
            self.tick_weapon(scene)
            if len(scene.launches()) == 2:
                break
        self.assertEqual([0, 2], [row['shell_index'] for row in scene.launches()])
        self.assertEqual([19, 10, 9], gun.ammo)

    def test_trigger_refreshes_current_frame_before_releasing_an_owned_next_shell(self):
        from test_player_rebuilt_attack_policy import Observations

        scene = self.scene(clip=1, burst=1, third=True)
        gun = scene.battle._gun_state
        runtime = scene.runtime
        observations = Observations(targets=1, points=1)
        observations.frame['ammo'] = tuple(gun.ammo)
        observations.passed(0)
        observations.passed(2)
        observations.prime()
        runtime.attack_policy = observations.policy
        observations.tick(runtime.now)
        runtime._apply_next_shell()
        self.assertEqual(2, gun.pending_index)

        observations.frame['line_revision'] += 1
        runtime.now += .11
        observations.tick(runtime.now, background=False)
        self.assertIsNone(observations.policy.current_row(observations.policy.next_plan))
        plan = runtime._apply_next_shell(at_trigger=True)
        self.assertEqual(2, plan['shell_index'])
        self.assertEqual(2, gun.pending_index)
        self.assertEqual([(scene.settings.NEXT_SHELLS, 103)], scene.setting_calls)

    def test_source_changes_recheck_a_ranked_queue_before_releasing_it(self):
        from test_player_rebuilt_attack_policy import Observations

        for he, preferred in ((True, 2), (False, 1)):
            with self.subTest(he=he):
                scene = self.scene(clip=3, burst=1, third=he)
                runtime, gun = scene.runtime, scene.battle._gun_state
                observations = Observations(clips=3, targets=4, points=8, he=he)
                observations.frame['ammo'] = tuple(gun.ammo)
                if not he:
                    observations.frame['shells'][1]['piercing'] = 150.
                observations.passed(0)
                observations.passed(preferred, target=4, sample=7)
                observations.prime()
                runtime.attack_policy = observations.policy
                observations.tick(runtime.now)
                runtime._apply_next_shell()
                self.assertEqual(preferred, gun.pending_index)
                for revision in range(1, 7):
                    observations.frame['pose'] = ('source', revision)
                    runtime.now += .11
                    self.assertEqual('aim', observations.tick(runtime.now)['action'])
                    runtime._apply_next_shell()
                    self.assertEqual(preferred, gun.pending_index)
                    self.assertEqual(revision, runtime.attack_policy.next_plan['pose_stamp'][1][1])
                    probes = [call for call in observations.calls
                              if call[0] == runtime.now and call[1] == 'background']
                    self.assertEqual(2, len(probes))
                    self.assertEqual((preferred, ('bot', 4), 7, 'penetration'), probes[0][2:])
                self.assertEqual([(scene.settings.NEXT_SHELLS, 101 + preferred)],
                                 scene.setting_calls)

                # True proof loss must still clear the native reservation.
                observations.frame['pose'] = ('source', 7)
                observations.value(preferred, target=4, sample=7, line='world_blocked')
                runtime.now += .3
                observations.tick(runtime.now)
                runtime._apply_next_shell()
                self.assertIsNone(gun.pending_index)
                review = runtime._shell_receipt['next_review']
                self.assertIn('source', review['proof_changes'])
                self.assertEqual('world_blocked', review['candidate']['line'])
                self.assertEqual(preferred, review['blocked_rank'])

    def test_next_clip_plan_can_change_and_cancel_without_unloading_current_clip(self):
        scene = self.scene(third=True)
        gun = scene.battle._gun_state
        before = (gun.shot_index, gun.clip, gun.reload_time, list(gun.ammo))
        for index in (1, 2, 1, None):
            self.queue(scene, index)
            self.assertEqual(index, gun.pending_index)
            self.assertEqual(before, (gun.shot_index, gun.clip, gun.reload_time, gun.ammo))
            checkpoint = self.input_checkpoint(scene)
            self.assertEqual(0, checkpoint['shell_index'])
            self.assertEqual(index is not None, checkpoint['shell_change_pending'])
            self.assertEqual(0 if index is None else index, checkpoint['next_shell_index'])
            self.assertEqual(6, checkpoint['gun_checkpoint']['clip'])
        self.assertEqual([(scene.settings.NEXT_SHELLS, value)
                          for value in (102, 103, 102, 101)], scene.setting_calls)
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.assertFalse(scene.launches())

    def test_preexisting_manual_next_shell_is_not_replaced_cancelled_or_reloaded(self):
        scene = self.scene(third=True)
        gun = scene.battle._gun_state
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.NEXT_SHELLS, 102))
        for index in (2, None, 0):
            self.queue(scene, index)
            self.assertEqual(1, gun.pending_index)
        self.intent(scene, 'reload_clip', index=2)
        scene.runtime._apply_shell_intent()
        scene.control.stop('manual_plan_survives_automatic_stop')
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102)], scene.setting_calls)
        self.assertEqual((0, 6, 1, 0.),
                         (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))
        self.assertIsNone(scene.runtime._owned_next_shell)

    def test_manual_selection_of_same_queued_shell_takes_over_the_lease(self):
        scene = self.scene(third=True)
        gun = scene.battle._gun_state
        self.queue(scene, 1)
        self.assertIsNotNone(scene.runtime._owned_next_shell)
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.NEXT_SHELLS, 102))
        self.queue(scene, 2)
        scene.control.stop('manual_selection_survives_stop')
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.assertEqual(1, gun.pending_index)
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102)] * 2, scene.setting_calls)

    def test_published_pending_plan_is_not_a_reload_and_actual_reload_is_not_ready(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        self.queue(scene, 1)
        scene.observe()
        self.assertEqual(1, scene.runtime.state['next_shell_index'])
        self.assertFalse(scene.runtime.state['ammo_reload_pending'])
        self.assertTrue(scene.runtime.planner._weapon_ready(scene.runtime._planner_bot()))
        self.queue(scene, None)
        gun.clip = 3
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.RELOAD_PARTIAL_CLIP, 0))
        scene.observe()
        self.assertEqual(0, scene.runtime.state['shell_index'])
        self.assertEqual(0, scene.runtime.state['next_shell_index'])
        self.assertTrue(scene.runtime.state['ammo_reload_pending'])
        self.assertFalse(scene.runtime.planner._weapon_ready(scene.runtime._planner_bot()))

    def test_last_physical_tail_promotes_next_clip_after_stop_not_at_intra_clip_boundary(self):
        scene = self.scene(clip=4, burst=2)
        gun = scene.battle._gun_state
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.NEXT_SHELLS, 102))
        scene.lay_current()
        self.assertTrue(scene.fire())
        self.assertEqual((0, 3, 1), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertTrue(scene.advance(.1))
        self.assertEqual((0, 2, 1), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertAlmostEqual(gun.clip_reload, gun.reload_time)
        scene.advance(gun.clip_reload)
        scene.lay_current()
        self.assertTrue(scene.fire())
        self.assertEqual((0, 1, 1), (gun.shot_index, gun.clip, gun.pending_index))
        scene.control.stop('committed_trigger_keeps_its_future_clip')
        self.assertEqual(1, gun.pending_index)
        self.assertTrue(scene.advance(.1))
        self.assertEqual((1, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertAlmostEqual(gun.reload_duration, gun.reload_time)
        self.assertGreater(gun.reload_time, gun.clip_reload)
        self.assertEqual([0, 0, 0, 0], [row['shell_index'] for row in scene.launches()])
        self.assertEqual([16, 10], gun.ammo)
        self.assertIsNone(scene.battle._local_player_burst)
        self.assertFalse(scene.control.active)
        checkpoint = self.input_checkpoint(scene)
        self.assertEqual(1, checkpoint['shell_index'])
        self.assertEqual(0, checkpoint['gun_checkpoint']['clip'])

    def test_next_plan_during_existing_reload_never_restarts_or_retargets_that_load(self):
        scene = self.scene(third=True)
        gun = scene.battle._gun_state
        gun.clip = 3
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.RELOAD_PARTIAL_CLIP, 0))
        self.assertEqual(0, gun.clip)
        scene.advance(1.)
        remaining, duration = gun.reload_time, gun.reload_duration
        self.assertGreater(remaining, 0.)
        self.assertLess(remaining, duration)
        for index in (1, 2, None, 1):
            self.queue(scene, index)
            for action in ('reload_clip', 'switch_shell'):
                self.intent(scene, action, index=2)
                scene.runtime._apply_shell_intent()
            self.assertEqual((0, 0, remaining, duration),
                (gun.shot_index, gun.clip, gun.reload_time, gun.reload_duration))
        self.assertEqual(1, sum(code == scene.settings.RELOAD_PARTIAL_CLIP
                                for code, unused in scene.setting_calls))
        self.assertFalse(any(code == scene.settings.CURRENT_SHELLS
                             for code, unused in scene.setting_calls))
        scene.advance(remaining)
        self.assertEqual((0, 6, 1, 0.),
                         (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))

    def test_native_next_input_callback_stop_releases_only_owned_future_plan(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        send = scene.battle.client.send_input
        stopped = []

        def stop_from_checkpoint(*args, **kwargs):
            result = send(*args, **kwargs)
            if not stopped:
                stopped.append(True)
                scene.control.stop('native_next_checkpoint_stop')
            return result

        scene.battle.client.send_input = stop_from_checkpoint
        self.queue(scene, 1)
        self.assertTrue(stopped)
        self.assertFalse(scene.control.active)
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.assertIsNone(gun.pending_index)
        self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102),
                          (scene.settings.NEXT_SHELLS, 101)], scene.setting_calls)

    def test_native_current_or_next_callback_cannot_reload_replacement_gun(self):
        for setting in ('CURRENT_SHELLS', 'NEXT_SHELLS'):
            with self.subTest(setting=setting):
                scene = self.scene()
                original = scene.battle._gun_state
                original.clip = 3
                replacement = GunState(scene.entity.typeDescriptor,
                                       ammo_layout={101: 12, 102: 9})
                replacement.clip, replacement.reload_time = 2, 0.
                before = (replacement.shot_index, replacement.clip,
                          replacement.pending_index, replacement.reload_time,
                          list(replacement.ammo))
                send, replaced = scene.battle.client.send_input, []

                def replace_from_checkpoint(*args, **kwargs):
                    result = send(*args, **kwargs)
                    if not replaced:
                        replaced.append(True)
                        scene.battle._gun_state = replacement
                    return result

                scene.battle.client.send_input = replace_from_checkpoint
                # The real setting has already mutated the original gun when
                # its native input checkpoint synchronously replaces the owner.
                # Neither the setting's return nor a stale reload decision may
                # grant an operation on that replacement gun.
                if setting == 'CURRENT_SHELLS':
                    self.intent(scene, 'switch_shell', 1)
                    scene.runtime._apply_shell_intent()
                    self.assertEqual((1, 0), (original.shot_index, original.clip))
                    self.assertGreater(original.reload_time, 0.)
                else:
                    self.queue(scene, 1)
                    self.assertEqual((0, 3, 1, 0.),
                        (original.shot_index, original.clip,
                         original.pending_index, original.reload_time))
                self.assertTrue(replaced)
                self.assertIs(replacement, scene.runtime.gun)
                self.assertNotEqual(scene.runtime._identity, scene.runtime._binding())
                self.intent(scene, 'reload_clip', 0)
                scene.runtime._apply_shell_intent()
                self.assertEqual(before,
                    (replacement.shot_index, replacement.clip,
                     replacement.pending_index, replacement.reload_time,
                     replacement.ammo))
                self.assertEqual([(getattr(scene.settings, setting), 102)],
                                 scene.setting_calls)
                self.assertFalse(scene.launches())

    def failed_release(self, raises=False):
        scene = self.scene(third=True)
        self.queue(scene, 1)
        actual, refusing = scene.battle.change_vehicle_setting, [True]

        def boundary(code, value):
            if refusing[0] and code == scene.settings.NEXT_SHELLS and value == 101:
                if raises:
                    raise RuntimeError('native_next_release_unavailable')
                return False
            return actual(code, value)

        scene.battle.change_vehicle_setting = boundary
        scene.control.stop('native_next_release_unavailable')
        return scene, actual, refusing

    def test_failed_owned_next_release_retains_cleanup_for_real_retry(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                scene, unused_actual, refusing = self.failed_release(raises)
                gun = scene.battle._gun_state
                self.assertFalse(scene.control.active)
                self.assertEqual(1, gun.pending_index)
                self.assertIsNotNone(scene.runtime._owned_next_shell)
                self.assertTrue(scene.control.release_pending)
                refusing[0] = False
                scene.control.retry_releases(scene.now + 1.)
                self.assertIsNone(scene.runtime._owned_next_shell)
                self.assertIsNone(gun.pending_index)
                self.assertFalse(scene.control.release_pending)
                self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))

    def test_delayed_next_release_does_not_cancel_a_new_manual_plan(self):
        scene, actual, refusing = self.failed_release()
        gun = scene.battle._gun_state
        self.assertIsNotNone(scene.runtime._owned_next_shell)
        self.assertTrue(scene.control.release_pending)
        # The actual manual setting supersedes the retired owner's pending
        # value while that owner's physical cleanup remains unavailable.
        self.assertTrue(actual(scene.settings.NEXT_SHELLS, 103))
        self.assertEqual(2, gun.pending_index)
        refusing[0] = False
        scene.control.retry_releases(scene.now + 1.)
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.assertFalse(scene.control.release_pending)
        self.assertEqual((0, 6, 2, 0.),
                         (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102),
                          (scene.settings.NEXT_SHELLS, 103)], scene.setting_calls)

    def test_delayed_next_release_does_not_cancel_replacement_gun_pending(self):
        scene, unused_actual, refusing = self.failed_release()
        original = scene.battle._gun_state
        self.assertIsNotNone(scene.runtime._owned_next_shell)
        self.assertTrue(scene.control.release_pending)
        replacement = GunState(scene.entity.typeDescriptor,
                               ammo_layout={101: 12, 102: 9, 103: 7})
        replacement.clip, replacement.reload_time = 2, 0.
        scene.battle._gun_state = replacement
        # Deliberately choose the same pending index as the retired lease.
        # Only actual gun identity can distinguish this manual input from the
        # automatic operation whose failed cleanup is about to be retried.
        self.assertTrue(scene.battle._sender.change_vehicle_setting(
            scene.entity.id, scene.settings.NEXT_SHELLS, 102))
        self.assertEqual(1, original.pending_index)
        self.assertEqual(1, replacement.pending_index)
        before = (replacement.shot_index, replacement.clip,
                  replacement.pending_index, replacement.reload_time,
                  list(replacement.ammo))
        calls = list(scene.setting_calls)
        refusing[0] = False
        scene.control.retry_releases(scene.now + 1.)
        self.assertIsNone(scene.runtime._owned_next_shell)
        self.assertFalse(scene.control.release_pending)
        self.assertEqual(before,
            (replacement.shot_index, replacement.clip,
             replacement.pending_index, replacement.reload_time,
             replacement.ammo))
        self.assertEqual(calls, scene.setting_calls)
        self.assertEqual([(scene.settings.NEXT_SHELLS, 102)] * 2, calls)
        self.assertEqual(1, self.input_checkpoint(scene)['next_shell_index'])
        self.assertEqual(1, original.pending_index)

    def test_next_write_finishing_after_stop_still_installs_retryable_cleanup(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                scene = self.scene()
                gun = scene.battle._gun_state
                policy = scene.runtime.attack_policy
                policy.frame = policy.evaluator.snapshot(scene.now)
                self.intent(scene, 'wait')
                actual = scene.battle.change_vehicle_setting
                entered, refusing = [], [True]

                def late_native_write(code, value):
                    if (not entered and code == scene.settings.NEXT_SHELLS and value == 102):
                        entered.append(True)
                        scene.control.stop('before_native_next_write')
                        # The genuine native consumer finishes only after
                        # Stop already observed no pending write to remove.
                        return actual(code, value)
                    if refusing[0] and code == scene.settings.NEXT_SHELLS and value == 101:
                        if raises:
                            raise RuntimeError('late_native_next_cleanup_unavailable')
                        return False
                    return actual(code, value)

                def next_plan(now):
                    policy.next_shell = 1
                    return 1

                scene.battle.change_vehicle_setting = late_native_write
                # Only the tactical output is supplied. The actual update
                # stack must retain cleanup born after its reentrant Stop.
                with mock.patch.object(policy, 'update', side_effect=lambda now: policy.decision), \
                        mock.patch.object(policy, 'background', side_effect=next_plan):
                    scene.tick()
                self.assertTrue(entered)
                self.assertFalse(scene.control.active)
                self.assertEqual(1, gun.pending_index)
                self.assertIsNotNone(scene.runtime._owned_next_shell)
                self.assertTrue(scene.control.release_pending)
                refusing[0] = False
                scene.control.retry_releases(scene.now + 1.)
                self.assertIsNone(gun.pending_index)
                self.assertIsNone(scene.runtime._owned_next_shell)
                self.assertFalse(scene.control.release_pending)
                self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))

    def test_final_drive_sender_stop_prevents_later_next_shell_and_reload_consumers(self):
        for action, index in (('wait', None), ('reload_clip', 0), ('switch_shell', 1)):
            with self.subTest(action=action):
                scene = self.scene()
                gun = scene.battle._gun_state
                gun.clip = 3
                self.intent(scene, action, index)
                policy = scene.runtime.attack_policy
                policy.frame = policy.evaluator.snapshot(scene.now)
                policy.next_shell = 1
                # Supply a tactical decision only. The complete engine, final
                # native drive sender, Stop and gun consumers remain real.
                update = mock.patch.object(policy, 'update',
                    side_effect=lambda now: policy.decision)
                background = mock.patch.object(policy, 'background', return_value=1)
                inside, stopped = [False], []
                send_drive, send_input = scene.runtime._send_drive, scene.battle.client.send_input

                def final_sender():
                    inside[0] = True
                    try:
                        return send_drive()
                    finally:
                        inside[0] = False

                def stop_from_final(*args, **kwargs):
                    result = send_input(*args, **kwargs)
                    if inside[0] and not stopped:
                        stopped.append(True)
                        scene.control.stop('final_drive_checkpoint_stop')
                    return result

                scene.runtime._send_drive = final_sender
                scene.battle.client.send_input = stop_from_final
                with update, background:
                    scene.tick()
                self.assertTrue(stopped)
                self.assertFalse(scene.runtime.active)
                self.assertFalse(scene.setting_calls)
                self.assertEqual((0, 3, None, 0.),
                    (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))

    def test_unknown_native_geometry_never_authorizes_unloading_the_current_clip(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        gun.clip = 3
        before = list(gun.ammo)
        scene.runtime.attack_policy.reset()

        def unavailable():
            raise RuntimeError('native geometry is unavailable')

        scene.on_probe = unavailable
        for unused in range(100):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            self.assertIsNone(scene.runtime.attack_policy.search_started, row)
            self.assertNotIn(row['action'], ('reload_clip', 'switch_shell'))
            self.assertEqual((0, 3, 0., before),
                             (gun.shot_index, gun.clip, gun.reload_time, gun.ammo))
        self.assertFalse(scene.setting_calls)
        self.assertFalse(scene.launches())

    def test_real_global_failure_plan_waits_for_copied_retreat_attempt_before_early_reload(self):
        scene = self.scene()
        self.move_from_previous_route_point(scene)
        gun = scene.battle._gun_state
        gun.clip = 3
        for index, piercing in enumerate((1., 1000.)):
            gun.shots[index].piercingPower = (piercing, piercing)
            scene.battle.client.effective_params['gun']['shots'][index]['source_shot'][
                'piercingPower'] = (piercing, piercing)
        policy = scene.runtime.attack_policy
        policy.reset()
        self.assertIsInstance(policy.evaluator, attack_policy.NativeAttackEvaluator)
        search_started = None
        # Use the actual route-attempt boundary without actuating the vehicle.
        for unused in range(140):
            scene.step(.11)
            decision = policy.update(scene.now)
            policy.background(scene.now)
            if decision['action'] == 'search_penetration':
                scene.runtime._move_order({}, scene.now)
            if policy.search_started is not None and search_started is None:
                search_started = policy.search_started
            self.assertEqual((0, 3, 0.), (gun.shot_index, gun.clip, gun.reload_time))
            if decision['action'] == 'reload_clip' and decision.get('early_reload'):
                break
        else:
            self.fail('real native evidence did not produce an early reload plan: %r' % policy.status())
        self.assertIsNotNone(search_started)
        self.assertGreaterEqual(scene.now - search_started, attack_policy.SEARCH_SECONDS)
        self.assertEqual(1, decision['shell_index'])
        self.assertEqual('passed', decision['candidate']['armor'])
        self.assertTrue(scene.world_queries)
        # A supplied, non-arrived route anchor is the only tactical seam in
        # this withdrawal test. Endpoint freezing/progress/timeout and input
        # settlement are the copied production planner and native consumer.
        order = dict(id=scene.runtime.actor_id, combat_mode='advance',
            target_id=scene.target.id, target_kind='bot',
            move_position=(0., 0., -24.), face_position=(0., 0., 40.),
            fire_allowed=False, shell_index=0)
        began = scene.now
        moving = scene.runtime._reload_order(order, began)
        self.assertEqual('magazine_reload_retreat', moving['combat_mode'])
        self.assertEqual('withdraw', moving['tactical_phase'])
        self.assertFalse(scene.runtime._reload_retreat['ready'])
        scene.runtime._apply_shell_intent()
        self.assertFalse(scene.setting_calls)
        scene.step(server_bot_ai.RETREAT_PROGRESS_TIMEOUT_SECONDS - .01)
        scene.runtime._reload_order(order, scene.now)
        scene.runtime._apply_shell_intent()
        self.assertFalse(scene.setting_calls)
        self.assertEqual((0, 3, 0.), (gun.shot_index, gun.clip, gun.reload_time))
        scene.step(.02)
        held = scene.runtime._reload_order(order, scene.now)
        self.assertEqual('magazine_reload_hold', held['tactical_phase'])
        self.assertEqual('copied_retreat_attempt_complete', scene.runtime._reload_retreat['reason'])
        scene.runtime._apply_shell_intent()
        self.assertEqual([(scene.settings.CURRENT_SHELLS, 102)], scene.setting_calls)
        self.assertEqual((1, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertGreater(gun.reload_time, 0.)
        deadline = gun.reload_time
        scene.runtime._apply_shell_intent()
        self.assertEqual(1, len(scene.setting_calls))
        self.assertEqual(deadline, gun.reload_time)

    def test_complete_loop_carries_real_evidence_and_retreat_receipt_into_native_reload(self):
        scene = self.scene()
        gun = scene.battle._gun_state
        gun.clip = 3
        before = list(gun.ammo)
        for index, piercing in enumerate((1., 1000.)):
            gun.shots[index].piercingPower = (piercing, piercing)
            scene.battle.client.effective_params['gun']['shots'][index]['source_shot'][
                'piercingPower'] = (piercing, piercing)
        scene.runtime.attack_policy.reset()
        settings, accepted = scene.battle.change_vehicle_setting, []

        def observe_setting(code, value):
            if code in (scene.settings.CURRENT_SHELLS, scene.settings.RELOAD_PARTIAL_CLIP):
                accepted.append(dict(now=scene.now,
                    decision=copy.deepcopy(scene.runtime.attack_policy.decision),
                    retreat=copy.deepcopy(scene.runtime._reload_retreat)))
            return settings(code, value)

        scene.battle.change_vehicle_setting = observe_setting
        search_started = None
        for unused in range(230):
            row = scene.tick()
            self.assertIsNone(scene.control.last_control_failure, row)
            if scene.runtime.attack_policy.search_started is not None and search_started is None:
                search_started = scene.runtime.attack_policy.search_started
            self.assertEqual(before, gun.ammo)
            if accepted:
                break
            self.assertEqual((0, 3, 0.), (gun.shot_index, gun.clip, gun.reload_time))
        else:
            self.fail('complete foreground loop never consumed its valid alternate clip: %r' % scene.trace[-3:])
        self.assertIsNotNone(search_started)
        self.assertEqual(1, len(accepted))
        receipt = accepted[0]
        self.assertGreaterEqual(receipt['now'] - search_started, attack_policy.SEARCH_SECONDS)
        self.assertEqual('reload_clip', receipt['decision']['action'])
        self.assertTrue(receipt['decision']['early_reload'])
        self.assertEqual('passed', receipt['decision']['candidate']['armor'])
        self.assertTrue(receipt['retreat']['ready'])
        self.assertIn(receipt['retreat']['reason'],
            ('copied_cover_attempt_complete', 'copied_retreat_attempt_complete'))
        self.assertEqual((1, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertGreater(gun.reload_time, 0.)
        self.assertFalse(scene.launches())

    def test_no_verified_shot_and_no_he_yields_to_copied_withdrawal(self):
        scene = self.scene(clip=1, burst=1)
        gun = scene.battle._gun_state
        before = list(gun.ammo)
        for index in range(len(gun.shots)):
            gun.shots[index].piercingPower = (1., 1.)
            scene.battle.client.effective_params['gun']['shots'][index]['source_shot'][
                'piercingPower'] = (1., 1.)
        started = None
        for unused in range(180):
            row = self.tick_weapon(scene)
            policy = scene.runtime.attack_policy
            if started is None:
                started = policy.search_started
            if row['order'].get('combat_mode') == 'withdraw':
                break
        else:
            self.fail('The expired search never reached withdrawal: %r' % scene.trace[-3:])
        self.assertIsNotNone(started)
        self.assertGreaterEqual(scene.now - started, attack_policy.SEARCH_SECONDS)
        self.assertEqual('no_he_or_verified_penetration', policy.decision['reason'])
        self.assertEqual(before, gun.ammo)
        self.assertFalse(scene.launches())


if __name__ == '__main__':
    unittest.main()
