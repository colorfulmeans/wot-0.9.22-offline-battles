"""Opening route progress with the report 144204 map and observed hulls.

The foreground controller, navigation, pathfinder, local modifiers, driver,
traffic and final sender are real. Native aiming replays only blocked scans;
the native ground/BSP seam is explicit and still respects the map's dry
corridors. Production copied-physics and whole-hull collision helpers advance
the pose. This does not reproduce BigWorld suspension, timing or live gameplay.
"""
import math
from types import SimpleNamespace
import unittest
from unittest import mock

from test_player_navigation_completion import RealNavigationCase
from test_player_stationary_engagement import AimingBoundary
from test_player_stationary_waypoint import PLAYER_SHAPE, captured_pit_neighbours
from gui.mods.offline_lan_0922 import tank_collision, vehicle_physics
from gui.mods.offline_lan_0922.player_control import PlayerControl
from gui.mods.offline_lan_0922.player_control.traffic import TurnClearance, body


ORIGIN = (-34., .2581680409672512, -110.)
YAW = .029842
START = 35.020999908447266
ENEMIES = ((2130706456, (6., .3199999928474426, 94.)),
           (2130706452, (14., .28999999165534973, 118.)))


class BlockedOpeningScan(AimingBoundary):
    """The report never returned a target or a proved lane in 765 decisions."""
    def __init__(self, targets):
        super().__init__(targets[0])
        self.targets = targets
        self.target = None
        self.sample = self.confirmed = self.last_solution = None
        self.stage = None
        self.search_since = START

    def update(self, control, candidates, now):
        elapsed = now - START - 1.995
        if elapsed < 0.:
            self.target, self.checking, self.scan = None, False, None
        else:
            # Initial visibility, then the captured 1.353 s first switch and
            # roughly 2.959 s lock alternation. None ever supplies a shot proof.
            episode = 0 if elapsed < 1.353 else 1 + int((elapsed - 1.353) / 2.959)
            self.target = self.targets[episode % 2].id
            self.checking = int(elapsed / .11) % 14 != 13
            self.scan = dict(identity=(self.target, 0, 'full'), pending=[1, 2]) if self.checking else None
        return None, None, False


class OpeningPhysics(object):
    """Closed-loop copied-physics seam with real vehicle collision refusals.

    The report's PARAMS line 1502 supplies power, speed limits, terrain ratios
    and traverse limit; contact_chain supplies mass. Brake friction uses the
    existing physics defaults. The 1.2 m track gauge is an explicit fixture
    value, not a claimed descriptor measurement. Track-centred turning is
    retained because the captured stationary pivot translated the hull centre.
    """
    def __init__(self, neighbours):
        self.position, self.yaw, self.speed, self.omega = ORIGIN, YAW, 0., 0.
        self.now = START
        self.params = dict(vehicle_physics._DEFAULTS, mass=29148.,
            powerW=500. * 735.49875, speedFwd=55. / 3.6, speedBwd=20. / 3.6,
            terrainResist=(.998, 1.143, 1.670), rotSpd=.7783950319281508,
            rotationIsAroundCenter=False, trackCenter=1.2)
        self.peers = [body(row['id'], row['position'], row['yaw'], row['collision_shape'],
                           row['pitch'], row['roll']) for row in neighbours]
        self.refusals = []
        self.maximum_overlap = 0.
        self.distance = 0.

    def advance(self, sender, dt):
        remaining = dt
        while remaining > 1.e-9:
            step = min(remaining, .032)
            self.omega = vehicle_physics.traverse_step(self.params, self.omega,
                sender.turn, self.speed, step, drive_intent=sender.forward)
            old_yaw = self.yaw
            candidate_yaw = old_yaw + self.omega * step
            offset = vehicle_physics.track_pivot_offset(self.params, self.speed,
                self.omega, drive_intent=sender.forward)
            turn_fraction = tank_collision.rotation_fraction(self.position,
                old_yaw, candidate_yaw, PLAYER_SHAPE, self.peers, pivot_offset=offset)
            if turn_fraction < .999:
                self.refusals.append(('rotation', self.now, tuple(self.position)))
            self.yaw = old_yaw + (candidate_yaw - old_yaw) * turn_fraction
            turned = vehicle_physics.track_pivot_position(self.position, old_yaw, self.yaw, offset)
            self.speed = vehicle_physics.longitudinal_step(self.params, self.speed,
                sender.forward, sender.turn, 0., step, handbrake=sender.handbrake)
            movement = (math.sin(self.yaw) * self.speed * step,
                        math.cos(self.yaw) * self.speed * step)
            current = body(2130706436, turned, self.yaw, PLAYER_SHAPE)
            fraction = tank_collision.translation_fraction(current, movement, self.peers)
            if fraction < .999:
                self.refusals.append(('translation', self.now, tuple(turned)))
            following = (turned[0] + movement[0] * fraction, .25,
                         turned[2] + movement[1] * fraction)
            self.distance += math.hypot(following[0] - self.position[0],
                                        following[2] - self.position[2])
            self.position = following
            if fraction < 1.:
                self.speed *= fraction
            actual = body(2130706436, self.position, self.yaw, PLAYER_SHAPE)
            for peer in self.peers:
                contact = tank_collision.physical_planar_contact(actual, peer)
                if contact is not None:
                    self.maximum_overlap = max(self.maximum_overlap, contact[2])
            remaining -= step


