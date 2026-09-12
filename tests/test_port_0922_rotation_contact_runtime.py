"""Both control adapters must respect the same swept hull rotation limit."""
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as local
import test_port_0922_bot_runtime as bots


class PlayerRotationContactTests(unittest.TestCase):
    def test_side_contact_limits_both_turn_signs_and_releases_after_separation(self):
        for direction in (-1., 1.):
            with self.subTest(direction=direction):
                runtime = local._runtime()
                battle = local.BattleRuntime(runtime)
                battle.client = local._Client()
                battle._avatar = runtime.bigworld.avatar
                entity = local._Vehicle(10, local._Descriptor(), local._Vector(),
                                        (0, 0, 0), {'health': 500})
                runtime.bigworld.entities[10] = entity
                battle._server = types.SimpleNamespace(vehicle_id=10)
                battle._sender = types.SimpleNamespace(
                    forward=0., turn=direction, handbrake=False,
                    send_current=mock.Mock(return_value=True))
                battle._local_descriptor = entity.typeDescriptor
                battle._attach_local_presentation()
                shape = battle._collision_shape(entity.typeDescriptor)
                peer = dict(id=1000001, x=2*shape[0], y=0., z=0.,
                            yaw=0., shape=shape)
                battle._contact_tanks = lambda *args: [peer]
                battle._smoothed_drive_pitch = lambda *args: 0.
                battle._update_vertical_motion = lambda e, p, y, dt: p
                battle._ground_pitch = lambda *args: 0.
                battle._apply_slope_slide = lambda p, y, dt, e=None: p
                battle._resolve_local_tank_contacts = lambda e, p, y, dt: p
                with mock.patch.object(local.vehicle_physics, 'longitudinal_step', return_value=0.), \
                        mock.patch.object(local.vehicle_physics, 'traverse_step', return_value=2*direction):
                    battle._drive_local(.1)
                    stopped = battle._local_yaw
                    self.assertGreater(stopped*direction, 0.)
                    self.assertLess(abs(stopped), .011/shape[1])
                    self.assertEqual(0., battle._local_turn_speed)
                    peer['x'] = 100.
                    battle._drive_local(.1)
                self.assertAlmostEqual(.2*direction, battle._local_yaw-stopped)


class BotRotationContactTests(unittest.TestCase):
    setUp = bots.BotRuntimeTests.setUp
    tearDown = bots.BotRuntimeTests.tearDown

    def test_player_side_contact_limits_both_bot_turn_signs_and_releases(self):
        for direction in (-1., 1.):
            with self.subTest(direction=direction):
                command = bots.BotRuntimeTests._stationary_command()
                command.update(turn=direction, target_yaw=direction,
                               movement_intent=True, recovery_mode='drive')
                runtime = self.module.BotRuntime(
                    1, descriptor_resolver=lambda unused: bots._combat_descriptor(),
                    adapter_factory=lambda *args, **kwargs: bots._FixedAdapter(command),
                    direction_probe=lambda *args: {'clear': True, 'slope': 0.},
                    ground_probe=lambda *args: 0., physics_ground_probe=lambda *args: 0.,
                    spawn_resolver=bots._spawn_resolver, baked_graph=bots._graph())
                runtime.battle_start(self.start)
                state = runtime.states[11]
                state.update(x=0., y=0., z=0., yaw=0., speed=0., grounded_once=True)
                shape = state['collision_shape']
                peer = dict(id=1, x=2*shape[0], y=0., z=0., yaw=0.,
                            half_width=shape[0], half_length=shape[1],
                            shape=shape, mass=state['mass'], speed=0., alive=True)
                with mock.patch.object(self.module.vehicle_physics, 'longitudinal_step', return_value=0.), \
                        mock.patch.object(self.module.vehicle_physics, 'traverse_step', return_value=2*direction):
                    runtime.update(.04, 1., neighbours=[peer])
                    stopped = state['yaw']
                    self.assertGreater(stopped*direction, 0.)
                    self.assertLess(abs(stopped), .011/shape[1])
                    self.assertEqual(0., runtime._turn_speeds[11])
                    peer['x'] = 100.
                    runtime.update(.04, 1.04, neighbours=[peer])
                self.assertAlmostEqual(.08*direction, state['yaw']-stopped)
