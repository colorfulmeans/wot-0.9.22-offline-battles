"""Final foreground integration review: public identity and native re-entry.

The runtime update and mounted EquipmentState are real Python implementations;
only native engine/device callbacks are injected at the unavailable boundary.
"""
import math
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/res/scripts/client'))
sys.path.insert(0, str(ROOT / 'tests'))
from gui.mods.offline_lan_0922.equipment_mechanics import EquipmentState, project_equipment
from gui.mods.offline_lan_0922.player_control.tactics import CombatTactics
from gui.mods.offline_lan_0922.player_control.traffic import PlayerTraffic
import test_player_independent_traffic as traffic_fixture
from test_player_independent_traffic import apply, order, peer, state


def equipment(identity, name, **fields):
    descriptor = dict(id=identity, name=name, compactDescr=identity,
                      reuseCount=1, cooldownSeconds=90., **fields)
    return EquipmentState(project_equipment(descriptor))


class EquipmentReentryTests(unittest.TestCase):
    def controller(self, items):
        controller, unused_nav, entity = traffic_fixture.ForegroundControllerTrafficIntegrationTests().controller()
        controller.features = {'consumables'}
        owner = controller.owner
        owner._equipment_state = items
        owner._local_airborne = owner._local_support_rise_blocked = False
        owner._local_ground_plane = dict(gradient_x=0., gradient_z=.2)
        owner._records = {'player:101': dict(ready=True, local=True, engine_id=7,
            critical_state=dict(devices=[dict(name='gunHealth', state='destroyed')],
                                crew_ko=['loader1'], fire=True), state=dict(team=1))}
        owner._critical_extra_index = lambda descriptor, name:3
        return controller, entity

    def test_actual_update_stops_before_activating_second_consumable(self):
        kits = [equipment(11, 'largeRepairkit', repairAll=True),
                equipment(12, 'largeMedkit', repairAll=True)]
        controller, unused_entity = self.controller(kits)
        calls = []
        def activate(code):
            calls.append(code)
            if len(calls) == 1:
                controller.stop('native_equipment_stop')
            return True
        controller.owner._activate_equipment = activate
        controller.update(.1, 1.)
        self.assertEqual([11 | (1 << 16)], calls)
        self.assertFalse(controller.active)
        self.assertNotIn(12, controller.consumable_pending)

    def test_native_target_resolution_stop_cannot_activate_the_retired_kit(self):
        controller, unused_entity = self.controller([equipment(11, 'smallRepairkit')])
        def resolve(descriptor, name):
            controller.stop('native_extra_stop')
            return 3
        controller.owner._critical_extra_index = resolve
        controller.owner._activate_equipment = mock.Mock(return_value=True)
        controller.update(.1, 1.)
        controller.owner._activate_equipment.assert_not_called()
        self.assertFalse(controller.active)

    def test_governor_callback_stop_does_not_resurrect_a_toggle_owner(self):
        limiter = equipment(21, 'removedRpmLimiter', engineHpLossPerSecond=.01)
        controller, unused_entity = self.controller([limiter])
        owner = controller.owner
        owner._local_speed = 3.
        owner._records['player:101']['critical_state'] = {}
        controller.governor.uphill_since = -2.
        calls = []
        def activate(code):
            calls.append(code)
            limiter.active = bool(code >> 16)
            if code >> 16:
                controller.stop('native_governor_stop')
            return True
        owner._activate_equipment = activate
        controller.update(.1, 1.)
        self.assertEqual([21 | (1 << 16), 21], calls)
        self.assertFalse(controller.active)
        self.assertFalse(limiter.active)
        self.assertIsNone(controller.owned_governor)
        self.assertIsNone(controller.governor_request)

    def test_siege_callback_stop_cannot_restore_old_braking_token(self):
        from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
        controller, entity = self.controller([])
        controller.features = {'drive'}
        owner = controller.owner
        entity.typeDescriptor.hasSiegeMode = True
        entity.siegeState = 0
        states = types.SimpleNamespace(DISABLED=0, ENABLED=1, SWITCHING_ON=2, SWITCHING_OFF=3)
        owner._runtime = types.SimpleNamespace(constants=types.SimpleNamespace(VEHICLE_SIEGE_STATE=states))
        owner._local_siege_pending = owner._local_siege_braking = None
        owner._local_speed, owner._local_turn_speed = 2., 0.
        owner._notify_player_control_siege = BattleRuntime._notify_player_control_siege
        owner._change_local_siege = types.MethodType(BattleRuntime._change_local_siege, owner)
        owner._request_player_control_siege = types.MethodType(BattleRuntime._request_player_control_siege, owner)
        owner._cancel_player_control_siege = types.MethodType(BattleRuntime._cancel_player_control_siege, owner)
        # The actual runtime publishes its unsent braking boolean before
        # this native-edge callback. Stop must release it inside that stack.
        owner._report_local_siege_edge = lambda *args, **kwargs:controller.stop('native_siege_stop')
        controller.update_siege(entity, order('engage', hold=True), True, 0.)
        controller.update_siege(entity, order('engage', hold=True), True, 1.)
        self.assertFalse(controller.active)
        self.assertIsNone(controller.siege_brake)
        self.assertIsNone(controller.siege_intent)
        self.assertIsNone(owner._local_siege_braking)

    def test_snapshot_replacement_after_first_kit_cannot_reuse_old_mount_list(self):
        first = equipment(11, 'largeRepairkit', repairAll=True)
        second = equipment(12, 'largeMedkit', repairAll=True)
        controller, unused_entity = self.controller([first, second])
        calls = []
        def activate(code):
            calls.append(code)
            controller.owner._equipment_state = [first, second]
            return True
        controller.owner._activate_equipment = activate
        controller.update(.1, 1.)
        self.assertEqual([11 | (1 << 16)], calls)


