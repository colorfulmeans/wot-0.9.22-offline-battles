"""Recorded mixed refusal and postmortem fire lifecycle regressions."""
import math, types, unittest, json, subprocess, copy
from pathlib import Path
from unittest import mock
import test_port_0922_bot_combat_manoeuvre as feedback
import test_port_0922_battle_runtime as battle
from gui.mods.offline_lan_0922 import player_critical_mechanics as mechanics


class ExhaustedLocalActionTests(unittest.TestCase):
    setUp = feedback.LocalActionFeedbackTests.setUp

    def test_off_heading_native_and_remembered_pivot_failures_retire_private_target(self):
        proof = dict(self.proof, yaw=self.proof['yaw']+1.6)
        rows = [proof, dict(kind='rotation',clear=False,reason='local_sweep_blocked'),
                dict(kind='rotation',clear=False,reason='realized_rotation_rejection')]
        for now in (10.,10.3,10.6,10.9,11.2):
            self.runtime._report_blocked_planner(self.position,self.command,
                {},self.state,now,rows)
        self.assertEqual(1,self.nav.bot_states[20]['blocked_step_replans'])
        self.assertEqual({},self.nav.grid._failed_edges)
        self.assertTrue(self.state['_planner_blocked_handoff']['local_actions_exhausted'])

    def test_one_available_or_deferred_candidate_prevents_exhaustion(self):
        for clear in (True,None):
            proof=dict(self.proof,yaw=self.proof['yaw']+1.6)
            rows=[proof,dict(kind='rotation',clear=False,reason='local_sweep_blocked'),
                  dict(kind='rotation',clear=clear,reason='deferred')]
            self.runtime._report_blocked_planner(self.position,self.command,{},self.state,10.,rows)
            self.assertFalse(self.state['_planner_blocked_handoff']['local_actions_exhausted'])
            self.assertFalse(self.nav.bot_failed_edges)

    def test_traffic_only_does_not_publish_static_failure(self):
        rows=[dict(kind='rotation',clear=False,reason='friendly_or_wreck_rotation')]
        self.runtime._report_blocked_planner(self.position,self.command,{},self.state,10.,rows)
        self.assertFalse(self.nav.bot_failed_edges)


class PostmortemFireTests(unittest.TestCase):
    def test_late_live_snapshot_cannot_reignite_dead_vehicle_or_hud(self):
        runtime=battle._runtime(); owner=battle.BattleRuntime(runtime)
        owner._avatar=runtime.bigworld.avatar
        entity=battle._Vehicle(10,battle._Descriptor(),battle._Vector(),(0,0,0),{'health':0})
        runtime.bigworld.entities[10]=entity
        record=dict(engine_id=10,state=dict(health=0,alive=False),kind='player',network_id=1,local=True)
        owner._present_critical=mock.Mock(return_value=True)
        payload=dict(devices=[],destroyed=[],crew_ko=[],fire=True,ammo_rack_death=False,
                     events=[dict(kind='fire',state=True,cause='shot')])
        owner._apply_critical_state(record,payload)
        self.assertFalse(entity.is_on_fire)
        self.assertFalse(record['critical_state']['fire'])
        self.assertFalse(any(e.get('kind')=='fire' and e.get('state') for e in owner._present_critical.call_args.args[1]))

    def test_already_dead_participant_clears_durable_fire_and_attribution(self):
        import test_port_0922_consumable_audit as fixture
        owner,player=fixture.battle_state([])
        player.critical=dict(fire=True)
        player.alive=False;player.health=0
        player.combat_fire_timer=5.;player.combat_fire_elapsed=2.
        player.fire_attacker_kind='bot';player.fire_attacker_id=8
        owner.last_shell_fire_sources[('player',player.player_id)]=('bot',8)
        def commit(participant,payload):participant.critical=payload
        with mock.patch.object(owner,'_commit_player_critical_progress',side_effect=commit):
            self.assertEqual(1,owner._tick_player_fire(.1))
            self.assertEqual(0,owner._tick_player_fire(.1))
        self.assertFalse(player.critical['fire'])
        self.assertEqual(0.,player.combat_fire_timer)
        self.assertEqual('',player.fire_attacker_kind)
        self.assertNotIn(('player',player.player_id),owner.last_shell_fire_sources)

    def test_lethal_server_fire_publishes_stop_in_same_damage_result(self):
        player=types.SimpleNamespace(critical=dict(fire=True),alive=True,health=1,combat_fire_elapsed=0.)
        target=types.SimpleNamespace(is_on_fire=True,_fire_timer=0.)
        payload=dict(devices=[],destroyed=[],crew_ko=[],fire=True,events=[])
        def extinguish(*unused):target.is_on_fire=False
        with mock.patch.object(mechanics,'_descriptor',return_value=object()), \
             mock.patch.object(mechanics,'_CriticalTarget',return_value=target), \
             mock.patch.object(mechanics.critical_damage,'tick_fire',return_value=(2,payload)), \
             mock.patch.object(mechanics.critical_damage,'_state',return_value=dict(fire=True)), \
             mock.patch.object(mechanics.critical_damage,'_offh_extinguish',side_effect=extinguish):
            result=mechanics.advance_fire(player,1.,10.)
        self.assertFalse(result['critical']['fire'])
        self.assertFalse(result['burning'])
        self.assertEqual(0.,result['fire_timer'])
        self.assertIn(dict(kind='fire',state=False,cause='fire'),result['critical']['events'])


