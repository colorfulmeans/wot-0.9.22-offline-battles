"""Sequence regressions for canonical-result ammunition decisions."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ammo_policy import ShotPolicy, allocation, ordered, stages, apportion
from gui.mods.offline_lan_0922.default_loadouts import shell_roles, VEHICLE_GUNS, GUN_AMMUNITION


def profile(kinds=('ARMOR_PIERCING', 'ARMOR_PIERCING_CR', 'HIGH_EXPLOSIVE'), clip=1, arty=False):
    result = dict(class_tag='SPG' if arty else 'mediumTank', clip_size=clip,
                shells=[dict(index=i, kind=kind, name='', penetration=100+i*20)
                        for i, kind in enumerate(kinds)])
    if kinds[0] == 'HIGH_EXPLOSIVE' and not arty and len(kinds) == 2:
        result.update(vehicle_name='ussr:test', gun_name='_122mm_cannon_U-11')
        for shell, name in zip(result['shells'], GUN_AMMUNITION['ussr:_122mm_cannon_U-11']):
            shell['name'] = name
    return result


class AmmoPolicyTests(unittest.TestCase):
    def setup_policy(self, p=None):
        self.policy = ShotPolicy(p or profile())
        self.state = dict(shell_index=0, clip=(p or {}).get('clip_size', 1),
                          ammo_remaining=[100]*len(self.policy.shells), ammo_reload_pending=False)
        self.sequence = 0
        self.policy.choose(self.state)
        return self.policy

    def shot(self, hit=True, damage=0, pen=False, shell=0, group=None, count=1, resolve=True):
        self.sequence += 1
        seq = self.sequence
        self.policy.launch(seq, shell, group or seq, count, dict(x=0, z=0), ('bot', 9))
        if resolve:
            self.policy.resolve(seq, hit, damage, pen)
        return seq

    def test_two_zero_hp_hits_ignore_miss_and_latch_upgrade(self):
        p = self.setup_policy()
        self.shot(); self.shot(hit=False); self.shot()
        self.assertEqual(1, p.desired)
        self.shot(damage=100, pen=True)
        self.assertEqual(1, p.desired)

    def test_positive_damage_resets_zero_hp_streak(self):
        p = self.setup_policy()
        self.shot(); self.shot(damage=1); self.shot()
        self.assertEqual(0, p.desired)

    def test_movement_uses_displacement_not_travel_or_rotation(self):
        p = self.setup_policy(); self.shot()
        for point in ((1, 0), (0, 1), (-1, 0), (0, -1), (0, 0), (3, 0)):
            p.context(dict(x=point[0], z=point[1]), ('bot', 9))
        self.assertEqual(1, next(iter(p.failures.values())))
        p.context(dict(x=3.01, z=0), ('bot', 9))
        self.assertFalse(p.failures)
        self.assertEqual((3.01, 0), p.anchor)

    def test_old_target_and_position_results_do_not_pollute(self):
        p = self.setup_policy()
        a = self.shot(resolve=False); b = self.shot(resolve=False)
        p.context(dict(x=4, z=0), ('bot', 10))
        p.resolve(a, True, 0, False); p.resolve(b, True, 0, False)
        self.assertEqual(0, p.desired)

    def test_change_target_keeps_latched_upgrade(self):
        p = self.setup_policy(); self.shot(); self.shot()
        p.context(dict(x=4, z=0), ('bot', 10))
        self.assertEqual(1, p.desired)
        self.assertFalse(p.failures)

    def test_out_of_order_result_waits_for_prior_launch(self):
        p = self.setup_policy()
        a = self.shot(resolve=False); b = self.shot(resolve=False)
        p.resolve(b, True, 0, False)
        self.assertEqual(0, p.desired)
        p.resolve(a, True, 0, False)
        self.assertEqual(1, p.desired)
        p.resolve(a, True, 0, False)
        self.assertEqual(1, p.desired)

    def test_default_he_counts_nonpenetrating_direct_damage(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE')))
        self.shot(damage=20); self.shot(hit=False, damage=40); self.shot(damage=10)
        self.assertEqual(1, p.desired)

    def test_default_he_penetration_resets_and_splash_is_ignored(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE')))
        self.shot(); self.shot(damage=10, pen=True); self.shot(hit=False); self.shot()
        self.assertEqual(0, p.desired)

    def test_he_default_backup_prequeues_return_before_its_only_shot(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE')))
        self.shot(); self.shot()
        self.state['shell_index'] = 1
        self.assertEqual(0, p.choose(self.state))
        self.shot(shell=1, hit=False)
        self.state['shell_index'] = 0
        self.assertEqual(0, p.choose(self.state))

    def test_ordinary_he_phase_returns_after_two_physical_shots(self):
        p = self.setup_policy()
        self.shot(); self.shot()
        self.state['shell_index'] = 1; p.choose(self.state)
        self.shot(shell=1); self.shot(shell=1)
        self.assertEqual(2, p.desired)
        self.state['shell_index'] = 2
        self.assertEqual(2, p.choose(self.state))
        self.shot(shell=2, hit=False)
        self.assertEqual(0, p.choose(self.state))  # Locked for reload after shot two.
        self.shot(shell=2, hit=False)
        self.state['shell_index'] = 0
        self.assertEqual(0, p.choose(self.state))

    def test_artillery_misses_count_direct_zero_hp_hit_resets(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE',)*2, arty=True))
        self.shot(hit=False); self.shot(hit=True); self.shot(hit=False)
        self.assertEqual(0, p.desired)
        self.shot(hit=False)
        self.assertEqual(1, p.desired)

    def test_artillery_splash_damage_resets_miss_streak(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE',)*2, arty=True))
        self.shot(hit=False); self.shot(hit=False, damage=1); self.shot(hit=False)
        self.assertEqual(0, p.desired)

    def test_untriggered_failure_does_not_cross_magazines(self):
        p = self.setup_policy(profile(clip=3))
        self.shot(); self.shot(damage=1); self.shot()
        self.shot()
        self.assertEqual(0, p.desired)

    def test_burst_waits_for_all_pellets_and_one_failed_trigger_upgrades(self):
        p = self.setup_policy(profile(clip=2))
        self.shot(group=1, count=2)
        self.assertEqual(0, p.desired)
        self.shot(group=1, count=2, hit=False)
        self.assertEqual(1, p.desired)

    def test_burst_any_damage_prevents_upgrade_and_all_misses_ignored(self):
        p = self.setup_policy(profile(clip=4))
        self.shot(group=1, count=2); self.shot(group=1, count=2, damage=1)
        self.shot(group=3, count=2, hit=False); self.shot(group=3, count=2, hit=False)
        self.assertEqual(0, p.desired)

    def test_magazine_backup_without_upgrade_returns_at_last_round(self):
        p = self.setup_policy(profile(clip=4))
        self.shot(); self.shot()
        self.state.update(shell_index=1, clip=4)
        self.assertEqual(1, p.choose(self.state))
        self.shot(shell=1, damage=100)
        self.state['clip'] = 1
        p.used = 3
        self.assertEqual(0, p.choose(self.state))

    def test_magazine_backup_failure_overrides_automatic_return(self):
        p = self.setup_policy(profile(clip=4))
        self.shot(); self.shot()
        self.state.update(shell_index=1, clip=4); p.choose(self.state)
        self.shot(shell=1); self.shot(shell=1)
        self.state['clip'] = 1
        self.assertEqual(2, p.choose(self.state))

    def test_batchat_artillery_backup_returns_only_at_magazine_end(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE',)*2, clip=3, arty=True))
        self.shot(hit=False); self.shot(hit=False)
        self.state.update(shell_index=1, clip=3)
        self.assertEqual(1, p.choose(self.state))
        self.state['clip'] = 1
        p.used = 2
        self.assertEqual(0, p.choose(self.state))

    def test_exhausted_backup_skipped_and_single_or_empty_inventory(self):
        p = self.setup_policy()
        self.state['ammo_remaining'] = [2, 0, 2]; p.choose(self.state)
        self.shot(); self.shot()
        self.assertEqual(2, p.desired)
        self.state['ammo_remaining'] = [0, 0, 2]
        self.assertEqual(2, p.choose(self.state))
        self.state['ammo_remaining'] = [0, 0, 0]
        p.choose(self.state)  # Finite native inventory blocks firing.

    def test_unknown_outcome_is_not_a_miss(self):
        p = self.setup_policy(profile(('HIGH_EXPLOSIVE',)*2, arty=True))
        a = self.shot(hit=False); b = self.shot(resolve=False)
        p.resolve(b, False, 0, False, known=False)
        self.shot(hit=False)
        self.assertEqual(0, p.desired)

    def test_whole_magazine_ratios(self):
        self.assertEqual([20, 12, 4], allocation(profile(clip=4), 36, 3))
        self.assertEqual([15, 10, 5], allocation(profile(clip=5), 30, 3))
        self.assertEqual([27, 9], allocation(profile(('HIGH_EXPLOSIVE',)*2, clip=3, arty=True), 36, 2))
        self.assertEqual([32, 24], allocation(profile(('ARMOR_PIERCING', 'ARMOR_PIERCING_CR'), clip=8), 56, 2))

    def test_apportion_fills_and_keeps_each_available_choice(self):
        for total in range(3, 150):
            counts = apportion(total, (60, 30, 10))
            self.assertEqual(total, sum(counts))
            self.assertTrue(all(c > 0 for c in counts))

    def test_gun_rule_is_independent_of_vehicle_fitting(self):
        names = ('_75mm_APCBC', '_Gr_38_HL_A', '_75mm_Sprg.18')
        self.assertNotIn('germany:G80_Pz_IV_AusfD', VEHICLE_GUNS)
        self.assertEqual({2: 'standard', 1: 'premium'}, shell_roles(
            'germany:G80_Pz_IV_AusfD', '_75mm_KwK_37_L24', names))

    def test_native_price_catalogue_sorts_silver_he_before_gold_nonhe(self):
        p = dict(vehicle_name='germany:any', gun_name='any', shells=[
            dict(index=0, name='_Gr_38_HL_A', kind='HOLLOW_CHARGE'),
            dict(index=1, name='silver_he', kind='HIGH_EXPLOSIVE')])
        self.assertEqual([1, 0], [s['index'] for s in ordered(p)])

    def test_burst_return_prequeues_at_last_trigger_not_last_pellet(self):
        config = profile(clip=12)
        config['burst_size'] = 3
        p = self.setup_policy(config)
        self.shot(); self.shot()
        self.state.update(shell_index=1, clip=3)
        p.choose(self.state)
        p.used = 9
        self.assertEqual(0, p.choose(self.state))

    def test_ammunition_capacity_above_one_thousand_is_not_truncated(self):
        from test_port_0922_bot_ammo import _load_bot_runtime, _descriptor
        runtime = _load_bot_runtime()
        config = profile(('HIGH_EXPLOSIVE',), clip=50)
        self.assertEqual([1350], allocation(config, 1350, 1))
        self.assertEqual(1350, runtime._bot_ammo_capacity(_descriptor(1350)))

    def test_cancelled_trigger_counts_only_projectiles_that_launched(self):
        p = self.setup_policy(profile(clip=12))
        self.shot(group=1, count=3)
        self.assertEqual(0, p.desired)
        self.state.update(burst_active=False, burst_group_seq=1, burst_next_index=1)
        self.assertEqual(1, p.choose(self.state))

    def test_single_trigger_magazine_prequeues_backup_return_during_reload(self):
        config = profile(clip=2)
        config['burst_size'] = 2
        p = self.setup_policy(config)
        self.shot(group=1, count=2); self.shot(group=1, count=2)
        self.assertEqual(1, p.desired)
        self.state.update(ammo_reload_pending=True, next_shell_index=1, clip=0)
        self.assertEqual(0, p.choose(self.state))
        self.assertEqual(1, p.desired)  # The incoming backup magazine stays locked.

    def test_late_choice_never_replaces_locked_or_loaded_round(self):
        from test_port_0922_bot_ammo import _load_bot_runtime, _descriptor, _profile
        runtime = _load_bot_runtime()
        ammo = runtime._BotAmmoState(_descriptor(), _profile())
        ammo.stage(1, True)
        ammo.stage(2, True)  # Editable while waiting to fire.
        self.assertEqual((0, 2), (ammo.loaded, ammo.next))
        self.assertTrue(ammo.consume_loaded())
        ammo.stage(1, False)  # The next round is already reloading.
        self.assertEqual((0, 2), (ammo.loaded, ammo.next))
        ammo.stage(1, True)
        self.assertEqual((2, 1), (ammo.loaded, ammo.next))

    def _fire_without_observing_a_ready_frame(self, config, rounds):
        import types
        from test_port_0922_bot_ammo import _load_bot_runtime
        runtime = _load_bot_runtime()
        descriptor = types.SimpleNamespace(gun=types.SimpleNamespace(
            shots=[{} for s in config['shells']], maxAmmo=60, clip=(1,)))
        ammo = runtime._BotAmmoState(descriptor, config)
        policy = ShotPolicy(config)
        state = {}
        ammo.publish(state)
        fired = []
        for sequence in range(1, rounds + 1):
            command = policy.choose(state)
            ammo.stage(command, True)
            shell = ammo.loaded
            self.assertTrue(ammo.consume_loaded())
            ammo.publish(state)  # Every published frame is already reloading.
            policy.launch(sequence, shell, sequence, 1, dict(x=0, z=0), ('bot', 9))
            policy.resolve(sequence, True, 0, False)
            fired.append(shell)
        return fired

    def test_he_probe_returns_after_one_shot_without_a_ready_snapshot(self):
        fired = self._fire_without_observing_a_ready_frame(
            profile(('HIGH_EXPLOSIVE', 'HOLLOW_CHARGE')), 7)
        self.assertEqual([0, 0, 0, 1, 0, 0, 0], fired)

    def test_ordinary_he_returns_after_two_shots_without_a_ready_snapshot(self):
        fired = self._fire_without_observing_a_ready_frame(profile(), 10)
        self.assertEqual([0, 0, 0, 1, 1, 1, 2, 2, 0, 0], fired)

    def test_empty_primary_keeps_backup_nonhe_before_he(self):
        config = profile(('ARMOR_PIERCING', 'HOLLOW_CHARGE', 'HIGH_EXPLOSIVE'))
        config['vehicle_name'] = 'germany:test'
        config['shells'][1]['name'] = '_Gr_38_HL_A'
        self.assertEqual([0, 2, 1], [s['index'] for s in ordered(config)])
        self.assertEqual([1, 2], [s['index'] for s in stages(config, [0, 10, 10])])

    def test_empty_he_primary_leaves_a_closed_nonhe_cycle(self):
        from unittest import mock
        config = profile(('HIGH_EXPLOSIVE', 'ARMOR_PIERCING', 'ARMOR_PIERCING_CR'))
        config.update(vehicle_name='ussr:test', gun_name='test_he_three_types')
        for shell, name in zip(config['shells'], ('he', 'low', 'high')):
            shell['name'] = name
        with mock.patch.dict(GUN_AMMUNITION, {'ussr:test_he_three_types': ('he', 'low', 'high')}):
            p = self.setup_policy(config)
            self.state.update(ammo_remaining=[0, 10, 10], shell_index=1)
            self.assertEqual(1, p.choose(self.state))
            self.shot(shell=1); self.shot(shell=1)
            self.assertEqual(2, p.desired)


class CanonicalAmmoResultTests(unittest.TestCase):
    def test_two_admitted_zero_hp_hits_drive_the_actual_room_order(self):
        import test_port_0922_server_projectiles as ledger
        room = ledger._state()
        ledger.ServerProjectileLedgerTests._armed_bot(room)
        config = profile()
        room.bot_manifest = [dict(id=16, profile=config)]
        room.bot_states[16].update(x=0., z=0., shell_index=0,
                                  ammo_remaining=[10, 10, 10], clip=1,
                                  ammo_reload_pending=False)
        room.bot_orders = dict(orders=[dict(id=16, target_kind='player', target_id=1)])
        for seq in (1, 2):
            room.bot_pending_projectile_launches.add((16, seq))
            launch = ledger._launch(shooter_id=16, shooter_kind='bot', shot_seq=seq)
            self.assertTrue(room.launch_projectile(ledger.SIMULATION_WORKER_AUTHORITY_ID, launch))
            identity = '1:b:16:%d' % seq
            message = ledger._resolve(room, identity, direct=ledger._effect(
                target_id=1, damage=0, shot_result=0, x=0.))
            self.assertTrue(room.resolve_projectile(ledger.SIMULATION_WORKER_AUTHORITY_ID, message))
            self.assertEqual(0 if seq == 1 else 1, room.bot_orders['orders'][0]['shell_index'])
            self.assertTrue(room.resolve_projectile(ledger.SIMULATION_WORKER_AUTHORITY_ID, message))
        self.assertEqual(1000, room.players[1].health)
        self.assertEqual(1, room.bot_ammo_policies[16].desired)


if __name__ == '__main__':
    unittest.main()
