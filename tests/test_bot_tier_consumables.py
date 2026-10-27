"""Tier consumables, exact priorities and filtered elite repair effects."""
import sys
import types
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src/res/scripts/client'),
               str(Path(__file__).resolve().parents[1]/'server')]
from gui.mods.offline_lan_0922 import equipment_mechanics as em


def cache():
    descriptors = {}
    for i, name in enumerate(('handExtinguishers','autoExtinguishers','smallMedkit',
                               'largeMedkit','smallRepairkit','largeRepairkit')):
        descriptors[i] = types.SimpleNamespace(name=name,id=(0,i),compactDescr=100+i,
            tags=('medkit',) if 'Medkit' in name else ('repairkit',) if 'Repairkit' in name else (),
            cooldownSeconds=90,reuseCount=-1,autoactivate=name=='autoExtinguishers',
            repairAll=name in ('largeMedkit','largeRepairkit'),
            fireStartingChanceFactor=.9 if name=='autoExtinguishers' else 1.)
    return types.SimpleNamespace(equipmentIDs=lambda: {d.name:i for i,d in descriptors.items()},
                                 equipments=lambda: descriptors)


def critical(*pairs, **extra):
    result=dict(devices=[dict(name=n,state=s,hp=0. if s=='destroyed' else 20.,max_hp=100.)
                         for n,s in pairs],destroyed=[n for n,s in pairs if s=='destroyed'],
                crew_ko=[],fire=False)
    result.update(extra)
    return result


def equipment(skill, kind):
    return em.EquipmentState(next(c for c in em.default_bot_consumables(cache(),skill)
                                  if c['kind']==kind))


