import unittest
from gui.mods.offline_lan_0922 import ram_tracks

class RamTrackTests(unittest.TestCase):
    def test_only_contacted_side_loses_hp_and_duplicate_contact_is_one_loss(self):
        profile={'devices':[{'name':'leftTrackHealth','max_hp':200.}, {'name':'rightTrackHealth','max_hp':200.}]}
        current={'devices':[{'name':'engineHealth','hp':120.,'max_hp':260.,'state':'critical'}],
                 'crew_ko':['driver'],'fire':False,'ammo_rack_death':False}
        result=ram_tracks.damage(current,profile,['leftTrackHealth','leftTrackHealth'],6.)
        rows={r['name']:r for r in result['devices']}
        self.assertEqual(80.,rows['leftTrackHealth']['hp'])
        self.assertEqual('critical',rows['leftTrackHealth']['state'])
        self.assertNotIn('rightTrackHealth',rows)
        self.assertEqual(120.,rows['engineHealth']['hp'])
        self.assertEqual(['driver'],result['crew_ko'])
        self.assertEqual('ramming',result['events'][0]['cause'])
        self.assertEqual(1,len(current['devices']))
    def test_body_contact_missing_geometry_or_slow_push_does_not_damage_tracks(self):
        profile={'devices':[{'name':'leftTrackHealth','max_hp':200.}]}
        self.assertIsNone(ram_tracks.damage({},profile,[],20.))
        self.assertIsNone(ram_tracks.damage({},profile,['leftTrackHealth'],2.))
        self.assertIsNone(ram_tracks.damage({},None,['leftTrackHealth'],20.))
        for name in ('engineHealth','ammoBayHealth','driverHealth'):
            with self.assertRaises(ValueError):ram_tracks.damage({},profile,[name],20.)
    def test_material_metadata_reversal_retains_actor_side(self):
        pair=ram_tracks.ContactArmors((45.,80.),(('leftTrackHealth',),()))
        self.assertEqual((80.,45.),pair.reversed())
        self.assertEqual(((),('leftTrackHealth',)),pair.reversed().tracks)

    def test_native_contact_tracks_require_nearest_surface_at_witness(self):
        import math,types
        from unittest import mock
        import test_port_0922_battle_runtime as f
        battle=f.BattleRuntime(f._runtime())
        battle._collision_shape=lambda td:(1.,1.,0.,1.)
        vehicle=types.SimpleNamespace(typeDescriptor=object(),position=(0.,0.,0.))
        matrix=types.SimpleNamespace(translation=(0.,0.,0.))
        reach=math.sqrt(2.)+1.
        def hit(distance,name,df):
            return types.SimpleNamespace(dist=distance,matInfo=types.SimpleNamespace(
                armor=30.,vehicleDamageFactor=df,extra=types.SimpleNamespace(name=name)))
        for contacts,expected in (([hit(reach,'leftTrackHealth',0.),hit(reach+.2,'hull',1.)],['leftTrackHealth']),
                                  ([hit(reach,'hull',1.),hit(reach+.1,'rightTrackHealth',0.)],[]),
                                  ([hit(reach-1.,'rightTrackHealth',0.),hit(reach+.1,'hull',1.)],[]),
                                  ([hit(reach+.347,'rightTrackHealth',0.),hit(reach+.5,'hull',1.)],['rightTrackHealth']),
                                  ([hit(reach+1.1,'rightTrackHealth',0.),hit(reach+1.2,'hull',1.)],[])):
            battle._ram_contact_ray_trace=[]
            with mock.patch.object(f.battle_runtime_module,'collide_vehicle_at_matrix',return_value=contacts):
                result=battle._native_ram_vehicle_armor(vehicle,matrix,(1.,0.,0.),(-1.,0.))
            self.assertEqual(expected,result.get('contact_tracks',[]))
            ray=battle._ram_contact_ray_trace[0]
            self.assertEqual('sampled_contact_plane',ray['witness_source'])
            self.assertEqual(contacts[0].matInfo.extra.name,ray['surfaces'][0]['material'])
            self.assertAlmostEqual(abs(contacts[0].dist-reach),ray['first_surface_distance_to_witness'])

    def test_structural_height_search_preserves_native_first_skin_tracks(self):
        import math,types
        from unittest import mock
        import test_port_0922_battle_runtime as f
        battle=f.BattleRuntime(f._runtime());battle._collision_shape=lambda td:(1.,1.,0.,1.)
        first=types.SimpleNamespace(id=1,typeDescriptor=object(),position=(0.,0.,0.))
        second=types.SimpleNamespace(id=2,typeDescriptor=object(),position=(2.,0.,0.))
        a=types.SimpleNamespace(translation=f._Vector(0.,0.,0.))
        b=types.SimpleNamespace(translation=f._Vector(2.,0.,0.))
        reach=math.sqrt(2.)+1.
        def collide(vehicle,matrix,start,end,*args,**kwargs):
            low=start.y<.2
            name=('leftTrackHealth' if vehicle is first else 'rightTrackHealth') if low else 'hull'
            return [types.SimpleNamespace(dist=reach+.3,matInfo=types.SimpleNamespace(
                armor=30.,vehicleDamageFactor=0. if low else 1.,extra=types.SimpleNamespace(name=name)))]
        proof=dict(hit_point=(1.,.1,0.),contact_normal=(-1.,0.),contact_y_span=(0.,1.),
            local_vehicle=first,bot_vehicle=second,local_matrix=a,bot_matrix=b)
        with mock.patch.object(f.battle_runtime_module,'collide_vehicle_at_matrix',side_effect=collide):
            matched,unused_a,unused_b=battle._native_ram_contact_plate_pair(proof)
        self.assertIsNotNone(matched)
        self.assertGreaterEqual(matched[2],.2)
        self.assertEqual(['leftTrackHealth'],matched[0]['contact_tracks'])
        self.assertEqual(['rightTrackHealth'],matched[1]['contact_tracks'])
        self.assertEqual(30.,matched[0]['armor'])

    def test_server_ram_tracks_commit_once_and_reject_conflicting_contact_identity(self):
        import test_port_0922_server_projectiles as f
        from gui.mods.offline_lan_0922 import player_critical_mechanics as pcm
        import test_port_0922_critical_damage as critical_fixture
        state=f._state();state.bot_manifest_authority_id=f.SIMULATION_WORKER_AUTHORITY_ID
        player=state.players[1]
        player.effective_params['critical']=pcm.project_profile(critical_fixture._strict_1513_descriptor())
        state.bot_states[16]=dict(id=16,team=2,vehicle='ussr:R11_MS-1',health=1000,
            max_health=1000,alive=True,display_health=1000,x=0.,y=0.,z=0.,critical={},
            combat_revision=0,combat_base_revision=0,combat_ack_seq=0,combat_fire_elapsed=0.,combat_fire_timer=0.)
        state.bot_terminal_criticals[16]=f._terminal_critical()
        player.ram_contacts[1]={'bot_id':16}
        player.ram_contact_seq=1
        message=dict(ram_contact_player_id=1,ram_contact_seq=1,round_id=state.round_id,bot_id=16,target_kind='human',target_id=1,ram_seq=1,
            damage_to_bot=10,damage_to_target=10,track_contacts_bot=['rightTrackHealth'],
            track_contacts_target=['leftTrackHealth'],track_impact_speed=6.)
        self.assertTrue(state.report_bot_ram(f.SIMULATION_WORKER_AUTHORITY_ID,message))
        self.assertIn('leftTrackHealth',player.critical['destroyed'])
        self.assertNotIn('rightTrackHealth',player.critical['destroyed'])
        self.assertNotIn('engineHealth',[r['name'] for r in player.critical['devices']])
        before=(player.health,player.critical_revision,dict(player.critical))
        self.assertTrue(state.report_bot_ram(f.SIMULATION_WORKER_AUTHORITY_ID,message))
        self.assertEqual(before,(player.health,player.critical_revision,player.critical))
        self.assertFalse(state.report_bot_ram(f.SIMULATION_WORKER_AUTHORITY_ID,
            dict(message,track_contacts_target=['rightTrackHealth'])))
        events=[e for e in state.pending_events if e.get('source')=='ram' and 'critical' in e]
        self.assertTrue(events)
        self.assertTrue(all(r['cause']=='ramming' for e in events for r in e['critical']['events']))

    def test_player_pair_ram_commits_contacted_tracks_with_both_health_events(self):
        import test_port_0922_server_projectiles as f
        import test_port_0922_critical_damage as cf
        from gui.mods.offline_lan_0922 import player_critical_mechanics as pcm
        state=f._state();first=state.players[1];second=state.players[2]
        for player in (first,second):player.effective_params['critical']=pcm.project_profile(cf._strict_1513_descriptor())
        event=dict(damage_to_self=10,damage_to_other=12,closing_speed=6.,
            tracks_first=['leftTrackHealth'],tracks_second=['rightTrackHealth'])
        self.assertTrue(state._apply_human_ram_damage(first,second,event,(1,2),100000))
        self.assertEqual(['leftTrackHealth'],first.critical['destroyed'])
        self.assertEqual(['rightTrackHealth'],second.critical['destroyed'])
        self.assertTrue(all(e.get('critical',{}).get('events') for e in state.pending_events[-2:]))

    def test_worker_probe_projection_retains_exact_track_names_and_rejects_internal_modules(self):
        from gui.mods.offline_lan_0922.lan_client import _project_human_ram_armors
        row=dict(seq=1,first_id=1,second_id=2,available=True,armor_first=45.,armor_second=80.,
            tracks_first=['leftTrackHealth'],tracks_second=[])
        self.assertEqual([row],_project_human_ram_armors([row]))
        self.assertIsNone(_project_human_ram_armors([dict(row,tracks_first=['engineHealth'])]))
