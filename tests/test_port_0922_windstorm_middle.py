"""The upstream city bridge is additive, bidirectional and still rejects water."""
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'src/res/scripts/client')]
from verify_windstorm_middle_mesh import CASES
from gui.mods.offline_lan_0922 import prebaked_navigation as pn
from gui.mods.offline_lan_0922.ai.navigation import TerrainGrid


class MiddleBridgeTests(unittest.TestCase):
    def test_rebake_retains_input_and_rollback_base_profile_identities(self):
        import hashlib
        from build_windstorm_middle_mesh import retain_profile_identities
        base = json.dumps({'navigation_previous_sha256s': ['base_ancestor']}).encode()
        previous = json.dumps({'navigation_previous_sha256s': ['input_ancestor'],
                               'navigation_previous_sha256': 'single_ancestor'}).encode()
        graph = json.loads(base)
        retain_profile_identities(graph, previous, base)
        self.assertEqual(set(['base_ancestor', 'input_ancestor', 'single_ancestor',
            hashlib.sha256(base).hexdigest(), hashlib.sha256(previous).hexdigest()]),
            set(graph['navigation_previous_sha256s']))

    def test_published_windstorm_profiles_load_without_losing_route_edits(self):
        import copy
        from gui.mods.offline_lan_0922 import bot_tactics as cfg
        for identity in (
                'f0700b11ba30223ef55e9095fae31d318c0c3dc358b8c1601aa0d7f896576a23',
                '628e72bd770e5e0530faaeb4a21dee1df53f9efdbb94397871c3c75cc69f4bf0',
                'cda6076246a291d79b7ede5b2abaee3d08fc805974c048524ff865461d91f060'):
            profile = cfg.default_profile()
            entry = profile['maps']['84_winter']
            entry['resource_sha256'] = identity
            entry['default_routes'][0]['disabled'] = True
            expected = copy.deepcopy(entry)
            # Disabled travel follows the matching shared path and owns no waits.
            for row in expected['default_routes']:
                if not row.get('disabled'):continue
                shared=next(r for r in expected['default_routes'] if r['team']==row['team']
                    and r['id']==row['id'] and r.get('class_tag','all')=='all')
                row['points']=[p[:2]+[0] for p in shared['points']]
            expected['resource_sha256'] = cfg.MAPS['84_winter']['resource_sha256']
            self.assertEqual(expected, cfg.canonical(profile)['maps']['84_winter'])
        entry['resource_sha256'] = '0'*64
        with self.assertRaises(cfg.TacticsError):
            cfg.canonical(profile)

    def test_recorded_vk_bank_steps_agree_with_final_motion_guard(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        for start, yaw, distance in (
                ((137.23083470742873, -8.724451541900635, -155.67042578069092), -1.937706704805682, 1.),
                ((135.50522838075153, -8.81385612487793, -144.03357949681367), -1.4850764059541883, .06)):
            end = (start[0]+math.sin(yaw)*distance, start[1], start[2]+math.cos(yaw)*distance)
            self.assertFalse(grid.segment_has_motion_hazard(start, end, 13))
            self.assertTrue(pn.pose_is_safe(graph, end, hazard_mask=pn.MOTION_FATAL_HAZARDS))

    def test_native_exit_cannot_admit_a_runtime_shore_veto(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda x,z,y:y, lambda *a: False, baked_graph=graph)
        patch = graph['local_meshes'][2]
        for i, mask in enumerate(patch['hazards']):
            if mask & pn.SHORE_EDGE:
                end = (patch['origin'][0]+i%patch['width'], -9., patch['origin'][1]+i//patch['width'])
                start = (end[0]-1., -9., end[2])
                if grid.segment_has_motion_hazard(start, end, pn.MOTION_FATAL_HAZARDS):
                    evidence = {}
                    self.assertFalse(grid._live_baked_egress_clear(start, end, evidence=evidence))
                    self.assertEqual('hazard_or_unavailable', evidence['egress_reason'])
                    break
        else:
            self.fail('No retained shoreline veto exercised')

    def test_clearance_weight_uses_the_vertices_actual_metres(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        for number, patch in enumerate(graph['local_meshes']):
            for i, key in enumerate(grid._local_meshes.keys[number]):
                if key[0] < 0 and patch['heights_mm'][i] is not None:
                    missing = 8-grid._baked_link_count(key)
                    self.assertAlmostEqual(missing*patch['cell_size']*.2, grid._baked_clearance_penalty(key))
        for key in ((125, 125), (161, 88)):
            if grid._baked_index(key) is not None:
                self.assertAlmostEqual((8-grid._baked_link_count(key))*4.*.2, grid._baked_clearance_penalty(key))

    def test_reverse_shortcut_cannot_skip_a_fine_shore_corner(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        first, last = (134., -8.765, -158.), (128., -8.673, -163.)
        # The former 6 m apron here was not a physical cliff. Exercise the
        # traversal/cache contract with an explicit hazardous fine cell instead
        # of requiring that disproved apron to remain blocked in the map.
        cell = grid._motion_segment_cells(first, last)[2]
        patch = graph['local_meshes'][-cell[0]-1]
        patch['hazards'] = list(patch['hazards'])
        patch['hazards'][cell[1]] = 9
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        self.assertTrue(grid.segment_has_motion_hazard(first, last, 9))
        self.assertFalse(grid.segment_clear(first, last))
        # Two rays with the same nearest endpoint cells must not share the
        # coarse corridor cache when their sub-cell boundary crossings differ.
        for offset in (.01, .21, -.21):
            a = (first[0]+offset, first[1], first[2])
            b = (last[0], last[1], last[2]+offset)
            if grid.segment_has_motion_hazard(a, b, 9):
                self.assertFalse(grid.segment_clear(a, b))

    def test_bridge_mouths_are_bidirectional_and_retain_shore_guards(self):
        graph = pn.with_shore_hazards(json.loads((ROOT/'navgraphs/84_winter.json').read_bytes()))
        self.assertEqual(3, len(graph['local_meshes']))
        grid = TerrainGrid(lambda *a: None, baked_graph=graph)
        for a, b in CASES:
            for start, end in ((a, b), (b, a)):
                path = grid.plan(start, end, max_expansions=20000)
                self.assertTrue(path)
                self.assertLess(math.hypot(path[-1][0]-end[0], path[-1][2]-end[2]), 2.)
                for first, last in zip(path, path[1:]):
                    self.assertTrue(grid.segment_clear(first, last))
                    self.assertFalse(grid.segment_has_motion_hazard(first, last, 13))
        patch = graph['local_meshes'][2]
        for i, mask in enumerate(patch['hazards']):
            if mask & 9:
                point = (patch['origin'][0]+i%patch['width']*patch['cell_size'], 0., patch['origin'][1]+i//patch['width']*patch['cell_size'])
                self.assertFalse(pn.pose_is_safe(graph, point, hazard_mask=9))
