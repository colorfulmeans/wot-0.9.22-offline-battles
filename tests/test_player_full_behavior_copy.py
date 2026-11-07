"""Source completeness and identical original fixtures for the full player copy.

Original fixture parity is separate from the foreground identity, roster and
traffic integration scenes below. These tests do not certify Windows movement
or native trigger execution. No original test is weakened or replaced by a test
of a new simplified policy.
"""

import ast
import contextlib
import copy
import importlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/res/scripts/client"))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tests"))
PREFIX = "gui.mods.offline_lan_0922"
COPIED = PREFIX + ".player_control.copied"
RETIRED_PLAYER_MODULES = (
    "aiming", "ammunition", "artillery", "cover", "direct_engagement",
    "driving", "equipment_policy", "fire_admission", "firing_lane",
    "hull_alignment", "local_height", "local_routes", "missions",
    "navigation", "navigation_support", "observations", "parking",
    "pathfinding", "route_catalog", "sortie", "strategy", "tactics",
    "targeting", "traffic", "traffic_laws", "weapon", "wrecks",
)

spec = importlib.util.spec_from_file_location(
    "player_behavior_copy_generator", ROOT / "tools/sync_player_behavior_copy.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def fixture_module(filename, copied):
    """Run unchanged fixture logic, relocating only its behavior imports."""
    path = ROOT / "tests" / filename
    source = path.read_text(encoding="utf8")
    if copied:
        source, unused = generator.rewrite_imports(source)
    module = types.ModuleType("_full_player_copy_fixture_" + filename[:-3] + ("_copy" if copied else "_source"))
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def run_fixture_suite(filename, copied):
    module = fixture_module(filename, copied)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TestResult()
    suite.run(result)
    return module, result


class FullCopySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outputs, cls.manifest = generator.build()

    def test_every_source_file_is_exact_generated_copy(self):
        self.assertEqual([], generator.check(self.outputs))

    def test_retired_simplified_player_behavior_cannot_be_packaged_or_restored(self):
        self.assertEqual(27, len(RETIRED_PLAYER_MODULES))
        self.assertEqual([], [name for name in RETIRED_PLAYER_MODULES
            if (generator.CLIENT / "player_control" / (name + ".py")).exists()])

    def test_inventory_includes_every_private_nested_and_public_definition(self):
        for row in self.manifest["files"]:
            with self.subTest(module=row["module"]):
                original = generator.declarations((ROOT / row["source"]).read_text())
                copied = generator.declarations((ROOT / row["target"]).read_text())
                copied = [value for value in copied if not (
                    row["module"] == "bot_runtime" and value["name"] == "BotRuntime.controlled_states" or
                    row["module"] == "spg_modes" and value["name"] == "_roster_states")]
                self.assertEqual([(v["name"], v["kind"]) for v in original],
                                 [(v["name"], v["kind"]) for v in copied])
                self.assertEqual(original, row["declarations"])

    def test_observed_roster_owner_seam_reverses_to_exact_source(self):
        source = (generator.CLIENT / "bot_runtime.py").read_text()
        expected, unused = generator.rewrite_imports(source, "bot_runtime")
        copied = (generator.DESTINATION / "bot_runtime.py").read_text()
        self.assertEqual(expected, generator.reverse_ownership_hook(copied))
        runtime_class = importlib.import_module(COPIED + ".bot_runtime").BotRuntime
        runtime = runtime_class.__new__(runtime_class)
        runtime.states = {11: dict(id=11), 12: dict(id=12)}
        self.assertEqual(list(runtime.states.values()), list(runtime.controlled_states()))

        class ForegroundOwner(runtime_class):
            def controlled_states(self):
                return (self.states[11],)

        own = ForegroundOwner.__new__(ForegroundOwner)
        own.states = runtime.states
        self.assertEqual([11], [state["id"] for state in own.controlled_states()])
        self.assertIn(12, own.states)

    def test_nonspatial_spg_roster_hook_reverses_to_exact_original_law(self):
        source = (generator.CLIENT / "spg_modes.py").read_text()
        expected, unused = generator.rewrite_imports(source, "spg_modes")
        copied = (generator.DESTINATION / "spg_modes.py").read_text()
        self.assertEqual(expected, generator.reverse_spg_roster_hook(copied))
        module = importlib.import_module(COPIED + ".spg_modes")
        physical = [dict(id=1, team=1, x=0., y=0., z=0.)]
        actor = types.SimpleNamespace(_ordered_states=lambda: physical)
        self.assertIs(physical, module._roster_states(actor))
        public = physical + [dict(id=2, team=1, alive=True)]
        actor.spg_roster_states = lambda: public
        self.assertIs(public, module._roster_states(actor))
        self.assertIs(physical, actor._ordered_states())
        self.assertNotIn("position", public[1])
        self.assertIn("# Humans never participate in this admission test.", copied)

    def test_full_runtime_and_server_tactical_closure_are_present(self):
        files = {row["module"]: row for row in self.manifest["files"]}
        for module in ("bot_runtime", "ai.navigation", "ai.adapter", "ai.driver",
                       "ai.traffic", "ai.planner", "server_bot_ai",
                       "server_route_tasks", "server_route_recovery", "server_empty_ammo",
                       "native_simulation", "native_control_core", "native_weapons"):
            self.assertIn(module, files)
        runtime_names = {item["name"] for item in files["bot_runtime"]["declarations"]}
        for name in ("_update_once", "_navigation_target_impl", "_gun_angle_order",
                     "_friendly_reposition_order", "_mark_friendly_reposition",
                     "_rear_laying_order", "_artillery_position_order",
                     "_magazine_followup_order", "_retain_magazine_followup"):
            self.assertIn("BotRuntime." + name, runtime_names)
        # This check does not allow a handful of copied methods to stand in for
        # the complete monolithic state machine.
        self.assertGreater(files["bot_runtime"]["source_lines"], 18000)

    def test_no_explicit_original_behavior_import_even_in_lazy_functions(self):
        for row in self.manifest["files"]:
            source = (ROOT / row["target"]).read_text()
            rewritten, imports = generator.rewrite_imports(source)
            with self.subTest(module=row["module"]):
                self.assertEqual(source, rewritten)
                self.assertFalse(any(item["copied"] for item in imports))

    def test_foreground_integration_does_not_reimport_original_behavior(self):
        live_modules = ("__init__", "full_runtime", "attack_policy", "native_aim",
            "native_drive", "trigger_admission", "manual_aim", "commands",
            "native_actions", "settling", "shot_receipts", "test_actions",
            "capabilities")
        for name in live_modules:
            path = generator.CLIENT / "player_control" / (name + ".py")
            with self.subTest(module=name):
                unused, imports = generator.rewrite_imports(path.read_text(),
                    "player_control." + name)
                self.assertEqual([], [item["source"] for item in imports if item["copied"]])

    def test_foreground_geometry_declares_every_extracted_owner_dependency(self):
        full = importlib.import_module(PREFIX + ".player_control.full_runtime")
        geometry = full._ForegroundGeometry(types.SimpleNamespace(owner=types.SimpleNamespace()))
        record = next(row for row in self.manifest["extractions"]
                      if row["target"].endswith("battle_geometry.py"))
        self.assertEqual([], [name for name in record["required_instance_attributes"]
                              if name not in geometry.__dict__ and name not in geometry.OBSERVATIONS])
        for method in record["methods"]:
            with self.subTest(method=method["name"]):
                for name in method["calls"]:
                    self.assertTrue(callable(getattr(geometry, name)), name)

    def test_mixed_and_relative_imports_keep_all_aliases_and_nonimport_bytes(self):
        source = (
            "from gui.mods.offline_lan_0922 import tank_collision, bot_tactics as rules\n"
            "def late():\n"
            "    from .ai.local_height import LocalHeightLinks\n"
            "    from .native_input_diagnostics import write_json_record\n"
            "    return 'from . import bot_runtime', LocalHeightLinks, write_json_record\n")
        result, unused = generator.rewrite_imports(source, "bot_runtime")
        self.assertIn("from %s import tank_collision" % PREFIX, result)
        self.assertIn("from %s import bot_tactics as rules" % COPIED, result)
        self.assertIn("from %s.ai.local_height import LocalHeightLinks" % COPIED, result)
        self.assertIn("from %s.native_input_diagnostics import write_json_record" % PREFIX, result)
        self.assertIn("return 'from . import bot_runtime', LocalHeightLinks, write_json_record", result)

    def test_protocol_alias_uses_exact_primitives_without_importing_network_owner(self):
        source = "from gui.mods.offline_lan_0922 import lan_client as lan_protocol, tank_collision\n"
        transformed, unused = generator.rewrite_imports(source, "bot_runtime")
        self.assertIn("from %s import protocol_primitives as lan_protocol" % COPIED, transformed)
        primitive = importlib.import_module(COPIED + ".protocol_primitives")
        self.assertEqual(-1, primitive.WORKER_AUTHORITY_ID)
        self.assertEqual(2., primitive.SNAPSHOT_STALL_SECONDS)
        for value, expected in ((True, None), (3, 3), (3., 3), ("4", 4), (4.5, None),
                                (float("inf"), None), (float("nan"), None)):
            self.assertEqual(expected, primitive._exact_int(value))
        row = next(item for item in self.manifest["extractions"]
                   if item["target"].endswith("protocol_primitives.py"))
        original_lines = (ROOT / row["source"]).read_text().splitlines(keepends=True)
        actual = (ROOT / row["target"]).read_text()
        for fragment in row["globals"]:
            text = "".join(original_lines[fragment["line"] - 1:fragment["end_line"]])
            self.assertEqual(fragment["source_sha256"], generator.digest(text))
            self.assertIn(text.rstrip("\n"), actual)
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(ast.parse(actual))))

    def test_all_copy_modules_import_under_transitive_original_behavior_guard(self):
        # Isolate the copied package from both existing GUI fixture modules and
        # the actual foreground wrapper (tested independently by its adapter
        # suite). A neutral service may not quietly import original Bot policy.
        code = r'''
import importlib, importlib.util, pathlib, sys, types
root=pathlib.Path(sys.argv[1]); scripts=root/'src/res/scripts/client'
package=scripts/'gui/mods/offline_lan_0922'
for name,path in [('gui',scripts/'gui'),('gui.mods',scripts/'gui/mods'),
                  ('gui.mods.offline_lan_0922',package),
                  ('gui.mods.offline_lan_0922.player_control',package/'player_control')]:
    value=types.ModuleType(name); value.__path__=[str(path)]; value.__package__=name
    sys.modules[name]=value
    if '.' in name:
        parent,child=name.rsplit('.',1); setattr(sys.modules[parent],child,value)
spec=importlib.util.spec_from_file_location('copy_generator',root/'tools/sync_player_behavior_copy.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
data={'bot_editor_maps','bot_tactics_default_data','spg_position_data','bot_fitting_data'}
forbidden={g.PREFIX+'.'+name for name in g.CLIENT_MODULES if name not in data}
forbidden.update(g.SERVER_MODULES); forbidden.add(g.PREFIX+'.lan_client')
class Guard:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in forbidden:
            raise ImportError('original behavior import: '+fullname)
        return None
sys.meta_path.insert(0,Guard())
native=importlib.import_module(g.PREFIX+'.native_math');native._backend=None;native._attempted=True
for module in g.CLIENT_MODULES+g.SERVER_MODULES+('battle_geometry','protocol_primitives'):
    value=importlib.import_module(g.COPY_PREFIX+'.'+module)
    assert 'player_control/copied/' in pathlib.Path(value.__file__).as_posix()
print('independent imports',len(g.CLIENT_MODULES)+len(g.SERVER_MODULES)+2)
'''
        completed = subprocess.run([sys.executable, "-c", code, str(ROOT)],
                                   cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("independent imports", completed.stdout)

    def test_unreviewed_expansion_of_shared_protocol_surface_fails(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed shared behavior"):
            generator.shared_symbols(
                "from gui.mods.offline_lan_0922 import lan_client\nlan_client.Client()\n", "bot_runtime")

    def test_new_internal_dependency_cannot_silently_be_classed_as_shared(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed shared internal dependency"):
            generator.shared_boundary([dict(imports=[dict(copied=False,
                source=PREFIX + ".ai.navigation.TerrainNavigator")])])
        actual = {row["module"] for row in self.manifest["shared_import_boundary"]}
        self.assertTrue(actual.issubset(generator.SHARED_MODULES))
        self.assertIn("burst_mechanics", actual)
        self.assertNotIn("ai.navigation", actual)

    def test_native_wrapper_late_imports_resolve_to_player_laws(self):
        weapons = (generator.DESTINATION / "native_weapons.py").read_text()
        control = (generator.DESTINATION / "native_control_core.py").read_text()
        self.assertIn("from %s.bot_runtime import _BotGunState" % COPIED, weapons)
        self.assertIn("from %s.bot_runtime import _BotAmmoState" % COPIED, weapons)
        self.assertIn("from %s import bot_runtime as laws" % COPIED, control)
        self.assertIn("from %s.ai.driver import LocalDriver" % COPIED, control)

    def test_geometry_callbacks_and_all_self_dependencies_are_exact_source_methods(self):
        record = self.manifest["extractions"][0]
        original = (ROOT / record["source"]).read_text()
        copied = (ROOT / record["target"]).read_text()
        source_class = next(node for node in ast.parse(original).body
                            if isinstance(node, ast.ClassDef) and node.name == "BattleRuntime")
        copied_class = next(node for node in ast.parse(copied).body
                            if isinstance(node, ast.ClassDef) and node.name == "CopiedBattleGeometry")
        source_methods = {node.name: node for node in source_class.body if isinstance(node, ast.FunctionDef)}
        copy_methods = {node.name: node for node in copied_class.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual({row["name"] for row in record["methods"]}, set(copy_methods))
        self.assertTrue(set(generator.GEOMETRY_SEEDS).issubset(copy_methods))

        def fragment(text, node):
            start = min([node.lineno] + [value.lineno for value in node.decorator_list])
            return "\n".join(text.splitlines()[start - 1:node.end_lineno])

        for name, node in copy_methods.items():
            expected = "class X(object):\n" + fragment(original, source_methods[name]) + "\n"
            expected, unused = generator.rewrite_imports(expected, "battle_runtime")
            expected = expected.split("\n", 1)[1].rstrip("\n")
            with self.subTest(method=name):
                self.assertEqual(expected, fragment(copied, node))
                self.assertTrue(generator._self_attributes(source_methods[name]).intersection(source_methods).issubset(copy_methods))
        for forbidden in ("__init__", "_create_worker_bots", "_frame", "_cleanup"):
            self.assertNotIn(forbidden, copy_methods)

    def test_server_portability_is_local_and_does_not_patch_global_math(self):
        compat = importlib.import_module(COPIED + "._compat")
        for value, expected in ((0., True), (1e308, True), (float("inf"), False),
                                (-float("inf"), False), (float("nan"), False)):
            self.assertEqual(expected, compat.isfinite(value))
        source = (generator.DESTINATION / "server_bot_ai.py").read_text()
        self.assertNotIn("sys.path.insert", source)
        self.assertNotIn("math.isfinite(", source)
        for module in generator.SERVER_MODULES:
            source = (generator.DESTINATION / (module + ".py")).read_text()
            ast.parse(source)
            self.assertIn("from __future__ import division", source)
            self.assertIn("import text as str, round_py3 as round", source)
        # Server-only aliases must never replace the pinned original client
        # rounding or string behavior merely because the module was copied.
        self.assertNotIn("import text as str, round_py3 as round",
                         (generator.DESTINATION / "bot_runtime.py").read_text())

    def test_py27_half_even_fallback_matches_python3_float_and_integer_oracle(self):
        compat = importlib.import_module(COPIED + "._compat")
        samples = [0., -0., .5, -.5, 1.5, 2.5, -1.5, -2.5,
                   2.675, .0078125, .0234375, -.0078125, -.0234375,
                   1.7976931348623157e308, 5.e-324, -5.e-324]
        rng = random.Random(119)
        samples.extend(rng.uniform(-2000., 2000.) for unused in range(250))
        for value in samples:
            for digits in (None, -309, -308, -4, 0, 2, 3, 6, 308, 323, 324):
                with self.subTest(value=value, digits=digits):
                    try:
                        expected = round(value) if digits is None else round(value, digits)
                    except (OverflowError, ValueError) as exc:
                        with self.assertRaises(type(exc)):
                            compat.round_half_even(value, digits)
                    else:
                        actual = compat.round_half_even(value, digits)
                        self.assertEqual(expected, actual)
                        self.assertIs(type(expected), type(actual))
                        if isinstance(actual, float) and actual == 0.:
                            self.assertEqual(math.copysign(1., expected), math.copysign(1., actual))
        for value in (5, 15, 25, -15, 10000000000000000000000005):
            for digits in (None, -25, -2, -1, 0, 3):
                expected = round(value) if digits is None else round(value, digits)
                self.assertEqual(expected, compat.round_half_even(value, digits))

    def test_server_aliases_keep_unicode_routes_and_cover_reservation_cells(self):
        compat = importlib.import_module(COPIED + "._compat")
        tasks = importlib.import_module(COPIED + ".server_route_tasks")
        planner_module = importlib.import_module(COPIED + ".server_bot_ai")
        self.assertIs(tasks.str, compat.text)
        self.assertIs(planner_module.round, compat.round_py3)
        actor = planner_module.BotPlanner()
        actor.tactics = None
        actor.tactics_map = "01_karelia"
        route_id = "\u73a9\u5bb6\u8def\u7ebf"
        self.assertEqual(route_id, actor._task_family(dict(id=route_id), 1))
        self.assertEqual([0, 2, 2, 0, -2],
                         [int(compat.round_half_even(value / 8.))
                          for value in (4., 12., 20., -4., -12.)])


class FullCopyOriginalFixtureTests(unittest.TestCase):
    # The fixture files are the existing Bot regression contract. We run each
    # against BOTH original and mirrored modules and require the same test
    # count and success, instead of writing forgiving clone-only assertions.
    FIXTURES = (
        "test_port_0922_navigation.py",
        "test_port_0922_navigation_wait_recovery.py",
        "test_port_0922_traffic.py",
    )

    def test_existing_navigation_wait_recovery_and_traffic_fixtures_both_implementations(self):
        for filename in self.FIXTURES:
            original_module, original = run_fixture_suite(filename, False)
            copied_module, copied = run_fixture_suite(filename, True)
            with self.subTest(fixture=filename):
                self.assertGreater(original.testsRun, 0)
                self.assertEqual(original.testsRun, copied.testsRun)
                self.assertEqual([], original.errors + original.failures,
                                 "Original baseline itself failed: %s" % filename)
                self.assertEqual([], copied.errors + copied.failures,
                                 "Unchanged fixture failed on copy: %s" % filename)
                for exported in ("TerrainNavigator", "TerrainGrid", "LocalDriver", "BotAdapter", "TrafficCoordinator"):
                    if hasattr(copied_module, exported):
                        self.assertTrue(getattr(copied_module, exported).__module__.startswith(COPIED + "."))
                        self.assertIsNot(getattr(copied_module, exported), getattr(original_module, exported))

    def test_existing_friendly_reposition_timeout_fixtures_use_complete_runtime_copy(self):
        harness = importlib.import_module("test_port_0922_bot_runtime")
        names = (
            "test_authored_wait_cancels_friendly_reposition_without_translation",
            "test_blocked_friendly_lane_repositions_through_safe_driver",
            "test_blocked_reposition_expires_without_crossing_native_gate",
            "test_friendly_lane_fail_closed_without_blocker_does_not_reposition",
        )
        for copied in (False, True):
            module = importlib.import_module(COPIED + ".bot_runtime")
            result = unittest.TestResult()
            suite = unittest.TestSuite(harness.BotRuntimeTests(name) for name in names)
            if copied:
                with mock.patch.object(harness, "_load", return_value=module):
                    suite.run(result)
            else:
                suite.run(result)
            with self.subTest(copied=copied):
                self.assertEqual(len(names), result.testsRun)
                self.assertEqual([], result.failures + result.errors)

    def test_existing_aim_candidate_fixture_runs_only_copied_geometry_methods(self):
        fixtures = importlib.import_module("test_port_0922_gun_angle_handoff")
        geometry = importlib.import_module(COPIED + ".battle_geometry").CopiedBattleGeometry
        original_class = fixtures.battle_fixtures.NativeBattleRuntime
        original_scene = fixtures.CandidateReachabilityTests.scene

        class CopiedCandidateTests(fixtures.CandidateReachabilityTests):
            def scene(self):
                runtime, original, source, target, descriptor = original_scene(self)
                actor = geometry.__new__(geometry)
                # Identical world/pose/descriptor fixtures; only the code owner
                # changes. The fixture's injected native lambdas are preserved.
                actor.__dict__.update(original.__dict__)
                return runtime, actor, source, target, descriptor

        original_result, copied_result = unittest.TestResult(), unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(fixtures.CandidateReachabilityTests).run(original_result)
        # A hidden delegation to the old BattleRuntime must fail even if the
        # generated class happens to produce the same result in this scene.
        with mock.patch.object(original_class, "_bot_aim_context", side_effect=AssertionError("original aim context called")), \
                mock.patch.object(original_class, "_bot_firing_lane", side_effect=AssertionError("original firing lane called")):
            unittest.defaultTestLoader.loadTestsFromTestCase(CopiedCandidateTests).run(copied_result)
        self.assertGreater(original_result.testsRun, 0)
        self.assertEqual(original_result.testsRun, copied_result.testsRun)
        self.assertEqual([], original_result.failures + original_result.errors)
        self.assertEqual([], copied_result.failures + copied_result.errors)

    def test_existing_local_sweep_fixture_runs_copied_candidate_and_runtime_closure(self):
        fixtures = importlib.import_module("test_port_0922_local_action_sweep")
        harness = importlib.import_module("test_port_0922_bot_runtime")
        geometry = importlib.import_module(COPIED + ".battle_geometry").CopiedBattleGeometry
        runtime_module = importlib.import_module(COPIED + ".bot_runtime")
        source_scene = fixtures.LocalActionSweepTests.scene

        class CopiedSweepTests(fixtures.LocalActionSweepTests):
            def scene(self):
                original, state, descriptor = source_scene(self)
                actor = geometry.__new__(geometry)
                actor.__dict__.update(original.__dict__)
                return actor, state, descriptor

        results = []
        for copied in (False, True):
            result = unittest.TestResult()
            case = CopiedSweepTests if copied else fixtures.LocalActionSweepTests
            with contextlib.redirect_stdout(io.StringIO()):
                if copied:
                    with mock.patch.object(harness, "_load", return_value=runtime_module):
                        unittest.defaultTestLoader.loadTestsFromTestCase(case).run(result)
                else:
                    unittest.defaultTestLoader.loadTestsFromTestCase(case).run(result)
            results.append(result)
            with self.subTest(copied=copied):
                self.assertEqual([], result.errors + result.failures)
        self.assertGreater(results[0].testsRun, 10)
        self.assertEqual(results[0].testsRun, results[1].testsRun)

    def test_existing_full_body_cover_and_tactical_geometry_fixtures_both_implementations(self):
        original = fixture_module("test_port_0922_tactical_geometry.py", False)
        copied = fixture_module("test_port_0922_tactical_geometry.py", True)
        geometry_module = importlib.import_module(COPIED + ".battle_geometry")
        geometry = geometry_module.CopiedBattleGeometry
        original_scene = copied.TacticalGeometryTests.scene

        def copied_scene(case):
            runtime, old, source, target, descriptor = original_scene(case)
            actor = geometry.__new__(geometry)
            actor.__dict__.update(old.__dict__)
            return runtime, actor, source, target, descriptor

        copied.TacticalGeometryTests.scene = copied_scene
        results = []
        for module in (original, copied):
            result = unittest.TestResult()
            # Keep the original collision fake but install it in the namespace
            # whose generated geometry actually consumes it. No tested result,
            # native input, budget, candidate or assertion is changed.
            with mock.patch.object(module.fixtures, "battle_runtime_module",
                                   geometry_module if module is copied else module.fixtures.battle_runtime_module):
                unittest.defaultTestLoader.loadTestsFromTestCase(module.TacticalGeometryTests).run(result)
            results.append(result)
            self.assertEqual([], result.errors + result.failures)
        self.assertEqual(10, results[0].testsRun)
        self.assertEqual(results[0].testsRun, results[1].testsRun)


class FullCopyDifferentialTests(unittest.TestCase):
    def setUp(self):
        self.original_nav = importlib.import_module(PREFIX + ".ai.navigation")
        self.copied_nav = importlib.import_module(COPIED + ".ai.navigation")
        self.original_traffic = importlib.import_module(PREFIX + ".ai.traffic")
        self.copied_traffic = importlib.import_module(COPIED + ".ai.traffic")

    def test_local_fallback_timeout_has_identical_state_transitions_and_failure_memory(self):
        fixture = fixture_module("test_port_0922_navigation.py", False)
        graph = fixture.StaticHullNavigationTests._flat_graph()
        navigators = [module.TerrainNavigator(lambda *args: 0., baked_graph=copy.deepcopy(graph))
                      for module in (self.original_nav, self.copied_nav)]
        current, goal, local = (8., 0., 8.), (8., 0., 40.), (12., 0., 12.)
        request = ("local", 11, "route")
        for nav in navigators:
            nav.next_target(11, current, goal, request, 0.)
            nav._remember_local_fallback(local, goal, nav.bot_states[11], current)
            nav.bot_states[11]["last_target"] = local
        outputs = []
        for now in (1., 2., 4., 8., 13., 13.1, 26.):
            targets = [nav.next_target(11, current, goal, request, now) for nav in navigators]
            self.assertEqual(targets[0], targets[1])
            self.assertEqual(navigators[0].bot_states, navigators[1].bot_states)
            self.assertEqual(navigators[0].bot_failed_edges, navigators[1].bot_failed_edges)
            outputs.append(targets[1])
        self.assertEqual(local, outputs[0])
        self.assertNotEqual(local, outputs[4])
        self.assertEqual("timeout", navigators[1].bot_states[11]["local_target_end_reason"])

    def test_traffic_copy_does_not_call_original_coordinator_or_driver(self):
        fixture = fixture_module("test_port_0922_traffic.py", False)
        first = fixture.body(1, 0., 0., speed=0.)
        second = fixture.body(2, 0., 7.5, math.pi, 0.)
        coordinator = self.copied_traffic.TrafficCoordinator()
        original_driver = importlib.import_module(PREFIX + ".ai.driver")
        with mock.patch.object(self.original_traffic.TrafficCoordinator, "adjust", side_effect=AssertionError("original traffic called")), \
                mock.patch.object(original_driver.LocalDriver, "drive", side_effect=AssertionError("original driver called")):
            for now in (0., 1., 3., 6., 20.):
                command = coordinator.adjust(first["id"], first, fixture.command(), [second], now, lambda *args: True)
                self.assertIn("throttle", command)

    def test_server_target_route_and_recovery_state_match_identical_fixture(self):
        fixture = fixture_module("test_port_0922_server_bot_ai.py", False)
        original_class = importlib.import_module("server_bot_ai").BotPlanner
        copied_class = importlib.import_module(COPIED + ".server_bot_ai").BotPlanner
        planners = [original_class(), copied_class()]
        route = fixture._route("same-route", [(0., 0., False), (0., 100., False)])
        manifest = [fixture._bot(1, 1, 0, route, class_tag="heavyTank"),
                    fixture._bot(2, 1, 1, route, class_tag="mediumTank")]
        states = [fixture._state(1, 1, 0., 0.), fixture._state(2, 1, 8., 0.)]
        for planner in planners:
            planner.reset(19)
        for now in (0., 1., 2., 8., 16., 40., 180., 185.):
            orders = [planner.build_orders(copy.deepcopy(manifest), copy.deepcopy(states), [], now)
                      for planner in planners]
            self.assertEqual(orders[0], orders[1])
            for attribute in ("_route_states", "_route_history", "_route_recoveries", "_travel_tasks",
                              "_route_assignments", "_cover_states", "_combat_states", "_target_assignments"):
                self.assertEqual(getattr(planners[0], attribute), getattr(planners[1], attribute), attribute)
        self.assertIsNot(original_class, copied_class)
        self.assertTrue(copied_class.__module__.startswith(COPIED + "."))


class ForegroundPublicObservationTests(unittest.TestCase):
    """Retained non-spatial roster contracts at the real foreground boundary.

    These do not assert the retired player's special endgame strategy: copied
    spg_modes deliberately excludes humans from that admission calculation.
    They prove identity/liveness provenance without inventing physical poses.
    """
    def setUp(self):
        harness = importlib.import_module("test_player_full_runtime").FullRuntimeTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        self.battle, self.runtime = harness.battle, harness.runtime

    def test_unpresented_allies_keep_public_identity_without_hidden_position(self):
        self.battle._start_message.update(
            players=[dict(id=1, team=1), dict(id=2, team=1)],
            bots=[dict(id=3, team=1, alive=True)])
        self.battle._pending_bot_create_order = ["bot:3"]
        self.battle._bots_ready_reported = False
        self.assertTrue(self.runtime.start(("drive",)))
        rows = {(row["kind"], row["network_id"]): row for row in self.runtime._public_allies()}
        self.assertEqual({("human", 2), ("bot", 3)}, set(rows))
        for row in rows.values():
            self.assertIsNot(row.get("alive"), False)
            self.assertFalse(row.get("world_pose", False))
            self.assertNotEqual("SPG", row.get("class_tag"))
            self.assertFalse(any(key in row for key in ("position", "x", "y", "z")))
        self.assertFalse(self.battle._bots_ready_reported)
        self.assertEqual(["bot:3"], self.battle._pending_bot_create_order)

    def test_same_round_public_bot_death_merges_without_ready_entity_or_pose(self):
        self.battle._start_message.update(
            players=[dict(id=1, team=1)], bots=[dict(id=3, team=1, alive=True)])
        self.assertTrue(self.runtime.start(("drive",)))
        self.battle._last_snapshot = dict(round_id=3, bots=[dict(
            id=3, alive=False, health=0, x=100., y=20., z=200.)])
        rows = self.runtime._public_allies()
        self.assertEqual(1, len(rows))
        self.assertEqual(("bot", 3, False, 0),
                         (rows[0]["kind"], rows[0]["network_id"], rows[0]["alive"], rows[0]["health"]))
        self.assertFalse(any(key in rows[0] for key in ("position", "x", "y", "z")))
        self.battle._last_snapshot["round_id"] = 2
        rows = self.runtime._public_allies()
        self.assertEqual(1, len(rows))
        self.assertTrue(rows[0]["alive"])

    def test_zero_bot_round_starts_full_controller_without_any_worker_creation_receipt(self):
        self.battle._start_message.update(players=[dict(id=1, team=1)], bots=[])
        self.battle._pending_bot_create_order = ["unrelated-incomplete-presentation"]
        self.battle._bots_ready_reported = False
        self.assertTrue(self.runtime.start(("drive",)))
        self.runtime.set_mission("attack", dict(position=(0., 0., 24.)))
        self.battle._last_frame_time = .1
        result = self.runtime.update(.1, .1)
        self.assertTrue(result["order"])
        self.assertGreater(self.runtime.planner.revision, 0)
        self.assertEqual((), self.runtime._public_allies())
        self.assertFalse(self.battle._bots_ready_reported)

    def test_real_spg_admission_counts_unpresented_live_bots_then_same_round_death(self):
        self.battle.entities[7].typeDescriptor.type.tags = ("SPG",)
        self.battle._start_message.update(
            players=[dict(id=1, team=1)], bots=[dict(id=3, team=1, alive=True)])
        self.assertTrue(self.runtime.start(("drive",)))
        self.assertEqual("SPG", self.runtime.state["profile"]["class_tag"])
        modes = importlib.import_module(COPIED + ".spg_modes")
        modes.update(self.runtime.engine, 0.)
        self.assertEqual("deployment", self.runtime.state["_spg_mode"])
        public = next(row for row in self.runtime.engine.spg_roster_states() if row["id"] == 3)
        self.assertFalse(any(key in public for key in ("position", "x", "y", "z")))
        self.assertEqual({self.runtime.actor_id}, set(self.runtime.engine.states))
        self.battle._last_snapshot = dict(round_id=2, bots=[dict(id=3, alive=False, health=0)])
        modes.update(self.runtime.engine, 1.)
        self.assertEqual("deployment", self.runtime.state["_spg_mode"])
        self.battle._last_snapshot["round_id"] = 3
        modes.update(self.runtime.engine, 2.)
        self.assertEqual("sortie", self.runtime.state["_spg_mode"])
        self.assertEqual({self.runtime.actor_id}, set(self.runtime.engine.states))
        self.battle._sender.send_current.assert_not_called()

    def test_real_spg_admission_keeps_original_explicit_human_exclusion(self):
        self.battle.entities[7].typeDescriptor.type.tags = ("SPG",)
        self.battle._start_message.update(
            players=[dict(id=1, team=1), dict(id=2, team=1)], bots=[])
        self.assertTrue(self.runtime.start(("drive",)))
        self.assertEqual(1, len(self.runtime._public_allies()))
        modes = importlib.import_module(COPIED + ".spg_modes")
        modes.update(self.runtime.engine, 0.)
        self.assertEqual("sortie", self.runtime.state["_spg_mode"])
        self.assertEqual([self.runtime.actor_id],
                         [row["id"] for row in self.runtime.engine.spg_roster_states()])


class ForegroundTrafficObservationTests(unittest.TestCase):
    """Each actual foreground owner observes, but never executes, its peer.

    The copied coordinator receives the same body/command shapes as the source
    fixtures. Unlike the full-team fixtures, these scenes have two completely
    separate coordinators and each runtime controls exactly one human actor.
    """
    def scene(self, own_network=1, peer_network=2, own_position=(0., 0., 0.),
              peer_position=(0., 0., 7.5), own_yaw=0., peer_yaw=math.pi,
              own_speed=0., peer_speed=0., peer_inputs=True, own_engine=7,
              peer_engine=8, peer_kind="player"):
        fixture = importlib.import_module("test_player_full_runtime").FullRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        battle, runtime = fixture.battle, fixture.runtime
        own = battle.entities.pop(7)
        own.id = own_engine
        own.matrix.translation, own.matrix.yaw = own_position, own_yaw
        own.position = own_position
        battle.entities[own_engine] = own
        battle._server.vehicle_id = own_engine
        battle.client.player_id = own_network
        battle._local_speed = own_speed
        record = battle._records.pop("player:1")
        record.update(network_id=own_network, engine_id=own_engine)
        record["state"].update(id=own_network)
        matrix = importlib.import_module("player_native_fixtures").Matrix()
        matrix.translation, matrix.yaw = peer_position, peer_yaw
        peer = types.SimpleNamespace(id=peer_engine, position=peer_position, matrix=matrix,
            typeDescriptor=own.typeDescriptor, isAlive=lambda: True, isStarted=True,
            health=1000, siegeState=0)
        battle.entities[peer_engine] = peer
        peer_state = dict(id=peer_network, team=1, alive=True, health=1000,
                          x=peer_position[0], y=peer_position[1], z=peer_position[2],
                          yaw=peer_yaw, speed=peer_speed, vehicle="ussr:R11_MS-1")
        if peer_kind == "player":
            # Real player rows require the canonical client-owned physics,
            # crew and equipment projection. Reuse the original wire fixture,
            # never weaken that contract to admit a bare default descriptor.
            peer_state["effective_params"] = importlib.import_module(
                "test_port_0922_bot_runtime")._effective_params_snapshot()
        if peer_inputs:
            peer_state.update(movement_dir=1, rotation_dir=0, service_brake=False)
        other = dict(ready=True, kind=peer_kind, network_id=peer_network,
            engine_id=peer_engine, team=1, state=peer_state,
            vehicle="ussr:R11_MS-1")
        battle._records = {"player:%s" % own_network: record,
                           "%s:%s" % (peer_kind, peer_network): other}
        battle._start_message.update(
            players=[dict(id=own_network, team=1)] +
                    ([dict(id=peer_network, team=1)] if peer_kind == "player" else []),
            bots=[dict(id=peer_network, team=1)] if peer_kind == "bot" else [])
        self.assertTrue(runtime.start(("drive",)))
        self.accept_frame(battle, runtime, 0.)
        return battle, runtime

    @staticmethod
    def accept_frame(battle, runtime, now, advance_peer=True):
        """Present a new accepted observation, not a local render tick."""
        sequence = getattr(battle, "_fixture_input_sequence", 0) + 1
        battle._fixture_input_sequence = sequence
        battle.client._snapshot_accepted_time = 1000. + now
        snapshot = dict(round_id=battle._start_message["round_id"],
                        tick=sequence, players=[], bots=[])
        for record in battle._records.values():
            old_sequence = record["state"].get("input_seq", sequence)
            record["state"] = dict(record["state"], input_seq=(sequence
                if advance_peer or record.get("local") else old_sequence))
            snapshot["bots" if record["kind"] == "bot" else "players"].append(
                dict(record["state"]))
        battle._last_snapshot = snapshot
        battle.client.last_snapshot = snapshot
        runtime._observe(now)

    @staticmethod
    def bodies(runtime):
        engine = runtime.engine
        rows, unused = engine._traffic_snapshot(engine._player_neighbours(runtime._players))
        return rows[runtime.actor_id], [body for actor, body in rows.items() if actor != runtime.actor_id]

    @staticmethod
    def longitudinal_clear(heading, yaw):
        delta = abs((heading - yaw + math.pi) % (2. * math.pi) - math.pi)
        return delta < .05 or abs(delta - math.pi) < .05

    def install_peer_wall(self, runtime, unknown=False):
        def probe(identity, position, yaw, heading, distance, descriptor, step, now):
            return dict(proved=not unknown, clear=self.longitudinal_clear(heading, yaw))
        patcher = mock.patch.object(runtime.geometry, "_probe_bot_local_motion", side_effect=probe)
        patcher.start()
        self.addCleanup(patcher.stop)

    def local_adjust(self, runtime, now, order=None, clear=None):
        body, peers = self.bodies(runtime)
        command = order if order is not None else dict(throttle=1., turn=0.,
            target_yaw=body["yaw"], movement_intent=True, recovery_mode="drive", combat_mode="route")
        return runtime.engine._traffic_coordinator.adjust(runtime.actor_id, body, command,
            peers, now, clear or (lambda heading, distance=None: self.longitudinal_clear(heading, body["yaw"])))

    def test_two_local_only_coordinators_elect_one_backer_from_public_identity(self):
        first = self.scene()
        second = self.scene(own_network=2, peer_network=1, own_position=(0., 0., 7.5),
            peer_position=(0., 0., 0.), own_yaw=math.pi, peer_yaw=0., own_engine=7, peer_engine=8)
        modes = importlib.import_module(COPIED + ".ai.traffic")
        physical = [copy.deepcopy(battle._local_matrix.__dict__) for battle, unused in (first, second)]
        for unused, runtime in (first, second):
            self.install_peer_wall(runtime)
        results = []
        for now in (0., modes.YIELD_SECONDS + .1):
            results = []
            for battle, runtime in (first, second):
                self.accept_frame(battle, runtime, now)
                runtime._observe_traffic(now)
                results.append(self.local_adjust(runtime, now))
                self.assertEqual({runtime.actor_id}, set(runtime.engine.states))
                self.assertEqual(1, len(runtime.engine.controlled_states()))
                self.assertEqual({1000001, 1000002}, next(iter(runtime.engine._traffic_coordinator._pairs.values()))["blocked"])
                battle._sender.send_current.assert_not_called()
        self.assertEqual([.7, -.7], [row["throttle"] for row in results])
        for original, (battle, runtime) in zip(physical, (first, second)):
            self.assertEqual(original, battle._local_matrix.__dict__)
            peer_id = next(iter(runtime._traffic_observed))
            self.assertNotEqual(runtime.actor_id, peer_id)
            self.assertNotIn("recovery_mode", runtime._traffic_observed[peer_id]["input"])
        for now in (modes.YIELD_SECONDS + modes.HEAD_ON_RETREAT_SECONDS, 410.):
            for battle, runtime in (first, second):
                self.accept_frame(battle, runtime, now)
                runtime._observe_traffic(now)
                self.assertEqual(1., self.local_adjust(runtime, now)["throttle"])

    def test_crossing_winner_is_identical_when_native_engine_creation_order_changes(self):
        first = self.scene(own_position=(0., 0., -5.), peer_position=(-5., 0., 0.),
            peer_yaw=math.pi / 2., own_speed=4., peer_speed=4., own_engine=8, peer_engine=7)
        second = self.scene(own_network=2, peer_network=1, own_position=(-5., 0., 0.),
            peer_position=(0., 0., -5.), own_yaw=math.pi / 2., peer_yaw=0.,
            own_speed=4., peer_speed=4., own_engine=7, peer_engine=8)
        winners, commands = [], []
        for unused, runtime in (first, second):
            runtime._observe_traffic(0.)
            commands.append(self.local_adjust(runtime, 0., clear=lambda *args: True))
            lease = next(iter(runtime.engine._traffic_coordinator._pairs.values()))
            self.assertEqual("yield", lease["mode"])
            winners.append(lease["winner"])
        self.assertEqual([1000001, 1000001], winners)
        self.assertEqual([1., 0.], [command["throttle"] for command in commands])

    def test_bot_namespace_priority_does_not_depend_on_native_entity_ids(self):
        winners = []
        for own_native, peer_native in ((7, 8), (8, 7)):
            unused, runtime = self.scene(peer_network=1, peer_kind="bot",
                own_position=(0., 0., -5.), peer_position=(-5., 0., 0.),
                peer_yaw=math.pi / 2., own_speed=4., peer_speed=4.,
                own_engine=own_native, peer_engine=peer_native)
            runtime._observe_traffic(0.)
            command = self.local_adjust(runtime, 0., clear=lambda *args: True)
            lease = next(iter(runtime.engine._traffic_coordinator._pairs.values()))
            winners.append(lease["winner"])
            self.assertEqual(0., command["throttle"])
            self.assertEqual([runtime.actor_id],
                             [row["id"] for row in runtime.engine.controlled_states()])
            self.assertEqual({1, 1000001}, set(runtime.engine.states))
        self.assertEqual([1, 1], winners)

    def test_complete_update_observes_peer_before_local_control_and_only_sends_local_input(self):
        battle, runtime = self.scene()
        self.install_peer_wall(runtime)
        runtime.set_mission("attack", dict(position=(0., 0., 24.)))
        coordinator = runtime.engine._traffic_coordinator
        peer = battle.entities[8]
        original_poses = [copy.deepcopy(entity.matrix.__dict__)
                          for entity in (battle.entities[7], peer)]
        with mock.patch.object(coordinator, "adjust", wraps=coordinator.adjust) as adjust:
            battle._last_frame_time = .1
            runtime.update(.1, .1)
        actors = [call.args[0] for call in adjust.call_args_list]
        self.assertIn(1000001, actors)
        self.assertEqual(1000002, actors[0])
        self.assertEqual(1, actors.count(1000002))
        self.assertTrue(all(actor == 1000001 for actor in actors[1:]))
        self.assertEqual({1000002}, set(runtime._traffic_observed))
        self.assertEqual({1000001}, set(runtime.engine.states))
        self.assertGreater(runtime.engine._alive_bot_ticks, 0)
        self.assertGreater(runtime.planner.revision, 0)
        battle._sender.send_current.assert_called_once_with()
        self.assertEqual(original_poses,
            [entity.matrix.__dict__ for entity in (battle.entities[7], peer)])

    def test_zero_speed_without_published_input_cannot_invent_peer_request_or_double_block(self):
        unused, runtime = self.scene(peer_inputs=False)
        self.install_peer_wall(runtime)
        runtime._observe_traffic(0.)
        self.assertEqual({}, runtime._traffic_observed)
        self.assertEqual({}, runtime.engine._traffic_coordinator._orders)
        self.local_adjust(runtime, 0.)
        lease = next(iter(runtime.engine._traffic_coordinator._pairs.values()))
        self.assertEqual({runtime.actor_id}, lease["blocked"])

    def test_unknown_native_peer_sweep_cannot_become_proved_second_block(self):
        unused, runtime = self.scene()
        self.install_peer_wall(runtime, unknown=True)
        runtime._observe_traffic(0.)
        self.assertEqual({}, runtime.engine._traffic_coordinator._pairs)
        observed = runtime._traffic_observed[1000002]
        self.assertFalse(observed["geometric_proof"])
        self.assertTrue(observed["input"]["movement_intent"])
        self.assertNotIn("forward_blocked_by", observed["input"])
        self.local_adjust(runtime, 0.)
        lease = next(iter(runtime.engine._traffic_coordinator._pairs.values()))
        self.assertEqual({runtime.actor_id}, lease["blocked"])

    def test_stalled_public_input_is_not_renewed_by_render_ticks(self):
        unused, runtime = self.scene()
        self.install_peer_wall(runtime)
        coordinator = runtime.engine._traffic_coordinator
        runtime._observe_traffic(0.)
        original_time = coordinator._orders[1000002][0]
        modes = importlib.import_module(COPIED + ".ai.traffic")
        with mock.patch.object(coordinator, "adjust", wraps=coordinator.adjust) as adjust:
            runtime._observe_traffic(modes.ORDER_FRESH_SECONDS + .1)
        adjust.assert_not_called()
        self.assertEqual(original_time, coordinator._orders[1000002][0])
        self.assertNotIn(1000002, runtime._traffic_observed)

    def test_dense_render_ticks_preserve_original_peer_input_age(self):
        unused, runtime = self.scene()
        self.install_peer_wall(runtime)
        coordinator = runtime.engine._traffic_coordinator
        runtime._observe_traffic(0.)
        for now in (.5, 1., 1.4):
            runtime._observe_traffic(now)
            self.assertEqual(0., coordinator._orders[1000002][0])
        runtime._observe_traffic(1.6)
        self.assertNotIn(1000002, runtime._traffic_observed)
        self.assertEqual(0., coordinator._orders[1000002][0])

    def test_other_players_fresh_snapshots_cannot_renew_stalled_peer_input_sequence(self):
        battle, runtime = self.scene()
        self.install_peer_wall(runtime)
        runtime._observe_traffic(0.)
        for now in (.5, 1., 1.6, 2.):
            self.accept_frame(battle, runtime, now, advance_peer=False)
            runtime._observe_traffic(now)
        self.assertNotIn(1000002, runtime._traffic_observed)
        self.assertEqual(0., runtime.engine._traffic_coordinator._orders[1000002][0])

    def test_new_accepted_frame_restores_unchanged_forward_input_after_stall(self):
        battle, runtime = self.scene()
        self.install_peer_wall(runtime)
        coordinator = runtime.engine._traffic_coordinator
        modes = importlib.import_module(COPIED + ".ai.traffic")
        runtime._observe_traffic(0.)
        later = modes.ORDER_FRESH_SECONDS + .1
        runtime._observe_traffic(later)
        self.assertNotIn(1000002, runtime._traffic_observed)
        self.accept_frame(battle, runtime, later + .1)
        runtime._observe_traffic(later + .1)
        self.assertEqual(1., coordinator._orders[1000002][1]["throttle"])
        self.assertEqual(later + .1, coordinator._orders[1000002][0])
        self.assertIn(1000002, runtime._traffic_observed)
        # Transport and game clocks deliberately have different origins.
        self.assertGreater(battle.client._snapshot_accepted_time, 1000.)

    def test_real_observed_forward_input_and_body_block_admit_one_finite_courtesy_yield(self):
        battle, runtime = self.scene(own_position=(0., 0., 7.), peer_position=(0., 0., 0.),
                                   peer_yaw=0., own_network=2, peer_network=1)
        modes = importlib.import_module(COPIED + ".ai.traffic")
        body, unused = self.bodies(runtime)
        hold = dict(throttle=0., turn=0., target_yaw=body["yaw"], movement_intent=False,
                    recovery_mode="arrived", combat_mode="artillery_hold", fire_allowed=True, target_id=99)
        commands = []
        for now in (0., modes.PARKED_JAM_SECONDS):
            self.accept_frame(battle, runtime, now)
            runtime._observe_traffic(now)
            commands.append(self.local_adjust(runtime, now, hold, lambda *args: True))
        self.assertEqual(0., commands[0]["throttle"])
        self.assertEqual(.7, commands[1]["throttle"])
        self.assertEqual("friendly_yield", commands[1]["traffic_mode"])
        self.assertFalse(commands[1]["fire_allowed"])
        self.assertEqual(runtime.actor_id,
            runtime.engine._traffic_coordinator._orders[1000001][1]["forward_blocked_by"])
        for now in (modes.PARKED_JAM_SECONDS + modes.PARKED_YIELD_SECONDS, 410.):
            self.accept_frame(battle, runtime, now)
            runtime._observe_traffic(now)
            self.assertEqual(hold, self.local_adjust(runtime, now, hold, lambda *args: True))
        battle._sender.send_current.assert_not_called()
        self.assertEqual((0., 0., 7.), battle._local_matrix.translation)


class ForegroundPlannerObservationTests(unittest.TestCase):
    """Real cooperative branches need accepted peer evidence, not just copies."""
    def scene(self):
        fixture = importlib.import_module("test_player_full_runtime").FullRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        battle, runtime = fixture.battle, fixture.runtime
        original = importlib.import_module("test_port_0922_server_bot_ai")
        matrix_type = importlib.import_module("player_native_fixtures").Matrix
        own = battle.entities[7]
        own.matrix.translation = own.position = (0., 0., -40.)
        battle._navigation_graph.update(objective_bases=((-55., -55.), (55., 55.)),
                                        objective_base_radii=(5., 5.))
        for identity, kind, network, team, point, roles in (
                (8, "bot", 12, 1, (-20., 0., -30.), dict(support=1., flanker=.1)),
                (9, "player", 2, 2, (0., 0., 40.), dict(support=1., flanker=.1))):
            matrix = matrix_type()
            matrix.translation = point
            descriptor = copy.deepcopy(own.typeDescriptor)
            descriptor.maxHealth = 2000
            battle.entities[identity] = types.SimpleNamespace(id=identity,
                position=point, matrix=matrix, typeDescriptor=descriptor,
                isAlive=lambda: True, isStarted=True, health=2000, siegeState=0)
            raw = original._state(network, team, point[0], point[2])
            importlib.import_module(PREFIX + ".burst_mechanics").TriggerClock().publish(raw)
            raw.update(health=2000, max_health=2000,
                profile=original._profile("mediumTank", roles),
                vehicle="ussr:R11_MS-1")
            raw["profile"].update(desired_range=40., fire_range=520.,
                shells=[dict(index=0, kind="ARMOR_PIERCING", penetration=200., damage=100.)])
            if kind == "player":
                raw["effective_params"] = importlib.import_module(
                    "test_port_0922_bot_runtime")._effective_params_snapshot()
            battle._records["%s:%s" % (kind, network)] = dict(ready=True,
                kind=kind, network_id=network, engine_id=identity, team=team,
                state=raw, spot_visible=True, vehicle="ussr:R11_MS-1")
        battle._start_message.update(players=[dict(id=1, team=1), dict(id=2, team=2)],
                                     bots=[dict(id=12, team=1)])
        battle._gun_state.tick(10., True, 0., 0., 0., own.typeDescriptor)
        self.assertTrue(battle._gun_state.can_fire())
        self.assertTrue(runtime.start(("drive",)))
        runtime.state["profile"].update(class_tag="mediumTank", dominant_role="support",
            desired_range=40., fire_range=520., roles=dict(support=.1, flanker=1.),
            shells=[dict(index=0, kind="ARMOR_PIERCING", penetration=200., damage=100.)])
        runtime._observe(0.)
        control_type = importlib.import_module(PREFIX + ".player_control").PlayerControl
        control = control_type(battle, ("drive",), notify=lambda *args: None)
        control.runtime, control.active = runtime, True
        control._runtime_binding = control._native_binding()
        runtime.controller = control
        battle._player_control = control
        battle.state, battle.client.team, battle._sixth_sense = "running", 1, None
        battle._clock = lambda: battle._last_frame_time
        battle._fail = mock.Mock(side_effect=AssertionError("team observation bridge failed"))
        battle_type = importlib.import_module(PREFIX + ".battle_runtime").BattleRuntime
        for name in ("on_bot_observation", "_apply_team_observation", "_observe_local_vehicle"):
            setattr(battle, name, types.MethodType(getattr(battle_type, name), battle))
        return battle, runtime

    @staticmethod
    def accept(runtime, message, now):
        runtime.owner._last_frame_time = now
        return runtime.owner.on_bot_observation(message)

    @staticmethod
    def receipt(round_id=3, shooters=(12,), visible=True):
        return dict(type="bot_observation", round_id=round_id, contacts=[dict(
            observing_team=1, target_kind="human", target_id=2, target_team=2,
            visible=visible, fresh=visible, time_left=1. if visible else 0.,
            visible_by_bot_ids=[12] if visible else [], visible_by_player_ids=[1] if visible else [],
            shootable_by_bot_ids=list(shooters) if visible else [])])

    @staticmethod
    def plan(runtime, now):
        runtime.now = now
        runtime._observe(now)
        target = runtime._targets[0]
        # This is a physical lane receipt, not a replacement planner decision.
        key = runtime.engine._shot_los_key(runtime.state, target)
        runtime.engine._shot_los_cache[key] = (now, True)
        result = runtime._planner_order(now)
        return result, {row["id"]: row for row in runtime.planner._last_orders["orders"]}

    def test_accepted_peer_lane_reaches_real_flank_and_suppressor_branches(self):
        battle, runtime = self.scene()
        self.assertTrue(self.accept(runtime, self.receipt(), 0.))
        local, orders = self.plan(runtime, 0.)
        self.assertEqual("flank", local["combat_mode"])
        self.assertEqual("flank", orders[runtime.actor_id]["combat_mode"])
        self.assertNotEqual("flank", orders[12]["combat_mode"])
        self.assertTrue(orders[12]["fire_allowed"])
        self.assertEqual({12, runtime.actor_id}, set(
            runtime.planner._contacts[1][("human", 2)]["shootable_by_bot_ids"]))
        self.assertEqual([runtime.actor_id], [row["id"] for row in runtime.engine.controlled_states()])
        battle._sender.send_current.assert_not_called()

    def test_actual_team_event_and_complete_loop_preserve_peer_authority(self):
        battle, runtime = self.scene()
        self.assertTrue(self.accept(runtime, self.receipt(), 0.))
        target = runtime._targets[0]
        runtime.engine._shot_los_cache[runtime.engine._shot_los_key(
            runtime.state, target)] = (.1, True)
        original_peer = copy.deepcopy(battle.entities[8].matrix.__dict__)
        original_gun = copy.deepcopy(battle._gun_state.__dict__)
        battle._last_frame_time = .1
        runtime.update(.1, .1)
        self.assertEqual("flank", runtime._last_order["combat_mode"])
        self.assertEqual(original_peer, battle.entities[8].matrix.__dict__)
        self.assertEqual(original_gun, battle._gun_state.__dict__)
        self.assertEqual([runtime.actor_id], [row["id"] for row in runtime.engine.controlled_states()])
        battle._sender.send_current.assert_called_once_with()

    def test_missing_peer_lane_never_invents_a_second_shooter(self):
        unused, runtime = self.scene()
        local, unused = self.plan(runtime, 0.)
        self.assertNotEqual("flank", local["combat_mode"])
        self.assertEqual([runtime.actor_id],
            runtime.planner._contacts[1][("human", 2)]["shootable_by_bot_ids"])

    def test_wrong_round_peer_lane_does_not_enable_cooperative_flank(self):
        unused, runtime = self.scene()
        self.assertFalse(self.accept(runtime, self.receipt(round_id=2), 0.))
        local, unused = self.plan(runtime, 0.)
        self.assertNotEqual("flank", local["combat_mode"])

    def test_receipt_does_not_create_an_unknown_or_human_peer_shooter(self):
        battle, runtime = self.scene()
        ally = copy.deepcopy(battle.entities[8])
        ally.id = 10
        ally.position = ally.matrix.translation = (-20., 0., -45.)
        battle.entities[10] = ally
        raw = dict(battle._records["bot:12"]["state"], id=3)
        raw["effective_params"] = importlib.import_module(
            "test_port_0922_bot_runtime")._effective_params_snapshot()
        battle._records["player:3"] = dict(ready=True, kind="player", network_id=3,
            engine_id=10, team=1, state=raw, vehicle="ussr:R11_MS-1")
        runtime._observe(0.)
        self.assertIn(3, [row["network_id"] for row in runtime._players])
        self.accept(runtime, self.receipt(shooters=(99, 1000003)), 0.)
        local, unused = self.plan(runtime, 0.)
        self.assertNotEqual("flank", local["combat_mode"])
        self.assertEqual([runtime.actor_id],
            runtime.planner._contacts[1][("human", 2)]["shootable_by_bot_ids"])

    def test_battle_event_rejects_nonrunning_closed_or_replaced_control(self):
        for boundary in ("nonrunning", "closed", "identity"):
            with self.subTest(boundary=boundary):
                battle, runtime = self.scene()
                if boundary == "nonrunning":
                    battle.state = "closed"
                elif boundary == "closed":
                    battle._player_control.closed = True
                else:
                    battle._generation += 1
                self.assertFalse(self.accept(runtime, self.receipt(), 0.))
                self.assertEqual({}, runtime._team_shooter_observations)
                battle._sender.send_current.assert_not_called()

    def test_passive_team_observation_cannot_restart_stopped_control(self):
        battle, runtime = self.scene()
        runtime.stop("manual")
        battle._player_control.active = False
        battle._sender.send_current.reset_mock()
        self.accept(runtime, self.receipt(), 0.)
        runtime.update(.1, .1)
        self.assertFalse(runtime.active)
        self.assertFalse(battle._player_control.active)
        battle._sender.send_current.assert_not_called()

    def test_dead_peer_is_removed_even_while_its_accepted_lane_receipt_is_young(self):
        battle, runtime = self.scene()
        self.accept(runtime, self.receipt(), 0.)
        battle.entities[8].isAlive = lambda: False
        battle.entities[8].health = 0
        local, unused = self.plan(runtime, .05)
        self.assertNotEqual("flank", local["combat_mode"])
        self.assertEqual([runtime.actor_id],
            runtime.planner._contacts[1][("human", 2)]["shootable_by_bot_ids"])

    def test_expired_or_explicitly_hidden_peer_lane_is_not_renewed_by_local_scans(self):
        for hidden in (False, True):
            with self.subTest(hidden=hidden):
                unused, runtime = self.scene()
                self.accept(runtime, self.receipt(), 0.)
                local, unused = self.plan(runtime, 0.)
                self.assertEqual("flank", local["combat_mode"])
                if hidden:
                    self.accept(runtime, self.receipt(visible=False), .1)
                later = (.11 if hidden else importlib.import_module(
                    COPIED + ".bot_runtime").SHOT_LANE_SECONDS + .01)
                local, unused = self.plan(runtime, later)
                self.assertNotEqual("flank", local["combat_mode"])
                self.assertEqual([runtime.actor_id],
                    runtime.planner._contacts[1][("human", 2)]["shootable_by_bot_ids"])


if __name__ == "__main__":
    unittest.main()
