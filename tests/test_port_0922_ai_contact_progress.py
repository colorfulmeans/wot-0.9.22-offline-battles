"""Native perception must retain the complete release Bot control owners."""
from pathlib import Path
import copy
import sys
import types
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'))
from gui.mods.offline_lan_0922.ai.driver import LocalDriver
from gui.mods.offline_lan_0922.ai.traffic import TrafficCoordinator
from gui.mods.offline_lan_0922.native_control_core import NativeControl
from gui.mods.offline_lan_0922.radio import RadioNetwork

class ContactProgressTests(unittest.TestCase):
    def owner(self,driver):
        runtime=types.SimpleNamespace(adapter=types.SimpleNamespace(driver=driver),
            _traffic_coordinator=TrafficCoordinator(),_radio_network=RadioNetwork(),round_id=1)
        owner=NativeControl(runtime,types.SimpleNamespace(),1)
        self.addCleanup(owner.detach)
        return runtime,owner

    def test_native_perception_does_not_replace_release_control_owners(self):
        driver=LocalDriver()
        state=driver._state(11,0,(0.,0.,0.))
        state.update(navigation_wait={'active':True,'age':4.},
                     translation_escape={'distance':2.},
                     objective_progress={'distance':15.})
        runtime,owner=self.owner(driver)
        before=copy.deepcopy(driver.states)
        self.assertIs(runtime.adapter.driver,driver)
        self.assertIs(owner.driver,driver)
        self.assertIs(owner.traffic,runtime._traffic_coordinator)
        owner.detach()
        self.assertEqual(before,driver.states)

    def test_installed_perception_keeps_slope_braking_and_command_history(self):
        reference=LocalDriver();actual=LocalDriver()
        runtime,owner=self.owner(actual)
        for index in range(30):
            args=(11,0,(0.,0.,0.),0.,4.,.1,(20.,20.,20.),(),lambda *unused:True)
            expected=reference.drive(*args)
            command=runtime.adapter.driver.drive(*args)
            self.assertEqual(expected,command)
            self.assertEqual(reference.states,actual.states)
        owner.detach()
        self.assertEqual(reference.states,actual.states)

    def test_detach_retains_parking_traffic_and_recovery_state(self):
        runtime,owner=self.owner(LocalDriver())
        runtime.adapter.driver._state(11,0,(0.,0.,0.))['recovery_time']=.85
        traffic=runtime._traffic_coordinator
        traffic._pairs[(11,12)]={'mode':'head_on','blocked_until':4.,'targets':{11:1.,12:-1.}}
        traffic._held[11]=1.
        before=copy.deepcopy((traffic._pairs,traffic._held,runtime.adapter.driver.states))
        owner.detach();owner.detach()
        self.assertIs(traffic,runtime._traffic_coordinator)
        self.assertEqual(before,(traffic._pairs,traffic._held,runtime.adapter.driver.states))

if __name__=='__main__':unittest.main()
