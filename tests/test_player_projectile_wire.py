"""Shared shot admission preserves the native projectile wire contract."""
import decimal
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'src/res/scripts/client'
sys.path.insert(0, str(CLIENT))


class PlayerProjectileWireTests(unittest.TestCase):
    def test_admission_uses_one_shared_owner_without_retired_or_network_imports(self):
        # A fresh process matters: existing integration fixtures can already
        # have imported network owners, hiding accidental transitive imports.
        script = textwrap.dedent('''
            import importlib
            import sys

            class NoRetiredOrNetworkOwner(object):
                def find_spec(self, fullname, path=None, target=None):
                    prefix = 'gui.mods.offline_lan_0922.'
                    if not fullname.startswith(prefix):
                        return None
                    root = fullname[len(prefix):].split('.', 1)[0]
                    if root in ('player_control', 'bots', 'lan_client') or '.copied.' in fullname:
                        raise ImportError('shared control loaded retired/network owner: ' + fullname)
                    return None

            sys.meta_path.insert(0, NoRetiredOrNetworkOwner())
            prefix = 'gui.mods.offline_lan_0922.'
            modules = dict((name, importlib.import_module(prefix + 'vehicle_control.' + name))
                for name in ('native_aim', 'attack_policy', 'trigger_admission',
                             'combat_control', 'full_runtime', 'bot_binding'))
            wire = importlib.import_module(prefix + 'projectile_wire')
            control = modules['combat_control'].CombatControl
            assert issubclass(modules['full_runtime'].FullPlayerRuntime, control)
            assert issubclass(modules['bot_binding'].BotControlBinding, control)
            assert modules['full_runtime'].AttackPolicy is modules['attack_policy'].AttackPolicy
            assert modules['bot_binding'].AttackPolicy is modules['attack_policy'].AttackPolicy
            assert modules['trigger_admission'].round_scalar is wire.round_scalar
            assert prefix + 'bot_runtime' in sys.modules
            assert prefix + 'lan_client' not in sys.modules
            assert not any(name.startswith(prefix + 'player_control') or
                name.startswith(prefix) and '.copied.' in name for name in sys.modules)
        ''')
        env = dict(os.environ, PYTHONPATH=str(CLIENT), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', script], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_lan_protocol_alias_uses_the_same_neutral_rounding_contract(self):
        from gui.mods.offline_lan_0922 import lan_client, projectile_wire
        self.assertIs(projectile_wire.round_scalar, lan_client._projectile_wire_round)

    def test_half_even_and_signed_zero_match_exact_decimal_oracle(self):
        from gui.mods.offline_lan_0922.projectile_wire import round_scalar
        rng = random.Random(1513)
        values = [0., -0., .0078125, -.0078125, .0000015, -.0000015,
                  .0000001, -.0000001, 5000., -5000., 10000., -10000.]
        values.extend(rng.uniform(-10000., 10000.) for unused in range(1024))
        values.extend(rng.uniform(-.00001, .00001) for unused in range(128))
        with decimal.localcontext() as context:
            context.prec = 50
            for value in values:
                expected = float(decimal.Decimal.from_float(value).quantize(
                    decimal.Decimal('0.000001'), rounding=decimal.ROUND_HALF_EVEN))
                actual = round_scalar(value)
                self.assertEqual(expected, actual, repr(value))
                self.assertEqual(math.copysign(1., expected),
                                 math.copysign(1., actual), repr(value))

    def test_scalar_keeps_existing_float_conversion_and_nonfinite_rejection(self):
        from gui.mods.offline_lan_0922.projectile_wire import round_scalar
        self.assertEqual(1., round_scalar(1))
        self.assertEqual(.007812, round_scalar('0.0078125'))
        for value in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaises((ValueError, OverflowError)):
                round_scalar(value)


if __name__ == '__main__':
    unittest.main()
