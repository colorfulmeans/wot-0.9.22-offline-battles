"""Contact provenance, deferred impact commits and stock feedback dispatch."""
import io
import contextlib
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture
from gui.mods.offline_lan_0922 import vehicle_stack, vehicle_physics as vp


class ContactDecisionTests(unittest.TestCase):
    def test_captured_mixed_plane_cannot_erase_a_native_roof_impact(self):
        velocity=(.7094615481,-17.5656679792,-4.5255149667)
        fitted=(-.4934372689,.6686189170,-.5562988455)
        self.assertLess(vp.landing_impact_speed(velocity,fitted),vp.FALL_SAFE_SPEED)
        hit=vehicle_stack.contact_impact([dict(carrier=['bot',28],
            point=(0.,0.,0.),normal=(0.,1.,0.))],velocity)
        self.assertAlmostEqual(17.5656679792,hit['speed'])
        self.assertGreater(vp.fall_damage(1000,hit['speed']),0)

    def test_only_final_geometric_contacts_may_supply_an_impact_face(self):
        params=dict(springs=[dict(x=1.,z=1.,static_compression=.2,side='left')],
                    pseudo_contacts=[])
        state=dict(height=0.,pitch=0.,roll=0.)
        admitted=dict(carrier=['bot',28],point=(1.,0.,1.),normal=(0.,1.,0.))
        rejected=dict(carrier=['bot',29],point=(1.,2.,1.),normal=(0.,1.,0.))
        selected=vehicle_stack.contact_surfaces(params,[0.],[],state,(0.,0.,0.),
            0.,0.,0.,[rejected,admitted])
        self.assertEqual([admitted],selected)
        self.assertEqual([],vehicle_stack.contact_surfaces(params,[-1.],[],state,
            (0.,0.,0.),0.,0.,0.,[admitted]))
        self.assertIsNone(vehicle_stack.contact_impact([], (0.,-20.,0.)))

    def test_landing_queue_uses_admitted_contact_not_last_probe(self):
        battle=fixture.BattleRuntime(fixture._runtime())
        battle._stack_context=dict(actor={'_stack_carrier':['bot',29]},
            contact_carrier=['bot',28],impact_carrier=['bot',27])
        entity=types.SimpleNamespace(typeDescriptor=types.SimpleNamespace(maxHealth=1000))
        battle._apply_fall_damage(entity,20.)
        self.assertEqual(['bot',27],battle._pending_landing_impacts[0]['vehicle_contact'])

    def test_bot_admitted_body_contact_does_not_require_origin_near_roof(self):
        battle=fixture.BattleRuntime(fixture._runtime())
        battle.client=types.SimpleNamespace(round_id=1,authority_epoch=1)
        actor=dict(id=11,x=0.,y=0.,z=0.,yaw=0.,mass=36000.)
        lower=dict(id=28,alive=True,max_health=1000)
        entity=types.SimpleNamespace(typeDescriptor=types.SimpleNamespace(maxHealth=1000))
        surface=dict(carrier=['bot',28],point=(0.,-1.5,0.),normal=(0.,1.,0.))
        battle._stack_context=dict(actor=actor,surfaces=[surface],
            hits=[(('bot',28),lower,surface['point'])],candidates=[(('bot',28),lower,entity)])
        params=dict(springs=[dict(x=0.,y=-1.5,z=0.,static_compression=.2,side='left')],
            pseudo_contacts=[])
        with contextlib.redirect_stdout(io.StringIO()):
            impact=battle._bot_stack_impact_contact(actor,params,[-1.5],[],
                dict(height=0.,pitch=0.,roll=0.,impact_speed=-20.,airborne=False),
                (0.,0.),(0.,-20.,0.),True,-20.,.05)
            self.assertEqual(20.,impact['speed'])
            with mock.patch.object(vp,'descriptor_mass',return_value=36000.):
                self.assertTrue(battle._bot_stack_impact(actor,20.,300))
        row=battle._stack_publication()[0]
        self.assertEqual((['bot',28],300),(row['lower'],row['lower_total']))

    def test_captured_horizontal_travel_cannot_cancel_or_create_gravity_damage(self):
        normal=(.6119097471,.6520100236,.4477156401)
        miss=vehicle_stack.contact_impact([dict(carrier=['bot',27],point=(0.,0.,0.),
            normal=normal)],(21.5953683331,-18.1495018132,-17.7363105315))
        self.assertGreater(miss['speed'],vp.FALL_SAFE_SPEED)
        self.assertAlmostEqual(18.1495018132*normal[1],miss['speed'],places=5)
        repeat=vehicle_stack.contact_impact([dict(carrier=['bot',6],point=(0.,0.,0.),
            normal=(-.41382095,.87457359,.25273156))],
            (20.1686531,-.33172475,-11.87789477))
        self.assertLess(repeat['speed'],1.)
        self.assertEqual(0,vp.fall_damage(7500,repeat['speed']))

    def test_unspent_descent_accepts_later_impulse_after_early_contact(self):
        book=vehicle_stack.Descent()
        first=dict(impact_speed=-18.,vertical_velocity=-18.,airborne=False)
        book.observe(True,-18.,first,.02)
        self.assertEqual('safe_vertical_closing',book.verdict(['bot',27],9.,True,.02))
        later=dict(impact_speed=-18.3,vertical_velocity=-9.,airborne=False)
        book.observe(False,-18.,later,.02)
        self.assertIsNone(vp.suspension_impact_velocity(False,-18.,later))
        self.assertEqual('admit',book.verdict(['bot',27],18.3,False,.02))
        book.commit(['bot',27])
        self.assertEqual('already_charged_this_descent',book.verdict(['bot',27],18.3,False,.02))
        # A different actual lower hull still owns its own first impact.
        self.assertEqual('admit',book.verdict(['bot',28],18.3,False,.02))

    def test_zero_or_missing_solver_impulse_cannot_reintroduce_horizontal_crush(self):
        for raw in (0.,None):
            with self.subTest(raw=raw):
                battle=fixture.BattleRuntime(fixture._runtime())
                actor=dict(id=11,x=0.,y=0.,z=0.,yaw=0.)
                surface=dict(carrier=['bot',28],point=(0.,0.,0.),normal=(-.6,.8,0.))
                battle._stack_context=dict(actor=actor,hits=[],surfaces=[surface])
                params=dict(springs=[dict(x=0.,z=0.,static_compression=.2,side='left')],pseudo_contacts=[])
                with contextlib.redirect_stdout(io.StringIO()):
                    result=battle._bot_stack_impact_contact(actor,params,[0.],[],
                        dict(height=0.,pitch=0.,roll=0.,impact_speed=raw,airborne=False),
                        (0.,0.),(30.,0. if raw==0. else -.1,0.),True,-.1,.05)
                self.assertIsNotNone(result)
                self.assertEqual(0.,result['speed'])
                self.assertEqual('safe_vertical_closing',result['verdict'])

    def test_real_new_fall_rearms_but_zero_time_settle_does_not(self):
        book=vehicle_stack.Descent()
        book.observe(True,-20.,dict(impact_speed=-20.,airborne=False),.05)
        book.commit(['bot',6])
        sequence=book.sequence
        book.observe(True,-20.,dict(impact_speed=-20.,airborne=False),0.)
        self.assertEqual(sequence,book.sequence)
        self.assertEqual('zero_elapsed_time',book.verdict(['bot',6],20.,True,0.))
        book.observe(False,0.,dict(impact_speed=None,airborne=False),.05)
        book.observe(True,-20.,dict(impact_speed=-20.,airborne=False),.05)
        self.assertEqual(sequence+1,book.sequence)
        self.assertEqual('admit',book.verdict(['bot',6],20.,True,.05))

    def test_player_deferred_roof_impact_is_queued_once_after_early_safe_touch(self):
        battle=fixture.BattleRuntime(fixture._runtime())
        battle._local_fall_armed=battle._local_airborne=True
        battle._local_vertical_speed=-18.
        battle._local_support_motion_pose=(0.,0.,0.)
        entity=fixture._Vehicle(10,fixture._suspension_descriptor(),fixture._Vector(),
                                (0,0,0),{'health':500})
        normal=[math.sqrt(1.-.51**2),.51,0.]
        def ground(x,z,*args,**kwargs):
            context=battle._stack_context
            context['hits'].append((('bot',27),{},(x,0.,z)))
            context.setdefault('surfaces',[]).append(dict(carrier=['bot',27],
                point=(x,0.,z),normal=tuple(normal)))
            return 0.
        battle._suspension_ground_y=ground
        queued=[]
        def commit(entity,speed,normal_impact=False):
            if speed>vp.FALL_SAFE_SPEED:
                queued.append(speed)
                return 100
            return 0
        battle._apply_landing_impact=commit
        solved=dict(height=0.,vertical_velocity=-18.,pitch=0.,roll=0.,
            pitch_velocity=0.,roll_velocity=0.,contact_count=10,airborne=False,
            left_flying=False,right_flying=False,impact_speed=-18.)
        with mock.patch.object(vp,'damper_suspension_step',return_value=solved), \
                contextlib.redirect_stdout(io.StringIO()):
            battle._update_vertical_motion(entity,(0.,0.,0.),0.,.02)
            self.assertEqual([],queued)
            normal[:]=(0.,1.,0.)
            battle._update_vertical_motion(entity,(0.,0.,0.),0.,.02)
            self.assertEqual([18.],queued)
            battle._update_vertical_motion(entity,(0.,0.,0.),0.,.02)
            self.assertEqual([18.],queued)

    def test_bot_vertical_cost_is_aggregated_and_context_restored_on_error(self):
        for failure in (False,True):
            with self.subTest(failure=failure):
                battle=fixture.BattleRuntime(fixture._runtime())
                battle.client=types.SimpleNamespace(round_id=1,authority_epoch=1)
                battle._stack_candidates=lambda actor:[]
                state=dict(id=11,x=0.,y=1.,z=0.)
                previous={'outer':True}
                battle._stack_context=previous
                def step(*args):
                    battle._stack_context['queries'].call('roof',lambda:True)
                    if failure:raise ValueError('sample-failure')
                    return False
                bot=types.SimpleNamespace(support_context=battle._stack_support_context,
                    _update_vertical_motion_impl=step)
                if failure:
                    with self.assertRaisesRegex(ValueError,'sample-failure'):
                        fixture.bot_runtime.BotRuntime._update_vertical_motion(bot,state,.05)
                else:
                    self.assertFalse(fixture.bot_runtime.BotRuntime._update_vertical_motion(bot,state,.05))
                self.assertIs(previous,battle._stack_context)
                profile=battle._support_profiles[('bot',11)]
                self.assertEqual(1,profile['contexts'])
                self.assertEqual(1,profile['calls']['roof'])
                self.assertEqual(1,profile['calls']['context_bot_vertical'])
                self.assertAlmostEqual(.05,profile['physics_dt'])
                self.assertAlmostEqual(profile['ms']['context_total'],profile['ms']['bot_vertical_context'])
                self.assertGreaterEqual(profile['ms']['context_total'],profile['ms']['roof'])

    def test_worker_uses_tilted_spring_at_its_actual_height_and_position(self):
        battle=fixture.BattleRuntime(fixture._runtime())
        battle.client=types.SimpleNamespace(round_id=1)
        actor=dict(id=1,kind='player',x=0.,y=2.,z=0.,yaw=0.,pitch=0.,roll=.3)
        params=dict(springs=[dict(x=1.,z=1.,static_compression=.2,side='left')],
                    pseudo_contacts=[])
        entity=types.SimpleNamespace(typeDescriptor=object())
        lower=dict(id=28,alive=True)
        battle._stack_context=dict(actor=actor,hits=[],candidates=[])
        x,z=math.cos(.3),1.
        roof_y=2.+math.sin(.3)-.1
        calls=[]
        def native(start,end,ground):
            calls.append((start.y,end.y))
            self.assertAlmostEqual(x,start.x)
            self.assertAlmostEqual(z,start.z)
            if end.y<=roof_y<=start.y:
                battle._stack_context['hits'].append((('bot',28),lower,(x,roof_y,z)))
                return (fixture._Vector(x,roof_y,z),fixture._Vector(0.,1.,0.))
        battle._stack_ground_hit=native
        with mock.patch.object(vp,'suspension_trial_excluded',return_value=False), \
                mock.patch.object(vp,'derive_suspension_params',return_value=params) as derive:
            with contextlib.redirect_stdout(io.StringIO()):
                hit=battle._stack_pressure_contact(actor,entity)
                self.assertEqual(('bot',28),hit[0])
                battle._stack_pressure_contact(actor,entity)
            self.assertEqual(1,derive.call_count)
        # The old origin-height short ray could never reach this roof.
        self.assertGreater(roof_y,actor['y']+.15)
        self.assertEqual(2.,actor['y'])
        self.assertEqual(2,len(calls))

    def test_runtime_prefers_native_face_over_fitted_plane(self):
        runtime=fixture._runtime()
        battle=fixture.BattleRuntime(runtime)
        battle._avatar=runtime.bigworld.avatar
        battle._local_fall_armed=battle._local_airborne=True
        battle._local_vertical_speed=-17.5656679792
        battle._local_support_motion_pose=(0.,0.,0.)
        entity=fixture._Vehicle(10,fixture._suspension_descriptor(),fixture._Vector(),
                                (0,0,0),{'health':500})
        lower=dict(id=28)
        def ground(x,z,*args,**kwargs):
            context=battle._stack_context
            context['hits'].append((('bot',28),lower,(x,0.,z)))
            context.setdefault('surfaces',[]).append(dict(carrier=['bot',28],
                point=(x,0.,z),normal=(0.,1.,0.)))
            return 0.
        battle._suspension_ground_y=ground
        battle._apply_landing_impact=mock.Mock(return_value=0)
        solved=dict(height=0.,vertical_velocity=0.,pitch=0.,roll=0.,
            pitch_velocity=0.,roll_velocity=0.,contact_count=10,airborne=False,
            left_flying=False,right_flying=False,impact_speed=-17.5656679792)
        plane=dict(normal=(-.4934372689,.6686189170,-.5562988455),
                   gradient_x=.738,gradient_z=.832,center_y=0.,center_x=0.,center_z=0.)
        with mock.patch.object(vp,'damper_suspension_step',return_value=solved), \
                mock.patch.object(vp,'suspension_world_ground_plane',return_value=plane), \
                contextlib.redirect_stdout(io.StringIO()):
            battle._update_vertical_motion(entity,(.041148,0.,-.262474),0.,.058)
        self.assertAlmostEqual(17.5656679792,battle._apply_landing_impact.call_args[0][1])


