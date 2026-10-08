"""Incoming contact evidence, including Bot -> stationary player admission."""
import contextlib
import copy
import importlib.util
import io
import math
import types
from pathlib import Path
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bots
import test_port_0922_battle_runtime as visible
from gui.mods.offline_lan_0922 import bot_state_codec, ram_history, ram_motion

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ram_transaction_fixtures',
    ROOT / 'tests/release097/test_096_ram_evidence6.py')
chain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chain)
SHAPE = (1.56252, 3.325788, .006011, 1.602434)
PLAYER_SHAPE = (1.7, 3.5, 0., 2.)


def motion(peer=1, seq=7, stamp=1000000, vz=-15.8):
    return [peer, seq, stamp, 0., 0., vz,
            0., 0., 6.8, round(math.pi,5), 0., 0.,
            0., 0., 0., 0., 0., 0., 0., 0., 0.]



class CaptureTests(unittest.TestCase):
    def scene(self, player_team=1, player_y=0.):
        module = bots._load()
        rt = module.BotRuntime(1)
        rt.states = {22: dict(id=22, team=2, slot=0, alive=True,
            x=0., y=0., z=4.5, yaw=math.pi, pitch=0., roll=0.,
            speed=15.8, mass=37400., collision_shape=SHAPE)}
        rt._player_collision_profile = lambda raw: dict(shape=PLAYER_SHAPE)
        player = dict(id=1, alive=True, team=player_team,
                      x=0., y=player_y, z=0., yaw=0.)
        return rt, player

    def test_real_sweep_preserves_incoming_speed_after_contact_stops_motion(self):
        rt, player = self.scene()
        with mock.patch.object(rt, '_probe_direction') as native:
            rt._guard_tank_translations([player], {22: (0., 0., 8.)}, 1000000)
            row = rt.states[22]['ram_motion'][0]
            self.assertEqual([1, 1, 1000000], row[:3])
            self.assertAlmostEqual(-15.8, row[5])
            rt.states[22]['speed'] = 0.
            pose = bots._position(rt.states[22]) if hasattr(bots, '_position') else (
                rt.states[22]['x'], rt.states[22]['y'], rt.states[22]['z'])
            rt._guard_tank_translations([player], {22: pose}, 1100000)
            self.assertEqual(row, rt.states[22]['ram_motion'][0])
            native.assert_not_called()

    def test_separation_clears_evidence_and_new_impact_has_new_sequence(self):
        rt, player = self.scene()
        rt._guard_tank_translations([player], {22: (0., 0., 8.)}, 1000000)
        player['x'] = 100.
        rt._guard_tank_translations([player], {22: (0., 0., 4.5)}, 1100000)
        self.assertEqual([], rt.states[22]['ram_motion'])
        player['x'] = 0.
        rt.states[22]['z'] = 4.5
        rt._guard_tank_translations([player], {22: (0., 0., 8.)}, 1200000)
        self.assertEqual(2, rt.states[22]['ram_motion'][0][1])

    def test_friend_and_vertically_separated_bodies_do_not_create_witness(self):
        for options in (dict(player_team=2), dict(player_y=10.)):
            rt, player = self.scene(**options)
            rt._guard_tank_translations([player], {22: (0., 0., 8.)}, 1000000)
            self.assertEqual([], rt.states[22]['ram_motion'])

    def test_death_retires_contact_evidence(self):
        rt, player = self.scene()
        rt._guard_tank_translations([player], {22: (0., 0., 8.)}, 1000000)
        rt.states[22]['alive'] = False
        rt._guard_tank_translations([player], {}, 1100000)
        self.assertEqual([], rt.states[22]['ram_motion'])


