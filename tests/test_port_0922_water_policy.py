"""One water policy, actual shoal paths, and complete SPG proof receipts."""
import contextlib
import io
import json
import math
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid, NAVIGABLE_WATER_DEPTH


class WaterPolicyTests(unittest.TestCase):
    def test_baker_and_runtime_share_one_water_limit_without_modifying_vendor(self):
        import bake_navigation_0922 as baker
        import test_port_0922_bot_runtime as harness
        fixture = harness.BotRuntimeTests(); fixture.setUp()
        try:
            self.assertEqual(1.2, NAVIGABLE_WATER_DEPTH)
            self.assertEqual(NAVIGABLE_WATER_DEPTH, fixture.module.BOT_WATER_AVOID_DEPTH)
            self.assertEqual(NAVIGABLE_WATER_DEPTH, baker.SHALLOW_WATER_THRESHOLD)
            self.assertEqual(NAVIGABLE_WATER_DEPTH, baker._legacy_baker().WATER_DEPTH_LIMIT)
        finally:
            fixture.tearDown()

    def test_actual_shoal_is_bidirectional_without_remote_bridge_detour(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *args: None, baked_graph=graph)
        for a,b in (((306.,-14.,189.),(264.,-14.,189.)), ((264.,-14.,189.),(306.,-14.,189.))):
            path = grid.plan(a,b,max_expansions=20000)
            self.assertTrue(path)
            self.assertLess(math.hypot(path[-1][0]-b[0],path[-1][2]-b[2]),2.)
            length = sum(math.hypot(q[0]-p[0],q[2]-p[2]) for p,q in zip(path,path[1:]))
            self.assertLess(length,50.)
            self.assertTrue(all(185.<=p[2]<=193. for p in path))
            for p,q in zip(path,path[1:]):
                self.assertTrue(grid.segment_clear(p,q))
                self.assertFalse(grid.segment_has_motion_hazard(p,q,13))
            for width in (1.2,1.8,2.15):
                for yaw in (math.pi/2,-math.pi/2):
                    for x in range(265,307):
                        self.assertTrue(grid.hull_pose_clear((x,-15.,189.),yaw,3.2,width), (x,yaw,width))

    def test_old_profile_identity_remains_accepted_by_rebuilt_grid(self):
        import hashlib,subprocess
        graph=json.loads((ROOT/'navgraphs/84_winter.json').read_bytes())
        old=subprocess.check_output(['git','show','f317c4e6:navgraphs/84_winter.json'],cwd=ROOT)
        self.assertIn(hashlib.sha256(old).hexdigest(),graph['navigation_previous_sha256s'])


class ArtilleryProofDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        import test_port_0922_bot_runtime as harness
        self.fixture=harness.BotRuntimeTests();self.fixture.setUp()
        self.module=self.fixture.module
        self.runtime=self.module.BotRuntime(1)
        self.runtime.round_id=2
        self.runtime.states[29]={'id':29}

    def tearDown(self):
        self.fixture.tearDown()

    def test_terminal_receipt_freezes_replaced_intent_and_is_bounded(self):
        intent={'created':10.,'fire_seq':1,'target_identity':('bot',2),
                'solution':{'aim_position':[1.,2.,3.]}}
        self.runtime._artillery_intents[29]=intent
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            self.runtime._record_artillery_transition(29,'intent_created',11.)
            intent['solution']['aim_position'][0]=999.
            self.runtime._cancel_artillery_intent(29,reason='exact_launch_failed',now=12.,evidence={'reason':'world_blocked'})
            for i in range(20):self.runtime._record_artillery_transition(29,'test',13.+i)
        history=self.runtime.states[29]['_spg_proof_history']
        self.assertEqual(16,len(history))
        lines=[json.loads(line.split('SPG PROOF ',1)[1]) for line in output.getvalue().splitlines() if 'SPG PROOF ' in line]
        self.assertEqual([1.,2.,3.],lines[0]['solution']['aim_position'])
        self.assertEqual('exact_launch_failed',lines[1]['reason'])
        self.assertEqual('world_blocked',lines[1]['evidence']['reason'])
        self.assertNotIn(29,self.runtime._artillery_intents)

    def test_reproof_can_slew_to_new_lead_but_pending_exact_shot_cannot(self):
        import test_port_0922_bot_runtime as harness
        descriptor=harness._combat_descriptor(dispersion=.03)
        state={'id':29,'x':0.,'y':0.,'z':0.,'yaw':0.,'pitch':0.,'roll':0.,
               'turret_yaw':.02,'gun_pitch':-.35,'fire_seq':0}
        target={'kind':'bot','id':2,'alive':True,'position':(0.,0.,100.)}
        original=(0.,0.,0.,0.,0.,0.,.03,-.34)
        proof={'source_pose':original,'target_identity':('bot',2),'shell_index':0,
               'fire_seq':1,'physical':self.module._shot_ballistics(descriptor,0),
               'deadline':20.,'created':1.,'absolute_deadline':30.,'attempts':1}
        self.runtime._artillery_reproofs[29]=proof
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(proof,self.runtime._active_artillery_reproof(state,target,descriptor,0,10.))
        self.runtime._artillery_intents[29]={'source':{'id':29},'source_pose':self.runtime._artillery_source_pose(state)}
        state['gun_pitch']-=.01
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(self.runtime._active_artillery_intent(state,target,descriptor,0,10.1))
        self.assertNotIn(29,self.runtime._artillery_intents)
        self.assertNotIn(29,self.runtime._artillery_reproofs)

    def test_fragmented_proof_history_survives_the_report_reader(self):
        import read_native_evidence as reader
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            self.runtime._record_artillery_transition(29,'aim_receipt_stale',12.,
                {'target_velocity':[8.,0.,0.],'details':'x'*12000})
        parsed=reader.parse_lines(out.getvalue().splitlines())
        self.assertEqual([],parsed['issues'])
        self.assertEqual(1,len(parsed['records']))
        record=parsed['records'][0]
        self.assertEqual('SPG PROOF',record['label'])
        self.assertEqual('aim_receipt_stale',record['data']['reason'])
        self.assertEqual('x'*12000,record['data']['evidence']['details'])

    def test_deadline_and_pose_cancellation_preserve_complete_cause(self):
        import test_port_0922_bot_runtime as harness
        descriptor=harness._combat_descriptor(dispersion=.03)
        state={'id':29,'x':0.,'y':0.,'z':0.,'yaw':0.,'fire_seq':0}
        target={'kind':'bot','id':2,'alive':True,'position':(0.,0.,100.)}
        for changed,reason in ((False,'proof_deadline_expired'),(True,'proof_identity_or_pose_changed')):
            self.runtime._artillery_reproofs[29]={'source_pose':(0.,0.,0.,0.),'target_identity':('bot',2),
                'shell_index':0,'fire_seq':1,'physical':self.module._shot_ballistics(descriptor,0),
                'deadline':5.,'created':1.,'absolute_deadline':8.,'attempts':3}
            state['x']=1. if changed else 0.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(self.runtime._active_artillery_reproof(state,target,descriptor,0,10.))
            receipt=self.runtime.states[29]['_spg_proof_history'][-1]
            self.assertEqual(reason,receipt['reason'])
            self.assertEqual(3,receipt['reproof']['attempts'])
            if changed:self.assertEqual(1.,receipt['evidence']['moved'])
            self.assertNotIn(29,self.runtime._artillery_reproofs)


if __name__=='__main__':unittest.main()
