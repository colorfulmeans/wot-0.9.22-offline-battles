"""The live foreground and worker bindings execute one actor task machine.

Only native observations and committed battle facts are fixtures. Task,
combat-order and planner implementations are the production implementations.
"""
import contextlib
import copy
import io
import unittest

import test_player_full_runtime as foreground
import test_port_0922_actor_binding as worker

from gui.mods.offline_lan_0922.vehicle_control.mission_control import MissionControl
from gui.mods.offline_lan_0922.vehicle_control.settling import HaltObservation
from gui.mods.offline_lan_0922.vehicle_control.strategy import BotPlanner


class SharedMissionTests(unittest.TestCase):
    def setUp(self):
        self.player_scene = foreground.FullRuntimeTests('runTest')
        self.player_scene.setUp()
        self.addCleanup(self.player_scene.doCleanups)
        self.player = self.player_scene.runtime
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.player.start(('drive',)))
        self.addCleanup(self.player.close)
        self.worker_scene = worker.ActorBindingTests('runTest')
        self.worker_scene.setUp()
        self.addCleanup(self.worker_scene.doCleanups)
        self.bot = self.worker_scene.binding
        self.other = self.worker_scene.other
        self.bot.features = set(('drive',))
        self.other.features = set(('drive',))
        self.bot.state['team'] = self.other.state['team'] = 1
        self.engine = self.worker_scene.engine
        self.engine.control_planner = BotPlanner()
        self.engine.control_manifest = [dict(state) for state in self.engine.states.values()]
        self.bot.planner = self.other.planner = self.engine.control_planner
        self.defense = dict(arena_bounds=(-1000., -1000., 1000., 1000.),
            capture_bases={
                '1': [dict(id='home', x=0., y=0., z=0., radius=12.),
                      dict(id='other-home', x=100., y=0., z=100., radius=12.)],
                '2': [dict(id='enemy', x=0., y=0., z=40., radius=12.)]},
            states={'1': dict(points=0.), '2': dict(points=0.)})
        self.engine.control_defense_context = lambda: copy.deepcopy(self.defense)
        self.actors = (self.player, self.bot)
        for actor in self.actors + (self.other,):
            self.pose(actor, (0., 0., -30.))
        self.publish_defense()

    def publish_defense(self):
        self.player.owner._last_snapshot = dict(
            round_id=self.player.owner._start_message['round_id'],
            defense=copy.deepcopy(self.defense))
        if 'battle_result' in self.defense:
            self.player.owner._last_snapshot['battle_result'] = self.defense['battle_result']

    def pose(self, actor, point, speed=0., turn=0., supported=True):
        if actor is self.player:
            owner = actor.owner
            owner._local_matrix.translation = tuple(point)
            owner._local_position = tuple(point)
            owner._local_speed, owner._local_turn_speed = speed, turn
            owner._local_pitch = owner._local_roll = 0.
            owner._local_suspension_pitch_velocity = 0.
            owner._local_suspension_roll_velocity = 0.
            owner._local_vertical_speed = 0.
            owner._local_air_lateral = (0., 0.)
            owner._local_airborne = not supported
            owner._local_support_rise_blocked = False
            owner._overturn_level = 0
            actor._observe_local(actor.now)
        else:
            actor.state.update(x=point[0], y=point[1], z=point[2], yaw=0.,
                speed=speed, pitch=0., roll=0., suspension_pitch_velocity=0.,
                suspension_roll_velocity=0., vertical_speed=0.,
                air_lateral_x=0., air_lateral_z=0., airborne=not supported,
                _overturn_level=0)
            actor.engine._turn_speeds[actor.actor_id] = turn
            actor.record_support(False)

    def order(self, mode='route'):
        return dict(combat_mode=mode, move_position=(0., 0., 40.),
            face_position=(0., 0., 40.), aim_position=None, fire_allowed=False,
            target_id=None, target_kind=None, route_join=False,
            throttle_override=None)

    def accept(self, actor, now, order=None):
        actor.now = float(now)
        supplied = dict(self.order() if order is None else order)
        if actor is self.player:
            self.assertTrue(actor._advance_mission_retry(now))
            return actor._accept_task_order(supplied, now)
        return actor.refine_order(supplied, (), now)

    def assert_same_task(self):
        first, second = (actor.mission_status() for actor in self.actors)
        self.assertEqual(first, second)

    def test_both_bindings_inherit_the_entire_task_implementation(self):
        methods = ('set_mission', 'mission_preflight', '_mission_order',
            '_mission_guard_order', '_mission_brakes', '_observe_mission',
            '_retire_implicit', '_advance_mission_retry', '_cancel_mission',
            '_start_mission_lifecycle', '_accept_task_order',
            'mission_team_orders', 'guard_mission_controls',
            'finish_battle', 'mission_status')
        for actor in self.actors:
            for name in methods:
                self.assertNotIn(name, type(actor).__dict__)
                self.assertIs(getattr(type(actor), name), getattr(MissionControl, name))
        self.assertIsNot(self.player._mission_halt, self.bot._mission_halt)
        self.assertIsNot(self.bot._mission_halt, self.other._mission_halt)

    def test_automatic_capture_defense_handoff_and_started_capture_match(self):
        for actor in self.actors:
            capture = self.accept(actor, 1., self.order('base_capture'))
            self.assertEqual('base_capture', capture['combat_mode'])
            self.assertFalse(actor._mission['explicit'])
            self.assertFalse(actor._mission.get('capture_started'))
            defense = self.accept(actor, 2., self.order('base_defense'))
            self.assertEqual('base_defense', defense['combat_mode'])
            self.assertEqual('defending', actor._mission['phase'])
            self.pose(actor, (0., 0., 40.))
            self.accept(actor, 3., self.order('base_capture'))
            self.assertTrue(actor._mission['capture_started'])
            retained = self.accept(actor, 4., self.order('base_defense'))
            self.assertEqual('base_capture', retained['combat_mode'])
            self.assertTrue(actor._mission['holding'])
        self.assert_same_task()
        self.assertIsNone(self.other._mission)

    def test_return_base_keeps_player_choice_then_requires_real_rest(self):
        for actor in self.actors:
            self.pose(actor, (100., 0., 98.))
            self.assertEqual('running', actor.set_mission('return_base', {})['status'])
            order = self.accept(actor, 0.)
            self.assertEqual((0., 0., 0.), order['move_position'])
            self.pose(actor, (0., 0., 0.), speed=.8)
            self.accept(actor, 1.)
            self.assertEqual('arriving', actor._mission['phase'])
            stopped = actor.guard_mission_controls(dict(throttle=1., turn=1.,
                fire_allowed=True, confirmed_facing={'state': 'turning'}))
            self.assertEqual((0., 0., True, False),
                (stopped['throttle'], stopped['turn'], stopped['brake'], stopped['fire_allowed']))
            self.assertNotIn('confirmed_facing', stopped)
            self.pose(actor, (0., 0., 0.))
            for now in (2., 2.49):
                self.accept(actor, now)
                self.assertEqual('running', actor._mission['status'])
            self.accept(actor, 2.5)
            self.assertEqual(('completed', 'holding'),
                (actor._mission['status'], actor._mission['phase']))
        self.assert_same_task()

    def test_hold_defend_and_attack_arrival_share_same_state_transitions(self):
        for kind, payload, terminal, phase in (
                ('hold_position', {}, 'completed', 'holding'),
                ('defend_base', {}, 'running', 'defending'),
                ('attack', {'position': (0., 0., 0.)}, 'completed', 'holding')):
            for actor in self.actors:
                actor.now = 0.
                self.pose(actor, (0., 0., 0.))
                actor.set_mission(kind, payload)
                self.accept(actor, 0.)
                self.assertEqual('arriving', actor._mission['phase'])
                self.accept(actor, .5)
                self.assertEqual((terminal, phase, True),
                    (actor._mission['status'], actor._mission['phase'], actor._mission['holding']))
            self.assert_same_task()

    def test_empty_ammunition_switches_attack_task_without_a_second_rule(self):
        self.player.gun.ammo[:] = [0 for value in self.player.gun.ammo]
        ammo = self.bot._native_ammo()
        ammo.restore(dict(ammo_remaining=[0 for value in ammo.remaining],
            shell_index=0, next_shell_index=0, ammo_reload_pending=False))
        for actor in self.actors:
            actor.set_mission('attack', {'position': (0., 0., 20.)})
            self.accept(actor, 1.)
            self.assertEqual('capture_base', actor._mission['action'])
            self.assertEqual('ammunition_exhausted', actor._mission['reason'])
            self.assertEqual((0., 0., 40.), actor._mission['destination'])
        self.assert_same_task()

    def test_failed_implicit_task_retries_and_cannot_change_another_actor(self):
        self.other.set_mission('hold_position', {})
        other_before = copy.deepcopy(self.other.mission_status())
        self.defense['capture_bases']['2'] = []
        self.publish_defense()
        for actor in self.actors:
            self.accept(actor, 1., self.order('base_capture'))
            self.assertEqual(('failed', 'capture_circle_unavailable'),
                (actor._mission['status'], actor._mission['reason']))
            self.assertEqual(6., actor._implicit_retry['at'])
            held = actor.guard_mission_controls(dict(throttle=1., turn=1., fire_allowed=True))
            self.assertEqual((0., 0., False, False),
                (held['throttle'], held['turn'], held['brake'], held['fire_allowed']))
            self.accept(actor, 5., self.order('base_capture'))
            self.assertEqual(1, actor._implicit_failures)
            self.accept(actor, 6., self.order('base_capture'))
            self.assertEqual(2, actor._implicit_failures)
            self.assertEqual(16., actor._implicit_retry['at'])
        self.assert_same_task()
        self.assertEqual(other_before, self.other.mission_status())

    def test_explicit_timeout_lifecycle_and_command_projection_match(self):
        for actor in self.actors:
            actor.set_mission('return_base', {'command_id': 'return', 'timeout': 2.})
            rows = actor.mission_team_orders([dict(command_id='peer')])
            self.assertEqual('peer', rows[0]['command_id'])
            self.assertEqual('BACKTOBASE', rows[1]['command'])
            self.assertEqual([actor.actor_id], rows[1]['recipient_bot_ids'])
            self.assertEqual((0, 2000), (rows[1]['issued_tick'], rows[1]['expires_tick']))
            self.accept(actor, 2.)
            self.assertEqual('failed', actor._mission['status'])
            self.assertIsNone(actor._implicit_retry)
            actor._start_mission_lifecycle()
            self.assertIsNone(actor._mission)
            actor.set_mission('attack', {})
            actor._cancel_mission('manual')
            self.assertEqual(('cancelled', False),
                (actor._mission['status'], actor._mission['holding']))
        self.assert_same_task()

    def test_capture_terminal_uses_committed_battle_result(self):
        self.defense['battle_result'] = dict(reason='base captured', winner=1, base_team=2)
        self.publish_defense()
        for actor in self.actors:
            self.pose(actor, (0., 0., 40.))
            self.accept(actor, 1., self.order('base_capture'))
            self.assertEqual(('completed', 'captured'),
                (actor._mission['status'], actor._mission['phase']))
        self.assert_same_task()

    def test_equal_local_task_ids_keep_both_actors_in_shared_public_planning(self):
        # These local task receipts are not server radio IDs. The common
        # planner addresses them by recipient actor, not a global ID map.
        self.bot.set_mission('return_base', {})
        self.other.set_mission('attack', {})
        self.assertEqual(self.bot._mission['id'], self.other._mission['id'])
        commands = self.bot.mission_team_orders(self.other.mission_team_orders())
        result = self.engine.control_planner.build_orders(
            self.engine.control_manifest, list(self.engine.states.values()), [],
            1., defense=self.defense, team_orders=commands)
        orders = dict((row['id'], row) for row in result['orders'])
        self.assertEqual('BACKTOBASE', orders[self.bot.actor_id]['team_command'])
        self.assertEqual('ATTACK', orders[self.other.actor_id]['team_command'])
        self.assertEqual(self.bot._mission['id'],
                         orders[self.bot.actor_id]['team_command_id'])
        self.assertEqual(self.other._mission['id'],
                         orders[self.other.actor_id]['team_command_id'])

    def test_worker_arrival_uses_own_motion_and_unknown_support_never_settles(self):
        self.pose(self.bot, (0., 0., 0.))
        self.bot.set_mission('hold_position', {})
        self.bot._mission_support_known = False
        for now in (0., 1., 10.):
            self.accept(self.bot, now)
            self.assertEqual('running', self.bot._mission['status'])
            self.assertFalse(self.bot._mission_halt.receipt['known'])
        self.bot.record_support(False)
        self.bot.state.pop('suspension_roll_velocity')
        self.accept(self.bot, 11.)
        self.assertFalse(self.bot._mission_halt.receipt['known'])
        self.bot.state['suspension_roll_velocity'] = 0.
        self.accept(self.bot, 12.)
        self.accept(self.bot, 12.5)
        self.assertEqual('completed', self.bot._mission['status'])
        self.assertEqual([], self.worker_scene.observer_reads)


