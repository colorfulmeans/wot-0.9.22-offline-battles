"""SPG proof freshness separates canonical target motion from aiming bias."""
import copy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src/res/scripts/client')]
from test_port_0922_bot_ammo import _load_bot_runtime


class ArtilleryMotionReferenceTests(unittest.TestCase):
    def setUp(self):
        self.module=_load_bot_runtime()
        self.runtime=self.module.BotRuntime(1)
        self.events=[]
        self.runtime._record_artillery_transition=lambda bot,reason,now,evidence: self.events.append((reason,evidence))

    def test_stationary_report_target_accepts_both_recorded_gunner_offsets(self):
        point=(-422.6289288845398,2.0395278930664062,386.06598017109485)
        for aim in [(-423.0925993715598,2.8056080746843257,381.12494008719875),
                    (-422.4839096170486,4.198908288064899,387.61135783404745)]:
            intent=dict(created=326.321,solution=dict(aim_position=aim),
                        target_motion_reference=dict(position=point,velocity=(0.,0.,0.),prediction_seconds=0.))
            before=copy.deepcopy(intent)
            target=dict(position=point,velocity=(0.,0.,0.))
            self.assertFalse(self.runtime._reject_stale_artillery_receipt(
                dict(id=30),target,{},0,intent,dict(flight_time=2.85153),326.632))
            self.assertEqual(before,intent)
            reason,evidence=self.events[-1]
            self.assertEqual('aim_receipt_current',reason)
            self.assertAlmostEqual(0.,evidence['error_metres'])
            self.assertGreater(evidence['raw_aim_error_metres'],1.5)
            self.assertNotEqual((0.,0.,0.),evidence['frozen_aim_offset'])

    def test_real_motion_is_rejected_even_when_it_moves_toward_biased_aim(self):
        intent=dict(created=1.,solution=dict(aim_position=(5.,1.,100.)),
                    target_motion_reference=dict(position=(0.,0.,100.),velocity=(0.,0.,0.)))
        target=dict(position=(5.,0.,100.),velocity=(0.,0.,0.))
        proof=dict(deadline=61.,absolute_deadline=121.)
        self.runtime._active_artillery_reproof=lambda *unused:proof
        cancelled=[]
        self.runtime._cancel_artillery_intent=lambda *a,**kw:cancelled.append(kw)
        self.assertTrue(self.runtime._reject_stale_artillery_receipt(
            dict(id=30),target,{},0,intent,dict(flight_time=1.),2.))
        evidence=cancelled[-1]['evidence']
        self.assertAlmostEqual(0.,evidence['raw_aim_error_metres'])
        self.assertAlmostEqual(5.,evidence['error_metres'])
        self.assertEqual(1,proof['attempts'])

    def test_predicted_queue_motion_and_deliberate_lead_error_are_separate(self):
        # Real speed is 8 m/s; imperfect leading intentionally aims elsewhere.
        intent=dict(created=1.,solution=dict(aim_position=(30.,3.,100.)),
                    target_motion_reference=dict(position=(0.,0.,100.),
                                                 velocity=(8.,0.,0.),prediction_seconds=.5))
        target=dict(position=(4.,0.,100.),velocity=(8.,0.,0.))
        self.assertFalse(self.runtime._reject_stale_artillery_receipt(
            dict(id=30),target,{},0,intent,dict(flight_time=2.),1.5))
        self.assertEqual(0.,self.events[-1][1]['error_metres'])
        self.assertGreater(self.events[-1][1]['raw_aim_error_metres'],1.5)

    def test_aimed_target_retains_unmodified_canonical_motion(self):
        self.runtime._gun_states[11]=types.SimpleNamespace(fully_aimed_dispersion=.03)
        self.runtime._gunnery_error=lambda *a:dict(lead_scale=.75)
        target=dict(position=(0.,0.,100.),velocity=(8.,0.,0.))
        original=copy.deepcopy(target)
        with mock.patch.object(self.module.bot_gunnery,'aim_offset_metres',return_value=(4.,2.)):
            aimed=self.runtime._aimed_target(dict(id=11,x=0.,y=0.,z=0.),target,1.)
        self.assertEqual(original,target)
        self.assertEqual((4.,2.,100.),aimed['position'])
        self.assertEqual((6.,0.,0.),aimed['velocity'])
        self.assertEqual(dict(position=(0.,0.,100.),velocity=(8.,0.,0.)),aimed['_canonical_motion'])

    def test_strategic_controller_freezes_canonical_reference_with_queued_arc(self):
        from test_port_0922_artillery_controller import _descriptor
        from gui.mods.offline_lan_0922.artillery_controller import ArtilleryController
        controller=ArtilleryController()
        target=dict(kind='human',network_id=2,position=(4.,2.,560.),velocity=(6.,0.,0.),
                    _canonical_motion=dict(position=(0.,0.,560.),velocity=(8.,0.,0.)))
        # Producer metadata must be frozen when the arc is created, before
        # the asynchronous world query can finish against a newer contact.
        candidates=controller._candidates(dict(id=11,x=0.,y=0.,z=0.),target,_descriptor(),0)
        self.assertTrue(candidates)
        expected=dict(position=(0.,0.,560.),velocity=(8.,0.,0.),prediction_seconds=0.)
        self.assertTrue(all(c['target_motion_reference']==expected for c in candidates))

if __name__=='__main__':unittest.main()
