"""Player-owned next-cassette settings exercise the real gun transaction."""
import unittest
from types import SimpleNamespace
from unittest import mock

import test_player_control_integration_review as integration
from gui.mods.offline_lan_0922.gun_mechanics import GunState


class MagazineControlTests(unittest.TestCase):
    def control(self, clip=6, burst=1):
        fixture = integration.PlayerControlIntegrationReviewTests()
        fixture.rows = []
        control = fixture.control()
        descriptor = SimpleNamespace(gun=dict(
            clip=(clip, 2.), burst=(burst, .1), reloadTime=12.,
            shots=[dict(shell=dict(compactDescr=100+i), speed=900.,
                        gravity=9.81, maxDistance=720.) for i in range(3)]))
        gun = GunState(descriptor)
        gun.ammo = [24, 24, 24]
        gun.clip, gun.reload_time = clip, 0.
        control.owner._gun_state = gun
        control.active = True
        control.direct_engagement = SimpleNamespace(retreat=True)
        settings = SimpleNamespace(CURRENT_SHELLS=1, NEXT_SHELLS=2,
                                   RELOAD_PARTIAL_CLIP=3)
        control.owner._runtime = SimpleNamespace(constants=SimpleNamespace(
            VEHICLE_SETTING=settings))
        calls = []

        def change(code, compact):
            calls.append((code, compact))
            if code == settings.RELOAD_PARTIAL_CLIP:
                return gun.reload_partial_clip()
            index = compact - 100
            if code == settings.NEXT_SHELLS:
                gun.request_shell_index(index)
            else:
                gun.sync_shell_index(index)
            return True

        control.owner.change_vehicle_setting = mock.Mock(side_effect=change)
        return control, gun, settings, calls

    def test_next_clip_can_change_and_cancel_without_touching_loaded_cassette(self):
        control, gun, settings, calls = self.control()
        for index in (1, 2, 1):
            self.assertTrue(control.queue_next_automatic_clip(index))
            self.assertEqual(index, gun.pending_index)
            self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))
        self.assertTrue(control.queue_next_automatic_clip(None))
        self.assertIsNone(gun.pending_index)
        self.assertEqual([settings.NEXT_SHELLS]*4, [code for code, value in calls])

    def test_explicit_pending_shell_is_not_replaced_or_cancelled(self):
        control, gun, unused, calls = self.control()
        gun.request_shell_index(1)
        self.assertFalse(control.queue_next_automatic_clip(2))
        self.assertEqual(1, gun.pending_index)
        self.assertFalse(control.queue_next_automatic_clip(None))
        self.assertFalse(control.reload_automatic_clip(2))
        self.assertEqual((0, 6, 1, 0.),
                         (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))
        self.assertEqual([], calls)

    def test_direct_selection_cannot_unload_a_live_magazine(self):
        for loaded in (0, 2):
            with self.subTest(loaded=loaded):
                control, gun, unused, calls = self.control()
                gun.shot_index = loaded
                control.queue_automatic_shell(1)
                self.assertEqual((loaded, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))
                self.assertEqual([], calls)

    def test_single_round_and_existing_artillery_selection_are_unchanged(self):
        for clip, direct in ((1, True), (6, False)):
            with self.subTest(clip=clip, direct=direct):
                control, gun, settings, calls = self.control(clip)
                if not direct:
                    control.direct_engagement = None
                control.queue_automatic_shell(1)
                expected = settings.CURRENT_SHELLS if direct else settings.NEXT_SHELLS
                self.assertEqual([(expected, 101)], calls)

    def test_refused_next_clip_cannot_reload_the_wrong_ammo(self):
        control, gun, unused, calls = self.control()
        control.owner.change_vehicle_setting = mock.Mock(return_value=False)
        self.assertFalse(control.reload_automatic_clip(2))
        self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))
        self.assertEqual(1, control.owner.change_vehicle_setting.call_count)

    def test_partial_reload_requires_the_withdrawal_policy(self):
        control, gun, unused, calls = self.control()
        control.direct_engagement.retreat = False
        self.assertFalse(control.reload_automatic_clip(1))
        self.assertEqual([], calls)
        self.assertEqual(6, gun.clip)

    def test_authorized_reload_promotes_one_plan_once(self):
        control, gun, settings, calls = self.control()
        self.assertTrue(control.reload_automatic_clip(2))
        self.assertEqual([(settings.NEXT_SHELLS, 102), (settings.RELOAD_PARTIAL_CLIP, 0)], calls)
        self.assertEqual((2, 0, gun.reload), (gun.shot_index, gun.clip, gun.reload_time))
        self.assertFalse(control.reload_automatic_clip(2))
        self.assertEqual(2, len(calls))

    def test_active_trigger_does_not_receive_automatic_ammo_settings(self):
        for attribute in ('_local_fire_intent', '_local_player_burst'):
            with self.subTest(attribute=attribute):
                control, gun, unused, calls = self.control(burst=2)
                setattr(control.owner, attribute, {'owned': True})
                self.assertFalse(control.queue_next_automatic_clip(1))
                self.assertFalse(control.reload_automatic_clip(1))
                self.assertEqual([], calls)
                self.assertEqual((0, 6), (gun.shot_index, gun.clip))

    def test_gun_replacement_inside_setting_callback_cannot_reload_replacement(self):
        control, gun, unused, calls = self.control()
        replacement = self.control()[1]

        def replace(code, value):
            calls.append((code, value))
            control.owner._gun_state = replacement
            return True

        control.owner.change_vehicle_setting.side_effect = replace
        self.assertFalse(control.reload_automatic_clip(1))
        self.assertEqual(1, len(calls))
        self.assertEqual((0, 6, 0.), (replacement.shot_index, replacement.clip, replacement.reload_time))

    def test_plan_remains_pending_across_subshots_and_promotes_only_at_clip_end(self):
        control, gun, unused, calls = self.control(clip=4, burst=2)
        self.assertTrue(control.queue_next_automatic_clip(2))
        self.assertTrue(gun.begin_burst(2))
        self.assertTrue(gun.commit_burst_round(False))
        self.assertEqual((0, 3, 2), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertTrue(gun.commit_burst_round(True))
        self.assertEqual((0, 2, 2), (gun.shot_index, gun.clip, gun.pending_index))
        gun.reload_time = 0.
        self.assertTrue(gun.begin_burst(2))
        self.assertTrue(gun.commit_burst_round(False))
        self.assertEqual((0, 1, 2), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertTrue(gun.commit_burst_round(True))
        self.assertEqual((2, 0, None), (gun.shot_index, gun.clip, gun.pending_index))
        self.assertEqual(gun.reload, gun.reload_time)

    def late_write_after_stop(self, raises=False):
        control, gun, settings, calls = self.control()
        refusing = [True]
        def change(code, compact):
            calls.append((code, compact))
            if len(calls) == 1:
                # The native write finishes after a synchronous Stop callback
                # already observed no pending shell and released its token.
                control.stop('stop_before_native_next_shell_write')
                gun.request_shell_index(compact - 100)
                return True
            if refusing[0]:
                if raises:
                    raise RuntimeError('native_next_shell_cleanup_failed')
                return False
            gun.request_shell_index(compact - 100)
            return True
        control.owner.change_vehicle_setting.side_effect = change
        self.assertFalse(control.queue_next_automatic_clip(2))
        return control, gun, settings, calls, refusing

    def test_stop_during_native_next_write_retries_a_refused_or_failed_cleanup(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                control, gun, settings, calls, refusing = self.late_write_after_stop(raises)
                self.assertFalse(control.active)
                self.assertEqual((gun, 2), control.next_clip_request)
                self.assertEqual(['clip_ammo_release'],
                                 [stage for stage, unused in control.release_pending])
                self.assertEqual((0, 6, 2, 0.),
                                 (gun.shot_index, gun.clip, gun.pending_index, gun.reload_time))
                refusing[0] = False
                control.retry_releases(control.next_release)
                self.assertEqual([], control.release_pending)
                self.assertIsNone(control.next_clip_request)
                self.assertIsNone(gun.pending_index)
                self.assertEqual((0, 6, 0.), (gun.shot_index, gun.clip, gun.reload_time))
                self.assertEqual([(settings.NEXT_SHELLS, 102), (settings.NEXT_SHELLS, 100),
                                  (settings.NEXT_SHELLS, 100)], calls)
                control.retry_releases(control.next_release + 2.)
                self.assertEqual(3, len(calls))

    def test_delayed_clip_cleanup_preserves_a_manual_plan_or_replaced_gun(self):
        for replace_gun in (False, True):
            with self.subTest(replace_gun=replace_gun):
                control, gun, unused, calls, refusing = self.late_write_after_stop()
                self.assertEqual(['clip_ammo_release'],
                                 [stage for stage, unused in control.release_pending])
                current = self.control()[1] if replace_gun else gun
                current.request_shell_index(1)
                control.owner._gun_state = current
                refusing[0] = False
                control.retry_releases(control.next_release)
                self.assertEqual([], control.release_pending)
                self.assertIsNone(control.next_clip_request)
                self.assertEqual((0, 6, 1, 0.),
                                 (current.shot_index, current.clip, current.pending_index, current.reload_time))
                self.assertEqual(2, len(calls))


if __name__ == '__main__':
    unittest.main()