class PublicIdentityElectionTests(unittest.TestCase):
    def test_bot_namespace_is_given_priority_independent_of_local_engine_order(self):
        for own_engine, other_engine in ((1, 8), (8, 1)):
            player = PlayerTraffic()
            for now in (0., 1.6):
                own = state(now, identity=own_engine)
                own['actor_key'] = ('player', 1)
                other = peer(other_engine, (0., 0., 4.1), math.pi)
                other['actor_key'] = ('bot', 99)
                clear = lambda heading, reach=6.:abs(
                    (heading+math.pi) % (2.*math.pi)-math.pi) > 2.
                command = apply(player, own, [other], order(), clear)
            self.assertEqual(-.7, command['throttle'])
            self.assertEqual(other_engine, player.receipt['priority'])
            self.assertEqual(own_engine, player.receipt['retreat'])

    def test_real_contacts_and_update_keep_pair_roles_across_client_allocations(self):
        controllers = []
        for network, z, yaw, other_z, other_yaw in (
                (101, 0., 0., 4.1, math.pi),
                (102, 4.1, math.pi, 0., 0.)):
            controller, unused_nav, entity = traffic_fixture.ForegroundControllerTrafficIntegrationTests().controller()
            owner = controller.owner
            other_network = 203-network
            other = types.SimpleNamespace(id=8, position=(0., 0., other_z),
                health=1000, isAlive=lambda:True, isStarted=True,
                typeDescriptor=entity.typeDescriptor,
                matrix=types.SimpleNamespace(yaw=other_yaw, pitch=0., roll=0.))
            owner.client.player_id = network
            owner._start_message['players'] = [dict(id=101, team=1), dict(id=102, team=1)]
            owner._records = {'player:%s' % other_network:dict(ready=True, kind='player',
                network_id=other_network, engine_id=8, state=dict(team=1))}
            owner._server_entity = lambda identity, own=entity, peer=other:own if identity == 7 else peer
            owner.local_pose = lambda z=z, yaw=yaw:((0., 0., z), yaw)
            controller.direction_clear = lambda position, heading, descriptor, shape, reach=None, yaw=yaw:abs(
                (heading-yaw+math.pi) % (2.*math.pi)-math.pi) > 2.
            del controller._contacts  # Use the real public snapshot producer.
            controllers.append(controller)
        for now in (0., 1.6):
            for controller in controllers:
                controller.owner._clock = lambda now=now:now
                controller.update(.1, now)
        self.assertEqual([0., -.7], [control.owner._sender.forward for control in controllers])
        self.assertEqual([7, 8], [control.player_traffic.receipt['priority'] for control in controllers])
        self.assertEqual([8, 7], [control.player_traffic.receipt['retreat'] for control in controllers])

    def test_crossing_tie_uses_canonical_identity_with_local_collision_handles(self):
        winners = []
        for network, position, yaw, other_position, other_yaw, velocity in (
                (1, (0., 0., -3.), 0., (-3., 0., 0.), math.pi/2., (3., 0., 0.)),
                (2, (-3., 0., 0.), math.pi/2., (0., 0., -3.), 0., (0., 0., 3.))):
            player = PlayerTraffic()
            own = state(position=position, yaw=yaw, speed=3., identity=7)
            own['actor_key'] = ('player', network)
            other = peer(8, other_position, other_yaw, velocity=velocity)
            other['actor_key'] = ('player', 3-network)
            apply(player, own, [other], order(), lambda *args:True)
            winner = player.pairs[8]['winner']
            winners.append(network if winner == 7 else 3-network)
        self.assertEqual([1, 1], winners)

    def test_each_client_local_engine_assignment_still_elects_only_one_backer(self):
        policies = [PlayerTraffic(), PlayerTraffic()]
        commands = []
        for now in (0., 1.6):
            commands = []
            for network, player, z, yaw, other_z, other_yaw in (
                    (1, policies[0], 0., 0., 4.1, math.pi),
                    (2, policies[1], 4.1, math.pi, 0., 0.)):
                # Both native clients create their own tank first; engine 7
                # therefore refers to a different human on each machine.
                own = state(now, (0., 0., z), yaw, identity=7)
                own.update(id=network, actor_key=('player', network))
                other = peer(8, (0., 0., other_z), other_yaw)
                other['actor_key'] = ('player', 3-network)
                clear = lambda heading, reach=6., yaw=yaw: abs(
                    (heading-yaw+math.pi) % (2.*math.pi)-math.pi) > 2.
                commands.append(apply(player, own, [other], order('return_base'), clear))
        self.assertEqual([0., -.7], [command['throttle'] for command in commands])

    def test_flanker_election_uses_public_identity_not_local_engine_creation_order(self):
        chosen = []
        for network in (1, 2):
            own = state(identity=7)
            own.update(id=network, actor_key=('player', network), health=1000, max_health=1000)
            ally = dict(id=8, actor_key=('player', 3-network), position=(-30., 0., 30.),
                        alive=True, health=1000, max_health=1000, class_tag='mediumTank')
            context = dict(target=dict(id=99, position=(0., 0., 160.)), fire_clear=True,
                           supported=True, allies=[ally])
            descriptor = types.SimpleNamespace(type=types.SimpleNamespace(tags=('mediumTank',)))
            selected = CombatTactics().movement(own, context, descriptor, True,
                                                 lambda *args:0., lambda *args:True)
            chosen.append(selected is not None)
        self.assertEqual([True, False], chosen)


