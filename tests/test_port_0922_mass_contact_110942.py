"""Static track reaction must also own geometric contact recovery."""
import math
import types
import unittest

import test_port_0922_battle_runtime as local
import test_port_0922_bot_runtime as bots
from test_port_0922_tank_collision import _tank, tank_collision as contact
from gui.mods.offline_lan_0922 import vehicle_physics as drive


class GroundedMassContactTests(unittest.TestCase):
    def pair(self, dt):
        # Report 110942 round 2: the installed VK 28.01 and KV-5 masses.
        heavy = _tank(1, 0., 0., mass=100575.)
        light = _tank(15, -2.9, 0., mass=26183., vx=2. * dt)
        for body in (heavy, light):
            body['contact_decel'] = drive.contact_push_decel(
                dict(drive._DEFAULTS, mass=body['mass']), False)
        return heavy, light

    def test_pair_iterations_cannot_move_a_hull_the_first_iteration_held(self):
        for dt in (1. / 15., 1. / 30., 1. / 120.):
            heavy, light = self.pair(dt)
            result = contact.resolve_pairs([heavy, light], dt)
            self.assertEqual((0., 0.), result[1]['delta_velocity'])
            self.assertEqual((0., 0.), result[1]['correction'])
            self.assertLess(result[15]['correction'][0], 0.)
            self.assertAlmostEqual(-light['vx'], result[15]['delta_velocity'][0])
            self.assertEqual((15,), result[1]['grounded_contacts'])
            self.assertNotIn('grounded_contacts', heavy)

    def test_stopped_peer_pose_cannot_reintroduce_position_only_shove(self):
        for dt in (1. / 30., 1. / 120.):
            heavy, light = self.pair(dt)
            first = contact.resolve_tank(heavy, [light], dt=dt)
            heavy['grounded_contacts'] = first['grounded_contacts']
            light['vx'] += first['responses'][0][1][0]
            for unused in range(8):
                # A pending reciprocal impulse stops the peer before its
                # replicated, overlapping presentation pose catches up.
                result = contact.resolve_tank(heavy, [light], dt=dt)
                self.assertEqual((0., 0.), result['correction'])
                self.assertEqual((0., 0.), result['delta_velocity'])
                heavy['grounded_contacts'] = result['grounded_contacts']

    def test_stationary_ground_reaction_also_absorbs_bounded_hull_friction(self):
        heavy, light = self.pair(1. / 30.)
        light['vz'] = .8
        heavy['yaw'] = .01
        result = contact.resolve_tank(heavy, [light], dt=1. / 30.)
        self.assertEqual((0., 0.), result['correction'])
        self.assertEqual((0., 0.), result['delta_velocity'])
        # The moving light hull still receives the reciprocal contact load.
        self.assertLess(result['responses'][0][1][0], 0.)
        self.assertLess(result['responses'][0][1][1], 0.)

    def test_hold_expires_on_separation_airborne_movement_and_overload(self):
        for change in ('separated', 'airborne', 'moving', 'overload'):
            heavy, light = self.pair(1. / 30.)
            heavy['grounded_contacts'] = (15,)
            if change == 'separated':
                light['x'] = -20.
            elif change == 'airborne':
                heavy['contact_decel'] = None
            elif change == 'moving':
                heavy['vx'] = .03
            else:
                light['vx'] = 20.
            result = contact.resolve_tank(heavy, [light], dt=1. / 30.)
            self.assertEqual((), result['grounded_contacts'])
            if change != 'separated':
                self.assertGreater(math.hypot(*result['correction']), 0.)
        heavy, light = self.pair(1. / 30.)
        heavy['grounded_contacts'] = (15,)
        light['vx'] = -.1
        leaving = contact.resolve_tank(heavy, [light], dt=1. / 30.)
        self.assertEqual((15,), leaving['grounded_contacts'])
        self.assertEqual((0., 0.), leaving['correction'])
        self.assertEqual((0., 0.), leaving['delta_velocity'])

    def test_new_stationary_spawn_overlap_keeps_mass_weighted_recovery(self):
        heavy, light = self.pair(1. / 30.)
        light['vx'] = 0.
        result = contact.resolve_pairs([heavy, light], 1. / 30.)
        self.assertGreater(result[1]['correction'][0], 0.)
        self.assertLess(result[15]['correction'][0], 0.)
        self.assertAlmostEqual(
            -result[15]['correction'][0] / result[1]['correction'][0],
            heavy['mass'] / light['mass'])
        self.assertEqual((), result[1]['grounded_contacts'])

    def test_high_speed_impact_keeps_both_real_masses(self):
        heavy, light = self.pair(1. / 120.)
        heavy['grounded_contacts'] = (15,)
        light['vx'] = 20.
        result = contact.resolve_tank(heavy, [light], dt=1. / 120.)
        velocity = result['delta_velocity'][0]
        self.assertAlmostEqual(20. * light['mass'] /
                               (heavy['mass'] + light['mass']), velocity)
        self.assertAlmostEqual(0., heavy['mass'] * velocity +
                               light['mass'] * result['responses'][0][1][0])

    def test_immovable_hull_never_replays_its_stale_velocity(self):
        for speed in (-20., 20.):
            heavy, light = self.pair(1. / 30.)
            light.update(immovable=True, alive=False, vx=speed, vz=20.)
            stopped = dict(light, vx=0., vz=0.)
            self.assertEqual(
                contact.resolve_tank(heavy, [stopped], dt=1. / 30.),
                contact.resolve_tank(heavy, [light], dt=1. / 30.))


