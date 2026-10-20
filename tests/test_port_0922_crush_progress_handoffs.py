"""Crush preview transactions and bounded local-action progress handoffs."""
import copy
import math
import types
import unittest
from unittest import mock
import test_port_0922_local_action_sweep as sweep_tests
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922 import battle_runtime as battle_module


class CrushPreviewTests(unittest.TestCase):
    scene = sweep_tests.LocalActionSweepTests.scene

    def setup_motion(self, detail, world='clear'):
        battle, state, descriptor = self.scene()
        state.update(yaw=0., pitch=0., roll=0.)
        battle._avatar = types.SimpleNamespace(spaceID=1)
        battle._destructibles = types.SimpleNamespace(
            _catalog_motion_proposal=mock.Mock(return_value=detail),
            _catalog_motion_blocked=mock.Mock(return_value=dict(status='crushed',
                token=((33405,77,None),),accepted_now=True,used_kinetic_speed=False)))
        battle._tree_motion_proposal = mock.Mock(return_value=dict(status='clear',requires_commit=False))
        battle._complete_bot_tree_contact = mock.Mock(side_effect=lambda *args:args[-1])
        battle._turret_motion_is_clear = mock.Mock(return_value=True)
        battle._destructible_drive_speed_cap = mock.Mock(return_value=None)
        battle._bot_destructible_travel_descriptor = mock.Mock(return_value=None)
        return battle,state,descriptor

    def test_falling_pole_preview_admits_transaction_without_destroying_then_real_commit_rechecks(self):
        for sign in (-1.,1.):
            with self.subTest(sign=sign):
                detail=dict(status='crushed',token=((33405,77,None),),requires_commit=True,
                    accepted_now=False,used_kinetic_speed=True,kinds='falling')
                battle,state,td=self.setup_motion(detail)
                with mock.patch.object(battle_module.world_collision,'check_horizontal_collision',return_value='clear') as world:
                    value=battle._probe_bot_local_motion(8,(0.,0.,0.),0.,0. if sign>0 else math.pi,2.,td,.1,1.)
                    self.assertTrue(value['clear']); self.assertFalse(value['proved'])
                    self.assertEqual('local_sweep_commit_required',value['reason'])
                    self.assertEqual('catalog_commit_required',value['trace']['reason'])
                    battle._destructibles._catalog_motion_blocked.assert_not_called()
                    self.assertEqual({'realised':'translation'},state['_world_contact_trace'])
                    state.update(movement_dir=int(sign),rotation_dir=0)
                    status=battle._resolve_bot_motion(8,(0.,0.,0.),0.,sign*5.,td,.1,2.)
                    self.assertEqual('crushed',status)
                    self.assertTrue(battle._destructibles._catalog_motion_blocked.call_args.kwargs['commit_enabled'])
                    self.assertEqual(3,world.call_count) # preview, real sweep, replacement BSP

    def test_real_wall_remains_hard_and_never_reaches_crush_proposal(self):
        battle,state,td=self.setup_motion(dict(status='crushed',requires_commit=True))
        with mock.patch.object(battle_module.world_collision,'check_horizontal_collision',return_value='hard'):
            value=battle._probe_bot_local_motion(8,(0,0,0),0.,0.,1.,td,.1,1.)
        self.assertFalse(value['clear']);self.assertTrue(value['proved'])
        battle._destructibles._catalog_motion_proposal.assert_not_called()

    def test_hard_sibling_cannot_be_overridden_by_crushable_subset(self):
        battle,state,td=self.setup_motion(dict(status='hard',requires_commit=True,
            token=((33405,77,None),),kinds='falling,structure'))
        with mock.patch.object(battle_module.world_collision,'check_horizontal_collision',return_value='clear'):
            value=battle._probe_bot_local_motion(8,(0,0,0),0.,0.,1.,td,.1,1.)
        self.assertFalse(value['clear']);self.assertTrue(value['proved'])
        battle._destructibles._catalog_motion_blocked.assert_not_called()

    def test_replacement_geometry_can_stop_actual_crush(self):
        battle,state,td=self.setup_motion(dict(status='clear',requires_commit=False))
        state.update(movement_dir=1,rotation_dir=0)
        with mock.patch.object(battle_module.world_collision,'check_horizontal_collision',side_effect=('clear','hard')):
            self.assertEqual('hard',battle._resolve_bot_motion(8,(0,0,0),0.,5.,td,.1,1.))


