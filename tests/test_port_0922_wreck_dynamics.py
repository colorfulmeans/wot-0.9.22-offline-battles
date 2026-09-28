"""Report 143607: off-centre wreck impulses, cliff release and powered shoves."""
import copy
import math
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bt
import test_port_0922_battle_runtime as vt
from test_port_0922_tank_collision import tank_collision as c, _tank
from test_port_0922_tank_contact_ledger import ledger, bot_state_codec


class AngularContactTests(unittest.TestCase):
    def test_a_powered_corner_delivers_wreck_torque_at_its_real_lever(self):
        a = _tank(1, 0., 0., mass=100575.)
        b = _tank(2, 2.99, 1., mass=23496.)
        a.update(traverse_speed=1., traverse_torque=500000.)
        b['alive'] = False
        solved = c.resolve_pairs([a,b], .1)
        c.traverse_impulses(c.post_contact_velocity_bodies([a,b],solved),
                            .1, angular_results=solved)
        self.assertNotEqual(0.,solved[2]['delta_yaw'])

    def test_worker_state_uses_its_mounted_shape_for_the_same_inertia(self):
        state = dict(alive=False,mass=32000.,collision_shape=(1.3,2.9,0.,2.))
        body = dict(alive=False,mass=32000.,shape=state['collision_shape'])
        self.assertEqual(c.wreck_yaw_inertia(body),c.wreck_yaw_inertia(state))

    def test_contact_lever_rotates_in_both_directions_without_adding_energy(self):
        for offset in (-2.5, 0.0, 2.5):
            a = _tank(1, offset, -6.99, mass=100575., vz=8.)
            b = _tank(2, 0., 0., mass=23496.)
            b['alive'] = False
            inertia = c.wreck_yaw_inertia(b)
            before = .5*a['mass']*a['vz']**2
            result = c.resolve_pairs([a,b], .02)
            self.assertAlmostEqual(0., sum(body['mass']*result[body['id']]['delta_velocity'][1]
                                          for body in (a,b)), places=6)
            after = 0.
            for body in (a,b):
                dv = result[body['id']]['delta_velocity']
                after += .5*body['mass']*((body['vx']+dv[0])**2+(body['vz']+dv[1])**2)
            omega = result[2]['delta_yaw']
            after += .5*inertia*omega**2
            self.assertLessEqual(after, before+1.e-6)
            if offset:
                self.assertLess(omega*offset, 0.)
            else:
                self.assertAlmostEqual(0., omega)

    def test_angular_checkpoint_is_coalesced_retried_and_acknowledged_once(self):
        sent = {}
        ledger.record(sent, 11, (1.,2.), angular=12000.)
        first = list(sent[11])
        ledger.record(sent, 11, (3.,4.), angular=-4000.)
        latest = list(sent[11])
        self.assertEqual(8000., ledger.unseen_angular(latest, None))
        self.assertEqual(-4000., ledger.unseen_angular(latest, first))
        self.assertEqual(0., ledger.unseen_angular(first, latest))
        state = dict(id=11, push_yaw=.125, contact_push_acks=[[1]+latest[1:]])
        decoded = bot_state_codec.decode_row(bot_state_codec.encode_row(state), {})
        self.assertEqual(.125, decoded['push_yaw'])
        self.assertEqual(0., ledger.pending_angular(sent, 11, decoded['contact_push_acks'], 1))
        for bad in (float('nan'),float('inf'),True):
            with self.assertRaises((ValueError,TypeError)):
                ledger.normalize([latest[:6]+[bad]])


