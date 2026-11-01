"""Current launcher/service persistence, exact deltas and first-start handoff."""
import copy
import json
import os
import tempfile
import unittest
from unittest import mock
import save_services as services
import save_ledger
import save_slots


class ServiceSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.slot = save_slots.create_slot('Services', save_slots.MODE_NEW_ACCOUNT, root=self.root)['id']
        self.kw = dict(root=self.root, is_running=lambda: False)

    def read(self, garage=False):
        path = (save_ledger.ledger_path(self.slot, root=self.root) if garage else
                save_slots.metadata_path(self.slot, root=self.root))
        with open(path, encoding='utf8') as stream:
            return json.load(stream)

    def garage(self):
        path = save_ledger.ledger_path(self.slot, root=self.root)
        save_ledger._write_state(path, {'ledger': {'wallet': dict(credits=10, gold=0, freeXP=0, crystal=0),
            'slots': 30, 'premiumExpiryTime': 0,
            'offlineServices': {'personalReserves': {'counts': {'xp': 4},
                'active': {'xp': [100, 1000]}, 'history': {'xp': [[10, 20]]}}}}})

    def test_fresh_save_premium_slots_and_reserves_reach_client_config(self):
        save_ledger.write_balances(self.slot, {}, premium_days=3, now=100, **self.kw)
        services.add_slots(self.slot, 7, **self.kw)
        services.write_reserves(self.slot, {'xp': 12, 'credits': 5}, **self.kw)
        from gui.mods.offline_lan_0922 import config
        directory = save_slots.slot_dir(self.slot, root=self.root)
        with mock.patch.object(config, 'save_slot_dir', return_value=directory):
            initial = config.save_slot_initial_services()
        self.assertEqual(100 + 3 * 86400, initial['premiumExpiryTime'])
        self.assertEqual(37, initial['accountSlots'])
        self.assertEqual(12, initial['personalReserves']['counts']['xp'])
        self.assertEqual(3, len(self.read()['initial_account_notifications']))

    def test_existing_save_edits_preserve_active_reserves_and_queue_each_delta_once(self):
        self.garage()
        services.write_reserves(self.slot, {'xp': 2, 'credits': 9}, **self.kw)
        services.add_slots(self.slot, 10, **self.kw)
        first = self.read(True)
        services.write_reserves(self.slot, {'xp': 2, 'credits': 9}, **self.kw)
        self.assertEqual(first, self.read(True))
        ledger = first['ledger']
        stock = ledger['offlineServices']['personalReserves']
        self.assertEqual({'xp': [100, 1000]}, stock['active'])
        self.assertEqual([[10, 20]], stock['history']['xp'])
        self.assertEqual(40, ledger['slots'])
        rows = ledger['personalMissions']['notifications']
        phases = [change['phase'] for row in rows for change in row['settlement']['account_changes']]
        self.assertEqual(['granted', 'revoked', 'granted'], phases)

    def test_premium_same_displayed_days_preserve_expiry_and_removal_queues_exact_seconds(self):
        self.garage()
        save_ledger.write_balances(self.slot, {}, premium_days=3, now=100, **self.kw)
        before = self.read(True)
        save_ledger.write_balances(self.slot, {}, premium_days=3, now=200, **self.kw)
        self.assertEqual(before, self.read(True))
        self.assertEqual(3, save_ledger.premium_days(self.slot, root=self.root, now=200))
        save_ledger.write_balances(self.slot, {}, premium_days=0, now=200, **self.kw)
        ledger = self.read(True)['ledger']
        self.assertEqual(0, ledger['premiumExpiryTime'])
        change = ledger['personalMissions']['notifications'][-1]['settlement']['account_changes'][0]
        self.assertEqual('revoked', change['phase'])
        self.assertEqual(3 * 86400 - 100, change['rewards'][0]['seconds'])

    def test_invalid_counts_overflow_and_running_game_leave_files_unchanged(self):
        self.garage()
        before = self.read(True)
        for value in (-1, True, 1.5, save_ledger.MAX_BALANCE + 1):
            with self.assertRaises(save_ledger.SaveLedgerError):
                services.write_reserves(self.slot, {'xp': value}, **self.kw)
        with self.assertRaises(save_ledger.SaveLedgerError):
            services.add_slots(self.slot, save_ledger.MAX_BALANCE, **self.kw)
        with self.assertRaises(save_ledger.SaveLedgerError):
            services.add_slots(self.slot, 1, root=self.root, is_running=lambda: True)
        with self.assertRaises(save_ledger.SaveLedgerError):
            save_ledger.write_balances(self.slot, {'gold': 900}, premium_days=-1, **self.kw)
        self.assertEqual(before, self.read(True))


if __name__ == '__main__':
    unittest.main()
