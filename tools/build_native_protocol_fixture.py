#!/usr/bin/env python3
"""Build #1513 property bodies for the bounded native-network experiment.

This does not encode Mercury message headers, entity identifiers, positions,
space data, or clocks. Run inspect_client.py on the client before using it.
Vehicle values must be exported from the exact running client's descriptor.
"""

import argparse
import base64
import json
import math
import os
from pathlib import Path
import pickle
import struct
import sys
import zipfile

import packed_xml


CLIENT_BUILD = "wot-0.9.22.0.1-cn-1513"
NUMERIC_FORMATS = {
    "INT8": "b", "UINT8": "B", "INT16": "h", "UINT16": "H",
    "INT32": "i", "UINT32": "I", "INT64": "q", "UINT64": "Q",
    "FLOAT32": "f", "FLOAT64": "d", "FLOAT": "f",
}
AVATAR_BASE_VALUES = {
    "name": "NativeProtocolProbe", "arenaUniqueID": 1,
    # Exact constants.pyc: REGULAR=1 and RANDOM=1; zero is UNKNOWN.
    "arenaBonusType": 1, "arenaGuiType": 1, "arenaExtraData": {},
    "weatherPresetID": 0, "denunciationsLeft": 10, "clientCtx": "",
    "tkillIsSuspected": False, "playLimits": {},
}
AVATAR_OWN_VALUES = {
    "remoteCamera": {"time": 0.0, "shotPoint": [0.0, 0.0, 0.0], "zoom": 0},
    "isObserverFPV": False, "observerFPVControlMode": 0, "numOfObservers": 0,
    "team": 1, "playerVehicleID": 0, "isObserverBothTeams": False,
    "isGunLocked": False, "ownVehicleGear": 0, "ownVehicleAuxPhysicsData": 0,
}


def scalar(value):
    if value.value_type == packed_xml.TYPE_ELEMENT:
        return scalar(value.value.value)
    if value.value_type == packed_xml.TYPE_COMPRESSED_STRING:
        # Packed XML stores a base64-looking source string as decoded bytes.
        return base64.b64encode(value.value).decode("ascii")
    if isinstance(value.value, bytes):
        return value.value.decode("utf-8")
    return value.value


def children(element, name):
    return [value for key, value in element.children if key.decode() == name]


def child(element, name, required=True):
    values = children(element, name)
    if len(values) > 1 or (required and not values):
        raise ValueError("expected one %s section" % name)
    return values[0] if values else None


def section(value):
    if value.value_type != packed_xml.TYPE_ELEMENT:
        raise ValueError("expected a Packed XML element")
    return value.value


