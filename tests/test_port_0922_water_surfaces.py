"""Unculled water must match recorded #1513 rays, without HP/timer changes."""
import json
import math
from pathlib import Path
import unittest
from unittest import mock
import test_port_0922_drowning_receipts as fixture
from gui.mods.offline_lan_0922 import water_surfaces as water
from gui.mods.offline_lan_0922.water_surface_data import SURFACES


class WaterGeometryTests(unittest.TestCase):
    def test_every_supported_map_has_an_explicit_catalog_including_dry_maps(self):
        root = Path(__file__).resolve().parents[1]
        names = {json.loads(p.read_bytes()).get('map') for p in (root/'navgraphs').glob('*.json')}
        self.assertEqual(names-{None}, set(SURFACES))
        self.assertTrue(any(not rows for rows in SURFACES.values()))

    def test_all_104_recorded_native_hits_match_without_streaming_cell_mask(self):
        replay = json.loads((Path(__file__).parent/'fixtures/report191606-water-rays.json').read_bytes())
        self.assertEqual(104, len(replay['cases']))
        for case in replay['cases']:
            self.assertAlmostEqual(case['native_depth'], water.depth(replay['map'], case['point']), delta=6.e-6)

    def test_rotated_rectangle_bounds_and_forward_ray_are_not_global_water_plane(self):
        with mock.patch.dict(SURFACES, test=[(10., 5., 20., 2., 8., 0., 1.)]):
            self.assertEqual(4., water.depth('test', (17., 1., 20.)))
            self.assertEqual(-1., water.depth('test', (10., 1., 23.)))
            self.assertEqual(-1., water.depth('test', (10., -16., 20.)))
            self.assertEqual(-50., water.depth('test', (10., 55., 20.)))
            self.assertEqual(4., water.depth('test', (10., 1., 22.0005)))
            self.assertEqual(-1., water.depth('test', (10., 1., 22.002)))
        self.assertIsNone(water.depth('unknown', (0., 0., 0.)))


class UnculledAuthorityTests(fixture.DrowningReceiptTests):
    def test_worker_publishes_submerged_even_when_native_render_query_misses(self):
        self.battle._config = dict(map='spaces/84_winter')
        record = self.battle._records['player:1']['state']
        record.update(x=225.682, y=-18.316, z=48.716)
        world = self.battle._runtime.bigworld
        world.wg_collideWater = mock.Mock(return_value=-1.)
        self.assertTrue(self.battle._publish_player_environment(.3, 1.))
        self.sender.assert_called_once_with([dict(player_id=1, input_seq=12, level=2)], 1)
        ready = next(row for tag, row in self.rows if row['reason']=='observation_ready')
        self.assertEqual('compiled_water_rectangles', ready['sample']['water']['source'])
        comparison = ready['query_environment']['compiled_comparison']
        self.assertEqual(-1., comparison['native_depth'])
        self.assertGreater(comparison['selected_depth'], 2.8)

    def test_worker_and_visible_physics_use_identical_depth_without_native_queries(self):
        self.battle._config = dict(map='84_winter')
        world = self.battle._runtime.bigworld
        world.wg_collideWater = mock.Mock(side_effect=AssertionError('render query used'))
        values = []
        for worker in (False, True):
            self.battle._worker_mode = worker
            receipt = {}
            values.append(self.battle._water_depth((225.1, -18.3163, 48.628), receipt))
            self.assertEqual('compiled_water_rectangles', receipt['source'])
        self.assertEqual(values[0], values[1])
        self.assertGreater(values[0], 3.)
        world.wg_collideWater.assert_not_called()
