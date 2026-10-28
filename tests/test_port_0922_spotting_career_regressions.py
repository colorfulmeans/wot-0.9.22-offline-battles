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
from gui.mods.offline_lan_0922 import radio, tank_collision, native_control_core
from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
from gui.mods.offline_lan_0922.account_rpc import data, postbattle_store as ledger
from gui.mods.offline_lan_0922.personal_rating import personal_rating
from lan_battle_server import BattleState
from test_port_0922_career_dossiers import Dossier

def receipt(serial=1, stun=True):
    stats = dict(((key, 0) for key in ledger.RECEIPT_STAT_NAMES))
    stats.update(stun_num=5 if stun else 0, assist_stun=1000 if stun else 0, dropped_capture_points=250)
    return dict(receipt_id='audit:1:%d' % serial, arena_unique_id=serial, round_id=serial, player_id=1, account_key='audit-account', player_name='Audit', vehicle='usa:A38_T92', team=1, winner=1, map='01_karelia', death_reason=-1, duration=60, stats=stats, stun_capable=stun, rewards=dict(xp=600, credits=1000, free_xp=30), public_results=[dict(actor_kind='player', actor_id=1, name='Audit', vehicle='usa:A38_T92', team=1, health=100, death_reason=-1, killer_kind='', killer_id=0, is_team_killer=False, xp=600, stats=dict(stats), achievements=[])])

class RatingTests(unittest.TestCase):

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
        row = dict(battles=100, wins=50, damage=100000, originalXP=50000)
        first = personal_rating(dict(vehicles={'sold': row}))
        self.assertGreater(first, 0)
        self.assertEqual(first, personal_rating(dict(battles=999999, vehicles={'sold': row})))

class CareerTests(unittest.TestCase):

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

class RadioTests(unittest.TestCase):

    def test_individual_retained_sources_require_recipient_link(self):
        network = radio.RadioNetwork()
        observer, peer, far = (('human', 1), ('bot', 2), ('human', 3))
        target = ('bot', 18)
        actors = {observer: (1, (0, 0, 0), 60), peer: (1, (100, 0, 0), 60), far: (1, (400, 0, 0), 60)}
        network.configure(actors, 1)
        network.observe(observer, target, 1, 10, dict(x=0))
        network.observe(far, target, 1, 10, dict(x=0))
        network.hidden(observer, target)
        self.assertEqual([(observer, 9)], network.assist_sources(peer, target, 2))
        self.assertEqual([], network.assist_sources(peer, target, 11))
        actors[observer] = (1, (-1000, 0, 0), 60)
        network.configure(actors, 2)
        self.assertEqual([], network.assist_sources(peer, target, 2))

    def test_native_events_export_same_individual_lease(self):
        owner = types.SimpleNamespace(_old_radio=radio.RadioNetwork(), _now=2)
        native = native_control_core._NativeRadio(owner)
        native.actors = {('human', 1): (1, (0, 0, 0), 60), ('bot', 2): (1, (0, 0, 0), 60)}
        native.connected = lambda a, b: True
        runtime = types.SimpleNamespace(_visible_target_poses={}, _spot_until={})
        adapter = types.SimpleNamespace(runtime=runtime, radio=native, backend=None, _sources={(0, 1): dict(team=1)}, _old_radio=owner._old_radio, observations=lambda: ())
        with mock.patch.object(native_control_core, '_observation_rows', return_value=[((0, 1), (1, 18), 1.0, 10.0, {})]):
            native_control_core.NativeControl._sync_events(adapter)
        self.assertEqual([(('human', 1), 9.0)], native.assist_sources(('bot', 2), ('bot', 18), 2.0))
        native.actors.pop(('human', 1))
        self.assertEqual([], native.assist_sources(('bot', 2), ('bot', 18), 2.0))

    def test_server_source_validation(self):
        actors = {('human', 1): (1, True), ('bot', 2): (1, True), ('bot', 3): (2, True)}
        source = dict(kind='human', id=1, time_left=4.0)
        recipient = dict(kind='bot', id=2, time_left=5.0, spotters=[source])
        result = BattleState._validated_radio_rows([recipient], actors, 1, max_duration=10.0)
        self.assertEqual([source], result[0]['spotters'])
        for update in (dict(kind='bot', id=2), dict(kind='bot', id=3), dict(time_left=6.0), dict(spotters=[])):
            bad = copy.deepcopy(recipient)
            bad['spotters'][0].update(update)
            with self.assertRaises(ValueError):
                BattleState._validated_radio_rows([bad], actors, 1, max_duration=10.0)

    def test_worker_batch_commits_sources_atomically_and_empty_batch_clears(self):
        from test_port_0922_bot_runtime import ServerBotObservationRelayTests as fixture
        from lan_battle_server import SIMULATION_WORKER_AUTHORITY_ID as worker
        state, unused, unused = fixture._server()
        message = fixture._human_message(state.round_id, observer_ids=())
        contact = message['contacts'][0]
        contact['fresh'] = False
        contact['radio_recipients'] = [dict(kind='human', id=2, time_left=8.0, spotters=[dict(kind='human', id=1, time_left=8.0)])]
        with mock.patch('lan_battle_server.time.monotonic', return_value=100.0):
            result = state.update_bot_observation(worker, message)
            self.assertIsInstance(result, dict)
            self.assertEqual([('player', 1)], state._radio_assisters(('player', 2), ('bot', 11), 2))
            before = copy.deepcopy(state.spotting_assist_leases)
            invalid = copy.deepcopy(message)
            invalid['contacts'][0]['radio_recipients'][0]['spotters'][0]['id'] = 999
            self.assertFalse(state.update_bot_observation(worker, invalid))
            self.assertEqual(before, state.spotting_assist_leases)
            state.update_bot_observation(worker, dict(round_id=state.round_id, contacts=[]))
            self.assertEqual([], state._radio_assisters(('player', 2), ('bot', 11), 2))

    def test_server_retained_owner_expires(self):
        state = object.__new__(BattleState)
        state.players = {1: types.SimpleNamespace(connected=True, alive=True, team=1)}
        state.bot_states = {2: dict(alive=True, team=1)}
        state.player_spotted = {1: set()}
        state.bot_spotted = {2: set()}
        attacker, target = (('bot', 2), ('bot', 18))
        state._vehicle_team = lambda kind, identity: 1
        state.spotting_assist_leases = {(attacker, target): [(('player', 1), 11.0)]}
        with mock.patch('lan_battle_server.time.monotonic', return_value=2.0):
            self.assertEqual([('player', 1)], state._radio_assisters(attacker, target, 2))
        with mock.patch('lan_battle_server.time.monotonic', return_value=12.0):
            self.assertEqual([], state._radio_assisters(attacker, target, 2))