class EntityDefinitions:
    def __init__(self, archive):
        self.archive = archive
        self.members_read = set()
        aliases = self.read("scripts/entity_defs/alias.xml")
        self.aliases = {key.decode(): value for key, value in aliases.children}

    def read(self, member):
        self.members_read.add(member)
        return packed_xml.read_packed_xml(self.archive.read(member))

    def type_schema(self, value, resolving=()):
        name = scalar(value).strip()
        if name in NUMERIC_FORMATS or name in ("STRING", "PYTHON"):
            return {"kind": name}
        if name in ("VECTOR2", "VECTOR3", "VECTOR4"):
            return {"kind": name}
        if name in self.aliases:
            if name in resolving:
                raise ValueError("recursive type alias: %s" % name)
            return {"kind": "ALIAS", "name": name,
                    "type": self.type_schema(self.aliases[name], resolving + (name,))}
        node = section(value)
        if name in ("ARRAY", "TUPLE"):
            size = child(node, "size", required=False)
            return {"kind": name, "size": None if size is None else int(scalar(size)),
                    "of": self.type_schema(child(node, "of"), resolving)}
        if name == "FIXED_DICT":
            nullable = child(node, "AllowNone", required=False)
            allow_none = scalar(nullable) if nullable is not None else False
            if isinstance(allow_none, str):
                allow_none = allow_none.strip().lower()
                if allow_none not in ("true", "false", "1", "0"):
                    raise ValueError("AllowNone needs a boolean")
                allow_none = allow_none in ("true", "1")
            elif not isinstance(allow_none, (bool, int)) or allow_none not in (False, True):
                raise ValueError("AllowNone needs a boolean")
            implemented = child(node, "implementedBy", required=False)
            if implemented is not None:
                raise ValueError("custom FIXED_DICT codec is outside this fixture")
            fields = []
            for field_name, field in section(child(node, "Properties")).children:
                fields.append({"name": field_name.decode(),
                               "type": self.type_schema(child(section(field), "Type"), resolving)})
            return {"kind": name, "allow_none": bool(allow_none),
                    "fields": fields}
        raise ValueError("unsupported property type: %s" % name)

    def properties(self, entity, flags):
        # #1513 0x8053b0 appends/overrides this order; it sorts only the separate
        # clientServerProperties index table, not the full-stream property vector.
        ordered = {}

        def visit(member, active=()):
            if member in active:
                raise ValueError("recursive entity inheritance: %s" % member)
            node = self.read(member)
            parent = child(node, "Parent", required=False)
            if parent is not None:
                visit("scripts/entity_defs/%s.def" % scalar(parent), active + (member,))
            implements = child(node, "Implements", required=False)
            if implements is not None:
                for interface in children(section(implements), "Interface"):
                    visit("scripts/entity_defs/interfaces/%s.def" % scalar(interface),
                          active + (member,))
            properties = child(node, "Properties", required=False)
            if properties is None:
                return
            for raw_name, raw_property in section(properties).children:
                prop = section(raw_property)
                name = raw_name.decode()
                property_flags = scalar(child(prop, "Flags"))
                ordered[name] = {"name": name, "flags": property_flags,
                                 "source": member, "type_value": child(prop, "Type")}

        visit("scripts/entity_defs/%s.def" % entity)
        result = []
        for prop in ordered.values():
            if prop["flags"] in flags:
                prop["type"] = self.type_schema(prop.pop("type_value"))
                result.append(prop)
        return result

    def client_entity_names(self):
        root = self.read("scripts/entities.xml")
        return [name.decode() for name, unused in
                section(child(root, "ClientServerEntities")).children]


def packed_length(length):
    if not 0 <= length <= 0xFFFFFF:
        raise ValueError("variable value exceeds the packed uint24 limit")
    return bytes([length]) if length < 255 else b"\xff" + length.to_bytes(3, "little")


def string_bytes(value):
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict) and set(value) == {"base64"}:
        return base64.b64decode(value["base64"], validate=True)
    raise ValueError("STRING requires text or an exact {base64: ...} byte value")


def encode_value(schema, value):
    kind = schema["kind"]
    if kind == "ALIAS":
        return encode_value(schema["type"], value)
    if kind in NUMERIC_FORMATS:
        fmt = NUMERIC_FORMATS[kind]
        if fmt in "fd":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("%s needs a finite number" % kind)
        elif not isinstance(value, int):
            raise ValueError("%s needs an integer" % kind)
        return struct.pack("<" + fmt, value)
    if kind.startswith("VECTOR"):
        width = int(kind[-1])
        if not isinstance(value, (list, tuple)) or len(value) != width:
            raise ValueError("%s component count mismatch" % kind)
        return b"".join(encode_value({"kind": "FLOAT32"}, item) for item in value)
    if kind in ("STRING", "PYTHON"):
        data = string_bytes(value) if kind == "STRING" else pickle.dumps(value, protocol=2)
        return packed_length(len(data)) + data
    if kind in ("ARRAY", "TUPLE"):
        if not isinstance(value, (list, tuple)):
            raise ValueError("%s needs a sequence" % kind)
        size = schema["size"]
        if size is not None and len(value) != size:
            raise ValueError("fixed sequence size mismatch")
        prefix = packed_length(len(value)) if size is None else b""
        return prefix + b"".join(encode_value(schema["of"], item) for item in value)
    if kind == "FIXED_DICT":
        if value is None and schema["allow_none"]:
            return b"\0"
        if not isinstance(value, dict):
            raise ValueError("FIXED_DICT needs a mapping")
        expected = {field["name"] for field in schema["fields"]}
        if set(value) != expected:
            raise ValueError("FIXED_DICT fields differ: %s" % sorted(set(value) ^ expected))
        prefix = b"\1" if schema["allow_none"] else b""
        return prefix + b"".join(encode_value(field["type"], value[field["name"]])
                                  for field in schema["fields"])
    raise ValueError("unsupported codec: %s" % kind)


