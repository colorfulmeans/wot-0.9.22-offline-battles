import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.driver import LocalDriver

class DriverSideCommitTests(unittest.TestCase):
    def test_clear_obstacle_side_survives_symmetric_replanning(self):
        driver=LocalDriver()
        state=driver._state(1,0,(0.,0.,0.))
        first=driver._choose_yaw(state,0.,lambda yaw: abs(yaw)>.5)
        side=state['escape_side']
        state['clock']+=.3
        second=driver._choose_yaw(state,.05,lambda yaw: abs(yaw)>.5)
        self.assertGreater((second-.05)*side,0.)
        self.assertGreater(state['escape_side_until'],state['clock'])
    def test_real_veto_can_override_the_committed_side(self):
        driver=LocalDriver()
        state=driver._state(1,0,(0.,0.,0.))
        first=driver._choose_yaw(state,0.,lambda yaw: abs(yaw)>.5)
        second=driver._choose_yaw(state,0.,lambda yaw: yaw*first<0.)
        self.assertLess(first*second,0.)