class ActionProgressTests(unittest.TestCase):
    def scene(self):
        driver=LocalDriver();state=driver._state(10,9,(0.,0.,0.))
        state.update(clock=10.,translation_progress_at=10.,progress_identity=('combat','bot',16),
            objective_progress=dict(goal=(0.,0.,8.),best=8.,at=0.,
                order_goal=(0.,0.,-100.),order_best=90.,travel_origin=(0.,0.,5.),travel_best=5.,
                connectors=[],identity=('combat','bot',16)))
        return driver,state

    def drive(self, driver, position, target=(0.,0.,8.), dt=.1, progress=None):
        return driver.drive(10,9,position,0.,1.,dt,target,(),lambda *args,**kw:True,
            stop_at_target=False,progress_target=target if progress is None else progress,
            recovery_goal=(0.,0.,-100.),turn_speed_limit=.5,progress_identity=('combat','bot',16))

    def test_real_local_translation_does_not_inherit_macro_timeout(self):
        driver,state=self.scene()
        command=self.drive(driver,(0.,0.,2.))
        self.assertNotEqual('reverse_turn',command['recovery_mode'])
        self.assertEqual('new_best_local_translation',state['objective_progress']['credit_reason'])
        self.assertFalse(state['arrival_trace']['objective_stalled'])
        self.assertEqual((0.,0.,-100.),state['objective_progress']['order_goal'])

    def test_near_endpoint_arrival_counts_even_when_macro_progress_point_is_different(self):
        driver,state=self.scene();state['objective_progress'].update(goal=(0.,0.,-100.),best=90.,
            action_points=[dict(goal=(0.,0.,5.),best=5.)])
        command=self.drive(driver,(0.,0.,4.),target=(0.,0.,5.),progress=(0.,0.,-100.))
        self.assertEqual('arrived',command['recovery_mode'])
        self.assertEqual('new_best_action_translation',state['objective_progress']['credit_reason'])

    def test_reselecting_point_without_translation_does_not_renew_clock(self):
        driver,state=self.scene()
        command=self.drive(driver,(0.,0.,0.),target=(0.,0.,6.))
        self.assertEqual('reverse_turn',command['recovery_mode'])
        self.assertEqual('objective_timeout',state['recovery_trigger']['reason'])
        self.assertAlmostEqual(.1,state['recovery_trigger']['translation_age'])

    def test_revisiting_already_reached_local_points_cannot_credit_an_orbit(self):
        driver,state=self.scene();state['objective_progress'].update(at=state['clock'],
            action_points=[dict(goal=(0.,0.,2.),best=0.),dict(goal=(0.,0.,-2.),best=0.)])
        # The progress point remains the macro goal; only near driver targets alternate.
        modes=[]
        for i in range(100):
            point=(0.,0.,2. if i%2 else -2.)
            modes.append(self.drive(driver,point,target=point,progress=(0.,0.,-100.))['recovery_mode'])
        self.assertIn('reverse_turn',modes)

    def test_completed_short_translation_retires_parent_backout_but_rejection_does_not(self):
        for sign in (-1.,1.):
            for reason in ('distance_completed','lease_expired'):
                with self.subTest(sign=sign,reason=reason):
                    driver,state=self.scene();state.update(recovery_time=.7,recovery_count=2)
                    escape=dict(start=(0.,0.,0.),yaw=0.,sign=sign,distance=2.,until=30. if reason=='distance_completed'else 9.)
                    state['short_translation_escape']=escape
                    pos=(0.,0.,sign*2.) if reason=='distance_completed' else (0.,0.,0.)
                    driver._retained_short_escape(state,pos,0.,(),lambda *a:True,3.,1.5)
                    self.assertNotIn('short_translation_escape',state)
                    self.assertEqual(reason,state['escape_terminal']['reason'])
                    self.assertEqual(0. if reason=='distance_completed'else .7,state['recovery_time'])
                    self.assertEqual(3 if reason=='distance_completed'else 2,state['recovery_count'])

    def test_drive_handoff_after_successful_forward_exit_does_not_resume_old_reverse(self):
        driver,state=self.scene()
        state.update(recovery_time=.7,recovery_count=2,
            short_translation_escape=dict(start=(0.,0.,0.),yaw=0.,sign=1.,distance=2.,until=30.))
        command=self.drive(driver,(0.,0.,2.))
        self.assertNotEqual('reverse_turn',command['recovery_mode'])
        self.assertEqual('distance_completed',state['escape_terminal']['reason'])
        self.assertEqual(0.,state['recovery_time'])
        self.assertNotIn('short_translation_escape',state)

    def test_completed_long_translation_retires_parent_backout_once(self):
        driver,state=self.scene();state.update(recovery_time=.7,recovery_count=2)
        state['translation_escape']=dict(start=(0.,0.,0.),yaw=0.,distance=2.,until=30.)
        self.assertIsNone(driver._retained_translation_escape(state,(0.,0.,2.),0.,(),lambda *a:True,3.,1.5))
        self.assertEqual(0.,state['recovery_time']);self.assertEqual(3,state['recovery_count'])
        self.assertIsNone(driver._retained_translation_escape(state,(0.,0.,2.),0.,(),lambda *a:True,3.,1.5))
        self.assertEqual(3,state['recovery_count'])


if __name__=='__main__':unittest.main()
