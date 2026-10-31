"""Interactive armor geometry viewer for the 0.9.22 vehicle editor.

The viewer reads stock #1513 collision resources. A per-pixel depth renderer
composites actual component surfaces and verified interior volumes into Tk.
"""

from __future__ import annotations

try:
    from . import ui_layout
except ImportError:
    import ui_layout

import base64
from collections import OrderedDict
import math
import os
import re
import struct
import zipfile
import zlib
import time

try:
    import packed_xml
except ImportError:
    import sys

    _TOOLS_ROOT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tools")
    if _TOOLS_ROOT not in sys.path:
        sys.path.insert(0, _TOOLS_ROOT)
    import packed_xml

try:
    from . import i18n, vehicle_overlays
except ImportError:
    import i18n
    import vehicle_overlays


_PRIMITIVES_MAGIC = b"\x65\x4e\xa1\x42"
_ARMOR_FIELD = re.compile(r"^[A-Za-z0-9_.-]+$")
_TURRET_GROUP = re.compile(r"^turrets[0-9]+$")
_TURRET_VARIANT_KEY = re.compile(r"^turret[0-9]+$")
_MESH_CACHE_LIMIT = 64
_MESH_CACHE = OrderedDict()
_RESOURCE_PACKAGE_CACHE = {}

_ZH = {
    'X-ray': '透视',
    'External modules': '外部模块',
    'Main armor': '主装甲', 'Exterior opacity': '车体不透明度',
    'Preview turret': '预览炮塔', 'Preview gun': '预览火炮',
    'Restore default display': '恢复默认显示',
    'Module opacity': '模块不透明度', 'Display settings': '显示设置',
    'Show all': '全部显示', 'Hide all': '全部隐藏', 'Close': '关闭',
    'Hull': '车体', 'Turret': '炮塔', 'Chassis': '底盘',
    'No geometry': '无几何数据', 'Display': '显示',
    "Armor": "装甲",
    "Internal modules": "内部模块",
    "Internal module data": "内部模块数据",
    "Modules and crew": "模块与乘员",
    "Engine": "发动机", "Ammo": "弹药", "Fuel": "油箱",
    "Radio": "电台", "Crew": "乘员",
    "Ammo rack": "弹药架", "Fuel tank": "油箱",
    "Turret rotation mechanism": "炮塔旋转机构",
    "Main armor (mm, vehicle scale)": "主装甲（毫米，本车色阶）",
    "Spaced armor / external modules (mm, vehicle scale)": "间隙装甲／外部模块（毫米，本车色阶）",
    "Tracks (external module)": "履带（外部模块）",
    "Tracks": "履带", "Gun": "炮管", "Spaced armor": "间隙装甲",
    "Modules": "模块", "Commander": "车长", "Gunner": "炮手",
    "Driver": "驾驶员", "Loader": "装填手", "Radio operator": "通信兵",
    "%s (also %s)": "%s（兼%s）",
    "Crew roster does not match the decoded layout.": "乘员编制与解码布局不匹配。",
    "Observation devices": "观察装置", "Transmission": "传动装置",
    "%s (no data)": "%s（无数据）",
    "%s (incomplete)": "%s（部分缺失）",
    "Crew %s": "乘员%s",
    "No decoded interior geometry is available.": "没有可用的解码内部曲面。",
    "component frame mismatch": "部件坐标框架不匹配",
    "selected component has no matching interior": "当前所选部件没有匹配的内部曲面",
    "Drag to orbit · wheel to zoom · click a module to inspect it":
        "拖动旋转 · 滚轮缩放 · 点击模块查看名称",
    "Console-sourced surfaces; selected PC frame verified. Missing modules are not drawn.":
        "Console 来源内部表面；已核对当前 PC 部件坐标框架，缺失或不匹配部分不显示。",
    "Some interior data is unavailable:\n%s": "部分内部模块数据不可用：\n%s",
    "3D armor viewer": "3D 装甲检视",
    "Drag to orbit · wheel to zoom · click armor to select its field":
        "拖动旋转 · 滚轮缩放 · 点击装甲跳转到对应属性",
    "Loading stock collision model...": "正在读取原版碰撞模型…",
    "No armor field selected": "尚未选中装甲属性",
    "Selected: %s · %s mm": "已选：%s · %s 毫米",
    "Selected: %s · %s mm · no surface in this collision model":
        "已选：%s · %s 毫米 · 当前碰撞模型中没有可视化表面",
    "Material %s has no editable thickness field.":
        "材质 %s 没有可修改的厚度属性。",
    "Armor model unavailable: %s": "无法显示装甲模型：%s",
    "Reset view": "复位视角",
    "Nominal thickness (mm)": "标称厚度（毫米）",
    "Unmapped": "未映射",
    "Click an armor surface or choose an armor field.":
        "点击装甲表面，或在左侧选择装甲属性。",
}


class ArmorViewerError(Exception):
    """A contained stock-resource or geometry error."""


def _translated(language, text):
    if i18n.resolve_language(language) == i18n.LANGUAGE_CHINESE:
        return _ZH.get(text, text)
    return text


def _aligned(value, alignment=4):
    return (value + alignment - 1) // alignment * alignment


def _decode_primitives_sections(data):
    """Return named payloads from one BigWorld primitives container."""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 32:
        raise ArmorViewerError("The primitives resource is truncated.")
    if bytes(data[:4]) != _PRIMITIVES_MAGIC:
        raise ArmorViewerError("The primitives resource has an unknown magic.")
    footer_size = struct.unpack_from("<I", data, len(data) - 4)[0]
    footer_start = len(data) - 4 - footer_size
    if footer_start < 4 or footer_start % 4:
        raise ArmorViewerError("The primitives directory is invalid.")

    entries = []
    offset = footer_start
    footer_end = len(data) - 4
    while offset < footer_end:
        if offset + 24 > footer_end:
            raise ArmorViewerError("The primitives directory is truncated.")
        payload_size = struct.unpack_from("<I", data, offset)[0]
        offset += 20  # payload length plus the stock 16-byte digest field
        name_size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        padded_name_size = _aligned(name_size)
        if (name_size < 1 or offset + padded_name_size > footer_end or
                b"\0" in data[offset:offset + name_size]):
            raise ArmorViewerError("A primitives section name is invalid.")
        try:
            name = bytes(data[offset:offset + name_size]).decode("ascii")
        except UnicodeDecodeError:
            raise ArmorViewerError(
                "A primitives section name is not ASCII text.")
        offset += padded_name_size
        entries.append((name, payload_size))
    if offset != footer_end or not entries:
        raise ArmorViewerError("The primitives directory is incomplete.")

    sections = {}
    payload_offset = 4
    for name, payload_size in entries:
        payload_end = payload_offset + payload_size
        if payload_end > footer_start or name in sections:
            raise ArmorViewerError("The primitives sections overlap.")
        sections[name] = bytes(data[payload_offset:payload_end])
        payload_offset = _aligned(payload_end)
    if payload_offset != footer_start:
        raise ArmorViewerError("The primitives payload sizes are inconsistent.")
    return sections


def _header_text(payload, offset=0, size=64):
    if len(payload) < offset + size:
        return ""
    raw = payload[offset:offset + size].split(b"\0", 1)[0]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return ""


def _decode_index_section(payload):
    if len(payload) < 72:
        raise ArmorViewerError("The collision index buffer is truncated.")
    index_format = _header_text(payload)
    if index_format == "list":
        index_width = 2
        unpack_code = "H"
    elif index_format in ("list32", "list32bit"):
        index_width = 4
        unpack_code = "I"
    else:
        raise ArmorViewerError(
            "The collision index format is unsupported: %s" %
            (index_format or "unknown"))
    index_count, group_count = struct.unpack_from("<II", payload, 64)
    if index_count > 20 * 1000 * 1000 or group_count > 100000:
        raise ArmorViewerError("The collision index counts are unreasonable.")
    index_end = 72 + index_count * index_width
    expected = index_end + group_count * 16
    if expected != len(payload):
        raise ArmorViewerError("The collision index buffer size is invalid.")
    indices = struct.unpack_from(
        "<%d%s" % (index_count, unpack_code), payload, 72)
    groups = []
    for group_index in range(group_count):
        start, triangle_count, first_vertex, vertex_count = struct.unpack_from(
            "<4I", payload, index_end + group_index * 16)
        end = start + triangle_count * 3
        if (end > index_count or first_vertex + vertex_count > 0xffffffff or
                any(index < first_vertex or
                    index >= first_vertex + vertex_count
                    for index in indices[start:end])):
            raise ArmorViewerError("A collision primitive group is invalid.")
        groups.append({
            "start": start,
            "triangleCount": triangle_count,
            "firstVertex": first_vertex,
            "vertexCount": vertex_count,
        })
    return tuple(indices), tuple(groups)


def _decode_vertex_section(payload):
    if len(payload) < 136:
        raise ArmorViewerError("The collision vertex buffer is truncated.")
    vertex_format = _header_text(payload)
    declaration = _header_text(payload, 68)
    vertex_count = struct.unpack_from("<I", payload, 132)[0]
    if vertex_count < 1 or vertex_count > 10 * 1000 * 1000:
        raise ArmorViewerError("The collision vertex count is invalid.")
    data_size = len(payload) - 136
    if data_size % vertex_count:
        raise ArmorViewerError("The collision vertex stride is invalid.")
    stride = data_size // vertex_count
    if stride < 12 or stride > 512:
        raise ArmorViewerError("The collision vertex layout is unsupported.")
    if not vertex_format or not declaration:
        raise ArmorViewerError("The collision vertex declaration is missing.")
    vertices = []
    for index in range(vertex_count):
        point = struct.unpack_from("<3f", payload, 136 + index * stride)
        if not all(math.isfinite(value) for value in point):
            raise ArmorViewerError("The collision vertex data is not finite.")
        vertices.append(point)
    return tuple(vertices)


def _children(element, name):
    encoded = name.encode("utf-8")
    return [value for current, value in element.children
            if current == encoded]


def _element_children(element, name):
    return [value.value for value in _children(element, name)
            if value.value_type == packed_xml.TYPE_ELEMENT]


def _unique_child(element, name):
    values = _children(element, name)
    return values[0] if len(values) == 1 else None


def _first_child(element, name):
    values = _children(element, name)
    return values[0] if values else None