class WreckTests(unittest.TestCase):

    def worker(self):
        worker = object.__new__(BotRuntime)
        worker._descriptors = {}
        worker._contact_motion_bodies = lambda unused: []
        worker._baked_pose_progress_clear = lambda *args: True
        worker._turret_pose_is_clear = lambda *args: True
        worker._wreck_rotation_probe = lambda *args, **kwargs: True
        worker.motion_resolver = lambda *args, **kwargs: 'clear'
        worker._passive_motion_status = lambda *args, **kwargs: 'clear'
        return worker

    def state(self):
        return dict(id=16, x=0.0, y=0.0, z=0.0, yaw=1.24765, aim_yaw=-2.77334, turret_yaw=2.262195307179586, gun_pitch=0.018, collision_shape=tank_collision.DEFAULT_SHAPE, mass=29300.0, alive=False)

    def check_angles(self, state):
        self.assertAlmostEqual(0.0, math.sin(state['aim_yaw'] - state['yaw'] - state['turret_yaw']))
        self.assertAlmostEqual(2.262195307179586, state['turret_yaw'])

    def test_both_admitted_rotation_paths(self):
        for combined in (False, True):
            state = self.state()
            worker = self.worker()
            if combined:
                self.assertTrue(worker._try_wreck_swept_pose(state, (0.219, 0.481), 0.38762, 1.0))
            else:
                state['push_yaw'] = 0.38762
                worker._advance_wreck_yaw(state, dict(delta_yaw=0.0), 1.0)
            self.assertAlmostEqual(1.63527, state['yaw'])
            self.check_angles(state)

    def test_blocked_pose_does_not_commit(self):
        state = self.state()
        before = copy.deepcopy(state)
        worker = self.worker()
        worker._wreck_rotation_probe = lambda *args, **kwargs: False
        self.assertFalse(worker._try_wreck_swept_pose(state, (0.2, 0.4), 0.4, 1.0))
        self.assertEqual(before, state)

    def test_ground_rejection_rolls_back_angles(self):
        state = self.state()
        before = copy.deepcopy(state)
        worker = self.worker()
        worker._physics_ground_probe = lambda *args: 0.0
        worker._physics_params_for = lambda unused: None
        worker._contact_now = None

        def commit(*unused):
            worker._set_wreck_hull_yaw(state, state['yaw'] + 0.4)
            return True
        worker._try_wreck_swept_pose = commit
        worker._update_vertical_motion = lambda *args: True
        worker._apply_wreck_contact_response(state, dict(delta_velocity=(0.0, 0.0), delta_yaw=0.4, correction=(0.0, 0.0)), 1.0)
        self.assertAlmostEqual(before['yaw'], state['yaw'])
        self.assertAlmostEqual(before['aim_yaw'], state['aim_yaw'])
        self.check_angles(state)

    def test_wrap_and_missing_relative_field(self):
        state = self.state()
        state.pop('turret_yaw')
        BotRuntime._set_wreck_hull_yaw(state, 7.0)
        self.check_angles(state)
if __name__ == '__main__':
    unittest.main()
