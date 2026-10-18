"""Local candidates must use non-committing realised body geometry."""
import math
import types
import unittest
from unittest import mock
from test_port_0922_battle_runtime import _runtime, BattleRuntime
from test_port_0922_bot_runtime import _combat_descriptor


class LocalActionSweepTests(unittest.TestCase):
    def scene(self):
        battle=BattleRuntime(_runtime())
        state=dict(id=8,alive=True,movement_dir=0,rotation_dir=1,
                   _rotation_contact_trace={'realised':'rotation'},
                   _world_contact_trace={'realised':'translation'})
        battle._bots=types.SimpleNamespace(states={8:state})
        battle._bot_motion_kinds={8:'original'}
        return battle,state,_combat_descriptor()

    def test_rotation_previews_only_next_physical_slice_without_commit(self):
        battle,state,descriptor=self.scene()
        def turn(*args,**kwargs):
            self.assertFalse(kwargs['commit_enabled'])
            state['_rotation_contact_trace']={'hit':(61.3968,1.7,-51.8394)}
            return False
        battle._resolve_bot_rotation=mock.Mock(side_effect=turn)
        result=battle._probe_bot_local_motion(8,(58.877,1.1,-48.988),-.1804,-1.1184,None,descriptor,.1,241.341)
        self.assertFalse(result['clear'])
        self.assertEqual('local_sweep_blocked',result['reason'])
        self.assertAlmostEqual(-.075,result['checked_yaw']+.1804)
        self.assertEqual({'realised':'rotation'},state['_rotation_contact_trace'])
        self.assertEqual('original',battle._bot_motion_kinds[8])

    def test_signed_left_right_and_wrapped_rotation_slices(self):
        for start, goal in ((0., .05), (0., -.05), (0., 2.), (0., -2.),
                            (3.13, -3.13), (-3.13, 3.13)):
            with self.subTest(start=start, goal=goal):
                battle,state,descriptor=self.scene()
                battle._resolve_bot_rotation=mock.Mock(return_value=True)
                value=battle._probe_bot_local_motion(
                    8,(0.,1.1,0.),start,goal,None,descriptor,.1,1.)
                # atan2 is an independent shortest-turn oracle, including
                # crossing the +/- pi seam in either direction.
                delta=math.atan2(math.sin(goal-start),math.cos(goal-start))
                expected=math.copysign(min(abs(delta),.075),delta)
                actual=value['checked_yaw']-start
                self.assertAlmostEqual(expected,actual)
                self.assertGreater(actual*delta,0.)
                call=battle._resolve_bot_rotation.call_args
                self.assertAlmostEqual(start,call.args[2])
                self.assertAlmostEqual(start+expected,call.args[3])
                self.assertFalse(call.kwargs['commit_enabled'])

    def test_preview_and_real_commit_sweep_the_same_reported_rotation(self):
        # KV-1 at 22:11:12.749 in report c31c22a3a1fb: the left sweep
        # strikes a wall, while the mirrored right sweep is clear.
        start=.7943278541736059
        for delta in (-.055154066175541, .055154066175541):
            with self.subTest(delta=delta):
                battle,state,descriptor=self.scene()
                battle._destructible_pose_sweep=mock.Mock(return_value={
                    'status':'clear','requires_commit':False})
                battle._tree_motion_proposal=mock.Mock(return_value={
                    'status':'clear','requires_commit':False})
                battle._complete_bot_tree_contact=mock.Mock(return_value='clear')
                def native(position, first, last, td, **kwargs):
                    return last > first
                battle._native_world_rotation_is_clear=mock.Mock(side_effect=native)
                position=(189.242936047,1.100000143,-287.227001755)
                preview=battle._probe_bot_local_motion(8,position,start,
                    start+delta,None,descriptor,.1580047607421875,161.154)
                proposed=battle._native_world_rotation_is_clear.call_args
                realised=battle._resolve_bot_rotation(8,position,start,
                    start+delta,descriptor,.1580047607421875,161.154,.75)
                committed=battle._native_world_rotation_is_clear.call_args
                self.assertEqual(delta > 0.,preview['clear'])
                self.assertEqual(realised,preview['clear'])
                self.assertEqual(proposed,committed)
                self.assertAlmostEqual(start+delta,proposed.args[2])

    def test_aligned_front_and_rear_use_full_motion_resolver_and_restore_controls(self):
        for yaw,sign in ((0.,1),(math.pi,-1)):
            battle,state,descriptor=self.scene()
            def move(*args,**kwargs):
                self.assertFalse(kwargs['commit_enabled'])
                self.assertEqual(yaw,kwargs['motion_yaw'])
                self.assertEqual(sign,state['movement_dir'])
                self.assertAlmostEqual(.54,abs(args[3])*args[5])
                state['_world_contact_trace']={'hit':(57.78,1.7,-44.49)}
                return 'hard'
            battle._resolve_bot_motion=mock.Mock(side_effect=move)
            result=battle._probe_bot_local_motion(8,(0.,1.1,0.),0.,yaw,.54,descriptor,.1,305.)
            self.assertFalse(result['clear'])
            self.assertEqual(0,state['movement_dir'])
            self.assertEqual(1,state['rotation_dir'])
            self.assertEqual({'realised':'translation'},state['_world_contact_trace'])

    def test_unaligned_future_exit_keeps_its_existing_rotation_owner(self):
        battle,state,descriptor=self.scene()
        battle._resolve_bot_motion=mock.Mock(side_effect=AssertionError('sideways prediction'))
        value=battle._probe_bot_local_motion(8,(0,0,0),0.,.5,2.,descriptor,.1,1.)
        self.assertIsNone(value['clear'])
        self.assertEqual('local_sweep_not_aligned',value['reason'])

    def test_pending_destruction_is_deferred_to_real_commit(self):
        battle,state,descriptor=self.scene()
        battle._resolve_bot_rotation=mock.Mock(return_value=None)
        result=battle._probe_bot_local_motion(8,(0,0,0),0.,1.,None,descriptor,.1,1.)
        self.assertTrue(result['clear'])
        self.assertFalse(result['proved'])
        self.assertEqual('local_sweep_commit_required',result['reason'])

    def test_preview_exception_restores_realised_evidence(self):
        battle,state,descriptor=self.scene()
        def failure(*args,**kwargs):
            state['movement_dir']=-99
            state['_world_contact_trace']={'candidate':True}
            raise RuntimeError('native failure')
        battle._resolve_bot_motion=mock.Mock(side_effect=failure)
        with self.assertRaises(RuntimeError):
            battle._probe_bot_local_motion(8,(0,0,0),0.,0.,2.,descriptor,.1,1.)
        self.assertEqual(0,state['movement_dir'])
        self.assertEqual({'realised':'translation'},state['_world_contact_trace'])

    def test_real_rotation_resolver_never_commits_candidate_destruction(self):
        battle,state,descriptor=self.scene()
        battle._destructible_pose_sweep=mock.Mock(return_value={
            'status':'crushed','requires_commit':True,'token':('prop',)})
        battle._native_world_rotation_is_clear=mock.Mock(side_effect=AssertionError('uncommitted replacement'))
        value=battle._resolve_bot_rotation(8,(0,0,0),0.,.01,descriptor,.1,1.,0.,commit_enabled=False)
        self.assertIsNone(value)
        self.assertEqual(1,battle._destructible_pose_sweep.call_count)

    def test_runtime_direction_and_rotation_callbacks_publish_full_sweep_evidence(self):
        import contextlib,io
        import test_port_0922_bot_runtime as bots
        fixture=bots.BotRuntimeTests();fixture.setUp()
        try:
            runtime=fixture.runtime
            runtime.battle_start(fixture.start)
            runtime.local_sweep_probe=mock.Mock(return_value={
                'clear':False,'reason':'local_sweep_blocked','source':'authoritative_body_sweep'})
            runtime.rotation_resolver=mock.Mock(return_value=True)
            runtime.navigator.grid.hull_pose_clear=mock.Mock(return_value=False)
            observed=[]
            def decide(state,clear):
                observed.append(state['pose_clear'](state['yaw']+.9))
                observed.append(state['pose_clear'](state['yaw']+1.2))
                observed.append(clear(state['yaw'],.54))
                return {'throttle':0.,'turn':0.,'target_yaw':state['yaw'],'fire_allowed':False}
            runtime.adapter.decide=decide
            with contextlib.redirect_stdout(io.StringIO()):runtime.update(.1,1.)
            self.assertEqual([False,False,False],observed)
            # Both positive target angles share the same next physical slice.
            self.assertEqual(2,runtime.local_sweep_probe.call_count)
            for call in runtime.local_sweep_probe.call_args_list:
                self.assertIs(call.args[5],runtime._descriptors[11])
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
