"""Build-540 observations: movement ownership and bounded diagnostic coverage."""
import copy
import os
import unittest
from types import SimpleNamespace
from unittest import mock
from test_port_0922_bot_ammo import _load_bot_runtime


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_bot_runtime()

    def test_empty_live_target_tracks_gun_without_replacing_travel_or_recovery(self):
        target = dict(alive=True, visible=True, position=(90.,3.,-50.))
        for mode in ('spg_route_travel','base_capture','route','advance_contact'):
            for moving_goal in ((0.,0.,200.), (0.,0.,-100.)):
                command = dict(empty_ammo=True, combat_mode=mode, target_id=9,
                    aim_position=(1.,0.,1.), face_position=moving_goal,
                    move_position=moving_goal, throttle=.7, turn=-.1, fire_allowed=False)
                before = copy.deepcopy(command)
                result = self.module._overlay_live_target_pose(command,target)
                self.assertEqual(target['position'],result.pop('aim_position'))
                before.pop('aim_position')
                self.assertEqual(before,result)
                self.assertEqual((1.,0.,1.),command['aim_position'])
        # Stocked/reloading combat keeps the existing live approach and facing.
        result=self.module._overlay_live_target_pose(dict(command,empty_ammo=False,
            combat_mode='advance_contact'),target)
        self.assertEqual(target['position'],result['move_position'])
        self.assertEqual(target['position'],result['face_position'])

    def test_disabled_order_diagnostic_does_not_read_or_copy_tactical_values(self):
        class Unreadable(dict):
            def get(self,*args):raise AssertionError('unused diagnostic allocation')
        with mock.patch.object(self.module,'detailed_enabled',return_value=False):
            self.assertEqual({},self.module._order_evidence(Unreadable()))

    def test_spg_control_history_survives_bulk_quota_and_preserves_actual_outputs(self):
        from gui.mods.offline_lan_0922 import artillery_diagnostics as d
        state=dict(id=23,profile=dict(class_tag='SPG'),yaw=.1,ammo_remaining=[0,0],
                   _authored_spg_travel=dict(kind='attack',index=3,recovery_phase='forward'))
        command=dict(empty_ammo=True,combat_mode='spg_route_travel',move_position=(0,0,100),
                     aim_position=(50,0,0),face_position=(0,0,100),target_id=1,
                     movement_intent=True,throttle=.8,turn=.2)
        rows=[]
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='1'), \
             mock.patch.object(d.diagnostics,'detail_record_ready',return_value=False), \
             mock.patch.object(d.diagnostics,'write_json_record',side_effect=lambda k,v:rows.append((k,v))):
            for n in range(17):
                d.observe(SimpleNamespace(round_id=1),state,command,.4,(-1)**n*.1,True,None,n*.25)
        self.assertEqual(3,len(rows))
        self.assertEqual('SPG CONTROL',rows[-1][0])
        self.assertLessEqual(len(rows[-1][1]['controls']),8)
        self.assertEqual([.8,.2],rows[-1][1]['driver'])
        self.assertEqual(.4,rows[-1][1]['controls'][-1][5])
        self.assertEqual([0,0],rows[-1][1]['stock'])
        self.assertEqual(3,rows[-1][1]['task']['index'])
        self.assertEqual(16,rows[-1][1]['turn_flips'])
        self.assertEqual((0,0,100),command['move_position'])
        self.assertNotIn('_spg_control_observation',self.module._copy_runtime_state(state))
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='1'), \
             mock.patch.object(d.diagnostics,'write_json_record',side_effect=RuntimeError('log unavailable')):
            d.observe(SimpleNamespace(round_id=1),state,command,0,0,True,None,8.)
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='0'), \
             mock.patch.object(d.diagnostics,'write_json_record',side_effect=AssertionError('ordinary entry')):
            d.observe(None,state,command,0,0,True,None,10.)

    def test_turn_flips_between_samples_are_counted_without_extra_output(self):
        from gui.mods.offline_lan_0922 import artillery_diagnostics as d
        state=dict(id=23,profile=dict(class_tag='SPG'))
        rows=[]
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='1'), \
             mock.patch.object(d.diagnostics,'write_json_record',side_effect=lambda k,v:rows.append(v)):
            for n in range(22):
                d.observe(SimpleNamespace(round_id=1),state,{},0,(-1)**n*.1,True,None,n*.1)
        self.assertEqual(2,len(rows))
        self.assertEqual(21,rows[-1]['turn_flips'])

    def test_team_killer_receipts_are_diagnostic_only_and_do_not_throw(self):
        from gui.mods.offline_lan_0922 import native_input_diagnostics as d
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='0'), \
             mock.patch.object(d,'write_json_record') as write:
            d.team_killer_receipt('event_received',actor_id=25)
            write.assert_not_called()
        with mock.patch.dict(os.environ,WOT_OFFLINE_DIAGNOSTICS='1'), \
             mock.patch.object(d,'write_json_record',side_effect=RuntimeError('log unavailable')):
            d.team_killer_receipt('native_arena_updated',engine_id=100)


if __name__=='__main__':unittest.main()