class SharedRestLawTests(unittest.TestCase):
    def motion(self):
        return dict(speed=0., turn_speed=0., pitch=0., roll=0.,
            pitch_speed=0., roll_speed=0., vertical_speed=0.,
            lateral_speed=(0., 0.), position=(0., 0., 0.), yaw=0.,
            airborne=False, support_rise_blocked=False, overturn_level=0)

    def test_thresholds_and_missing_observations_keep_the_same_rest_contract(self):
        for key, value in (('speed', .201), ('turn_speed', .021),
                ('vertical_speed', .201), ('pitch_speed', .021),
                ('roll_speed', .021), ('lateral_speed', (.201, 0.)),
                ('airborne', True), ('support_rise_blocked', True), ('overturn_level', 2)):
            observer = HaltObservation()
            motion = dict(self.motion(), **{key: value})
            self.assertFalse(observer.observe_motion(motion, 0.))
            self.assertFalse(observer.observe_motion(motion, 1.))
        for key in self.motion():
            observer = HaltObservation()
            motion = self.motion()
            del motion[key]
            self.assertFalse(observer.observe_motion(motion, 0.))
            self.assertFalse(observer.observe_motion(motion, 1.))
            self.assertFalse(observer.receipt['known'])
        for key in ('speed', 'turn_speed', 'pitch', 'roll', 'pitch_speed',
                    'roll_speed', 'vertical_speed', 'yaw', 'overturn_level'):
            observer = HaltObservation()
            motion = dict(self.motion(), **{key: float('nan')})
            self.assertFalse(observer.observe_motion(motion, 0.))
            self.assertFalse(observer.observe_motion(motion, 1.))
            self.assertFalse(observer.receipt['known'])
        observer = HaltObservation()
        self.assertFalse(observer.observe_motion(self.motion(), 0.))
        self.assertFalse(observer.observe_motion(self.motion(), .499))
        self.assertTrue(observer.observe_motion(self.motion(), .5))


if __name__ == '__main__':
    unittest.main()
