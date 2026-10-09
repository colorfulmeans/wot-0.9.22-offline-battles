"""Property payload checks; these do not claim native message acceptance."""

import base64
import io
import json
import os
from pathlib import Path
import pickle
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_native_protocol_fixture as fixture
import packed_xml


def string(value):
    return packed_xml.PackedValue(packed_xml.TYPE_STRING, value.encode())


def element(items, text=""):
    return packed_xml.PackedValue(
        packed_xml.TYPE_ELEMENT,
        packed_xml.PackedElement(string(text), [(name.encode(), value) for name, value in items]))


def prop(kind, flags):
    return element([("Type", string(kind)), ("Flags", string(flags))])


class NativeProtocolFixtureTests(unittest.TestCase):
    def test_native_avatar_uses_regular_random_battle_not_lobby_placeholders(self):
        self.assertEqual(1, fixture.AVATAR_BASE_VALUES["arenaBonusType"])
        self.assertEqual(1, fixture.AVATAR_BASE_VALUES["arenaGuiType"])
        properties = [{"name": name, "type": {"kind": "UINT8"}}
                      for name in ("arenaBonusType", "arenaGuiType")]
        self.assertEqual("0101", fixture.property_body(properties, {
            name: fixture.AVATAR_BASE_VALUES[name]
            for name in ("arenaBonusType", "arenaGuiType")})["body_hex"])

    def test_packed_xml_base64_string_restores_bool_alias(self):
        value = packed_xml.PackedValue(packed_xml.TYPE_COMPRESSED_STRING,
                                       base64.b64decode("BOOL"))
        self.assertEqual("BOOL", fixture.scalar(value))

    def test_inherited_own_properties_do_not_leak_into_base_body(self):
        documents = {
            "scripts/entity_defs/alias.xml": element([("BOOL", string("UINT8"))]),
            "scripts/entity_defs/interfaces/Observer.def": element([
                ("Properties", element([("camera", prop("UINT8", "OWN_CLIENT")),
                                         ("inherited", prop("UINT8", "BASE_AND_CLIENT"))]))]),
            "scripts/entity_defs/Avatar.def": element([
                ("Implements", element([("Interface", string("Observer"))])),
                ("Properties", element([("name", prop("STRING", "BASE_AND_CLIENT")),
                                         ("team", prop("UINT8", "OWN_CLIENT")),
                                         ("hidden", prop("INT32", "CELL_PRIVATE"))]))]),
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, document in documents.items():
                archive.writestr(name, packed_xml.write_packed_xml(document.value))
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
            definitions = fixture.EntityDefinitions(archive)
            base = definitions.properties("Avatar", {"BASE_AND_CLIENT"})
            own = definitions.properties("Avatar", {"OWN_CLIENT"})
        self.assertEqual(["inherited", "name"], [p["name"] for p in base])
        self.assertEqual(["camera", "team"], [p["name"] for p in own])
        body = fixture.property_body(base, {"name": "A", "inherited": 7})
        self.assertEqual("070141", body["body_hex"])
        self.assertEqual([0, 1], [p["offset"] for p in body["properties"]])

    def test_variable_lengths_and_binary_string(self):
        self.assertEqual(b"\xfe", fixture.packed_length(254))
        self.assertEqual(b"\xff\xff\0\0", fixture.packed_length(255))
        self.assertEqual(b"\xff\0\0\1", fixture.packed_length(65536))
        self.assertEqual(b"\x03\0\xff\x80", fixture.encode_value(
            {"kind": "STRING"}, {"base64": "AP+A"}))
        with self.assertRaises(ValueError):
            fixture.packed_length(0x1000000)

    def test_parent_override_keeps_original_slot_without_size_sorting(self):
        documents = {
            "scripts/entity_defs/alias.xml": element([]),
            "scripts/entity_defs/Parent.def": element([("Properties", element([
                ("wide", prop("UINT32", "OWN_CLIENT")),
                ("overridden", prop("UINT8", "OWN_CLIENT"))]))]),
            "scripts/entity_defs/interfaces/Extra.def": element([("Properties", element([
                ("extra", prop("UINT8", "OWN_CLIENT"))]))]),
            "scripts/entity_defs/Avatar.def": element([
                ("Parent", string("Parent")),
                ("Implements", element([("Interface", string("Extra"))])),
                ("Properties", element([("overridden", prop("UINT16", "OWN_CLIENT")),
                                         ("tail", prop("UINT8", "OWN_CLIENT"))]))]),
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, document in documents.items():
                archive.writestr(name, packed_xml.write_packed_xml(document.value))
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
            properties = fixture.EntityDefinitions(archive).properties("Avatar", {"OWN_CLIENT"})
        self.assertEqual(["wide", "overridden", "extra", "tail"],
                         [p["name"] for p in properties])
        self.assertEqual("0100000002000304", fixture.property_body(properties, {
            "wide": 1, "overridden": 2, "extra": 3, "tail": 4})["body_hex"])

    def test_fixed_dict_order_and_fixed_tuple_have_no_length_header(self):
        schema = {"kind": "FIXED_DICT", "allow_none": False, "fields": [
            {"name": "team", "type": {"kind": "UINT8"}},
            {"name": "engine", "type": {"kind": "TUPLE", "size": 2,
                                            "of": {"kind": "UINT8"}}}]}
        self.assertEqual(b"\x02\x03\x04", fixture.encode_value(
            schema, {"engine": [3, 4], "team": 2}))
        with self.assertRaises(ValueError):
            fixture.encode_value(schema, {"team": 2, "engine": [3, 4], "extra": 0})

    def test_fixed_dict_allow_none_parses_boolean_not_string_truthiness(self):
        definitions = fixture.EntityDefinitions.__new__(fixture.EntityDefinitions)
        definitions.aliases = {}
        for raw, expected in ((string("false"), False), (string("true"), True),
                              (string("0"), False), (string("1"), True),
                              (packed_xml.PackedValue(packed_xml.TYPE_BOOLEAN, False), False),
                              (packed_xml.PackedValue(packed_xml.TYPE_BOOLEAN, True), True)):
            with self.subTest(value=raw.value):
                schema = definitions.type_schema(element([
                    ("AllowNone", raw),
                    ("Properties", element([("value", element([("Type", string("UINT8"))]))]))],
                    text="FIXED_DICT"))
                self.assertIs(expected, schema["allow_none"])
                self.assertEqual(b"\x01\x03" if expected else b"\x03",
                                 fixture.encode_value(schema, {"value": 3}))
                if expected:
                    self.assertEqual(b"\0", fixture.encode_value(schema, None))
                else:
                    with self.assertRaises(ValueError):
                        fixture.encode_value(schema, None)
        with self.assertRaisesRegex(ValueError, "AllowNone"):
            definitions.type_schema(element([
                ("AllowNone", string("invalid")), ("Properties", element([]))],
                text="FIXED_DICT"))

    def test_python_uses_legacy_pickle_protocol(self):
        body = fixture.encode_value({"kind": "PYTHON"}, {})
        self.assertEqual(len(body) - 1, body[0])
        self.assertEqual(b"\x80\x02", body[1:3])
        self.assertEqual({}, pickle.loads(body[1:]))

    def test_invalid_numeric_or_sequence_values_fail(self):
        for schema, value in [({"kind": "UINT8"}, 256),
                              ({"kind": "FLOAT32"}, float("nan")),
                              ({"kind": "TUPLE", "size": 2, "of": {"kind": "UINT8"}}, [0]),
                              ({"kind": "STRING"}, {"base64": "!"})]:
            with self.subTest(schema=schema, value=value):
                with self.assertRaises((ValueError, struct.error)):
                    fixture.encode_value(schema, value)

    def test_missing_vehicle_state_never_fabricates_payload(self):
        result = fixture.property_body([], None)
        self.assertEqual("missing_runtime_state", result["status"])
        self.assertNotIn("body_hex", result)

    def test_vehicle_export_from_a_different_arena_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "arena type differ"):
            fixture.build_fixture("unused", 1, vehicle_state={
                "client_build": fixture.CLIENT_BUILD, "arena_type_id": 2})

    @unittest.skipUnless(os.environ.get("WOT_0922_CLIENT"), "exact client not configured")
    def test_exact_client_avatar_slices_and_vehicle_schema(self):
        result = fixture.build_fixture(os.environ["WOT_0922_CLIENT"], 1)
        self.assertEqual(11, len(result["avatar_base"]["properties"]))
        self.assertEqual(10, len(result["avatar_own_cell"]["properties"]))
        self.assertEqual("remoteCamera", result["avatar_own_cell"]["properties"][0]["name"])
        self.assertEqual(12, len(result["vehicle_all_clients"]["properties"]))
        self.assertEqual(40, result["avatar_own_cell"]["byte_length"])
        values = {prop["name"]: prop for prop in result["avatar_base"]["properties"]}
        self.assertEqual("01", values["arenaBonusType"]["body_hex"])
        self.assertEqual("01", values["arenaGuiType"]["body_hex"])
        self.assertEqual("missing_runtime_state", result["vehicle_all_clients"]["status"])
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
