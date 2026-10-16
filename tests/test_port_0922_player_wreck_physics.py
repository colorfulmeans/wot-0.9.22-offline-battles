"""The dead player's body keeps gravity while controls and HP stay inactive."""
import types
import unittest
from unittest import mock
import test_port_0922_battle_runtime as f
from gui.mods.offline_lan_0922 import vehicle_physics, vehicle_stack


class PlayerWreckPhysicsTests(unittest.TestCase):
    def test_dead_113_continues_falling_after_the_fatal_contact(self):
        runtime=f._runtime()
        battle=f.BattleRuntime(runtime)
        battle.client=f._Client()
        battle._avatar=runtime.bigworld.avatar
        entity=f._Vehicle(10,f._suspension_descriptor(),f._Vector(),(0,0,0),{'health':0})
        runtime.bigworld.entities[10]=entity
        battle._server=types.SimpleNamespace(vehicle_id=10)
        battle._sender=types.SimpleNamespace(forward=1.,turn=1.,send_current=mock.Mock())
        battle._local_descriptor=entity.typeDescriptor
        battle._local_physics=vehicle_physics.derive_params(entity.typeDescriptor)
        battle._local_position=(40.3864,-10.9108,65.0813)
        battle._local_vertical_speed=-15.666743289
        battle._local_airborne=True
        battle._local_fall_armed=True
        # Native ground/peer answers are absent after the carrier moves away.
        # The real vertical integrator and passive body step still execute.
        battle._suspension_ground_y=lambda *args,**kwargs:None
        battle._ground_y=lambda *args,**kwargs:None
        battle._contact_tanks=lambda *args,**kwargs:[]
        battle._native_world_rotation_is_clear=lambda *args,**kwargs:True
        battle._update_local_presentation=mock.Mock()
        before=battle._local_position
        battle._drive_local(.1)
        first=battle._local_position
        battle._drive_local(.1)
        self.assertLess(first[1],before[1])
        self.assertLess(battle._local_position[1],first[1])
        self.assertTrue(battle._local_wreck_active)
        self.assertEqual(0,entity.health)
        self.assertEqual((0.,0.),(battle._sender.forward,battle._sender.turn))
        self.assertFalse(battle._apply_fall_damage(entity,50.))

    def test_auxiliary_roof_pair_exemptions_are_removed(self):
        self.assertFalse(hasattr(vehicle_stack,'roof_contact_pairs'))
        self.assertFalse(hasattr(f.BattleRuntime,'_falling_roof_approaches'))


if __name__=='__main__':unittest.main()
