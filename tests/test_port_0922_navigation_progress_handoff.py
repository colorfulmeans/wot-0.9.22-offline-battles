"""A proved dogleg owns driver progress without crediting temporary orbits."""
import math
import types
import unittest
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator


class NavigationProgressHandoffTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BotAdapter('04_himmelsdorf', 1)
        self.state = dict(id=30,slot=0,team=2,position=(0.,0.,0.),yaw=math.pi/2,
                          speed=1.,dt=.1,neighbours=[],pose_clear=lambda yaw: True)
        self.target = (50.,0.,0.)
        self.order = dict(combat_mode='route',move_position=(0.,0.,-100.),
                          throttle_override=None)

    def callback(self, proved=True):
        def navigate(bot_id,position,goal,order,state):
            state['navigation_status']='safe'
            if proved: state['navigation_progress_target']=self.target
            return self.target
        self.adapter.navigation_target=navigate

    def test_real_travel_along_a_proved_dogleg_does_not_trigger_reverse(self):
        self.callback()
        for frame in range(150):
            self.state['position']=(frame*.03,0.,0.)
            command=self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
            self.assertNotIn(command['recovery_mode'],('reverse_turn','pivot_recovery'))

    def test_a_stalled_proved_edge_still_releases_to_recovery(self):
        self.callback()
        modes=[self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
               ['recovery_mode'] for unused in range(120)]
        self.assertIn('reverse_turn',modes)

    def test_t49_reported_sideways_leg_is_not_mistaken_for_macro_stall(self):
        # 160923 T49: a proved eastbound connector precedes the southbound
        # macro goal. Clear proof callbacks isolate the competing clocks.
        self.target=(-14.,.258,30.)
        self.order['move_position']=(-35.317,0.,-104.68)
        self.state['yaw']=1.518586986697
        self.callback()
        for frame in range(150):
            self.state['position']=(-32.464678224128+frame*.03,.265616893768,30.020126186448)
            command=self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
            self.assertNotIn(command['recovery_mode'],('reverse_turn','pivot_recovery'))

    def test_unproved_temporary_travel_retains_macro_stall_boundary(self):
        self.callback(False)
        modes=[]
        for frame in range(150):
            self.state['position']=(frame*.03,0.,0.)
            modes.append(self.adapter.decide_with_order(self.state,self.order,
                lambda *args: True)['recovery_mode'])
        self.assertIn('reverse_turn',modes)

    def test_an_old_proof_does_not_survive_a_new_callback_without_proof(self):
        self.callback()
        self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
        self.callback(False)
        self.adapter.decide_with_order(self.state,self.order,lambda *args: True)
        self.assertNotIn('navigation_progress_target',self.state)

    def owner(self, **changes):
        row=dict(navigation_status='safe',macro_progress_kind='path',path_key='leg',
                 last_target=self.target,index=1)
        row.update(changes)
        return types.SimpleNamespace(bot_states={30:row},paths={'leg':[(0.,0.,0.),self.target]})

    def proof(self,owner,current=(0.,0.,0.),target=None,now=0.):
        return TerrainNavigator.driver_progress_target(owner,30,current,target or self.target,now)

    def test_canonical_path_receipt_admits_its_actual_target(self):
        self.assertEqual(self.target,self.proof(self.owner()))

    def test_temporary_pending_missing_or_changed_target_has_no_path_receipt(self):
        for change in (dict(macro_progress_kind='temporary'),dict(navigation_status='pending'),
                       dict(path_key='missing'),dict(last_target=(0.,0.,20.))):
            self.assertIsNone(self.proof(self.owner(**change)))

    def test_close_waypoint_cannot_hide_an_unfinished_macro_goal(self):
        self.assertIsNone(self.proof(self.owner(),current=(49.5,0.,0.)))

    def test_a_retained_local_leg_keeps_its_lease_and_macro_deadlines(self):
        owner=self.owner(macro_progress_kind='temporary',local_fallback_target=self.target,
            local_fallback_start=(0.,0.,0.),local_fallback_intent=('leg',),
            local_fallback_episode=('leg',),local_target_progress_at=0.)
        self.assertEqual(self.target,self.proof(owner,now=1.))
        self.assertIsNone(self.proof(owner,now=13.))
        owner.bot_states[30]['temporary_stalled']=True
        self.assertIsNone(self.proof(owner,now=1.))

    def test_a_retained_local_target_cannot_borrow_a_changed_intent(self):
        owner=self.owner(local_fallback_target=self.target,local_fallback_start=(0.,0.,0.),
            local_fallback_intent=('new',),local_fallback_episode=('old',),local_target_progress_at=0.)
        self.assertIsNone(self.proof(owner))

    def test_runtime_publishes_only_the_current_navigation_receipt(self):
        import test_port_0922_bot_runtime as harness
        fixture=harness.BotRuntimeTests()
        fixture.setUp()
        try:
            runtime=fixture.runtime
            runtime.battle_start(fixture.start)
            target=self.target
            owner=self.owner()
            owner.bot_states={11:owner.bot_states[30]}
            owner.grid=types.SimpleNamespace(cell_size=4.)
            owner.next_target=lambda *args,**kwargs: target
            owner.driver_progress_target=lambda *args: TerrainNavigator.driver_progress_target(owner,*args)
            runtime.navigator=owner
            runtime._occupied_route_target=lambda *args: None
            runtime._route_lane_target=lambda bot,position,goal,point,*args: point
            state=dict(runtime.states[11],now=1.)
            runtime._navigation_target(11,(0.,0.,0.),self.order['move_position'],self.order,state)
            self.assertEqual(target,state['navigation_progress_target'])
            owner.bot_states[11]['macro_progress_kind']='temporary'
            runtime._navigation_target(11,(0.,0.,0.),self.order['move_position'],self.order,state)
            self.assertNotIn('navigation_progress_target',state)
        finally:
            fixture.tearDown()
