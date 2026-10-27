"""Recorded allied-hull sweep refusal must reach bounded gun-angle recovery."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest import mock

import test_port_0922_bot_runtime as harness


class TrafficPivotHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.runtime = self.fixture.module.BotRuntime(1)
        self.scene = json.loads((Path(__file__).parent / 'fixtures' /
            'jagdpanther2_144050_pivot.json').read_text())
        self.body = self.scene['body']
        self.command = dict(self.scene['command'], throttle_override=0.,
            move_position=self.body['position'])
        self.target = self.scene['target']
        self.command.update(aim_position=self.target['position'],
            face_position=self.target['position'], fire_allowed=True)
        x,y,z = self.body['position']
        self.state = dict(id=27, team=2, x=x,y=y,z=z, yaw=self.body['yaw'],
            speed=0., profile={'class_tag':'AT-SPG'}, collision_shape=self.body['shape'])
        self.runtime._gun_yaw_limits[27] = (-math.radians(10),math.radians(10),True)

    def guard(self, now=10., peers=None, command=None):
        from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator
        return TrafficCoordinator().safe_controls(self.body,
            command or self.command, self.scene['peers'] if peers is None else peers,
            now, lambda:0., self.scene['step'])

    def handoff(self, safety, now=10., target=None, aiming=True, command=None):
        self.runtime._record_traffic_pivot(self.state,command or self.command,
            safety,self.target if target is None else target,aiming,now)

    def test_recorded_guard_retains_real_collision_and_names_complete_pose_evidence(self):
        safe = self.guard()
        self.assertEqual(0.,safe['turn'])
        receipt = safe['rotation_safety']
        self.assertTrue(receipt['blocked'])
        self.assertGreater(receipt['fraction'],.3)
        self.assertLess(receipt['fraction'],.4)
        self.assertEqual([22,24],[p['id'] for p in receipt['peers']])
        self.assertEqual(tuple(self.body['shape']),receipt['shape'])
        from gui.mods.offline_lan_0922 import tank_collision
        calls=[]
        actual=tank_collision.rotation_fraction
        def counted(*args):
            calls.append(args)
            return actual(*args)
        with mock.patch.object(tank_collision,'rotation_fraction',side_effect=counted):
            self.guard()
        self.assertEqual(1,len(calls))  # evidence never repeats the native query

    def test_refused_aim_hands_off_to_existing_checked_relocation_and_bounded_exit(self):
        safe=self.guard()
        self.runtime._decision_cache[27]=('old',)
        self.handoff(safe)
        self.assertNotIn(27,self.runtime._decision_cache)
        self.assertEqual(('bot',9),self.state['_gun_angle_pivot_refusal'])
        self.runtime._decision_cache[27]=('same-owner',)
        self.handoff(safe,10.05)
        self.assertEqual(('same-owner',),self.runtime._decision_cache.pop(27))
        targets={9:self.target}
        order=self.runtime._gun_angle_order(self.state,self.command,targets,10.,lambda *a:True)
        self.assertIn('_gun_angle_adjustment',self.state)
        with mock.patch.object(self.runtime,'_gun_angle_target_fraction',return_value=1.):
            moved=self.runtime._gun_angle_order(self.state,self.command,targets,12.1,lambda *a:True)
        self.assertEqual('gun_angle_adjust',moved['combat_mode'])
        self.assertEqual(9,moved['target_id'])
        self.assertNotEqual(self.body['position'],moved['move_position'])
        self.runtime._gun_angle_order(self.state,self.command,targets,12.2,lambda *a:True)
        self.assertEqual('advance_contact',self.runtime._gun_angle_order(
            self.state,self.command,targets,19.,lambda *a:True)['combat_mode'])
        self.assertNotIn('_gun_angle_adjustment',self.state)
        self.assertEqual('relocation_stalled',self.state['_gun_angle_last_terminal']['reason'])

    def test_clear_guard_releases_only_an_unconsumed_handoff(self):
        self.handoff(self.guard())
        safe=self.guard(10.1,peers=[])
        self.assertNotIn('rotation_safety',safe)
        self.handoff(safe,10.1)
        self.assertNotIn('_gun_angle_pivot_refusal',self.state)
        self.assertEqual('unconsumed_handoff_released',self.state['_traffic_rotation_receipt']['owner'])
        self.handoff(self.guard(11.),11.)
        self.runtime._gun_angle_order(self.state,self.command,{9:self.target},11.,lambda *a:True)
        self.handoff(safe,11.1)
        self.assertEqual(('bot',9),self.state['_gun_angle_pivot_refusal'])

    def test_target_loss_and_priority_handoff_retire_the_existing_action(self):
        for priority in ('base_defense','artillery_deploy'):
            self.handoff(self.guard())
            self.runtime._gun_angle_order(self.state,self.command,{9:self.target},10.,lambda *a:True)
            self.runtime._gun_angle_order(self.state,dict(self.command,combat_mode=priority),
                {9:self.target},10.1,lambda *a:True)
            self.assertNotIn('_gun_angle_adjustment',self.state)
            self.assertNotIn('_gun_angle_pivot_refusal',self.state)
        self.handoff(self.guard())
        self.runtime._gun_angle_order(self.state,self.command,{},10.,lambda *a:True)
        self.assertNotIn('_gun_angle_pivot_refusal',self.state)

    def test_ordinary_steering_and_priority_movement_do_not_create_mechanical_refusal(self):
        for mode,aiming in (('route',False),('base_defense',True),('artillery_deploy',True)):
            self.state.pop('_gun_angle_pivot_refusal',None)
            self.handoff(self.guard(),command=dict(self.command,combat_mode=mode),aiming=aiming)
            self.assertNotIn('_gun_angle_pivot_refusal',self.state)
        self.state['profile']['class_tag']='SPG'
        self.handoff(self.guard())
        self.assertNotIn('_gun_angle_pivot_refusal',self.state)

    def test_native_sweep_rejection_reason_survives_the_complete_decision_receipt(self):
        receipt=dict(id=(1,4,1,10.),sampled_at=10.,query_count=0,
            reason_counts={},queries=[],dropped_queries=0)
        row=self.runtime._record_planning_verdict(receipt,dict(kind='local_sweep',
            clear=False,native_sweep=dict(reason='local_sweep_blocked',
                hit=(163.266,-13.091,-8.340),sampled_at=9.9)))
        self.assertEqual('local_sweep_blocked',row['reason'])
        self.assertEqual(9.9,row['native_sweep']['sampled_at'])
        self.assertEqual({'local_sweep_blocked':1},receipt['reason_counts'])


if __name__=='__main__':
    unittest.main()
