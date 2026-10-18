"""Assignment evidence retains same-update transitions without choosing routes."""
import copy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
import test_port_0922_withdraw_receipts as fixture
import lan_battle_server as server


class RouteAssignmentEvidenceTests(unittest.TestCase):
    def scene(self):
        case=fixture.RouteLeaseEvidenceTests()
        case.setUp()
        return case

    def test_pressure_choice_records_scores_and_every_candidate_outcome(self):
        case=self.scene();p=case.planner
        receipt=p._route_assignment_receipts[case.donor['id']]
        evidence=receipt['selection']
        self.assertEqual({b['id'] for b in case.bots},
                         {r['bot'] for r in evidence['candidates']})
        self.assertTrue(all(r['outcome'] for r in evidence['candidates']))
        eligible=[r for r in evidence['candidates'] if r['outcome']=='eligible']
        winner=max(eligible,key=lambda r:(r['score'],r['tie_break']))
        self.assertEqual(winner['bot'],evidence['selected_bot'])
        self.assertEqual(case.donor['id'],evidence['selected_bot'])
        self.assertEqual('target',evidence['target_route'])
        self.assertTrue(evidence['pressure'])
        self.assertTrue(evidence['contributors'])

    def test_expiry_and_reassignment_keep_both_events_and_old_cursor(self):
        case=self.scene();p=case.planner;bot=case.donor
        p._record_route_assignment(bot,7.,'target','source','lease_expired')
        first=copy.deepcopy(p._route_assignment_receipts[bot['id']])
        p._record_route_assignment(bot,7.,'source','target','pressure_rebalance')
        receipt=json.loads(json.dumps(p._route_assignment_receipts[bot['id']]))
        self.assertEqual(['lease_expired','pressure_rebalance'],
                         [r['reason'] for r in receipt['history'][-2:]])
        self.assertEqual([2,3],[r['sequence'] for r in receipt['history'][-2:]])
        self.assertEqual(first['previous_progress'],receipt['history'][-2]['previous_progress'])
        self.assertEqual(1,first['previous_progress']['index'])
        self.assertEqual({'x':100.,'y':0.,'z':100.,'hold':False},first['previous_progress']['point'])
        self.assertEqual(0,receipt['history_dropped'])
        self.assertTrue(all('history' not in r for r in receipt['history']))

    def test_bounded_history_exposes_omission_and_does_not_retain_old_graphs(self):
        case=self.scene();p=case.planner
        for at in range(2,12):
            p._record_route_assignment(case.donor,float(at),'target','source','lease_expired')
        receipt=p._route_assignment_receipts[case.donor['id']]
        self.assertEqual(8,len(receipt['history']))
        self.assertEqual(3,receipt['history_dropped'])
        self.assertEqual(list(range(4,12)),[r['sequence'] for r in receipt['history']])
        self.assertTrue(all('history' not in r for r in receipt['history']))

    def test_logging_leaves_existing_pressure_lease_and_route_cursor_decisions_unchanged(self):
        actual=self.scene();control=self.scene()
        control.planner._record_route_assignment=lambda *args,**kwargs:None
        for now,shift in [(5.,False),(7.,True),(11.,True),(15.,False),(21.,False)]:
            for case in (actual,control):
                contacts=case.contacts
                if shift:
                    contacts=contacts+[dict(position=dict(x=-100.,y=0.,z=z),
                        health=1000.,max_health=1000.) for z in (200.,300.)]
                case.planner._rebalance_routes(1,case.bots,contacts,now)
            def decisions(case):
                return {k:{name:value for name,value in lease.items()
                           if not name.startswith('_')} for k,lease in
                        case.planner._route_assignments.items()}
            self.assertEqual(decisions(control),decisions(actual))
            self.assertEqual(control.planner._route_states,actual.planner._route_states)

    def test_server_logs_all_same_update_events_once_and_resets_each_round(self):
        case=self.scene();p=case.planner;bot=case.donor
        p._record_route_assignment(bot,7.,'target','source','lease_expired')
        p._record_route_assignment(bot,7.,'source','target','pressure_rebalance')
        state=types.SimpleNamespace(round_id=0,bot_orders={'orders':[
            dict(id=bot['id'],route_assignment=p._route_assignment_receipts[bot['id']])]})
        output=[]
        with mock.patch.object(server,'_server_log',side_effect=output.append):
            server.BattleState._log_bot_route_assignments(state)
            server.BattleState._log_bot_route_assignments(state)
            self.assertEqual(3,len(output))
            p.reset(2)
            p._record_route_assignment(bot,10.,'source','target','pressure_rebalance')
            state.round_id=2
            state.bot_orders['orders'][0]['route_assignment']=p._route_assignment_receipts[bot['id']]
            server.BattleState._log_bot_route_assignments(state)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        from read_native_evidence import parse_lines
        parsed=parse_lines(output,'server.log')
        self.assertEqual([],parsed['issues'])
        rows=[r['data'] for r in parsed['records']]
        self.assertEqual([1,2,3,1],[r['sequence'] for r in rows])
        self.assertEqual([0,1,2,0],[r['prior_logged_sequence'] for r in rows])
        self.assertEqual([0,0,0,2],[r['round'] for r in rows])
        self.assertEqual('lease_expired',rows[1]['reason'])
        self.assertEqual('pressure_rebalance',rows[2]['reason'])
        self.assertTrue(rows[0]['selection']['candidates'])


if __name__=='__main__':unittest.main()
