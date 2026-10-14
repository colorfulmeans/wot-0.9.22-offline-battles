"""Current short physical proofs outrank expired long-direction preferences."""
import math
import unittest
from gui.mods.offline_lan_0922.ai.driver import LocalDriver

class ShortEscapeReproofTests(unittest.TestCase):
    def setup_state(self):
        d=LocalDriver();s=d._state(25,9,(341.2867,8.0569,-309.4159))
        s['clock']=12.
        for yaw in (0.,math.pi):s['failed_yaws'][d._yaw_key(yaw)]=30.
        return d,s

    def test_failed_long_heading_does_not_hide_proved_half_metre_exit(self):
        d,s=self.setup_state()
        command=d._short_escape(s,(341.2867,8.0569,-309.4159),0.,0.,.1,.1,0.,[],
            lambda yaw,distance: distance <= .5,3.,1.6)
        self.assertIsNotNone(command)
        self.assertEqual(.5,command['recovery_probe_distance'])
        self.assertEqual(0.,command['turn'])
        self.assertEqual(5,len(s['short_escape_probes']))
        retained=d._retained_short_escape(s,(341.2867,8.0569,-309.4159),0.,[],
            lambda yaw,distance: True,3.,1.6)
        self.assertIsNotNone(retained)
        self.assertIsNone(d._retained_short_escape(s,(341.2867,8.0569,-309.4159),0.,[],
            lambda yaw,distance: False,3.,1.6))

    def test_unknown_or_blocked_ground_never_permits_escape(self):
        d,s=self.setup_state()
        self.assertIsNone(d._short_escape(s,(0.,0.,0.),0.,0.,.1,.1,0.,[],
            lambda yaw,distance: False,3.,1.6))
        self.assertEqual(6,len(s['short_escape_probes']))
        self.assertFalse(any(r['clear'] for r in s['short_escape_probes']))

    def test_failed_fans_have_bounded_retry_work_and_success_keeps_live_proof(self):
        d,s=self.setup_state();calls=[]
        def probe(yaw,distance):calls.append((yaw,distance));return False
        d._short_escape(s,(0.,0.,0.),0.,0.,.1,.1,0.,[],probe,3.,1.6)
        self.assertEqual(6,len(calls))
        for time in (12.01,12.1,12.2):
            s['clock']=time
            self.assertIsNone(d._short_escape(s,(0.,0.,0.),0.,0.,.1,.1,0.,[],probe,3.,1.6))
        self.assertEqual(6,len(calls))
        s['clock']=12.25
        self.assertIsNotNone(d._short_escape(s,(0.,0.,0.),0.,0.,.1,.1,0.,[],lambda y,r:True,3.,1.6))
        self.assertIsNone(d._retained_short_escape(s,(0.,0.,0.),0.,[],lambda y,r:False,3.,1.6))
