"""A settled wreck edge wakes within a solve, without disturbing resting piles."""
import itertools
import unittest
from test_port_0922_tank_collision import _tank, tank_collision


class ChainTests(unittest.TestCase):
    def test_all_live_dead_chains_transmit_in_the_first_slice_for_all_ids(self):
        for alive_b, alive_c in itertools.product((True, False), repeat=2):
            for ids in itertools.permutations((1, 2, 3)):
                bodies = [_tank(actor, 0., z, vz=3. if z == 0. else 0.)
                          for actor, z in zip(ids, (0., 6.98, 13.96))]
                bodies[1]['alive'], bodies[2]['alive'] = alive_b, alive_c
                result = tank_collision.resolve_pairs(bodies, .05)
                self.assertGreater(result[ids[-1]]['delta_velocity'][1], .9,
                                   (alive_b, alive_c, ids))
                momentum = sum(b['mass'] * (b['vz'] + result[b['id']]['delta_velocity'][1]) for b in bodies)
                self.assertAlmostEqual(75000., momentum, places=6)

    def test_resting_overlapping_wrecks_remain_at_rest(self):
        bodies = [_tank(i, 0., z) for i, z in ((1, 0.), (2, 6.9), (3, 13.8))]
        for body in bodies: body['alive'] = False
        result = tank_collision.resolve_pairs(bodies, .05)
        for row in result.values():
            self.assertEqual((0., 0.), row['correction'])
            self.assertEqual((0., 0.), row['delta_velocity'])


if __name__ == '__main__': unittest.main()
