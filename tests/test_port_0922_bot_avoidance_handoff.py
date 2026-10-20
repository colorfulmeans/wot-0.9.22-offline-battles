"""Full producer/adapter lane-reposition identity and bounded turn allowance."""
import math
import unittest
import test_port_0922_bot_runtime as harness


class AvoidanceHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()
        self.runtime = self.fixture.module.BotRuntime(1)
        self.state = dict(id=3,team=1,x=0.,y=0.,z=0.,yaw=0.,speed=0.,
            slot=0,collision_shape=(1.5,3.5,0.,2.),half_width=1.5,half_length=3.5)
        self.runtime.states[3] = self.state
        self.runtime._physics_params_for = lambda unused: dict(rotSpd=.4)
        self.target = dict(id=21,kind='bot',alive=True,position=(0.,0.,100.))
        self.command = dict(target_id=21,target_kind='bot',combat_mode='engage',fire_range=500.)
        self.verdict = dict(blocker_kind='bot',blocker_id=4,blocker_team=1,
            blocker_position=(0.,0.,20.),blocker_radius=3.)

    def tearDown(self):
        self.fixture.tearDown()

    def mark(self, now=1.):
        return self.runtime._mark_friendly_reposition(self.state,self.command,self.target,
            dict(fire_seq=1,shot_yaw=0.),self.verdict,now)

    def test_all_turret_types_receive_same_physical_turn_time(self):
        for limits in (None,(-math.pi,math.pi,False),(-.2,.2,True)):
            with self.subTest(limits=limits):
                self.runtime._friendly_repositions.clear()
                self.runtime._gun_yaw_limits[3] = limits
                self.assertTrue(self.mark())
                marker = self.runtime._friendly_repositions[3]
                self.assertAlmostEqual(4.+math.pi/2/.4+2.,marker['deadline']-1.)
                self.assertAlmostEqual(math.pi/2,marker['time_budget']['turn_angle'])
                self.assertEqual(marker['time_budget'],self.state['_friendly_reposition_event']['marker']['time_budget'])
                self.assertTrue(self.mark(2.))
                self.assertIs(marker,self.runtime._friendly_repositions[3])
                self.assertEqual(1.,marker['started_at'])

    def test_turn_time_cap_timeout_retry_and_arrival_remain_bounded(self):
        self.runtime._physics_params_for = lambda unused: dict(rotSpd=.01)
        self.assertTrue(self.mark())
        marker = self.runtime._friendly_repositions[3]
        self.assertEqual(17.,marker['deadline'])
        order,expired = self.runtime._friendly_reposition_order(self.state,{21:self.target},17.)
        self.assertIsNone(order)
        self.assertTrue(expired)
        self.assertEqual('timeout',self.state['_friendly_reposition_last_terminal']['outcome'])
        self.assertEqual(25.,self.state['_friendly_reposition_retry']['until'])
        self.assertFalse(self.mark(18.))
        self.assertTrue(self.mark(26.))
        marker = self.runtime._friendly_repositions[3]
        self.state.update(zip(('x','y','z'),marker['destination']))
        self.assertEqual((None,False),self.runtime._friendly_reposition_order(self.state,{21:self.target},27.))
        self.assertEqual('arrived',self.state['_friendly_reposition_last_terminal']['outcome'])

    def test_produced_bot_and_human_order_keep_adapter_progress_episode(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        for kind,identity in (('bot',21),('human',1000002)):
            with self.subTest(kind=kind):
                self.runtime._friendly_repositions.clear()
                self.command.update(target_id=identity,target_kind=kind)
                self.target.update(id=identity,kind=kind)
                self.runtime._server_orders[3] = dict(self.command,
                    target_id=2 if kind=='human' else identity)
                self.assertTrue(self.mark())
                move,expired = self.runtime._friendly_reposition_order(self.state,{identity:self.target},1.1)
                self.assertFalse(expired)
                self.assertEqual((kind,identity),(move['target_kind'],move['target_id']))
                adapter = BotAdapter('01_karelia',7)
                state = dict(self.state,position=(0.,0.,0.),dt=.1,now=1.,neighbours=())
                approach = dict(self.command,move_position=(0.,0.,100.),aim_position=(0.,0.,100.))
                adapter.decide_with_order(dict(state),approach,lambda *a:True)
                progress = adapter.driver.states[3]['objective_progress']
                adapter.decide_with_order(dict(state,now=1.1),move,lambda *a:True)
                self.assertIs(progress,adapter.driver.states[3]['objective_progress'])
                adapter.decide_with_order(dict(state,now=1.2),approach,lambda *a:True)
                self.assertIs(progress,adapter.driver.states[3]['objective_progress'])

    def test_priority_target_loss_and_parking_release_with_original_receipt(self):
        for cause in ('parking','priority','target_changed','target_gone'):
            with self.subTest(cause=cause):
                self.runtime._server_orders[3] = dict(self.command)
                self.assertTrue(self.mark())
                marker = self.runtime._friendly_repositions[3]
                targets = {21:self.target}
                if cause == 'parking':
                    self.runtime._server_orders[3]['parking_phase'] = 'waiting'
                elif cause == 'priority':
                    self.runtime._server_orders[3]['combat_mode'] = 'base_defense'
                elif cause == 'target_changed':
                    self.runtime._server_orders[3]['target_id'] = 22
                else:
                    targets = {}
                self.assertEqual((None,False),self.runtime._friendly_reposition_order(self.state,targets,2.))
                event = self.state['_friendly_reposition_last_terminal']
                self.assertEqual(dict(parking='parking_handoff',priority='priority_handoff').get(cause,cause),event['outcome'])
                self.assertEqual(marker,event['marker'])
                self.assertNotIn(3,self.runtime._friendly_repositions)


if __name__ == '__main__':
    unittest.main()
