"""Uncertain roof/wait failures gain receipts without changing their verdicts."""
import unittest
from unittest import mock
from gui.mods.offline_lan_0922 import vehicle_stack
from test_port_0922_navigation import TerrainNavigator,StaticHullNavigationTests


class CarrierReceiptTests(unittest.TestCase):
    def test_receipt_distinguishes_no_contact_missing_hit_and_misaligned_witness(self):
        params=dict(springs=(dict(x=0.,y=0.,z=0.,side='left',static_compression=.1),),pseudo_contacts=())
        for height,hits,verdict in (
                (1.,[(('bot',12),{},(0.,0.,0.))],'no_final_contacts'),
                (0.,[],'no_roof_match'),
                (0.,[(('bot',12),{},(.2,0.,0.))],'no_roof_match'),
                (0.,[(('bot',12),{},(0.,0.,0.))],'matched_final_contact')):
            with self.subTest(verdict=verdict,hits=hits):
                solved=dict(height=height,pitch=0.,roll=0.)
                args=(params,[0.],[],solved,(0.,height,0.),0.,0.,0.,hits)
                expected=vehicle_stack.settled_carrier(*args)
                trace={}
                self.assertEqual(expected,vehicle_stack.settled_carrier(*args,trace=trace))
                self.assertEqual(verdict,trace['verdict'])
                self.assertEqual(len(hits),trace['roof_hits'])
                if height==1.:
                    self.assertEqual('not_in_final_contact_set',trace['rejected_points'][0]['reason'])
                    self.assertAlmostEqual(-.9,trace['rejected_points'][0]['compression_or_gap'])
                if hits and height==0.:
                    self.assertAlmostEqual(hits[0][2][0],trace['points'][0]['nearest']['distance_xz'])


class LocalSelectionReceiptTests(unittest.TestCase):
    def scene(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        state=dict(request_key=(('local',28), (6,6)),replan_generation=0)
        nav.bot_states[28]=state
        return nav,state

    def test_final_refusal_and_selection_are_identified_without_changing_outputs(self):
        current=(6.,0.,6.);candidate=(10.,0.,6.);goal=(30.,0.,6.)
        for mode in ('selected','temporary_path_repeats','connector_rejected','retired_target','no_candidate'):
            with self.subTest(mode=mode):
                nav,state=self.scene()
                origin=current
                target=candidate
                expected=candidate
                if mode=='temporary_path_repeats':
                    state.update(temporary_stalled=True,temporary_visited_cells={nav.grid.cell_for(candidate)})
                    expected=current
                elif mode=='connector_rejected':origin=(7.,0.,6.);expected=current
                elif mode=='retired_target':state['local_target_retired']=(candidate,30.);expected=None
                elif mode=='no_candidate':target=None;expected=None
                with mock.patch.object(nav.grid,'safe_local_target',return_value=target), \
                        mock.patch.object(nav.grid,'dry_segment_clear',return_value=mode!='connector_rejected'):
                    result=nav._new_local_fallback(28,current,origin,goal,5.,(),state)
                self.assertEqual(expected,result)
                receipt=state['local_selection']
                self.assertEqual(mode,receipt['outcome'])
                self.assertEqual(target,receipt['candidate'])
                self.assertEqual(5.,receipt['at'])

    def test_retained_target_receipt_replaces_an_older_refusal(self):
        nav,state=self.scene();state['local_selection']=dict(outcome='stale')
        with mock.patch.object(nav,'_retained_local_fallback',return_value=(10.,0.,6.)):
            result=nav._safe_fallback_target(28,(6.,0.,6.),(30.,0.,6.),10.,(),state)
        self.assertEqual((10.,0.,6.),result)
        self.assertEqual('retained',state['local_selection']['outcome'])
        self.assertEqual(10.,state['local_selection']['at'])


if __name__=='__main__':unittest.main()