def _value_text(value):
    if value is None:
        return None
    if value.value_type == packed_xml.TYPE_STRING:
        try:
            return value.value.decode("utf-8")
        except (AttributeError, UnicodeDecodeError):
            return None
    if value.value_type == packed_xml.TYPE_INTEGER:
        return str(value.value)
    if value.value_type == packed_xml.TYPE_COMPRESSED_STRING:
        try:
            return base64.b64encode(value.value).decode("ascii")
        except (AttributeError, TypeError, ValueError):
            return None
    return None


def _vector(value, default=(0.0, 0.0, 0.0)):
    fallback = None if default is None else tuple(default)
    if value is None:
        return fallback
    if value.value_type == packed_xml.TYPE_VECTOR:
        raw = value.value
        if len(raw) != 12:
            return fallback
        result = struct.unpack("<3f", raw)
    elif value.value_type == packed_xml.TYPE_STRING:
        try:
            parts = value.value.decode("ascii").strip().split()
            if len(parts) != 3:
                return fallback
            result = tuple(float(part) for part in parts)
        except (AttributeError, UnicodeDecodeError, TypeError, ValueError,
                OverflowError):
            return fallback
    else:
        return fallback
    if not all(math.isfinite(item) for item in result):
        return fallback
    return tuple(float(item) for item in result)


def _layer_values(layers, path):
    current = [layer for layer in layers if layer is not None]
    for offset, name in enumerate(path):
        final = offset == len(path) - 1
        nested = []
        scalar = None
        for layer in current:
            value = _first_child(layer, name)
            if value is None:
                continue
            if final and scalar is None:
                scalar = value
            if value.value_type == packed_xml.TYPE_ELEMENT:
                nested.append(value.value)
        if final:
            return scalar
        current = nested
        if not current:
            return None
    return None


def _layer_elements(layers, path):
    current = [layer for layer in layers if layer is not None]
    for name in path:
        nested = []
        for layer in current:
            value = _first_child(layer, name)
            if value is not None and value.value_type == packed_xml.TYPE_ELEMENT:
                nested.append(value.value)
        current = nested
        if not current:
            break
    return current


def _ordered_entry_names(layers, container_name):
    names = []
    for container in _layer_elements(layers, (container_name,)):
        for raw_name, unused_value in container.children:
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if name not in names:
                names.append(name)
    return names


def _entry_layers(layers, container_name, entry_name):
    result = []
    for container in _layer_elements(layers, (container_name,)):
        value = _unique_child(container, entry_name)
        if value is not None and value.value_type == packed_xml.TYPE_ELEMENT:
            result.append(value.value)
    return result


def _shared_entry(root, name):
    if root is None:
        return None
    shared = _unique_child(root, "shared")
    if shared is None or shared.value_type != packed_xml.TYPE_ELEMENT:
        return None
    entry = _unique_child(shared.value, name)
    if entry is None or entry.value_type != packed_xml.TYPE_ELEMENT:
        return None
    return entry.value


def _matching_hull_variant(hull, chassis_name, turret_group, turret_name):
    """Return the best exact component-matched hull variant, if present."""
    variants = _first_child(hull, "variants")
    if variants is None or variants.value_type != packed_xml.TYPE_ELEMENT:
        return None
    best = None
    best_score = -1
    for unused_name, value in variants.value.children:
        if value.value_type != packed_xml.TYPE_ELEMENT:
            continue
        variant = value.value
        score = 0
        chassis = _first_child(variant, "chassis")
        if chassis is not None:
            if _value_text(chassis) != chassis_name:
                continue
            score += 100
        matched = True
        for raw_name, component in variant.children:
            try:
                name = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if _TURRET_VARIANT_KEY.fullmatch(name) is None:
                continue
            group_name = "turrets" + name[len("turret"):]
            if (group_name != turret_group or
                    _value_text(component) != turret_name):
                matched = False
                break
            score += 1
        if matched and score > best_score and score > 0:
            best = variant
            best_score = score
    return best


def _armor_identity(record):
    parts = str(record.get("fieldPath", "")).split("/")
    if len(parts) < 3 or _ARMOR_FIELD.fullmatch(parts[-1]) is None:
        return None
    category = record.get("category")
    material = parts[-1]
    if category == "vehicle" and parts[:2] == ["hull", "armor"]:
        return ("hull", "hull", material, None)
    if category == "chassis":
        if (parts[0] == "shared" and len(parts) == 4 and
                parts[2] == "armor"):
            return ("chassis", parts[1], material, None)
        if (parts[0] == "chassis" and len(parts) == 4 and
                parts[2] == "armor"):
            return ("chassis", parts[1], material, ("local",))
    if category == "turret":
        if (parts[0] == "shared" and len(parts) == 4 and
                parts[2] == "armor"):
            return ("turret", parts[1], material, None)
        if (_TURRET_GROUP.fullmatch(parts[0]) is not None and
                len(parts) == 4 and parts[2] == "armor"):
            return ("turret", parts[1], material, (parts[0], parts[1]))
    if category == "guns":
        if (parts[0] == "shared" and len(parts) == 4 and
                parts[2] == "armor"):
            return ("gun", parts[1], material, None)
        if (_TURRET_GROUP.fullmatch(parts[0]) is not None and
                len(parts) == 6 and parts[2] == "guns" and
                parts[4] == "armor"):
            return ("gun", parts[3], material, (parts[0], parts[1]))
    return None


def _record_map(records):
    result = {}
    for record in records:
        identity = _armor_identity(record)
        if identity is not None and identity not in result:
            result[identity] = record
    return result


def _focus_identity(record):
    return _armor_identity(record or {})


def _component_roots(package_path, nation):
    result = {}
    for category in ("chassis", "guns", "turrets"):
        member = "scripts/item_defs/vehicles/%s/components/%s.xml" % (
            nation, category)
        try:
            unused_data, result[category] = vehicle_overlays._read_source_member(
                package_path, member)
        except vehicle_overlays.VehicleOverlayError:
            result[category] = None
    return result


def _resource_package_paths(game_root):
    package_root = os.path.join(os.path.abspath(game_root), "res", "packages")
    if not os.path.isdir(package_root):
        raise ArmorViewerError("The stock resource package folder is missing.")
    try:
        names = [name for name in os.listdir(package_root)
                 if name.lower().endswith(".pkg")]
    except OSError as error:
        raise ArmorViewerError(
            "The stock resource package folder is unreadable: %s" % error)
    preferred = [name for name in names
                 if name.startswith("vehicles_") or
                 name.startswith("00_tank_tutorial")]
    remaining = [name for name in names if name not in preferred]
    return tuple(os.path.join(package_root, name)
                 for name in sorted(preferred) + sorted(remaining))


def _resource_directory(member):
    return member.rsplit("/", 1)[0] if "/" in member else member


def _read_resource_member(game_root, member):
    member = re.sub(r"/{2,}", "/", member)
    if (not member.startswith("vehicles/") or "\\" in member or
            member.startswith("/") or ".." in member.split("/")):
        raise ArmorViewerError("The collision resource path is unsafe.")
    root = os.path.realpath(os.path.abspath(game_root))
    directory_key = (root, _resource_directory(member))
    paths = list(_resource_package_paths(root))
    preferred = _RESOURCE_PACKAGE_CACHE.get(directory_key)
    if preferred in paths:
        paths.remove(preferred)
        paths.insert(0, preferred)
    for path in paths:
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        try:
            with zipfile.ZipFile(path, "r") as archive:
                matches = [info for info in archive.infolist()
                           if info.filename == member]
                if len(matches) > 1:
                    raise ArmorViewerError(
                        "A collision resource is repeated in %s." %
                        os.path.basename(path))
                if matches:
                    payload = archive.read(matches[0])
                    _RESOURCE_PACKAGE_CACHE[directory_key] = path
                    return payload
        except ArmorViewerError:
            raise
        except (IOError, OSError, ValueError, zipfile.BadZipFile) as error:
            raise ArmorViewerError(
                "A stock resource package is unreadable: %s" % error)
    raise ArmorViewerError("The stock resource is missing: %s" % member)


def _material_identifiers(visual_root):
    groups = []
    render_sets = _element_children(visual_root, "renderSet")
    for render_set in render_sets:
        for geometry in _element_children(render_set, "geometry"):
            for primitive_group in _element_children(
                    geometry, "primitiveGroup"):
                materials = _element_children(primitive_group, "material")
                identifier = None
                if len(materials) == 1:
                    identifier = _value_text(
                        _unique_child(materials[0], "identifier"))
                groups.append(identifier or "unmapped")
    return tuple(groups)


def _mesh_for_model(game_root, model_member):
    cache_key = (os.path.realpath(os.path.abspath(game_root)), model_member)
    if cache_key in _MESH_CACHE:
        mesh = _MESH_CACHE.pop(cache_key)
        _MESH_CACHE[cache_key] = mesh
        return mesh
    if not model_member.endswith(".model"):
        raise ArmorViewerError("The collision model path is invalid.")
    try:
        model_root = packed_xml.read_packed_xml(
            _read_resource_member(game_root, model_member))
    except (TypeError, ValueError) as error:
        raise ArmorViewerError("The collision model is unreadable: %s" % error)
    visual_base = _value_text(_unique_child(model_root, "nodelessVisual"))
    if not visual_base or not visual_base.startswith("vehicles/"):
        raise ArmorViewerError("The collision model has no nodeless visual.")
    visual_member = visual_base + ".visual_processed"
    primitives_member = visual_base + ".primitives_processed"
    try:
        visual_root = packed_xml.read_packed_xml(
            _read_resource_member(game_root, visual_member))
        sections = _decode_primitives_sections(
            _read_resource_member(game_root, primitives_member))
    except (TypeError, ValueError) as error:
        raise ArmorViewerError(
            "The collision visual is unreadable: %s" % error)

    index_candidates = []
    vertex_candidates = []
    for name, payload in sections.items():
        header = _header_text(payload)
        if header in ("list", "list32", "list32bit"):
            index_candidates.append((name, payload))
        elif len(payload) >= 136 and _header_text(payload, 68):
            remainder = len(payload) - 136
            count = struct.unpack_from("<I", payload, 132)[0]
            if count and remainder >= count * 12 and remainder % count == 0:
                vertex_candidates.append((name, payload))
    if len(index_candidates) != 1 or len(vertex_candidates) != 1:
        raise ArmorViewerError(
            "The collision visual does not have one mesh buffer pair.")
    indices, groups = _decode_index_section(index_candidates[0][1])
    vertices = _decode_vertex_section(vertex_candidates[0][1])
    identifiers = _material_identifiers(visual_root)
    if len(identifiers) != len(groups):
        raise ArmorViewerError(
            "The collision materials and primitive groups do not match.")

    surfaces = []
    for group_index, group in enumerate(groups):
        triangles = []
        start = group["start"]
        for offset in range(group["triangleCount"]):
            point_indices = indices[start + offset * 3:start + offset * 3 + 3]
            if any(index >= len(vertices) for index in point_indices):
                raise ArmorViewerError(
                    "A collision triangle references a missing vertex.")
            triangles.append(tuple(vertices[index] for index in point_indices))
        surfaces.append({
            "material": identifiers[group_index],
            "triangles": tuple(triangles),
        })
    box = _unique_child(visual_root, 'boundingBox')
    bounds = None
    if box is not None and box.value_type == packed_xml.TYPE_ELEMENT:
        low = _vector(_unique_child(box.value, 'min'), default=None)
        high = _vector(_unique_child(box.value, 'max'), default=None)
        if low is not None and high is not None:
            bounds = (low, high)
    result = {"model": model_member, "surfaces": tuple(surfaces), 'bounds': bounds}
    _MESH_CACHE[cache_key] = result
    while len(_MESH_CACHE) > _MESH_CACHE_LIMIT:
        _MESH_CACHE.popitem(last=False)
    return result


