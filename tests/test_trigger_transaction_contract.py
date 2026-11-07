"""Committed triggers survive tactical changes through the real Bot loop."""

from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'server')]

from tests import test_port_0922_bot_runtime as fixtures


class TriggerRuntimeIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.fixture = fixtures.BotRuntimeTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.module = self.fixture.module

    def _ready_runtime(self):
        descriptor = fixtures._combat_descriptor(
            reload_time=4.0, clip=(5, 2.0), dispersion=0.01,
            max_ammo=20)
        descriptor.gun.burst = (3, 0.1)
        descriptor.gun.shotDispersionFactors = {
            'afterShot': 4.0, 'afterShotInBurst': 1.0,
            'turretRotation': 0.0,
        }
        command = {
            'target_yaw': 0.0, 'throttle': 0.0, 'turn': 0.0,
            'shell_index': 0, 'fire_allowed': False, 'target_id': None,
            'fire_range': 500.0, 'combat_mode': 'hold',
            'aim_position': (0.0, 1.0, 0.0),
            'face_position': (0.0, 1.0, 0.0),
            'move_position': (0.0, 0.0, 100.0),
            'recovery_mode': 'arrived', 'movement_intent': False,
        }
        runtime = self.module.BotRuntime(
            1, descriptor_resolver=lambda unused: descriptor,
            adapter_factory=lambda *unused, **kwargs: fixtures._FixedAdapter(command),
            control_seconds=self.module.WORKER_CONTROL_SECONDS,
            direction_probe=lambda *unused: {'clear': True, 'slope': 0.0},
            visibility_probe=lambda *unused: False,
            firing_lane_probe=lambda *unused: False,
            friendly_lane_probe=lambda *unused: False,
            direct_launch_origin_probe=lambda source, *unused: (
                source['x'], source['y'] + 1.0, source['z']),
            ground_probe=lambda *unused: 0.0,
            physics_ground_probe=lambda *unused: 0.0,
            spawn_resolver=fixtures._spawn_resolver,
            baked_graph=fixtures._graph())
        self.addCleanup(runtime.close)
        runtime.battle_start(self.fixture.start)
        runtime._next_observation = 100.0
        runtime._next_shot_lane_refresh = 100.0
        runtime._next_cover_refresh = 100.0
        state = runtime.states[11]
        state['gun_aligned'] = True
        gun = runtime._gun_states[11]
        gun.elapsed = 10.0
        ammo = runtime._ammo_states[11]
        initial_ammo = ammo.remaining[ammo.loaded]
        return runtime, state, gun, ammo, initial_ammo

    def _running_trigger(self):
        runtime, state, gun, ammo, initial_ammo = self._ready_runtime()
        descriptor = runtime._descriptors[state['id']]
        preview = runtime._direct_launch_preview(
            state, descriptor, ammo.loaded, gun, {'flight_time': 0.5})
        self.assertTrue(runtime._fire(
            state, gun, 1.0, descriptor, ammo_state=ammo,
            launch_preview=preview, launch_time_us=0))
        return runtime, state, gun, ammo, initial_ammo

    def test_physical_terminal_before_first_commit_preserves_ready_weapon(self):
        for reason in self.module.burst_mechanics.TERMINAL_REASONS:
            with self.subTest(reason=reason):
                runtime, state, gun, ammo, initial_ammo = self._ready_runtime()
                clock = runtime._burst_states[state['id']]
                before = (list(ammo.remaining), gun.clip, gun.elapsed,
                          gun.reload_duration, gun.reload_kind,
                          gun.ready(), state['fire_seq'])
                self.assertTrue(clock.start(1, 3, .1, ammo.loaded))
                gun.begin_burst(3, 1.)
                self.assertEqual(0, clock.next_index)
                self.assertEqual(3, gun._burst_remaining)
                self.assertEqual([], runtime._pending_launches)

                self.assertTrue(runtime._terminate_active_trigger(
                    state, reason, gun_state=gun, ammo_state=ammo,
                    burst_state=clock))

                self.assertEqual(before, (list(ammo.remaining), gun.clip, gun.elapsed,
                    gun.reload_duration, gun.reload_kind, gun.ready(), state['fire_seq']))
                self.assertEqual(initial_ammo, ammo.remaining[ammo.loaded])
                self.assertFalse(clock.active)
                self.assertEqual(0, clock.next_index)
                self.assertEqual(reason, clock.terminal_reason)
                self.assertEqual(0, gun._burst_remaining)
                self.assertEqual([], runtime._pending_launches)

    def test_duplicate_first_request_cannot_abort_an_armed_uncommitted_trigger(self):
        runtime, state, gun, ammo, unused = self._ready_runtime()
        descriptor = runtime._descriptors[state['id']]
        preview = runtime._direct_launch_preview(
            state, descriptor, ammo.loaded, gun, {'flight_time': 0.5})
        clock = runtime._burst_states[state['id']]
        self.assertTrue(clock.start(1, 3, .1, ammo.loaded))
        self.assertTrue(gun.begin_burst(3, 1.))
        self.assertEqual(0, clock.next_index)
        self.assertEqual([], runtime._pending_launches)
        before_clock = dict(clock.__dict__)
        before_gun = dict(gun.__dict__)
        before_ammo = list(ammo.remaining)
        before_sequence = state['fire_seq']

        self.assertFalse(runtime._fire(
            state, gun, 1., descriptor, ammo_state=ammo,
            launch_preview=preview, launch_time_us=0))

        self.assertEqual(before_clock, clock.__dict__)
        self.assertEqual(before_gun, gun.__dict__)
        self.assertEqual(before_ammo, ammo.remaining)
        self.assertEqual(before_sequence, state['fire_seq'])
        self.assertTrue(clock.active)
        self.assertEqual((0, 3), (clock.next_index, gun._burst_remaining))
        self.assertEqual([], runtime._pending_launches)

    def test_real_bot_loop_finishes_trigger_without_a_target_or_fire_order(self):
        runtime, state, gun, ammo, initial_ammo = self._running_trigger()
        state['gun_aligned'] = False
        friendly = mock.Mock(return_value=False)
        runtime.friendly_lane_probe = friendly
        with mock.patch.object(runtime, '_advance_active_burst',
                               wraps=runtime._advance_active_burst) as advance, \
                mock.patch.object(runtime, '_fire', wraps=runtime._fire) as fire:
            updates = runtime.update(0.21, 0.21, players=[])

        self.assertEqual(2, advance.call_count)
        self.assertTrue(all(call.args[5] is None for call in advance.call_args_list))
        self.assertTrue(all(call.args[6] is None for call in advance.call_args_list))
        friendly.assert_not_called()
        self.assertEqual(initial_ammo - 3, ammo.remaining[ammo.loaded])
        self.assertEqual(2, gun.clip)
        self.assertEqual(3, state['fire_seq'])
        self.assertFalse(runtime._burst_states[11].active)
        self.assertEqual([1, 2, 3], [
            launch['fire_seq'] for launch in runtime._pending_launches])
        self.assertEqual([0, 100000, 200000], [
            launch['launch_time_us'] for launch in runtime._pending_launches])
        self.assertTrue(any(message.get('type') == 'bot_state'
                            for message in updates))
        # The policy never issued a new trigger after the physical tail.
        self.assertTrue(runtime.adapter.calls)
        self.assertFalse(runtime.adapter.command['fire_allowed'])
        fire.assert_not_called()

    def test_real_bot_death_branch_terminates_tail_without_extra_shells(self):
        runtime, state, gun, ammo, initial_ammo = self._running_trigger()
        state['alive'] = False
        state['health'] = 0

        runtime.update(0.21, 0.21, players=[])

        clock = runtime._burst_states[11]
        self.assertFalse(clock.active)
        self.assertEqual('actor_destroyed', clock.terminal_reason)
        self.assertEqual(1, clock.next_index)
        self.assertEqual(initial_ammo - 1, ammo.remaining[ammo.loaded])
        self.assertEqual(4, gun.clip)
        self.assertEqual(0, gun._burst_remaining)
        self.assertEqual(1, state['fire_seq'])
        self.assertEqual(1, len(runtime._pending_launches))


if __name__ == '__main__':
    unittest.main()