class TierConsumableTests(unittest.TestCase):
    def test_all_four_native_loadouts_and_per_item_uses(self):
        for skill in em.BOT_SKILLS:
            items=em.default_bot_consumables(cache(),skill)
            self.assertEqual(0 if skill=='rookie' else 3,len(items))
            self.assertEqual(tuple(items),em.bot_consumable_contracts(dict(botConsumables=items)))
            for c in items:
                self.assertEqual(90.,c['cooldownSeconds'])
                self.assertEqual(1 if skill=='regular' else -1,em.EquipmentState(c).uses_left)
                self.assertEqual(skill=='elite',c['autoactivate'] if c['kind']=='extinguisher' else c['repairAll'])
        self.assertEqual(-1,cache().equipments()[2].reuseCount)

    def test_malformed_or_mixed_loadouts_are_rejected(self):
        items=em.default_bot_consumables(cache(),'regular')
        items[1]=em.default_bot_consumables(cache(),'elite')[1]
        with self.assertRaisesRegex(ValueError,'order'):
            em.bot_consumable_contracts(dict(botConsumables=items))

    def test_every_adjacent_repair_priority_and_severity(self):
        for skill in ('regular','veteran'):
            expected=[pair for pair in em.BOT_REPAIR_PRIORITY
                      if skill!='regular' or 'Track' not in pair[0]]
            for higher,lower in zip(expected,expected[1:]):
                # A single device cannot be both red and yellow at once.
                if higher[0]==lower[0]:continue
                self.assertEqual(higher[0],em.bot_repair_selection(critical(lower,higher),skill))
        self.assertEqual('gunHealth',em.bot_repair_selection(critical(
            ('ammoBayHealth','critical'),('gunHealth','destroyed')),'veteran'))

    def test_no_red_fuel_or_yellow_track_trigger(self):
        payload=critical(('fuelTankHealth','destroyed'),('leftTrackHealth','critical'))
        for skill in ('regular','veteran','elite'):
            item=equipment(skill,'repairkit')
            self.assertIsNone(item.poll_bot(0.,payload,skill=skill))
            self.assertIsNone(item.poll_bot(10.,payload,skill=skill))
        self.assertIsNone(em.bot_repair_selection(critical(('leftTrackHealth','destroyed')),'regular'))
        self.assertEqual('leftTrackHealth',em.bot_repair_selection(critical(('leftTrackHealth','destroyed')),'veteran'))

    def test_regular_each_consumable_only_once(self):
        for kind,payload,stun in [('repairkit',critical(('gunHealth','destroyed')),False),
                ('medkit',critical(crew_ko=['loader1']),False),
                ('extinguisher',critical(fire=True),False)]:
            item=equipment('regular',kind)
            self.assertIsNone(item.poll_bot(0.,payload,stun,skill='regular'))
            self.assertIsNotNone(item.poll_bot(5.,payload,stun,skill='regular'))
            self.assertEqual(0,item.uses_left)
            self.assertIsNone(item.poll_bot(1000.,payload,stun,skill='regular'))

    def test_veteran_and_elite_repeat_only_after_native_cooldown_and_observation(self):
        for skill in ('veteran','elite'):
            item=equipment(skill,'repairkit');payload=critical(('gunHealth','destroyed'))
            self.assertIsNone(item.poll_bot(0.,payload,skill=skill))
            self.assertIsNotNone(item.poll_bot(.01,payload,skill=skill))
            self.assertIsNone(item.poll_bot(90.,payload,skill=skill))
            self.assertIsNone(item.poll_bot(90.01,payload,skill=skill))
            self.assertIsNotNone(item.poll_bot(90.02,payload,skill=skill))
            self.assertEqual(-1,item.uses_left)

    def test_manual_extinguisher_is_five_seconds_after_automatic(self):
        payload=critical(fire=True)
        self.assertIsNotNone(equipment('elite','extinguisher').poll_bot(12.,payload,skill='elite'))
        for skill in ('regular','veteran'):
            item=equipment(skill,'extinguisher')
            self.assertIsNone(item.poll_bot(12.,payload,skill=skill))
            self.assertIsNone(item.poll_bot(16.999,payload,skill=skill))
            self.assertEqual('extinguish_fire',item.poll_bot(17.,payload,skill=skill)['action'])

    def test_fire_ending_cancels_timer_without_consuming_then_new_fire_restarts(self):
        item=equipment('regular','extinguisher')
        item.poll_bot(0.,critical(fire=True),skill='regular')
        self.assertIsNone(item.poll_bot(4.,critical(),skill='regular'))
        self.assertEqual(1,item.uses_left)
        self.assertIsNone(item.poll_bot(10.,critical(fire=True),skill='regular'))
        self.assertIsNone(item.poll_bot(14.99,critical(fire=True),skill='regular'))
        self.assertIsNotNone(item.poll_bot(15.,critical(fire=True),skill='regular'))

    def test_pending_fire_delay_and_cooldown_survive_snapshot_handoff(self):
        item=equipment('veteran','extinguisher');payload=critical(fire=True)
        item.poll_bot(10.,payload,skill='veteran')
        snap=item.snapshot(12.)
        restored=em.EquipmentState(item.contract);restored.restore(snap,100.)
        self.assertIsNone(restored.poll_bot(102.999,payload,skill='veteran'))
        self.assertIsNotNone(restored.poll_bot(103.,payload,skill='veteran'))
        self.assertFalse(restored.ready(192.999));self.assertTrue(restored.ready(193.))

    def test_crew_priority_numbers_precede_stun(self):
        order=list(em.BOT_CREW_PRIORITY)
        for i,name in enumerate(order):
            self.assertEqual(name,em.bot_crew_selection(critical(crew_ko=list(reversed(order[i:])))))
        item=equipment('veteran','medkit');payload=critical(crew_ko=['driver','gunner2','loader2'])
        item.poll_bot(0.,payload,True,skill='veteran')
        effect=item.poll_bot(.01,payload,True,skill='veteran')
        self.assertEqual('loader2',effect['selected']);self.assertTrue(effect['clearStun'])

    def test_regular_ignores_pure_stun_but_crew_heal_keeps_native_stun_clear(self):
        item=equipment('regular','medkit')
        self.assertIsNone(item.poll_bot(0.,critical(),True,skill='regular'))
        self.assertIsNone(item.poll_bot(10.,critical(),True,skill='regular'))
        payload=critical(crew_ko=['gunner1'])
        item.poll_bot(11.,payload,True,skill='regular')
        effect=item.poll_bot(11.01,payload,True,skill='regular')
        self.assertEqual('gunner1',effect['selected']);self.assertTrue(effect['clearStun'])
        for skill in ('veteran','elite'):
            item=equipment(skill,'medkit');item.poll_bot(0.,critical(),True,skill=skill)
            self.assertTrue(item.poll_bot(.01,critical(),True,skill=skill)['clearStun'])

    def test_elite_repair_really_leaves_red_fuel_and_yellow_track_untouched(self):
        from test_port_0922_bot_runtime import _critical_descriptor
        from test_port_0922_bot_ammo import _load_bot_runtime
        runtime=_load_bot_runtime().BotRuntime(1)
        payload=critical(('gunHealth','destroyed'),('fuelTankHealth','destroyed'),
                         ('leftTrackHealth','critical'),('rightTrackHealth','destroyed'),fire=True)
        item=equipment('elite','repairkit');item.poll_bot(0.,payload,skill='elite')
        effect=item.poll_bot(.01,payload,skill='elite')
        self.assertEqual(['fuelTankHealth','leftTrackHealth'],effect['excludedDevices'])
        state=dict(id=11,health=1000,max_health=1000,critical=payload)
        self.assertTrue(runtime._apply_bot_equipment_effect(state,_critical_descriptor(),effect,strict=True))
        devices={r['name']:r for r in state['critical']['devices']}
        self.assertEqual(0.,devices['fuelTankHealth']['hp'])
        self.assertEqual(20.,devices['leftTrackHealth']['hp'])
        self.assertGreater(devices['gunHealth']['hp'],0.)
        self.assertGreater(devices['rightTrackHealth']['hp'],0.)
        self.assertTrue(state['critical']['fire'])

    def test_every_tier_survives_server_codec_and_authority_takeover(self):
        from test_port_0922_bot_runtime import ServerBotStateRevisionTests as Fixture
        import bot_state_rows
        from lan_battle_server import SIMULATION_WORKER_AUTHORITY_ID
        for skill in em.BOT_SKILLS:
            with self.subTest(skill=skill):
                contracts=em.default_bot_consumables(cache(),skill)
                items=[em.EquipmentState(c) for c in contracts]
                if items:
                    items[0].poll_bot(0.,critical(fire=True),skill=skill)
                    items[1].activate(0.,critical(crew_ko=['loader1']),selected='loader1')
                snapshots=[item.snapshot(1.) for item in items]
                server,unused_manifest,unused_socket=Fixture._server(equipment_states=snapshots)
                canonical=server.current_battle_message()['bot_manifest'][0]['equipment_states']
                restored=em.restore_equipment_states(canonical,contracts=contracts,now=20.)
                self.assertEqual([i.uses_left for i in items],[i.uses_left for i in restored])
                publication=Fixture._publication(server,2.)
                publication['bots'][0]['equipment_states']=[i.snapshot(20.) for i in restored]
                self.assertTrue(server.update_bot_states(SIMULATION_WORKER_AUTHORITY_ID,
                    bot_state_rows.publication(publication)),server.last_bot_state_reject)
                if skill in ('regular','veteran'):
                    self.assertIsNone(restored[0].poll_bot(23.999,critical(fire=True),skill=skill))
                    self.assertIsNotNone(restored[0].poll_bot(24.,critical(fire=True),skill=skill))
                if items:
                    self.assertAlmostEqual(89.,canonical[1]['cooldownTimeLeft'])
                    self.assertEqual(0 if skill=='regular' else -1,canonical[1]['usesLeft'])

    def test_rookie_has_no_kit_effect_even_with_damage(self):
        item=equipment('elite','repairkit')
        self.assertIsNone(item.poll_bot(0.,critical(('gunHealth','destroyed')),skill='rookie'))
        self.assertIsNone(item.poll_bot(10.,critical(('gunHealth','destroyed')),skill='rookie'))

if __name__=='__main__':unittest.main()