class WreckOwnerTests(unittest.TestCase):
    setUp = bt.ShovedWreckTests.setUp
    tearDown = bt.ShovedWreckTests.tearDown
    _runtime = bt.ShovedWreckTests._runtime
    _wreck = bt.ShovedWreckTests._wreck

    def test_visible_offcentre_collision_reaches_worker_as_the_frozen_yaw_impulse(self):
        worker=self._runtime();worker.states.pop(12)
        state=self._wreck(worker)
        state['collision_shape']=c.DEFAULT_SHAPE
        native=vt._runtime();battle=vt.BattleRuntime(native)
        battle.client=vt._Client();battle._avatar=native.bigworld.avatar
        battle._local_physics=dict(vt._effective_params_snapshot()['physics'],mass=100575.)
        local=vt._Vehicle(10,vt._Descriptor(),vt._Vector(),(0,0,0),{'health':500})
        peer=_tank(1000011,0.,0.,mass=state['mass'])
        peer.update(alive=False,kind='bot',network_id=11,physical_velocity=(0.,0.))
        battle._collision_shape=lambda unused:c.DEFAULT_SHAPE
        battle._contact_tanks=lambda *args,**kw:[peer]
        battle._motion_is_clear=lambda *args,**kw:True
        battle._baked_pose_safe=lambda *args:True
        battle._poll_local_ram_contact_episodes=lambda *args:None
        battle._local_speed=8.
        with mock.patch('sys.stdout'):
            battle._resolve_local_tank_contacts(local,(2.5,0.,-6.99),0.,.02)
            row=battle._local_contact_pushes[11]
            self.assertLess(row[6],0.)
            raw=dict(id=battle.client.player_id,tank_pushes=[row])
            # A later pose change must not rebind the accepted impulse lever.
            state['yaw']=.5
            worker._consume_human_contact_pushes([raw],1.)
            self.assertAlmostEqual(row[6]/c.wreck_yaw_inertia(state),state['push_yaw'])
            before=state['push_yaw']
            worker._consume_human_contact_pushes([raw],2.)
            self.assertEqual(before,state['push_yaw'])

    def test_repeated_offset_impulses_turn_wreck_but_world_veto_still_wins(self):
        for blocked in (False,True):
            worker = self._runtime()
            worker.states.pop(12)
            state = self._wreck(worker)
            worker._wreck_rotation_probe = mock.Mock(return_value=not blocked)
            worker._player_collision_profile = lambda raw: dict(mass=100575.,
                shape=c.DEFAULT_SHAPE,ram_profile={},physics=worker._physics_params_for(11))
            sent = {}
            inertia = c.wreck_yaw_inertia(state)
            with mock.patch('sys.stdout'):
                for i in range(2):
                    before = state['yaw']
                    ledger.record(sent, 11, (0.,0.), angular=inertia*2.)
                    raw=dict(id=1,x=100.,y=0.,z=100.,yaw=0.,speed=0.,
                             tank_pushes=list(sent.values()))
                    worker._resolve_tank_contacts([raw], i*2., .1)
                    self.assertEqual([[1]+sent[11][1:]],state['contact_push_acks'])
                    if blocked:
                        self.assertEqual(before,state['yaw'])
                    else:
                        self.assertGreater(state['yaw'],before)
                    for j in range(50):
                        worker._resolve_tank_contacts([raw],i*2.+j*.02,.02)
                    self.assertEqual(0.,state['push_yaw'])
            self.assertTrue(worker._wreck_rotation_probe.called)

    def test_departed_wreck_falls_and_lands_after_horizontal_momentum_stops(self):
        worker=self._runtime(ground=-8.)
        worker.states.pop(12)
        state=self._wreck(worker)
        worker._apply_wreck_contact_response(state,dict(delta_velocity=(0.,2.),correction=(0.,0.)),.1)
        self.assertTrue(state['airborne'])
        state['push_x']=state['push_z']=0.
        previous=state['y']
        for i in range(120):
            worker._resolve_tank_contacts([],i*.02,.02)
            self.assertLessEqual(state['y'],previous)
            self.assertEqual(0,state['health'])
            self.assertFalse(state['alive'])
            previous=state['y']
        self.assertEqual(-8.,state['y'])
        self.assertFalse(state['airborne'])

    def test_airborne_wreck_keeps_horizontal_momentum_without_ground_friction(self):
        worker=self._runtime(ground=-100.)
        worker.states.pop(12)
        state=self._wreck(worker)
        state.update(airborne=True, push_z=2.,push_yaw=.3)
        worker._apply_wreck_contact_response(state,dict(delta_velocity=(0.,0.),correction=(0.,0.)),.1)
        self.assertEqual(2.,state['push_z'])
        self.assertEqual(.3,state['push_yaw'])
        self.assertAlmostEqual(.03,state['yaw'])

    def test_ten_spring_wreck_tips_off_supported_edge(self):
        # Use the same descriptor/spring adapter as the live cliff regression.
        worker,state,unused=bt.BotRuntimeTests._suspension_case(self,lambda x,z: 0. if z<=0. else -8.)
        worker.states={state['id']:state}
        state.update(x=0.,y=0.,z=-4.,alive=False,health=0,grounded_once=True,
                     mass=25000.,collision_shape=c.DEFAULT_SHAPE)
        idle=dict(delta_velocity=(0.,0.),correction=(0.,0.))
        for i in range(120):worker._apply_wreck_contact_response(state,idle,.02)
        departed=False
        for i in range(120):
            worker._apply_wreck_contact_response(state,dict(delta_velocity=(0.,.5),correction=(0.,0.)),.02)
            if state['airborne']:
                departed=True
                break
        self.assertTrue(departed)
        self.assertGreater(state['z'],-4.)
        self.assertLess(state['y'],0.)


