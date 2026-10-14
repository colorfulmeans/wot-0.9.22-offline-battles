"""Real three-dimensional world normals own impact HP, never X/Z constraint normals."""
import math
import unittest
from unittest import mock
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
import test_port_0922_battle_runtime as players

class SlopeImpactTests(unittest.TestCase):
    def test_reported_nearly_upward_normal_does_not_turn_road_speed_into_impact(self):
        normal=(-.019139670190476604,.9968812650520577,.0765598877559855)
        runtime=object.__new__(BotRuntime)
        runtime._apply_bot_fall_damage=mock.Mock(return_value=10)
        state=dict(id=5,yaw=2.56,vertical_speed=-2.,airborne=True,
            _world_contact_trace=dict(hit=(157.995,-14.781,187.038),normal=normal))
        self.assertEqual(0,runtime._apply_world_contact_impact(state,12.69718764873187,100.))
        runtime._apply_bot_fall_damage.assert_not_called()
        battle=players.BattleRuntime(players._runtime())
        battle._local_airborne=True;battle._local_vertical_speed=-2.;battle._clock=lambda:100.
        battle._apply_fall_damage=mock.Mock(return_value=10)
        self.assertLess(battle._apply_world_contact_impact(object(),dict(hit=(0.,0.,0.),normal=normal),12.69718764873187,2.56),10.)
        battle._apply_fall_damage.assert_not_called()

    def test_actual_wall_and_roof_impacts_keep_their_normal_closing_speed(self):
        for yaw,vertical,normal,speed in ((0.,0.,(0.,0.,-1.),20.),(0.,20.,(0.,-1.,0.),0.)):
            runtime=object.__new__(BotRuntime)
            runtime._apply_bot_fall_damage=mock.Mock(return_value=10)
            state=dict(id=5,yaw=yaw,vertical_speed=vertical,airborne=True,
                _world_contact_trace=dict(hit=(0.,0.,0.),normal=normal))
            self.assertEqual(10,runtime._apply_world_contact_impact(state,speed,100.))
            runtime._apply_bot_fall_damage.assert_called_once_with(state,20.)

if __name__=='__main__':unittest.main()
