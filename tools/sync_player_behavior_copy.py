#!/usr/bin/env python3
"""Mechanically mirror complete Bot behavior sources into the player namespace.

This is a source-copy verifier, NOT a claim that PlayerControl is wired to it.
All copied functions/classes (including authority/physical code) are retained.
Only explicit import remaps, Python-2.7 server portability and the reversible
controlled-actor/non-spatial-roster ownership seams are permitted.
The visible-player adapter must separately own input, physics and publication.

Use --write to regenerate through apply_patch; the default/--check is read-only.
Do not hand-edit generated files. New player behavior belongs outside this mirror
until its baseline and integration have independently passed their checks.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src/res/scripts/client/gui/mods/offline_lan_0922"
DESTINATION = CLIENT / "player_control/copied"
PREFIX = "gui.mods.offline_lan_0922"
COPY_PREFIX = PREFIX + ".player_control.copied"

# Full source units, not a selection of methods considered "necessary" by a
# new implementation. The native wrappers contain late calls back into Bot
# laws, so they must be copied even though their C++ primitives remain shared.
CLIENT_MODULES = (
    "bot_runtime", "ai", "ai.adapter", "ai.driver",
    "ai.local_height", "ai.maps", "ai.navigation", "ai.planner",
    "ai.traffic", "bot_tactics",
    "bot_tactics_runtime", "bot_gunnery", "bot_fittings", "hull_aiming",
    "spg_positions", "spg_route_travel", "spg_route_recovery", "spg_modes",
    "empty_ammo", "capture_orders", "initial_allocation", "route_network",
    "ammo_policy", "team_class_policy", "local_navigation_mesh",
    "native_navigation", "native_simulation", "native_control_core",
    "native_weapons", "artillery_diagnostics", "default_loadouts",
    "descriptor_donation", "vehicle_configuration", "equipment_test",
    "bot_editor_maps", "bot_tactics_default_data", "spg_position_data",
    "bot_fitting_data", "artillery_controller", "artillery_arc_queue",
)
SERVER_MODULES = (
    "server_bot_ai", "server_route_recovery", "server_route_tasks",
    "server_empty_ammo",
)
MODULES = frozenset(CLIENT_MODULES + SERVER_MODULES)
PROTOCOL_REMAP = PREFIX + ".lan_client"
PROTOCOL_TARGET = COPY_PREFIX + ".protocol_primitives"

# These callbacks are Bot algorithms embedded in the engine-facing owner, not
# neutral ray casts. Their complete self-call closure and global helper closure
# are mechanically extracted, without copying unrelated lobby/authority entry
# points from the 33k-line BattleRuntime class.
GEOMETRY_SEEDS = (
    "_bot_visibility", "_bot_aim_context", "_bot_aim_point",
    "_bot_aim_damage_score", "_bot_firing_lane", "_bot_incoming_lane",
    "_bot_friendly_firing_lane",
    "_bot_direct_launch_origin", "_bot_artillery_planning_origin",
    "_bot_artillery_aim_samples", "_bot_artillery_status",
    "_bot_ballistic_solution", "_bot_artillery_launch",
    "_bot_artillery_friendly_lane", "_bot_artillery_cancel",
    "_artillery_arc_probe", "_probe_bot_local_motion", "_resolve_bot_rotation",
    "_direction_world_receipt", "_direction_probe", "_turret_motion_is_clear",
    "_sample_ground_plane",
    "_navigation_height_columns", "_navigation_surface_observation",
    "_navigation_obstacle",
)
OWNER_LOOP_SOURCE = "for state in self.states.values():"
OWNER_LOOP_COPY = "for state in self.controlled_states():"
OWNER_HOOK = '''

    def controlled_states(self):
        """Select owned actors; the player adapter can retain read-only peers."""
        return self.states.values()
'''
SPG_ROSTER_SOURCE = "states = list(runtime._ordered_states())"
SPG_ROSTER_COPY = "states = list(_roster_states(runtime))"
SPG_ROSTER_HOOK = '''

def _roster_states(runtime):
    """Read non-spatial admission identities; default to the original roster."""
    return getattr(runtime, 'spg_roster_states', runtime._ordered_states)()
'''

# Only these protocol primitives are needed from lan_client. Importing the
# complete network owner also imports original Bot policy, so these exact
# source fragments are separately mirrored instead. No network class is used.
BOUNDED_SHARED_SYMBOLS = {
    "lan_client": ("WORKER_AUTHORITY_ID", "SNAPSHOT_STALL_SECONDS", "_exact_int"),
}
SHARED_ROLES = {
    "prebaked_navigation": "Shared immutable graph loading/schema and geometry predicates.",
    "native_math": "Shared native computation primitives, not native Bot policy ownership.",
    "native_navigation_query": "Shared engine geometry oracle.",
    "burst_mechanics": "Unified physical trigger clock for manual, Bot and player auto.",
    "vehicle_fitting_context": "Actual descriptor/crew/equipment parameter context.",
    "vehicle_physics": "Neutral copied vehicle-motion equations; caller owns integration.",
    "worker_diagnostics": "Instrumentation only; names do not confer worker authority.",
    "native_input_diagnostics": "Instrumentation only.",
    "config": "Shared configuration/path data; not copied application lifecycle.",
}
SHARED_MODULES = frozenset((
    "arena_boundary", "ballistics", "battle_visibility", "bot_state_codec",
    "burst_mechanics", "collision_flags", "combat_rules", "crew_battle",
    "critical_damage", "critical_statistics", "default_crew",
    "destructibles_compat", "destructibles_sensor", "device_damage",
    "effective_params", "entities.remote_vehicle", "environment_modules",
    "environment_push", "equipment_mechanics", "fire_model", "gc_sweep",
    "graphics_probe", "gun_mechanics", "gun_pitch_limits",
    "loadout", "native_input_diagnostics", "native_mapping_mask", "native_math",
    "native_navigation_query", "native_world", "physics_audit",
    "prebaked_destructibles", "prebaked_foliage", "prebaked_navigation",
    "projectile_runtime", "radio", "ram_motion", "roof_crush_test",
    "shot_dispersion", "shot_geometry", "siege_mechanics", "spotting",
    "stun_mechanics", "support_queries", "tank_collision", "tank_contact_ledger",
    "track_damage", "tree_diagnostics", "vehicle_blacklist",
    "vehicle_fitting_context", "vehicle_physics", "vehicle_stack",
    "water_geometry", "water_surfaces", "worker_diagnostics", "world_census",
    "world_collision",
))

PACKAGE_INIT = '''"""Full mechanically copied Bot behavioral sources, independently owned.