class PlayerOpeningProgressTests(RealNavigationCase):
    def test_initial_blocked_contacts_preserve_real_map_route_progress(self):
        from test_player_control import PlayerRegressionTests
        nav = self.navigation('100_thepit', 'mediumTank', profile=dict(name='Default'),
                              ground=lambda *unused: .25)
        route = next(row for row in nav.routes if row['id'] == 'class_mt_rim_west')
        # Hold the observed initial route assignment fixed. Strategy transfer
        # parity has its own real-map tests; no mission bypasses combat here.
        nav.selection = [route]
        nav.opening_origin = ORIGIN
        neighbours = captured_pit_neighbours()
        physics = OpeningPhysics(neighbours)
        control, unused_target = PlayerRegressionTests().aim_controller()
        owner = control.owner
        entity = owner._server_entity(1)
        entity.id = 2130706436
        entity.typeDescriptor.type = SimpleNamespace(tags=('mediumTank',))
        entity.typeDescriptor.gun = SimpleNamespace()
        targets = [SimpleNamespace(id=identity, position=point, typeDescriptor=object(),
                                  health=1000, maxHealth=1000, isAlive=lambda: True)
                   for identity, point in ENEMIES]
        records = dict((target.id, target) for target in targets)
        owner._start_message = dict(map='100_thepit', round_id=1,
            bot_tactics=dict(name='Default'))
        owner._clock = lambda: physics.now
        owner.local_pose = lambda: (physics.position, physics.yaw)
        owner._collision_shape = lambda unused: PLAYER_SHAPE
        owner._local_physics = physics.params
        owner._local_pitch = owner._local_roll = owner._local_turn_speed = 0.
        owner._mutable_shot_ray = lambda: ((physics.position[0], physics.position[1] + 1.,
                                           physics.position[2]),
                                          (math.sin(physics.yaw), 0., math.cos(physics.yaw)))
        owner._tactical_ray_clear = lambda *unused: False

        def native_direction(position, heading, speed, descriptor, reach, width, **unused):
            # Native BSP is unavailable. The seam preserves the real baked
            # dry-corridor refusal; real Traffic additionally sweeps all hulls.
            reach = 5. if reach is None else reach
            end = (position[0] + math.sin(heading) * reach, .25,
                   position[2] + math.cos(heading) * reach)
            clear = nav.navigator.grid.dry_segment_clear(position, end, physics.now)
            return dict(clear=clear, collision=not clear, water=False, slope=0.)

        owner._direction_probe = native_direction
        del control.direction_clear  # Restore PlayerControl's native adapter.
        self.assertIs(control.direction_clear.__func__, PlayerControl.direction_clear)
        control.navigation = nav
        control.turn_clearance = TurnClearance()
        control.direct_engagement = BlockedOpeningScan(targets)
        control._contacts = lambda unused: ([], neighbours, records if physics.now >= START + 1.995 else {})
        control.firing_lane = control.lane_from = lambda *unused: False
        control.emit_result = mock.Mock(return_value=True)
        control.publish_status = mock.Mock()
        control.aiming.defer_ordered_point = mock.Mock()
        control.weapon.fired, control.weapon.committed = False, 0

        first_goal = route['waypoints'][1]
        closest = float('inf')
        modes, indices, trace = [], [], []
        # Keep observing after the bounded head-on/retreat leases expire.
        # This is an eventual-progress budget for the crowded fixture, not a
        # native driving-efficiency or frame-timing acceptance threshold.
        decision_step, maximum_elapsed = .11, 120.
        with mock.patch('gui.mods.offline_lan_0922.player_control.pathfinding.write_json_record'):
            for tick in range(int(math.ceil(maximum_elapsed / decision_step))):
                physics.now = START + tick * decision_step
                owner._local_speed, owner._local_turn_speed = physics.speed, physics.omega
                control.update(decision_step, physics.now)
                order = control.last_order
                modes.append(order.get('combat_mode'))
                indices.append(order.get('route_index'))
                sender = owner._sender
                self.assertEqual((order['throttle'], order['turn'], order['brake']),
                                 (sender.forward, sender.turn, sender.handbrake))
                physics.advance(sender, decision_step)
                span = math.hypot(physics.position[0] - first_goal[0],
                                  physics.position[2] - first_goal[1])
                closest = min(closest, span)
                if tick % 10 == 0:
                    trace.append((round(physics.now - START, 2), tuple(physics.position),
                        order.get('combat_mode'), order.get('route_index'),
                        order.get('recovery_mode'), order.get('local_target')))
                if order.get('route_index') is not None and order['route_index'] >= 2:
                    break

        evidence = dict(position=physics.position, closest=closest, trace=trace,
                        elapsed=physics.now - START, distance=physics.distance,
                        maximum_overlap=physics.maximum_overlap,
                        collision_refusal_count=len(physics.refusals),
                        collision_refusals=physics.refusals[:5])
        self.assertNotIn('advance_contact', modes, evidence)
        self.assertIsNone(control.engagement_hold)
        self.assertTrue(any(index is not None and index >= 2 for index in indices), evidence)
        self.assertLessEqual(closest, 6., evidence)
        self.assertGreater(math.hypot(physics.position[0] - ORIGIN[0],
                                     physics.position[2] - ORIGIN[2]), 30., evidence)
        self.assertLessEqual(physics.maximum_overlap, tank_collision.POSITION_SLOP + 1.e-7, evidence)
        self.assertEqual(0, control.weapon.trigger.call_count)


if __name__ == '__main__':
    unittest.main()
