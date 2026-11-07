from __future__ import print_function

import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'src' / 'res' / 'scripts' / 'client'
sys.path.insert(0, str(CLIENT))

from gui.mods.offline_lan_0922 import burst_mechanics
from gui.mods.offline_lan_0922 import gun_mechanics
from gui.mods.offline_lan_0922 import native_weapons


class TriggerMechanicsTests(unittest.TestCase):

    def test_native_facade_is_a_clock_subtype_for_python_two_method_binding(self):
        # In Python 2, calling TriggerClock.accepts/publish with an unrelated
        # NativeBurst raises TypeError even if its fields look identical.
        self.assertTrue(issubclass(native_weapons.NativeBurst,
                                   burst_mechanics.TriggerClock))
        clock = native_weapons.NativeBurst(object())
        clock._sync((True, 41, 3, 1, 0.1, 0.0, 0))
        due = dict(shot_seq=42, burst_group_seq=41, burst_index=1,
                   burst_count=3, shell_index=0, final=False)
        self.assertTrue(clock.accepts(due))
        wire = {}
        clock.publish(wire)
        self.assertEqual(1, wire['burst_next_index'])
        self.assertEqual(41, wire['burst_group_seq'])

    @staticmethod
    def _gun(count=3, interval=0.1):
        return types.SimpleNamespace(
            burst=(count, interval),
            shotDispersionFactors={
                'afterShot': 4.0,
                'afterShotInBurst': 1.25,
            })

    def test_descriptor_count_is_clamped_by_ammo_and_loaded_clip(self):
        self.assertEqual(
            (2, 0.1),
            burst_mechanics.planned_count(self._gun(5), 7, 2))
        self.assertEqual(
            (0, 0.1),
            burst_mechanics.planned_count(self._gun(5), 0, 5))

    def test_every_crossed_interval_produces_a_unique_physical_sequence(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(41, 5, 0.1, 2))

        first = clock.advance(0.0)
        self.assertTrue(clock.commit(first[0]))
        crossed = clock.advance(0.205)

        self.assertEqual([41], [edge['shot_seq'] for edge in first])
        self.assertEqual([42, 43], [edge['shot_seq'] for edge in crossed])
        self.assertEqual([1, 2], [edge['burst_index'] for edge in crossed])
        self.assertEqual([0.1, 0.2], [
            round(edge['due_offset'], 6) for edge in crossed])
        self.assertEqual(1, clock.next_index)
        self.assertAlmostEqual(-0.105, clock.time_left)
        for edge in crossed:
            self.assertTrue(clock.commit(edge))
        self.assertEqual(3, clock.next_index)
        self.assertAlmostEqual(0.095, clock.time_left)
        self.assertTrue(clock.active)

    def test_last_round_finishes_the_group_at_the_exact_cadence(self):
        clock = burst_mechanics.TriggerClock()
        clock.start(9, 3, 0.1, 0)

        edges = clock.advance(0.2)

        self.assertEqual([9, 10, 11], [edge['shot_seq'] for edge in edges])
        self.assertTrue(edges[-1]['final'])
        self.assertTrue(clock.active)
        self.assertEqual(0, clock.next_index)
        for index, edge in enumerate(edges):
            self.assertTrue(clock.commit(edge))
            self.assertEqual(index + 1 < len(edges), clock.active)
        self.assertEqual(3, clock.next_index)
        self.assertEqual(0.0, clock.time_left)

    def test_wire_snapshot_preserves_only_the_unlaunched_tail(self):
        source = burst_mechanics.TriggerClock()
        source.start(100, 5, 0.1, 1)
        for edge in source.advance(0.22):
            self.assertTrue(source.commit(edge))
        wire = {}
        source.publish(wire)

        restored = burst_mechanics.TriggerClock()
        self.assertTrue(restored.restore(wire, 102))

        self.assertEqual((), restored.advance(0.079))
        due = restored.advance(0.001)
        self.assertEqual([103], [edge['shot_seq'] for edge in due])
        self.assertEqual(3, restored.next_index)
        self.assertTrue(restored.commit(due[0]))
        self.assertEqual(4, restored.next_index)

    def test_physical_termination_keeps_the_group_already_on_the_wire(self):
        clock = burst_mechanics.TriggerClock()
        clock.start(20, 5, 0.1, 0)
        self.assertTrue(clock.commit(clock.advance(0.0)[0]))

        self.assertTrue(clock.terminate('actor_destroyed'))
        wire = {}
        clock.publish(wire)

        self.assertFalse(wire['burst_active'])
        self.assertEqual(20, wire['burst_group_seq'])
        self.assertEqual(5, wire['burst_count'])
        self.assertEqual(1, wire['burst_next_index'])
        self.assertEqual('actor_destroyed', clock.terminal_reason)
        restored = burst_mechanics.TriggerClock()
        self.assertTrue(restored.restore(wire, 20))
        self.assertEqual((), restored.advance(1.0))

    def test_incomplete_or_sequence_inconsistent_wire_state_is_rejected(self):
        clock = burst_mechanics.TriggerClock()
        with self.assertRaises(ValueError):
            clock.restore({'burst_active': True}, 1)

        source = burst_mechanics.TriggerClock()
        source.start(20, 3, 0.1, 0)
        self.assertTrue(source.commit(source.advance(0.0)[0]))
        wire = {}
        source.publish(wire)
        with self.assertRaises(ValueError):
            clock.restore(wire, 99)

    def test_scheduling_does_not_commit_and_zero_time_repeats_the_same_edge(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(6, 3, 0.1, 2))

        first = clock.advance(0.0)

        self.assertEqual(first, clock.advance(0.0))
        self.assertTrue(clock.active)
        self.assertEqual(0, clock.next_index)
        self.assertEqual(0.0, clock.time_left)
        self.assertTrue(clock.accepts(first[0]))
        self.assertEqual(0, clock.next_index)
        self.assertTrue(clock.commit(first[0]))
        self.assertEqual(1, clock.next_index)
        self.assertFalse(clock.accepts(first[0]))
        self.assertFalse(clock.commit(first[0]))
        self.assertEqual((), clock.advance(0.0))
        self.assertAlmostEqual(0.1, clock.time_left)

    def test_single_round_trigger_is_not_finished_until_its_launch_commits(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(6, 1, 0.0, 2))

        edge = clock.advance(0.0)[0]

        self.assertTrue(edge['final'])
        self.assertTrue(clock.active)
        self.assertEqual(0, clock.next_index)
        self.assertTrue(clock.commit(edge))
        self.assertFalse(clock.active)
        self.assertEqual(1, clock.next_index)
        self.assertEqual(0.0, clock.time_left)
        self.assertFalse(clock.commit(edge))
        wire = {}
        clock.publish(wire)
        restored = burst_mechanics.TriggerClock()
        self.assertTrue(restored.restore(wire, 6))
        self.assertEqual((), restored.advance(1.0))

    def test_early_out_of_order_and_forged_edges_do_not_advance_the_clock(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(20, 3, 0.1, 2))
        first = clock.advance(0.0)[0]
        for name, value in (
                ('shot_seq', 21), ('burst_group_seq', 19),
                ('burst_index', 1), ('burst_count', 2),
                ('shell_index', 1), ('final', True)):
            with self.subTest(field=name):
                forged = dict(first)
                forged[name] = value
                self.assertFalse(clock.accepts(forged))
                self.assertFalse(clock.commit(forged))
                self.assertEqual(0, clock.next_index)
                self.assertTrue(clock.active)
        self.assertTrue(clock.commit(first))
        second = dict(first, shot_seq=21, burst_index=1)
        self.assertFalse(clock.commit(second))
        self.assertEqual(1, clock.next_index)
        self.assertAlmostEqual(0.1, clock.time_left)
        due = clock.advance(0.2)
        self.assertFalse(clock.commit(due[1]))
        self.assertEqual(1, clock.next_index)
        self.assertTrue(clock.commit(due[0]))
        self.assertFalse(clock.commit(due[0]))
        self.assertTrue(clock.commit(due[1]))
        self.assertEqual(3, clock.next_index)
        self.assertFalse(clock.active)

    def test_abort_can_withdraw_only_an_uncommitted_trigger(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(20, 3, 0.1, 2))
        first = clock.advance(0.0)[0]

        self.assertTrue(clock.abort())

        self.assertFalse(clock.active)
        self.assertEqual((0, 0, 0), (
            clock.group_seq, clock.count, clock.next_index))
        self.assertFalse(clock.commit(first))
        self.assertFalse(clock.abort())
        self.assertTrue(clock.start(20, 3, 0.1, 2))
        self.assertTrue(clock.commit(clock.advance(0.0)[0]))
        self.assertFalse(clock.abort())
        self.assertTrue(clock.active)
        self.assertEqual((20, 3, 1), (
            clock.group_seq, clock.count, clock.next_index))
        self.assertAlmostEqual(0.1, clock.time_left)

    def test_tactical_and_controller_reasons_cannot_terminate_a_trigger(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(20, 3, 0.1, 2))
        self.assertTrue(clock.commit(clock.advance(0.0)[0]))
        for reason in ('stop', 'controller_changed', 'target_lost',
                       'target_destroyed', 'gun_unaligned',
                       'friendly_blocked', 'world_blocked',
                       'penetration_failed', 'timeout', None):
            with self.subTest(reason=reason):
                with self.assertRaises(ValueError):
                    clock.terminate(reason)
                self.assertTrue(clock.active)
                self.assertIsNone(clock.terminal_reason)
                self.assertEqual(1, clock.next_index)
                self.assertAlmostEqual(0.1, clock.time_left)
        for edge in clock.advance(0.2):
            self.assertTrue(clock.commit(edge))
        self.assertEqual(3, clock.next_index)
        self.assertFalse(clock.active)

    def test_every_physical_reason_terminates_once_without_new_commits(self):
        reasons = ('actor_destroyed', 'battle_ended', 'round_changed',
                   'gun_unavailable', 'weapon_replaced',
                   'ammunition_unavailable', 'launch_unavailable',
                   'transport_unavailable', 'native_failure')
        self.assertEqual(frozenset(reasons), burst_mechanics.TERMINAL_REASONS)
        for reason in reasons:
            with self.subTest(reason=reason):
                clock = burst_mechanics.TriggerClock()
                self.assertTrue(clock.start(20, 3, 0.1, 2))
                self.assertTrue(clock.commit(clock.advance(0.0)[0]))
                pending = clock.advance(0.2)
                self.assertTrue(clock.terminate(reason))
                self.assertFalse(clock.terminate(reason))
                self.assertEqual(reason, clock.terminal_reason)
                self.assertEqual((20, 3, 1), (
                    clock.group_seq, clock.count, clock.next_index))
                self.assertFalse(clock.active)
                self.assertEqual(0.0, clock.time_left)
                self.assertFalse(clock.commit(pending[0]))

    def test_snapshot_rejects_uncommitted_first_or_undrained_due_edges(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(20, 5, 0.1, 2))
        for unused_schedule in (False, True):
            if unused_schedule:
                clock.advance(0.0)
            with self.assertRaises(ValueError):
                clock.publish({})
        self.assertTrue(clock.commit(clock.advance(0.0)[0]))
        clock.publish({})
        due = clock.advance(0.205)
        with self.assertRaises(ValueError):
            clock.publish({})
        self.assertTrue(clock.commit(due[0]))
        with self.assertRaises(ValueError):
            clock.publish({})
        self.assertTrue(clock.commit(due[1]))
        wire = {}
        clock.publish(wire)
        self.assertEqual(3, wire['burst_next_index'])
        self.assertAlmostEqual(0.095, wire['burst_time_left'])

    def test_pending_trigger_cannot_be_replaced_by_another_request(self):
        clock = burst_mechanics.TriggerClock()
        self.assertTrue(clock.start(20, 3, 0.1, 2))
        self.assertTrue(clock.commit(clock.advance(0.0)[0]))

        self.assertFalse(clock.start(21, 2, 0.2, 0))

        self.assertEqual((20, 3, 1, 2), (
            clock.group_seq, clock.count, clock.next_index, clock.shell_index))
        self.assertAlmostEqual(0.1, clock.time_left)
        self.assertTrue(clock.active)

    def test_partial_clip_one_or_two_rounds_forms_a_complete_trigger(self):
        for remaining in (1, 2):
            with self.subTest(remaining=remaining):
                count, interval = burst_mechanics.planned_count(
                    self._gun(5), 10, remaining)
                self.assertEqual(remaining, count)
                clock = burst_mechanics.TriggerClock()
                self.assertTrue(clock.start(20, count, interval, 2))
                due = clock.advance(1.0)
                self.assertEqual(remaining, len(due))
                self.assertEqual([False] * (remaining - 1) + [True], [
                    edge['final'] for edge in due])
                for edge in due:
                    self.assertTrue(clock.commit(edge))
                self.assertFalse(clock.active)
                self.assertEqual(remaining, clock.next_index)

    def test_callback_partition_does_not_change_physical_trigger_schedule(self):
        for count, interval in ((1, 0.0), (3, 0.1), (16, 0.02),
                                (64, 0.0075), (5, 0.25)):
            for partition in ((1.5,), (0.013, 0.007, 0.28, 0.001, 1.199)):
                with self.subTest(count=count, interval=interval,
                                  partition=partition):
                    clock = burst_mechanics.TriggerClock()
                    self.assertTrue(clock.start(20, count, interval, 2))
                    elapsed = 0.0
                    actual = []
                    for dt in partition:
                        for edge in clock.advance(dt):
                            actual.append((edge['shot_seq'],
                                           elapsed + edge['due_offset']))
                            self.assertTrue(clock.commit(edge))
                        elapsed += dt
                    self.assertEqual(list(range(20, 20 + count)), [
                        value[0] for value in actual])
                    for index, (unused_seq, due_at) in enumerate(actual):
                        self.assertAlmostEqual(index * interval, due_at)
                    self.assertFalse(clock.active)
                    self.assertEqual(count, clock.next_index)

    def test_intra_and_final_rounds_use_distinct_bloom_terms(self):
        gun = self._gun()
        self.assertEqual(
            1.25, burst_mechanics.after_shot_factor(gun, False))
        self.assertEqual(
            4.0, burst_mechanics.after_shot_factor(gun, True))

    def test_multi_round_zero_interval_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            burst_mechanics.descriptor_burst(self._gun(3, 0.0))

    def test_player_gun_ledger_debits_each_round_and_reloads_after_final(self):
        descriptor = types.SimpleNamespace(
            gun=types.SimpleNamespace(
                shots=({'shell': {'compactDescr': 7}},),
                shotDispersionAngle=0.1,
                shotDispersionFactors={
                    'afterShot': 4.0, 'afterShotInBurst': 1.0,
                    'turretRotation': 0.0},
                aimingTime=1.0, reloadTime=4.0, clip=(5, 2.0),
                burst=(3, 0.1), maxAmmo=10),
            chassis={'shotDispersionFactors': (0.0, 0.0)},
            turret={'maxAmmo': 10}, maxAmmo=10,
            activeGunShotIndex=0)
        state = gun_mechanics.GunState(
            descriptor, ammo_layout={7: 10})
        state.clip = 5
        state.reload_time = 0.0
        state.reload_duration = 4.0

        self.assertTrue(state.begin_burst(3))
        self.assertTrue(state.commit_burst_round(False))
        # This ledger proves ammunition/reload accounting, not the human
        # gunRotator's native dispersion or its BigWorld presentation.
        self.assertEqual(9, state.ammo[0])
        self.assertEqual(4, state.clip)
        self.assertEqual(0.0, state.reload_time)
        self.assertFalse(state.can_fire())

        self.assertTrue(state.commit_burst_round(False))
        self.assertEqual(0.0, state.reload_time)
        self.assertTrue(state.commit_burst_round(True))
        self.assertEqual(7, state.ammo[0])
        self.assertEqual(2, state.clip)
        self.assertEqual(state.clip_reload, state.reload_time)


if __name__ == '__main__':
    unittest.main()
