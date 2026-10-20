"""Confirmed failed shots give other checked regions a bounded opportunity."""
import contextlib
import io
import unittest
import json
import sys
from pathlib import Path
from test_port_0922_parking_displacement import SPGFirePositionTests as Fixture


class ZoneRetryTests(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    _runtime=Fixture._runtime
    fixture=Fixture.fixture
    observe=Fixture.observe

    def fail_and_retry(self, fixture, start):
        runtime,state,target,order,gun,ammo=fixture
        with contextlib.redirect_stdout(io.StringIO()):
            for n in range(31):self.observe(fixture,start+n)
            plan=runtime._retry_spg_fire_position(state,state['_spg_initial'],start+30.)
        state.update(plan['point'])
        return plan,state['_spg_position_retry_receipt']

    def test_second_confirmed_failure_moves_to_other_region_before_old_points_expire(self):
        scene=self.fixture()
        first,one=self.fail_and_retry(scene,0.)
        self.assertEqual('home',first['zone'])
        second,two=self.fail_and_retry(scene,46.)
        self.assertEqual('other',second['zone'])
        self.assertEqual(['home'],two['excluded_zones'])
        self.assertFalse(two['cycle_restarted'])
        self.assertEqual(2,two['failures']['home'])

    def test_all_failed_regions_start_new_cycle_without_permanent_ban(self):
        scene=self.fixture()
        zones=[];receipts=[]
        for start in (0.,46.,92.,138.,184.,230.):
            plan,receipt=self.fail_and_retry(scene,start)
            zones.append(plan['zone']);receipts.append(receipt)
        self.assertEqual(['home','other','other'],zones[:3])
        self.assertTrue(any(r['cycle_restarted'] for r in receipts))
        self.assertTrue(all(r['attempts'] for r in receipts))

    def test_one_region_can_keep_retrying_safe_points(self):
        scene=self.fixture(alternate=False)
        self.fail_and_retry(scene,0.)
        plan,receipt=self.fail_and_retry(scene,46.)
        self.assertEqual('home',plan['zone'])
        self.assertTrue(receipt['cycle_restarted'])
        self.assertEqual(2,len(receipt['attempts']))

    def test_pending_no_target_and_reload_do_not_exhaust_a_region(self):
        scene=self.fixture();runtime,state,target,order,gun,ammo=scene
        with contextlib.redirect_stdout(io.StringIO()):
            for n in range(100):self.observe(scene,float(n),planning={'state':'pending'})
        self.assertNotIn('_spg_zone_failures',state)
        self.assertNotIn('_spg_fire_position_failure',state)

    def test_actual_shot_resets_region_history(self):
        scene=self.fixture();runtime,state,target,order,gun,ammo=scene
        self.fail_and_retry(scene,0.)
        self.assertTrue(state['_spg_zone_failures'])
        state['fire_seq']+=1
        self.observe(scene,31.,planning={'state':'pending'})
        self.assertNotIn('_spg_zone_failures',state)

    def test_recorded_m41_gets_another_region_without_claiming_a_clear_firing_arc(self):
        root=Path(__file__).resolve().parents[1]
        case=json.loads((root/'tests/fixtures/m41-205632-parking.json').read_bytes())
        scene=self.fixture();runtime,state,target,order,gun,ammo=scene
        runtime.baked_graph=json.loads((root/'navgraphs'/(case['map']+'.json')).read_bytes())
        cfg=self.module.bot_tactics
        raw=cfg.empty('Recorded M41')
        raw['maps'][case['map']]=dict(mode='regular',
            resource_sha256=cfg.MAPS[case['map']]['resource_sha256'],
            positions=case['positions'],routes=[])
        runtime._bot_tactics=cfg.canonical(raw)
        state.update(id=30,team=2,vehicle='usa:A18_M41',collision_shape=tuple(case['shape']))
        state.update(dict(zip(('x','y','z'),case['position'])))
        plan=self.module.bot_tactics_runtime.assign_manual_positions(
            runtime._bot_tactics,case['map'],runtime.baked_graph,[state],preferred_zone=case['zone'])[0][30]
        state['_spg_initial']=plan
        state.update(plan['point'])
        runtime.states={30:state}
        first,_=self.fail_and_retry(scene,0.)
        self.assertEqual(case['zone'],first['zone'])
        log=io.StringIO()
        with contextlib.redirect_stdout(log):
            for n in range(31):self.observe(scene,46.+n)
            second=runtime._retry_spg_fire_position(state,state['_spg_initial'],76.)
        self.assertNotEqual(case['zone'],second['zone'])
        self.assertEqual('runtime_required',second['fire_validation'])
        sys.path.insert(0,str(root/'tools'))
        from read_native_evidence import parse_lines
        evidence=parse_lines(log.getvalue().splitlines())
        self.assertEqual([],evidence['issues'])
        receipt=next(r['data'] for r in evidence['records'] if r['label']=='SPG POSITION RETRY')
        self.assertEqual(second['zone'],receipt['selected_zone'])
        self.assertEqual([case['zone']],receipt['excluded_zones'])


del Fixture

if __name__=='__main__':unittest.main()
