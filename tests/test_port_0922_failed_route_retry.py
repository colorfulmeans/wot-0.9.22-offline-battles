"""Captured no-progress handoffs must permit another bounded route attempt."""
import unittest

from test_port_0922_server_bot_ai import BotPlanner, _bot, _route, _state, _order_signature


class FailedRouteRetryTests(unittest.TestCase):
    def scene(self, singleton=False):
        planner = BotPlanner()
        route = _route('center_line', [(0, 18, False)] if singleton else
                       [(334, -370, False), (394, -214, False), (365, 15, False)])
        other = _route('west_pass', [(346, -402, False), (140, -223, False),
                                    (68, -224, False)])
        manifest = [_bot(13, 1, 0, route, 'mediumTank'),
                    _bot(24, 1, 1, other, 'mediumTank')]
        bot = dict(manifest[0], state=_state(13, 1, -11, 19) if singleton else
                   _state(13, 1, 337, -142))
        planner._route_states[13] = dict(route_id=route['id'], index=0 if singleton else 1)
        order = dict(id=13, route_id=route['id'], route_index=0 if singleton else 1,
                     combat_mode='route', move_position=route['waypoints'][0 if singleton else 1])
        return planner, bot, manifest, order

    def test_report_13_eleven_metres_from_single_goal_is_not_arrival(self):
        planner, bot, manifest, order = self.scene(True)
        for now in (0, 19.9):
            planner._reroute_wreck_stall(order, bot, manifest, now)
            self.assertEqual('center_line', order['route_id'])
        planner._reroute_wreck_stall(order, bot, manifest, 20)
        self.assertEqual('west_pass', order['route_id'])

    def test_travelling_combat_withdrawal_pauses_the_failed_attempt(self):
        planner,bot,manifest,order=self.scene()
        planner._reroute_wreck_stall(order,bot,manifest,0)
        for now in (5,10,50):
            order['combat_mode']='under_fire_withdraw'
            planner._reroute_wreck_stall(order,bot,manifest,now)
        self.assertEqual('center_line',order['route_id'])
        order['combat_mode']='route'
        planner._reroute_wreck_stall(order,bot,manifest,100)
        self.assertEqual(5.,order['route_attempt']['elapsed'])
        planner._reroute_wreck_stall(order,bot,manifest,115)
        self.assertEqual('skip_gate',order['route_attempt']['action'])

    def test_report_28_short_support_holds_pause_instead_of_erase_attempt(self):
        planner,bot,manifest,order=self.scene(True)
        planner._reroute_wreck_stall(order,bot,manifest,0.)
        for start in (5.,10.,15.,20.):
            order['combat_mode']='support_hold';planner._reroute_wreck_stall(order,bot,manifest,start)
            order['combat_mode']='route';planner._reroute_wreck_stall(order,bot,manifest,start+1.)
            self.assertEqual('center_line',order['route_id'])
        planner._reroute_wreck_stall(order,bot,manifest,24.)
        self.assertEqual('west_pass',order['route_id'])

    def test_return_failure_retries_immediately_without_a_failed_route_cooldown(self):
        planner,bot,manifest,order=self.scene()
        for now in (0,20,40):planner._reroute_wreck_stall(order,bot,manifest,now)
        self.assertEqual(('center_line',0),(order['route_id'],order['route_index']))
        planner._reroute_wreck_stall(order,bot,manifest,60)
        self.assertEqual('retry_cycle',order['route_attempt']['action'])
        self.assertEqual(1,order['route_index'])
        self.assertNotIn('retry_after',order['route_attempt'])

    def test_real_single_goal_arrival_and_explicit_holds_still_do_not_switch(self):
        for change in ('arrived', 'hold', 'command', 'disabled'):
            planner, bot, manifest, order = self.scene(True)
            if change == 'arrived': bot['state'].update(x=0, z=18)
            if change == 'hold': order['throttle_override'] = 0
            if change == 'command': order['team_command'] = 'STAY'
            if change == 'disabled': bot['state']['critical'] = {'destroyed': ['leftTrackHealth']}
            for now in (0, 20, 40, 160):
                planner._reroute_wreck_stall(order, bot, manifest, now)
            self.assertEqual('center_line', order['route_id'], change)

    def test_macro_waypoint_retains_original_thirteen_metre_arrival(self):
        planner, bot, manifest, order = self.scene()
        bot['state'].update(x=390, z=-214)
        for now in (0, 20, 40):
            planner._reroute_wreck_stall(order, bot, manifest, now)
        self.assertNotIn(13, planner._wreck_route_progress)

    def test_retries_can_return_again_after_another_complete_failed_attempt(self):
        planner,bot,manifest,order=self.scene()
        changes=[];previous=order['route_id']
        for now in range(501):
            order['combat_mode']='route'
            planner._reroute_wreck_stall(order,bot,manifest,now)
            if order['route_id']!=previous:
                changes.append((now,order['route_id']));previous=order['route_id']
            recovery=planner._route_recoveries.get(bot['id'])
            if recovery and recovery['phase'] in ('return','transfer'):
                root=planner._cycle_route(bot)['waypoints'][0];bot['state'].update(x=root['x'],z=root['z'])
        self.assertEqual(['west_pass','center_line','west_pass','center_line'],[r for t,r in changes[:4]])
        self.assertTrue(all(b[0]-a[0]>=40 for a,b in zip(changes,changes[1:])))

    def test_untried_suitable_route_is_preferred_to_old_failed_route(self):
        planner,bot,manifest,order=self.scene()
        third=_route('fresh_lane',[(500,500,False),(500,-400,False)])
        manifest.append(_bot(25,1,2,third,'mediumTank'))
        for now in (0,20,40):planner._reroute_wreck_stall(order,bot,manifest,now)
        planner._recovery_route_visits[13]={'west_pass':1}
        bot['state'].update(x=334,z=-370)
        planner._reroute_wreck_stall(order,bot,manifest,41)
        self.assertEqual(('fresh_lane',0),(order['route_id'],order['route_index']))

    def test_event_records_current_failed_attempt_and_retry_reason(self):
        planner,bot,manifest,order=self.scene()
        for now in (0,20,40):planner._reroute_wreck_stall(order,bot,manifest,now)
        trace=order['route_attempt']
        self.assertEqual(('center_line','return_to_anchor'),(trace['route_id'],trace['action']))
        self.assertEqual(('return',0),(trace['phase'],trace['next_index']))
        self.assertNotIn('retry_after',trace)
        self.assertEqual(20,trace['elapsed'])

    def test_attempt_telemetry_cannot_advance_strategic_order_revision(self):
        planner, bot, manifest, order = self.scene()
        planner._reroute_wreck_stall(order, bot, manifest, 0)
        before = _order_signature(order)
        planner._reroute_wreck_stall(order, bot, manifest, 9)
        self.assertEqual(9, order['route_attempt']['elapsed'])
        self.assertEqual(before, _order_signature(order))


if __name__ == '__main__':
    unittest.main()
