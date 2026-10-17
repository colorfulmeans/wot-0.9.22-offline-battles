"""Contact provenance, pressure geometry and non-mutating stock UI diagnostics."""
import io
import contextlib
import math
import types
import unittest
from unittest import mock

import test_port_0922_battle_runtime as fixture
from gui.mods.offline_lan_0922 import vehicle_stack, vehicle_physics as vp
from gui.mods.offline_lan_0922.ram_feedback_diagnostics import RibbonProbe


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
                dict(height=0.,pitch=0.,roll=0.),(0.,0.),(0.,-20.,0.))
            self.assertEqual(20.,impact['speed'])
            with mock.patch.object(vp,'descriptor_mass',return_value=36000.):
                self.assertTrue(battle._bot_stack_impact(actor,20.,300))
        row=battle._stack_publication()[0]
        self.assertEqual((['bot',28],300),(row['lower'],row['lower_total']))

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


class RibbonDiagnosticsTests(unittest.TestCase):
    def scene(self):
        class Panel(object):
            def _addRibbon(self,ribbonID,ribbonType):return 'stock-add'
            def _updateRibbon(self,ribbonID,ribbonType):return 'stock-update'
            def onShow(self,ribbonID):return 'stock-show'
            def onChange(self,ribbonID):return 'stock-change'
            def onHide(self,ribbonID):return 'stock-hide'
            def _dispose(self):return 'stock-dispose'
        self.now=0.;self.logs=[]
        self.probe=RibbonProbe(Panel,('ram','receivedRam'),lambda:self.now,
            lambda event,row:self.logs.append(dict(row)),(1,1,1))
        self.addCleanup(self.probe.close)
        return Panel,Panel()

    def test_no_hide_after_last_damage_is_observable_without_forcing_it(self):
        cls,panel=self.scene()
        self.assertEqual('stock-add',panel._addRibbon(7,'receivedRam'))
        panel.onShow(7)
        self.probe.note(dict(event_id='1:2:0',damage=1,source='ram',attack_reason=2),True)
        self.now=30.
        self.probe.poll()
        row=next(r for r in self.logs if r['phase']=='no_hide_callback')
        self.assertEqual((7,30.,True),(row['ribbon'],row['age'],row['state']['shown']))
        self.assertEqual(0.,row['last_damage'])
        self.assertEqual('stock-hide',panel.onHide(7))
        self.assertEqual({},self.probe.rows)

    def test_close_restores_exact_stock_methods(self):
        cls,panel=self.scene()
        original=self.probe.methods['_addRibbon'][0]
        self.probe.close()
        self.assertIs(original,cls._addRibbon)
        self.assertEqual('stock-add',panel._addRibbon(7,'receivedRam'))

    def test_dispose_retires_only_its_panel_and_non_ram_is_ignored(self):
        cls,panel=self.scene();second=cls()
        panel._addRibbon(7,'receivedRam');second._addRibbon(7,'ram')
        panel._addRibbon(8,'damage')
        panel._dispose()
        self.assertEqual([(id(second),7)],list(self.probe.rows))

    def test_stock_exceptions_are_not_swallowed_by_observation(self):
        class Bad(object):
            def method(self,*args,**kwargs):raise ValueError('native-stock-error')
        for name in RibbonProbe.METHODS:setattr(Bad,name,Bad.method)
        logs=[]
        probe=RibbonProbe(Bad,('ram',),lambda:0.,lambda event,row:logs.append(row),(1,1,1))
        try:
            with self.assertRaisesRegex(ValueError,'native-stock-error'):
                Bad()._addRibbon(1,'ram')
            self.assertTrue(any(row['phase']=='stock_call_error' for row in logs))
        finally:probe.close()


if __name__=='__main__':unittest.main()
