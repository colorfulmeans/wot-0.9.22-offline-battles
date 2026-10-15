"""Native #1513 garage block contract and optional velocity enrichment."""
import copy
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922.garage_shell_tooltip import GarageShellTooltipPatch


def _fixture(damage='damage', speed=1415, kind='ARMOR_PIERCING_CR'):
    labels = {'damage': '伤害', 'avgDamage': '平均伤害'}
    text = lambda value: value.decode('utf-8') if isinstance(value, bytes) else value
    main = lambda value: '<main>%s</main>' % text(value)

    class Constructor(object):
        def __init__(self):
            self.shell = types.SimpleNamespace(descriptor=types.SimpleNamespace(
                compactDescr=42, kind=kind))
            # Different descriptor identity and a distractor shot ensure that
            # velocity comes from this gun's matching shell compact descriptor.
            shots = [GunShot(7, speed), GunShot(42, speed), GunShot(8, 999)]
            self.configuration = types.SimpleNamespace(params=True,
                vehicle=types.SimpleNamespace(descriptor=types.SimpleNamespace(
                    gun=types.SimpleNamespace(shots=shots),
                    activeGunShotIndex=0)))
            self._valueWidth = 80
            self.rows = [self._packParameterBlock('口径', '105', ' (毫米)'),
                         self._packParameterBlock(labels[damage], '293–488', ' (HP)'),
                         self._packParameterBlock('穿透力', '270–255', ' (毫米)'),
                         {'type': 'nativeFootnote', 'data': {'text': 'native note'}}]

        def _packParameterBlock(self, name, value, units):
            # Shape and styles verified from #1513 shell.pyc/formatters.pyc.
            return {'linkage': 'textParameterBlock', 'padding': {'left': -5},
                    'data': {'name': main(name) + '<standard>%s</standard>' % text(units),
                             'value': '<stats>%s</stats>' % value,
                             'valueWidth': self._valueWidth}}

        def construct(self):
            return copy.deepcopy(self.rows)

    class Advanced(Constructor):
        def construct(self):
            return copy.deepcopy(self.rows)

    class GunShot(object):
        def __init__(self, compact_descr, velocity):
            self.shell = types.SimpleNamespace(compactDescr=compact_descr)
            self.speed = velocity

        def get(self, *unused):
            raise AssertionError('Operation is not allowed')
        __getitem__ = get

    module = types.SimpleNamespace(CommonStatsBlockConstructor=Constructor,
        _AdvancedCommonStatsBlockConstructior=Advanced,
        text_styles=types.SimpleNamespace(main=main),
        params_formatters=types.SimpleNamespace(BASE_SCHEME=(
            lambda value: '<red>%s</red>' % value,
            lambda value: '<stats>%s</stats>' % value,
            lambda value: '<green>%s</green>' % value)),
        _ms=lambda key: labels[key.rsplit('/', 1)[-1]])
    return module, GarageShellTooltipPatch(module, lambda value: '{:,}'.format(value))


