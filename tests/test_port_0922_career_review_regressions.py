"""Regressions from the 1.0.0 spotting, wreck and career audit."""
import copy
import io
import json
import math
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src/res/scripts/client'), str(ROOT / 'server')]
from gui.mods.offline_lan_0922.account_rpc import data, postbattle_store as ledger
from gui.mods.offline_lan_0922.personal_rating import personal_rating
from test_port_0922_career_dossiers import Dossier

def receipt(serial=1, stun=True):
    stats = dict(((key, 0) for key in ledger.RECEIPT_STAT_NAMES))
    stats.update(stun_num=5 if stun else 0, assist_stun=1000 if stun else 0, dropped_capture_points=250)
    return dict(receipt_id='audit:1:%d' % serial, arena_unique_id=serial, round_id=serial, player_id=1, account_key='audit-account', player_name='Audit', vehicle='usa:A38_T92', team=1, winner=1, map='01_karelia', death_reason=-1, duration=60, stats=stats, stun_capable=stun, rewards=dict(xp=600, credits=1000, free_xp=30), public_results=[dict(actor_kind='player', actor_id=1, name='Audit', vehicle='usa:A38_T92', team=1, health=100, death_reason=-1, killer_kind='', killer_id=0, is_team_killer=False, xp=600, stats=dict(stats), achievements=[])])

class RatingTests(unittest.TestCase):

    def test_unknown_historical_inputs_are_not_zero_performance(self):
        from gui.mods.offline_lan_0922.personal_rating import input_coverage
        progress = dict(vehicles={'legacy': dict(battles=10, wins=5, damage=1000)})
        self.assertIn('originalXP', input_coverage(progress)['legacy'])
        self.assertEqual(0, personal_rating(progress))
        row = progress['vehicles']['legacy']
        row.update(originalXP=0, survivedBattles=0,
                   damageAssistedRadio=0, damageAssistedTrack=0,
                   _rating_input_missing=['originalXP'])
        self.assertEqual({'legacy': ['originalXP']}, input_coverage(progress))
        self.assertEqual(0, personal_rating(progress))

    def test_formula_vector_and_no_banked_xp(self):
        self.assertEqual(0, personal_rating({}))
        row = dict(battles=1000, wins=530, survivedBattles=320, damage=1500000, originalXP=650000, damageAssistedRadio=200000, damageAssistedTrack=100000)
        progress = dict(vehicles={'one': row})
        self.assertEqual(5843, personal_rating(progress))
        row['xp'] = 65000000
        self.assertEqual(5843, personal_rating(progress))
        with mock.patch.object(data, 'account_dossier', return_value=''):
            self.assertEqual(5843, data.stats({}, progress)['account']['globalRating'])

    def test_account_entitlement_diff_keeps_current_rating(self):
        from gui.mods.offline_lan_0922.account_rpc import requests
        row = dict(battles=1000, wins=530, survivedBattles=320, damage=1500000, originalXP=650000, damageAssistedRadio=200000, damageAssistedTrack=100000)
        progress = dict(vehicles={'one': row})
        state = types.SimpleNamespace(snapshot=lambda: {}, touched_vehicles=lambda: set(), touched_items=lambda: {}, touched_tankmen=lambda: set(), touched_recycled=lambda: set())
        pushed = []
        context = dict(garage=state, push_update=pushed.append, postbattle_store=types.SimpleNamespace(progress=lambda: progress))
        with mock.patch.object(data, 'account_dossier', return_value=''), mock.patch.object(data, 'inventory', return_value={}):
            result = requests._fitting(context, lambda unused: True, extra_diff=lambda *unused: {'account': {'globalRating': 0, 'attrs': 123}})
            result.before_response()
        self.assertEqual(5843, pushed[0]['account']['globalRating'])
        self.assertEqual(123, pushed[0]['account']['attrs'])

    def test_sold_vehicle_and_duplicate_account_totals(self):
        row = dict(battles=100, wins=50, damage=100000, originalXP=50000,
                   survivedBattles=0, damageAssistedRadio=0, damageAssistedTrack=0)
        first = personal_rating(dict(vehicles={'sold': row}))
        self.assertGreater(first, 0)
        self.assertEqual(first, personal_rating(dict(battles=999999, vehicles={'sold': row})))

