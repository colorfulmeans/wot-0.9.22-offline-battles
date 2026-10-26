"""Preview all selected scopes without sampling or altering the draft."""
import copy
import unittest
import bot_tactics_preview as preview
import bot_tactics_store as storage
from gui.mods.offline_lan_0922 import bot_gunnery

class PreviewTests(unittest.TestCase):
    def test_all_scopes_are_covered_and_slot_exceptions_stay_visible(self):
        document=storage.contract.empty()
        document['behavior']=[dict(team=0,class_tag='all',slot=-1,values=dict(skill='regular')),
                              dict(team=2,class_tag='heavyTank',slot=7,values=dict(crew_preset='all',reaction_seconds=0))]
        before=copy.deepcopy(document)
        groups=preview.grouped(document)
        scopes=[s for g in groups for s in g['scopes']]
        self.assertEqual(150,len(scopes));self.assertEqual(150,len(set(scopes)))
        self.assertEqual(2,len(groups));self.assertEqual(document,before)
        special=next(g for g in groups if g['values'].get('crew_preset')=='all')
        self.assertEqual([(2,'heavyTank',7)],special['scopes'])
        text=str(preview.rows(special,'zh'))
        self.assertIn('100% 全部满技能',text);self.assertNotIn('75%',text)
        self.assertEqual(13,len(preview.rows(special,'zh')))
        self.assertIn('槽位 8',text)

    def test_inherited_room_difficulty_is_never_fabricated_as_regular(self):
        group=preview.grouped(storage.contract.empty(),2,'SPG','2,4')[0]
        self.assertEqual([(2,'SPG',1),(2,'SPG',3)],group['scopes'])
        text=str(preview.rows(group,'en'))
        self.assertIn('sampled separately',text);self.assertNotIn('Regular',text)
        self.assertNotIn('75%',text)

    def test_manual_fields_and_zero_ratios_remain_independent(self):
        document=storage.contract.empty();values=dict(skill='regular',development='intermediate',equipment='improved',crew_preset='all',ammo_ratios=[0,0,0])
        document['behavior']=[dict(team=1,class_tag='heavyTank',slot=-1,values=values)]
        group=preview.grouped(document,1,'heavyTank','')[0]
        self.assertEqual(values,storage.contract.effective(document,1,'heavyTank',0))
        rows=preview.rows(group,'zh')
        self.assertEqual('0 : 0 : 0（不携带炮弹）',rows[3][1])
        self.assertIn('3 紫色',rows[2][1]);self.assertIn('全部满技能',rows[7][1])
        self.assertEqual('%g'%bot_gunnery.skill_parameters('regular')['reaction_seconds'],rows[8][1])

    def test_zero_and_one_limits_have_their_own_saved_source_in_both_languages(self):
        for limit in (0,1):
            document=storage.contract.empty()
            document['behavior']=[dict(team=0,class_tag='all',slot=-1,values=dict(ammo_limit=limit))]
            group=preview.grouped(document,1,'SPG','')[0]
            for language in ('zh','en'):
                row=next(row for row in preview.rows(group,language)
                         if row[0]==preview.labels.parameter_label('ammo_limit',language))
                self.assertEqual(str(limit),row[1])
                self.assertNotIn('Difficulty default',row[2])