def _collision_model(layers):
    value = _layer_values(layers, ("hitTester", "collisionModelClient"))
    path = _value_text(value)
    if not path:
        return None
    return path if path.endswith(".model") else path + ".model"


def _add_points(left, right):
    return tuple(float(left[index]) + float(right[index]) for index in range(3))


def _part_scene(game_root, role, name, layers, offset, records, contexts):
    model = _collision_model(layers)
    if not model:
        return None
    mesh = _mesh_for_model(game_root, model)
    mapping = _record_map(records)
    surfaces = []
    for surface in mesh["surfaces"]:
        material = surface["material"]
        record = next((mapping[(role, name, material, context)]
                       for context in contexts
                       if (role, name, material, context) in mapping), None)
        thickness = None
        if record is not None:
            raw_value = record.get(
                "currentValue", record.get("originalValue"))
            try:
                thickness = float(raw_value)
            except (TypeError, ValueError, OverflowError):
                thickness = None
        factor = _value_text(_layer_values(layers, ('armor', material, 'vehicleDamageFactor')))
        kind = ('tracks' if role == 'chassis' else
                'gun' if role == 'gun' and material == 'gun' else
                'observation' if material == 'surveyingDevice' else
                'spaced' if factor is not None and float(factor) == 0 else 'main')
        translated_triangles = tuple(
            tuple(_add_points(point, offset) for point in triangle)
            for triangle in surface["triangles"])
        surfaces.append({
            "role": role,
            "component": name,
            "material": material,
            "fieldKey": ((record["member"], record["fieldPath"])
                         if record is not None else None),
            "thickness": thickness,
            "armorKind": kind,
            "triangles": translated_triangles,
        })
    return {
        "role": role,
        "component": name,
        "model": model,
        "offset": offset,
        "localBounds": mesh.get('bounds'),
        "surfaces": tuple(surfaces),
    }


def component_choices(vehicle_root, component_roots, translations=None):
    """Mirror #1513 fitting popover's reverse FittingItem comparison.

    Nation and item type are constant within each selector. The remaining
    comparator fields are level, purchase currencies and localized userName.
    Original topology order is the stable tie-break, not a synthetic name sort.
    """
    turrets, guns = [], {}
    def metadata(name, layers):
        raw = _value_text(_layer_values(layers, ('userString',))) or name
        key = raw.rsplit(':',1)[-1].lstrip('#')
        label = translations.gettext(key) if translations else name
        if not label or label == key: label = name
        return dict(name=name, label=label,
                    level=int(float(_value_text(_layer_values(layers, ('level',))) or 0)),
                    price=float(_value_text(_layer_values(layers, ('price',))) or 0))
    for raw_group, value in vehicle_root.children:
        group = raw_group.decode('utf-8')
        if not _TURRET_GROUP.fullmatch(group) or value.value_type != packed_xml.TYPE_ELEMENT:
            continue
        for raw_name, _ in value.value.children:
            name = raw_name.decode('utf-8')
            layers = _entry_layers([vehicle_root], group, name)
            shared = _shared_entry(component_roots.get('turrets'), name)
            if shared is not None: layers.append(shared)
            row = metadata(name, layers)
            row['key'] = (group, name)
            row['guns'] = tuple(_ordered_entry_names(layers, 'guns'))
            turrets.append(row)
            for gun in row['guns']:
                ls = _entry_layers(layers, 'guns', gun)
                shared = _shared_entry(component_roots.get('guns'), gun)
                if shared is not None: ls.append(shared)
                if gun not in guns: guns[gun] = metadata(gun, ls)
    order = lambda row:(row['level'],row['price'],row['label'])
    return dict(turrets=tuple(sorted(turrets,key=order,reverse=True)),
                guns=tuple(sorted(guns.values(),key=order,reverse=True)))


def resolve_mount(choices, current=None, role=None, value=None):
    """Keep the user's new choice, preserve its valid partner, else first fit."""
    current = dict(current or {})
    if role == 'turret': current['turret'] = tuple(value)
    if role == 'gun': current['gun'] = value
    turrets = choices['turrets']
    if not turrets: raise ArmorViewerError('The vehicle has no turret configuration.')
    turret = next((r for r in turrets if r['key'] == tuple(current.get('turret', ()))), None)
    if role == 'turret' and turret is None:
        raise ArmorViewerError('The selected turret is not in the vehicle topology.')
    if role == 'gun' and (turret is None or value not in turret['guns']):
        turret = next((r for r in turrets if value in r['guns']), None)
        if turret is None: raise ArmorViewerError('The selected gun has no compatible turret.')
    if turret is None: turret = turrets[0]
    gun = current.get('gun')
    if gun not in turret['guns']:
        gun = next((r['name'] for r in choices['guns'] if r['name'] in turret['guns']), None)
    if gun is None: raise ArmorViewerError('The selected turret has no gun configuration.')
    return dict(turret=turret['key'], gun=gun)


def _configuration(vehicle_root, component_roots, focus, mounted=None):
    focus_role = focus[0] if focus else None
    focus_name = focus[1] if focus else None
    focus_context = focus[3] if focus else None

    chassis_names = _ordered_entry_names([vehicle_root], "chassis")
    if not chassis_names:
        raise ArmorViewerError("The vehicle has no chassis configuration.")
    chassis_name = (focus_name if focus_role == "chassis" and
                    focus_name in chassis_names else chassis_names[0])
    chassis_layers = _entry_layers([vehicle_root], "chassis", chassis_name)
    shared_chassis = _shared_entry(component_roots.get("chassis"), chassis_name)
    if shared_chassis is not None:
        chassis_layers.append(shared_chassis)

    turret_candidates = []
    for raw_group, value in vehicle_root.children:
        try:
            group_name = raw_group.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if (_TURRET_GROUP.fullmatch(group_name) is not None and
                value.value_type == packed_xml.TYPE_ELEMENT):
            for raw_name, unused_entry in value.value.children:
                try:
                    name = raw_name.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                turret_candidates.append((group_name, name))
    if not turret_candidates:
        raise ArmorViewerError("The vehicle has no turret configuration.")

    chosen_turret = None
    if focus_role == "turret":
        if focus_context is not None:
            chosen_turret = next((item for item in turret_candidates
                                  if item == focus_context), None)
        else:
            chosen_turret = next((item for item in turret_candidates
                                  if item[1] == focus_name), None)
    if focus_role == "gun":
        candidates = turret_candidates
        if focus_context is not None:
            candidates = [item for item in turret_candidates
                          if item == focus_context]
        for item in candidates:
            group = _unique_child(vehicle_root, item[0])
            local_turret = (_unique_child(group.value, item[1])
                            if group is not None and
                            group.value_type == packed_xml.TYPE_ELEMENT
                            else None)
            turret_layers = ([local_turret.value]
                             if local_turret is not None and
                             local_turret.value_type == packed_xml.TYPE_ELEMENT
                             else [])
            shared = _shared_entry(component_roots.get("turrets"), item[1])
            if shared is not None:
                turret_layers.append(shared)
            if focus_name in _ordered_entry_names(turret_layers, "guns"):
                chosen_turret = item
                break
    if mounted is not None:
        chosen_turret = tuple(mounted['turret'])
        if chosen_turret not in turret_candidates:
            raise ArmorViewerError('The selected turret is not in the vehicle topology.')
    if chosen_turret is None:
        chosen_turret = turret_candidates[0]

    turret_group, turret_name = chosen_turret
    group_value = _unique_child(vehicle_root, turret_group)
    local_turret = (_unique_child(group_value.value, turret_name)
                    if group_value is not None and
                    group_value.value_type == packed_xml.TYPE_ELEMENT
                    else None)
    turret_layers = ([local_turret.value]
                     if local_turret is not None and
                     local_turret.value_type == packed_xml.TYPE_ELEMENT
                     else [])
    shared_turret = _shared_entry(component_roots.get("turrets"), turret_name)
    if shared_turret is not None:
        turret_layers.append(shared_turret)

    gun_names = _ordered_entry_names(turret_layers, "guns")
    if not gun_names:
        raise ArmorViewerError("The selected turret has no gun configuration.")
    gun_name = (focus_name if focus_role == "gun" and
                focus_name in gun_names else gun_names[0])
    if mounted is not None:
        gun_name = mounted['gun']
        if gun_name not in gun_names:
            raise ArmorViewerError('The selected gun is not compatible with the turret.')
    gun_layers = _entry_layers(turret_layers, "guns", gun_name)
    shared_gun = _shared_entry(component_roots.get("guns"), gun_name)
    if shared_gun is not None:
        gun_layers.append(shared_gun)

    hull = _unique_child(vehicle_root, "hull")
    if hull is None or hull.value_type != packed_xml.TYPE_ELEMENT:
        raise ArmorViewerError("The vehicle hull descriptor is missing.")
    hull_variant = _matching_hull_variant(
        hull.value, chassis_name, turret_group, turret_name)
    hull_layers = ([hull_variant] if hull_variant is not None else [])
    hull_layers.append(hull.value)
    return {
        "chassis": (chassis_name, chassis_layers),
        "hull": ("hull", hull_layers),
        "turret": (turret_group, turret_name, turret_layers),
        "gun": (gun_name, gun_layers),
    }


