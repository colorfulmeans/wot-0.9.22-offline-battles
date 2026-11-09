"""Paired physical fixtures share complete initial state, not native C-API proof."""

import builtins
import contextlib
import importlib.util
import io
from pathlib import Path
import random
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_NAME = '_native_motion_initial_state_fixture'


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class InitialStateTests(unittest.TestCase):
    def setUp(self):
        self.original_modules = dict(sys.modules)
        self.addCleanup(self.restore_modules)
        self.scope = contextlib.ExitStack()
        self.addCleanup(self.scope.close)
        # The production gate runs CPython 2.7. These test-only names allow its
        # pure fixture construction on Python 3 without claiming C-API parity.
        for name, value in (('xrange', range), ('long', int), ('unicode', str)):
            self.scope.enter_context(mock.patch.object(
                builtins, name, value, create=True))
        imp_loader = types.ModuleType('imp')
        imp_loader.load_source = load_source
        self.scope.enter_context(mock.patch.dict(sys.modules, {'imp': imp_loader}))
        self.fixture = load_source(
            FIXTURE_NAME, ROOT / 'tools/native_simulation_motion_fixture.py')
        self.bot = self.fixture.bot_runtime

    def restore_modules(self):
        names = set(sys.modules) | set(self.original_modules)
        for name in names:
            if (name in ('gui', 'BigWorld', 'Math', FIXTURE_NAME,
                         'full_tick_destructibles') or name.startswith('gui.')):
                if name in self.original_modules:
                    sys.modules[name] = self.original_modules[name]
                else:
                    sys.modules.pop(name, None)

    def scene(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.fixture.HostScene('movement', native_library='', **kwargs)

    def test_all_three_arms_have_identical_complete_initial_states(self):
        scenes = [self.scene() for unused in range(3)]
        expected = scenes[0].runtime.states
        self.assertEqual(29, len(expected))
        self.assertTrue(all(state.get('route') for state in expected.values()))
        for scene in scenes[1:]:
            self.assertEqual(expected, scene.runtime.states)
            self.assertEqual(scenes[0].runtime._initial_allocation_seed,
                             scene.runtime._initial_allocation_seed)
            self.assertEqual(
                {actor: agent['route'] for actor, agent in
                 scenes[0].runtime.adapter.director.agents.items()},
                {actor: agent['route'] for actor, agent in
                 scene.runtime.adapter.director.agents.items()})

    def test_bootstrap_scope_preserves_stdlib_and_other_random_operations(self):
        case = self
        source = self.bot.random
        system_random = random.SystemRandom
        observed = []

        class CheckedRuntime(self.bot.BotRuntime):
            def battle_start(self, message):
                case.assertIsNot(source, case.bot.random)
                case.assertIs(system_random, random.SystemRandom)
                case.assertIs(source.Random, case.bot.random.Random)
                case.assertIs(source.random, case.bot.random.random)
                observed.append(True)
                return super(CheckedRuntime, self).battle_start(message)

        self.scene(runtime_class=CheckedRuntime)
        self.assertEqual([True], observed)
        self.assertIs(source, self.bot.random)
        self.assertIs(system_random, random.SystemRandom)

    def test_failed_construction_restores_the_original_random_owner(self):
        case = self
        source = self.bot.random
        system_random = random.SystemRandom

        class FailingRuntime(self.bot.BotRuntime):
            def battle_start(self, message):
                case.assertIsNot(source, case.bot.random)
                raise ValueError('fixture construction boundary')

        with self.assertRaisesRegex(ValueError, 'fixture construction boundary'):
            self.scene(runtime_class=FailingRuntime)
        self.assertIs(source, self.bot.random)
        self.assertIs(system_random, random.SystemRandom)


if __name__ == '__main__':
    unittest.main()
