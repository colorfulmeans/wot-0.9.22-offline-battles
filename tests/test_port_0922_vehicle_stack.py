"""Vertical contacts: real native admission, time and settlement ownership."""
import contextlib
import io
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as battle_fixture
import test_port_0922_contact_support_navigation as support
from test_port_0922_server_projectiles import _state, _update_player_input
from gui.mods.offline_lan_0922 import vehicle_stack, tank_collision


class StackLawTests(unittest.TestCase):
    def test_pressure_is_elapsed_time_based_at_different_update_rates(self):
        receipts=[]
        for hz in (6,15,30,60):
            ledger=vehicle_stack.Ledger()
            for unused in range(hz*6):
                ledger.advance(('player',1),('bot',11),1./hz,True,True,36000,36000)
            receipts.append(ledger.publication()[0])
        self.assertEqual({30},{row['lower_total'] for row in receipts})
        self.assertEqual({30},{row['upper_total'] for row in receipts})

    def test_top_wreck_keeps_pressure_bottom_wreck_stops_it(self):
        ledger=vehicle_stack.Ledger()
        ledger.advance(('bot',11),('player',1),2.,False,True,36000,36000)
        row=ledger.publication()[0]
        self.assertEqual((0,10),(row['upper_total'],row['lower_total']))
        ledger.advance(('bot',11),('player',1),20.,True,False,36000,36000)
        self.assertEqual(row,ledger.publication()[0])

    def test_striking_mass_changes_lower_impact_without_planar_ram(self):
        self.assertGreater(vehicle_stack.impact_damage(1000,20,60000,30000),
                           vehicle_stack.impact_damage(1000,20,30000,60000))
        self.assertEqual(0,vehicle_stack.impact_damage(1000,5,60000,30000))

    def test_proved_stack_never_gets_horizontal_separation_or_repeated_ram(self):
        upper=dict(id=11,kind='bot',network_id=11,x=0.,y=1.,z=0.,yaw=0.,
            mass=36000.,vx=0.,vz=0.,shape=(1.5,3.,0.,2.),alive=True,
            stack_carrier=['bot',12])
        lower=dict(upper,id=12,network_id=12,y=0.,stack_carrier=None)
        solved=tank_collision.resolve_pairs([upper,lower],.1)
        self.assertEqual((0.,0.),solved[11]['correction'])
        result=tank_collision.resolve_tank(upper,[lower],now=1.,dt=.1)
        self.assertFalse(result['ram_events'])
        self.assertEqual(1.,tank_collision.translation_fraction(upper,(0.,1.),[lower]))
        self.assertEqual((0.,1.),tank_collision.slide_translation(upper,(0.,1.),[lower]))


