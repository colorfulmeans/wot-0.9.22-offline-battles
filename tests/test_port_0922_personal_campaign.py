"""Reward delivery, reset/replay and operation claims share one ledger."""
import copy
import json
import types
import unittest
from unittest import mock

import test_port_0922_economy as fixture
from gui.mods.offline_lan_0922 import personal_campaign as campaign


def node(text='', **fields):
    return {'value': str(text), 'children': list(fields.items())}


def token(name, count=1, **kwargs):
    return node(id=node(name), count=node(count), **kwargs)


def quest(bonus):
    return node(bonus=bonus)


class RewardsTests(unittest.TestCase):
    def test_main_honors_and_restart_pay_only_missing_stages(self):
        state = fixture._state()
        state.snapshot()['personalMissionProgress'] = {'1': 1}
        definition = {1: {'main': quest(node(credits=node(100))),
                          'add': quest(node(freeXP=node(20)))}}
        campaign.settle(state, now=100, definitions=definition)
        self.assertEqual(100100, state.snapshot()['wallet']['credits'])
        restarted = fixture._state(state.snapshot())
        campaign.settle(restarted, now=101, definitions=definition)
        self.assertEqual(100100, restarted.snapshot()['wallet']['credits'])
        restarted.snapshot()['personalMissionProgress']['1'] = 2
        campaign.settle(restarted, now=102, definitions=definition)
        self.assertEqual(100100, restarted.snapshot()['wallet']['credits'])
        self.assertEqual(520, restarted.snapshot()['wallet']['freeXP'])
        self.assertEqual({'1': 2}, restarted.snapshot()['personalMissionRewarded'])

    def test_reset_reclaims_only_earned_orders_and_replay_preserves_cash_receipt(self):
        state = fixture._state()
        definition = {15: {'main': quest(node(credits=node(100))),
            'add': quest(node(token=token('free_award_list'), credits=node(500)))}}
        state.snapshot()['personalMissionProgress'] = {'15': 2}
        campaign.settle(state, now=100, definitions=definition)
        self.assertEqual(100600, state.snapshot()['wallet']['credits'])
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])
        state.snapshot()['personalMissionRequestedCompleted'] = {}
        campaign.settle(state, now=101, definitions=definition)
        self.assertEqual({}, state.snapshot()['personalMissionProgress'])
        self.assertEqual({'15': 2}, state.snapshot()['personalMissionRewarded'])
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])
        state.snapshot()['personalMissionRequestedCompleted'] = {'15': 2}
        campaign.settle(state, now=102, definitions=definition)
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])
        self.assertEqual(100600, state.snapshot()['wallet']['credits'])
        campaign.settle(state, now=103, definitions=definition)
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])

    def test_spent_order_rejects_whole_reset_and_consumes_failed_request(self):
        state = fixture._state()
        state.snapshot().update(personalMissionProgress={'15': 2, '1': 1},
            personalMissionRewarded={'15': 2}, personalMissionOrders=0,
            personalMissionPawned={'1': 1},
            personalMissionRewardJournal={'orders:15': {'count': 1}},
            personalMissionRequestedCompleted={'1': 1})
        definition = {1: {'main': quest(node()), 'main_award_list': quest(node()),
                          'add': quest(node())},
                      15: {'main': quest(node()), 'add': quest(node(token=token('free_award_list')))}}
        result = campaign.settle(state, now=100, definitions=definition)
        self.assertEqual({'15': 2, '1': 1}, state.snapshot()['personalMissionProgress'])
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])
        self.assertEqual('PERSONAL_MISSION_RESET_ORDERS_SPENT', result['reset_error'])
        self.assertNotIn('personalMissionRequestedCompleted', state.snapshot())

    def test_reset_returns_cancelled_pawns_before_reclaiming_earned_orders(self):
        state = fixture._state()
        state.snapshot().update(personalMissionProgress={'15': 2, '30': 1},
            personalMissionRewarded={'15': 2, '30': 1}, personalMissionOrders=0,
            personalMissionPawned={'30': 4},
            personalMissionRewardJournal={'orders:15': {'count': 1}},
            personalMissionRequestedCompleted={})
        definition = {15: {'main': quest(node()), 'add': quest(node(token=token('free_award_list')))}}
        result = campaign.settle(state, now=100, definitions=definition)
        self.assertEqual('', result['reset_error'])
        self.assertEqual({}, state.snapshot()['personalMissionProgress'])
        # The old four-order pledge exceeded the one earned order. Returning
        # it and withdrawing that one reward leaves no phantom free orders.
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])

    def test_crew_provenance_survives_duplicate_descriptors_and_new_inventory_ids(self):
        from gui.mods.offline_lan_0922.account_rpc import garage_store
        snapshot = fixture._snapshot()
        snapshot.update(personalMissionProgress={'15': 1}, personalMissionRewarded={'15': 1},
            barracksTankmen={701: b'female', 702: b'female'}, personalMissionTankwomen={'15': True},
            personalMissionDossier={'achievements:tankwomenProgress': 1},
            personalMissionRewardJournal={'crew:15': {'tankman': 702, 'descriptor': 'ZmVtYWxl',
                                                       'dossier_count': 1}, 'crewBonus:15': True})
        serialized = json.loads(json.dumps(garage_store._ledger_payload(snapshot)))
        self.assertNotIn('tankman', serialized['personalMissions']['rewardJournal']['crew:15'])
        restored = fixture._snapshot()
        restored['vehicles'][0].update(crew=[501, 502], tankmen={501: b'one', 502: b'two'})
        garage_store._apply_ledger(restored, {'ledger': serialized})
        self.assertEqual(504, restored['personalMissionRewardJournal']['crew:15']['tankman'])
        state = fixture._state(restored)
        state.snapshot()['personalMissionRequestedCompleted'] = {}
        result = campaign.settle(state, now=100, definitions={})
        self.assertEqual('', result['reset_error'])
        self.assertEqual({503: b'female'}, state.snapshot()['barracksTankmen'])
        self.assertEqual(30, state.snapshot()['accountBerths'])
        self.assertEqual({'15': 1}, state.snapshot()['personalMissionRewarded'])
        self.assertTrue(state.snapshot()['personalMissionRewardJournal']['crewBonus:15'])

    def test_crew_provenance_follows_trained_assigned_crew_across_restore(self):
        from gui.mods.offline_lan_0922.account_rpc import garage_store
        snapshot = fixture._snapshot()
        snapshot['vehicles'][0]['tankmen'][102] = b'female-trained'
        snapshot.update(personalMissionProgress={'15': 1}, personalMissionRewarded={'15': 1},
            personalMissionTankwomen={'15': True},
            personalMissionDossier={'achievements:tankwomenProgress': 1},
            personalMissionRewardJournal={'crew:15': {'tankman': 102,
                'descriptor': 'original-descriptor', 'dossier_count': 1}, 'crewBonus:15': True})
        serialized = json.loads(json.dumps(garage_store._ledger_payload(snapshot)))
        restored = fixture._snapshot()
        restored['vehicles'][0].update(crew=[801, 802], tankmen={801: b'one', 802: b'female-trained'})
        garage_store._apply_ledger(restored, {'ledger': serialized})
        state = fixture._state(restored)
        state.snapshot()['personalMissionRequestedCompleted'] = {}
        result = campaign.settle(state, now=100, definitions={})
        self.assertEqual('', result['reset_error'])
        self.assertEqual([801, None], state.snapshot()['vehicles'][0]['crew'])
        self.assertEqual({801: b'one'}, state.snapshot()['vehicles'][0]['tankmen'])


    def test_order_honors_refunds_pawn_and_discards_manually_supplied_balance(self):
        state = fixture._state()
        state.snapshot().update(personalMissionProgress={'270': 2},
            personalMissionRewarded={'270': 1}, personalMissionPawned={'270': 4},
            personalMissionOrders=21)
        definition = {270: {'main': quest(node()), 'add': quest(node(
            token=token('free_award_list'), credits=node(500000)))}}
        campaign.settle(state, now=100, definitions=definition)
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])
        self.assertEqual({}, state.snapshot()['personalMissionPawned'])
        campaign.settle(state, now=101, definitions=definition)
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])

    def test_all_final_honors_repeated_resets_and_full_cascade_never_inflate_orders(self):
        state = fixture._state()
        definitions = dict((qid, {'main': quest(node(credits=node(100))),
            'add': quest(node(token=token('free_award_list'), credits=node(200)))})
            for qid in range(15, 301, 15))
        all_honors = dict((str(qid), 2) for qid in definitions)
        state.snapshot().update(personalMissionProgress=all_honors.copy(),
                                personalMissionOrders=21)
        campaign.settle(state, now=100, definitions=definitions)
        self.assertEqual(20, state.snapshot()['personalMissionOrders'])
        paid_credits = state.snapshot()['wallet']['credits']
        for unused in range(3):
            for key in sorted(all_honors, key=int):
                requested = all_honors.copy()
                requested[key] = 1
                state.snapshot()['personalMissionRequestedCompleted'] = requested
                campaign.settle(state, now=101, definitions=definitions)
                self.assertEqual(19, state.snapshot()['personalMissionOrders'])
                state.snapshot()['personalMissionRequestedCompleted'] = all_honors.copy()
                campaign.settle(state, now=102, definitions=definitions)
                self.assertEqual(20, state.snapshot()['personalMissionOrders'])
        state.snapshot()['personalMissionRequestedCompleted'] = {}
        campaign.settle(state, now=103, definitions=definitions)
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])
        self.assertEqual({}, state.snapshot()['personalMissionProgress'])
        state.snapshot()['personalMissionRequestedCompleted'] = all_honors.copy()
        campaign.settle(state, now=104, definitions=definitions)
        self.assertEqual(20, state.snapshot()['personalMissionOrders'])
        self.assertEqual(paid_credits, state.snapshot()['wallet']['credits'])

    def test_old_empty_save_cannot_retain_manual_orders(self):
        state = fixture._state()
        state.snapshot()['personalMissionOrders'] = 21
        result = campaign.settle(state, now=100, definitions={})
        self.assertFalse(result['pending'])
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])

    def test_legacy_paid_honors_rebuild_unique_sources_from_resource_counts(self):
        state = fixture._state()
        definitions = {15: {'main': quest(node()),
            'add': quest(node(token=token('free_award_list', 3)))}}
        state.snapshot().update(personalMissionProgress={'15': 2},
            personalMissionRewarded={'15': 2}, personalMissionOrders=21,
            personalMissionRewardJournal={'orders:15': {'count': 100},
                'orders:1': {'count': 50}, 'orders:30': {'count': 50}})
        campaign.settle(state, now=100, definitions=definitions)
        self.assertEqual(3, state.snapshot()['personalMissionOrders'])
        self.assertEqual({'orders:15': {'count': 3}},
                         state.snapshot()['personalMissionRewardJournal'])
        state.snapshot()['personalMissionRewardJournal'] = {}
        campaign.settle(state, now=101, definitions=definitions)
        self.assertEqual(3, state.snapshot()['personalMissionOrders'])
        self.assertEqual(100000, state.snapshot()['wallet']['credits'])

    def test_legacy_excess_pledges_absorb_earnings_until_cleared(self):
        state = fixture._state()
        definitions = dict((qid, {'main': quest(node()),
            'main_award_list': quest(node()),
            'add': quest(node(token=token('free_award_list')))})
            for qid in (15, 30, 45, 60, 75))
        progress = {'15': 1, '30': 2}
        state.snapshot().update(personalMissionProgress=progress.copy(),
            personalMissionRewarded=progress.copy(), personalMissionOrders=21,
            personalMissionPawned={'15': 4})
        campaign.settle(state, now=100, definitions=definitions)
        self.assertEqual(0, state.snapshot()['personalMissionOrders'])
        self.assertEqual({'15': 4}, state.snapshot()['personalMissionPawned'])
        for qid in (45, 60, 75):
            state.snapshot()['personalMissionProgress'][str(qid)] = 2
            campaign.settle(state, now=101, definitions=definitions)
            self.assertEqual(0, state.snapshot()['personalMissionOrders'])
        state.snapshot()['personalMissionProgress']['15'] = 2
        campaign.settle(state, now=102, definitions=definitions)
        self.assertEqual(5, state.snapshot()['personalMissionOrders'])
        self.assertEqual({}, state.snapshot()['personalMissionPawned'])
        campaign.settle(state, now=103, definitions=definitions)
        self.assertEqual(5, state.snapshot()['personalMissionOrders'])

    def test_paid_honors_migration_also_releases_old_pledges_once(self):
        state = fixture._state()
        definitions = {15: {'main': quest(node()),
            'add': quest(node(token=token('free_award_list')))}}
        state.snapshot().update(personalMissionProgress={'15': 2},
            personalMissionRewarded={'15': 2}, personalMissionOrders=21,
            personalMissionPawned={'15': 4})
        campaign.settle(state, now=100, definitions=definitions)
        self.assertEqual({}, state.snapshot()['personalMissionPawned'])
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])
        campaign.settle(state, now=101, definitions=definitions)
        self.assertEqual(1, state.snapshot()['personalMissionOrders'])

    def test_reward_failure_rolls_back_whole_stage_and_remains_pending(self):
        state = fixture._state()
        state.snapshot()['personalMissionProgress'] = {'1': 1}
        definition = {1: {'main': quest(node(credits=node(100), item=node(99999))),
                          'add': quest(node())}}
        result = campaign.settle(state, now=100, definitions=definition)
        self.assertEqual(100000, state.snapshot()['wallet']['credits'])
        self.assertEqual({}, state.snapshot().get('personalMissionRewarded', {}))
        self.assertEqual(1, result['pending'][0][0])

    def test_reset_rebuilds_progress_tokens_without_revoking_claimed_operation(self):
        state = fixture._state()
        state.snapshot().update(personalMissionProgress={'1': 1},
            personalMissionRewarded={'1': 1},
            personalMissionTokens={'parts': [campaign.TOKEN_EXPIRY, 4]},
            personalMissionTokenRewards=['operation'])
        definition = {1: {'main': quest(node(token=token('parts'))), 'add': quest(node())}}
        operation = node(id=node('operation'), enabled=node('true'),
            conditions=node(preBattle=node(account=node(token=node(
                id=node('parts'), greaterOrEqual=node(5), consume=node(5))))),
            bonus=node(token=token('complete')))
        tiles = node(quests={'children': [('tokenQuest', operation)]})
        with mock.patch.object(campaign, '_resource', return_value=tiles):
            result = campaign.settle(state, now=100, definitions=definition)
        self.assertEqual([], result['pending'])
        tokens = state.snapshot()['personalMissionTokens']
        self.assertEqual(0, tokens['parts'][1])
        self.assertEqual(1, tokens['complete'][1])
        self.assertEqual(['operation'], state.snapshot()['personalMissionTokenRewards'])

    def test_operation_reward_and_badge_delivered_once(self):
        state = fixture._state()
        state.snapshot().update(personalMissionProgress={'1': 1})
        definition = {1: {'main': quest(node(token=token('parts', count=5))), 'add': quest(node())}}
        operation = node(id=node('operation'), enabled=node('true'),
            conditions=node(preBattle=node(account=node(token=node(
                id=node('parts'), greaterOrEqual=node(5), consume=node(5))))),
            bonus=node(slots=node(1), vehicle=node('ussr:reward'),
                       dossier=node(name=node('playerBadges:10'), value=node('timestamp'), type=node('set'))))
        tiles = node(quests={'children': [('tokenQuest', operation)]})
        with mock.patch.object(campaign, '_resource', return_value=tiles), mock.patch.object(campaign, '_grant_vehicle') as grant:
            first = campaign.settle(state, now=100, definitions=definition)
            second = campaign.settle(state, now=101, definitions=definition)
        grant.assert_called_once_with(state, 'ussr:reward')
        self.assertEqual(['operation'], first['operation_rewards'])
        self.assertEqual([], second['operation_rewards'])
        self.assertEqual(31, state.snapshot()['accountSlots'])
        self.assertEqual({'10': 100}, state.snapshot()['accountBadges'])

    def test_reward_state_and_bound_camouflage_survive_json_roundtrip(self):
        from gui.mods.offline_lan_0922.account_rpc import garage_store
        snapshot = fixture._snapshot()
        snapshot.update(personalMissionProgress={'15': 2},
            personalMissionRewarded={'15': 2}, personalMissionTankwomen={'15': True},
            personalMissionOrders=1, personalMissionPawned={},
            personalMissionTokens={'operation_complete': [campaign.TOKEN_EXPIRY, 1]},
            personalMissionTokenRewards=['operation'],
            personalMissionDossier={'achievements:tankwomenProgress': 1},
            customizationItems={2: {15144: {50001: 2}}})
        serialized = json.loads(json.dumps(garage_store._ledger_payload(snapshot)))
        restored = fixture._snapshot()
        garage_store._apply_ledger(restored, {'ledger': serialized})
        for name in ('personalMissionRewarded', 'personalMissionTankwomen',
                     'personalMissionTokens', 'personalMissionTokenRewards',
                     'personalMissionDossier', 'customizationItems'):
            self.assertEqual(snapshot[name], restored[name], name)


    def test_existing_reward_vehicle_pays_only_bare_credit_refund(self):
        state = fixture._state()
        record = state.snapshot()['vehicles'][0]
        record['vehicleTypeName'] = 'ussr:reward'
        with mock.patch.object(state, '_item_refund', return_value={'credits': 200000}) as refund:
            campaign._grant_vehicle(state, 'ussr:reward')
        refund.assert_called_once_with(record['vehicleTypeCompactDescr'])
        self.assertEqual(300000, state.snapshot()['wallet']['credits'])
        self.assertEqual(1, len(state.snapshot()['vehicles']))


    def test_delayed_female_preserves_native_free_skill_and_selected_specialization(self):
        state = fixture._state()
        state.snapshot()['personalMissionProgress'] = {'15': 1}
        tman = node(isPremium=node('true'), isFemale=node('true'), role=node('commander'),
            roleLevel=node(100), freeXP=node(210063), fnGroupID=node(1), lnGroupID=node(1),
            iGroupID=node(1), nationID=node(0), vehicleTypeID=node(0), freeSkills=node('brotherhood'))
        definition = {'main': node(bonusDelayed=node(berths=node(1),
            dossier=node(name=node('achievements:tankwomenProgress'), value=node(1), type=node('add')),
            tankmen=node(tman=tman)))}
        state._vehicles = types.SimpleNamespace(makeIntCompactDescrByID=lambda *args: 123,
            getVehicleType=lambda value: types.SimpleNamespace(crewRoles=(('gunner',),)))
        make = mock.Mock(return_value=b'female-free-skill')
        state._tankmen = types.SimpleNamespace(SKILL_NAMES=('gunner',), ROLES=('gunner',),
                                               makeTmanDescrByTmanData=make)
        received = campaign.claim_tankwoman(state, 15, 2, 3, 0, definition=definition, now=100)
        self.assertEqual(b'female-free-skill', state.snapshot()['barracksTankmen'][received])
        self.assertEqual(['brotherhood'], make.call_args[0][0]['freeSkills'])
        self.assertEqual((2, 3, 'gunner'), tuple(make.call_args[0][0][key]
                         for key in ('nationID', 'vehicleTypeID', 'role')))
        self.assertEqual({'15': True}, state.snapshot()['personalMissionTankwomen'])
        self.assertEqual(31, state.snapshot()['accountBerths'])
        with self.assertRaises(campaign.GarageError):
            campaign.claim_tankwoman(state, 15, 2, 3, 0, definition=definition)
        state.snapshot()['personalMissionRequestedCompleted'] = {}
        campaign.settle(state, now=101, definitions={})
        self.assertEqual({}, state.snapshot()['barracksTankmen'])
        state.snapshot()['personalMissionProgress'] = {'15': 1}
        campaign.claim_tankwoman(state, 15, 2, 3, 0, definition=definition, now=102)
        self.assertEqual(31, state.snapshot()['accountBerths'])
        self.assertEqual(1, state.snapshot()['personalMissionDossier']['achievements:tankwomenProgress'])


if __name__ == '__main__':
    unittest.main()
