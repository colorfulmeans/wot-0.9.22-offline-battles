#!/usr/bin/env python3
"""Run existing full Bot fixtures unchanged against both behavior namespaces.

This checks copied algorithm parity, NOT visible-player I/O or Windows physics.
Every implementation runs in an isolated process. Test helpers are recursively
imported with only behavior imports relocated. The existing BotRuntime fixture's
dynamic _load reads the copy instead of the original; no test body or assertion
is simplified. The shared native-boundary fakes remain the original fixtures.

Copied server graph loading gets the original fixture resource locator, solely
to read identical navgraph inputs. Production foreground integration preloads
its own actual graph cache instead. Protocol/authority tests are not counted as
player behavior coverage.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import contextlib
import importlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest

import sync_player_behavior_copy as generator


ROOT = generator.ROOT
TESTS = ROOT / "tests"
FIXTURES = (
    "test_port_0922_bot_runtime.py",
    "test_port_0922_ai.py",
    "test_port_0922_navigation.py",
    "test_port_0922_navigation_wait_recovery.py",
    "test_port_0922_traffic.py",
    "test_port_0922_traffic_jam.py",
    "test_port_0922_traffic_pivot_handoff.py",
    "test_port_0922_driver_arrival.py",
    "test_port_0922_driver_recovery_feedback.py",
    "test_port_0922_driver_block_evidence.py",
    "test_port_0922_driver_side_commit.py",
    "test_port_0922_local_height.py",
    "test_port_0922_spg_modes.py",
    "test_port_0922_spg_route_recovery.py",
    "test_port_0922_route_recovery_cycle.py",
    "test_port_0922_route_task_rules.py",
    "test_port_0922_wait_parking.py",
    "test_port_0922_parking_displacement.py",
    "test_port_0922_empty_ammo_navigation.py",
    "test_port_0922_server_bot_ai.py",
    "test_port_0922_route_arrival_disks.py",
    "test_port_0922_route_priorities.py",
    "test_port_0922_initial_navigation_handoffs.py",
    "test_port_0922_initial_allocation.py",
    "test_port_0922_capture_protection.py",
    "test_port_0922_spg_zone_retry.py",
    "test_port_0922_spg_initial_positions.py",
    "test_port_0922_artillery_controller.py",
)

# Existing fixtures also use the editor's unchanged graph/profile input
# factories. Their behavior imports must follow the same namespace so a
# fixture's mock of cfg.default_map reaches the factory, not the old cfg.
# These launcher helpers are NOT shipped as player behavior or counted as
# migrated classes; only their fixture-local imports are relocated.
FIXTURE_HELPERS = {
    "bot_tactics_store": ROOT / "launcher/bot_tactics_store.py",
    "bot_tactics_geometry": ROOT / "launcher/bot_tactics_geometry.py",
}

# The omitted BotRuntime classes exercise server checkpoint/message authority,
# not the copied client state machine. The retained classes are complete.
CLASSES = {
    "test_port_0922_bot_runtime.py": (
        "BotRuntimeTests", "ShovedWreckTests", "WreckPushMassTests",
        "HumanShovedWreckTests", "BotOwnStationaryVisionTests"),
    "test_port_0922_route_task_rules.py": (
        "RouteTaskTests", "AuthoredArtilleryTravelTests"),
    "test_port_0922_server_bot_ai.py": (
        "ServerBotTacticsTests", "ServerBotCompetenceTests",
        "ServerBotTargetLadderTests", "ServerBotArtilleryTests"),
}
EXCLUDED_CASES = {
    # These two parse the original files as static ABI-contract checks. Their
    # copied-method text equality is covered by test_player_full_behavior_copy.
    "test_port_0922_local_height.py": {
        "test_native_column_recasts_below_each_layer_and_preserves_normals",
        "test_scope_is_released_even_when_the_navigation_decision_throws"},
    # These four instantiate the unchanged server authority, not the copied
    # BotPlanner, and therefore cannot count as copied planner evidence.
    "test_port_0922_server_bot_ai.py": {
        "test_server_damage_accounting_forwards_hostile_bot_threat",
        "test_global_planning_runs_at_one_hz_while_worker_snapshots_stay_30_hz",
        "test_first_live_tick_replans_immediately_after_round_reset",
        "test_observation_and_damage_memory_survive_skipped_plan_ticks"},
    "test_port_0922_spg_initial_positions.py": {
        # Source/resource tooling and authoritative server message admission
        # remain in their original suites, not player planning parity counts.
        "test_all_map_audit_does_not_count_resource_manifest_as_a_map",
        "test_generated_runtime_module_matches_authoring_json",
        "test_real_server_admits_plan_into_canonical_manifest",
        "test_malformed_optional_plan_is_contained_by_real_server"},
}


def load_copied_module(module_name):
    """The original fixture already reloads its module for every test."""
    name = generator.COPY_PREFIX + "." + module_name
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        name, generator.DESTINATION / (module_name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    setattr(importlib.import_module(generator.COPY_PREFIX), module_name, module)
    return module


def load_copied_runtime():
    return load_copied_module("bot_runtime")


class CopyFixtureLoader(importlib.abc.Loader):
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source = self.path.read_text(encoding="utf8")
        transformed, imports = generator.rewrite_imports(source)
        # unittest.mock string targets are another import locator, not test
        # behavior. Leaving @patch('original.ai.navigation...') unchanged
        # would patch the wrong implementation while exercising copied code.
        lines, offsets = generator._offsets(transformed)
        edits = []
        for node in ast.walk(ast.parse(transformed)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            function = node.func
            is_patch = (isinstance(function, ast.Name) and function.id == "patch"
                        or isinstance(function, ast.Attribute) and function.attr == "patch")
            value = node.args[0]
            if not is_patch or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            for original in sorted(
                    [generator.PREFIX + "." + name for name in generator.CLIENT_MODULES] +
                    list(generator.SERVER_MODULES), key=len, reverse=True):
                if value.value == original or value.value.startswith(original + "."):
                    replacement = generator.mirrored_module(original) + value.value[len(original):]
                    edits.append((generator._position(lines, offsets, value.lineno, value.col_offset),
                                  generator._position(lines, offsets, value.end_lineno, value.end_col_offset),
                                  repr(replacement)))
                    break
        for start, end, replacement in sorted(edits, reverse=True):
            transformed = transformed[:start] + replacement + transformed[end:]
        module.__file__ = str(self.path)
        module.__copy_fixture_imports__ = imports
        exec(compile(transformed, str(self.path), "exec"), module.__dict__)
        if self.path.name == "test_port_0922_bot_runtime.py":
            module._load = load_copied_runtime
        elif self.path.name == "test_port_0922_artillery_controller.py":
            module._load = lambda: load_copied_module("artillery_controller")


class CopyFixtureFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in FIXTURE_HELPERS:
            filename = FIXTURE_HELPERS[fullname]
            return importlib.util.spec_from_file_location(
                fullname, filename, loader=CopyFixtureLoader(filename))
        if "." in fullname or not fullname.startswith("test_port_0922_"):
            return None
        # This huge fixture owns stock-engine fakes and the original
        # BattleRuntime initializer. Its extracted behavioral methods are
        # separately rebound in the geometry parity tests.
        if fullname == "test_port_0922_battle_runtime":
            return None
        filename = TESTS / (fullname + ".py")
        if not filename.is_file():
            return None
        return importlib.util.spec_from_file_location(
            fullname, filename, loader=CopyFixtureLoader(filename))


class RecordedResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.test_ids = []

    def startTest(self, test):
        self.test_ids.append(test.id())
        super().startTest(test)


def _selected_suite(module, filename):
    allowed = CLASSES.get(filename)
    excluded = EXCLUDED_CASES.get(filename, ())
    suite = unittest.TestSuite()
    for name, value in sorted(module.__dict__.items()):
        if (not isinstance(value, type) or not issubclass(value, unittest.TestCase)
                or value.__module__ != module.__name__
                or allowed is not None and name not in allowed):
            continue
        for method in unittest.defaultTestLoader.getTestCaseNames(value):
            if method not in excluded:
                suite.addTest(value(method))
    return suite


def worker(filename, copied):
    os.environ["WOT_OFFLINE_DIAGNOSTICS"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path[:0] = [str(ROOT), str(TESTS), str(ROOT / "server"),
                   str(ROOT / "launcher"), str(ROOT / "src/res/scripts/client")]
    if copied:
        sys.meta_path.insert(0, CopyFixtureFinder())
        # Only a file locator changes. No graph/routing decision is patched.
        tasks = importlib.import_module(generator.COPY_PREFIX + ".server_route_tasks")
        tasks.__file__ = str(ROOT / "server/server_route_tasks.py")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        module = importlib.import_module(Path(filename).stem)
        suite = _selected_suite(module, filename)
        result = RecordedResult()
        suite.run(result)
    data = dict(fixture=filename, implementation="copy" if copied else "source",
                tests=result.testsRun, test_ids=result.test_ids,
                excluded=sorted(EXCLUDED_CASES.get(filename, ())),
                errors=[dict(test=test.id(), detail=detail) for test, detail in result.errors],
                failures=[dict(test=test.id(), detail=detail) for test, detail in result.failures],
                skipped=[dict(test=test.id(), reason=reason) for test, reason in result.skipped],
                success=result.wasSuccessful())
    # A test that crashed before loading anything is never a parity success.
    data["success"] = bool(data["success"] and result.testsRun)
    print(json.dumps(data, sort_keys=True))
    return 0 if data["success"] else 1


def run_one(filename, copied, timeout):
    completed = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--worker",
         filename, "--implementation", "copy" if copied else "source"],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", WOT_OFFLINE_DIAGNOSTICS="1"))
    try:
        row = json.loads(completed.stdout.splitlines()[-1])
    except (ValueError, IndexError):
        row = dict(fixture=filename, implementation="copy" if copied else "source",
                   tests=0, test_ids=[], success=False, failures=[],
                   errors=[dict(test="fixture_process", detail=completed.stdout + completed.stderr)])
    if completed.returncode and row.get("success"):
        row.update(success=False, errors=row.get("errors", []) +
                   [dict(test="fixture_process", detail=completed.stderr)])
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="append", choices=FIXTURES,
                        help="Repeat for specific original fixture files; default: all.")
    parser.add_argument("--implementation", choices=("source", "copy", "both"), default="both")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=1200.)
    parser.add_argument("--output-dir", type=Path,
                        help="Write per-fixture JSON and summary.json for CI artifacts.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--worker", choices=FIXTURES)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.implementation == "copy")
    if args.list:
        print(json.dumps(dict(fixtures=FIXTURES, classes=CLASSES,
                              excluded_cases={k: sorted(v) for k, v in EXCLUDED_CASES.items()}),
                         indent=2, sort_keys=True))
        return 0
    fixtures = args.fixture or FIXTURES
    implementations = ((False, True) if args.implementation == "both" else
                       (args.implementation == "copy",))
    rows = []
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(run_one, name, copied, args.timeout): (name, copied)
                   for name in fixtures for copied in implementations}
        for future in concurrent.futures.as_completed(futures):
            name, copied = futures[future]
            try:
                row = future.result()
            except Exception as error:
                row = dict(fixture=name, implementation="copy" if copied else "source",
                           tests=0, test_ids=[], success=False, failures=[],
                           errors=[dict(test="fixture_process", detail=repr(error))])
            rows.append(row)
            if args.output_dir:
                report = args.output_dir / (Path(name).stem + "." + row["implementation"] + ".json")
                report.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf8")
            print("%s %s: %d tests, %d failures, %d errors" % (
                row["implementation"], row["fixture"], row["tests"],
                len(row["failures"]), len(row["errors"])), flush=True)
            for error in row["errors"] + row["failures"]:
                print(error["test"] + "\n" + error["detail"], flush=True)
    success = all(row["success"] for row in rows)
    if args.implementation == "both":
        for name in fixtures:
            group = {row["implementation"]: row for row in rows if row["fixture"] == name}
            if group["source"]["test_ids"] != group["copy"]["test_ids"]:
                success = False
                print("Fixture inventory differs: " + name)
    summary = dict(scope="Same-source copied behavior fixtures; foreground I/O and Windows are separate.",
                   success=success, executions=sum(row["tests"] for row in rows),
                   results=sorted(rows, key=lambda row: (row["fixture"], row["implementation"])))
    if args.output_dir:
        (args.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf8")
        print("Parity %s: %d fixture executions; %d test executions. Reports: %s" % (
            "passed" if success else "FAILED", len(rows), summary["executions"], args.output_dir))
    else:
        print(json.dumps(summary, sort_keys=True))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