class StackSettlementTests(unittest.TestCase):
    def scene(self):
        state=_state()
        for player in state.players.values():
            player.health=player.max_health=1000
        return state

    def receipt(self,up=5,low=5):
        return dict(stacks=[dict(upper=['player',1],lower=['player',2],
            upper_total=up,lower_total=low,contact_seconds=1.)])

    def test_replay_coalescing_and_old_receipts_never_repeat_hp(self):
        state=self.scene()
        state._consume_stack_contacts(self.receipt())
        state._consume_stack_contacts(self.receipt())
        self.assertEqual((995,995),(state.players[1].health,state.players[2].health))
        state._consume_stack_contacts(self.receipt(20,20))
        state._consume_stack_contacts(self.receipt(10,10))
        self.assertEqual((980,980),(state.players[1].health,state.players[2].health))
        for event in state.pending_events:
            if event.get('stack_phase'):
                self.assertTrue(state._validate_combat_event_for_wire(event))

    def test_friendly_damage_uses_existing_blue_and_team_damage_statistics(self):
        state=self.scene();state.players[2].team=1
        state._consume_stack_contacts(self.receipt())
        self.assertEqual(5,state._statistics_row('player',1)['team_damage'])
        self.assertEqual(0,state._statistics_row('player',1)['damage_dealt'])
        self.assertTrue(state.players[1].team_killer)

    def test_dead_top_can_damage_and_kill_live_bottom_once(self):
        state=self.scene();state.players[1].alive=False;state.players[1].health=0
        state.players[2].health=3
        state._consume_stack_contacts(self.receipt(0,5))
        self.assertFalse(state.players[2].alive)
        self.assertEqual(1,state.players[1].frags)
        state._consume_stack_contacts(self.receipt(0,10))
        self.assertEqual(1,state.players[1].frags)

    def test_dead_bottom_cannot_keep_hurting_top(self):
        state=self.scene();state.players[2].alive=False;state.players[2].health=0
        state._consume_stack_contacts(self.receipt(100,100))
        self.assertEqual(1000,state.players[1].health)

    def test_player_landing_hits_lower_once_through_reliable_landing_channel(self):
        state=self.scene()
        state.human_collision_profiles={1:dict(mass=36000.),2:dict(mass=36000.)}
        player=state.players[1]
        player.offer_reliable=lambda unused:True
        self.assertTrue(_update_player_input(state,1,up_cosine=1.))
        message=dict(type='landing_observation',round_id=state.round_id,
            authority_epoch=state.authority_epoch,observation_seq=1,
            input_seq=player.input_seq,impact_speed=20.,vehicle_contact=['player',2])
        self.assertTrue(state.submit_landing_observation(1,message))
        self.assertEqual((700,700),(state.players[1].health,state.players[2].health))
        self.assertTrue(state.submit_landing_observation(1,message))
        self.assertEqual((700,700),(state.players[1].health,state.players[2].health))
        self.assertFalse(state.submit_landing_observation(1,dict(message,vehicle_contact=['player',1])))

    def test_bot_roof_impact_uses_manifest_mass_and_updates_stock_event(self):
        state=self.scene()
        state.bot_states[11]=dict(id=11,team=2,health=1000,max_health=1000,
            alive=True,x=0.,y=0.,z=0.,vehicle='china:Ch01_Type59')
        state.bot_manifest=[dict(id=11,stack_mass=36000.)]
        self.assertEqual(36000.,state._stack_actor_mass(('bot',11)))
        state._consume_stack_contacts(dict(stacks=[dict(upper=['player',1],
            lower=['bot',11],upper_total=5,lower_total=25)]))
        self.assertEqual(975,state.bot_states[11]['health'])
        event=next(e for e in state.pending_events if e.get('target_bot')==11 and e.get('stack_phase'))
        self.assertEqual('bot_hit',event['kind'])
        self.assertTrue(state._validate_combat_event_for_wire(event))
        self.assertEqual(25,state._statistics_row('player',1)['damage_dealt'])

    def test_client_landing_queue_retains_lower_identity_on_retry(self):
        import test_port_0922_lan_client_projectiles as wire_fixture
        fixture=wire_fixture.ProjectileWireTests()
        client=fixture.active_client()
        self.assertTrue(fixture.send_player_input(client))
        self.assertEqual(1,client.send_landing_observation(20.,vehicle_contact=['bot',11]))
        self.assertEqual(['bot',11],client._landing_observation_pending['wire']['vehicle_contact'])
        self.assertTrue(client._send_pending_landing_observation(rebind=True))
        self.assertEqual(['bot',11],client._landing_observation_pending['wire']['vehicle_contact'])
        self.assertFalse(client.send_landing_observation(20.,vehicle_contact=['bad',11]))

    def test_epoch_change_retires_pressure_ledger(self):
        runtime=battle_fixture._runtime()
        battle=battle_fixture.BattleRuntime(runtime)
        battle.client=types.SimpleNamespace(round_id=1,authority_epoch=1)
        ledger=battle._stack_ledger_for_round()
        ledger.strike(('player',1),('bot',11),30)
        battle.client.authority_epoch=2
        self.assertEqual([],battle._stack_publication())