class DeferredBotImpactTests(unittest.TestCase):
    def scene(self, accepted=True, deferred=True, damage=300):
        battle=fixture.BattleRuntime(fixture._runtime())
        book=vehicle_stack.Descent()
        book.observe(True,-18.,dict(impact_speed=-18.,airborne=False),.05)
        battle._stack_context=dict(impact_descent=book,
            impact_decision=dict(verdict='admit',carrier=['bot',27],
                                 descent=book.sequence,speed=18.))
        state=dict(id=11,alive=True,x=0.,y=0.,z=0.,yaw=0.)
        paid=[]
        def spend(actor,speed):
            paid.append(speed)
            return damage
        bot=types.SimpleNamespace(_turret_motion_probe=(lambda *args:accepted) if deferred else None,
            _turret_pending_landing_impacts=None,
            _turret_state_pose=lambda s:dict(s),
            _snapshot_bot_suspension_state=lambda s:dict(s),
            _restore_bot_suspension_state=lambda s,snapshot:s.update(snapshot),
            _descriptors={11:{}},_turn_speeds={},round_id=1,
            _invalidate_realised_motion=lambda *args:None,
            _release_detailed_support=lambda s:None,
            _apply_bot_fall_damage=spend,stack_impact_commit=battle._commit_stack_impact)
        bot._apply_bot_landing_impact=types.MethodType(
            fixture.bot_runtime.BotRuntime._apply_bot_landing_impact,bot)
        def integrate(s,*args):
            bot._apply_bot_landing_impact(s,18.,True)
            if deferred:
                self.assertEqual([],paid)
                self.assertEqual('admit',book.verdict(['bot',27],18.,True,.05))
            return False
        bot._integrate_vertical_motion=integrate
        return bot,state,book,paid

    def test_deferred_and_immediate_damage_commit_once_after_hp_spend(self):
        for deferred in (False,True):
            with self.subTest(deferred=deferred),contextlib.redirect_stdout(io.StringIO()):
                bot,state,book,paid=self.scene(deferred=deferred)
                fixture.bot_runtime.BotRuntime._update_vertical_motion_impl(bot,state,.05)
                self.assertEqual([18.],paid)
                self.assertEqual('already_charged_this_descent',
                                 book.verdict(['bot',27],18.,True,.05))
                self.assertEqual({('bot',27)},book.charged)

    def test_rejected_pose_discards_damage_and_dedup_commit(self):
        bot,state,book,paid=self.scene(accepted=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(fixture.bot_runtime.BotRuntime._update_vertical_motion_impl(bot,state,.05))
        self.assertEqual([],paid)
        self.assertEqual('admit',book.verdict(['bot',27],18.,True,.05))

    def test_zero_damage_does_not_consume_later_valid_impact(self):
        bot,state,book,paid=self.scene(damage=0)
        fixture.bot_runtime.BotRuntime._update_vertical_motion_impl(bot,state,.05)
        self.assertEqual([18.],paid)
        self.assertEqual('admit',book.verdict(['bot',27],18.,True,.05))


class StockFeedbackEntryTests(unittest.TestCase):
    def test_ram_dispatch_preserves_shared_panel_methods_and_bound_callbacks(self):
        class Panel:
            def _addRibbon(self,*args):pass
            def _updateRibbon(self,*args):pass
            def onShow(self):return 'stock-show'
            def onChange(self):return 'stock-change'
            def onHide(self,ribbonID):return ribbonID
            def _dispose(self):pass
        name='gui.Scaleform.daapi.view.battle.shared.ribbons_panel'
        panel=Panel()
        original=dict(Panel.__dict__)
        bound_show,bound_hide=panel.onShow,panel.onHide
        runtime=fixture._runtime()
        battle=fixture.BattleRuntime(runtime)
        battle._avatar=runtime.bigworld.avatar
        battle._avatar.playerVehicleID=10
        battle._synchronise_player_identity(10)
        local=dict(engine_id=10,local=True,kind='player',network_id=1,state=dict(team=1))
        enemy=dict(engine_id=11,local=False,kind='bot',network_id=2,state=dict(team=2))
        module=types.ModuleType(name)
        module.BattleRibbonsPanel=Panel
        constants_name='gui.Scaleform.genConsts.BATTLE_EFFICIENCY_TYPES'
        constants=types.ModuleType(constants_name)
        constants.BATTLE_EFFICIENCY_TYPES=types.SimpleNamespace(RAM='ram',RECEIVED_RAM='receivedRam')
        with mock.patch.dict('sys.modules',{name:module,constants_name:constants}),contextlib.redirect_stdout(io.StringIO()):
            for target,attacker in ((enemy,local),(local,enemy)):
                self.assertTrue(battle._present_combat_feedback(dict(
                    event_id='1:1:0',source='ram',attack_reason=2,damage=100,dead=False),
                    target,attacker))
        self.assertEqual(2,len(battle._avatar.battle_events))
        self.assertEqual(original,dict(Panel.__dict__))
        self.assertEqual('stock-show',bound_show())
        self.assertEqual(7,bound_hide(7))


if __name__=='__main__':unittest.main()