class PlayerContactHoldTests(unittest.TestCase):
    def runtime(self):
        engine = local._runtime()
        battle = local.BattleRuntime(engine)
        battle.client = local._Client()
        battle._avatar = engine.bigworld.avatar
        own_descriptor, peer_descriptor = local._Descriptor(), local._Descriptor()
        own_descriptor.physics['weight'] = 100575.
        peer_descriptor.physics['weight'] = 26183.
        entity = local._Vehicle(10, own_descriptor, local._Vector(),
                                (0, 0, 0), {'health': 500})
        peer = local._Vehicle(15, peer_descriptor, local._Vector(),
                              (0, 0, 0), {'health': 500})
        engine.bigworld.entities.update({10: entity, 15: peer})
        shape = battle._collision_shape(own_descriptor)
        battle._records['bot:15'] = dict(
            engine_id=15, network_id=15, kind='bot', ready=True,
            state=dict(id=15, x=-(shape[0] + shape[1]) + .1, y=0., z=0.,
                       yaw=math.pi / 2., speed=.04, team=1, alive=True,
                       rotation_dir=0, movement_dir=0, collision_shape=shape))
        battle._local_physics = local.vehicle_physics.derive_params(own_descriptor)
        battle._sender = types.SimpleNamespace(forward=0.)
        battle._motion_is_clear = lambda *args, **kwargs: True
        battle._baked_pose_safe = lambda *args: True
        return battle, entity

    def test_pending_peer_impulse_and_unchanged_pose_do_not_shove_parked_kv5(self):
        battle, entity = self.runtime()
        for unused in range(8):
            position = battle._resolve_local_tank_contacts(
                entity, (0., 0., 0.), 0., 1. / 30.)
            self.assertEqual((0., 0., 0.), position)
            self.assertEqual((1000015,), battle._local_grounded_contacts)
            self.assertEqual((0., 0.), (battle._local_push_x, battle._local_push_z))
        sent = battle._local_contact_pushes[15]
        self.assertAlmostEqual(-26183. * .04, sent[2])
        battle._records['bot:15']['state']['x'] = -100.
        battle._resolve_local_tank_contacts(entity, position, 0., 1. / 30.)
        self.assertEqual((), battle._local_grounded_contacts)

    def test_airborne_player_releases_static_hold_and_keeps_external_momentum(self):
        battle, entity = self.runtime()
        battle._resolve_local_tank_contacts(entity, (0., 0., 0.), 0., 1. / 30.)
        battle._local_airborne = True
        position = battle._resolve_local_tank_contacts(
            entity, (0., 0., 0.), 0., 1. / 30.)
        self.assertEqual((), battle._local_grounded_contacts)
        self.assertGreater(position[0], 0.)
        battle._records = {}
        battle._local_push_x = .5
        battle._resolve_local_tank_contacts(entity, position, 0., 1. / 30.)
        self.assertEqual(.5, battle._local_push_x)

    def test_airborne_peer_has_no_ground_grip_in_visible_contact_body(self):
        battle, entity = self.runtime()
        battle._records['bot:15']['state']['airborne'] = True
        peers = battle._contact_tanks((0., 0., 0.),
                                     battle._collision_shape(entity.typeDescriptor), .03)
        self.assertEqual(1, len(peers))
        self.assertIsNone(peers[0]['contact_decel'])


class WorkerContactHoldTests(unittest.TestCase):
    setUp = bots.ShovedWreckTests.setUp
    tearDown = bots.ShovedWreckTests.tearDown
    _runtime = bots.ShovedWreckTests._runtime

    def test_worker_carries_held_overlap_until_departure_then_expires_it(self):
        runtime = self._runtime()
        heavy, light = runtime.states[11], runtime.states[12]
        for state, mass in ((heavy, 100575.), (light, 26183.)):
            state.update(x=0., y=0., z=0., yaw=0., speed=0., mass=mass,
                         team=1, push_x=0., push_z=0., movement_dir=0,
                         rotation_dir=0, grounded_once=True)
            runtime._physics_params_for(state['id'])['mass'] = mass
        light.update(speed=.04, z=-heavy['collision_shape'][1] -
                     light['collision_shape'][1] + .1)
        runtime.contact_motion_probe = lambda *args: True
        for tick in range(8):
            runtime._resolve_tank_contacts((), 1. + tick / 30., 1. / 30.)
            self.assertEqual((0., 0.), (heavy['x'], heavy['z']))
            self.assertEqual((12,), heavy['_grounded_contacts'])
        light['x'] = 100.
        runtime._resolve_tank_contacts((), 2., 1. / 30.)
        self.assertEqual((), heavy['_grounded_contacts'])


if __name__ == '__main__':
    unittest.main()
