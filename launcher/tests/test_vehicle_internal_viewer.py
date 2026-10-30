import base64
import struct
import unittest
import zlib

import vehicle_internal_viewer as viewer


class InteriorViewerTests(unittest.TestCase):
    def fixture(self):
        vertices = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
        blob = struct.pack('<4sII', b'IM01', 3, 1)
        blob += b''.join(struct.pack('<3d', *point) for point in vertices)
        blob += struct.pack('<3I', 0, 1, 2)
        geometry = dict(part='hull', reference_bounds=((0., 0., 0.), (1., 1., 1.)),
            payload=base64.b64encode(zlib.compress(blob)).decode('ascii'))
        record = ('heavyTank', 8, (), (), (('engine', 'hull', 'engine_0', geometry),), ())
        scene = dict(vehicleMember='scripts/item_defs/vehicles/usa/A_Test.xml',
            bounds=((0., 0., 0.), (3., 3., 3.)), parts=({'role': 'hull',
                'model': 'vehicles/test/collision_client/Hull.model',
                'localBounds': geometry['reference_bounds'], 'offset': (2., 3., 4.)},))
        return scene, {('usa', 'atest'): record}

    def test_keeps_exact_decoded_vertices_and_component_translation(self):
        scene, layouts = self.fixture()
        result = viewer.load_scene(scene, layouts)
        surface = result['parts'][0]['surfaces'][0]
        self.assertEqual((((2., 3., 4.), (3., 3., 4.), (2., 4., 4.)),),
                         surface['triangles'])
        self.assertEqual((), result['warnings'])

    def test_different_component_frame_is_missing_instead_of_resized(self):
        scene, layouts = self.fixture()
        scene['parts'][0]['localBounds'] = ((0., 0., 0.), (1., 1., 2.))
        result = viewer.load_scene(scene, layouts)
        self.assertEqual((), result['parts'])
        self.assertIn('frame mismatch', result['warnings'][0])

    def test_uncovered_vehicle_does_not_get_an_archetype(self):
        scene, unused = self.fixture()
        result = viewer.load_scene(scene, {})
        self.assertEqual((), result['parts'])
        self.assertTrue(result['warnings'])
