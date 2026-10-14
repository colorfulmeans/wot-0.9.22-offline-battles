"""Environmental damage is location-owned, source-specific and retry-safe."""
import contextlib
import io
import types
import unittest
from unittest import mock
import test_port_0922_critical_damage as fixtures
import test_port_0922_server_projectiles as server_fixture
import test_port_0922_lan_client_projectiles as wire_fixture
from gui.mods.offline_lan_0922 import environment_modules as em
from gui.mods.offline_lan_0922 import critical_damage as cd
from gui.mods.offline_lan_0922 import device_damage as dd
from gui.mods.offline_lan_0922 import player_critical_mechanics as pcm


class EnvironmentalModulesTests(unittest.TestCase):
    def target(self, pools=None):
        td=fixtures._strict_1513_descriptor()
        return types.SimpleNamespace(id=1,health=1000,maxHealth=1000,typeDescriptor=td,
            devices_hp=dict(pools or {}),_destroyed_devices=set(),_critical_devices=set(),
            _crew_ko=set(),is_on_fire=True,_fire_started=0.,_fire_timer=0.,
            _offline_proposal_only=True,_ammo_rack_death=False)

    def test_fire_reduces_only_internal_module_pools_and_never_crew(self):
        v=self.target()
        with contextlib.redirect_stdout(io.StringIO()):
            damage,payload=cd.tick_fire(v,1.,now=1.)
        self.assertEqual(50,damage)
        for name in em.FIRE_DEVICES:
            self.assertEqual(dd.device_max_hp(v.typeDescriptor,name)-10.,v.devices_hp[name])
        for name in ('leftTrackHealth','rightTrackHealth','gunHealth','surveyingDeviceHealth'):
            self.assertNotIn(name,v.devices_hp)
        self.assertEqual(set(),v._crew_ko)
        self.assertIsNotNone(payload)

    def test_fire_and_landing_can_detonate_a_depleted_ammo_rack(self):
        for fire in (True,False):
            v=self.target({'ammoBayHealth':5.})
            with contextlib.redirect_stdout(io.StringIO()):
                if fire: damage,payload=cd.tick_fire(v,1.,now=1.)
                else: damage,payload=em.apply_impact(v,20.,[dict(name='ammoBayHealth',weight=1.)])
            self.assertEqual(v.health,damage)
            self.assertTrue(v._ammo_rack_death)
            self.assertEqual(0.,v.devices_hp['ammoBayHealth'])
            self.assertTrue(payload['ammo_rack_death'])

    def test_slow_frame_stops_module_burning_at_the_first_terminal_tick(self):
        v=self.target({'ammoBayHealth':5.})
        with contextlib.redirect_stdout(io.StringIO()):
            damage,payload=cd.tick_fire(v,5.,now=5.)
        self.assertEqual(1000,damage)
        self.assertNotIn('engineHealth',v.devices_hp)

    def test_module_test_mode_keeps_existing_ammo_detonation_protection(self):
        v=self.target({'ammoBayHealth':5.})
        with contextlib.redirect_stdout(io.StringIO()):
            damage,payload=cd.tick_fire(v,1.,now=1.,module_test_mode=True)
        self.assertEqual(0,damage)
        self.assertFalse(v._ammo_rack_death)
        self.assertEqual(0.,v.devices_hp['ammoBayHealth'])

    def test_impact_only_damages_reached_external_internal_and_crew_targets(self):
        v=self.target()
        with contextlib.redirect_stdout(io.StringIO()):
            unused,payload=em.apply_impact(v,20.,[
                dict(name='leftTrackHealth',weight=1.),dict(name='engineHealth',weight=.25),
                dict(name='driverHealth',weight=1.)])
        self.assertEqual(0.,v.devices_hp['leftTrackHealth'])
        self.assertEqual(75.,v.devices_hp['engineHealth'])
        self.assertEqual({'driver'},v._crew_ko)
        self.assertNotIn('ammoBayHealth',v.devices_hp)
        self.assertNotIn('rightTrackHealth',v.devices_hp)
        self.assertTrue(all(e['cause']=='world_collision' for e in payload['events']))

    def test_empty_geometry_and_safe_landing_have_no_module_loss(self):
        for speed,contacts in ((20.,[]),(9.,[dict(name='leftTrackHealth',weight=1.)])):
            v=self.target()
            with contextlib.redirect_stdout(io.StringIO()):
                damage,payload=em.apply_impact(v,speed,contacts)
            self.assertEqual(0,damage)
            self.assertIsNone(payload)
            self.assertEqual({},v.devices_hp)

    def test_multiple_witnesses_do_not_damage_one_module_multiple_times(self):
        v=self.target()
        contacts=[dict(name='engineHealth',weight=.25),dict(name='engineHealth',weight=.5)]
        with contextlib.redirect_stdout(io.StringIO()):em.apply_impact(v,12.,contacts)
        self.assertEqual(120.,v.devices_hp['engineHealth'])

    def test_known_contact_position_drives_native_and_interior_queries(self):
        v=self.target();v.matrix=object()
        math_module=types.SimpleNamespace(Vector3=fixtures._Point)
        def internal(vehicle,td,start,end):
            return [(0.5,'driverHealth')] if start.x>0 else [(0.5,'engineHealth')]
        def external(vehicle,matrix,start,end,math,**kwargs):
            return [(0.,1.,fixtures._Material('rightTrackHealth' if start.x>0 else 'leftTrackHealth'),'vehicleChassis')]
        with mock.patch('gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',side_effect=external), \
             mock.patch.object(cd,'_offh_internal_ray_hits',side_effect=internal), \
             contextlib.redirect_stdout(io.StringIO()):
            left=em.collect_contacts(v,[(-1.,0.,0.)],(0.,1.,0.),20.,math_module)
            right=em.collect_contacts(v,[(1.,0.,0.)],(0.,1.,0.),20.,math_module)
        self.assertEqual({'leftTrackHealth','engineHealth'},{r['name'] for r in left})
        self.assertEqual({'rightTrackHealth','driverHealth'},{r['name'] for r in right})

    def test_recorded_bridge_driver_contact_now_exceeds_injury_threshold(self):
        v=self.target();v.matrix=object()
        with mock.patch('gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',return_value=[]), \
             mock.patch.object(cd,'_offh_internal_ray_hits',return_value=[(.833336323389437,'driverHealth')]), \
             contextlib.redirect_stdout(io.StringIO()):
            contacts=em.collect_contacts(v,[(32.54449438730874,-14.857442855834961,74.96820962987717)],
                (0.,1.,0.),16.74883017251508,types.SimpleNamespace(Vector3=fixtures._Point))
            em.apply_impact(v,16.74883017251508,contacts)
        self.assertEqual({'driver'},v._crew_ko)
        self.assertEqual(1,len(contacts))

    def test_shock_reaches_deep_and_lateral_modules_without_global_damage(self):
        v=self.target();v.matrix=object();ends=[]
        def internal(vehicle,td,start,end):
            ends.append((end.x,end.y,end.z))
            hits=[(.833336323389437,'driverHealth')]
            if end.y>3.:hits.append((3.,'engineHealth'))
            if end.x>1.:hits.append((2.5,'radioHealth'))
            return hits
        with mock.patch('gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',return_value=[]), \
             mock.patch.object(cd,'_offh_internal_ray_hits',side_effect=internal), \
             contextlib.redirect_stdout(io.StringIO()):
            contacts=em.collect_contacts(v,[(0.,0.,0.)],(0.,1.,0.),16.74883017251508,
                types.SimpleNamespace(Vector3=fixtures._Point))
            em.apply_impact(v,16.74883017251508,contacts)
        self.assertEqual(5,len(ends))
        self.assertAlmostEqual(4.049298103509049,ends[0][1])
        self.assertEqual({'engineHealth','radioHealth','driverHealth'},{r['name'] for r in contacts})
        self.assertAlmostEqual(150.-202.46490517545246/1.75,v.devices_hp['engineHealth'])
        self.assertNotIn('ammoBayHealth',v.devices_hp)
        self.assertNotIn('leftTrackHealth',v.devices_hp)
        self.assertEqual({'driver'},v._crew_ko)

    def test_external_query_failure_preserves_interior_shock(self):
        v=self.target();v.matrix=object()
        with mock.patch('gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',side_effect=RuntimeError('external withdrawn')), \
             mock.patch.object(cd,'_offh_internal_ray_hits',return_value=[(2.,'engineHealth')]), \
             contextlib.redirect_stdout(io.StringIO()):
            contacts=em.collect_contacts(v,[(0.,0.,0.)],(1.,0.,0.),16.75,
                types.SimpleNamespace(Vector3=fixtures._Point))
        self.assertEqual(['engineHealth'],[r['name'] for r in contacts])

    def test_missing_or_out_of_segment_geometry_does_not_nominate_modules(self):
        v=self.target();v.matrix=object()
        for hits in (None,[],[(8.,'engineHealth'),(-1.,'radioHealth'),(float('nan'),'ammoBayHealth')]):
            with mock.patch('gui.mods.offline_lan_0922.entities.remote_vehicle.collide_vehicle_at_matrix',return_value=[]), \
                 mock.patch.object(cd,'_offh_internal_ray_hits',return_value=hits), \
                 contextlib.redirect_stdout(io.StringIO()):
                contacts=em.collect_contacts(v,[(0.,0.,0.)],(0.,-1.,0.),16.75,
                    types.SimpleNamespace(Vector3=fixtures._Point))
            self.assertEqual([],contacts)

    def test_recorded_landings_have_mixed_states_with_30_coefficient(self):
        v=self.target()
        # Use the actual installed pools and contact weights from report 151604.
        component=fixtures._Strict1513Component
        v.typeDescriptor.hull=component(ammoBayHealth=component(maxHealth=203.,maxRegenHealth=101.5))
        v.typeDescriptor.fuelTank=component(maxHealth=175.,maxRegenHealth=87.5)
        v.typeDescriptor.chassis=component(maxHealth=200.,maxRegenHealth=100.)
        v.typeDescriptor.turret=component(turretRotatorHealth=component(maxHealth=140.,maxRegenHealth=70.))
        with contextlib.redirect_stdout(io.StringIO()):
            em.apply_impact(v,13.995103890736372,[
                dict(name='leftTrackHealth',weight=.9073306165998628),
                dict(name='turretRotatorHealth',weight=.6616425053204138)])
            em.apply_impact(v,13.240236440622468,[
                dict(name='ammoBayHealth',weight=.8159129621855199),
                dict(name='fuelTankHealth',weight=.8079084413649028),
                dict(name='rightTrackHealth',weight=.9891207988092617)])
        self.assertEqual({'leftTrackHealth','turretRotatorHealth'},v._critical_devices)
        # Serialized report inputs/receipts differ at roughly 1e-5 HP.
        self.assertAlmostEqual(203.-1.5*52.87501105880318,v.devices_hp['ammoBayHealth'],places=3)
        self.assertFalse(v._ammo_rack_death)

    def test_recorded_heavy_landings_can_detonate_full_ammo_at_30(self):
        for speed,weight in ((18.9940181189427,.7998457562245733),
                             (18.30258067650511,.8133127314833454)):
            v=self.target();component=fixtures._Strict1513Component
            v.typeDescriptor.hull=component(ammoBayHealth=component(maxHealth=203.,maxRegenHealth=101.5))
            with contextlib.redirect_stdout(io.StringIO()):
                damage,payload=em.apply_impact(v,speed,[dict(name='ammoBayHealth',weight=weight)])
            expected=max(0.,203.-(speed-10.)*30.*weight)
            self.assertAlmostEqual(expected,v.devices_hp['ammoBayHealth'])
            self.assertEqual(expected==0.,v._ammo_rack_death)
            self.assertEqual(v.health if expected==0. else 0,damage)

    def test_report_184752_falls_cross_only_contacted_module_thresholds(self):
        component=fixtures._Strict1513Component
        cases=((16.821033432582368, {'fuelTankHealth':(200.,.5522720059710093)}, {'fuelTankHealth'}),
               (16.356126811512986, {'engineHealth':(360.,.7967294695413109),
                'leftTrackHealth':(300.,.8729463203200343),
                'rightTrackHealth':(300.,.5631807145666561)}, {'leftTrackHealth'}))
        for speed,pools,expected_yellow in cases:
            v=self.target()
            v.typeDescriptor.fuelTank=component(maxHealth=200.,maxRegenHealth=100.)
            v.typeDescriptor.engine=component(maxHealth=360.,maxRegenHealth=180.)
            v.typeDescriptor.miscAttrs=component(engineHealthFactor=1.)
            v.typeDescriptor.chassis=component(maxHealth=300.,maxRegenHealth=150.)
            with contextlib.redirect_stdout(io.StringIO()):
                damage,payload=em.apply_impact(v,speed,[dict(name=n,weight=w) for n,(hp,w) in pools.items()])
            self.assertEqual(0,damage)
            self.assertEqual(expected_yellow,v._critical_devices)
            self.assertEqual(set(pools),set(v.devices_hp))
            for name,(maximum,weight) in pools.items():
                self.assertAlmostEqual(maximum-(speed-10.)*30.*weight,v.devices_hp[name])

    def test_fire_publication_preserves_module_event_cause(self):
        state=server_fixture._state();player=state.players[1]
        player.effective_params['critical']=pcm.project_profile(fixtures._strict_1513_descriptor())
        player.critical=dict(fire=True,devices=[dict(name='radioHealth',hp=55.,state='normal')],
            destroyed=[],crew_ko=[],ammo_rack_death=False)
        player.fire_attacker_kind='bot';player.fire_attacker_id=11
        with contextlib.redirect_stdout(io.StringIO()):state._tick_player_fire(1.)
        event=state.pending_events[-1]
        self.assertEqual('fire',event['source'])
        self.assertTrue(event['critical']['events'])
        self.assertTrue(all(r['cause']=='fire' for r in event['critical']['events']))
        self.assertEqual([],player.critical.get('events'))

    def test_ground_witnesses_choose_sampled_contact_and_void_has_none(self):
        params=dict(springs=[dict(x=-1.,y=0.,z=0.),dict(x=1.,y=0.,z=0.)],pseudo_contacts=[])
        self.assertEqual([(-1.,1.,0.)],em.ground_witnesses(params,[1.,0.],[],(0.,1.,0.),0.,0.,0.))
        self.assertEqual([],em.ground_witnesses(params,[None,None],[],(0.,1.,0.),0.,0.,0.))

    def test_invalid_contacts_are_rejected(self):
        for rows in ([dict(name='fakeHealth',weight=1.)],[dict(name='engineHealth',weight=float('nan'))],
                     [dict(name='engineHealth',weight=True)],[dict(name='engineHealth',weight=2.)]):
            with self.assertRaises(ValueError):em.normalize_contacts(rows)

    def test_server_landing_is_atomic_and_replay_never_reapplies_module_or_crew_loss(self):
        state=server_fixture._state();player=state.players[1]
        player.effective_params['critical']=pcm.project_profile(fixtures._strict_1513_descriptor())
        self.assertTrue(server_fixture._update_player_input(state,1,up_cosine=1.))
        message=dict(type='landing_observation',round_id=1,authority_epoch=state.authority_epoch,
            observation_seq=1,input_seq=player.input_seq,impact_speed=20.,module_contacts=[
                dict(name='engineHealth',weight=.25),dict(name='driverHealth',weight=1.)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(state.submit_landing_observation(1,message))
            before=(player.health,player.critical_revision,player.critical)
            self.assertTrue(state.submit_landing_observation(1,message))
        self.assertEqual(before,(player.health,player.critical_revision,player.critical))
        self.assertEqual(['driver'],player.critical['crew_ko'])
        self.assertEqual('health',state.pending_events[-1]['kind'])
        self.assertIn('critical',state.pending_events[-1])
        changed=dict(message,module_contacts=[dict(name='ammoBayHealth',weight=1.)])
        self.assertFalse(state.submit_landing_observation(1,changed))
        self.assertEqual(before,(player.health,player.critical_revision,player.critical))

    def test_bot_landing_uses_fresh_contacts_and_never_double_damages(self):
        import test_port_0922_bot_runtime as harness
        fixture=harness.BotRuntimeTests();fixture.setUp()
        try:
            runtime=fixture.runtime;runtime.battle_start(fixture.start)
            state=runtime.states[11]
            descriptor=runtime._descriptors[11]
            state['critical']={}
            state['_landing_contact_witnesses']=[(0.,0.,0.)]
            state['_landing_contact_normal']=(0.,1.,0.)
            runtime.impact_contacts_resolver=mock.Mock(return_value=[dict(name='leftTrackHealth',weight=.1)])
            with contextlib.redirect_stdout(io.StringIO()):
                runtime._apply_bot_fall_damage(state,11.)
                before=state.get('critical')
                runtime._apply_bot_fall_damage(state,11.)
            self.assertEqual(before,state.get('critical'))
            runtime.impact_contacts_resolver.assert_called_once()
            self.assertNotIn('_landing_contact_witnesses',state)
        finally:fixture.tearDown()

    def test_player_fire_and_bot_shadow_apply_the_same_internal_losses(self):
        import test_port_0922_bot_runtime as harness
        from gui.mods.offline_lan_0922 import bot_runtime
        descriptor=fixtures._strict_1513_descriptor()
        player=server_fixture._state().players[1]
        player.effective_params['critical']=pcm.project_profile(descriptor)
        player.critical=dict(fire=True,devices=[],destroyed=[],crew_ko=[],ammo_rack_death=False)
        player.combat_fire_elapsed=0.;player.combat_fire_timer=0.
        state=dict(id=16,health=player.health,max_health=player.max_health,critical=player.critical)
        shadow=bot_runtime._BotCriticalVehicle(state,descriptor,0.,0.)
        with contextlib.redirect_stdout(io.StringIO()):
            result=pcm.advance_fire(player,1.,1.)
            damage,payload=cd.tick_fire(shadow,1.,now=1.)
        self.assertEqual(damage,result['damage'])
        self.assertEqual([(r['name'],r['hp']) for r in payload['devices']],
                         [(r['name'],r['hp']) for r in result['critical']['devices']])

    def test_default_bot_landing_samples_modules_without_the_suspension_trial(self):
        import test_port_0922_bot_runtime as harness
        fixture=harness.BotRuntimeTests();fixture.setUp()
        try:
            runtime=fixture.runtime;runtime.battle_start(fixture.start)
            state=runtime.states[11]
            state.update(y=.1,vertical_speed=-20.,airborne=True,grounded_once=True,speed=0.)
            runtime._suspension_params[11]=None
            runtime._physics_ground_probe=lambda *args: 0.
            runtime.impact_contacts_resolver=mock.Mock(return_value=[dict(name='leftTrackHealth',weight=.1)])
            with contextlib.redirect_stdout(io.StringIO()):runtime._update_vertical_motion(state,.1)
            self.assertTrue(runtime.impact_contacts_resolver.called)
            self.assertTrue(any(r['name']=='leftTrackHealth' for r in state['critical']['devices']))
        finally:fixture.tearDown()

    def test_rejected_turret_pose_discards_landing_contacts_before_damage(self):
        import test_port_0922_bot_runtime as harness
        fixture=harness.BotRuntimeTests();fixture.setUp()
        try:
            runtime=fixture.runtime;runtime.battle_start(fixture.start)
            state=runtime.states[11]
            before=state['health']
            runtime.impact_contacts_resolver=mock.Mock(return_value=[dict(name='ammoBayHealth',weight=1.)])
            def landing(state,*args):
                state['y']-=1.
                state['_landing_contact_witnesses']=[(0.,0.,0.)]
                state['_landing_contact_normal']=(0.,1.,0.)
                runtime._apply_bot_landing_impact(state,20.)
                return False
            runtime._integrate_vertical_motion=landing
            runtime._turret_motion_probe=lambda *args: False
            with contextlib.redirect_stdout(io.StringIO()):runtime._update_vertical_motion(state,.1)
            self.assertEqual(before,state['health'])
            runtime.impact_contacts_resolver.assert_not_called()
            self.assertNotIn('_landing_contact_witnesses',state)
        finally:fixture.tearDown()

    def test_client_queue_and_retry_preserve_each_impacts_geometry_contacts(self):
        fixture=wire_fixture.ProjectileWireTests();client=fixture.active_client()
        self.assertTrue(fixture.send_player_input(client))
        a=[dict(name='leftTrackHealth',weight=1.)];b=[dict(name='engineHealth',weight=.3)]
        self.assertEqual(1,client.send_landing_observation(20.,a))
        self.assertEqual(a,wire_fixture.wire_copy(client._outbound_queue[-1][1])['module_contacts'])
        self.assertTrue(fixture.send_player_input(client))
        self.assertEqual(1,client.send_landing_observation(22.,b))
        self.assertTrue(client._handle_landing_observation_result(dict(type='landing_observation_result',
            round_id=3,authority_epoch=4,observation_seq=1,input_seq=1,committed_seq=1,accepted=True,reason='')))
        self.assertEqual(b,wire_fixture.wire_copy(client._outbound_queue[-1][1])['module_contacts'])


if __name__=='__main__':unittest.main()