class NativeRoofAdmissionTests(unittest.TestCase):
    def scene(self):
        runtime=battle_fixture._runtime()
        battle=battle_fixture.BattleRuntime(runtime)
        battle._avatar=runtime.bigworld.avatar
        state=dict(id=12,x=0.,y=0.,z=0.,yaw=0.,collision_shape=(1.5,3.,0.,2.))
        entity=types.SimpleNamespace(typeDescriptor=object())
        actor=dict(id=11,x=0.,y=2.,z=0.,yaw=0.,pitch=0.,roll=0.)
        battle._stack_context=dict(actor=actor,hits=[],candidates=[(('bot',12),state,entity)])
        battle._warn_optional_failure=mock.Mock()
        return battle,actor

    def test_only_upward_non_gun_native_hit_can_support(self):
        for component,normal,expected in (('vehicleHull',1.,True),
                ('vehicleGun',1.,False),('vehicleHull',-1.,False),
                ('vehicleHull',.1,False)):
            with self.subTest(component=component,normal=normal):
                battle,actor=self.scene()
                collision=types.SimpleNamespace(dist=.1,compName=component)
                evidence=types.SimpleNamespace(collision=collision,
                    worldNormal=battle_fixture._Vector(0.,normal,0.))
                with mock.patch.object(battle_fixture.battle_runtime_module,'_collide_vehicle_evidence_at_matrix',return_value=[evidence]):
                    hit=battle._stack_ground_hit(battle._vector((0.,2.1,0.)),
                        battle._vector((0.,1.9,0.)),None)
                self.assertEqual(expected,hit is not None)
                self.assertEqual(expected,bool(actor.get('_stack_carrier')))

    def test_no_native_hit_cannot_invent_roof_from_obb_overlap(self):
        battle,actor=self.scene()
        with mock.patch.object(battle_fixture.battle_runtime_module,'_collide_vehicle_evidence_at_matrix',return_value=[]):
            self.assertIsNone(battle._stack_ground_hit(battle._vector((0.,2.1,0.)),
                battle._vector((0.,1.9,0.)),None))
        self.assertNotIn('_stack_carrier',actor)


class SupportAndRecoveryTests(unittest.TestCase):
    scene=support.ContactSupportTests.scene

    def test_travel_on_same_supported_slope_does_not_reactivate_detailed(self):
        runtime,state=self.scene(lambda x,z:.25*z)
        state.update(pitch=-math.atan(.25),terrain_pitch=-math.atan(.25),
                     _edge_support_active=True,airborne=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._release_detailed_support(state))
            for frame in range(1,30):
                runtime._contact_now=frame
                state['z']+=2.
                # Horizontal integration precedes height settlement.
                self.assertFalse(runtime._contact_edge_support_needed(state))
                state['y']=.25*state['z']

    def test_one_real_missing_point_still_enables_then_five_restore_close(self):
        terrain=lambda x,z:0. if x<=.5 else None
        runtime,state=self.scene(terrain)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(runtime._contact_edge_support_needed(state))
            self.assertFalse(runtime._release_detailed_support(state))
            runtime._physics_ground_probe=lambda *unused:0.
            self.assertTrue(runtime._release_detailed_support(state))

    def test_short_recovery_grade_excludes_body_ground_clearance(self):
        runtime=battle_fixture._runtime()
        battle=battle_fixture.BattleRuntime(runtime)
        battle._avatar=runtime.bigworld.avatar
        battle._water_depth=lambda unused:0.
        battle._support_column=lambda *args,**kwargs:0.
        def ray(start,end,trace):
            if start.x==end.x and start.z==end.z:
                return (battle._vector((start.x,-.35*start.z,start.z)),)
            return None
        battle._collide_navigation=ray
        result=battle._direction_probe((0.,.25,0.),0.,0.,object(),.5,
                                      corridor_half_width=1.5)
        self.assertTrue(result['clear'],result)
        self.assertAlmostEqual(-.35,result['slope'])


if __name__=='__main__':unittest.main()