class RailwayBirthDataTests(unittest.TestCase):
    def test_all_railway_spawn_changes_are_recorded_without_grid_or_route_edits(self):
        root=Path(__file__).resolve().parents[1]
        checked=changed=0
        for path in (root/'navgraphs').glob('*.json'):
            graph=json.loads(path.read_bytes())
            receipt=graph.get('validation',{}).get('spawn_railway_revalidation')
            if not receipt:continue
            original=json.loads(subprocess.check_output(
                ['git','show','e87b0108:navgraphs/'+path.name],cwd=root))
            for key in ('routes','heights_mm','links','hazards','local_meshes'):
                self.assertEqual(original.get(key),graph.get(key),(path.name,key))
            expected=copy.deepcopy(original['spawn_formations'])
            for row in receipt['changes']:
                self.assertEqual(row['before'],expected[row['team']][row['slot']])
                self.assertEqual(row['before'][3],row['after'][3])
                self.assertLessEqual(math.hypot(row['after'][0]-row['before'][0],
                    row['after'][2]-row['before'][2]),32.)
                expected[row['team']][row['slot']]=row['after']
            # Later, independently evidenced local ground repairs compose with
            # the railway birth audit; they must not erase its retained receipt.
            level=graph.get('validation',{}).get('spawn_level_ground_revalidation')
            if level:
                self.assertEqual('47_canada_a',path.stem)
                self.assertEqual(30,level['slots_checked'])
                for row in level['changes']:
                    slot=row['slot']-1  # Ground audit uses user-facing slots.
                    self.assertEqual(row['before'],expected[row['team']][slot])
                    self.assertEqual(row['before'][3],row['after'][3])
                    self.assertFalse(row['ground_before']['clear'])
                    self.assertTrue(row['ground_after']['clear'])
                    self.assertLessEqual(row['shift'],16.)
                    expected[row['team']][slot]=row['after']
            self.assertEqual(expected,graph['spawn_formations'])
            checked+=receipt['slots_checked'];changed+=len(receipt['changes'])
            if path.stem=='06_ensk':
                self.assertNotEqual(original['spawn_formations']['1'][7],
                                    graph['spawn_formations']['1'][7])
        self.assertEqual(330,checked)
        self.assertEqual(151,changed)


class NavigationResolutionEvidenceTests(unittest.TestCase):
    def test_spawn_validator_accepts_only_recorded_changes(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        import check_navigation_resolution as checker
        root=Path(__file__).resolve().parents[1]
        name='04_himmelsdorf'
        old=json.loads(subprocess.check_output(['git','show',
            'ca22f909:navgraphs/'+name+'.json'],cwd=root))
        new=json.loads((root/'navgraphs'/(name+'.json')).read_bytes())
        checker.verify_retained_gameplay(old,new,name)
        altered=copy.deepcopy(new)
        altered['spawn_formations']['1'][0][0]+=.1
        with self.assertRaises(AssertionError):checker.verify_retained_gameplay(old,altered,name)
        altered=copy.deepcopy(new)
        altered['routes']={}
        with self.assertRaises(AssertionError):checker.verify_retained_gameplay(old,altered,name)
