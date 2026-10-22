"""Delayed-result and magazine-boundary regressions for fast custom guns."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'server'))
from lan_battle_server import BattleState
from test_bot_shot_ammo_policy import profile
from test_port_0922_bot_ammo import _load_bot_runtime, _descriptor
from gui.mods.offline_lan_0922.ammo_policy import ShotPolicy
from gui.mods.offline_lan_0922 import bot_state_codec


class LateAmmoTests(unittest.TestCase):
    def simulate(self, clip, delay):
        runtime = _load_bot_runtime()
        from effective_params_fixture import bot_default_crew_factors
        original_factors = runtime.loadout.attribute_factors
        runtime.loadout.attribute_factors = bot_default_crew_factors
        self.addCleanup(setattr, runtime.loadout, 'attribute_factors', original_factors)
        descriptor = _descriptor(1800, clip=(clip, .1))
        descriptor.gun.reloadTime = .1
        config = profile(clip=clip)
        ammo = runtime._BotAmmoState(descriptor, config)
        gun = runtime._BotGunState(descriptor)
        policy = ShotPolicy(config)
        queue, launches, transitions = [], [], []
        seq = 0
        state = {}
        def snapshot():
            ammo.publish(state)
            state.update(fire_seq=seq, clip=gun.clip, clip_size=clip,
                         ammo_magazine_started=gun.reload_kind == 'intra',
                         reload_time=gun.remaining(), reload_duration=gun.duration())
            return dict(state, ammo_remaining=list(ammo.remaining))
        previous = snapshot()
        total = sum(ammo.remaining)
        for frame in range(300):
            for due, shot in list(queue):
                if due <= frame:
                    policy.resolve(shot, True, 0, False)
                    queue.remove((due, shot))
            selected = policy.choose(state)
            gun.tick(.1001)
            ammo.stage(selected, False)
            boundary = gun.complete_reload(1., ammo.planned_rounds())
            ammo.stage(selected, boundary is not None, boundary == 'full')
            if boundary == 'full':
                gun.clip = min(clip, ammo.planned_rounds())
            ready = snapshot()
            self.assertTrue(BattleState._validate_bot_ammo_transition(previous, ready))
            if gun.ready() and ammo.can_fire():
                loaded = ammo.loaded
                self.assertTrue(gun.fire())
                self.assertTrue(ammo.consume_loaded())
                seq += 1
                if not launches or loaded != launches[-1]:
                    transitions.append((seq, loaded))
                launches.append(loaded)
                policy.launch(seq, loaded, seq, 1, dict(x=0, z=0), ('bot', 9))
                queue.append((frame+delay, seq))
                fired = snapshot()
                self.assertTrue(BattleState._validate_bot_ammo_transition(ready, fired))
                self.assertEqual(total-seq, sum(ammo.remaining))
                previous = fired
            else:
                previous = ready
        self.assertGreater(seq, 200)
        self.assertTrue(any(shell == 1 for shell in launches))
        if clip == 1:
            self.assertTrue(any(shell == 2 for shell in launches))
            self.assertEqual([0, 1, 2, 0], [shell for seq, shell in transitions[:4]])
        else:
            # The backup magazine has already finished before its results
            # arrive: old results must not upgrade the returned main phase.
            self.assertEqual([0, 1, 0], [shell for seq, shell in transitions[:3]])
        if clip > 1:
            for shot, shell in transitions[1:]:
                self.assertEqual(0, (shot-1) % clip)
        return transitions

    def test_ten_shots_per_second_with_twenty_in_flight(self):
        transitions = self.simulate(1, 20)
        self.assertEqual((22, 1), transitions[1])

    def test_tenth_second_reload_magazines_with_many_old_results(self):
        self.simulate(3, 20)

    def test_out_of_order_old_results_cannot_upgrade_new_stage(self):
        p = ShotPolicy(profile())
        state = dict(shell_index=0, ammo_remaining=[100,100,100])
        p.choose(state)
        for seq in range(1, 21):
            p.launch(seq, 0, seq, 1, dict(x=0,z=0), ('bot',9))
        p.resolve(2, True, 0, False)
        self.assertEqual(0, p.desired)
        p.resolve(1, True, 0, False)
        self.assertEqual(1, p.desired)
        p.launch(21, 1, 21, 1, dict(x=0,z=0), ('bot',9))
        for seq in reversed(range(3,21)):
            p.resolve(seq, True, 0, False)
        self.assertEqual(1, p.desired)
        self.assertFalse(p.failures)
        p.resolve(21, True, 0, False)
        self.assertEqual(1, p.desired)
        p.launch(22, 1, 22, 1, dict(x=0,z=0), ('bot',9))
        p.resolve(22, True, 0, False)
        self.assertEqual(2, p.desired)

    def test_partial_magazine_with_equal_inventory_is_not_fresh(self):
        before = dict(shell_index=0, next_shell_index=0, ammo_remaining=[2,20,3],
                      fire_seq=1, clip=2, clip_size=3, ammo_reload_pending=False,
                      ammo_magazine_started=True, reload_time=0.)
        with self.assertRaisesRegex(ValueError, 'inside magazine'):
            BattleState._validate_bot_ammo_transition(before, dict(before, shell_index=1))
        self.assertTrue(BattleState._validate_bot_ammo_transition(before, dict(before, next_shell_index=1)))

    def test_started_magazine_flag_survives_wire_codec(self):
        from test_port_0922_bot_state_codec import _bot_state, STATIC
        for started in (True, False):
            state = _bot_state(ammo_magazine_started=started)
            row = bot_state_codec.encode_row(state)
            restored = bot_state_codec.decode_row(row, STATIC)
            self.assertEqual(started, restored['ammo_magazine_started'])

    def test_unknown_result_closes_gap_without_inventing_a_failure(self):
        p = ShotPolicy(profile())
        p.choose(dict(ammo_remaining=[100,100,100]))
        for seq in range(1,4):
            p.launch(seq, 0, seq, 1, dict(x=0,z=0), ('bot',9))
        p.resolve(1, True, 0, False)
        p.resolve(3, True, 0, False)
        self.assertEqual(0, p.desired)
        p.resolve(2, False, 0, False, known=False)
        self.assertEqual(0, p.desired)
        self.assertFalse(p.pending)

if __name__ == '__main__':
    unittest.main()
