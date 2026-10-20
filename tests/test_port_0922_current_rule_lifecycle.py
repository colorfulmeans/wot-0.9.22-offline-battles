"""Current support, contact-owner and diagnostic-update lifecycles.

These are engine-free contracts. They do not certify native rendering,
map traversal or BigWorld timing.
"""
import contextlib
import copy
import io
import sys
import unittest
from unittest import mock

import test_port_0922_contact_support_navigation as support
import test_port_0922_complete_navigation_receipts as receipts
import test_port_0922_server_bot_ai as server
from gui.mods.offline_lan_0922 import tank_collision
sys.path.insert(0,str(server.PORT_ROOT/'tools'))
from read_native_evidence import parse_lines


class CurrentRuleLifecycleTests(unittest.TestCase):
    def test_each_missing_witness_enables_four_restored_keep_and_five_restore_release(self):
        for missing in range(5):
            with self.subTest(point=missing),contextlib.redirect_stdout(io.StringIO()):
                runtime,state=support.ContactSupportTests.scene(self,lambda x,z:0.)
                runtime._contact_now=1.
                points=[(p['x'],p['z']) for p in runtime._basic_support_status(state)]
                # A changed world belongs to the next physical sample; the
                # same-tick query receipt is deliberately reused exactly.
                runtime._contact_now=1.1
                def probe(x,z,*args,**kwargs):
                    return None if (x,z)==points[missing] else 0.
                with mock.patch.object(runtime,'_ground_probe_at',side_effect=probe):
                    self.assertIsNotNone(runtime._suspension_params_for(11))
                    self.assertTrue(state['_edge_support_active'])
                    state['airborne']=False
                    runtime._contact_now=1.2
                    self.assertFalse(runtime._release_detailed_support(state))
                    self.assertEqual(4,sum(p['valid'] for p in state['_support_mode_sample'][1]))
                runtime._contact_now=1.4
                self.assertTrue(runtime._release_detailed_support(state))
                self.assertNotIn('_edge_support_active',state)
                self.assertIsNone(runtime._suspension_params_for(11))

    def test_contact_partition_changes_with_geometry_and_actor_kind_without_grace(self):
        for kind in ('player','bot'):
            for alive in (False,True):
                with self.subTest(kind=kind,alive=alive):
                    lower=dict(id=12,kind='bot',network_id=12,x=0.,y=0.,z=0.,
                        yaw=0.,pitch=0.,roll=0.,shape=(1.5,3.,0.,2.),
                        mass=36000.,vx=0.,vz=0.,alive=True)
                    upper=dict(lower,id=11,kind=kind,network_id=11,y=1.9,alive=alive)
                    self.assertFalse(tank_collision.planar_body_contact(upper,lower))
                    self.assertEqual((0.,0.),tank_collision.resolve_tank(upper,[lower],dt=.1)['correction'])
                    # No persistent roof exemption: a later same-layer side
                    # overlap must be separated by either solver owner.
                    upper.update(y=0.,x=2.)
                    self.assertTrue(tank_collision.planar_body_contact(upper,lower))
                    self.assertNotEqual((0.,0.),tank_collision.resolve_tank(upper,[lower],dt=.1)['correction'])
                    self.assertNotEqual((0.,0.),tank_collision.resolve_pairs([upper,lower],.1)[11]['correction'])
                    upper['x']=30.
                    self.assertEqual((0.,0.),tank_collision.resolve_tank(upper,[lower],dt=.1)['correction'])

    def test_same_revision_progress_reaches_final_motion_log_without_resetting_cached_drive(self):
        case=receipts.RuntimeReceiptTests()
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            case.setUp()
            self.addCleanup(case.tearDown)
            runtime=case.runtime
            planner=server.BotPlanner()
            route=server._route('lane',[(0.,0.,False),(0.,100.,False),(0.,500.,False)])
            bot=server._bot(11,1,0,route,'heavyTank')
            payload=planner.build_orders([bot],[server._state(11,1,0.,100.)],[],1.)
            runtime._apply_orders(dict(bot_order_revision=payload['revision'],bot_orders=payload['orders']))
            token=runtime._server_order_tokens[11]
            cached=object()
            runtime._decision_cache[11]=cached
            updated=copy.deepcopy(payload['orders'])
            updated[0]['route_assignment']['progress']['at']=2.
            self.assertTrue(runtime._apply_orders(dict(bot_order_revision=payload['revision'],bot_orders=updated)))
            self.assertIs(cached,runtime._decision_cache[11])
            self.assertEqual(token,runtime._server_order_tokens[11])
            runtime._decision_cache.pop(11)
            state=runtime.states[11]
            position=tuple(state[k] for k in ('x','y','z'))
            state['_motion_stall_log']=(position,-10.)
            runtime._log_motion_stall(state,{},0.,0.,False,{},3.)
            runtime._finish_motion_stall(state,False,False,position,3.)
        parsed=parse_lines(out.getvalue().splitlines(),'worker')
        self.assertEqual([],parsed['issues'])
        row=next(r['data'] for r in parsed['records'] if r['label']=='BOT MOTION')
        progress=row['strategic']['route_assignment']['progress']
        self.assertEqual(2.,progress['at'])
        self.assertEqual(updated[0]['route_index'],progress['final_order']['route_index'])
        self.assertEqual('after_contacts_and_support',row['execution_receipt']['phase'])
