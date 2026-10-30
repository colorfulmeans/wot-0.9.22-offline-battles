"""#1513 invoice contracts and partial-batch retry safety."""
import base64
import copy
import sys
import types
import unittest
from unittest import mock

import test_port_0922_garage as fixture


class NativeNotificationTests(unittest.TestCase):
    def setUp(self):
        self.module = fixture._load_port_module('native_notifications')
        constants = types.ModuleType('constants')
        constants.INVOICE_ASSET = types.SimpleNamespace(DATA=6)
        self.constants = mock.patch.dict(sys.modules, {'constants': constants})
        self.constants.start()
        self.addCleanup(self.constants.stop)

    def test_invoice_uses_signed_actual_deltas_and_passports(self):
        rewards = [{'kind': 'credits', 'count': 123},
                   {'kind': 'item', 'id': 42, 'count': 3},
                   {'kind': 'crew', 'count': 1,
                    'passports': [base64.b64encode(b'passport').decode('ascii')]},
                   {'kind': 'style', 'id': 128, 'count': 5}]
        original = copy.deepcopy(rewards)
        assets = self.module.reward_assets(rewards)
        self.assertEqual(123, assets['credits'])
        self.assertEqual({42: 3}, assets['items'])
        self.assertEqual([b'passport'], assets['tankmen'])
        self.assertEqual([dict(custType='style', value=5, isPermanent=True)],
                         assets['customizations'])
        self.assertEqual(dict(assetType=6, at=1234, data=assets),
                         self.module.invoice(assets, 1234))
        self.assertEqual(-123, self.module.reward_assets(rewards[:1], -1)['credits'])
        self.assertEqual(original, rewards)

    def test_missing_crew_identity_is_not_acknowledged_as_a_count_only_notice(self):
        with self.assertRaisesRegex(ValueError, 'passports'):
            self.module.reward_assets([{'kind': 'crew', 'count': 1}])

    def test_transport_retries_failed_messages_without_repeating_accepted_ones(self):
        send = mock.Mock(side_effect=[None, RuntimeError('not ready'), None])
        messenger = types.ModuleType('messenger')
        messenger.MessengerEntry = types.SimpleNamespace(g_instance=types.SimpleNamespace(
            protos=types.SimpleNamespace(BW=types.SimpleNamespace(serviceChannel=
                types.SimpleNamespace(onReceiveSysMessage=send)))))
        chat = types.ModuleType('chat_shared')
        chat.SYS_MESSAGE_TYPE = types.SimpleNamespace(
            invoiceReceived=types.SimpleNamespace(index=lambda: 4))
        chat.SYS_MESSAGE_IMPORTANCE = types.SimpleNamespace(
            normal=types.SimpleNamespace(index=lambda: 0))
        receipt = {'notification_at': 100, 'account_changes': [
            {'phase': 'granted', 'rewards': [{'kind': 'gold', 'count': 100}]},
            {'phase': 'granted', 'rewards': [{'kind': 'credits', 'count': 500}]}]}
        with mock.patch.dict(sys.modules, {'messenger': messenger, 'chat_shared': chat}):
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                self.module.publish_settlement(receipt, 'receipt-a')
            self.assertTrue(self.module.publish_settlement(receipt, 'receipt-a'))
        self.assertEqual(3, send.call_count)
        self.assertEqual(send.call_args_list[1].args[0], send.call_args_list[2].args[0])
        self.assertEqual(100, send.call_args.args[0]['data']['created_at'])

    def test_badge_and_orders_keep_the_native_nested_record_shapes(self):
        assets = self.module.reward_assets([
            {'kind': 'badge', 'id': 7, 'count': 1},
            {'kind': 'token', 'id': 'free_award_list', 'count': 2}])
        self.assertEqual({'value': 1}, assets['dossier']['account'][('badges', 7)])
        self.assertEqual({'count': 2}, assets['tokens']['free_award_list'])

    def test_failed_reset_has_a_stock_notice_without_assets(self):
        settlement = {'reset_error':
            'PERSONAL_MISSION_RESET_WALLET_UNAVAILABLE: credits required=100 available=0'}
        rows = self.module.settlement_messages(settlement)
        self.assertEqual(1, len(rows))
        self.assertEqual('adminMessage', rows[0][0])
        self.assertIn('100', rows[0][1])
        self.assertNotIn('PERSONAL_MISSION_RESET', rows[0][1])

    def test_visible_notice_cannot_be_acknowledged_when_conversion_returns_empty(self):
        ui = fixture._load_port_module('personal_campaign_ui')
        with mock.patch.object(self.module, 'publish_settlement', return_value=False):
            with self.assertRaisesRegex(ValueError, 'no native notification'):
                ui.notify({'reset_error': 'source unavailable'}, identifier='saved-row')

    def test_historical_count_only_crew_keeps_known_fact_and_other_invoice_assets(self):
        settlement = {'account_changes': [{'rewards': [
            {'kind': 'crew', 'count': 2}, {'kind': 'credits', 'count': 50}]}]}
        rows = self.module.settlement_messages(settlement)
        self.assertEqual(['adminMessage', 'invoiceReceived'], [row[0] for row in rows])
        self.assertIn('2', rows[0][1])
        self.assertEqual({'credits': 50}, rows[1][1]['data'])
