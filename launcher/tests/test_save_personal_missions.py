import json
import os
import tempfile
import unittest
from unittest import mock

import save_ledger
import save_personal_missions as missions
import personal_missions_ui
from test_launcher_window import _FakeTk, _FakeTtk, _Root, _StringVar
from types import SimpleNamespace


class PersonalMissionEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        self.directory = os.path.join(self.root, "career")
        os.mkdir(self.directory)
        self.path = os.path.join(self.directory, "garage_state.json")
        self.kwargs = dict(root=self.root, is_running=lambda: False)

    def read(self, filename="garage_state.json"):
        with open(os.path.join(self.directory, filename)) as stream:
            return json.load(stream)

    def test_all_operations_and_chains_cover_exactly_300_missions(self):
        ids = [qid for operation in range(4) for chain in range(5)
               for qid in missions.mission_ids(operation, chain)]
        self.assertEqual(list(range(1, 301)), ids)

    def test_new_save_uses_metadata_and_does_not_fabricate_a_garage(self):
        missions.write_progress("career", {"1": 1, "300": 2}, **self.kwargs)
        missions.write_account_fields("career", orders=7, **self.kwargs)
        self.assertFalse(os.path.exists(self.path))
        self.assertEqual({"1": 1, "300": 2},
                         self.read("save.json")[missions.INITIAL_KEY])
        self.assertEqual(7, missions.read_account_fields("career", root=self.root)["orders"])

    def test_existing_save_preserves_daily_goals_wallet_vehicles_and_other_chains(self):
        state = {"schema": 5, "vehicles": {"tank": {"shells": [1, 2]}},
                 "ledger": {"wallet": {"gold": 123},
                            "personalMissions": {"regular": [1, 16], "orders": 4},
                            "offlineServices": {"dailyMissions": {"damage": 500}}}}
        with open(self.path, "w") as stream:
            json.dump(state, stream)
        missions.write_progress("career", {"1": 2, "16": 1, "300": 2}, **self.kwargs)
        saved = self.read()
        self.assertEqual(state["vehicles"], saved["vehicles"])
        self.assertEqual(state["ledger"]["wallet"], saved["ledger"]["wallet"])
        self.assertEqual(state["ledger"]["offlineServices"], saved["ledger"]["offlineServices"])
        self.assertEqual([16], saved["ledger"]["personalMissions"]["regular"])
        self.assertEqual(4, saved["ledger"]["personalMissions"]["orders"])
        self.assertEqual({"1": 2, "16": 1, "300": 2},
                         missions.read_progress("career", root=self.root))

    def test_invalid_or_running_edits_do_not_write(self):
        for progress in ({"0": 1}, {"301": 1}, {"1": 3}, {"1": True}):
            with self.assertRaises(save_ledger.SaveLedgerError):
                missions.write_progress("career", progress, **self.kwargs)
        with self.assertRaises(save_ledger.SaveLedgerError):
            missions.write_progress("career", {"1": 1}, root=self.root, is_running=lambda: True)
        with self.assertRaises(save_ledger.SaveLedgerError):
            missions.write_account_fields("career", orders=22, **self.kwargs)
        self.assertFalse(os.path.exists(os.path.join(self.directory, "save.json")))

    def test_badge_removal_clears_equipped_badge_and_preserves_dates(self):
        state = {"schema": 5, "ledger": {"accountBadges": {"1": 100, "2": 200},
                 "offlineServices": {"selectedBadges": [1], "badgeSelectionVerified": True}}}
        with open(self.path, "w") as stream:
            json.dump(state, stream)
        with mock.patch.object(missions, "badge_catalogue", return_value=[{"id": 1}, {"id": 2}]):
            missions.write_account_fields("career", badges=[2], **self.kwargs)
            self.assertEqual({"2": 200}, self.read()["ledger"]["accountBadges"])
            self.assertEqual([], self.read()["ledger"]["offlineServices"]["selectedBadges"])
            with self.assertRaises(save_ledger.SaveLedgerError):
                missions.write_account_fields("career", badges=[999], **self.kwargs)

    def test_failed_atomic_replace_preserves_original(self):
        missions.write_progress("career", {"1": 1}, **self.kwargs)
        with mock.patch.object(save_ledger.os, "replace", side_effect=OSError("busy")):
            with self.assertRaises(save_ledger.SaveLedgerError):
                missions.write_progress("career", {"1": 2}, **self.kwargs)
        self.assertEqual({"1": 1}, missions.read_progress("career", root=self.root))

    def test_badge_catalogue_reads_resource_dictionary_ids_and_native_labels(self):
        px = missions.vehicle_overlays.packed_xml
        def text(value):
            return px.PackedValue(px.TYPE_STRING, value.encode())
        def element(children, value=None):
            return px.PackedValue(px.TYPE_ELEMENT, px.PackedElement(value, children))
        badge = element([(b'name', text('ranked_s1_gold')), (b'value', element([
            (b'item', element([(b'name', text('id')), (b'type', text('int'))], text('29'))),
            (b'item', element([(b'name', text('weight')), (b'type', text('float'))], text('5.10'))),
        ]))])
        tree = px.PackedElement(children=[(b'badges', element([(b'badge', badge)]))])
        with mock.patch.object(missions.vehicle_overlays, '_require_target',
                return_value=({'path': self.root}, 'scripts.pkg')), mock.patch.object(
                missions.vehicle_overlays, '_read_source_member', return_value=(b'', tree)):
            self.assertEqual([{'id': 29, 'label': 'ranked_s1_gold', 'weight': 5.1}],
                             missions.badge_catalogue(self.root))

    def test_ui_honors_dependency_and_switching_keep_unsaved_edits(self):
        owner = SimpleNamespace(_tk=_FakeTk, _ttk=_FakeTtk, _t=lambda text: text,
            _save_slot_id="career", game_root=_StringVar(""), save_dialog=_Root(),
            _busy=False, _maintenance_busy=False)
        with mock.patch.object(missions, "read_progress", return_value={}):
            dialog = personal_missions_ui.PersonalMissionsDialog(owner)
        label, completed, honors = dialog.rows[0]
        honors.set(True)
        dialog.changed(0, "honors")
        self.assertTrue(completed.get())
        self.assertEqual({"1": 2}, dialog.progress)
        completed.set(False)
        dialog.changed(0, "completed")
        self.assertFalse(honors.get())
        self.assertEqual({}, dialog.progress)
        dialog.set_chain(1)
        dialog.operation.set(dialog.operations[3])
        dialog.chain.set(dialog.chains[4])
        dialog.refresh()
        dialog.set_chain(2)
        self.assertEqual(1, dialog.progress["1"])
        self.assertEqual(2, dialog.progress["300"])
        with mock.patch.object(missions, "write_progress") as write:
            self.assertTrue(dialog.save())
            write.assert_called_once_with("career", dialog.progress, None)


if __name__ == "__main__":
    unittest.main()
