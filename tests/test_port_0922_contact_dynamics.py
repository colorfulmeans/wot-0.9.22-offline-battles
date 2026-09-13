"""Sustained hull contact must spend track force, not positional teleporting."""
import math
import unittest
from unittest import mock
from test_port_0922_tank_collision import _tank, tank_collision as contact
from gui.mods.offline_lan_0922 import vehicle_physics as drive


class GroundContactTests(unittest.TestCase):
    def test_turning_a_pinned_hull_spends_mass_and_engine_power_for_either_owner(self):
        for dt in (1./15, 1./30, 1./60):
            for actor in (1, 1000001):
                for mass, power, peer_mass, moves in (
                        (20000., 300., 100000., False),
                        (100000., 2000., 10000., True),
                        (100000., 20., 10000., False)):
                    for sign in (-1., 1.):
                        params = dict(drive._DEFAULTS, mass=mass, powerW=power*735.49875)
                        a, b = _tank(actor, 0., 0., mass=mass), _tank(3, 3., 0., mass=peer_mass)
                        a['traverse_speed'], a['traverse_torque'] = drive.contact_traverse(
                            params, 1.5, 0., sign, dt)
                        for value in (a, b):
                            value['contact_decel'] = drive.contact_push_decel(
                                dict(params, mass=value['mass']), False)
                        delta = contact.traverse_impulses([a, b], dt)[3]
                        pushed = drive.contact_push_step(dict(params, mass=peer_mass),
                                                          delta[0], delta[1], 0., dt)
                        self.assertEqual(moves, pushed[0] > 0.)
                        self.assertEqual(0., pushed[1])

    def test_turn_reaction_is_reciprocal_and_cannot_send_multiple_full_torque_budgets(self):
        a = _tank(1, 0., 0., mass=50000.)
        a.update(traverse_speed=.6, traverse_torque=300000.)
        peers = [_tank(2, 3., 0., mass=10000.), _tank(3, -3., 0., mass=10000.)]
        result = contact.traverse_impulses([a]+peers, .04)
        self.assertAlmostEqual(0., sum(t['mass']*result[t['id']][0] for t in [a]+peers))
        spent = sum(abs(result[b['id']][0])*b['mass']*3.5 for b in peers)
        self.assertGreater(spent, 0.)
        self.assertLessEqual(spent, a['traverse_torque']*.04+1e-8)
        a['traverse_torque'] = 0.
        self.assertTrue(all(v == (0., 0.) for v in contact.traverse_impulses([a]+peers, .04).values()))

    def test_clear_recovery_arc_is_pruned_without_losing_an_interior_contact(self):
        shape = (1.5, 3.5, -.8, 2.)
        peer = _tank(2, 0., 7.6)
        with mock.patch.object(contact, '_obb_overlap', wraps=contact._obb_overlap) as sat:
            self.assertEqual(1., contact.rotation_fraction((0., 0., 0.), 0., .85, shape, [peer]))
        self.assertLess(sat.call_count, 100)
        peer['x'], peer['z'] = 5., 0.
        self.assertLess(contact.rotation_fraction((0., 0., 0.), 0., math.pi/2, shape, [peer]), 1.)

    def test_hostile_side_contact_overrides_firing_hold_and_preserves_combat_target(self):
        from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
        from gui.mods.offline_lan_0922.ai.driver import combat_hull_aim
        adapter = BotAdapter('test', 1)
        peer = dict(id=2, team=2, position=(2.99, 0., 0.), shape=(1.5, 3.5, -.8, 2.),
                    half_width=1.5, half_length=3.5, alive=True)
        state = dict(id=1, slot=0, team=1, position=(0., 0., 0.), yaw=0., speed=0.,
                     dt=.1, half_width=1.5, half_length=3.5, neighbours=[peer], pose_clear=lambda yaw: False)
        strategic = dict(target_id=2, aim_position=(3., 0., 0.), move_position=(0., 0., 0.),
                         face_position=(3., 0., 0.), combat_mode='engage', fire_allowed=True, throttle_override=0.)
        commands = [adapter.decide_with_order(state, strategic, lambda *args: True) for _ in range(40)]
        self.assertTrue(all(c['movement_intent'] and c['fire_allowed'] and c['target_id'] == 2 for c in commands))
        self.assertTrue(any(c['throttle'] > 0. for c in commands))
        self.assertTrue(any(c['throttle'] < 0. for c in commands))
        for command in commands:
            turn, throttle, aiming = combat_hull_aim(0., math.pi/2, -.1, .1,
                command['turn'], command['throttle'], command['recovery_mode'])
            self.assertFalse(aiming)
            self.assertEqual(command['throttle'], throttle)
        peer['position'] = (3.1, 0., 0.)
        self.assertTrue(adapter.decide_with_order(state, strategic, lambda *a: True)['movement_intent'])
        peer['position'] = (10., 0., 0.)
        self.assertFalse(adapter.decide_with_order(state, strategic, lambda *a: True)['movement_intent'])
        peer.update(position=(2.99, 0., 0.), team=1)
        self.assertFalse(adapter.decide_with_order(state, strategic, lambda *a: True)['movement_intent'])

    def test_side_hug_cannot_be_bypassed_by_repeated_traverse(self):
        shape = (1.5, 3.5, -.8, 2.)
        for actor in (1, 1000001):
            for direction in (-1., 1.):
                peer = _tank(actor, 3., 0.)
                yaw = 0.
                for unused in range(120):
                    delta = direction*.02
                    fraction = contact.rotation_fraction((0., 0., 0.), yaw, yaw+delta, shape, [peer])
                    yaw += delta*fraction
                self.assertLess(abs(yaw), .003)
                self.assertEqual(3., peer['x'])
                # The contact may open through ordinary translation, after
                # which the same command can turn. There is no sticky lease.
                peer['x'] = 10.
                self.assertEqual(1., contact.rotation_fraction((0., 0., 0.), yaw, yaw+.02, shape, [peer]))

    def test_turn_can_leave_an_existing_corner_contact(self):
        shape = (1.5, 3.5, -.8, 2.)
        peer = _tank(2, 2.99, 5.)
        self.assertEqual(1., contact.rotation_fraction((0., 0., 0.), 0., -.2, shape, [peer]))
        self.assertLess(contact.rotation_fraction((0., 0., 0.), 0., .2, shape, [peer]), .02)
        peer['y'] = 8.
        self.assertEqual(1., contact.rotation_fraction((0., 0., 0.), 0., .2, shape, [peer]))

    def test_turn_sweep_checks_between_clear_endpoint_poses(self):
        shape = (1.5, 3.5, -.8, 2.)
        peer = _tank(2, 5., 0.)
        for yaw in (0., math.pi/2):
            self.assertIsNone(contact.obb_contact(0., 0., yaw, shape, 5., 0., 0., shape))
        self.assertLess(contact.rotation_fraction((0., 0., 0.), 0., math.pi/2, shape, [peer]), 1.)

    def test_stationary_side_holds_for_either_identity_and_frame_rate(self):
        for dt in (1./15, 1./30, 1./60):
            for owner in (1, 1000001):
                a = _tank(owner, -2.9, 0, mass=20000, vx=2*dt, yaw=math.pi/2)
                b = _tank(3, 0, 0, mass=60000)
                b['contact_decel'] = (6., 6.)
                own = contact.resolve_tank(a, [b], dt=dt)
                peer = contact.resolve_tank(b, [a], dt=dt)
                self.assertEqual((0., 0.), peer['correction'])
                self.assertEqual((0., 0.), peer['delta_velocity'])
                self.assertAlmostEqual(-a['vx'], own['delta_velocity'][0])
                self.assertLess(own['correction'][0], 0)
                self.assertEqual((0., 0.), own['responses'][0][1])

    def test_same_power_cannot_push_every_mass_and_extra_power_breaks_hold(self):
        def response(mass, horsepower, target_mass, dt):
            params = dict(drive._DEFAULTS, mass=mass, powerW=horsepower*735.49875)
            speed = drive.longitudinal_step(params, 0., 1., False, 0., dt)
            a = _tank(1, -2.9, 0, mass=mass, vx=speed, yaw=math.pi/2)
            b = _tank(2, 0, 0, mass=target_mass)
            b['contact_decel'] = drive.contact_push_decel(dict(params, mass=target_mass), False)
            return contact.resolve_tank(b, [a], dt=dt)
        for dt in (1./15, 1./30, 1./60):
            weak = response(20000., 300., 100000., dt)
            stronger = response(100000., 2000., 10000., dt)
            weak_engine = response(100000., 20., 10000., dt)
            self.assertEqual((0., 0.), weak['correction'])
            self.assertEqual((0., 0.), weak_engine['correction'])
            self.assertGreater(stronger['delta_velocity'][0], 0)
            self.assertGreater(stronger['correction'][0], 0)

    def test_high_speed_impact_exceeds_static_hold_and_preserves_mass_ratio(self):
        a = _tank(1, -2.9, 0, mass=20000, vx=20)
        b = _tank(2, 0, 0, mass=60000)
        b['contact_decel'] = (6., 6.)
        result = contact.resolve_tank(a, [b], dt=1./60)
        delta = result['responses'][0][1]
        self.assertAlmostEqual(5., delta[0])
        self.assertAlmostEqual(0., 20000*result['delta_velocity'][0]+60000*delta[0])

    def test_hull_friction_is_limited_by_reviewed_normal_load(self):
        result = contact.pair_response((-1., 0., .1), 1./20000, 1./30000, (2., 10.), (0., 0.))
        normal_j = abs(result[2])*20000
        tangent_j = abs(result[3])*20000
        self.assertAlmostEqual(.3*normal_j, tangent_j)
        self.assertLess(result[3], 0)
        self.assertGreater(result[7], 0)
        self.assertAlmostEqual(0., 20000*result[3]+30000*result[7])
        scrape = contact.pair_response((-1., 0., .1), 1./20000, 1./30000, (0., 10.), (0., 0.))
        self.assertEqual((0., 0.), scrape[2:4])

    def test_three_vehicle_sweep_conserves_momentum_without_reapplying_frozen_hits(self):
        tanks = [_tank(1, -2.8, 0, mass=20000, vx=10),
                 _tank(2, 0, 0, mass=30000),
                 _tank(3, 2.8, 0, mass=50000)]
        result = contact.resolve_pairs(tanks, 1./30)
        momentum = 0.
        energy = 0.
        for tank in tanks:
            vx = tank['vx']+result[tank['id']]['delta_velocity'][0]
            vz = tank['vz']+result[tank['id']]['delta_velocity'][1]
            momentum += tank['mass']*vx
            energy += .5*tank['mass']*(vx*vx+vz*vz)
        self.assertAlmostEqual(200000., momentum)
        self.assertLessEqual(energy, 1000000.)
        self.assertGreater(result[3]['delta_velocity'][0], 0)

    def test_reverse_can_leave_front_contact_but_cannot_enter_rear_hull(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        driver = LocalDriver()
        front = dict(id=2, position=(0.,0.,6.99), yaw=0., half_length=3.5, half_width=1.5)
        rear = dict(front, id=3, position=(0.,0.,-8.))
        self.assertIsNone(driver._reverse_blocked_by_vehicle((0.,0.,0.),0.,[front],3.5,1.5))
        self.assertEqual(3, driver._reverse_blocked_by_vehicle((0.,0.,0.),0.,[front,rear],3.5,1.5))
        side = dict(front, position=(2.99,0.,1.))
        self.assertIsNone(driver._reverse_blocked_by_vehicle((0.,0.,0.),0.,[side],3.5,1.5))

    def test_reverse_keeps_a_clear_escape_straight_when_its_turn_arc_is_occupied(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        for position in ((2.99, 0., 1.), (0., 0., 6.99)):
            driver = LocalDriver()
            driver._state(1, 0, (0., 0., 0.)).update(recovery_time=.5, recovery_side=1.)
            peer = dict(id=2, position=position, yaw=0., half_length=3.5, half_width=1.5)
            order = driver.drive(1, 0, (0., 0., 0.), 0., 0., .04,
                                 (0., 0., 100.), [peer], lambda *a: True,
                                 half_width=1.5, pose_clear=lambda yaw: False)
            self.assertEqual('reverse_turn', order['recovery_mode'])
            self.assertLess(order['throttle'], 0.)
            self.assertEqual(0., order['turn'])

    def test_forward_escape_checks_the_complete_hull_path(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        side = dict(id=2, position=(2.99, 0., -1.), yaw=0., half_length=3.5, half_width=1.5)
        rear = dict(side, id=3, position=(0., 0., -8.))
        front = dict(side, id=4, position=(0., 0., 8.))
        for peers, mode in (([side, rear], 'forward_escape'), ([side, rear, front], 'blocked')):
            driver = LocalDriver()
            driver._state(1, 0, (0., 0., 0.)).update(recovery_time=.5, recovery_side=1.)
            order = driver.drive(1, 0, (0., 0., 0.), 0., 0., .04,
                                 (0., 0., 100.), peers, lambda *a: True,
                                 half_width=1.5, pose_clear=lambda yaw: False)
            self.assertEqual(mode, order['recovery_mode'])
            self.assertEqual(0., order['turn'])
            self.assertEqual(.72 if mode == 'forward_escape' else 0., order['throttle'])

    def test_contact_oscillation_cannot_renew_driver_wait_forever(self):
        from gui.mods.offline_lan_0922.ai.driver import LocalDriver
        for dt in (1./15, 1./30, 1./60):
            driver = LocalDriver()
            modes=[]
            for i in range(int(5/dt)):
                order = driver.drive(1, 0, (.05 if i%2 else -.05, 0., 0.),
                                     0., 0., dt, (0.,0.,100.), [], lambda *a: True)
                modes.append(order['recovery_mode'])
                driver.wait_for_traffic(1, dt)
            self.assertIn('reverse_turn', modes)
