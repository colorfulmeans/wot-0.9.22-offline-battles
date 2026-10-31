import math
import struct
import unittest
from unittest import mock

import vehicle_armor_viewer as viewer


class Variable(object):
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


def primitives_container(sections):
    payload = bytearray(viewer._PRIMITIVES_MAGIC)
    footer = bytearray()
    for name, data in sections:
        payload.extend(data)
        while len(payload) % 4:
            payload.append(0)
        encoded = name.encode("ascii")
        footer.extend(struct.pack("<I", len(data)))
        footer.extend(b"\0" * 16)
        footer.extend(struct.pack("<I", len(encoded)))
        footer.extend(encoded)
        while len(footer) % 4:
            footer.append(0)
    payload.extend(footer)
    payload.extend(struct.pack("<I", len(footer)))
    return bytes(payload)


def packed_element(children):
    packed = viewer.packed_xml
    return packed.PackedElement(children=[
        (name.encode("utf-8"), value) for name, value in children])


def element_value(children):
    packed = viewer.packed_xml
    return packed.PackedValue(packed.TYPE_ELEMENT, packed_element(children))


def string_value(value, value_type=None):
    packed = viewer.packed_xml
    return packed.PackedValue(
        packed.TYPE_STRING if value_type is None else value_type, value)


class VehicleArmorGeometryTest(unittest.TestCase):
    def test_primitives_directory_returns_exact_named_payloads(self):
        data = primitives_container((
            ("indices", b"first"),
            ("vertices", b"second payload"),
        ))

        self.assertEqual(
            {"indices": b"first", "vertices": b"second payload"},
            viewer._decode_primitives_sections(data))

    def test_primitives_directory_rejects_a_bad_footer(self):
        data = bytearray(primitives_container((("bsp2", b"payload"),)))
        data[-4:] = struct.pack("<I", len(data) + 4)

        with self.assertRaises(viewer.ArmorViewerError):
            viewer._decode_primitives_sections(bytes(data))

    def test_index_and_vertex_buffers_keep_group_boundaries(self):
        index_header = b"list" + b"\0" * 60
        indices = (0, 1, 2, 1, 3, 2)
        index_payload = bytearray(index_header)
        index_payload.extend(struct.pack("<II", len(indices), 1))
        index_payload.extend(struct.pack("<6H", *indices))
        index_payload.extend(struct.pack("<4I", 0, 2, 0, 4))

        decoded_indices, groups = viewer._decode_index_section(index_payload)

        self.assertEqual(indices, decoded_indices)
        self.assertEqual(2, groups[0]["triangleCount"])
        self.assertEqual(4, groups[0]["vertexCount"])

        vertex_payload = bytearray(b"BPVTxyz" + b"\0" * 57)
        vertex_payload.extend(b"\0" * 4)
        vertex_payload.extend(b"set3/xyz" + b"\0" * 56)
        vertex_payload.extend(struct.pack("<I", 2))
        vertex_payload.extend(struct.pack("<3fI", 1.0, 2.0, 3.0, 7))
        vertex_payload.extend(struct.pack("<3fI", -1.0, -2.0, -3.0, 9))

        self.assertEqual(
            ((1.0, 2.0, 3.0), (-1.0, -2.0, -3.0)),
            viewer._decode_vertex_section(vertex_payload))

    def test_text_and_binary_component_offsets_are_equivalent(self):
        packed = viewer.packed_xml
        binary = packed.PackedValue(
            packed.TYPE_VECTOR, struct.pack("<3f", 1.5, 2.5, -3.5))
        text = packed.PackedValue(
            packed.TYPE_STRING, b"1.5 2.5 -3.5")

        self.assertEqual(viewer._vector(binary), viewer._vector(text))
        self.assertEqual((0.0, 0.0, 0.0), viewer._vector(
            packed.PackedValue(packed.TYPE_STRING, b"not a vector")))

    def test_data_section_reads_first_duplicate_and_blob_as_base64_text(self):
        packed = viewer.packed_xml
        first = packed_element((("turret", string_value(b"1 2 3")),))
        second = packed_element((("turret", string_value(b"4 5 6")),))
        hull = packed_element((
            ("turretPositions", packed.PackedValue(
                packed.TYPE_ELEMENT, first)),
            ("turretPositions", packed.PackedValue(
                packed.TYPE_ELEMENT, second)),
        ))

        self.assertIs(first, viewer._layer_elements(
            [hull], ("turretPositions",))[0])
        self.assertEqual("M2M7", viewer._value_text(
            string_value(b"3c;", packed.TYPE_COMPRESSED_STRING)))

    def test_hull_variant_matches_the_selected_turret(self):
        packed = viewer.packed_xml
        variant = packed_element((
            ("turret0", string_value(
                b"3c;", packed.TYPE_COMPRESSED_STRING)),
            ("turretPositions", element_value((
                ("turret", string_value(b"0 1 -0.1")),))),
        ))
        hull = packed_element((("variants", element_value((
            ("hull2", packed.PackedValue(packed.TYPE_ELEMENT, variant)),))),))

        self.assertIs(variant, viewer._matching_hull_variant(
            hull, "Chassis-A", "turrets0", "M2M7"))
        self.assertIsNone(viewer._matching_hull_variant(
            hull, "Chassis-A", "turrets0", "M2M5"))

    def test_armor_identity_keeps_part_namespaces_separate(self):
        hull = {"category": "vehicle", "fieldPath": "hull/armor/armor_1"}
        turret = {
            "category": "turret",
            "fieldPath": "turrets0/Turret-A/armor/armor_1",
        }
        gun = {
            "category": "guns",
            "fieldPath": "shared/Gun-A/armor/armor_1",
        }

        self.assertEqual(("hull", "hull", "armor_1", None),
                         viewer._armor_identity(hull))
        self.assertEqual(
            ("turret", "Turret-A", "armor_1", ("turrets0", "Turret-A")),
                         viewer._armor_identity(turret))
        self.assertEqual(("gun", "Gun-A", "armor_1", None),
                         viewer._armor_identity(gun))

    def test_local_gun_identity_keeps_its_mounting_turret(self):
        first = {
            "category": "guns",
            "fieldPath":
                "turrets0/Turret-A/guns/Gun-A/armor/armor_1",
        }
        second = {
            "category": "guns",
            "fieldPath":
                "turrets0/Turret-B/guns/Gun-A/armor/armor_1",
        }

        self.assertNotEqual(viewer._armor_identity(first),
                            viewer._armor_identity(second))
        self.assertEqual(("turrets0", "Turret-B"),
                         viewer._armor_identity(second)[3])

    def test_armor_identity_rejects_non_armor_fields_with_the_same_shape(self):
        records = (
            {"category": "chassis",
             "fieldPath": "shared/Chassis-A/terrainResistance/soft"},
            {"category": "turret",
             "fieldPath": "turrets0/Turret-A/yawLimits/minYaw"},
            {"category": "guns",
             "fieldPath": "turrets0/Turret-A/guns/Gun-A/pitchLimits/minPitch"},
        )

        self.assertEqual([None, None, None],
                         [viewer._armor_identity(record)
                          for record in records])

    def test_classification_uses_material_damage_factor_instead_of_thickness(self):
        layers=[packed_element((('armor',element_value((
            ('armor_1',element_value((('vehicleDamageFactor',string_value(b'0.0')),))),
            ('armor_2',string_value(b'22')),
        ))),))]
        mesh=dict(surfaces=tuple(dict(material=m,triangles=()) for m in ('armor_1','armor_2','gun')))
        with mock.patch.object(viewer,'_collision_model',return_value='gun.model'), \
             mock.patch.object(viewer,'_mesh_for_model',return_value=mesh):
            part=viewer._part_scene('', 'gun','Gun',layers,(0,0,0),[],(None,))
        self.assertEqual(['spaced','main','gun'],[s['armorKind'] for s in part['surfaces']])

    def test_vehicle_relative_scales_separate_thin_plates_and_external_modules(self):
        surfaces = [dict(thickness=v, armorKind='main') for v in (0,8,16,22)]
        track = dict(thickness=5, armorKind='tracks')
        scene = dict(parts=({'surfaces':tuple(surfaces+[track])},))
        scales = viewer._armor_scales(scene)
        self.assertEqual([0,8,16,22], scales['main'])
        self.assertEqual([0,5], scales['external'])
        self.assertEqual(4, len({viewer._armor_color(s, scales) for s in surfaces}))
        self.assertNotEqual(viewer._armor_color(track, scales), viewer._armor_color(surfaces[2], scales))
        self.assertEqual('#555b66', viewer._armor_color(dict(thickness=None), scales))
        for surface in surfaces+[track]:
            color = viewer._armor_color(surface, scales)
            for light in (-.10,0,.12):
                rgb = tuple(int(viewer._shade(color,light)[i:i+2],16) for i in (1,3,5))
                self.assertGreater(max(rgb)-min(rgb),60)

    def test_thickness_colors_use_fixed_absolute_stops(self):
        self.assertEqual(viewer.thickness_color(20),
                         viewer.thickness_color("20"))
        self.assertNotEqual(viewer.thickness_color(20),
                            viewer.thickness_color(250))
        self.assertEqual("#555b66", viewer.thickness_color(None))

    def test_projection_depth_sorts_and_keeps_finite_screen_points(self):
        panel = viewer.ArmorViewerPanel.__new__(viewer.ArmorViewerPanel)
        panel._view_mode = 'armor'
        panel._scene = {
            "bounds": ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
            "parts": ({"surfaces": ({
                "role": "hull", "component": "hull",
                "material": "armor_1", "fieldKey": ("m", "f"),
                "thickness": 50.0,
                "triangles": (
                    ((-1.0, -1.0, -0.5), (1.0, -1.0, -0.5),
                     (0.0, 1.0, -0.5)),
                    ((-1.0, -1.0, 0.5), (1.0, -1.0, 0.5),
                     (0.0, 1.0, 0.5)),
                ),
            },)},),
        }
        panel._yaw = 0.0
        panel._pitch = 0.0
        panel._zoom = 1.0

        triangles = panel._projected_triangles(400, 300)

        self.assertEqual(2, len(triangles))
        self.assertLess(triangles[0][0], triangles[1][0])
        self.assertTrue(all(math.isfinite(value)
                            for unused_depth, points, unused_surface, unused_area
                            in triangles for point in points for value in point))

    def test_focus_field_reports_when_the_collision_model_has_no_surface(self):
        panel = viewer.ArmorViewerPanel.__new__(viewer.ArmorViewerPanel)
        panel._view_mode = 'armor'
        panel._language = viewer.i18n.LANGUAGE_ENGLISH
        panel._scene_error = ""
        panel._focus_key = None
        panel.selection = Variable()
        panel._redraw = lambda: None
        panel._scene = {"parts": ({"surfaces": ()},)}
        record = {
            "member": "scripts/item_defs/vehicles/china/Ch01_Type59.xml",
            "fieldPath": "turrets0/Type59/armor/armor_13",
            "category": "turret",
            "fieldLabel": "Type59 / Armor thickness (armor_13)",
            "currentValue": "65",
        }

        self.assertFalse(panel.focus_field(record, reload_scene=False))
        self.assertIn("no surface in this collision model",
                      panel.selection.get())

    def test_non_armor_focus_does_not_hide_a_scene_load_error(self):
        panel = viewer.ArmorViewerPanel.__new__(viewer.ArmorViewerPanel)
        panel._view_mode = 'armor'
        panel._language = viewer.i18n.LANGUAGE_ENGLISH
        panel._scene = None
        panel._scene_error = "Armor model unavailable: stock resource missing"
        panel._focus_key = None
        panel.selection = Variable()
        panel._redraw = lambda: None

        self.assertFalse(panel.focus_field({
            "member": "scripts/item_defs/vehicles/germany/G138.xml",
            "fieldPath": "invisibility/moving",
            "category": "vehicle",
        }, reload_scene=False))
        self.assertEqual(panel._scene_error, panel.selection.get())

    def test_internal_shell_has_no_mesh_diagonals_and_does_not_hide_or_capture_modules(self):
        panel = viewer.ArmorViewerPanel.__new__(viewer.ArmorViewerPanel)
        panel._view_mode = 'internal'
        panel._yaw = panel._pitch = 0.0
        panel._zoom = 1.0
        panel._focus_key = None
        triangles = (((-1., -1., 0.), (1., -1., 0.), (1., 1., 0.)),
                     ((-1., -1., 0.), (1., 1., 0.), (-1., 1., 0.)))
        shell = dict(role='hull', component='hull', triangles=triangles)
        module = dict(moduleLabel='engine', color='#df8c42',
                      triangles=triangles[:1])
        panel._scene = dict(bounds=((-1., -1., -1.), (1., 1., 1.)),
                            parts=({'surfaces': (shell,)},))
        panel._internal_scene = dict(parts=({'surfaces': (module,)},))

        class Canvas:
            def __init__(self):
                self.calls = []
            def winfo_width(self): return 400
            def winfo_height(self): return 300
            def delete(self, unused): pass
            def create_polygon(self, coords, **options):
                self.calls.append((coords, options))
                return len(self.calls)
            def create_line(self, *args, **options):
                self.calls.append((args, options))
                return len(self.calls)

        panel.canvas = Canvas()
        contexts = []
        panel._draw_context_shell = lambda w, h: contexts.extend(
            panel._projected_shell_outlines(w, h))
        panel._redraw()
        self.assertEqual(1, len(panel.canvas.calls))
        self.assertEqual(4, len(contexts[0]))
        self.assertEqual('', panel.canvas.calls[0][1]['outline'])
        self.assertEqual({1: module}, panel._item_surface)
        self.assertEqual(1, len(panel._projected_triangles(400, 300)))
        self.assertEqual(1, len(panel._projected_shell_outlines(400, 300)))
        panel._yaw = 0.4
        self.assertNotEqual([v for p in contexts[0] for v in p],
            [value for point in panel._projected_shell_outlines(400, 300)[0]
             for value in point])

    def test_flat_plate_drops_internal_diagonal_but_keeps_selected_boundary(self):
        surface = dict(role='hull', component='hull')
        a, b, c, d = (0., 0., 0.), (2., 0., 0.), (2., 2., 0.), (0., 2., 0.)
        triangles = [(0, (a, b, c), surface, 4),
                     (0, (a, c, d), surface, 4)]
        self.assertEqual(4, len(viewer._surface_edges(triangles)))
        self.assertEqual(4, len(viewer._surface_edges(triangles, boundary_only=True)))

    def test_relative_ramp_is_continuous_and_rejects_unknown_numbers(self):
        for value in (None, float('nan'),float('inf'),-1):
            self.assertEqual('#555b66',viewer.thickness_color(value,22))
        self.assertNotEqual(viewer.thickness_color(8,22),viewer.thickness_color(16,22))
        self.assertEqual(viewer.thickness_color(22,22),viewer.thickness_color(100,100))

    def test_component_switch_invalidates_internal_geometry_before_display(self):
        panel = viewer.ArmorViewerPanel.__new__(viewer.ArmorViewerPanel)
        panel._vehicle_member = 'scripts/item_defs/vehicles/usa/T29.xml'
        panel._game_root, panel._records = 'client', []
        panel._internal_scene = {'old_turret': True}
        panel._view_mode = 'internal'
        panel._scene_loader = lambda *args, **kwargs: {'new_turret': True}
        observed = []
        panel.set_view_mode = lambda mode: observed.append((mode, panel._internal_scene, panel._scene))
        self.assertTrue(panel._load_scene({'fieldPath': 'turrets0/second/armor/armor_1'}))
        self.assertEqual([('internal', None, {'new_turret': True})], observed)


if __name__ == "__main__":
    unittest.main()
