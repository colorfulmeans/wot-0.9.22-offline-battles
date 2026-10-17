"""Recorded 043353 exits; controlled native replies, not Windows acceptance."""
import json
import math
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922 import tank_collision

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / 'tests/fixtures/caucasus_043353_contact_exits.json').read_text())


class ReverseContactTests(unittest.TestCase):
    def setUp(self):
        self.driver = LocalDriver()
        self.case = DATA['t95']

    def reverse(self, peers=None, distance=2.0):
        c = self.case
        return self.driver._reference_reverse_blocked_by_vehicle(c['position'], c['yaw'],
            c['peers'] if peers is None else peers, c['half_length'], c['half_width'], distance)

    def test_recorded_t95_tangent_does_not_deepen_overlap(self):
        c = self.case; p = c['position']; w = c['peers'][0]
        hit = tank_collision._obb_overlap(p[0], p[2], c['yaw'],
            (c['half_width'], c['half_length']), w['position'][0], w['position'][2],
            w['yaw'], (w['half_width'], w['half_length']))
        self.assertAlmostEqual(.0027854934275488574, hit[2])
        self.assertAlmostEqual(0., -math.sin(c['yaw'])*hit[0]-math.cos(c['yaw'])*hit[1])
        for distance in (.05, .1, .5, 1., 2.):
            with self.subTest(distance=distance):
                self.assertIsNone(self.reverse(distance=distance))
                q = [p[0]-math.sin(c['yaw'])*distance, p[1], p[2]-math.cos(c['yaw'])*distance]
                after = tank_collision._obb_overlap(q[0], q[2], c['yaw'],
                    (c['half_width'], c['half_length']), w['position'][0], w['position'][2],
                    w['yaw'], (w['half_width'], w['half_length']))
                self.assertLessEqual(after[2], hit[2]+1.e-9)

    def test_other_rear_hull_still_blocks_full_sweep(self):
        c = self.case; p = c['position']; y = c['yaw']
        rear = dict(id=99, position=(p[0]-math.sin(y)*8.,p[1],p[2]-math.cos(y)*8.),
                    yaw=y,half_length=3.,half_width=2.)
        self.assertEqual(99, self.reverse(c['peers']+[rear]))
        self.assertIsNone(self.reverse(c['peers']+[rear], .1))

    def test_initial_rear_contact_that_deepens_is_rejected(self):
        self.assertEqual(4, self.driver._reference_reverse_blocked_by_vehicle(
            (0.,0.,0.),0.,[dict(id=4,position=(0.,0.,-6.),yaw=0.,
            half_length=3.5,half_width=1.5)],3.5,1.5,1.))

    def test_intermediate_hull_cannot_be_skipped_by_endpoint(self):
        self.assertEqual(4, self.driver._reference_reverse_blocked_by_vehicle(
            (0.,0.,0.),0.,[dict(id=4,position=(0.,0.,-9.),yaw=0.,
            half_length=1.,half_width=1.)],3.5,1.5,20.))

    def test_native_and_reference_wrapper_publish_same_decision_inputs(self):
        c=self.case
        for native in (None,-1,0):
            with self.subTest(native=native), mock.patch.object(self.driver,'_native_geometry',return_value=native):
                result=self.driver._reverse_blocked_by_vehicle(c['position'],c['yaw'],c['peers'],
                    c['half_length'],c['half_width'],2.)
                receipt=self.driver._last_reverse_receipt
                self.assertEqual(23 if native==0 else None,result)
                self.assertEqual(result,receipt['blocker'])
                self.assertEqual(tuple(c['position']),receipt['origin'])
                self.assertEqual(2.,receipt['distance'])


class NativeExitAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph=json.loads((ROOT/'navgraphs/37_caucasus.json').read_text())

    def scene(self, case):
        nav=TerrainNavigator(lambda x,z,hint:.860245,lambda *args:False,baked_graph=self.graph)
        w=case['wreck'];shape=w['shape']
        nav.grid.set_static_hulls([(w['id'],w['position'][0],w['position'][2],w['yaw'],shape[1],shape[0])],
                                  clearance=1.8657310009002686)
        return nav

    def select(self, nav, c):
        state={}
        result=nav._new_local_fallback(c['bot'],tuple(c['current']),tuple(c['origin']),
            tuple(c['goal']),c['at'],(),state)
        return result,state['local_selection']

    def test_recorded_e3_and_amx_keep_native_proved_exit_despite_coarse_cost(self):
        for c in DATA['connectors']:
            with self.subTest(bot=c['bot']):
                nav=self.scene(c)
                self.assertEqual(240.,nav.grid.segment_penalty(c['current'],c['candidate'],c['at']))
                result,selection=self.select(nav,c)
                self.assertEqual(tuple(c['candidate']),result)
                self.assertEqual('selected',selection['outcome'])
                self.assertEqual('clear',selection['connector']['reason'])
                self.assertEqual(240.,selection['connector']['proof']['coarse_penalty'])
                # Reuse still re-proves geometry; it is not a permanent exemption.
                self.assertFalse(nav.bot_segment_penalized(c['bot'],c['current'],result,c['at']))
                self.assertTrue(nav.grid.dry_segment_clear(c['current'],result,c['at']+1))
                nav.grid.obstacle_probe=lambda *args:True
                self.assertFalse(nav.grid.dry_segment_clear(c['current'],result,c['at']+2))

    def test_real_wreck_corridor_is_not_advisory(self):
        c=DATA['connectors'][0];nav=self.scene(c);a=c['current'];b=c['candidate']
        nav.grid.set_static_hulls([(91,(a[0]+b[0])*.5,(a[2]+b[2])*.5,0.,2.,1.)],clearance=2.)
        receipt={}
        self.assertFalse(nav.grid._live_exit_clear(a,b,c['at'],receipt))
        self.assertEqual('static_hull_corridor',receipt['egress_reason'])
        self.assertEqual(91,receipt['blocker'])

    def test_timed_failure_still_rejects_even_when_native_clear(self):
        c=DATA['connectors'][0];nav=self.scene(c)
        edge=next(iter(nav.grid._edge_keys_for_segment(c['current'],c['candidate'])))
        nav.grid._failed_edges[edge]=(c['at']+10.,240.)
        receipt={}
        self.assertFalse(nav.grid._live_exit_clear(c['current'],c['candidate'],c['at'],receipt))
        self.assertEqual('timed_failed_edge',receipt['egress_reason'])
        self.assertTrue(nav.grid._live_exit_clear(c['current'],c['candidate'],c['at']+11.))

    def test_private_edge_veto_has_terminal_reason(self):
        c=DATA['connectors'][0];nav=self.scene(c)
        with mock.patch.object(nav,'_bot_edges_penalized',return_value=True):
            result,selection=self.select(nav,c)
        self.assertEqual(tuple(c['current']),result)
        self.assertEqual('connector_rejected',selection['outcome'])
        self.assertEqual('bot_private_or_retired_edge',selection['connector']['reason'])

    def test_deferred_changed_revision_exception_and_real_wall_do_not_admit(self):
        c=DATA['connectors'][0]
        for verdict in ('deferred',True,'revision','exception'):
            with self.subTest(verdict=verdict):
                nav=self.scene(c);receipt={}
                def probe(*args):
                    if verdict=='exception':raise RuntimeError('probe failed')
                    if verdict=='revision':nav.grid._native_proof_revision+=1;return False
                    return verdict
                nav.grid.obstacle_probe=probe
                self.assertFalse(nav.grid._live_exit_clear(c['current'],c['candidate'],c['at'],receipt))
                self.assertIn(receipt['egress_reason'],('deferred','obstacle','probe_failed'))

    def test_missing_support_water_and_height_break_still_reject(self):
        c=DATA['connectors'][0]
        for kind in ('missing','height','water'):
            with self.subTest(kind=kind):
                nav=self.scene(c);receipt={}
                if kind=='missing':nav.grid.ground_probe=lambda *args:None
                if kind=='height':nav.grid.ground_probe=lambda x,z,hint:hint+10.
                patch=mock.patch.object(nav.grid,'segment_has_motion_hazard',return_value=True) if kind=='water' else mock.patch.object(nav.grid,'_inside',wraps=nav.grid._inside)
                with patch:self.assertFalse(nav.grid._live_exit_clear(c['current'],c['candidate'],c['at'],receipt))
                self.assertIn(receipt['egress_reason'],('missing_support','grade','hazard_or_unavailable'))

    def test_final_actual_pose_probe_keeps_each_rejection_reason(self):
        c=DATA['connectors'][0]
        for verdict,reason in ((True,'native_obstacle'),('deferred','native_deferred'),
                               ('revision','native_revision_changed'),('exception','native_probe_exception')):
            with self.subTest(verdict=verdict):
                nav=self.scene(c)
                original=nav.grid._probe_obstacle
                def probe(start,end,width,*args,**kwargs):
                    if start[1]>.9:
                        if verdict=='exception':raise RuntimeError('failed final probe')
                        if verdict=='revision':nav.grid._native_proof_revision+=1;return False
                        return verdict
                    return original(start,end,width,*args,**kwargs)
                with mock.patch.object(nav.grid,'_probe_obstacle',side_effect=probe):
                    result,selection=self.select(nav,c)
                self.assertEqual(tuple(c['current']),result)
                self.assertEqual('connector_rejected',selection['outcome'])
                self.assertEqual(reason,selection['connector']['reason'])

    def test_retained_exit_rechecks_and_publishes_wreck_moving_into_corridor(self):
        c=DATA['connectors'][0];nav=self.scene(c);state={}
        target=nav._new_local_fallback(c['bot'],tuple(c['current']),tuple(c['origin']),
            tuple(c['goal']),c['at'],(),state)
        nav.bot_states[c['bot']]=state
        self.assertEqual(target,nav._retained_local_fallback(c['bot'],c['current'],c['goal'],c['at']+.1,state))
        a,b=c['current'],target
        nav.grid.set_static_hulls([(91,(a[0]+b[0])*.5,(a[2]+b[2])*.5,0.,2.,1.)],clearance=2.)
        self.assertIsNone(nav._retained_local_fallback(c['bot'],a,c['goal'],c['at']+.2,state))
        proof=nav.bot_search_diagnostics(c['bot'],a,c['at']+.2)['local_retained_proof']
        self.assertFalse(proof['clear'])
        self.assertEqual('static_hull_corridor',proof['proof']['egress_reason'])
        self.assertEqual(91,proof['proof']['blocker'])

    def test_exact_wreck_pose_refreshes_even_when_coarse_revision_does_not(self):
        c=DATA['connectors'][0];nav=self.scene(c);h=list(nav.grid._static_hulls[0]);rev=nav.grid.static_hull_revision
        h[1]+=.001
        self.assertFalse(nav.grid.set_static_hulls([h],clearance=1.8657310009002686))
        self.assertEqual(rev,nav.grid.static_hull_revision)
        self.assertEqual(h[1],nav.grid._static_hulls[0][1])


if __name__=='__main__':unittest.main()