Generated by tools/sync_player_behavior_copy.py. This package deliberately
preserves the complete algorithms and their state, not a simplified replacement.
Original comments/docstrings retain their historical Bot/worker vocabulary;
they are provenance, not instructions to simplify or forbid the player copy.
Do not instantiate its Bot authority lifecycle for a human vehicle: the visible
player adapter must supply real local state, inputs and physical feedback, and
must not publish bot_state or simulate another actor. Source-copy checks alone
are not end-to-end migration or Windows validation.
"""
'''

COMPAT_SOURCE = '''"""Only Python-2.7 portability for mechanically copied server sources.

Server JSON text is Unicode. Native client byte strings use UTF-8. These
aliases are imported ONLY by copied server modules; original client laws keep
their Python-2.7 builtins, including the existing rounding behavior.
"""
from __future__ import print_function, division

import io
import math
import sys
import zipfile

try:
    _text_type = unicode
    _integer_types = (int, long)
except NameError:
    _text_type = str
    _integer_types = (int,)


def text(value):
    if isinstance(value, _text_type):
        return value
    if sys.version_info[0] < 3 and isinstance(value, str):
        return value.decode('utf8')
    return _text_type(value)


def round_half_even(value, ndigits=None):
    """CPython-3 float rounding from the exact binary value, also on 2.7."""
    from decimal import Decimal, ROUND_HALF_EVEN, localcontext
    integer = isinstance(value, _integer_types)
    if ndigits is not None and not isinstance(ndigits, _integer_types):
        raise TypeError('ndigits must be an integer')
    number = value if integer else float(value)
    if not integer and (math.isnan(number) or math.isinf(number)):
        if ndigits is not None:
            return number
        if math.isnan(number):
            raise ValueError('cannot convert float NaN to integer')
        raise OverflowError('cannot convert float infinity to integer')
    if ndigits is None:
        exact = Decimal(number) if integer else Decimal.from_float(number)
        return int(exact.to_integral_value(rounding=ROUND_HALF_EVEN))
    if integer and ndigits >= 0:
        return number
    if not integer and ndigits > 323:
        return number
    if not integer and ndigits < -308:
        return math.copysign(0.0, number)
    if integer and -ndigits > len(str(abs(number))) + 1:
        return 0
    with localcontext() as context:
        # Every finite double's exact decimal expansion fits this precision.
        # No intermediate float scaling is allowed: e.g. 2.675 at 2 places
        # must be 2.67, whereas an exact .5 tie must choose the even result.
        context.prec = max(1100, len(str(abs(number))) + abs(ndigits) + 8)
        exact = Decimal(number) if integer else Decimal.from_float(number)
        rounded = exact.quantize(Decimal(1).scaleb(-ndigits),
                                 rounding=ROUND_HALF_EVEN)
        if integer:
            return int(rounded)
        result = float(rounded)
        if math.isinf(result):
            raise OverflowError('rounded value too large to represent')
        return result


def round_py3(value, ndigits=None):
    if sys.version_info[0] >= 3:
        return round(value) if ndigits is None else round(value, ndigits)
    return round_half_even(value, ndigits)


def isfinite(value):
    return not math.isnan(value) and not math.isinf(value)


def open_text(path):
    return io.open(path, mode='r', encoding='utf8')


BadZipFile = getattr(zipfile, 'BadZipFile', None) or zipfile.BadZipfile
'''


def source_path(module):
    if module in SERVER_MODULES:
        return ROOT / "server" / (module + ".py")
    path = CLIENT.joinpath(*module.split("."))
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


def target_path(module):
    path = DESTINATION.joinpath(*module.split("."))
    return path / "__init__.py" if module == "ai" else path.with_suffix(".py")


def digest(data):
    if isinstance(data, str):
        data = data.encode("utf8")
    return hashlib.sha256(data).hexdigest()


def resolved_from(node, source_module):
    """Resolve source relative imports before relocating the source package."""
    if not node.level:
        return node.module or ""
    if source_module in SERVER_MODULES:
        raise ValueError("Unexpected server relative import: %s" % source_module)
    package = PREFIX
    if source_module:
        parent = source_module if source_module == "ai" else source_module.rpartition(".")[0]
        if parent:
            package += "." + parent
    parts = package.split(".")
    parent = ".".join(parts[:len(parts) - node.level + 1])
    return parent + ("." + node.module if node.module else "")


def mirrored_module(full_name):
    if full_name == PROTOCOL_REMAP:
        return PROTOCOL_TARGET
    if full_name in SERVER_MODULES:
        return COPY_PREFIX + "." + full_name
    if full_name.startswith(PREFIX + "."):
        relative = full_name[len(PREFIX) + 1:]
        if relative in MODULES:
            return COPY_PREFIX + "." + relative
    return full_name


def _offsets(source):
    lines = source.splitlines(keepends=True)
    offsets, current = [], 0
    for line in lines:
        offsets.append(current)
        current += len(line)
    offsets.append(current)
    return lines, offsets


def _position(lines, offsets, line, byte_column):
    # CPython AST offsets use UTF-8 bytes, whereas source slicing uses Unicode.
    column = len(lines[line - 1].encode("utf8")[:byte_column].decode("utf8"))
    return offsets[line - 1] + column


def _alias(alias):
    return alias.name + (" as " + alias.asname if alias.asname else "")


def rewrite_imports(source, source_module=None):
    """Return source with only import statements relocated (including lazy imports).

    Exposed for running the SAME original fixture source against this namespace.
    No code AST is unparsed or reformatted; non-import bytes remain untouched.
    """
    tree = ast.parse(source)
    lines, offsets = _offsets(source)
    edits, imports = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ImportFrom, ast.Import)):
            continue
        start = _position(lines, offsets, node.lineno, node.col_offset)
        end = _position(lines, offsets, node.end_lineno, node.end_col_offset)
        old = source[start:end]
        indentation = lines[node.lineno - 1][:len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
        new = old
        if isinstance(node, ast.ImportFrom):
            origin = resolved_from(node, source_module)
            destination = mirrored_module(origin)
            source_head = "." * node.level + (node.module or "")
            aliases = []
            for alias in node.names:
                full_alias = origin + "." + alias.name if origin else alias.name
                target_alias = mirrored_module(full_alias)
                aliases.append((alias, full_alias, target_alias))
                if origin == PREFIX or origin.startswith(PREFIX + ".") or origin in SERVER_MODULES:
                    imports.append(dict(line=node.lineno, source=full_alias,
                        target=(target_alias if target_alias != full_alias else destination + "." + alias.name),
                        copied=(destination != origin or target_alias != full_alias)))
            # A root import can mix neutral services and copied behavior. Split
            # it without changing the original left-to-right alias evaluation.
            mixed = any(target != full for alias, full, target in aliases) and destination == origin
            if mixed:
                statements = []
                for alias, full, target in aliases:
                    module = target.rpartition(".")[0] if target != full else destination
                    name = _alias(alias)
                    if target != full and target.rpartition(".")[2] != alias.name:
                        name = target.rpartition(".")[2] + " as " + (alias.asname or alias.name)
                    statements.append("from %s import %s" % (module, name))
                new = ("\n" + indentation).join(statements)
            elif destination != origin or node.level:
                marker = "from " + source_head
                if not old.startswith(marker):
                    raise ValueError("Unsupported import layout: %r" % old)
                new = "from " + destination + old[len(marker):]
        else:
            replacements = []
            for alias in node.names:
                mapped = mirrored_module(alias.name)
                if mapped != alias.name:
                    if not alias.asname and "." in alias.name:
                        raise ValueError("Dotted import without alias needs explicit review: %s" % alias.name)
                    replacements.append((alias.name, mapped))
                if alias.name.startswith(PREFIX + ".") or alias.name in SERVER_MODULES:
                    imports.append(dict(line=node.lineno, source=alias.name,
                        target=mapped, copied=mapped != alias.name))
            for old_name, new_name in replacements:
                new = new.replace(old_name, new_name, 1)
        if new != old:
            edits.append((start, end, new))
    result = source
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result, imports


def portability(source, module):
    """Explicit server import/I/O compatibility; never change decisions."""
    changes = []
    if module not in SERVER_MODULES:
        return source, changes
    if module == "server_bot_ai":
        start = source.index("_PORT_ROOT = ")
        end = source.index("from " + COPY_PREFIX, start)
        source = source[:start] + source[end:]
        changes.append("Remove server-only sys.path bootstrap; copied imports are package-qualified.")
    tree = ast.parse(source)
    call_names = {id(node.func) for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    if any(isinstance(node, ast.Name) and node.id in ("str", "round") and
           id(node) not in call_names for node in ast.walk(tree)):
        raise ValueError("Server str/round acquired a non-call use; audit the compatibility alias: " + module)
    # The original server runs on Python 3. Preserve its true division,
    # Unicode JSON identity and ties-to-even rounding on the embedded 2.7
    # runtime by adapting only imports, never rewriting a decision body.
    insertion = max([node.end_lineno for node in tree.body
                     if isinstance(node, ast.ImportFrom) and node.module == "__future__"] +
                    ([tree.body[0].end_lineno] if tree.body and
                     isinstance(tree.body[0], ast.Expr) and
                     isinstance(tree.body[0].value, ast.Constant) and
                     isinstance(tree.body[0].value.value, str) else [0]))
    aliases = ("from __future__ import division\n"
               "from %s._compat import text as str, round_py3 as round\n" % COPY_PREFIX)
    lines = source.splitlines(keepends=True)
    source = "".join(lines[:insertion]) + aliases + "".join(lines[insertion:])
    changes.append(dict(kind="python3_runtime_semantics", original="", adapted=aliases,
        reason="Preserve original server true division, Unicode JSON IDs and CPython-3 half-even rounding under embedded Python 2.7. Client source modules retain original builtins."))
    uses_helper = "math.isfinite(" in source or "open(path, encoding='utf8')" in source
    if uses_helper:
        source = source.replace("import math\n", "import math\nfrom %s import _compat as _copy_compat\n" % COPY_PREFIX, 1)
    if "math.isfinite(" in source:
        source = source.replace("math.isfinite(", "_copy_compat.isfinite(")
        changes.append("math.isfinite -> Python-2.7-compatible equivalent, same predicate.")
    if "open(path, encoding='utf8')" in source:
        source = source.replace("open(path, encoding='utf8')", "_copy_compat.open_text(path)")
        source = source.replace("zipfile.BadZipFile", "_copy_compat.BadZipFile")
        source = source.replace("except (OSError, ValueError, KeyError, _copy_compat.BadZipFile):",
                                "except (IOError, OSError, ValueError, KeyError, _copy_compat.BadZipFile):")
        changes.append("UTF-8 text open, BadZipFile spelling and Python-2.7 IOError/OSError distinction through compatibility-only edits.")
    return source, changes


def ownership_hook(source, module):
    """Reversible owner seams retaining the complete original decision code.

    The default is exactly the original all-state iterator. A visible-player
    subclass can retain the observed roster for avoidance/cohorts while owning
    only its own movement and weapon actions. No source Bot file is changed.
    """
    if module == "spg_modes":
        if source.count(SPG_ROSTER_SOURCE) != 1 or "def _roster_states(" in source:
            raise ValueError("SPG admission roster source changed; review the I/O seam")
        result = source.replace(SPG_ROSTER_SOURCE, SPG_ROSTER_COPY, 1) + SPG_ROSTER_HOOK
        if reverse_spg_roster_hook(result) != source:
            raise ValueError("SPG roster seam failed exact reversible-source check")
        return result, [dict(kind="nonspatial_roster_io_seam", function="spg_modes.update",
            original=SPG_ROSTER_SOURCE, adapted=SPG_ROSTER_COPY,
            added_default_function="_roster_states", default="runtime._ordered_states()",
            reason="Allow public same-round Bot identity/liveness in SPG admission without inventing pose or changing the original human exclusion rule.",
            exact_reverse_verified=True)]
    if module != "bot_runtime":
        return source, []
    tree = ast.parse(source)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "BotRuntime")
    if any(isinstance(node, ast.FunctionDef) and node.name == "controlled_states" for node in owner.body):
        raise ValueError("Source added controlled_states; review/remove the copy adaptation")
    method = next(node for node in owner.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_update_once")
    lines = source.splitlines(keepends=True)
    body = "".join(lines[method.lineno - 1:method.end_lineno])
    if body.count(OWNER_LOOP_SOURCE) != 1:
        raise ValueError("Expected exactly one actor execution loop in _update_once")
    updated = body.replace(OWNER_LOOP_SOURCE, OWNER_LOOP_COPY, 1)
    result = ("".join(lines[:method.lineno - 1]) + updated
              + "".join(lines[method.end_lineno:owner.end_lineno])
              + OWNER_HOOK + "".join(lines[owner.end_lineno:]))
    if reverse_ownership_hook(result) != source:
        raise ValueError("Owner seam failed exact reversible-source check")
    return result, [dict(kind="actor_owner_io_seam", method="BotRuntime._update_once",
        original=OWNER_LOOP_SOURCE, adapted=OWNER_LOOP_COPY,
        added_default_method="BotRuntime.controlled_states",
        default="return self.states.values()",
        reason="Separate observed roster from locally controlled actors without removing any behavior.",
        exact_reverse_verified=True)]


def reverse_ownership_hook(source):
    if source.count(OWNER_HOOK) != 1 or source.count(OWNER_LOOP_COPY) != 1:
        raise ValueError("Unexpected owner adaptation shape")
    return source.replace(OWNER_HOOK, "", 1).replace(OWNER_LOOP_COPY, OWNER_LOOP_SOURCE, 1)


def reverse_spg_roster_hook(source):
    if source.count(SPG_ROSTER_HOOK) != 1 or source.count(SPG_ROSTER_COPY) != 1:
        raise ValueError("Unexpected non-spatial SPG roster adaptation shape")
    return source.replace(SPG_ROSTER_HOOK, "", 1).replace(SPG_ROSTER_COPY, SPG_ROSTER_SOURCE, 1)


def declarations(source):
    """Inventory every class, function and nested function, not just public APIs."""
    result = []

    class Inventory(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_definition(self, node):
            name = ".".join(self.stack + [node.name])
            result.append(dict(name=name, kind=type(node).__name__,
                               line=node.lineno, end_line=node.end_lineno))
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_ClassDef = visit_definition
        visit_FunctionDef = visit_definition
        visit_AsyncFunctionDef = visit_definition

    Inventory().visit(ast.parse(source))
    return result


def _bound_names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {item.id for target in targets for item in ast.walk(target)
                if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
    return set()


def _loaded_names(nodes):
    return {item.id for node in nodes for item in ast.walk(node)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}


def _self_attributes(node):
    found = {item.attr for item in ast.walk(node)
             if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name)
             and item.value.id == "self"}
    for item in ast.walk(node):
        if (isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                and item.func.id in ("getattr", "hasattr", "setattr")
                and len(item.args) >= 2 and isinstance(item.args[0], ast.Name)
                and item.args[0].id == "self" and isinstance(item.args[1], ast.Constant)
                and isinstance(item.args[1].value, str)):
            found.add(item.args[1].value)
    return found


def extract_battle_geometry():
    """Preserve every source byte of selected methods except import relocation."""
    path = CLIENT / "battle_runtime.py"
    raw = path.read_bytes()
    source = raw.decode("utf8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    owner = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "BattleRuntime")
    methods = {node.name: node for node in owner.body if isinstance(node, ast.FunctionDef)}
    closure = set(GEOMETRY_SEEDS)
    if closure.difference(methods):
        raise ValueError("Missing BattleRuntime geometry roots: %s" % sorted(closure.difference(methods)))
    while True:
        expanded = closure | {name for selected in closure
            for name in _self_attributes(methods[selected]) if name in methods}
        if expanded == closure:
            break
        closure = expanded
    if closure.intersection(("__init__", "_create_worker_bots", "_frame", "_cleanup")):
        raise ValueError("Geometry now reaches an authority lifecycle; review the new boundary")
    selected_methods = sorted((methods[name] for name in closure), key=lambda node: node.lineno)
    for node in selected_methods:
        for item in ast.walk(node):
            if (isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                    and item.func.id in ("getattr", "hasattr") and len(item.args) >= 2
                    and isinstance(item.args[0], ast.Name) and item.args[0].id == "self"
                    and not isinstance(item.args[1], ast.Constant)):
                raise ValueError("Geometry added dynamic self lookup; audit closure before copying: " + node.name)
    globals_by_name = {}
    for node in tree.body:
        for name in _bound_names(node):
            globals_by_name.setdefault(name, []).append(node)
    selected_globals = {node for node in tree.body
                        if isinstance(node, ast.ImportFrom) and node.module == "__future__"}
    needed = _loaded_names(selected_methods)
    while True:
        expanded = selected_globals | {node for name in needed
                                      for node in globals_by_name.get(name, ())}
        if owner in expanded:
            raise ValueError("Geometry global closure now references BattleRuntime ownership")
        new_names = needed | _loaded_names(expanded)
        if expanded == selected_globals and new_names == needed:
            break
        selected_globals, needed = expanded, new_names

    def fragment(node):
        start = min([node.lineno] + [item.lineno for item in getattr(node, "decorator_list", ())])
        return "".join(lines[start - 1:node.end_lineno]), start

    preamble = []
    global_records = []
    for node in sorted(selected_globals, key=lambda node: node.lineno):
        text, start = fragment(node)
        preamble.append(text.rstrip("\n"))
        global_records.append(dict(names=sorted(_bound_names(node)), line=start,
                                   end_line=node.end_lineno, source_sha256=digest(text)))
    body = []
    method_records = []
    for node in selected_methods:
        text, start = fragment(node)
        body.append(text.rstrip("\n"))
        method_records.append(dict(name=node.name, line=start, end_line=node.end_lineno,
            source_sha256=digest(text), calls=sorted(_self_attributes(node).intersection(methods))))
    combined = ("\n\n".join(preamble) + "\n\n\nclass CopiedBattleGeometry(object):\n"
                '    """Exact Bot geometry callbacks; caller supplies independent local state."""\n\n'
                + "\n\n".join(body) + "\n")
    result, imports = rewrite_imports(combined, "battle_runtime")
    unused, remappable = rewrite_imports(result)
    if any(row["copied"] for row in remappable):
        raise ValueError("Geometry extraction still imports original behavior")
    all_attributes = {name for node in selected_methods for name in _self_attributes(node)}
    record = dict(source=str(path.relative_to(ROOT)),
        target=str((DESTINATION / "battle_geometry.py").relative_to(ROOT)),
        source_sha256=digest(raw), copied_sha256=digest(result),
        seeds=list(GEOMETRY_SEEDS), methods=method_records, globals=global_records,
        required_instance_attributes=sorted(all_attributes.difference(methods)),
        imports=imports,
        contract="Every seed, self-method dependency, and referenced global helper is copied verbatim except explicit imports. No original-owner Bot method delegation.")
    return result, record


def extract_protocol_primitives():
    """Copy the bounded wire surface without importing the network owner."""
    path = CLIENT / "lan_client.py"
    raw = path.read_bytes()
    source = raw.decode("utf8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)
    selected = []
    found = set()
    required = set(BOUNDED_SHARED_SYMBOLS["lan_client"]) | {"integer_types"}
    for node in tree.body:
        names = _bound_names(node)
        if isinstance(node, ast.Try):
            names |= {item.id for item in ast.walk(node)
                      if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)}
        used = names.intersection(required)
        if used:
            selected.append((node, used))
            found.update(used)
    if found != required:
        raise ValueError("Protocol primitive declarations changed: " + repr(sorted(required - found)))
    fragments, records = [], []
    for node, names in selected:
        fragment = "".join(lines[node.lineno - 1:node.end_lineno])
        fragments.append(fragment.rstrip("\n"))
        records.append(dict(names=sorted(names), line=node.lineno, end_line=node.end_lineno,
                            source_sha256=digest(fragment)))
    result = ('"""Exact neutral protocol fragments; deliberately no network/Bot imports."""\n\n'
              + "\n\n".join(fragments) + "\n")
    record = dict(source=str(path.relative_to(ROOT)),
        target=str((DESTINATION / "protocol_primitives.py").relative_to(ROOT)),
        source_sha256=digest(raw), copied_sha256=digest(result),
        globals=records, imports=[],
        contract="Only WORKER_AUTHORITY_ID, SNAPSHOT_STALL_SECONDS, _exact_int and integer_types are required. All source fragments are byte-for-byte; no network owner or original Bot import.")
    return result, record


def shared_symbols(source, source_module):
    """Reject expansions of deliberately bounded shared protocol imports."""
    tree = ast.parse(source)
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            origin = resolved_from(node, source_module)
            if origin == PREFIX:
                for alias in node.names:
                    if alias.name in BOUNDED_SHARED_SYMBOLS:
                        bindings[alias.asname or alias.name] = alias.name
    observed = {name: set() for name in bindings.values()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = bindings.get(node.value.id)
            if module:
                observed[module].add(node.attr)
    for module, names in observed.items():
        unexpected = names.difference(BOUNDED_SHARED_SYMBOLS[module])
        if unexpected:
            raise ValueError("Unreviewed shared behavior surface %s: %s" % (module, sorted(unexpected)))
    return {name: sorted(values) for name, values in observed.items()}


def shared_boundary(records):
    """A newly introduced internal import needs review, not silent sharing."""
    boundary = {}
    for entry in records:
        for item in entry["imports"]:
            if item["copied"] or not item["source"].startswith(PREFIX + "."):
                continue
            relative = item["source"][len(PREFIX) + 1:]
            module = relative
            path = None
            while module:
                candidate = CLIENT.joinpath(*module.split("."))
                if candidate.with_suffix(".py").is_file():
                    path = candidate.with_suffix(".py")
                    break
                if (candidate / "__init__.py").is_file():
                    path = candidate / "__init__.py"
                    break
                module = module.rpartition(".")[0]
            if path is None or module not in SHARED_MODULES:
                raise ValueError("Unreviewed shared internal dependency: " + item["source"])
            row = boundary.setdefault(module, dict(module=module,
                source=str(path.relative_to(ROOT)),
                role=SHARED_ROLES.get(module, "Neutral physical, geometry, data or diagnostic service; no copied policy ownership."),
                referenced_symbols=set()))
            row["referenced_symbols"].add(relative)
    for row in boundary.values():
        row["referenced_symbols"] = sorted(row["referenced_symbols"])
    return [boundary[name] for name in sorted(boundary)]


def bounded_neutral_transitive_imports():
    """Audit the two shared services whose full module graph looks behavioral.

    These edges only read a configuration path or diagnostic environment flag.
    The reviewed consumer never calls the application/fixture installers that
    live elsewhere in the same source module.
    """
    consumer = (CLIENT / "equipment_mechanics.py").read_text(encoding="utf8")
    module = ast.parse(consumer)
    contract = next(node for node in module.body
                    if isinstance(node, ast.FunctionDef) and node.name == "bot_consumable_contracts")
    symbols = {node.attr for node in ast.walk(contract)
               if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
               and node.value.id == "equipment_test"}
    if symbols != {"governor_mode"}:
        raise ValueError("Neutral equipment projection gained an original behavior dependency: %s" % sorted(symbols))
    diagnostic = (CLIENT / "equipment_test.py").read_text(encoding="utf8")
    functions = {node.name: node for node in ast.parse(diagnostic).body if isinstance(node, ast.FunctionDef)}
    fragments = []
    for name in ("enabled", "governor_mode"):
        node = functions[name]
        calls = {ast.unparse(value.func) for value in ast.walk(node) if isinstance(value, ast.Call)}
        if calls.difference({"enabled", "os.environ.get"}):
            raise ValueError("Diagnostic flag reader gained a non-neutral call: " + name)
        if any(isinstance(value, (ast.Import, ast.ImportFrom)) for value in ast.walk(node)):
            raise ValueError("Diagnostic flag reader gained a nested import: " + name)
        fragments.append(dict(name=name, source_sha256=digest(ast.get_source_segment(diagnostic, node))))
    prebaked = (CLIENT / "prebaked_navigation.py").read_text(encoding="utf8")
    config_imports = [node for node in ast.walk(ast.parse(prebaked))
                      if isinstance(node, ast.ImportFrom) and node.module == PREFIX + ".config"]
    if len(config_imports) != 1 or [value.name for value in config_imports[0].names] != ["CONFIG_PATH"]:
        raise ValueError("Baked graph loader acquired a broader application-owner import")
    return [
        dict(consumer="prebaked_navigation", original_module="config", symbols=["CONFIG_PATH"],
             role="Immutable path value only; no garage, lobby, worker or bootstrap entry is called."),
        dict(consumer="equipment_mechanics.bot_consumable_contracts", original_module="equipment_test",
             symbols=["governor_mode"], function_closure=fragments,
             role="Environment-only diagnostic flag. No install_server, install_worker, movement or gun policy is called.")]


def build():
    actual_ai = {"ai" if path.name == "__init__.py" and path.parent == CLIENT / "ai"
                 else str(path.relative_to(CLIENT).with_suffix("")).replace("/", ".")
                 for path in (CLIENT / "ai").rglob("*.py")}
    expected_ai = {name for name in CLIENT_MODULES if name == "ai" or name.startswith("ai.")}
    if actual_ai != expected_ai:
        raise ValueError("AI directory changed; audit full copy census: missing=%s extra=%s" % (
            sorted(actual_ai - expected_ai), sorted(expected_ai - actual_ai)))
    outputs = {DESTINATION / "__init__.py": PACKAGE_INIT,
               DESTINATION / "_compat.py": COMPAT_SOURCE}
    entries = []
    for module in CLIENT_MODULES + SERVER_MODULES:
        path = source_path(module)
        raw = path.read_bytes()
        source = raw.decode("utf8")
        result, imports = rewrite_imports(source, module)
        result, adaptations = portability(result, module)
        result, owner_adaptations = ownership_hook(result, module)
        adaptations.extend(owner_adaptations)
        origin_defs = declarations(source)
        result_defs = declarations(result)
        copied_defs = [v for v in result_defs if not (
            module == "bot_runtime" and v["name"] == "BotRuntime.controlled_states" or
            module == "spg_modes" and v["name"] == "_roster_states")]
        if [(v["name"], v["kind"]) for v in origin_defs] != [(v["name"], v["kind"]) for v in copied_defs]:
            raise ValueError("Lost or changed source declarations in " + module)
        # Reparse and reject any explicit late/relative import back to a source
        # behavior module. Neutral helpers are separately named in the manifest.
        unused, copied_imports = rewrite_imports(result)
        if any(item["copied"] for item in copied_imports):
            raise ValueError("Copy still imports original behavior: " + module)
        target = target_path(module)
        outputs[target] = result
        entries.append(dict(module=module,
            source=str(path.relative_to(ROOT)), target=str(target.relative_to(ROOT)),
            source_sha256=digest(raw), copied_sha256=digest(result),
            source_lines=len(source.splitlines()), copied_lines=len(result.splitlines()),
            declarations=origin_defs, imports=imports, adaptations=adaptations,
            bounded_shared_symbols=shared_symbols(source, module)))
    geometry, geometry_record = extract_battle_geometry()
    outputs[DESTINATION / "battle_geometry.py"] = geometry
    protocol, protocol_record = extract_protocol_primitives()
    outputs[DESTINATION / "protocol_primitives.py"] = protocol
    shared = shared_boundary(entries + [geometry_record, protocol_record])
    manifest = dict(format="offline-player-full-behavior-copy", version=1,
        scope="Complete source mirror only; not proof of live PlayerControl wiring or Windows behavior.",
        source_revision_policy="Every source unit is content-fingerprinted. Generation is independent of HEAD so committing this mirror cannot invalidate its own check.",
        contract=dict(no_algorithms_removed=True, no_direct_original_behavior_imports=True,
            preserved_authority_code="Adapter must not invoke worker publication/physics for a human.",
            server_graph_loader="Original loading algorithm retained. Adapter must supply the client navgraph cache or override only the graph I/O seam.",
            shared_trigger="burst_mechanics remains the common manual/Bot physical trigger owner."),
        shared_service_roles=SHARED_ROLES, shared_import_boundary=shared,
        bounded_neutral_transitive_imports=bounded_neutral_transitive_imports(),
        files=entries, extractions=[geometry_record, protocol_record])
    outputs[DESTINATION / "manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    return outputs, manifest


def patch_for(outputs):
    parts = ["*** Begin Patch"]
    for path, content in outputs.items():
        relative = str(path.relative_to(ROOT))
        if not path.exists():
            parts.append("*** Add File: " + relative)
            parts.extend("+" + line for line in content.splitlines())
            continue
        old = path.read_text(encoding="utf8")
        if old == content:
            continue
        parts.append("*** Update File: " + relative)
        old_lines, new_lines = old.splitlines(), content.splitlines()
        for group in difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_grouped_opcodes(3):
            parts.append("@@")
            for tag, a, b, c, d in group:
                if tag == "equal":
                    parts.extend(" " + line for line in old_lines[a:b])
                if tag in ("delete", "replace"):
                    parts.extend("-" + line for line in old_lines[a:b])
                if tag in ("insert", "replace"):
                    parts.extend("+" + line for line in new_lines[c:d])
    parts.append("*** End Patch")
    return "\n".join(parts) + "\n"


def check(outputs):
    failures = []
    for path, expected in outputs.items():
        if not path.is_file():
            failures.append("missing: " + str(path.relative_to(ROOT)))
        elif path.read_bytes() != expected.encode("utf8"):
            failures.append("not an exact generated copy: " + str(path.relative_to(ROOT)))
    expected_paths = set(outputs)
    if DESTINATION.exists():
        failures.extend("unmanifested source: " + str(path.relative_to(ROOT))
                        for path in DESTINATION.rglob("*.py") if path not in expected_paths)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true", help="Verify exact mirror without edits (default).")
    options.add_argument("--write", action="store_true", help="Regenerate owned mirror through apply_patch.")
    args = parser.parse_args(argv)
    outputs, manifest = build()
    failures = check(outputs)
    if args.write and failures:
        # Do not race an original-source edit made while the mirror was built.
        for item in manifest["files"] + manifest["extractions"]:
            if digest((ROOT / item["source"]).read_bytes()) != item["source_sha256"]:
                raise RuntimeError("Source changed during build; retry: " + item["source"])
        subprocess.run(["apply_patch"], input=patch_for(outputs), cwd=ROOT, text=True, check=True)
        failures = check(outputs)
    for item in manifest["files"] + manifest["extractions"]:
        if digest((ROOT / item["source"]).read_bytes()) != item["source_sha256"]:
            failures.append("source changed during verification; regenerate: " + item["source"])
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("Exact source mirror verified: %d modules; %d declarations. Live adapter integration is a separate check." % (
        len(manifest["files"]), sum(len(item["declarations"]) for item in manifest["files"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
