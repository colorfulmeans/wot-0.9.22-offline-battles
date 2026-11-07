"""Foreground shot admission uses its copy, never the original Bot owner."""
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
    def test_admission_import_does_not_load_bot_policy_or_lan_client(self):
        # A fresh process matters: existing integration fixtures can already
        # have imported BotRuntime, hiding an accidental transitive import.
        script = textwrap.dedent('''
            import importlib
            import sys

            class NoBotPolicy(object):
                def find_spec(self, fullname, path=None, target=None):
                    prefix = 'gui.mods.offline_lan_0922.'
                    if not fullname.startswith(prefix):
                        return None
                    root = fullname[len(prefix):].split('.', 1)[0]
                    if (root in ('ai', 'bots', 'lan_client') or
                            root.startswith('bot_') and root not in (
                                'bot_state_codec', 'bot_editor_maps',
                                'bot_tactics_default_data', 'bot_fitting_data')):
                        raise ImportError('foreground loaded original Bot owner: ' + fullname)
                    return None

            sys.meta_path.insert(0, NoBotPolicy())
            prefix = 'gui.mods.offline_lan_0922.'
            for name in ('native_aim', 'attack_policy', 'trigger_admission', 'full_runtime'):
                importlib.import_module(prefix + 'player_control.' + name)
            assert prefix + 'lan_client' not in sys.modules
            assert prefix + 'bot_runtime' not in sys.modules
            assert prefix + 'player_control.copied.bot_runtime' in sys.modules
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