class SiegeObserverReentryTests(unittest.TestCase):
    def controller(self):
        from gui.mods.offline_lan_0922.battle_runtime import BattleRuntime
        controller, entity = EquipmentReentryTests().controller([])
        controller.features = {'drive'}
        owner = controller.owner
        entity.typeDescriptor.hasSiegeMode = True
        entity.siegeState = 0
        states = types.SimpleNamespace(DISABLED=0, ENABLED=1, SWITCHING_ON=2, SWITCHING_OFF=3)
        owner._runtime = types.SimpleNamespace(constants=types.SimpleNamespace(VEHICLE_SIEGE_STATE=states))
        owner._local_siege_pending = owner._local_siege_braking = None
        owner._local_speed, owner._local_turn_speed = 2., 0.
        owner._generation = 1
        owner.client.round_id = 'r'
        owner._notify_player_control_siege = BattleRuntime._notify_player_control_siege
        for name in ('_change_local_siege', '_request_player_control_siege',
                     '_cancel_player_control_siege', '_send_local_siege_request'):
            setattr(owner, name, types.MethodType(getattr(BattleRuntime, name), owner))
        owner._report_local_siege_edge = mock.Mock()
        return controller, entity

    def request(self, controller, entity):
        command = order('engage', hold=True)
        controller.update_siege(entity, command, True, 0.)
        controller.update_siege(entity, command, True, 1.)

    def test_previous_observer_stop_revokes_new_request_before_brake(self):
        controller, entity = self.controller()
        owner = controller.owner
        owner._player_control_siege_observer = dict(token=object(), enabled=False,
            callback=lambda *args:controller.stop('previous_observer_stop'))
        self.request(controller, entity)
        self.assertFalse(controller.active)
        self.assertIsNone(owner._local_siege_braking)
        self.assertIsNone(owner._player_control_siege_observer)
        self.assertIsNone(controller.siege_observer)
        self.assertIsNone(controller.siege_brake)
        owner._report_local_siege_edge.assert_not_called()

    def test_replacement_observer_and_brake_survive_old_call_and_stop(self):
        controller, entity = self.controller()
        owner, replacement, replaced = controller.owner, mock.Mock(), []
        def report(*args, **kwargs):
            if not replaced:
                replaced.append(True)
                owner._request_player_control_siege(True, replacement)
        owner._report_local_siege_edge = report
        self.request(controller, entity)
        self.assertIs(owner._player_control_siege_observer['callback'], replacement)
        self.assertIs(owner._local_siege_braking, True)
        self.assertIsNone(controller.siege_observer)
        self.assertIsNone(controller.siege_brake)
        controller.stop('old_control_stop')
        self.assertIs(owner._player_control_siege_observer['callback'], replacement)
        self.assertIs(owner._local_siege_braking, True)
        replacement.assert_not_called()

    def test_submitted_transition_remains_native_owned_after_stop(self):
        controller, entity = self.controller()
        owner = controller.owner
        owner._local_speed = 0.
        owner._sender.send_current.return_value = 17
        self.request(controller, entity)
        self.assertEqual((True, 17), owner._local_siege_pending)
        self.assertIsNone(owner._player_control_siege_observer)
        self.assertIsNone(controller.siege_observer)
        controller.stop('after_submission')
        self.assertEqual((True, 17), owner._local_siege_pending)
        self.assertFalse(controller.release_pending)

    def test_failed_exact_observer_release_is_retried_without_losing_ownership(self):
        controller, entity = self.controller()
        owner = controller.owner
        self.request(controller, entity)
        real_cancel, attempts = owner._cancel_player_control_siege, []
        def cancel(callback):
            attempts.append(callback)
            if len(attempts) == 1:
                raise RuntimeError('native cancellation unavailable')
            return real_cancel(callback)
        owner._cancel_player_control_siege = cancel
        controller.stop('release_retry')
        self.assertIs(owner._local_siege_braking, True)
        self.assertIn('automatic_siege_release', [stage for stage, unused in controller.release_pending])
        controller.retry_releases(2.)
        self.assertEqual(2, len(attempts))
        self.assertIs(attempts[0], attempts[1])
        self.assertIsNone(owner._local_siege_braking)
        self.assertIsNone(owner._player_control_siege_observer)
        self.assertFalse(controller.release_pending)


if __name__ == '__main__':
    unittest.main()
