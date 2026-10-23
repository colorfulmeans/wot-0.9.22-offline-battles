"""Native recruit construction and crash-safe per-save barracks delivery."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/res/scripts/client'))
from gui.mods.offline_lan_0922 import crew_recruits as crew
from gui.mods.offline_lan_0922.account_rpc import garage_store


def row(identifier='a' * 32, **changes):
    value = dict(id=identifier, nation='ussr', vehicle='ussr:R11_MS-1', role='commander', female=False, skills=2)
    value.update(changes)
    return value


class CrewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / crew.FILE_NAME
        self.snapshot = dict(vehicles=[dict(id=1, vehicleTypeCompactDescr=1, crew=[100001], tankmen={100001: b'original'})],
            barracksTankmen={}, recycleBinTankmen={100002: (b'dismissed', 0)}, accountBerths=2,
            personalMissionRewardJournal={'crew:1': {'tankman': 100003}})
        self.saved = None
        self.store = NS(mark_dirty=lambda: None, flush=self.flush)
        self.write([row()])

    def write(self, rows):
        self.path.write_text(json.dumps(dict(schema=1, crew=rows)), encoding='utf8')

    def flush(self, snapshot):
        self.saved = copy.deepcopy(snapshot)
        return True

    def deliver(self, write=None):
        with patch.object(crew, 'build', return_value=b'new recruit'):
            return crew.deliver(self.snapshot, NS(), NS(), self.store, str(self.path),
                lambda path, rows: (write or self.write)(rows), lambda message: None)

    def test_member_receipt_and_system_notice_commit_together_with_distinct_id(self):
        self.assertEqual(1, self.deliver())
        self.assertEqual({100004: b'new recruit'}, self.snapshot['barracksTankmen'])
        self.assertEqual(['a' * 32], self.saved[crew.RECEIPTS])
        notice = self.saved['personalMissionNotifications'][0]['settlement']
        self.assertEqual(1, notice['account_changes'][0]['rewards'][0]['count'])
        self.assertEqual([], crew.read(str(self.path)))

    def test_failed_save_keeps_request_and_all_live_assets_unchanged(self):
        before = copy.deepcopy(self.snapshot)
        self.store.flush = lambda snapshot: False
        self.assertEqual(0, self.deliver())
        self.assertEqual(before, self.snapshot)
        self.assertEqual([row()], crew.read(str(self.path)))

    def test_failed_inbox_write_then_restart_does_not_duplicate_member_or_notice(self):
        def fail(rows): raise OSError('inbox unavailable')
        with self.assertRaises(OSError): self.deliver(fail)
        restored = copy.deepcopy(self.saved)
        self.snapshot = restored
        self.assertEqual(0, self.deliver())
        self.assertEqual(1, len(self.snapshot['barracksTankmen']))
        self.assertEqual(1, len(self.snapshot['personalMissionNotifications']))
        self.assertEqual([], crew.read(str(self.path)))

    def test_full_barracks_and_native_failure_remain_pending(self):
        self.snapshot['accountBerths'] = 0
        self.assertEqual(0, self.deliver())
        self.assertEqual([row()], crew.read(str(self.path)))
        self.snapshot['accountBerths'] = 2
        with patch.object(crew, 'build', side_effect=ValueError('native refusal')):
            self.assertEqual(0, crew.deliver(self.snapshot, NS(), NS(), self.store,
                str(self.path), lambda path, rows: self.write(rows), lambda message: None))
        self.assertFalse(self.snapshot['barracksTankmen'])

    def test_multiple_identical_presets_are_intentionally_distinct_people(self):
        self.write([row(), row('b' * 32)])
        self.assertEqual(2, self.deliver())
        self.assertEqual({100004, 100005}, set(self.snapshot['barracksTankmen']))

    def test_receipts_survive_real_ledger_projection_and_restore(self):
        # The full ledger's other fields are exercised by garage-store tests.
        self.deliver()
        payload = garage_store._ledger_payload(self.snapshot)
        self.assertEqual(['a' * 32], payload[crew.RECEIPTS])
        restored = copy.deepcopy(self.snapshot); restored.pop(crew.RECEIPTS)
        garage_store._apply_ledger(restored, {'ledger': payload})
        self.assertEqual(['a' * 32], restored[crew.RECEIPTS])

    def test_unexpected_requests_do_not_reach_native_factory(self):
        for changes in (dict(skills=True), dict(skills=14), dict(skills=-1), dict(female=1),
                        dict(nation='usa'), dict(vehicle='ussr:R11_MS-1\n'), dict(id='a' * 32 + '\n')):
            with self.assertRaises(ValueError): crew.request(row(**changes))

    def test_native_factory_receives_gender_and_unassigned_exact_skill_xp(self):
        vehicle = NS(type=NS(id=(0, 1), crewRoles=(('commander', 'gunner'), ('driver',))))
        calls = []
        class Descriptor:
            levelUpXpCost = staticmethod(lambda level, sequence: (level + 1) * 2 ** sequence)
            def __init__(self, raw): self.__dict__.update(raw)
        def factory(data):
            calls.append(data)
            return data
        tankmen = NS(TankmanDescr=Descriptor, makeTmanDescrByTmanData=factory)
        value = crew.build(row(female=True), NS(VehicleDescr=lambda **kwargs: vehicle), tankmen)
        self.assertEqual(30300, value['freeXP'])
        self.assertEqual([], value['skills']); self.assertEqual([], value['freeSkills'])
        self.assertTrue(value['isFemale']); self.assertEqual(100, value['roleLevel'])
        with self.assertRaises(ValueError):
            crew.build(row(role='loader'), NS(VehicleDescr=lambda **kwargs: vehicle), tankmen)


if __name__ == '__main__': unittest.main()