def property_body(properties, values):
    if values is None:
        return {"status": "missing_runtime_state", "properties": properties}
    expected = {prop["name"] for prop in properties}
    if set(values) != expected:
        raise ValueError("property fields differ: %s" % sorted(set(values) ^ expected))
    body = bytearray()
    layout = []
    for prop in properties:
        value = values[prop["name"]]
        data = encode_value(prop["type"], value)
        layout.append(dict(prop, offset=len(body), size=len(data), value=value,
                           body_hex=data.hex()))
        body.extend(data)
    return {"status": "encoded", "properties": layout, "byte_length": len(body),
            "body_hex": body.hex(), "body_base64": base64.b64encode(body).decode("ascii")}


def build_fixture(client, arena_type_id, player_vehicle_id=0, name="NativeProtocolProbe",
                  team=1, vehicle_state=None):
    base_values = dict(AVATAR_BASE_VALUES, arenaTypeID=arena_type_id, name=name)
    own_values = dict(AVATAR_OWN_VALUES, playerVehicleID=player_vehicle_id, team=team)
    if vehicle_state is not None:
        if vehicle_state.get("client_build") != CLIENT_BUILD:
            raise ValueError("vehicle export must identify the exact #1513 client")
        if ("arena_type_id" in vehicle_state and
                vehicle_state["arena_type_id"] != arena_type_id):
            raise ValueError("runtime vehicle export and fixture arena type differ")
        if not vehicle_state.get("vehicle"):
            raise ValueError("vehicle export must identify the selected vehicle")
        properties = vehicle_state["properties"]
        compact = string_bytes(properties["publicInfo"]["compDescr"])
        if not compact:
            raise ValueError("vehicle export has an empty compact descriptor")
        if properties["publicInfo"]["name"] != name or properties["publicInfo"]["team"] != team:
            raise ValueError("Avatar and Vehicle name/team must agree")
    with zipfile.ZipFile(Path(client) / "res/packages/scripts.pkg") as archive:
        definitions = EntityDefinitions(archive)
        result = {
            "schema": 1, "client_build": CLIENT_BUILD,
            "scope": "property bodies only; no engine message or creation header",
            "encoding": {"byte_order": "little", "variable_length": "packed_uint24",
                         "python": "pickle_protocol_2",
                         "property_order": "parent/interfaces depth-first then declaration order"},
            "evidence_boundary": "Exact resource schema; native wire acceptance is still required.",
            "client_server_entities_declaration_order": definitions.client_entity_names(),
            "avatar_base": property_body(definitions.properties("Avatar", {"BASE_AND_CLIENT"}), base_values),
            "avatar_own_cell": property_body(definitions.properties("Avatar", {"OWN_CLIENT"}), own_values),
            "vehicle_all_clients": property_body(definitions.properties("Vehicle", {"ALL_CLIENTS"}),
                                                  vehicle_state["properties"] if vehicle_state else None),
        }
        result["resource_members"] = sorted(definitions.members_read)
    if vehicle_state:
        result["vehicle"] = vehicle_state["vehicle"]
        for key in ("arena_type_id", "map"):
            if key in vehicle_state:
                result[key] = vehicle_state[key]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", default=os.environ.get("WOT_0922_CLIENT"))
    parser.add_argument("--arena-type-id", type=int, required=True,
                        help="Exact runtime ArenaType.id; do not substitute a map list index")
    parser.add_argument("--player-vehicle-id", type=int, default=0)
    parser.add_argument("--name", default="NativeProtocolProbe")
    parser.add_argument("--team", type=int, choices=(1, 2), default=1)
    parser.add_argument("--vehicle-state", type=Path,
                        help="Runtime export: client_build, vehicle, properties; binary STRINGs use {base64: ...}")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.client:
        parser.error("--client or WOT_0922_CLIENT is required")
    try:
        state = json.loads(args.vehicle_state.read_text()) if args.vehicle_state else None
        fixture = build_fixture(args.client, args.arena_type_id, args.player_vehicle_id,
                                args.name, args.team, state)
        text = json.dumps(fixture, indent=2, ensure_ascii=True) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text)
    except (OSError, ValueError, KeyError, struct.error, zipfile.BadZipFile) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
