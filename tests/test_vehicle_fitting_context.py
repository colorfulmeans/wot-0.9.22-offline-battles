"""Installed fitting facts are readable without importing Bot decisions."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace as NS
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'src/res/scripts/client'
sys.path.insert(0, str(CLIENT))


class VehicleFittingContextTests(unittest.TestCase):
    def isolated(self, script):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(CLIENT), str(ROOT / 'tests'))),
                   PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', textwrap.dedent(script)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_player_loadout_modifiers_do_not_import_bot_modules(self):
        self.isolated('''
            import sys
            from types import SimpleNamespace
            class NoBot(object):
                def find_spec(self, fullname, path=None, target=None):
                    if (fullname.startswith('gui.mods.offline_lan_0922.') and
                            fullname.rsplit('.', 1)[-1].startswith('bot_')):
                        raise ImportError('player loadout entered Bot dependency: ' + fullname)
                    return None
            sys.meta_path.insert(0, NoBot())
            from gui.mods.offline_lan_0922 import loadout
            descriptor = SimpleNamespace(optionalDevices=(), miscAttrs={})
            result = loadout.modifiers(descriptor, crew_skills=(('brotherhood',),))
            assert result['has_brotherhood']
            assert result['reload_factor'] > 0.
        ''')

    def test_fitting_reconstruction_does_not_import_bot_runtime_for_crew_names(self):
        self.isolated('''
            import sys
            from unittest.mock import patch
            from test_bot_fittings import FittingContracts, fitting
            class NoRuntime(object):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'gui.mods.offline_lan_0922.bot_runtime':
                        raise ImportError('descriptor reconstruction loaded BotRuntime')
                    return None
            sys.meta_path.insert(0, NoRuntime())
            fixture = FittingContracts()
            with patch.dict(sys.modules, fixture._items()):
                descriptor = fitting.build(fixture._native('ussr:R04_T-34', 'regular'),
                                           'ussr:R04_T-34', 'regular')
            assert fitting.context(descriptor)['crew_roster'] == ('commander', 'loader1')
            assert 'gui.mods.offline_lan_0922.bot_runtime' not in sys.modules
        ''')

    def test_ammunition_health_uses_native_fitting_without_bot_imports(self):
        self.isolated('''
            import sys
            from types import SimpleNamespace as NS
            class NoBot(object):
                def find_spec(self, fullname, path=None, target=None):
                    if (fullname.startswith('gui.mods.offline_lan_0922.') and
                            fullname.rsplit('.', 1)[-1].startswith('bot_')):
                        raise ImportError('device health entered Bot dependency: ' + fullname)
                    return None
            sys.meta_path.insert(0, NoBot())
            from gui.mods.offline_lan_0922 import device_damage
            from gui.mods.offline_lan_0922 import vehicle_fitting_context as fittings
            descriptor = NS(hull=NS(ammoBayHealth=NS(maxHealth=100, maxRegenHealth=50)),
                            miscAttrs={'ammoBayHealthFactor': 1.5})
            assert device_damage.device_max_hp(descriptor, 'ammoBayHealth') == 150
            fittings.register(descriptor, dict(crew_roster=(), factors={
                (id(descriptor), (), False, ()): {'offline/ammoBayHealth': 1.2}}))
            assert device_damage.device_max_hp(descriptor, 'ammoBayHealth') == 180
            assert device_damage.device_regen_hp(descriptor, 'ammoBayHealth') == 90
            fittings.clear()
            assert device_damage.device_max_hp(descriptor, 'ammoBayHealth') == 150
        ''')

    def test_native_factor_chain_uses_installed_crew_without_bot_imports(self):
        self.isolated('''
            import sys
            from types import SimpleNamespace as NS
            from unittest.mock import patch
            class NoBot(object):
                def find_spec(self, fullname, path=None, target=None):
                    if (fullname.startswith('gui.mods.offline_lan_0922.') and
                            fullname.rsplit('.', 1)[-1].startswith('bot_')):
                        raise ImportError('native factor read entered Bot dependency: ' + fullname)
                    return None
            sys.meta_path.insert(0, NoBot())
            from test_port_0922_loadout import ClientFactorTests
            from gui.mods.offline_lan_0922 import loadout, vehicle_fitting_context as fittings
            utils, modules = ClientFactorTests()._native_factor_modules()
            descriptor = NS(type=NS(crewRoles=(('commander',), ('loader',))),
                            optionalDevices=(), miscAttrs={'gunReloadTimeFactor': .875})
            value = dict(wire={'crew_level': 75}, crew=('first', 'second'), directives=(),
                         crew_roster=('commander', 'loader1'), crew_skills=((), ()))
            fittings.register(descriptor, value)
            calls = []
            def update(desc, crew, equipments, factors, flags, fire, *native):
                calls.append((tuple(crew), tuple(flags), fire))
                factors['gun/reloadTime'] = .9
            with patch.object(loadout, '_client_modules', return_value=modules), \\
                    patch.object(loadout, '_update_native_attribute_factors_with_split',
                                 side_effect=update):
                factors = fittings.native_factors(descriptor,
                    {'crew_ko': ('loader1',), 'fire': True})
                result = loadout.modifiers(descriptor, factors=factors)
            assert calls == [(('first', 'second'), (True, False), True)]
            assert abs(result['reload_factor'] - .7875) < 1.e-12
            assert factors['_aspects'] == (0, 1)
            utils.generateDefaultCrew.assert_not_called()
        ''')

    def test_registry_and_public_bot_compatibility_aliases_share_one_owner(self):
        from gui.mods.offline_lan_0922 import bot_fittings, vehicle_fitting_context as fittings
        for name in ('context', 'clear', 'register', 'native_factors', 'battle_factors',
                     'skill_snapshot', 'skill_count', 'skill_level'):
            self.assertIs(getattr(fittings, name), getattr(bot_fittings, name), name)
        self.assertIs(fittings._CONTEXTS, bot_fittings._CONTEXTS)
        self.addCleanup(fittings.clear)
        travel, siege = NS(), NS()
        composite = NS(defaultVehicleDescr=travel, siegeVehicleDescr=siege, hasSiegeMode=True)
        value = dict(crew=('crew data',))
        fittings.register(composite, value)
        for descriptor in (composite, travel, siege):
            self.assertIs(value, bot_fittings.context(descriptor))
        self.assertIsNone(fittings.context(NS()))
        bot_fittings.clear()
        self.assertIsNone(fittings.context(composite))

    def test_crew_roster_keeps_exact_instance_names_and_rejects_invalid_rosters(self):
        from gui.mods.offline_lan_0922.vehicle_fitting_context import descriptor_crew_roster
        descriptor = NS(type=NS(crewRoles=(('commander', 'radioman'), ('driver',),
                        ('gunner',), ('loader',), ('loader',), ('radioman',))))
        self.assertEqual(('commander', 'driver', 'gunner1', 'loader1', 'loader2', 'radioman1'),
                         descriptor_crew_roster(descriptor))
        for roles in (None, (), ('commander',), ((),), (('invalid',),),
                      (('commander',), ('commander',))):
            self.assertEqual((), descriptor_crew_roster(NS(type=NS(crewRoles=roles))))

    def test_native_cache_separates_crew_fire_equipment_and_retains_diagnostic_contract(self):
        from gui.mods.offline_lan_0922 import loadout, native_input_diagnostics as diagnostic
        from gui.mods.offline_lan_0922 import vehicle_fitting_context as fittings
        self.addCleanup(fittings.clear)
        descriptor = NS(type=NS(name='ussr:R04_T-34'), optionalDevices=(),
                        gun=NS(reloadTime=10.), miscAttrs={'gunReloadTimeFactor': .875})
        value = dict(wire=dict(vehicle='ussr:R04_T-34', tier='regular', crew_level=75),
                     crew_roster=('commander', 'loader1'), crew_skills=())
        fittings.register(descriptor, value)
        with mock.patch.object(loadout, 'attribute_factors',
                side_effect=lambda *args, **kwargs: {'gun/reloadTime': .9}) as native, \
                mock.patch.object(diagnostic, 'detailed_enabled', return_value=True), \
                mock.patch.object(diagnostic, 'validation_event') as emit:
            baseline = fittings.native_factors(descriptor)
            self.assertIs(baseline, fittings.native_factors(descriptor))
            for critical, equipment in (({'crew_ko': ('loader1',)}, ()),
                                        ({'fire': True}, ()), ({}, (123,))):
                self.assertIsNot(baseline, fittings.native_factors(descriptor, critical, equipment))
        self.assertEqual(4, native.call_count)
        self.assertEqual(4, emit.call_count)
        self.assertEqual([(True, True), (True, False), (True, True), (True, True)],
                         [call.kwargs['activity_flags'] for call in native.call_args_list])
        self.assertEqual([False, False, True, False],
                         [call.kwargs['is_fire'] for call in native.call_args_list])
        self.assertEqual((123,), native.call_args.kwargs['equipments'])
        for call in emit.call_args_list:
            self.assertEqual('bot_effective_factors', call.args[0])
            self.assertAlmostEqual(7.875, call.kwargs['effective_reload_seconds'])


if __name__ == '__main__':
    unittest.main()