def _scene_bounds(parts):
    points = [point for part in parts for surface in part["surfaces"]
              for triangle in surface["triangles"] for point in triangle]
    if not points:
        raise ArmorViewerError("The collision scene contains no triangles.")
    minimum = tuple(min(point[index] for point in points) for index in range(3))
    maximum = tuple(max(point[index] for point in points) for index in range(3))
    return minimum, maximum


def load_vehicle_armor_scene(game_root, vehicle_member, records,
                             focus_record=None, mounted=None):
    """Load one mounted configuration around the requested armor field."""
    status, package_path = vehicle_overlays._require_target(game_root)
    match = vehicle_overlays._VEHICLE_MEMBER.fullmatch(vehicle_member)
    if match is None or "/components/" in vehicle_member:
        raise ArmorViewerError("Select one original vehicle definition.")
    nation, unused_vehicle = match.groups()
    try:
        unused_data, vehicle_root = vehicle_overlays._read_source_member(
            package_path, vehicle_member)
    except vehicle_overlays.VehicleOverlayError as error:
        raise ArmorViewerError(str(error))
    component_roots = _component_roots(package_path, nation)
    focus = _focus_identity(focus_record)
    choices = component_choices(vehicle_root, component_roots,
        vehicle_overlays._vehicle_translations(status['path'], nation))
    resolved = resolve_mount(choices, mounted) if mounted is not None else None
    config = _configuration(vehicle_root, component_roots, focus, resolved)

    chassis_name, chassis_layers = config["chassis"]
    hull_name, hull_layers = config["hull"]
    turret_group, turret_name, turret_layers = config["turret"]
    gun_name, gun_layers = config["gun"]
    hull_position = _vector(_layer_values(chassis_layers, ("hullPosition",)))
    turret_positions = _layer_elements(hull_layers, ("turretPositions",))
    try:
        turret_slot = int(turret_group[len("turrets"):])
    except (TypeError, ValueError):
        raise ArmorViewerError("The turret group has no valid position slot.")
    if not turret_positions or turret_slot >= len(turret_positions[0].children):
        raise ArmorViewerError(
            "The hull has no position for %s." % turret_group)
    turret_position = _vector(
        turret_positions[0].children[turret_slot][1], default=None)
    if turret_position is None:
        raise ArmorViewerError(
            "The hull position for %s is invalid." % turret_group)
    gun_position = _vector(_layer_values(turret_layers, ("gunPosition",)))
    turret_offset = _add_points(hull_position, turret_position)
    gun_offset = _add_points(turret_offset, gun_position)

    specs = (
        ("chassis", chassis_name, chassis_layers, (0.0, 0.0, 0.0),
         (("local",), None)),
        ("hull", hull_name, hull_layers, hull_position, (None,)),
        ("turret", turret_name, turret_layers, turret_offset,
         ((turret_group, turret_name), None)),
        ("gun", gun_name, gun_layers, gun_offset,
         ((turret_group, turret_name), None)),
    )
    parts = []
    errors = []
    for role, name, layers, offset, contexts in specs:
        try:
            part = _part_scene(
                status["path"], role, name, layers, offset, records, contexts)
        except ArmorViewerError as error:
            errors.append("%s: %s" % (role, error))
            continue
        if part is not None:
            parts.append(part)
    if not parts:
        raise ArmorViewerError("; ".join(errors) or
                               "No stock collision models were found.")
    crew = _unique_child(vehicle_root, "crew")
    roles = tuple((key.decode("ascii"),) + tuple((_value_text(value) or "").split())
                  for key, value in crew.value.children) if (
                      crew is not None and crew.value_type == packed_xml.TYPE_ELEMENT) else ()
    return {
        "componentChoices": choices,
        "crewRoles": roles,
        "vehicleMember": vehicle_member,
        "configuration": {
            "chassis": chassis_name,
            "turretGroup": turret_group,
            "turret": turret_name,
            "gun": gun_name,
        },
        "parts": tuple(parts),
        "bounds": _scene_bounds(parts),
        "warnings": tuple(errors),
    }


def _interpolate(left, right, amount):
    return tuple(int(round(left[index] + (right[index] - left[index]) * amount))
                 for index in range(3))


# Vehicle-relative thickness ramps, matching the two-scale collision-view
# convention observed on tanks.gg. Neither scale is penetration probability.
_PRIMARY_PALETTE = ((0., (20, 196, 36)), (.5, (245, 221, 40)), (1., (239, 39, 29)))
_SECONDARY_PALETTE = ((0., (31, 211, 217)), (.33, (48, 135, 239)),
                      (.66, (83, 39, 231)), (1., (229, 30, 219)))


def thickness_color(thickness, maximum=400., secondary=False):
    try:
        value = float(thickness)
        if not math.isfinite(value) or value < 0:
            return '#555b66'
    except (TypeError, ValueError, OverflowError):
        return '#555b66'
    fraction = min(1., value / max(1., maximum))
    palette = _SECONDARY_PALETTE if secondary else _PRIMARY_PALETTE
    for (low, left), (high, right) in zip(palette, palette[1:]):
        if fraction <= high:
            return '#%02x%02x%02x' % _interpolate(left, right, (fraction-low)/(high-low))
    return '#%02x%02x%02x' % palette[-1][1]


def _palette_group(surface):
    kind = surface.get('armorKind', 'tracks' if surface.get('role') == 'chassis' else 'main')
    return 'main' if kind == 'main' else 'external'


def _armor_scales(scene):
    values = {'main': {0.}, 'external': {0.}}
    present = set()
    for part in (scene or {}).get('parts', ()):
        for surface in part['surfaces']:
            value = surface.get('thickness')
            if value is not None and math.isfinite(value) and value >= 0:
                group = _palette_group(surface)
                present.add(group)
                values[group].add(value)
    return {group: sorted(values[group]) for group in values if group in present}


def _armor_color(surface, scales):
    group = _palette_group(surface)
    return thickness_color(surface.get('thickness'), max(scales.get(group, (1.,))), group == 'external')


def _shade(color, amount):
    raw = color.lstrip("#")
    base = tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))
    if amount >= 0:
        target = (255, 255, 255)
        result = _interpolate(base, target, min(1.0, amount))
    else:
        result = _interpolate(base, (0, 0, 0), min(1.0, -amount))
    return "#%02x%02x%02x" % result


def _surface_edges(triangles, boundary_only=False):
    """Keep open/silhouette edges, dropping shared tessellation diagonals."""
    edges = {}
    for unused_depth, points, surface, area in triangles:
        component = (surface.get('role'), surface.get('component'))
        for index in range(3):
            a, b = points[index], points[(index + 1) % 3]
            endpoints = tuple(sorted(tuple(round(value, 5) for value in p)
                                     for p in (a, b)))
            key = (component, endpoints)
            record = edges.setdefault(key, [[], (a[0], a[1], b[0], b[1])])
            record[0].append(area > 0)
    return [coords for signs, coords in edges.values()
            if len(signs) == 1 or (not boundary_only and any(signs) and not all(signs))]


def _face_light(points, depth_scale):
    """Stable camera-space lighting without showing triangle boundaries."""
    edges = [((point[0] - points[0][0]), -(point[1] - points[0][1]),
              (point[2] - points[0][2]) * depth_scale) for point in points[1:]]
    a, b = edges
    normal = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    length = math.sqrt(sum(value*value for value in normal))
    if not length:
        return 0.0
    direction = -1 if normal[2] < 0 else 1
    intensity = sum(normal[i]*direction*light for i, light in enumerate((-.4, .7, .6))) / length
    return -.10 + .22 * max(0.0, min(1.0, intensity))


