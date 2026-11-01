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

    def test_seat_roles_combined_duties_missing_seats_and_exact_mesh(self):
        scene, layouts = self.fixture()
        record = layouts[('usa', 'atest')]
        geometry = record[4][0][3]
        roles = (('commander', 'loader'), ('gunner',), ('loader',), ('loader',))
        scene['crewRoles'] = roles
        layouts[('usa', 'atest')] = record[:2] + (roles, ()) + (record[4], (
            (('hull', 'crew0', geometry),), (('hull', 'crew1', geometry),), (), ()))
        result = viewer.load_scene(scene, layouts)
        seats = result['crewSlots']
        self.assertEqual(4, len(seats))
        self.assertEqual(('commander','loader'), seats[0]['roles'])
        self.assertEqual((1,2), (seats[2]['number'], seats[3]['number']))
        self.assertNotEqual(seats[2]['color'], seats[3]['color'])
        self.assertTrue(any(w.startswith('crew 3:') for w in result['warnings']))
        surfaces = [p['surfaces'][0] for p in result['parts']]
        self.assertEqual(surfaces[0]['triangles'], surfaces[1]['triangles'])
        self.assertEqual(seats[0], surfaces[1]['crewSlot'])
        scene['crewRoles'] = (('driver',),)
        rejected = viewer.load_scene(scene, layouts)
        self.assertEqual(['engine'], [p['surfaces'][0]['moduleEntity'] for p in rejected['parts']])
        self.assertIn('Crew roster does not match the decoded layout.', rejected['warnings'])

    def test_uncovered_vehicle_keeps_exact_roster_without_inventing_surfaces(self):
        scene, unused = self.fixture()
        scene['crewRoles'] = (('driver',), ('gunner','loader'))
        result = viewer.load_scene(scene,{})
        self.assertEqual((), result['parts'])
        self.assertEqual(2,len(result['crewSlots']))
        self.assertEqual(('gunner','loader'), result['crewSlots'][1]['roles'])
