"""First-trigger mode boundary, independent of ammunition and native tails.

These tests exercise the real foreground authorization and copied transition
consumers with controlled native observations. They do not emulate a Windows
gameplay session or substitute for actual-barrel first-edge admission.
"""
from types import SimpleNamespace
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import siege_mechanics
from gui.mods.offline_lan_0922.player_control import full_runtime


class SiegeLaunchBoundaryTests(unittest.TestCase):
    def scene(self, mode=siege_mechanics.ENABLED, has_mode=True, clip=1):
        entity = SimpleNamespace(typeDescriptor=SimpleNamespace(hasSiegeMode=has_mode),
                                 siegeState=mode)
        gun = SimpleNamespace(clip=clip, clip_size=clip)
        battle = SimpleNamespace(_gun_state=gun, _local_siege_pending=None,
                                 _local_siege_braking=None, _local_player_burst=None)
        runtime = full_runtime.FullPlayerRuntime(battle)
        runtime.entity = entity
        runtime.actor_id = 77
        runtime.active = True
        runtime.features = {'fire', 'drive'}
        state = dict(id=77, siege_state=mode, gun_aligned=True,
                     position=(0., 0., 0.), profile=dict(class_tag='TD'))
        runtime.engine = SimpleNamespace(states={77: state})
        runtime.planner = SimpleNamespace(_target_decisions={})
        runtime._identity = ('round', 77)
        runtime._binding = lambda: runtime._identity
        runtime._live = lambda *args: True
        runtime._mission_brakes = lambda: False
        runtime.pose_stamp = lambda: ('current', 1)
        runtime.weapon.owned = lambda: True
        runtime.weapon.verified = True
        target = dict(kind='bot', id=42, network_id=42, position=(0., 0., 40.),
                      visible=True, alive=True)
        runtime._targets = [target]
        # This unit starts at an already-selected original planner order;
        # cold-start LOS/admission is exercised by the full ownership suite.
        runtime.combat_stop.accept(dict(combat_mode='engage', target_kind='bot', target_id=42))
        context = dict(source_pose=runtime.pose_stamp(), target=target)
        return runtime, battle, state, context

    def test_navigation_handoff_revokes_an_earlier_automatic_trigger_context(self):
        runtime, unused_battle, unused_state, context = self.scene(clip=6)
        self.assertIsNone(runtime.authorize_trigger(context, runtime.entity, runtime.gun, None))
        runtime.combat_stop.accept(dict(combat_mode='route', move_position=(100., 0., 0.)))
        self.assertEqual('original_combat_not_admitted', runtime.authorize_trigger(
            context, runtime.entity, runtime.gun, None))
        self.assertEqual(6, runtime.gun.clip)

    def test_travel_and_both_transition_states_refuse_automatic_first_edge(self):
        for mode in (siege_mechanics.DISABLED, siege_mechanics.SWITCHING_ON,
                     siege_mechanics.SWITCHING_OFF):
            with self.subTest(mode=mode):
                runtime, unused_battle, unused_state, context = self.scene(mode)
                self.assertEqual('siege_mode_not_ready', runtime.authorize_trigger(
                    context, runtime.entity, runtime.gun, None))

    def test_stable_enabled_native_echo_admits_normal_alignment_checks(self):
        runtime, unused_battle, unused_state, context = self.scene()
        self.assertIsNone(runtime.authorize_trigger(context, runtime.entity, runtime.gun, None))

    def test_enabled_entity_without_matching_observed_mode_is_not_ready(self):
        runtime, unused_battle, state, context = self.scene()
        state['siege_state'] = siege_mechanics.SWITCHING_ON
        self.assertEqual('siege_mode_not_ready', runtime.authorize_trigger(
            context, runtime.entity, runtime.gun, None))

    def test_pending_observer_native_request_and_unsent_brake_each_fence_first_edge(self):
        for holder, field, value in (
                ('runtime', '_siege_pending', dict(enabled=True)),
                ('battle', '_local_siege_pending', (False, 18)),
                ('battle', '_local_siege_braking', False)):
            with self.subTest(field=field):
                runtime, battle, unused_state, context = self.scene()
                setattr(runtime if holder == 'runtime' else battle, field, value)
                self.assertEqual('siege_mode_not_ready', runtime.authorize_trigger(
                    context, runtime.entity, runtime.gun, None))

    def test_native_gun_alignment_and_source_pose_still_required_after_mode_entry(self):
        for mutation, reason in (('source', 'source_pose_changed'),
                                 ('inverse', 'native_gun_not_aligned'),
                                 ('barrel', 'native_gun_not_aligned')):
            with self.subTest(mutation=mutation):
                runtime, unused_battle, state, context = self.scene()
                if mutation == 'source':
                    context['source_pose'] = ('old', 0)
                elif mutation == 'inverse':
                    runtime.weapon.verified = False
                else:
                    state['gun_aligned'] = False
                self.assertEqual(reason, runtime.authorize_trigger(
                    context, runtime.entity, runtime.gun, None))

    def test_ordinary_tank_has_no_siege_mode_requirement(self):
        runtime, unused_battle, unused_state, context = self.scene(
            siege_mechanics.DISABLED, has_mode=False)
        self.assertIsNone(runtime.authorize_trigger(context, runtime.entity, runtime.gun, None))

    def test_plain_enabled_child_retains_physical_capability_and_pending_fence(self):
        runtime, unused_battle, unused_state, context = self.scene(has_mode=False)
        runtime.engine._descriptor_pairs = {
            77: (SimpleNamespace(hasSiegeMode=True), runtime.entity.typeDescriptor)}
        self.assertTrue(runtime.siege_capable())
        self.assertIsNone(runtime.authorize_trigger(context, runtime.entity, runtime.gun, None))
        runtime._siege_pending = dict(enabled=False)
        self.assertEqual('siege_mode_not_ready', runtime.authorize_trigger(
            context, runtime.entity, runtime.gun, None))
        self.assertTrue(runtime.siege_navigation_owns(dict(combat_mode='base_defense')))

    def test_retained_native_outer_descriptor_also_preserves_capability(self):
        runtime, battle, unused_state, context = self.scene(
            siege_mechanics.SWITCHING_OFF, has_mode=False)
        battle._local_descriptor = SimpleNamespace(hasSiegeMode=True)
        self.assertTrue(runtime.siege_capable())
        self.assertEqual('siege_mode_not_ready', runtime.authorize_trigger(
            context, runtime.entity, runtime.gun, None))

    def test_single_and_magazine_enabled_guns_share_the_same_mode_boundary(self):
        for clip in (1, 4, 30):
            with self.subTest(clip=clip):
                runtime, unused_battle, unused_state, context = self.scene(clip=clip)
                self.assertIsNone(runtime.authorize_trigger(
                    context, runtime.entity, runtime.gun, None))
                self.assertEqual(clip, runtime.gun.clip)

    def test_travel_first_edge_cannot_apply_next_shell_or_submit_a_native_trigger(self):
        runtime, unused_battle, state, unused_context = self.scene(siege_mechanics.DISABLED)
        runtime.controller = SimpleNamespace(issue_automatic_trigger=mock.Mock())
        runtime._apply_next_shell = mock.Mock()
        engine = SimpleNamespace(player_runtime=runtime)
        self.assertFalse(full_runtime._PlayerBehaviorEngine._fire(
            engine, state, runtime.gun, 1., runtime.entity.typeDescriptor))
        runtime._apply_next_shell.assert_not_called()
        runtime.controller.issue_automatic_trigger.assert_not_called()

    def test_a_committed_physical_group_blocks_mode_change_not_the_rest_of_a_magazine(self):
        runtime, battle, state, unused_context = self.scene(clip=30)
        observer = full_runtime._TriggerObservation(runtime)
        desired = mock.Mock(return_value=False)
        engine = SimpleNamespace(_descriptor_pairs={77: ('travel', 'siege')},
                                 _burst_states={77: observer}, _siege_desired=desired)
        battle._local_player_burst = dict(committed=1, count=3)
        command = dict(fire_allowed=False)
        self.assertFalse(full_runtime.copied_runtime.BotRuntime._update_bot_siege_intent(
            engine, state, command, None, .1))
        desired.assert_not_called()
        self.assertTrue(observer.active)
        self.assertEqual(30, runtime.gun.clip)
        battle._local_player_burst = None
        self.assertFalse(observer.active)


if __name__ == '__main__':
    unittest.main()
