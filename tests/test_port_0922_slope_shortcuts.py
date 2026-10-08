"""Prove bounded stair shortcuts against the reported exact-client ground."""
import json
import math
import unittest
import test_port_0922_ai as fixtures
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid
from gui.mods.offline_lan_0922.prebaked_navigation import load_graph


class SlopeShortcutTests(unittest.TestCase):
    start = (-58.0, 37.498, -250.0)
    goal = (-50.0, 31.049, -238.0)

    def setUp(self):
        with open(str(fixtures.ROOT / 'tests/fixtures/el_halluf_downhill_ground_1513.json')) as source:
            self.ground = json.load(source)
        self.calls = []

    def probe(self, x, z, hint):
        self.calls.append((x, z))
        data = self.ground
        fx, fz = x - data['origin'][0], z - data['origin'][1]
        ix, iz = int(math.floor(fx)), int(math.floor(fz))
        if ix < 0 or iz < 0 or ix + 1 >= data['width'] or iz + 1 >= data['height']:
            return None
        tx, tz = fx - ix, fz - iz
        rows = data['ground']
        return ((rows[iz][ix] * (1-tx) + rows[iz][ix+1] * tx) * (1-tz) +
                (rows[iz+1][ix] * (1-tx) + rows[iz+1][ix+1] * tx) * tz)

    def grid(self, obstacle=None, ground=None):
        return TerrainGrid(ground or self.probe, obstacle or (lambda *args: False),
            baked_graph=load_graph('29_el_hallouf', str(fixtures.ROOT)))

    def test_reported_stair_path_smooths_to_a_single_supported_descent(self):
        grid = self.grid()
        path = [self.start, (-58,36.018,-246), (-54,34.996,-246),
                (-54,33.494,-242), (-50,32.502,-242), self.goal]
        self.assertFalse(grid._baked_corridor(self.start, self.goal)[0])
        self.assertEqual(grid._smooth(path), (self.start, self.goal))
        self.assertTrue(grid.dry_segment_clear(self.start, self.goal, 1.0))

    def test_successful_native_proof_is_reused(self):
        grid = self.grid()
        self.assertTrue(grid.segment_clear(self.start, self.goal))
        calls = len(self.calls)
        self.assertGreater(calls, 2)
        self.assertTrue(grid.segment_clear(self.start, self.goal))
        self.assertEqual(calls, len(self.calls))

    def test_collision_missing_ground_and_hidden_cliff_reject_shortcut(self):
        self.assertFalse(self.grid(obstacle=lambda *args: True).segment_clear(self.start, self.goal))
        self.assertFalse(self.grid(ground=lambda *args: None).segment_clear(self.start, self.goal))
        def cliff(x, z, hint):
            return self.probe(x, z, hint) + (10.0 if z > -244.0 else 0.0)
        self.assertFalse(self.grid(ground=cliff).segment_clear(self.start, self.goal))

    def test_missing_corner_link_and_water_cannot_be_relaxed(self):
        for field, value in [('_baked_links', 0), ('_baked_hazards', 1),
                             ('_baked_heights', None)]:
            grid = self.grid()
            cell = grid.cell_for((-54,0,-250))
            index = grid._baked_index(cell)
            values = list(getattr(grid, field))
            values[index] = value
            setattr(grid, field, values)
            self.assertFalse(grid.segment_clear(self.start, (-54,34.996,-246)))

    def test_native_proof_is_required_even_when_baked_square_is_supported(self):
        grid = self.grid()
        grid.obstacle_probe = None
        self.assertFalse(grid.segment_clear(self.start, self.goal))

    def test_corner_gradient_above_native_full_grip_rejects_shortcut(self):
        grid = self.grid()
        grid._baked_heights = [None if h is None else h * 2 for h in grid._baked_heights]
        self.assertFalse(grid.segment_clear(self.start, self.goal))
        self.assertEqual([], self.calls)


if __name__ == '__main__':
    unittest.main()