class TransportTests(unittest.TestCase):
    def test_codec_roundtrip_carries_zero_speed_with_nonzero_incoming_velocity(self):
        state = dict(id=22, speed=0., ram_motion=[motion()])
        decoded = bot_state_codec.decode_row(bot_state_codec.encode_row(state), {})
        self.assertEqual(state['ram_motion'], decoded['ram_motion'])
        self.assertEqual(0., decoded['speed'])
        empty = bot_state_codec.encode_row(dict(state, ram_motion=[]))
        self.assertEqual(21, len(bot_state_codec.encode_row(state)) - len(empty))

    def test_archive_freezes_and_does_not_adopt_future_collision(self):
        h = ram_history.RamPoseArchive()
        row = motion()
        left = dict(id=22, x=0., y=0., z=6., ram_motion=[row])
        h.remember(1, 1000000, {22: left})
        row[5] = 0.
        h.remember(2, 1200000, {22: dict(left,
            ram_motion=[motion(seq=8,stamp=1190000,vz=-20.)])})
        pinned, error = h.pin(22, 2, 1050000, [1, 1000000, 2, 1200000])
        self.assertIsNone(error)
        self.assertEqual(-15.8, pinned['ram_motion'][0][5])

    def test_duplicate_peer_nonfinite_and_unbounded_rows_are_rejected(self):
        row = motion()
        nonfinite = motion(); nonfinite[3] = float('nan')
        boolean_id = motion(); boolean_id[1] = True
        for rows in ([row, row], [nonfinite], [row]*31, [boolean_id]):
            with self.assertRaises(ValueError):
                ram_motion.normalize(rows)

    def test_server_binds_incoming_speed_to_canonical_peer_and_sequence(self):
        for change in ({}, dict(bot_vz=-50.), dict(bot_ram_motion_seq=8), dict(x=0.01)):
            s = chain.server()
            for sample in s.ram_pose_archive.samples.values():
                sample[1][30]['ram_motion'] = [motion(vz=-8.)]
            receipt = chain.receipt(vz=0., bot_vz=-8., bot_ram_motion_seq=7)
            receipt.update(change)
            value, reason = s._validate_ram_contact(s.players[1], receipt)
            self.assertEqual(not change, value is not None)
            if change:
                self.assertEqual(('canonical_ram_motion_pose_mismatch' if 'x' in change
                                  else 'canonical_ram_motion_mismatch'), reason)

    def test_bot_into_stationary_player_settles_once_through_real_server(self):
        s = chain.server()
        for sample in s.ram_pose_archive.samples.values():
            sample[1][30]['ram_motion'] = [motion(vz=-8.)]
        b, worker = chain.worker()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(chain._update_player_input(s, 1, ram_contacts=[
                chain.receipt(vz=0., bot_vz=-8., bot_ram_motion_seq=7)]))
            player = s.players[1]
            decorated = b._decorate_ram_contacts(dict(id=1, alive=True, team=1,
                ram_contacts=list(player.ram_contacts.values())))
            report = worker._resolve_human_ram_receipts([decorated], 1.)[0]
            message = dict(report, type='bot_ram_report', round_id=s.round_id,
                           authority_epoch=s.authority_epoch)
            self.assertTrue(s.report_bot_ram(chain.SIMULATION_WORKER_AUTHORITY_ID, message))
            hp = player.health
            self.assertLess(hp, 50000)
            self.assertTrue(s.report_bot_ram(chain.SIMULATION_WORKER_AUTHORITY_ID, message))
            self.assertEqual(hp, player.health)

    def test_stationary_render_history_reads_paired_incoming_sample(self):
        b = visible.BattleRuntime(visible._runtime())
        b._bots = types.SimpleNamespace(states={})
        for revision, stamp in ((1, 1000000), (2, 1200000)):
            b._remember_ram_bot_snapshot(dict(bot_state_revision=revision,
                bot_state_time_us=stamp, bots=[dict(id=22, x=0., y=0., z=6.,
                    ram_motion=[motion()])]))
        result = b._ram_bot_state_at(22, 2, 1050000, velocity_only=True)
        self.assertEqual(0., result['ram_vz'])
        self.assertEqual(-15.8, ram_motion.for_player(result['ram_motion'], 1)[5])


