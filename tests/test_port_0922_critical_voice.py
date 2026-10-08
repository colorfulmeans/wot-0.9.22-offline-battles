"""Damage-and-critical feedback must retain the stock successful-hit voice."""
import copy
import types
import unittest
from unittest import mock

import test_port_0922_he_feedback as he_feedback
from gui.mods.offline_lan_0922 import critical_voice


class CriticalVoiceTests(unittest.TestCase):
    def test_nonpenetrating_internal_event_does_not_invent_a_penetration_voice(self):
        runtime,battle,attacker,target,event=he_feedback.HEFeedbackTests()._fixture()
        event.update(shell_index=0,shot_result=1,damage=0)
        event['critical']={'events':[{'kind':'device','name':'engineHealth',
            'old_state':'normal','state':'destroyed','cause':'shot'}]}
        with mock.patch.object(critical_voice,'present') as present:
            battle._present_combat_feedback(event,target,attacker)
        present.assert_not_called()
        vhf=runtime.constants.VEHICLE_HIT_FLAGS
        self.assertFalse(battle._avatar.shot_results[0][0]>>32 &
            vhf.MATERIAL_WITH_POSITIVE_DF_PIERCED_BY_PROJECTILE)

    def test_hp_damage_voices_are_never_replaced_by_a_no_damage_event(self):
        for name in (
                'enemy_hp_damaged_by_projectile_by_player',
                'enemy_hp_damaged_by_projectile_and_chassis_damaged_by_player',
                'enemy_hp_damaged_by_projectile_and_gun_damaged_by_player',
                'enemy_hp_damaged_by_explosion_at_direct_hit_by_player',
                'enemy_hp_damaged_by_near_explosion_by_player',
                'enemy_fire_started_by_player'):
            sound = types.SimpleNamespace(play=mock.Mock())
            avatar = types.SimpleNamespace(soundNotifications=sound)
            results = [(17 << 32) | 11]
            critical_voice.present(avatar, lambda values:
                avatar.soundNotifications.play(name, 11), results)
            sound.play.assert_called_once_with(name, 11)
            self.assertIs(sound, avatar.soundNotifications)
            self.assertFalse(hasattr(avatar, '_offlineCriticalVoiceCount'))

    def test_module_only_priority_preserves_flags_and_restores_on_exception(self):
        sound = types.SimpleNamespace(play=mock.Mock())
        avatar = types.SimpleNamespace(soundNotifications=sound)
        results = [(2081 << 32) | 11]

        def callback(values):
            self.assertIs(results, values)
            avatar.soundNotifications.play(
                'enemy_no_hp_damage_at_attempt_and_chassis_damaged_by_player', 11)
            raise ValueError('stock callback failure')

        with self.assertRaises(ValueError):
            critical_voice.present(avatar, callback, results)
        sound.play.assert_called_once_with(critical_voice.CRITICAL_EVENT, 11)
        self.assertIs(sound, avatar.soundNotifications)
        self.assertEqual([(2081 << 32) | 11], results)

    def test_runtime_uses_priority_only_for_nonlethal_zero_hp_module_hits(self):
        fixture = he_feedback.HEFeedbackTests()
        for damage, dead in ((150, False), (0, False), (150, True)):
            for device in ('leftTrackHealth', 'rightTrackHealth',
                           'gunHealth', 'engineHealth'):
                with self.subTest(damage=damage, dead=dead, device=device):
                    expected_proxy=damage==0 and not dead and device=='engineHealth'
                    runtime, battle, attacker, target, event = fixture._fixture()
                    event.update(shell_index=0, shot_result=2,
                                 damage=damage, dead=dead)
                    event['critical'] = {'events': [
                        {'kind': 'device', 'name': device, 'old_state': 'normal',
                         'state': 'destroyed', 'cause': 'shot'}]}
                    original = copy.deepcopy(event)
                    with mock.patch.object(critical_voice, 'present',
                            side_effect=lambda avatar, cb, values: cb(values)) as present:
                        battle._present_combat_feedback(event, target, attacker)
                    self.assertEqual(int(expected_proxy), present.call_count)
                    flags = battle._avatar.shot_results[0][0] >> 32
                    vhf = runtime.constants.VEHICLE_HIT_FLAGS
                    self.assertTrue(flags & vhf.DEVICE_PIERCED_BY_PROJECTILE)
                    self.assertTrue(flags & vhf.MATERIAL_WITH_POSITIVE_DF_PIERCED_BY_PROJECTILE)
                    self.assertEqual(original, event)
                    output = battle._avatar.battle_events[0]
                    event_types = runtime.battle_feedback_common.BATTLE_EVENT_TYPE
                    self.assertTrue(any(e['eventType'] == event_types.CRIT for e in output))
                    self.assertEqual(bool(damage), any(
                        e['eventType'] == event_types.DAMAGE for e in output))


if __name__ == '__main__':
    unittest.main()