class CareerTests(unittest.TestCase):

    def test_old_receipt_bodies_do_not_erase_known_stun_facts(self):
        raw = receipt()
        raw['stats'].pop('stun_num')
        raw['public_results'][0]['stats'] = dict(raw['stats'])
        norm = ledger._receipt(raw)
        row = dict(battles=1, wins=1, xp=600, damage=0, kills=0,
                   stunStatsCoverage=1, stunNum=5, battlesOnStunningVehicles=1)
        progress = ledger.PostBattleStore._empty_progress()
        progress.update(battles=1, wins=1, vehicles={norm['vehicle']: row})
        saved = dict(schema=ledger.SCHEMA, accountKey='audit-account', pending=[],
                     history=[norm], progress=progress)
        store = ledger.PostBattleStore(path=None)
        with mock.patch('builtins.open', return_value=io.BytesIO(json.dumps(saved).encode())):
            self.assertIsNone(store._load_from('unused'))
        got = store.progress()['vehicles'][norm['vehicle']]
        self.assertEqual((1, 5, 1), (got['stunStatsCoverage'], got['stunNum'],
                                   got['battlesOnStunningVehicles']))

    def test_missing_base_xp_repairs_only_from_complete_receipts(self):
        norm = ledger._receipt(receipt(stun=False))
        for complete in (True, False):
            progress = ledger.PostBattleStore._empty_progress()
            progress.update(battles=1, wins=1, vehicles={norm['vehicle']: dict(
                battles=1, wins=1, losses=0, xp=99999, damage=0, kills=0)})
            archive = norm if complete else dict(receipt_id=norm['receipt_id'], arena_unique_id=1)
            saved = dict(schema=ledger.SCHEMA, accountKey='audit-account', pending=[],
                         history=[archive], progress=progress)
            store = ledger.PostBattleStore(path=None)
            with mock.patch('builtins.open', return_value=io.BytesIO(json.dumps(saved).encode())):
                self.assertIsNone(store._load_from('unused'))
            row = store.progress()['vehicles'][norm['vehicle']]
            if complete:
                self.assertEqual(600, row['originalXP'])
                self.assertNotIn('_rating_input_missing', row)
            else:
                self.assertIn('originalXP', row['_rating_input_missing'])
                self.assertEqual(99999, row['xp'])

    def test_previous_review_cache_version_is_invalidated(self):
        progress = dict(vehicles={'usa:A38_T92': dict(battles=1, wins=1, changeTime=1)})
        version, rows = data.dossiers(3, 9999, progress, Dossier, lambda name: 123)
        self.assertEqual(4, version)
        self.assertEqual(1, len(rows))

    def test_zero_stun_still_counts_and_raw_defence_stays_intact(self):
        store = ledger.PostBattleStore(path=None)
        raw = receipt()
        store._apply_progress(ledger._receipt(raw))
        second = receipt(2)
        second['stats'].update(stun_num=0, assist_stun=0)
        second['public_results'][0]['stats'] = dict(second['stats'])
        store._apply_progress(ledger._receipt(second))
        row = store.progress()['vehicles'][raw['vehicle']]
        self.assertEqual(5, row['stunNum'])
        self.assertEqual(2, row['battlesOnStunningVehicles'])
        self.assertEqual(2, row['stunStatsCoverage'])
        self.assertEqual(200, row['droppedCapturePoints'])
        self.assertEqual(250, raw['stats']['dropped_capture_points'])
        dossier = Dossier('')
        data._write_battle_statistics(dossier, row)
        self.assertEqual(2, dossier['a15x15_2']['battlesOnStunningVehicles'])
        self.assertEqual(500, dossier['a15x15_2']['damageAssistedStun'] / 2)

    def test_non_stunning_vehicle_not_in_denominator(self):
        store = ledger.PostBattleStore(path=None)
        store._apply_progress(ledger._receipt(receipt(stun=False)))
        row = store.progress()['vehicles']['usa:A38_T92']
        self.assertEqual(1, row['stunStatsCoverage'])
        self.assertEqual(0, row.get('battlesOnStunningVehicles', 0))

    def test_partial_history_cannot_divide_lifetime_assistance(self):
        row = dict(battles=20, damageAssistedStun=40000, stunStatsCoverage=2, battlesOnStunningVehicles=2, stunNum=5)
        dossier = Dossier('')
        data._write_battle_statistics(dossier, row)
        self.assertEqual(40000, dossier['a15x15_2']['damageAssistedStun'])
        self.assertEqual(0, dossier['a15x15_2']['battlesOnStunningVehicles'])

    def test_migration_requires_complete_receipts_and_is_idempotent(self):
        norm = ledger._receipt(receipt())
        for complete in (True, False):
            row = dict(battles=1, wins=1, xp=600, damage=0, kills=0, damageAssistedStun=1000, droppedCapturePoints=250)
            progress = ledger.PostBattleStore._empty_progress()
            progress.update(battles=1, wins=1, vehicles={'usa:A38_T92': row})
            archive = norm if complete else dict(receipt_id=norm['receipt_id'], arena_unique_id=1)
            saved = dict(schema=ledger.SCHEMA, accountKey='audit-account', pending=[], history=[archive], progress=progress)
            store = ledger.PostBattleStore(path=None)
            for attempt in range(2):
                with mock.patch('builtins.open', return_value=io.BytesIO(json.dumps(saved).encode())):
                    self.assertIsNone(store._load_from('unused'))
                got = store.progress()['vehicles']['usa:A38_T92']
                self.assertEqual(1 if complete else 0, got['stunStatsCoverage'])
                self.assertEqual(100 if complete else 250, got['droppedCapturePoints'])
                saved['progress'] = store.progress()

    def test_mounted_shell_controls_capability(self):
        for stun in (None, object()):
            descriptor = types.SimpleNamespace(gun=types.SimpleNamespace(shots=[types.SimpleNamespace(shell=types.SimpleNamespace(stun=stun))]))
            vehicles = types.SimpleNamespace(VehicleDescr=mock.Mock(return_value=descriptor))
            with mock.patch.dict(sys.modules, {'items': types.SimpleNamespace(vehicles=vehicles)}):
                row = dict(vehicle_compact_descr='YQ==', stats=dict(stun_num=0))
                self.assertEqual(stun is not None, ledger._stun_capable(row))


if __name__ == "__main__":
    unittest.main()