class VisibleAdmissionTests(unittest.TestCase):
    def scene(self, witness=True):
        b = visible.BattleRuntime(visible._runtime())
        state = dict(id=22, alive=True, team=2, x=0., y=0., z=6.,
                     yaw=math.pi, speed=0., mass=37400., collision_shape=SHAPE)
        b._bots = types.SimpleNamespace(states={22: state},
                                       replica_contact_params=lambda *a: None)
        b._server_entity = lambda engine_id: types.SimpleNamespace(
            typeDescriptor=bots._combat_descriptor())
        b._ram_profile = lambda *a, **k: dict(spall_coefficient=1., ramming_bonus=0.)
        b._estimated_motion_time_us = lambda *a: 1300000
        b.client = types.SimpleNamespace(player_id=1)
        b._records = {'bot:22': dict(ready=True, kind='bot', network_id=22,
            engine_id=1022, state=state, presented_pose=state,
            presentation_time_us=1050000, presentation_bracket=[1,1000000,2,1200000])}
        for revision, stamp in ((1,1000000),(2,1200000)):
            b._remember_ram_bot_snapshot(dict(bot_state_revision=revision,
                bot_state_time_us=stamp, bots=[dict(state, ram_motion=(
                    [motion()] if witness else []))]))
        own = dict(id=-1, alive=True, team=1, x=0., y=0., z=0., yaw=0.,
                   vx=0., vy=0., vz=0., shape=PLAYER_SHAPE,
                   ram_profile=dict(spall_coefficient=1.,ramming_bonus=0.))
        b._queue_ram_contact_proof = mock.Mock(return_value=True)
        return b, own

    def test_real_history_projection_reaches_first_impact_proof_once(self):
        b, own = self.scene()
        others = b._contact_tanks((0.,0.,0.), PLAYER_SHAPE)
        self.assertEqual(-15.8, others[0]['vz'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(b._poll_local_ram_contact_episodes(object(),own,others))
            self.assertFalse(b._poll_local_ram_contact_episodes(object(),own,others))
        self.assertEqual(1,b._queue_ram_contact_proof.call_count)
        self.assertEqual(7,b._queue_ram_contact_proof.call_args.kwargs['bot_ram_motion_seq'])
        self.assertEqual((0.,0.,-15.8),b._queue_ram_contact_proof.call_args.args[5])

    def test_recorded_contact_pose_survives_a_later_presentation_shove(self):
        b, own = self.scene()
        # The renderer has moved; the incoming witness still owns the first
        # contact and native plate proof must use its matrices.
        own['z'] = -1.
        b._records['bot:22']['presented_pose'] = dict(
            b._records['bot:22']['presented_pose'], z=8.)
        others = b._contact_tanks((0.,0.,-1.), PLAYER_SHAPE)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(b._poll_local_ram_contact_episodes(object(),own,others))
        kwargs = b._queue_ram_contact_proof.call_args.kwargs
        self.assertEqual((0.,0.,0.), kwargs['own_pose'][:3])
        self.assertEqual((0.,0.,6.8), kwargs['bot_pose'][:3])

    def test_neutral_stationary_pair_does_not_borrow_predicted_motor_speed(self):
        b, own = self.scene(witness=False)
        others = b._contact_tanks((0.,0.,0.), PLAYER_SHAPE)
        others[0]['physical_velocity'] = (0.,-15.8)
        self.assertFalse(b._poll_local_ram_contact_episodes(object(),own,others))
        b._queue_ram_contact_proof.assert_not_called()

    def test_player_driven_collision_keeps_its_existing_live_velocity(self):
        b, own = self.scene(witness=False)
        own['vz'] = 8.
        others = b._contact_tanks((0.,0.,0.), PLAYER_SHAPE)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(b._poll_local_ram_contact_episodes(object(),own,others))
        self.assertEqual((0.,0.,8.),b._queue_ram_contact_proof.call_args.args[4])
        self.assertIsNone(b._queue_ram_contact_proof.call_args.kwargs['bot_ram_motion_seq'])
