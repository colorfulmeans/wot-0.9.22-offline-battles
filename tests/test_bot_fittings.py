"""Four-tier fitting identity, native install guards and immutable wire contracts."""
import base64
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import bot_fittings as fitting
from gui.mods.offline_lan_0922.bot_fitting_data import PLANS, CLASSES


class FittingContracts(unittest.TestCase):
    def tearDown(self):
        fitting.clear()

    def test_complete_catalog_and_tier_policy(self):
        self.assertEqual(len(PLANS), 576)
        self.assertEqual(set(PLANS), set(CLASSES))
        for vehicle, tiers in PLANS.items():
            self.assertEqual(set(tiers), set(fitting.TIERS), vehicle)
            for tier, value in tiers.items():
                self.assertEqual(value['crew'], fitting.crew_level(tier))
                self.assertEqual(len(value['modules']), 6)
                self.assertEqual(len(value['devices']), dict(rookie=0, regular=1, veteran=3, elite=3)[tier])
                self.assertEqual(len(set(value['devices'])), len(value['devices']))
                self.assertEqual(bool(value['directive']), tier == 'elite')
                if tier != 'elite':
                    self.assertIsNone(value['style'])
            self.assertEqual(tiers['elite']['modules'], tiers['veteran']['modules'])
            self.assertEqual(tiers['regular']['devices'], tiers['veteran']['devices'][:1])

    def test_reviewed_outfit_exceptions(self):
        excluded = [v for v, tiers in PLANS.items() if tiers['elite']['style'] is None]
        self.assertEqual(len(excluded), 22)
        for vehicle in ('france:F69_AMX13_57_100_GrandFinal', 'china:Ch03_WZ_111_A',
                        'china:Ch01_Type59_Gold', 'poland:Pl03_PzV_Poland'):
            self.assertIn(vehicle, excluded)

    def test_outfit_switch_is_independent_and_preserves_every_locked_exception(self):
        for vehicle, tiers in PLANS.items():
            for tier in fitting.TIERS:
                original = fitting.plan(vehicle, tier)
                enabled = fitting.plan(vehicle, tier, {'outfit': 'on'})
                disabled = fitting.plan(vehicle, tier, {'outfit': 'off'})
                self.assertEqual(tiers['elite']['style'], enabled.pop('style'), vehicle)
                self.assertIsNone(disabled.pop('style'), vehicle)
                original.pop('style')
                self.assertEqual(original, enabled)
                self.assertEqual(original, disabled)
        with self.assertRaises(ValueError):
            fitting.plan('ussr:R04_T-34', 'elite', {'outfit': 'arbitrary style'})

    def test_independent_native_build_restores_the_same_override_identity(self):
        vehicle='ussr:R04_T-34'
        overrides=dict(development='full',equipment='none',crew_preset='50',outfit='off')
        with patch.dict(sys.modules,self._items()):
            native=self._native(vehicle,'elite')
            descriptor=fitting.build(native,vehicle,'regular',overrides=overrides)
            context=fitting.context(descriptor)
            self.assertEqual(50,context['wire']['crew_level'])
            self.assertEqual([],context['wire']['devices']);self.assertIsNone(context['wire']['directive'])
            self.assertEqual((),context['skills']);self.assertEqual(overrides,context['wire']['overrides'])
            self.assertEqual(context['wire'],fitting.canonical(context['wire']))

    def test_wire_rejects_policy_tampering_and_bad_descriptors(self):
        vehicle = 'ussr:R04_T-34'
        expected = fitting.plan(vehicle, 'elite')
        value = dict(schema=1, vehicle=vehicle, tier='elite', crew_level=100,
                     descriptor=base64.b64encode(b'native fitting').decode(),
                     devices=expected['devices'], directive=expected['directive'], style=expected['style'])
        self.assertEqual(fitting.canonical(value), value)
        for key, bad in [('crew_level', True), ('crew_level', 49), ('crew_level', 75.5),
                         ('descriptor', '!!!'), ('descriptor', 'YQ==\n'),
                         ('devices', []), ('directive', None), ('style', None),
                         ('tier', 'invalid'), ('vehicle', 'unknown')]:
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                fitting.canonical(dict(value, **{key: bad}))

    def test_copy_isolation_and_descriptor_lifetime(self):
        original = fitting.plan('ussr:R04_T-34', 'regular')
        changed = fitting.plan('ussr:R04_T-34', 'regular')
        changed['modules']['gun'] = 'wrong'
        self.assertEqual(fitting.plan('ussr:R04_T-34', 'regular'), original)
        descriptor = NS(type=NS(name='ussr:R04_T-34'))
        other = NS(type=NS(name='ussr:R04_T-34'))
        fitting.register(descriptor, {'crew': (50,)})
        self.assertEqual(fitting.context(descriptor), {'crew': (50,)})
        self.assertIsNone(fitting.context(other))
        fitting.clear()
        self.assertIsNone(fitting.context(descriptor))

    def _native(self, vehicle, tier, refuse=False):
        """Mirror cache, tuple admission, serialization and outfit ABI shapes."""
        chosen = fitting.plan(vehicle, tier)
        parts = chosen['modules']
        components = {name: NS(name=name, compactDescr=name) for name in parts.values()}
        turret = components[parts['turret']]
        turret.guns = [components[parts['gun']]]
        typ = NS(name=vehicle, id=(0, 1), crewRoles=(('commander',), ('loader',)),
                 tags=(), chassis=[components[parts['chassis']]],
                 engines=[components[parts['engine']]], radios=[components[parts['radio']]],
                 fuelTanks=[components[parts['fuel_tank']]], turrets=[[turret]])
        devices = {name: NS(name=name, compactDescr=name) for name in chosen['devices']}
        native = NS()
        class Descriptor:
            def __init__(self, typeName=None, compactDescr=None):
                self.type = typ
                self.optionalDevices = [None]*3
                for kind, attribute in [('chassis','chassis'),('engine','engine'),('radio','radio'),
                                        ('fuel_tank','fuelTank'),('turret','turret'),('gun','gun')]:
                    setattr(self, attribute, components[parts[kind]])
                if compactDescr is not None:
                    for slot, name in enumerate(json.loads(compactDescr.decode())['devices']):
                        self.optionalDevices[slot] = devices[name]
            def installComponent(self, cd, position):
                self.assert_component(cd)
            def assert_component(self, cd):
                if cd not in components:
                    raise ValueError('unknown native component')
            def mayInstallComponent(self, cd, position):
                return (True, None)
            def mayInstallTurret(self, turret, gun, position):
                return (True, None)
            def installTurret(self, turret, gun, position):
                self.assert_component(turret)
                self.assert_component(gun)
            def mayInstallOptionalDevice(self, cd, slot):
                return (not refuse, 'native compatibility refusal' if refuse else None)
            def installOptionalDevice(self, cd, slot):
                if not self.mayInstallOptionalDevice(cd, slot)[0]:
                    raise AssertionError('tuple refusal ignored')
                self.optionalDevices[slot] = devices[cd]
            def makeCompactDescr(self):
                return json.dumps(dict(modules=parts, devices=[d.name for d in self.optionalDevices if d]),
                                  sort_keys=True).encode()
        native.VehicleDescr = Descriptor
        outfit = NS(camouflages=[NS(id=17, appliedTo=4368)])
        native.g_cache = NS(optionalDevices=lambda: devices, optionalDeviceIDs=lambda: {n:n for n in devices},
            equipments=lambda: {chosen['directive']: NS(name=chosen['directive'])},
            equipmentIDs=lambda: {chosen['directive']:chosen['directive']},
            customization20=lambda: NS(styles={chosen['style']:NS(outfits={
                1:outfit,2:outfit,4:outfit,8:NS(camouflages=[])})}))
        return native

    def _items(self):
        return {'items': NS(tankmen=NS(getSkillsMask=lambda names: tuple(names),
                  generateTankmen=lambda nation, vehicle, roles, premium, level, mask, preview: [
                      (level,mask)]*len(roles),
                  TankmanDescr=lambda raw: NS(skills=raw[1] if isinstance(raw[1],tuple) else ('repair','camouflage'))),
                  customizations=NS(makeCompDescr=lambda outfit: b'native outfit')),
                'items.components': NS(),
                'items.components.c11n_constants': NS(ApplyArea=NS(HULL=16))}

    def test_report_023439_elite_t71_accepts_native_empty_event_outfit(self):
        with patch.dict(sys.modules, self._items()):
            native = self._native('usa:A103_T71E1','elite')
            descriptor = fitting.build(native,'usa:A103_T71E1','elite')
            context = fitting.context(descriptor)
            self.assertEqual(context['wire']['style'],8)
            self.assertEqual(set(context['outfits']),{'1','2','4','8'})
            self.assertIsNone(context['camouflages']['8'])
            for season in ('1','2','4'):
                self.assertEqual(context['camouflages'][season],17)
            restored = fitting.build(native,'usa:A103_T71E1','elite',restored=context['wire'])
            self.assertEqual(fitting.context(restored)['wire'],context['wire'])

    def test_absent_hull_camouflage_has_no_invisibility_bonus(self):
        from gui.mods.offline_lan_0922 import bot_runtime
        calls = []
        descriptor = NS(type=NS(name='usa:A103_T71E1'),
                        computeBaseInvisibility=lambda factor,camo: calls.append((factor,camo)) or (0.1,0.2))
        fitting.register(descriptor,dict(season='8',camouflages={'1':15202,'8':None}))
        profile = {'camouflage_factor':1.0}
        self.assertEqual(bot_runtime._base_invisibility(descriptor,profile),(0.1,0.2))
        self.assertEqual(calls[-1],(1.0,None))
        fitting.context(descriptor)['season']='1'
        bot_runtime._base_invisibility(descriptor,profile)
        self.assertEqual(calls[-1],(1.0,15202))

    def test_only_hull_regions_select_camouflage(self):
        self.assertIsNone(fitting.hull_camouflage(NS(camouflages=[]),16))
        self.assertIsNone(fitting.hull_camouflage(NS(camouflages=[NS(id=17,appliedTo=4096)]),16))
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            fitting.hull_camouflage(NS(camouflages=[NS(id=17,appliedTo=16),NS(id=18,appliedTo=16)]),16)

    def test_all_four_tiers_build_and_restore_through_native_contract(self):
        for tier in fitting.TIERS:
            with self.subTest(tier=tier), patch.dict(sys.modules, self._items()):
                native = self._native('ussr:R04_T-34', tier)
                descriptor = fitting.build(native, 'ussr:R04_T-34', tier)
                context = fitting.context(descriptor)
                self.assertEqual(context['crew'][0][0], fitting.crew_level(tier))
                self.assertEqual(bool(context['directives']), tier == 'elite')
                self.assertEqual(bool(context['outfits']), tier == 'elite')
                restored = fitting.build(native, 'ussr:R04_T-34', tier, restored=context['wire'])
                self.assertEqual(context['wire'], fitting.context(restored)['wire'])
                bad = dict(context['wire'], descriptor=base64.b64encode(b'other').decode())
                with self.assertRaisesRegex(ValueError, 'restored'):
                    fitting.build(native, 'ussr:R04_T-34', tier, restored=bad)

    def test_native_device_refusal_does_not_install(self):
        with patch.dict(sys.modules, self._items()), self.assertRaisesRegex(ValueError, 'installation refused'):
            fitting.build(self._native('ussr:R04_T-34','regular',True), 'ussr:R04_T-34','regular')

    def test_crew_override_does_not_select_different_modules(self):
        with patch.dict(sys.modules, self._items()):
            native = self._native('ussr:R04_T-34','regular')
            descriptor = fitting.build(native, 'ussr:R04_T-34','regular',90)
            self.assertEqual(fitting.context(descriptor)['crew'][0][0],90)
            self.assertEqual(fitting.context(descriptor)['wire']['tier'],'regular')

    def test_native_crew_and_directive_reach_factors_once(self):
        from gui.mods.offline_lan_0922 import loadout
        descriptor = NS(type=NS(name='ussr:R04_T-34',crewRoles=(('commander',),)))
        directive = NS(updateVehicleAttrFactors=lambda *args: None)
        crew = (b'native trained crew',)
        fitting.register(descriptor, dict(crew=crew,directives=(directive,)))
        utils = NS(generateDefaultCrew=lambda *args: self.fail('Bot crew silently replaced'))
        modules = (utils,NS(MAX_SKILL_LEVEL=100),None,NS(DEFAULT=0,WHEN_STILL=1),None,None,None)
        with patch.object(loadout,'_client_modules',return_value=modules), \
                patch.object(loadout,'_native_attribute_factors',return_value={}) as native:
            self.assertIsNotNone(loadout.attribute_factors(descriptor))
            self.assertEqual(native.call_args.args[2],crew)
            self.assertEqual(native.call_args.args[3],[directive])
        with patch.object(loadout,'_client_modules',return_value=modules), \
                patch.object(loadout,'_native_attribute_factors',side_effect=ValueError('wrong tankman nation')) as native:
            self.assertIsNone(loadout.attribute_factors(descriptor))
            self.assertEqual(native.call_count,1)

    def test_production_cache_separates_same_vehicle_tiers(self):
        from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
        battle = BattleRuntime.__new__(BattleRuntime)
        battle._descriptor_cache = {}
        battle._arena_outfit_season = lambda: 1
        battle._runtime = NS(vehicles=None)
        battle._remote_factory = NS(prepare_descriptor=lambda descriptor:descriptor)
        original = fitting.build
        def native_builder(unused,vehicle,tier,level,restored,overrides=None):
            return original(self._native(vehicle,tier),vehicle,tier,level,restored)
        with patch.dict(sys.modules,self._items()), patch.object(fitting,'build',side_effect=native_builder) as build:
            regular = battle._resolve_bot_fitted_descriptor('ussr:R04_T-34','regular')
            elite = battle._resolve_bot_fitted_descriptor('ussr:R04_T-34','elite')
            self.assertIsNot(regular,elite)
            self.assertIs(battle._resolve_bot_fitted_descriptor('ussr:R04_T-34','regular'),regular)
            self.assertEqual(build.call_count,2)
            self.assertEqual(fitting.context(regular)['wire']['tier'],'regular')
            self.assertEqual(fitting.context(elite)['wire']['tier'],'elite')
            invalid = dict(fitting.context(regular)['wire'],descriptor=base64.b64encode(b'other').decode())
            with self.assertRaisesRegex(ValueError,'cached'):
                battle._resolve_bot_fitted_descriptor('ussr:R04_T-34','regular',restored=invalid)

    def test_native_conditional_skills_and_ammo_health_share_one_fitting(self):
        from gui.mods.offline_lan_0922 import loadout, bot_runtime, device_damage
        descriptor = NS(type=NS(name='ussr:R04_T-34'),miscAttrs={'ammoBayHealthFactor':1.0},
                        hull={'ammoBayHealth':{'maxHealth':180,'maxRegenHealth':120}})
        fitting.register(descriptor, dict(wire={'crew_level':100},crew_roster=('commander','loader1')))
        def factors(unused,activity_flags,is_fire,crew_level):
            return {'gun/reloadTime':1.0 if activity_flags[1] else 1.4,
                    'shotDispersion':(1.0,), 'offline/ammoBayHealth':1.2,
                    'offline/adrenaline_health_fraction':0.1 if activity_flags[1] else 0.0,
                    'offline/adrenaline_reload_factor':0.9,
                    'offline/engine_fire_factor':0.75}
        with patch.object(loadout,'attribute_factors',side_effect=factors) as native:
            state = dict(health=5,max_health=100,critical={})
            self.assertAlmostEqual(bot_runtime._critical_factor(state,descriptor,'reload'),0.9)
            self.assertEqual(device_damage.device_max_hp(descriptor,'ammoBayHealth'),216)
            self.assertEqual(native.call_count,1)
            state['critical']={'crew_ko':['loader1']}
            self.assertAlmostEqual(bot_runtime._critical_factor(state,descriptor,'reload'),1.4)
            self.assertEqual(native.call_count,2)
            self.assertEqual(device_damage.device_max_hp(descriptor,'ammoBayHealth'),216)
            state['critical']={}
            self.assertAlmostEqual(bot_runtime._critical_factor(state,descriptor,'reload'),0.9)
            self.assertEqual(native.call_count,2)
            self.assertEqual(fitting.battle_factors(descriptor)['engine_fire_factor'],0.75)


if __name__ == '__main__':
    unittest.main()