class ArmorViewerPanel(object):
    """Depth-buffered scene presentation with orbit, visibility and picking."""

    def __init__(self, parent, tk_module, on_select, language, game_root,
                 scene_loader=load_vehicle_armor_scene, gpu_factory=None):
        self._tk = tk_module
        self._on_select = on_select
        self._language = i18n.resolve_language(language)
        self._game_root = game_root
        self._scene_loader = scene_loader
        self._mounted = {} if scene_loader is load_vehicle_armor_scene else None
        self._component_choices = {}
        self._gpu_factory = gpu_factory
        self._gpu = None
        self._gpu_attempted = False
        self._gpu_key = None
        self._gpu_objects = []
        self._frame_times = []
        self._diagnostic = lambda message: None
        self._vehicle_member = None
        self._records = []
        self._record_by_key = {}
        self._focus_key = None
        self._scene = None
        self._view_mode = 'armor'
        self._internal_scene = None
        self._scene_error = ""
        self._scene_error_source = ""
        self._language_widgets = []
        self._yaw = -0.65
        self._pitch = -0.22
        self._zoom = 1.0
        self._drag_start = None
        self._drag_last = None
        self._dragged = False
        self._render_pending = None
        self._item_surface = {}
        self._selected_module = None
        self._shell_image = None
        self._pick_buffer = None
        self._hidden = set()
        self._group_visible = {}
        self._settings_window = None
        self._shell_alpha = tk_module.DoubleVar(value=16)
        self._module_alpha = tk_module.DoubleVar(value=85)

        self.frame = tk_module.Frame(parent, borderwidth=1, relief="solid",
                                     padx=8, pady=8)
        self.title_label = self._widget(tk_module.Label, self.frame,
            text="3D armor viewer", anchor="w", padx=0, pady=0)
        self.title_label.grid(row=0, column=0, sticky="we", pady=(0, 6))
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(5, weight=1)
        modes = tk_module.Frame(self.frame)
        modes.grid(row=1, column=0, sticky='ew')
        self._widget(tk_module.Button, modes, text='Armor',
                     command=lambda: self.set_view_mode('armor')).pack(side='left', fill='x', expand=True)
        self._widget(tk_module.Button, modes, text='X-ray',
                     command=lambda: self.set_view_mode('internal')).pack(side='left', fill='x', expand=True)
        self.help_label = self._widget(tk_module.Label,
            self.frame,
            text="Drag to orbit · wheel to zoom · click armor to select its field",
            anchor="w", justify="left", wraplength=520, padx=0, pady=0)
        self.help_label.grid(row=2, column=0, sticky="we", pady=(4, 0))
        self.selection = tk_module.StringVar(
            value=self._t("No armor field selected"))
        self.selection_label = self._widget(tk_module.Label,
            self.frame, textvariable=self.selection, anchor="w",
            justify="left", wraplength=520)
        self.selection_label.grid(row=3, column=0, sticky="we", pady=(4, 6))
        self.canvas = tk_module.Canvas(
            self.frame, width=540, height=500, background="#171b22",
            highlightthickness=1, highlightbackground="#414958")
        display = tk_module.Frame(self.frame)
        display.grid(row=4, column=0, sticky='ew', pady=(0, 4))
        self._display_buttons = []
        for index in range(3):
            var = tk_module.BooleanVar(value=True)
            button = tk_module.Checkbutton(display, variable=var, anchor='w', padx=0,
                command=lambda i=index: self._toggle_group(i))
            button.grid(row=0, column=index, sticky='ew')
            display.grid_columnconfigure(index, weight=1, uniform='display')
            self._display_buttons.append((button, var))
        self._widget(tk_module.Button, display, text='Display settings',
                     command=self._open_settings).grid(row=1, column=0, columnspan=3, sticky='ew')
        self.canvas.grid(row=5, column=0, sticky="nsew")
        controls = tk_module.Frame(self.frame)
        controls.grid(row=6, column=0, sticky="we", pady=(6, 0))
        self.legend_label = self._widget(tk_module.Label,
            controls, text="Nominal thickness (mm)",
            anchor="w", padx=0, pady=0)
        self.legend_label.pack(fill="x", pady=(0, 4))
        self.legend = tk_module.Frame(controls)
        self.legend.pack(fill="x")
        self._legend_cells = []
        self.reset_button = self._widget(tk_module.Button,
            self.frame, text="Reset view", command=self.reset_view)
        self.reset_button.grid(row=7, column=0, sticky="ew", pady=(6, 0))
        self.legend.bind('<Configure>', self._layout_legend)
        self._draw_legend()

        self.canvas.bind("<Configure>", self._redraw)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_by(1.12))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_by(1.0 / 1.12))
        self.frame.bind('<Configure>', self._wrap_text)
        self.frame.bind('<Destroy>', self._destroy_renderer)
        from tkinter import ttk
        mounts = tk_module.Frame(self.frame)
        for widget in (self.help_label, self.selection_label, display, self.canvas,
                       controls, self.reset_button):
            widget.grid_configure(row=int(widget.grid_info()['row'])+1)
        self.frame.grid_rowconfigure(5, weight=0)
        self.frame.grid_rowconfigure(6, weight=1)
        mounts.grid(row=2, column=0, sticky='ew', pady=(4, 0))
        self._mount_boxes = {}
        for column, (role, label) in enumerate((('turret', 'Preview turret'), ('gun', 'Preview gun'))):
            box = tk_module.Frame(mounts)
            box.grid(row=0, column=column, sticky='ew', padx=(0 if column == 0 else 4, 4 if column == 0 else 0))
            mounts.grid_columnconfigure(column, weight=1, uniform='mount')
            self._widget(tk_module.Label, box, text=label, anchor='w').pack(fill='x')
            combo = ttk.Combobox(box, state='disabled', width=12)
            combo.pack(fill='x')
            combo.bind('<<ComboboxSelected>>', lambda event, r=role: self._change_mount(r))
            self._mount_boxes[role] = combo

    def set_diagnostic_callback(self, callback):
        self._diagnostic = callback

    def _destroy_renderer(self, event):
        if event.widget is not self.frame:
            return
        if self._frame_times:
            import numpy as np
            self._diagnostic('Viewer frames: count=%d p50=%.2fms p95=%.2fms backend=%s' % (
                len(self._frame_times), np.percentile(self._frame_times, 50),
                np.percentile(self._frame_times, 95), 'OpenGL' if self._gpu else 'CPU'))
        if self._gpu:
            self._gpu.release()
            self._gpu = None

    def _refresh_mounts(self):
        if not self._component_choices:
            return
        config = self._scene['configuration']
        self._mounted = dict(turret=(config['turretGroup'], config['turret']), gun=config['gun'])
        for role, combo in self._mount_boxes.items():
            rows = self._component_choices[role+'s']
            combo.configure(values=[row['label'] if row['label'] == row['name'] else
                                    row['label'] + ' (' + row['name'] + ')' for row in rows],
                            state='readonly' if len(rows)>1 else 'disabled')
            combo.current(next(i for i, row in enumerate(rows)
                               if (row['key'] if role == 'turret' else row['name']) == self._mounted[role]))

    def _change_mount(self, role):
        row = self._component_choices[role+'s'][self._mount_boxes[role].current()]
        self._mounted = resolve_mount(self._component_choices, self._mounted, role,
                                     row['key'] if role == 'turret' else row['name'])
        self._hidden.clear()
        self._load_scene(self._record_by_key.get(self._focus_key))

    def _widget(self, factory, parent, text=None, **options):
        if text is not None:
            options['text'] = self._t(text)
        widget = factory(parent, **options)
        if text is not None:
            self._language_widgets.append((widget, text))
        return widget

    def set_language(self, language):
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None
        self._language = i18n.resolve_language(language)
        for widget, text in self._language_widgets:
            widget.config(text=self._t(text))
        self._refresh_groups()
        if self._view_mode == 'internal':
            self.set_view_mode('internal')
            return
        self._draw_legend()
        if self._scene_error_source:
            self._scene_error = self._t('Armor model unavailable: %s') % self._scene_error_source
        record = self._record_by_key.get(self._focus_key)
        if record is not None:
            self.focus_field(record, reload_scene=False)
        else:
            self.selection.set(self._scene_error or self._t('No armor field selected'))
            self._redraw()

    def _t(self, text):
        return _translated(self._language, text)

    def grid(self, *args, **kwargs):
        return self.frame.grid(*args, **kwargs)

    def load_vehicle(self, vehicle_member, records, focus_record=None):
        self._mounted = {} if self._scene_loader is load_vehicle_armor_scene else None
        self._component_choices = {}
        for combo in self._mount_boxes.values():
            combo.set('')
            combo.configure(values=(), state='disabled')
        self._internal_scene = None
        self._hidden.clear()
        self._group_visible.clear()
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None
        self._vehicle_member = vehicle_member
        self._records = [dict(record) for record in records]
        self._record_by_key = dict(
            ((record["member"], record["fieldPath"]), record)
            for record in self._records)
        self._focus_key = None
        self.selection.set(self._t("Loading stock collision model..."))
        self._load_scene(focus_record)

    def _load_scene(self, focus_record=None):
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None
        if not self._vehicle_member:
            return False
        # A field can select a different stock turret/gun on the same tank.
        # Revalidate interiors against that component rather than its old mesh.
        self._internal_scene = None
        self._selected_module = None
        try:
            options = dict(focus_record=focus_record)
            if self._mounted is not None:
                options['mounted'] = self._mounted
            self._scene = self._scene_loader(
                self._game_root, self._vehicle_member, self._records,
                **options)
        except (ArmorViewerError, vehicle_overlays.VehicleOverlayError,
                IOError, OSError, ValueError, zipfile.BadZipFile) as error:
            self._scene = None
            self._scene_error_source = str(error)
            self._scene_error = self._t("Armor model unavailable: %s") % error
            self.selection.set(self._scene_error)
            self._redraw()
            return False
        self._scene_error = ""
        self._scene_error_source = ""
        self._component_choices = self._scene.get('componentChoices', {})
        self._refresh_mounts()
        if getattr(self, '_view_mode', 'armor') == 'internal':
            self.set_view_mode('internal')
            return True
        self._refresh_groups()
        self._draw_legend()
        self._redraw()
        if focus_record is None:
            self.selection.set(self._t(
                "Click an armor surface or choose an armor field."))
            return True
        return self.focus_field(focus_record, reload_scene=False)

    def set_view_mode(self, mode):
        self._view_mode = mode
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None
        self.help_label.config(text=self._t(
            'Drag to orbit · wheel to zoom · click a module to inspect it'
            if mode == 'internal' else
            'Drag to orbit · wheel to zoom · click armor to select its field'))
        if mode == 'internal' and self._scene is not None:
            try:
                from . import vehicle_internal_viewer
            except ImportError:
                import vehicle_internal_viewer
            if self._internal_scene is None:
                try:
                    self._internal_scene = vehicle_internal_viewer.load_scene(self._scene)
                except (ValueError, OSError, KeyError, IndexError, struct.error, zlib.error) as error:
                    self._internal_scene = dict(self._scene, parts=(), warnings=(str(error),))
                # Exact PC observation surfaces supersede the absent Console
                # observation zone, without changing any interior geometry.
                if any(s.get('armorKind') == 'observation' and s.get('triangles')
                       for p in self._scene['parts'] for s in p['surfaces']):
                    self._internal_scene = dict(self._internal_scene, warnings=tuple(
                        w for w in self._internal_scene.get('warnings', ())
                        if w != 'surveyingDevice' and not w.startswith('surveyingDevice: ')))
                if self._internal_scene.get('warnings'):
                    from tkinter import messagebox
                    messagebox.showwarning(self._t('Internal module data'),
                        self._t('Some interior data is unavailable:\n%s') % '\n'.join(
                            self._internal_warning(warning)
                            for warning in self._internal_scene['warnings']), parent=self.frame)
            self.selection.set(self._surface_name(self._selected_module)
                if self._selected_module else self._t(
                    'Console-sourced surfaces; selected PC frame verified. Missing modules are not drawn.'))
        elif mode == 'armor':
            self.selection.set(self._t('Click an armor surface or choose an armor field.'))
        self.legend_label.config(text=self._t(
            'Modules and crew' if mode == 'internal' else 'Nominal thickness (mm)'))
        self._refresh_groups()
        self._draw_legend()
        self._redraw()

    def focus_field(self, record, reload_scene=True):
        identity = _focus_identity(record)
        new_key = ((record.get("member"), record.get("fieldPath"))
                   if identity is not None else None)
        if (reload_scene and getattr(self, '_mounted', None) is None and new_key is not None and self._scene is not None and
                not self._scene_contains_key(new_key)):
            self._focus_key = new_key
            return self._load_scene(record)
        self._focus_key = new_key
        if self._view_mode == 'internal':
            self.set_view_mode('internal')
            return
        if new_key is None:
            self.selection.set(
                self._scene_error if self._scene is None and self._scene_error
                else self._t("No armor field selected"))
        elif self._scene is None:
            self.selection.set(self._scene_error or self._t(
                "Selected: %s · %s mm · no surface in this collision model") % (
                    record.get("fieldLabel", record.get("fieldPath", "-")),
                    record.get("currentValue",
                               record.get("originalValue", "-"))))
        elif not self._scene_contains_key(new_key):
            current = record.get("currentValue", record.get("originalValue", "-"))
            self.selection.set(self._t(
                "Selected: %s · %s mm · no surface in this collision model") % (
                    record.get("fieldLabel", record.get("fieldPath", "-")),
                    current))
        else:
            current = record.get("currentValue", record.get("originalValue", "-"))
            self.selection.set(self._t("Selected: %s · %s mm") % (
                record.get("fieldLabel", record.get("fieldPath", "-")), current))
        if self._scene is not None and new_key is not None:
            selected_surface = next((surface for part in self._scene['parts']
                for surface in part['surfaces'] if surface.get('fieldKey') == new_key), None)
            if selected_surface and _palette_group(selected_surface) == 'external':
                source = {'tracks':'Tracks (external module)', 'gun':'Gun',
                          'spaced':'Spaced armor', 'observation':'Observation devices'}.get(
                              selected_surface.get('armorKind'), 'Tracks (external module)')
                self.selection.set(self.selection.get() + ' · ' + self._t(source))
        self._redraw()
        return new_key is not None and self._scene_contains_key(new_key)

    def _scene_contains_key(self, key):
        if self._scene is None:
            return False
        return any(surface.get("fieldKey") == key
                   for part in self._scene["parts"]
                   for surface in part["surfaces"])

    def update_field(self, member, field_path, current_value):
        key = (member, field_path)
        record = self._record_by_key.get(key)
        if record is None:
            return False
        record["currentValue"] = str(current_value)
        for current in self._records:
            if (current["member"], current["fieldPath"]) == key:
                current["currentValue"] = str(current_value)
        if self._scene is not None:
            for part in self._scene["parts"]:
                for surface in part["surfaces"]:
                    if surface["fieldKey"] == key:
                        try:
                            surface["thickness"] = float(current_value)
                        except (TypeError, ValueError, OverflowError):
                            surface["thickness"] = None
        self._draw_legend()
        if self._focus_key == key:
            self.focus_field(record, reload_scene=False)
        else:
            self._redraw()
        return True

    def reset_values(self):
        for record in self._records:
            record["currentValue"] = record.get("originalValue", "0")
        focus = self._record_by_key.get(self._focus_key)
        self._load_scene(focus)

    def reset_view(self):
        self._yaw = -0.65
        self._pitch = -0.22
        self._zoom = 1.0
        self._redraw()

    def _draw_legend(self):
        from tkinter import font as tkfont
        for child in self.legend.winfo_children():
            child.destroy()
        self._legend_cells = []
        self._legend_headers = []
        self._legend_minwidth = 1
        if getattr(self, '_view_mode', 'armor') == 'internal':
            try:
                from .vehicle_internal_viewer import MODULE_STYLES
            except ImportError:
                from vehicle_internal_viewer import MODULE_STYLES
            scene = self._internal_scene
            present = {surface.get('moduleEntity')
                       for part in (scene or {}).get('parts', ())
                       for surface in part['surfaces']}
            missing = (scene or {}).get('warnings', ())
            entries = []
            armor = [s for p in (self._scene or {}).get('parts', ()) for s in p['surfaces']]
            for kind, source, color in (('tracks','Tracks','#a35edb'), ('gun','Gun','#3689f5'),
                                       ('observation','Observation devices','#22dced')):
                exists = any(s.get('armorKind') == kind and s.get('triangles') for s in armor)
                label = self._t(source) if exists else self._t('%s (no data)') % self._t(source)
                entries.append((label, color if exists else '#838b97', 'External modules'))
            for entity, source, color in MODULE_STYLES:
                if entity == 'surveyingDevice':
                    continue
                label = self._t(source)
                if scene is not None and entity not in present:
                    label = self._t('%s (no data)') % label
                    color = '#838b97'
                elif any(entity in warning for warning in missing):
                    label = self._t('%s (incomplete)') % label
                entries.append((label, color, 'Internal modules'))
            present_seats = {surface.get('moduleLabel', '').split(' / ')[0]
                             for part in (scene or {}).get('parts', ())
                             for surface in part['surfaces']}
            for slot in (scene or {}).get('crewSlots', ()):
                label, color = self._crew_caption(slot), slot['color']
                if slot['identity'] not in present_seats:
                    label, color = self._t('%s (no data)') % label, '#838b97'
                entries.append((label, color, 'Crew'))
        else:
            scales = _armor_scales(self._scene)
            entries = []
            surfaces = [s for p in (self._scene or {}).get('parts', ()) for s in p['surfaces']]
            for group in ('Main armor', 'Spaced armor', 'External modules'):
                selected = [s for s in surfaces if self._surface_group(s) == group]
                if group == 'External modules':
                    for kind, source, color in (('tracks','Tracks','#a35edb'), ('gun','Gun','#3689f5'),
                                               ('observation','Observation devices','#22dced')):
                        exists = any(s.get('armorKind') == kind for s in selected)
                        entries.append((self._t(source) if exists else self._t('%s (no data)') % self._t(source),
                                        color if exists else '#838b97', group))
                    continue
                values = sorted({0.} | {s['thickness'] for s in selected
                    if s.get('thickness') is not None and math.isfinite(s['thickness']) and s['thickness'] >= 0})
                if not selected:
                    entries.append((self._t('No geometry'), '#838b97', group))
                    continue
                maximum = max(scales.get('main' if group == 'Main armor' else 'external', [0.]))
                ticks = values if len(values) <= 7 else [max(values)*i/6 for i in range(7)]
                entries.extend((('%g' % round(value, 1)), thickness_color(value, maximum, group != 'Main armor'),
                                group) for value in ticks)
            if any(surface.get('thickness') is None
                   for part in (self._scene or {}).get('parts', ())
                   for surface in part['surfaces']):
                entries.append((self._t('Unmapped'), '#555b66', None))
        last_group = None
        for label, color, group in entries:
            if group != last_group and group is not None:
                header = self._tk.Label(self.legend, text=self._t(group), anchor='w', padx=0)
                self._legend_headers.append((len(self._legend_cells), header))
            last_group = group
            cell = self._tk.Frame(self.legend)
            swatch = self._tk.Canvas(cell, width=16, height=12,
                                     highlightthickness=0)
            swatch.create_rectangle(0, 0, 16, 12, fill=color, outline='')
            swatch.pack(side='left', padx=(0, 6))
            caption = self._tk.Label(cell, text=label, anchor='w', padx=0, pady=0)
            caption.pack(side='left')
            font = tkfont.Font(root=self.legend, font=caption.cget('font'))
            self._legend_minwidth = max(self._legend_minwidth, min(180, font.measure(label) + 34))
            self._legend_cells.append(cell)
        self._legend_columns = None
        self._layout_legend()

    def _layout_legend(self, unused_event=None):
        cells = self._legend_cells
        if not cells:
            return
        available = max(1, self.legend.winfo_width())
        requested = self._legend_minwidth
        columns = min(len(cells), max(1, available // max(1, requested)))
        if columns == self._legend_columns and available == getattr(self, "_legend_width", None):
            return
        self._legend_width = available
        for index in range(len(cells)):
            self.legend.grid_columnconfigure(index, weight=0, uniform='')
        for index in range(columns):
            self.legend.grid_columnconfigure(index, weight=1, uniform='legend')
        headers = dict(getattr(self, '_legend_headers', ()))
        row, column = 0, 0
        for index, cell in enumerate(cells):
            for child in cell.winfo_children():
                if isinstance(child, self._tk.Label):
                    child.configure(wraplength=max(80, available // columns - 34))
            if index in headers:
                if column:
                    row += 1
                headers[index].grid(row=row, column=0, columnspan=columns, sticky='ew', pady=(2, 4))
                row, column = row+1, 0
            cell.grid(row=row, column=column, sticky='nw',
                      padx=(0, 6 if column < columns-1 else 0), pady=(0, 4))
            column += 1
            if column == columns:
                row, column = row+1, 0
        self._legend_columns = columns

    def _wrap_text(self, event):
        if event.widget is self.frame:
            available = max(120, event.width - 18)
            self.help_label.config(wraplength=available)
            self.selection_label.config(wraplength=available)

    def _crew_caption(self, slot):
        try:
            from .vehicle_internal_viewer import CREW_STYLES
        except ImportError:
            from vehicle_internal_viewer import CREW_STYLES
        roles = slot['roles']
        names = [self._t(CREW_STYLES.get(role, (role, ''))[0]) for role in roles]
        primary = names[0] + (str(slot['number']) if slot.get('number') else '')
        return self._t('%s (also %s)') % (primary, ' / '.join(names[1:])) if len(names)>1 else primary

    def _module_caption(self, surface):
        try:
            from .vehicle_internal_viewer import MODULE_STYLES
        except ImportError:
            from vehicle_internal_viewer import MODULE_STYLES
        identity = surface['moduleLabel'].split(' / ')[0]
        slot = surface.get('crewSlot') or next((slot for slot in
            (self._internal_scene or {}).get('crewSlots', ()) if slot['identity'] == identity), None)
        if slot:
            return self._crew_caption(slot)
        if identity.startswith('crew '):
            return self._t('Crew %s') % identity.split()[-1]
        names = {entity: label for entity, label, unused_color in MODULE_STYLES}
        names['transmission'] = 'Transmission'
        return self._t(names.get(identity, identity))

    def _internal_warning(self, warning):
        if ': ' in warning:
            name, detail = warning.split(': ', 1)
            return '%s: %s' % (self._module_caption({'moduleLabel': name}),
                               self._t(detail))
        return self._t(self._module_caption({'moduleLabel': warning}))

    def _press(self, event):
        self._drag_start = (event.x, event.y)
        self._drag_last = (event.x, event.y)
        self._dragged = False

    def _drag(self, event):
        if self._drag_last is None:
            return
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        if abs(event.x - self._drag_start[0]) + abs(
                event.y - self._drag_start[1]) > 4:
            self._dragged = True
        self._yaw += dx * 0.012
        self._pitch = max(-1.35, min(1.35, self._pitch + dy * 0.009))
        self._drag_last = (event.x, event.y)
        if self._render_pending is None:
            def render_latest():
                self._render_pending = None
                self._redraw()
            self._render_pending = self.canvas.after_idle(render_latest)

    def _release(self, event):
        if not self._dragged:
            self._pick(event.x, event.y)
        dragged = self._dragged
        self._drag_start = None
        self._drag_last = None
        self._dragged = False
        if self._render_pending is not None:
            self.canvas.after_cancel(self._render_pending)
            self._render_pending = None
        if dragged:
            self._redraw()

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            self._zoom_by(1.12 if delta > 0 else 1.0 / 1.12)

    def _zoom_by(self, factor):
        self._zoom = max(0.45, min(3.5, self._zoom * factor))
        self._redraw()
        return "break"

    def _pick(self, x, y):
        surface = None
        if self._gpu is not None:
            cw, ch = self._pick_size
            w, h = self._gpu._size[:2]
            surface = self._item_surface.get(self._gpu.pick(int(x*w/cw), int(y*h/ch)))
        elif self._pick_buffer is not None:
            h, w = self._pick_buffer.shape
            cw, ch = self._pick_size
            px, py = int(x*w/cw), int(y*h/ch)
            if 0 <= px < w and 0 <= py < h:
                surface = self._item_surface.get(int(self._pick_buffer[py, px]))
        if surface is None:
            return False
        if self._view_mode == 'internal':
            self._selected_module = surface
            self.selection.set(self._surface_name(surface))
            self._redraw()
            return True
        key = surface.get("fieldKey")
        if key is None or key not in self._record_by_key:
            self.selection.set(self._t(
                "Material %s has no editable thickness field.") %
                surface.get("material", "unmapped"))
            return False
        self._on_select(key)
        return True

    def _projected_triangles(self, width, height, scene=None):
        if self._scene is None:
            return []
        minimum, maximum = self._scene["bounds"]
        center = tuple((minimum[index] + maximum[index]) * 0.5
                       for index in range(3))
        radius = max(maximum[index] - minimum[index] for index in range(3)) * 0.5
        radius = max(radius, 0.001)
        scale = min(width, height) * 0.43 * self._zoom / radius
        cosine_yaw, sine_yaw = math.cos(self._yaw), math.sin(self._yaw)
        cosine_pitch, sine_pitch = math.cos(self._pitch), math.sin(self._pitch)

        screen_x, screen_y = width*.5, height*.5

        def project(point):
            x = point[0] - center[0]
            y = point[1] - center[1]
            z = point[2] - center[2]
            rotated_x = cosine_yaw * x + sine_yaw * z
            rotated_z = -sine_yaw * x + cosine_yaw * z
            rotated_y = cosine_pitch * y - sine_pitch * rotated_z
            depth = sine_pitch * y + cosine_pitch * rotated_z
            return (screen_x + rotated_x * scale,
                    screen_y - rotated_y * scale, depth)

        framing_points = [project(point) for part in self._scene['parts']
                          for surface in part['surfaces'] for triangle in surface['triangles']
                          for point in triangle]
        if framing_points:
            left, right = min(p[0] for p in framing_points), max(p[0] for p in framing_points)
            top, bottom = min(p[1] for p in framing_points), max(p[1] for p in framing_points)
            fit = min(width*.90/max(1.,right-left), height*.86/max(1.,bottom-top))
            factor = fit*self._zoom
            screen_x -= ((left+right)*.5-width*.5)*factor
            screen_y -= ((top+bottom)*.5-height*.5)*factor
            scale *= factor
        self._projection_scale = scale
        result = []
        if scene is None:
            scene = (self._internal_scene if getattr(self, '_view_mode', 'armor') == 'internal'
                     else self._scene)
        for part in (scene or {}).get('parts', ()):
            for surface in part["surfaces"]:
                for triangle in surface["triangles"]:
                    projected = tuple(project(point) for point in triangle)
                    area = ((projected[1][0] - projected[0][0]) *
                            (projected[2][1] - projected[0][1]) -
                            (projected[1][1] - projected[0][1]) *
                            (projected[2][0] - projected[0][0]))
                    if abs(area) < 0.05:
                        continue
                    result.append((
                        sum(point[2] for point in projected) / 3.0,
                        projected, surface, area))
        result.sort(key=lambda item: item[0])
        return result

    def _surface_group(self, surface):
        if surface.get('moduleEntity'):
            return 'Crew' if surface['moduleEntity'] == 'crew' else (
                'External modules' if surface['moduleEntity'] == 'surveyingDevice' else 'Internal modules')
        return {'tracks':'External modules', 'gun':'External modules',
                'observation':'External modules', 'spaced':'Spaced armor'}.get(
                    surface.get('armorKind'), 'Main armor')

    def _surface_identity(self, surface):
        group = self._surface_group(surface)
        if surface.get('moduleLabel'):
            return (group, surface['moduleLabel'].split(' / ')[0])
        return (group, surface.get('armorKind', 'main'), surface.get('role', ''),
                surface.get('component', ''))

    def _surface_name(self, surface):
        if surface.get('moduleLabel'):
            return self._module_caption(surface)
        kind = surface.get('armorKind', 'main')
        name = self._t({'tracks':'Tracks', 'gun':'Gun', 'observation':'Observation devices'}.get(
            kind, {'hull':'Hull', 'turret':'Turret', 'chassis':'Chassis', 'gun':'Gun'}.get(
                surface.get('role'), 'Main armor')))
        if kind == 'observation' and surface.get('role'):
            name += ' / ' + self._t({'hull':'Hull', 'turret':'Turret', 'gun':'Gun',
                                    'chassis':'Chassis'}.get(surface['role'], surface['role']))
        return name

    def _groups(self):
        return (('External modules', 'Internal modules', 'Crew') if self._view_mode == 'internal'
                else ('Main armor', 'Spaced armor', 'External modules'))

    def _surfaces(self):
        armor = [s for p in (self._scene or {}).get('parts', ()) for s in p['surfaces']]
        if self._view_mode != 'internal':
            return armor
        external = [s for s in armor if self._surface_group(s) == 'External modules']
        inside = [s for p in (self._internal_scene or {}).get('parts', ()) for s in p['surfaces']
                  if s.get('moduleEntity') != 'surveyingDevice']
        return external+inside

    def _visible(self, surface):
        return (self._group_visible.get(self._surface_group(surface), True) and
                self._surface_identity(surface) not in self._hidden)

    def _refresh_groups(self):
        present = {self._surface_group(s) for s in self._surfaces() if s.get('triangles')}
        for (button, var), group in zip(self._display_buttons, self._groups()):
            button.config(text=self._t(group), state='normal' if group in present else 'disabled')
            var.set(self._group_visible.get(group, True) and group in present)

    def _toggle_group(self, index):
        group = self._groups()[index]
        self._group_visible[group] = bool(self._display_buttons[index][1].get())
        self._redraw()

    def _open_settings(self):
        if self._settings_window is not None:
            self._settings_window.lift()
            return
        tk = self._tk
        win = self._settings_window = tk.Toplevel(self.frame)
        win.title(self._t('Display settings'))
        win.transient(self.frame.winfo_toplevel())
        parent = self.frame.winfo_toplevel()
        x = max(0, parent.winfo_rootx()+(parent.winfo_width()-440)//2)
        y = max(0, parent.winfo_rooty()+(parent.winfo_height()-570)//2)
        win.geometry('440x570+%d+%d' % (x, y))
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        host = tk.Frame(win, padx=8, pady=8)
        host.grid(row=0, column=0, sticky='nsew')
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(host, highlightthickness=0)
        bar = tk.Scrollbar(host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.grid(row=0, column=0, sticky='nsew'); bar.grid(row=0, column=1, sticky='ns')
        body = tk.Frame(canvas)
        def wheel(event):
            widget = event.widget
            while widget is not None and widget not in (body, canvas, win):
                widget = getattr(widget, 'master', None)
            if widget not in (body, canvas):
                return
            if event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
            return 'break'
        # Bind at this Toplevel, not globally; events from checkbuttons bubble
        # here too, while opacity scales retain their own input behavior.
        win.bind('<MouseWheel>', wheel)
        item = canvas.create_window(0, 0, window=body, anchor='nw')
        body.bind('<Configure>', lambda e: canvas.config(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
        rows = {}
        surfaces = list(self._surfaces())
        if self._view_mode == 'internal':
            try:
                from .vehicle_internal_viewer import MODULE_STYLES
            except ImportError:
                from vehicle_internal_viewer import MODULE_STYLES
            entities = {s.get('moduleEntity') for s in surfaces}
            for entity, _, color in MODULE_STYLES:
                if entity != 'surveyingDevice' and entity not in entities:
                    surfaces.append(dict(moduleLabel=entity, moduleEntity=entity, triangles=(), color=color))
            seats = {s.get('moduleLabel','').split(' / ')[0] for s in surfaces}
            for slot in (self._internal_scene or {}).get('crewSlots', ()):
                if slot['identity'] not in seats:
                    surfaces.append(dict(moduleLabel=slot['identity'], moduleEntity='crew',
                                         crewSlot=slot, triangles=(), color=slot['color']))
        for kind, source in (('tracks','Tracks'),('gun','Gun'),('observation','Observation devices')):
            if not any(s.get('armorKind') == kind for s in surfaces):
                surfaces.append(dict(armorKind=kind, triangles=()))
        for surface in surfaces:
            rows.setdefault(self._surface_identity(surface), surface)
        for group in self._groups():
            tk.Label(body, text=self._t(group), anchor='w').pack(fill='x', pady=(6, 2))
            found = False
            for identity, surface in rows.items():
                if identity[0] != group:
                    continue
                found = True
                var = tk.BooleanVar(value=bool(surface.get('triangles')) and identity not in self._hidden)
                def change(key=identity, value=var):
                    if value.get(): self._hidden.discard(key)
                    else: self._hidden.add(key)
                    self._redraw()
                has_data = bool(surface.get('triangles'))
                caption = self._surface_name(surface)
                if not has_data: caption = self._t('%s (no data)') % caption
                tk.Checkbutton(body, text=caption, variable=var,
                               state='normal' if has_data else 'disabled',
                               command=change, anchor='w', justify='left', wraplength=380).pack(fill='x')
            if not found:
                tk.Label(body, text=self._t('No geometry'), anchor='w', fg='#666666').pack(fill='x')
        for title, variable in (('Exterior opacity', self._shell_alpha), ('Module opacity', self._module_alpha)):
            tk.Label(host, text=self._t(title), anchor='w').grid(sticky='ew', columnspan=2)
            tk.Scale(host, from_=0, to=100, orient='horizontal', variable=variable,
                     command=lambda value: self._redraw()).grid(sticky='ew', columnspan=2)
        def close():
            win.destroy(); self._settings_window = None
        tk.Button(host, text=self._t('Restore default display'), command=self.restore_display).grid(
            sticky='ew', columnspan=2, pady=(6, 0))
        tk.Button(host, text=self._t('Close'), command=close).grid(sticky='ew', columnspan=2, pady=(6, 0))
        win.protocol('WM_DELETE_WINDOW', close)

    def restore_display(self):
        self._hidden.clear()
        self._group_visible.clear()
        self._shell_alpha.set(16)
        self._module_alpha.set(85)
        self._refresh_groups()
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None
            self._open_settings()
        self._redraw()

    def _try_gpu(self):
        if not self._gpu_attempted:
            self._gpu_attempted = True
            try:
                if self._gpu_factory is None:
                    try:
                        from .vehicle_gpu_renderer import GpuRenderer
                    except ImportError:
                        from vehicle_gpu_renderer import GpuRenderer
                    self._gpu = GpuRenderer()
                else:
                    self._gpu = self._gpu_factory()
                if self._gpu:
                    self._diagnostic('Viewer OpenGL device: %s' % self._gpu.info)
            except Exception as error:
                self._diagnostic('Viewer OpenGL unavailable; CPU fallback: %s' % error)
        return self._gpu is not None

    def _redraw_gpu(self):
        import numpy as np
        from PIL import ImageTk
        start = time.perf_counter()
        width, height = max(10, self.canvas.winfo_width()), max(10, self.canvas.winfo_height())
        internal = self._view_mode == 'internal'
        surfaces = self._surfaces()
        # Geometry and material uploads are invalidated by scene changes, not
        # camera, visibility, opacity or selection. Keep the source objects alive.
        key = (id(self._scene), id(self._internal_scene), internal,
               tuple((id(s), s.get('thickness'), s.get('color')) for s in surfaces))
        if key != self._gpu_key:
            objects, self._item_surface = {}, {}
            scales = _armor_scales(self._scene)
            for surface in surfaces:
                identity = self._surface_identity(surface)
                obj = objects.setdefault(identity, dict(surface=surface, triangles=[]))
                pick_id = len(self._item_surface)+1
                self._item_surface[pick_id] = surface
                color = surface.get('color') or dict(tracks='#a35edb', gun='#3689f5',
                    observation='#22dced').get(surface.get('armorKind')) or _armor_color(surface, scales)
                rgb = tuple(int(color[i:i+2],16) for i in (1,3,5))
                obj['triangles'].extend((triangle, rgb, pick_id) for triangle in surface['triangles'])
            if internal:
                for part in self._scene['parts']:
                    for surface in part['surfaces']:
                        if self._surface_group(surface) == 'External modules': continue
                        identity = ('context', surface.get('role'), surface.get('component'))
                        obj = objects.setdefault(identity, dict(surface=None, triangles=[]))
                        obj['triangles'].extend((triangle,(184,200,216),0) for triangle in surface['triangles'])
            self._gpu_objects = list(objects.values())
            self._gpu.load(self._gpu_objects)
            self._gpu_key = key
            self._gpu_points = np.asarray([p for part in self._scene['parts']
                for s in part['surfaces'] for triangle in s['triangles'] for p in triangle], dtype=np.float32)
        cy, sy, cp, sp = math.cos(self._yaw), math.sin(self._yaw), math.cos(self._pitch), math.sin(self._pitch)
        rotation = np.asarray(((cy,0,sy),(sp*sy,cp,-sp*cy),(-cp*sy,sp,cp*cy)))
        minimum, maximum = np.asarray(self._scene['bounds'])
        center = (minimum+maximum)*.5
        points = (self._gpu_points-center) @ rotation.T
        low, high = points.min(axis=0), points.max(axis=0)
        scale = min(width*.90/max(.001, high[0]-low[0]), height*.86/max(.001, high[1]-low[1]))*self._zoom
        # OpenGL's nearest depth is -1; Tk's vertical direction is inverted
        # only when the final framebuffer is copied, not in world space.
        matrix = np.eye(4)
        matrix[:3,:3] = rotation
        matrix[:3,3] = -rotation @ center
        matrix[0,3] -= (low[0]+high[0])*.5
        matrix[1,3] -= (low[1]+high[1])*.5
        matrix[0,:] *= 2*scale/width
        matrix[1,:] *= 2*scale/height
        matrix[2,:] *= -1/max(1.,float(np.linalg.norm(maximum-minimum))*4)
        selected_id = 0
        if not internal:
            selected_id = next((i for i,s in self._item_surface.items()
                                if s.get('fieldKey') is not None and s.get('fieldKey') == self._focus_key),0)
        styles = []
        for obj in self._gpu_objects:
            surface = obj['surface']
            if surface is None:
                styles.append(dict(alpha=self._shell_alpha.get()/100))
                continue
            focused = internal and self._selected_module is not None and (
                self._surface_identity(surface) == self._surface_identity(self._selected_module))
            alpha = self._module_alpha.get()/100 if internal else 1.
            if internal and self._surface_group(surface) == 'External modules': alpha *= .65
            if focused: alpha = 1.
            elif internal and self._selected_module is not None: alpha *= .4
            styles.append(dict(alpha=alpha if self._visible(surface) else 0., selected=focused,
                               tint=-.22 if internal and self._selected_module is not None else 0.))
        image = self._gpu.render(width,height,matrix,rotation,styles,selected_id)
        if self._shell_image is not None and self._shell_image.width() == width and self._shell_image.height() == height and self.canvas.find_withtag('depth_scene'):
            self._shell_image.paste(image)
        else:
            self.canvas.delete('all')
            self._shell_image = ImageTk.PhotoImage(image, master=self.canvas)
            self.canvas.create_image(0,0,image=self._shell_image,anchor='nw',tags=('depth_scene',))
        self._pick_buffer = None
        self._pick_size = (width,height)
        self._frame_times.append((time.perf_counter()-start)*1000)
        self._frame_times = self._frame_times[-240:]

    def _redraw(self, unused_event=None):
        if self._scene is not None and self._try_gpu():
            try:
                self._redraw_gpu()
                return
            except Exception as error:
                self._diagnostic('Viewer OpenGL rendering failed; CPU fallback: %s' % error)
                self._gpu.release()
                self._gpu = None
                self._gpu_key = None
        from PIL import ImageTk
        try:
            from .vehicle_scene_renderer import rasterize
        except ImportError:
            from vehicle_scene_renderer import rasterize
        width = max(10, int(self.canvas.winfo_width()))
        height = max(10, int(self.canvas.winfo_height()))
        self.canvas.delete('all')
        self._item_surface = {}
        self._pick_buffer = None
        if self._scene is None:
            self.canvas.create_text(width/2, height/2, text=self.selection.get(),
                fill='#c8ced8', width=max(120, width-48), justify='center')
            return
        # Bound rendering work during window resizing; retain canvas coordinates
        # for input, and use a depth buffer rather than Canvas item hit testing.
        factor = min(1., (400. if self._dragged else 640.)/max(width, height))
        w, h = max(10, round(width*factor)), max(10, round(height*factor))
        internal = self._view_mode == 'internal'
        surfaces = self._surfaces()
        visible = [s for s in surfaces if self._visible(s)]
        scene = dict(self._scene, parts=({'surfaces': visible},))
        triangles = self._projected_triangles(w, h, scene)
        scales = _armor_scales(self._scene)
        selected = self._selected_module
        objects = {}
        for unused_depth, projected, surface, unused_area in triangles:
            identity = self._surface_identity(surface)
            focused = ((selected is not None and self._surface_identity(selected) == identity)
                       if internal else surface.get('fieldKey') is not None and
                       surface.get('fieldKey') == self._focus_key)
            base = surface.get('color') or dict(tracks='#a35edb', gun='#3689f5',
                observation='#22dced').get(surface.get('armorKind')) or _armor_color(surface, scales)
            base = _shade(base, .25 if focused else (-.22 if internal and selected else 0.))
            color = _shade(base, _face_light(projected, self._projection_scale))
            # A field retains its own picking ID, even inside a shared category.
            key = id(surface)
            if key not in objects:
                pick_id = len(self._item_surface)+1
                self._item_surface[pick_id] = surface
                alpha = self._module_alpha.get()/100 if internal else 1.
                if internal and self._surface_group(surface) == 'External modules': alpha *= .65
                if focused: alpha = 1.
                elif internal and selected: alpha *= .4
                objects[key] = dict(id=pick_id, alpha=alpha, triangles=[])
            rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
            objects[key]['triangles'].append((projected, rgb))
        if internal and self._shell_alpha.get() > 0:
            shell = [s for p in self._scene['parts'] for s in p['surfaces']
                     if self._surface_group(s) != 'External modules']
            shell_scene = dict(self._scene, parts=({'surfaces': shell},))
            for _, projected, surface, _ in self._projected_triangles(w, h, shell_scene):
                key = ('context', surface.get('role'), surface.get('component'))
                if key not in objects:
                    objects[key] = dict(id=0, alpha=self._shell_alpha.get()/100, triangles=[])
                color = _shade('#b8c8d8', _face_light(projected, self._projection_scale))
                objects[key]['triangles'].append((projected, tuple(int(color[i:i+2],16) for i in (1,3,5))))
        image, self._pick_buffer = rasterize(w, h, list(objects.values()))
        self._pick_size = (width, height)
        if (w, h) != (width, height):
            from PIL import Image
            image = image.resize((width, height), Image.Resampling.BILINEAR)
        self._shell_image = ImageTk.PhotoImage(image, master=self.canvas)
        self.canvas.create_image(0, 0, image=self._shell_image, anchor='nw', tags=('depth_scene',))


class NullArmorViewerPanel(object):
    """Test/headless fallback preserving the editor interaction contract."""

    def __init__(self, *unused_args, **unused_kwargs):
        self.loaded = []
        self.focused = []
        self.updated = []

    def set_language(self, language):
        return None

    def grid(self, *unused_args, **unused_kwargs):
        return None

    def load_vehicle(self, vehicle_member, records, focus_record=None):
        self.loaded.append((vehicle_member, list(records), focus_record))

    def focus_field(self, record, reload_scene=True):
        self.focused.append((record, reload_scene))
        return _focus_identity(record) is not None

    def update_field(self, member, field_path, current_value):
        self.updated.append((member, field_path, current_value))
        return True

    def reset_values(self):
        return None
