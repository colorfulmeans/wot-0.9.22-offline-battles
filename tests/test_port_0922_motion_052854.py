"""Captured poses/targets from Windows367, with explicit native seams.

These tests prove geometry and lifecycle contracts, not native BSP acceptance.
"""
import json
import math
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import bot_runtime, tank_collision
from gui.mods.offline_lan_0922.ai.adapter import BotAdapter
from gui.mods.offline_lan_0922.ai.driver import LocalDriver

DATA = json.loads((Path(__file__).parent/'fixtures'/'motion_052854.json').read_text())


def own(name):
    d = DATA[name]
    return dict(position=tuple(d['final']), yaw=d['yaw'], pitch=d['pitch'],
                roll=d['roll'], collision_shape=tuple(d['shape']), id=1)


class MotionReportTests(unittest.TestCase):
    def test_chieftain_rear_sweep_uses_actual_pose_and_keeps_front_blocker(self):
        d = DATA['chieftain']; state = own('chieftain'); driver = LocalDriver()
        peers = [dict(p, half_width=p['shape'][0], half_length=p['shape'][1]) for p in d['nearby']]
        body = driver.collision_body(state)
        self.assertIsNotNone(driver._reverse_blocked_by_vehicle(state['position'], d['yaw'], peers,
            d['shape'][1], d['shape'][0], .5))
        self.assertIsNone(driver._reverse_blocked_by_vehicle(state['position'], d['yaw'], peers,
            d['shape'][1], d['shape'][0], .5, body=body))
        self.assertEqual({19,24}, {x['peer'] for x in driver._last_reverse_receipt['separated']})
        self.assertIsNotNone(driver._reverse_blocked_by_vehicle(state['position'], d['yaw']+math.pi,
            peers, d['shape'][1], d['shape'][0], .5, body=body))
        driver._reverse_blocked_by_vehicle(state['position'], d['yaw']+.2, peers,
            d['shape'][1],d['shape'][0],.5,body=body)
        self.assertFalse(driver._last_reverse_receipt['pose_refinement'])
        self.assertEqual([],driver._last_reverse_receipt['separated'])
        state['neighbours'] = peers
        self.assertIsNone(BotAdapter('31_airfield',1)._hull_contact(1,state,state['position']))

    def test_swept_certificate_does_not_skip_intermediate_or_missing_geometry(self):
        a = dict(x=0.,y=0.,z=0.,yaw=0.,pitch=0.,roll=0.,shape=(1.,2.,0.,2.))
        b = dict(a,z=-5.)
        self.assertFalse(tank_collision.swept_body_separated(a,b,(0.,0.,-10.)))
        self.assertTrue(tank_collision.swept_body_separated(a,dict(b,x=4.),(0.,0.,-10.)))
        self.assertFalse(tank_collision.swept_body_separated(a,dict(b,shape=None),(0.,0.,-10.)))

    def test_amx_consumes_near_point_and_proves_next_fixed_leg_from_actual_hull(self):
        nav = TerrainNavigator(lambda *args: -6., lambda *args: False)
        d = DATA['amx']; sel=d['selection']; state={}
        current=tuple(d['final']); goal=tuple(sel['goal']); next_point=(current[0],-6.,current[2]-3.)
        with mock.patch.object(nav.grid,'safe_local_target',side_effect=[tuple(sel['candidate']),next_point]) as choose, \
             mock.patch.object(nav.grid,'dry_segment_clear',return_value=True) as proof:
            result=nav._new_local_fallback(12,current,tuple(sel['origin']),goal,10.,(),state)
        self.assertEqual(next_point,result)
        self.assertEqual(tuple(sel['candidate']),choose.call_args_list[1].args[0])
        self.assertEqual(current,proof.call_args.args[0])
        self.assertEqual('selected',state['local_selection']['outcome'])
        self.assertLess(state['local_selection']['consumed_anchor']['actual_distance'],1.5)

    def test_already_arrived_candidate_feeds_existing_finite_retry(self):
        nav=TerrainNavigator(lambda *args: 0.,lambda *args:False)
        current=(0.,0.,0.);goal=(30.,0.,0.);state={'request_key':('route',)}
        with mock.patch.object(nav.grid,'safe_local_target',return_value=(.8,0.,0.)):
            for now in (0.,13.):
                self.assertEqual(current,nav._new_local_fallback(1,current,current,goal,now,(),state))
        self.assertEqual('already_arrived_candidate',state['local_selection']['outcome'])
        self.assertTrue(nav._local_retry_stalled(state,current,goal,13.,True))

    def test_reached_path_target_does_not_renew_macro_deadline_forever(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        state=dict(last_target=(.8,0.,0.), path_key=('route',), index=0)
        for now in (0.,1.,2.,3.):
            nav._observe_macro_progress(1,state,(0.,0.,0.),(30.,0.,0.),now)
        self.assertEqual(0.,state['macro_progress_at'])

    def test_connector_refusal_and_deferred_query_keep_distinct_receipts(self):
        for reply, deferred in ((True,False),('deferred',True)):
            nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
            state={};current=(0.,0.,0.);origin=(-1.,0.,0.);goal=(30.,0.,0.)
            nav.grid.prebaked=True
            with mock.patch.object(nav.grid,'safe_local_target',return_value=(3.,0.,0.)), \
                 mock.patch.object(nav.grid,'_baked_cell_height',return_value=0.), \
                 mock.patch.object(nav.grid,'_baked_neighbours',return_value=[]), \
                 mock.patch.object(nav.grid,'dry_segment_clear',return_value=True), \
                 mock.patch.object(nav.grid,'_probe_obstacle',return_value=reply):
                self.assertEqual(current,nav._new_local_fallback(1,current,origin,goal,10.,(),state))
            self.assertNotIn('local_retry_progress',state)
            self.assertEqual(deferred,state['local_selection']['connector_deferred'])

    def test_foch_height_rounding_keeps_start_and_deadline_but_real_new_leg_resets(self):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False)
        state={};goal=(360.648,0.,-154.437)
        for n,y in enumerate((-.46952366828918457,-.46952342987060547,-.46952390670776367)*10):
            nav._remember_local_fallback((59.755001068115234,y,30.1200008392334),goal,state,
                (56.+n*.001,0.,29.),100.+n)
        self.assertEqual(100.,state['local_target_progress_at'])
        self.assertEqual((56.,0.,29.),state['local_fallback_start'])
        self.assertFalse(state['local_target_update']['deadline_renewed'])
        nav._remember_local_fallback((62.,0.,30.),goal,state,(57.,0.,29.),131.)
        self.assertEqual(131.,state['local_target_progress_at'])

    def test_fv_rotation_preserves_measurement_and_refreshes_new_footprint(self):
        d=DATA['fv'];r=d['support_evidence']['slope_samples']; pos=d['final']
        grade=(r['front']-r['rear'])/r['length']
        pitch=-math.atan(grade)
        roll=math.atan2((r['right']-r['left'])/r['width'],math.sqrt(1.+grade*grade))
        state=dict(id=12,x=pos[0],y=pos[1],z=pos[2],yaw=d['yaw'],pitch=pitch,
            terrain_pitch=pitch,roll=roll,grounded_once=True,airborne=False,
            half_length=d['shape'][1],half_width=d['shape'][0],
            pose_sample=(pos[0],pos[2],r['sample_yaw']),_basic_slope_basis_yaw=r['sample_yaw'],
            _slope_pose_target=(pitch,roll),speed=0.)
        runtime=bot_runtime.BotRuntime(1);runtime._descriptors[12]={}
        runtime._suspension_params[12]=None
        points={p['name']:p['ground'] for p in d['support_evidence']['points']}
        runtime._ground_probe_at=mock.Mock(side_effect=[points[k] for k in ('front','rear','right','left')])
        runtime._turret_motion_probe=mock.Mock(return_value=True)
        self.assertTrue(runtime._reorient_basic_ground_pose(state))
        self.assertAlmostEqual(d['pitch'],state['pitch'])
        self.assertEqual(r['sample_yaw'],state['pose_sample'][2])
        self.assertTrue(runtime._update_slope_pose(state))
        self.assertEqual(4,runtime._ground_probe_at.call_count)
        self.assertEqual(d['yaw'],state['pose_sample'][2])
        self.assertEqual('measurement_accepted',state['_slope_pose_refresh']['reason'])
        self.assertFalse(runtime._update_slope_pose(state))
        self.assertEqual(4,runtime._ground_probe_at.call_count)
        # A rejected fresh pose must not overwrite the accepted receipt or
        # advance the measurement marker; the next ordinary call can retry.
        marker=state['pose_sample'];samples=state['_basic_slope_samples']
        state['yaw']+=.8
        runtime._ground_probe_at=mock.Mock(return_value=pos[1])
        runtime._turret_motion_probe=mock.Mock(return_value=False)
        self.assertFalse(runtime._update_slope_pose(state))
        self.assertEqual(marker,state['pose_sample'])
        self.assertIs(samples,state['_basic_slope_samples'])
        self.assertEqual('body_pose_rejected',state['_slope_pose_refresh']['reason'])


if __name__ == '__main__':
    unittest.main()
