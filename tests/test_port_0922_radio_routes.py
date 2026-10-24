"""Route reinforcements must obey the recipient's own radio knowledge."""
import copy
import unittest

import test_port_0922_bot_runtime  # Install the standalone client fixtures.
import test_port_0922_server_bot_ai as fixture
from server_bot_ai import BotPlanner


class RadioRouteTests(unittest.TestCase):
    def test_route_reinforcement_cannot_cancel_an_authored_wait(self):
        for phase in ('approach','waiting','queue'):
            planner,manifest,states,players,unused=self._fixture((11,))
            planner._route_assignments[11]=dict(route=manifest[0]['route'],until=0.)
            planner._route_states[11]=dict(parking_phase=phase)
            orders=self._orders(planner,manifest,states,players,1.)
            self.assertEqual('left',orders[11]['route_id'])

    def _fixture(self, recipients=(), lease=10.0, legacy=False):
        planner = BotPlanner()
        # This fixture holds poses fixed across minute evaluations. Isolate
        # pressure assignment from the independent 20-second stuck reroute.
        planner._reroute_wreck_stall = lambda *unused: None
        left = fixture._route('left', [(-300, 0, False), (-300, 300, True)])
        right = fixture._route('right', [(300, 0, False), (300, 300, True)])
        manifest = [fixture._bot(
            identity, 1, identity - 11, left if identity < 14 else right,
            'mediumTank', {'support': 1.0}) for identity in range(11, 15)]
        states = [fixture._state(identity, 1, -300 if identity < 14 else 300, 0)
                  for identity in range(11, 15)]
        players = [{'id': identity, 'team': 2, 'alive': True}
                   for identity in range(2, 5)]
        contacts = []
        for identity in range(2, 5):
            contact = fixture._contact(identity, 300, 300, [])
            if not legacy:
                contact['radio_recipients'] = [
                    {'kind': 'bot', 'id': recipient, 'time_left': lease}
                    for recipient in recipients]
            contacts.append(contact)
        targets = planner.known_targets(states, players)
        planner.report_contacts(contacts, targets, 1.0)
        return planner, manifest, states, players, contacts

    @staticmethod
    def _orders(planner, manifest, states, players, now):
        return {row['id']: row for row in
                planner.build_orders(manifest, states, players, now)['orders']}

    def test_unreceived_enemy_positions_do_not_change_routes(self):
        planner, manifest, states, players, unused = self._fixture()
        orders = self._orders(planner, manifest, states, players, 1.0)
        for identity in (11, 12, 13):
            self.assertEqual('left', orders[identity]['route_id'])
            self.assertEqual(-300.0, orders[identity]['move_position']['x'])
        self.assertTrue(all(row['target_id'] is None for row in orders.values()))

    def test_only_receiving_donor_returns_to_old_start_before_transfer(self):
        p,m,s,players,unused=self._fixture((11,))
        orders=self._orders(p,m,s,players,1.)
        self.assertEqual({11},set(p._travel_tasks))
        self.assertEqual('right',p._travel_tasks[11]['target_route']['id'])
        self.assertEqual('left',orders[11]['route_id'])
        self.assertEqual('route_transfer',orders[11]['combat_mode'])
        self.assertEqual('left',orders[12]['route_id'])
        s[0].update(x=300,z=0)
        committed=self._orders(p,m,s,players,2.)[11]
        self.assertEqual('right',committed['route_id']);self.assertNotIn(11,p._travel_tasks)

    def test_disconnected_donor_finishes_old_leg_until_task_expiry(self):
        p,m,s,players,contacts=self._fixture((11,))
        self._orders(p,m,s,players,1.)
        for c in contacts:c['radio_recipients']=[]
        p.report_contacts(contacts,p.known_targets(s,players),1.1)
        for now in (1.1,5.,61.,180.):
            self.assertEqual('route_transfer',self._orders(p,m,s,players,now)[11]['combat_mode'])
        order=self._orders(p,m,s,players,181.)[11]
        self.assertNotIn(11,p._travel_tasks);self.assertEqual('left',order['route_id'])

    def test_pending_target_survives_last_original_owner_death(self):
        p,m,s,players,contacts=self._fixture((11,),lease=500.)
        self._orders(p,m,s,players,1.)
        s[-1].update(alive=False,health=0)
        p._next_route_rebalance[1]=2.
        self._orders(p,m,s,players,2.)
        self.assertEqual('right',p._travel_tasks[11]['target_route']['id'])
        s[0].update(x=300,z=0)
        self.assertEqual('right',self._orders(p,m,s,players,3.)[11]['route_id'])
        self.assertTrue(p._route_assignments[11]['ordered_task'])
        self.assertEqual('right',self._orders(p,m,s,players,183.)[11]['route_id'])

    def test_selection_knowledge_is_a_frozen_snapshot(self):
        p,m,s,players,contacts=self._fixture((11,))
        self._orders(p,m,s,players,1.)
        evidence=p._route_assignment_receipts[11]['selection']['contact_inputs']
        self.assertTrue(evidence);frozen=copy.deepcopy(evidence)
        for c in p._contacts[1].values():c['position']['x']=9999.;c['radio_bot_until'].clear()
        self.assertEqual(frozen,evidence)

    def test_three_minute_evaluation_does_not_repeat_an_in_transit_assignment(self):
        p,m,s,players,contacts=self._fixture((11,12),lease=500.)
        self._orders(p,m,s,players,1.)
        donor=next(iter(p._travel_tasks));first=copy.deepcopy(p._travel_tasks[donor])
        for now in (5.,61.,180.):self._orders(p,m,s,players,now)
        self.assertEqual({donor},set(p._travel_tasks))
        self.assertEqual(first['until'],p._travel_tasks[donor]['until'])
        self.assertEqual(181.,p._next_route_rebalance[1])

    def test_new_receiver_waits_for_evaluation_and_old_cannot_renew_expired_task(self):
        p,m,s,players,contacts=self._fixture((11,))
        self._orders(p,m,s,players,1.)
        for c in contacts:c['radio_recipients']=[dict(kind='bot',id=12,time_left=500.)]
        p.report_contacts(contacts,p.known_targets(s,players),5.)
        self._orders(p,m,s,players,61.)
        self.assertNotIn(12,p._travel_tasks)
        self._orders(p,m,s,players,181.)
        self.assertNotIn(11,p._travel_tasks)
        p.report_contacts(contacts,p.known_targets(s,players),181.9)
        p._next_route_rebalance[1]=182.
        self._orders(p,m,s,players,182.)
        self.assertEqual('right',p._travel_tasks[12]['target_route']['id'])
        self.assertEqual('left',p._route_assignments[11]['route']['id'])

    def test_legacy_contacts_use_same_ordered_transfer(self):
        p,m,s,players,unused=self._fixture(legacy=True)
        self._orders(p,m,s,players,1.)
        self.assertEqual(1,len(p._travel_tasks))
        donor=next(iter(p._travel_tasks));task=p._travel_tasks[donor]
        self.assertEqual('pressure',task['kind']);self.assertEqual(181.,task['until'])
        self.assertEqual('right',task['target_route']['id'])
        self.assertEqual('left',p._route_assignments[donor]['route']['id'])


if __name__ == '__main__':
    unittest.main()
