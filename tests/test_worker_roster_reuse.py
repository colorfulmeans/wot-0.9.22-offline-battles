"""Membership reuse must retain current sequential collision poses."""
import unittest
from types import SimpleNamespace
from unittest import mock
from test_port_0922_bot_ammo import _load_bot_runtime


class WorkerRosterTests(unittest.TestCase):
    def test_ordinary_worker_executes_orders_without_freezing_diagnostic_snapshots(self):
        # This regression exercises the explicit engine-free reference seam.
        platform=mock.patch('sys.platform','linux')
        platform.start(); self.addCleanup(platform.stop)
        from test_port_0922_bot_runtime import BotRuntimeTests
        fixture=BotRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        runtime=fixture.runtime
        list(runtime.battle_start(fixture.start))
        runtime._server_orders[11]={'combat_mode':'route','fire_allowed':False,
            'move_position':(0.,0.,100.),'face_position':(0.,0.,100.)}
        runtime._server_order_tokens[11]=1
        with mock.patch.object(fixture.module,'detailed_enabled',return_value=False), \
             mock.patch.object(fixture.module,'_order_evidence',side_effect=AssertionError('unused diagnostic snapshot')) as evidence:
            list(runtime.update(.1,1.))
        evidence.assert_not_called()
        self.assertTrue(fixture.adapters[0].server_orders)

    def test_native_rotation_shares_membership_but_observes_mutated_peer_pose(self):
        module=_load_bot_runtime()
        from gui.mods.offline_lan_0922 import native_math
        state={'id':1,'collision_shape':{}}
        peer={'id':2,'x':1.}
        class States(dict):
            def items(self):raise AssertionError('membership rebuilt inside rotation')
        owner=SimpleNamespace(states=States({1:state,2:peer}))
        roster=((1,state),(2,peer)); seen=[]
        def native(name,*args):
            self.assertIs(roster,args[-2])
            seen.append(args[-2][1][1]['x'])
            return .75
        with mock.patch.object(native_math,'_load',return_value=SimpleNamespace(rotation_current=lambda:None)), \
             mock.patch.object(native_math,'call',side_effect=native):
            for x in (3.,9.):
                peer['x']=x
                self.assertEqual(.75,module.BotRuntime._rotation_fraction_for(
                    owner,state,(0.,0.,0.),0.,.1,(),current_roster=roster))
        self.assertEqual([3.,9.],seen)


if __name__=='__main__':unittest.main()