class GarageShellTooltipTests(unittest.TestCase):
    def test_speed_comparison_uses_native_scheme_and_each_views_baseline(self):
        for kind in ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR',
                     'HOLLOW_CHARGE', 'HIGH_EXPLOSIVE'):
            for speed, color in ((1400, 'green'), (800, 'red'), (1000, None)):
                module, patch = _fixture(speed=speed, kind=kind)
                patch.install()
                for advanced, owner in ((False, module.CommonStatsBlockConstructor),
                        (True, module._AdvancedCommonStatsBlockConstructior)):
                    constructor = owner()
                    descriptor = constructor.configuration.vehicle.descriptor
                    descriptor.gun.shots[0].speed = 2000 if advanced else 1000
                    descriptor.gun.shots[2].speed = 1000 if advanced else 2000
                    descriptor.activeGunShotIndex = 2
                    before = copy.deepcopy(constructor.rows)
                    result = constructor.construct()
                    number = '{:,}'.format(speed)
                    if color:
                        number = '<%s>%s</%s>' % (color, number, color)
                    with self.subTest(kind=kind, speed=speed, advanced=advanced):
                        self.assertEqual('<stats>%s</stats>' % number,
                                         result[2]['data']['value'])
                        self.assertEqual(2, descriptor.activeGunShotIndex)
                        self.assertEqual(before, result[:2] + result[3:])
                        self.assertEqual(before, constructor.rows)
                patch.uninstall()

    def test_unavailable_or_invalid_comparison_keeps_plain_velocity(self):
        for baseline in (0, float('nan'), float('inf')):
            module, patch = _fixture()
            patch.install()
            constructor = module.CommonStatsBlockConstructor()
            constructor.configuration.vehicle.descriptor.gun.shots[0].speed = baseline
            self.assertEqual('<stats>1,415</stats>',
                             constructor.construct()[2]['data']['value'])
            patch.uninstall()
        for index in (None, -1, 10):
            module, patch = _fixture()
            patch.install()
            constructor = module._AdvancedCommonStatsBlockConstructior()
            constructor.configuration.vehicle.descriptor.activeGunShotIndex = index
            self.assertEqual('<stats>1,415</stats>',
                             constructor.construct()[2]['data']['value'])
            patch.uninstall()

    def test_compatibility_lifecycle_installs_and_restores_native_garage_methods(self):
        from test_port_0922 import OfflineCompatibilityTests, _load_port_source
        runtime, unused_operations = OfflineCompatibilityTests()._runtime()
        module, unused_patch = _fixture()
        runtime.garage_shell_tooltip_module = module
        runtime.bigworld.wg_getNiceNumberFormat = lambda value: '{:,}'.format(value)
        owner = module.CommonStatsBlockConstructor
        original = owner.__dict__['construct']
        compatibility = _load_port_source('compat').OfflineCompatibility(runtime)
        compatibility.install()
        try:
            self.assertEqual(5, len(owner().construct()))
        finally:
            compatibility.fini()
        self.assertIs(original, owner.__dict__['construct'])

    def test_all_shell_families_and_both_native_views_keep_rows_and_add_after_damage(self):
        for damage in ('damage', 'avgDamage'):
            for kind in ('ARMOR_PIERCING', 'ARMOR_PIERCING_CR',
                         'HOLLOW_CHARGE', 'HIGH_EXPLOSIVE'):
                module, patch = _fixture(damage=damage, kind=kind)
                patch.install()
                for owner in (module.CommonStatsBlockConstructor,
                              module._AdvancedCommonStatsBlockConstructior):
                    with self.subTest(damage=damage, kind=kind, owner=owner):
                        constructor = owner()
                        before = copy.deepcopy(constructor.rows)
                        result = constructor.construct()
                        self.assertEqual(before, result[:2] + result[3:])
                        expected = constructor._packParameterBlock(
                            '炮弹速度', '1,415', ' (米/秒)')
                        self.assertEqual(expected, result[2])
                        self.assertEqual(before, constructor.rows)
                patch.uninstall()

    def test_no_context_wrong_shell_or_invalid_speed_preserves_native_details(self):
        for scenario in ('no_vehicle', 'wrong_shell', 'zero', 'nan', 'infinity'):
            module, patch = _fixture()
            patch.install()
            constructor = module.CommonStatsBlockConstructor()
            if scenario == 'no_vehicle':
                constructor.configuration.vehicle = None
            elif scenario == 'wrong_shell':
                constructor.shell.descriptor.compactDescr = 123
            else:
                constructor.configuration.vehicle.descriptor.gun.shots[1].speed = {
                    'zero': 0, 'nan': float('nan'), 'infinity': float('inf')}[scenario]
            with self.subTest(scenario=scenario):
                self.assertEqual(constructor.rows, constructor.construct())
            patch.uninstall()

    def test_disabled_parameter_display_and_existing_speed_are_not_duplicated(self):
        module, patch = _fixture()
        patch.install()
        constructor = module.CommonStatsBlockConstructor()
        constructor.rows = []
        self.assertEqual([], constructor.construct())
        constructor = module.CommonStatsBlockConstructor()
        constructor.rows.insert(2, constructor._packParameterBlock(
            '炮弹速度', '1,415', ' (米/秒)'))
        self.assertEqual(constructor.rows, constructor.construct())

    def test_optional_formatter_failure_does_not_break_native_view(self):
        module, patch = _fixture()
        patch.install()
        constructor = module.CommonStatsBlockConstructor()
        def fail(unused):
            raise ValueError('format unavailable')
        patch._number_format = fail
        self.assertEqual(constructor.rows, constructor.construct())
        self.assertTrue(patch._warned)

    def test_reversible_install_is_idempotent_and_does_not_overwrite_other_mods(self):
        module, patch = _fixture()
        owner = module.CommonStatsBlockConstructor
        original = owner.__dict__['construct']
        patch.install()
        wrapper = owner.__dict__['construct']
        patch.install()
        self.assertIs(wrapper, owner.__dict__['construct'])
        patch.uninstall()
        self.assertIs(original, owner.__dict__['construct'])
        patch.install()
        third_party = lambda self: []
        owner.construct = third_party
        patch.uninstall()
        self.assertIs(third_party, owner.__dict__['construct'])


if __name__ == '__main__':
    unittest.main()
