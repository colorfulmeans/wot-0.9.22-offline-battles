"""Consumer comparisons for crew work, directives and diagnostic isolation."""
import copy
import os
import types
import unittest
from unittest import mock

from gui.mods.offline_lan_0922 import bot_fittings, crew_battle, crew_injuries
from gui.mods.offline_lan_0922 import device_damage as damage
from gui.mods.offline_lan_0922 import equipment_test, critical_damage
from gui.mods.offline_lan_0922 import player_critical_mechanics, effective_params


def descriptor(roles):
    return types.SimpleNamespace(type=types.SimpleNamespace(crewRoles=roles),
        chassis={'maxHealth':200, 'maxRegenHealth':100},
        miscAttrs={})


class AcceptanceMatrixTests(unittest.TestCase):
    def tearDown(self):
        bot_fittings.clear()

    def test_crew_work_uses_physical_members_not_combined_roles(self):
        two = descriptor((('commander', 'gunner', 'radioman'), ('driver', 'loader')))
        four = descriptor((('commander',), ('driver',), ('gunner',), ('loader',)))
        six = descriptor(four.type.crewRoles + (('loader',), ('radioman',)))
        self.assertEqual((2,2), damage.repair_workforce(two))
        self.assertEqual([24.,12.,8.],
            [damage.repair_seconds('leftTrackHealth', td) for td in (two,four,six)])
        self.assertEqual(16., damage.repair_seconds('leftTrackHealth',four,crew_ko=('loader1',)))
        self.assertAlmostEqual(12*.57,damage.repair_seconds('leftTrackHealth',four,repair_factor=1.))

    def test_partial_skill_and_injury_change_actual_repaired_hp(self):
        td = descriptor((('commander',), ('driver',), ('gunner',), ('loader',)))
        # One 80% Repair carrier in four seats is a 20% average.
        factors = [.57, .57 + .43 * .2, 1.]
        values = [damage.repair_step_hp(0,'leftTrackHealth',td,1.,repair_factor=f) for f in factors]
        self.assertLess(values[0],values[1]); self.assertLess(values[1],values[2])
        self.assertLess(damage.repair_step_hp(0,'leftTrackHealth',td,1.,
            repair_factor=factors[0],crew_ko=('gunner1',)),values[0])
        self.assertEqual(0,damage.repair_step_hp(0,'leftTrackHealth',td,100.,
            crew_ko=crew_injuries.physical_roster(td.type.crewRoles)))

    def test_toolbox_and_directive_reach_shared_repair_consumer(self):
        td=descriptor((('commander',),('driver',),('gunner',),('loader',)))
        base=damage.repair_step_hp(0,'leftTrackHealth',td,1.,repair_factor=.57)
        td.miscAttrs['repairSpeedFactor']=1.25
        equipped=damage.repair_step_hp(0,'leftTrackHealth',td,1.,repair_factor=.57*1.1)
        self.assertAlmostEqual(base*1.25*1.1,equipped)

    def test_native_dynamic_repair_factor_survives_battle_projection(self):
        healthy=crew_battle.from_native({'repairSpeed':1.1})
        wounded=crew_battle.from_native({'repairSpeed':.785})
        self.assertEqual(1.1,crew_battle.canonical(healthy)['repair_speed_factor'])
        self.assertLess(wounded['repair_speed_factor'],healthy['repair_speed_factor'])

    def test_player_toolbox_descriptor_factor_survives_authority_handoff(self):
        td=descriptor((('commander',),('driver',),('gunner',),('loader',)))
        # Native toolbox changes descriptor miscAttrs, separately from the
        # crew/directive factor dictionary. Both must survive independently.
        for factor in (1.,1.25,1.4):
            td.miscAttrs['repairSpeedFactor']=factor
            profile=effective_params._canonical_critical(player_critical_mechanics.project_profile(td))
            restored=player_critical_mechanics.descriptor_from_profile(profile)
            self.assertEqual(factor,restored.miscAttrs['repairSpeedFactor'])
            self.assertAlmostEqual(12./factor,damage.repair_seconds('leftTrackHealth',restored,repair_factor=.57))

    def test_skill_directive_grants_untrained_bot_perk_only_to_eligible_carrier(self):
        td=descriptor((('commander','radioman'),('gunner',),('driver',)))
        context=dict(crew=('a','b','c'),crew_roster=('commander','gunner1','driver'),
            directives=(types.SimpleNamespace(skillName='gunner_rancorous'),))
        bot_fittings.register(td,context)
        tankmen=types.SimpleNamespace(TankmanDescr=lambda raw:types.SimpleNamespace(skills=()))
        with mock.patch.dict('sys.modules',{'items':types.SimpleNamespace(tankmen=tankmen)}):
            self.assertEqual(1,bot_fittings.skill_count(td,'gunner_rancorous'))
            self.assertEqual(0,bot_fittings.skill_count(td,'gunner_rancorous',{'crew_ko':['gunner1']}))

    def test_matrix_is_repeatable_and_cannot_leak_into_normal_play(self):
        vehicle=equipment_test.VEHICLES[1]
        ordinary=bot_fittings.plan(vehicle,'elite')
        for diagnostics,mode in [('0','4'),('1','3'),('1','4')]:
            with mock.patch.dict(os.environ,{'WOT_OFFLINE_DIAGNOSTICS':diagnostics,equipment_test.ENV:mode}):
                result=bot_fittings.plan(vehicle,'elite')
                self.assertEqual(ordinary['modules'],result['modules'])
                if diagnostics=='0': self.assertEqual(ordinary,result)
                elif mode=='3':self.assertEqual([],result['devices']);self.assertIsNone(result['directive'])
                else:self.assertEqual(['toolbox'],result['devices']);self.assertEqual('toolboxBattleBooster',result['directive'])

    def test_named_injuries_keep_double_loader_identity(self):
        roles=(('commander','radioman'),('driver',),('gunner',),('loader',),('loader',))
        facts=dict(roster=['loader2','driver','commander','loader1','gunner1'],wounded=['loader2'])
        self.assertEqual((4,),crew_injuries.injured_seats(roles,facts))
        with self.assertRaises(ValueError):crew_injuries.canonical(dict(facts,wounded=['radioman1']))


if __name__=='__main__': unittest.main()
