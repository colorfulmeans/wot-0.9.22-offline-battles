"""Sustained hull contact must spend track force, not positional teleporting."""
import math
import unittest
from test_port_0922_tank_collision import _tank, tank_collision as contact
from gui.mods.offline_lan_0922 import vehicle_physics as drive


class GroundContactTests(unittest.TestCase):
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