class HeadOnOwnerTests(unittest.TestCase):
    setUp = bt.ShovedWreckTests.setUp
    tearDown = bt.ShovedWreckTests.tearDown
    _runtime = bt.ShovedWreckTests._runtime

    def travel(self, human_mass, human_hp, bot_mass, bot_hp, hz):
        worker=self._runtime()
        worker.states.pop(12)
        state=worker.states[11]
        state.update(x=0.,y=0.,z=6.99,yaw=math.pi,speed=0.,mass=bot_mass,
                     pitch=0.,roll=0.,push_x=0.,push_z=0.,grounded_once=True,
                     collision_shape=c.DEFAULT_SHAPE,movement_dir=1)
        params=worker._physics_params_for(11)
        params.update(mass=bot_mass,powerW=bot_hp*735.49875)
        human_params=dict(params,mass=human_mass,powerW=human_hp*735.49875)
        worker._player_collision_profile=lambda raw:dict(mass=human_mass,
                shape=c.DEFAULT_SHAPE,ram_profile={},physics=human_params)
        native=vt._runtime();battle=vt.BattleRuntime(native)
        battle.client=vt._Client();battle._avatar=native.bigworld.avatar
        battle._local_physics=human_params
        local=vt._Vehicle(10,vt._Descriptor(),vt._Vector(),(0,0,0),{'health':500})
        battle._collision_shape=lambda unused:c.DEFAULT_SHAPE
        battle._motion_is_clear=lambda *args,**kw:True
        battle._baked_pose_safe=lambda *args:True
        battle._poll_local_ram_contact_episodes=lambda *args:None
        published=copy.deepcopy(state)
        def others(*args,**kw):
            pending=ledger.pending(battle._local_contact_pushes,11,published.get('contact_push_acks'),battle.client.player_id)
            peer=_tank(1000011,0.,published['z'],yaw=math.pi,mass=bot_mass,
                       vz=-published['speed']+published.get('push_z',0.)+pending[1]/bot_mass)
            peer.update(kind='bot',network_id=11,physical_velocity=(0.,peer['vz']),
                        contact_decel=self.module.vehicle_physics.contact_push_decel(params,True))
            return [peer]
        battle._contact_tanks=others
        position=(0.,0.,0.);dt=1./hz;bank=0.
        with mock.patch('sys.stdout'):
            for tick in range(hz*6):
                battle._local_speed=self.module.vehicle_physics.longitudinal_step(
                    human_params,battle._local_speed,1,False,0.,dt)
                start=position
                position=battle._resolve_local_tank_contacts(local,
                    (0.,0.,position[2]+battle._local_speed*dt),0.,dt,start_position=start)
                bank+=dt
                if bank+1.e-9>=.1:
                    raw=dict(id=battle.client.player_id,team=1,x=0.,y=0.,z=position[2],
                             yaw=0.,speed=battle._local_speed,forward=1,
                             tank_pushes=copy.deepcopy(list(battle._local_contact_pushes.values())))
                    worker._consume_human_contact_pushes([raw],tick*dt)
                    state['speed']=self.module.vehicle_physics.longitudinal_step(
                        params,state['speed'],1,False,0.,bank)
                    before=(state['x'],state['y'],state['z'])
                    state['z']-=state['speed']*bank
                    worker._guard_tank_translations([raw],{11:before})
                    worker._resolve_tank_contacts([raw],tick*dt,bank)
                    published=copy.deepcopy(state);bank=0.
        return state['z']-6.99

    def test_kv5_outpushes_su100m1_with_either_player_owner(self):
        for hz in (30,60,144):
            with self.subTest(hz=hz):
                self.assertGreater(self.travel(100575.,1200.,32000.,520.,hz),1.)
                self.assertLess(self.travel(32000.,520.,100575.,1200.,hz),-1.)

    def test_same_mass_with_weaker_engine_cannot_gain_the_same_push(self):
        strong=self.travel(100575.,1200.,32000.,520.,60)
        weak=self.travel(100575.,100.,32000.,520.,60)
        self.assertGreater(strong,weak)


if __name__=='__main__':unittest.main()
