"""Water diagnostics preserve the pre-existing server death/display contract."""
import json
import unittest
from unittest import mock
import test_port_0922_server_team_size as fixture
import lan_battle_server as server


class DrowningObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.state=fixture.BattleState(team_size=1)
        fixture._attach_worker(self.state)
        self.player,error=self.state.add_player(fixture._Connection(),('10.0.0.1',1001),fixture._hello(1))
        self.assertIsNone(error)
        self.player.participating=True;self.state.phase='battle';self.state.tick=450;self.state._elect_bot_authority()
        self.state._maybe_finish_battle=mock.Mock(return_value=False)
        self.logs=[]
        patch=mock.patch.object(server,'_server_log',side_effect=self.logs.append)
        patch.start();self.addCleanup(patch.stop)
        self.sequence=0

    def observe(self,level=2,critical=None,**changes):
        self.sequence+=1
        row=dict(player_id=self.player.player_id,input_seq=0,level=level)
        if critical is not None:row['drowning_critical']=critical
        msg=dict(type='player_environment',round_id=self.state.round_id,
            authority_epoch=self.state.authority_epoch,sample_seq=self.sequence,observations=[row])
        msg.update(changes)
        return self.state.update_player_environment(-1,msg)

    def records(self):
        return [json.loads(line.split('PLAYER WATER ',1)[1]) for line in self.logs if 'PLAYER WATER ' in line]

    def test_missing_proposal_only_adds_evidence_does_not_change_old_ten_second_gate(self):
        for n in range(1,301):
            self.state.tick=450+n;self.assertTrue(self.observe());self.state._tick_player_drowning(.1)
        self.assertTrue(self.player.alive)
        self.assertEqual(self.player.max_health,self.player.health)
        self.assertEqual(10.,self.state.player_drowning_seconds[self.player.player_id])
        self.assertTrue(any(r['reason']=='missing_critical_proposal' for r in self.records()))

    def test_valid_terminal_preserves_remaining_hp_display_and_commits_only_once(self):
        self.player.health=47
        for n in range(1,101):
            self.state.tick=450+n;self.observe(critical={});self.state._tick_player_drowning(.1)
        self.assertTrue(self.player.alive)
        self.assertEqual(47,self.player.health)
        self.state.tick+=1;self.observe(critical={});self.state._tick_player_drowning(.1)
        self.assertFalse(self.player.alive)
        self.assertEqual(47,self.player.display_health)
        self.assertEqual(5,self.player.death_reason)
        events=[e for e in self.state.pending_events if e.get('death_reason')==5]
        self.assertEqual(1,len(events))
        self.state._tick_player_drowning(1.)
        self.assertEqual(1,len([e for e in self.state.pending_events if e.get('death_reason')==5]))
        self.assertTrue(any(r['reason']=='death_committed' and r['display_health']==47 for r in self.records()))

    def test_stale_pause_safe_reset_and_missing_sample_have_distinct_reasons(self):
        self.observe();self.state._tick_player_drowning(3.)
        self.state.tick+=server.PLAYER_ENVIRONMENT_STALE_TICKS+1
        self.state._tick_player_drowning(2.)
        self.assertEqual(3.,self.state.player_drowning_seconds[self.player.player_id])
        self.observe(0);self.state._tick_player_drowning(.1)
        self.assertNotIn(self.player.player_id,self.state.player_drowning_seconds)
        self.state.player_environment.clear();self.state._tick_player_drowning(.1)
        reasons={r['reason'] for r in self.records()}
        self.assertTrue({'stale_observation','fresh_safe_reset','missing_observation'}<=reasons)

    def test_malformed_proposal_remains_rejected_with_exact_reason(self):
        self.assertFalse(self.observe(critical={'devices':[{'name':'bad'}]}))
        self.assertEqual({},self.state.player_environment)
        self.assertTrue(any(r['reason']=='invalid_proposal' and r['error'] for r in self.records()))

    def test_repeated_sequence_and_terminal_noop_are_logged(self):
        self.observe();self.sequence-=1;self.assertTrue(self.observe())
        self.state.battle_result={'winner':1};self.assertTrue(self.observe())
        self.assertTrue({'stale_sequence_noop','terminal_noop'}<={r['reason'] for r in self.records()})

    def test_invalid_round_and_empty_batch_and_overtaken_row_explain_admission(self):
        self.assertFalse(self.observe(round_id=self.state.round_id+1))
        self.assertTrue(self.observe(observations=[]))
        self.player.alive=False;self.assertTrue(self.observe())
        self.assertTrue({'round_or_epoch_mismatch','empty_batch','overtaken_or_inactive'}<={r['reason'] for r in self.records()})

    def test_diagnostic_exception_cannot_change_original_terminal_behavior(self):
        self.observe(critical={});self.state.player_drowning_seconds[self.player.player_id]=10.
        with mock.patch.object(server,'_server_log',side_effect=RuntimeError('sink unavailable')):
            self.assertEqual(1,self.state._tick_player_drowning(.1))
        self.assertFalse(self.player.alive)


if __name__=='__main__':unittest.main()
