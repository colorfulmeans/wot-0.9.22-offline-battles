"""Whole-body foreground cover, live-proof liveness and actual navigation use.

Real descriptors, player cover/pathfinding and mechanical envelopes are used.
The native terrain/ray functions are explicit geometry seams, not a claim of
Windows #1513 gameplay acceptance.
"""
import math
from types import SimpleNamespace
import unittest
from unittest import mock

from test_player_navigation_migration import controller, state
from test_player_navigation_independence import graph
from gui.mods.offline_lan_0922.player_control import cover
from gui.mods.offline_lan_0922.player_control.local_routes import LocalRoutes
from gui.mods.offline_lan_0922.player_control.navigation_support import PlayerHeightSupport
from gui.mods.offline_lan_0922.player_control.pathfinding import PlayerPathfinder


def descriptor():
    return SimpleNamespace(maxHealth=1000., type=SimpleNamespace(tags=('heavyTank',)),
        chassis=SimpleNamespace(hullPosition=(0., 0., 0.)),
        hull=SimpleNamespace(hitTester=SimpleNamespace(bbox=((-1., 0., -2.), (1., 1.4, 2.))),
                             turretPositions=((0., 1.4, 0.),)),
        turret=SimpleNamespace(hitTester=SimpleNamespace(bbox=((-0.7, 0., -1.), (.7, 1., 1.))),
                               gunPosition=(0., .3, 0.)),
        gun=SimpleNamespace(pitchLimits=dict(absolute=(-.5, .5),
                            minPitch=((0., -.5), (2.*math.pi, -.5)),
                            maxPitch=((0., .5), (2.*math.pi, .5))), turretYawLimits=None,
                            staticTurretYaw=None), activeTurretPosition=0)


class CoverScene(object):
    def __init__(self, crossfire=True):
        self.entity = SimpleNamespace(id=77, typeDescriptor=descriptor(), health=1000.)
        self.enemies = {}
        self.contacts, records = [], {}
        positions = ((0., 0., 40.), (40., 0., 0.)) if crossfire else ((0., 0., 40.),)
        for identity, point in enumerate(positions, 9):
            enemy = SimpleNamespace(id=identity, typeDescriptor=descriptor(), isStarted=True,
                isAlive=lambda: True, position=point,
                matrix=SimpleNamespace(yaw=0., pitch=0., roll=0.), aim=(0., 0.))
            enemy.getAimParams = lambda own=enemy: own.aim
            self.enemies[identity] = enemy
            self.contacts.append(dict(id=identity, position=point, yaw=0., pitch=0., roll=0.,
                visible=True, alive=True, health=1000., max_health=1000., team=2, turret_yaw=0.))
            records[str(identity)] = dict(engine_id=identity, ready=True, spot_visible=True,
                                         state=dict(team=2, turret_yaw=0.))
        self.owner = SimpleNamespace(client=SimpleNamespace(team=1, player_id=17),
            _avatar=SimpleNamespace(spaceID=1, gunRotator=SimpleNamespace(turretYaw=0., gunPitch=0.)),
            _start_message=dict(round_id=1),
            _player_control=SimpleNamespace(control_generation=1), _records=records,
            _server_entity=self.enemies.get, _water_depth=lambda point: 0.,
            _navigation_obstacle=lambda *args: False)
        self.search = cover.PlayerCover(self.owner)
        self.context = dict(contacts=self.contacts, supported=True, fire_clear=True,
                            gun_ready=True, fire_seq=0, allies=[], neighbours=[], turret_hulls=[])
        self.state = dict(state(), engine_id=77, pitch=0., roll=0.)
        self.owner.local_pose = lambda: (self.state['position'], self.state['yaw'])
        self.calls = []
        self.scene_revision = 1

    @property
    def target(self):
        return self.enemies[9]

    def ground(self, x, z, hint):
        self.calls.append(('ground', (x, z, hint)))
        return 0.

    def water(self, point):
        self.calls.append(('water', point))
        return 0.

    def segment(self, start, end):
        self.calls.append(('segment', (start, end)))
        return True

    def ray(self, start, end):
        self.calls.append(('ray', (start, end)))
        if abs(start[0]) > 30. or start[2] > 30.:
            return end[2] >= -4.
        return True

    def update(self, now, ray=None, ground=None):
        self.state['now'] = now
        return self.search.update(self.state, self.context, self.target, self.entity,
            self.ground if ground is None else ground, self.water, self.segment,
            self.ray if ray is None else ray, scene=lambda: self.scene_revision)

    def finish(self, ray=None, ground=None, maximum=30):
        for index in range(maximum):
            result = self.update(index * .1, ray=ray, ground=ground)
            if result is not None or self.search.receipt['status'] != 'pending':
                return result
        return None


class IndependentCoverTests(unittest.TestCase):
    def test_whole_body_samples_and_rotated_fan_match_the_real_vehicle(self):
        samples = cover.body_samples(descriptor())
        self.assertEqual(['hull', 'turret', 'hull', 'hull'], [row[0] for row in samples])
        first = cover.search_offsets(2., 4., 0)
        self.assertEqual(17, len(first))
        self.assertEqual(first[1:] + first[:1], cover.search_offsets(2., 4., 1))
        self.assertTrue(any(point[1] < -1. for point in first))
        self.assertTrue(any(point[1] > 1. for point in first))

    def test_hull_down_is_not_full_cover_when_second_visible_direction_exposes_the_body(self):
        scene = CoverScene()
        def incoming(start, end):
            scene.calls.append(('ray', (start, end)))
            if start[0] > 30.:
                return True
            if start[2] > 30.:
                return end[1] > 1.8
            return True
        self.assertIsNone(scene.finish(ray=incoming))
        self.assertEqual((9, 10), scene.search.receipt['threats'])
        origins = [row[1][0] for row in scene.calls if row[0] == 'ray']
        self.assertTrue(any(abs(point[1]-1.7) < 1.e-9 for point in origins))
        self.assertFalse(any(abs(point[1]-1.5) < 1.e-9 for point in origins))

    def test_second_threat_must_be_currently_visible_and_missing_mount_is_not_guessed(self):
        scene = CoverScene()
        scene.owner._records['10']['spot_visible'] = False
        observed = scene.search.observe(scene.state, scene.context, scene.target)
        self.assertEqual([9], [row['id'] for row in observed])
        scene.owner._records['10']['spot_visible'] = True
        scene.enemies[10].getAimParams = None
        self.assertIsNone(scene.search.observe(scene.state, scene.context, scene.target))
        scene.owner._records['10']['spot_visible'] = False
        del scene.contacts[0]['turret_yaw']
        del scene.owner._records['9']['state']['turret_yaw']
        scene.target.getAimParams = None
        self.assertIsNone(scene.search.observe(scene.state, scene.context, scene.target))
        self.assertIsNone(scene.update(0.))
        self.assertEqual('unavailable', scene.search.receipt['status'])

    def test_positive_prefix_survives_small_budget_and_unknown_never_means_cover(self):
        scene = CoverScene()
        scene.search.phase = 1
        ground_calls = []
        def ground(x, z, hint):
            ground_calls.append((x, z, hint))
            return 0.
        with mock.patch.object(cover, 'QUERY_BUDGET', 6):
            result = scene.finish(ground=ground)
        self.assertIsNotNone(result)
        self.assertLessEqual(scene.search.receipt['queries'], 6)
        self.assertEqual(len(ground_calls), len(set(ground_calls)))
        unknown = CoverScene()
        self.assertIsNone(unknown.finish(ray=lambda *args: None, maximum=40))
        self.assertNotEqual('ready', unknown.search.receipt['status'])

    def test_score_accounts_for_exposure_slope_congestion_and_reachable_peek(self):
        row = dict(travel_distance=8., route_alignment=.5, enemy_occlusion=1., exposure=.2,
                   slope=0., water=0., ally_congestion=0., peek_feasible=True, escape_feasible=True)
        best = cover.score_candidate(row)
        for changes in (dict(exposure=.7), dict(ally_congestion=1.), dict(slope=20.),
                        dict(peek_feasible=False), dict(water=1.)):
            self.assertGreater(best['score'], cover.score_candidate(dict(row, **changes))['score'])
        self.assertEqual(set(cover.WEIGHTS), set(best['breakdown']))

    def test_continuously_moving_source_and_threat_complete_expensive_fresh_candidate(self):
        scene = CoverScene()
        scene.search.phase = 1
        def expensive(start, end):
            scene.calls.append(('ray', (start, end)))
            if abs(start[0]) > 30. or start[2] > 30.:
                return end[2] >= -4. or end[0] < -2.
            return start[0] < -2.  # Only the third peek owns a firing lane.
        result, receipts = None, []
        for index in range(10):
            scene.state['position'] = (.02*index, 0., 0.)
            scene.target.position = (.1*index, 0., 40.+index)
            before = len(scene.calls)
            result = scene.update(index*.1, ray=expensive)
            receipts.append(dict(scene.search.receipt))
            self.assertLessEqual(len(scene.calls)-before, cover.FRESH_CANDIDATE_BUDGET)
            if result is not None:
                break
        self.assertIsNotNone(result)
        self.assertLessEqual(index, 4)
        self.assertTrue(any(row.get('fresh_candidate') for row in receipts))
        self.assertEqual(cover.FRESH_CANDIDATE_BUDGET, receipts[-1]['query_limit'])
        self.assertLess(result['peek'][0], -2.)
        self.assertEqual((9, 10), result['threats'])

    def test_scene_revision_churn_uses_same_bounded_fresh_candidate_path(self):
        scene = CoverScene()
        scene.search.phase = 1
        with mock.patch.object(cover, 'QUERY_BUDGET', 4):
            for index in range(8):
                scene.scene_revision += 1
                result = scene.update(index*.1)
                if result is not None:
                    break
        self.assertIsNotNone(result)
        self.assertTrue(scene.search.receipt['fresh_candidate'])

    def test_native_callback_cannot_publish_changed_owner_threat_or_scene_proof(self):
        for change in ('owner', 'threat', 'scene', 'source', 'own_turret', 'own_gun', 'enemy_angles'):
            with self.subTest(change=change):
                scene = CoverScene()
                scene.search.phase = 1
                changed = []
                def ray(start, end):
                    if not changed:
                        changed.append(True)
                        if change == 'owner':
                            scene.owner._avatar = SimpleNamespace(spaceID=1)
                        elif change == 'threat':
                            scene.target.position = (10., 0., 40.)
                        elif change == 'scene':
                            scene.scene_revision += 1
                        elif change == 'own_turret':
                            scene.owner._avatar.gunRotator.turretYaw = .3
                        elif change == 'own_gun':
                            scene.owner._avatar.gunRotator.gunPitch = .15
                        elif change == 'enemy_angles':
                            scene.target.aim = (.2, .1)
                        else:
                            scene.owner.local_pose = lambda: ((1., 0., 0.), 0.)
                    return scene.ray(start, end)
                with mock.patch.object(cover, 'QUERY_BUDGET', 84):
                    self.assertIsNone(scene.update(0., ray=ray))
                self.assertEqual('evidence_changed', scene.search.receipt['reason'])
                self.assertIsNone(scene.search.job)

    def test_real_turret_and_gun_angles_are_observed_and_missing_own_angles_stay_unknown(self):
        scene = CoverScene()
        scene.target.typeDescriptor.turret.gunPosition = (0., .3, 1.5)
        first = scene.search.observe(scene.state, scene.context, scene.target)[0]
        scene.target.aim = (math.pi/2., -.2)
        second = scene.search.observe(scene.state, scene.context, scene.target)[0]
        self.assertNotEqual(first['origin'], second['origin'])
        self.assertEqual((math.pi/2., -.2), (second['pose']['turret_yaw'], second['pose']['gun_pitch']))
        scene.owner._avatar.gunRotator.turretYaw = math.pi/2.
        scene.owner._avatar.gunRotator.gunPitch = -.1
        self.assertEqual((math.pi/2., -.1), scene.search.own_angles(scene.entity))
        scene.owner._avatar.gunRotator.gunPitch = None
        self.assertIsNone(scene.update(0.))
        self.assertEqual('unavailable', scene.search.receipt['status'])

    def test_retask_reset_during_native_query_cannot_publish_old_candidate(self):
        scene = CoverScene()
        scene.search.phase = 1
        changed = []
        def ray(start, end):
            if not changed:
                changed.append(True)
                scene.search.reset()
            return scene.ray(start, end)
        with mock.patch.object(cover, 'QUERY_BUDGET', 84):
            self.assertIsNone(scene.update(0., ray=ray))
        self.assertIsNone(scene.search.job)
        self.assertEqual('idle', scene.search.receipt['status'])

    def test_final_angle_or_scene_reader_reset_cannot_resurrect_proved_candidate(self):
        for reader in ('angles', 'scene'):
            with self.subTest(reader=reader):
                scene = CoverScene()
                scene.search.phase = 1
                calls = []
                original = scene.search.own_angles
                def reset_read(entity=None):
                    calls.append(True)
                    if len(calls) == 2:
                        scene.search.reset()
                    return original(entity) if reader == 'angles' else 1
                if reader == 'angles':
                    scene.search.own_angles = reset_read
                with mock.patch.object(cover, 'QUERY_BUDGET', 84):
                    result = scene.search.update(scene.state, scene.context, scene.target, scene.entity,
                        scene.ground, scene.water, scene.segment, scene.ray,
                        scene=reset_read if reader == 'scene' else lambda: 1)
                self.assertIsNone(result)
                self.assertIsNone(scene.search.job)
                self.assertEqual('idle', scene.search.receipt['status'])

    def test_same_decision_cannot_refill_budget_and_two_players_do_not_share_search(self):
        first, second = CoverScene(), CoverScene()
        with mock.patch.object(cover, 'QUERY_BUDGET', 2):
            first.update(0.)
            calls = len(first.calls)
            first.update(0.)
        self.assertEqual(calls, len(first.calls))
        self.assertIsNone(second.search.job)
        first.search.close()
        self.assertIsNone(first.search.owner)
        self.assertIsNotNone(second.search.owner)


class CoverNavigationConsumptionTests(unittest.TestCase):
    def navigation(self):
        scene = CoverScene()
        nav = controller()
        nav.navigator = PlayerPathfinder(lambda *args: 0., lambda *args: False, baked_graph=graph())
        self.addCleanup(nav.close)
        nav.support = PlayerHeightSupport(nav.navigator.grid, lambda *args: 0., None)
        nav.local_routes = LocalRoutes(nav.navigator, nav.support, 1)
        nav.cover_search = scene.search
        nav.set_context(scene.context)
        return nav, scene

    def test_actual_withdrawal_consumes_only_completed_whole_body_candidate_then_uses_own_navigation(self):
        nav, scene = self.navigation()
        gun = SimpleNamespace(clip_size=1, clip=1, reload_time=0.)
        with mock.patch.object(nav.navigator, 'next_target', wraps=nav.navigator.next_target) as routed:
            order = None
            for index in range(25):
                scene.state['now'] = index*.1
                order = nav.withdrawal(scene.state, scene.target, scene.entity, gun,
                                       lambda *args: True, scene.ray)
                if order is not None:
                    break
            self.assertIsNotNone(order)
            self.assertEqual('combat_cover', nav.cover_move['reason'])
            self.assertEqual((9, 10), nav.cover_move['threats'])
            self.assertIn('enemy_occlusion', nav.cover_move['breakdown'])
            self.assertTrue(order['travel_intent'])
            # Lateral/forward movement uses the private pathfinder; straight
            # reverse keeps the existing checked short-distance drive law.
            if order['throttle'] >= 0.:
                self.assertTrue(routed.called)
        scene.state.update(now=4., position=nav.cover_move['goal'])
        nav.withdrawal(scene.state, scene.target, scene.entity, gun, lambda *args: True, scene.ray)
        self.assertEqual('hold', nav.cover_move['phase'])
        scene.state['now'] = 5.1
        order = nav.withdrawal(scene.state, scene.target, scene.entity, gun, lambda *args: True, scene.ray)
        self.assertEqual('cover_peek', order['combat_mode'])

    def test_fresh_crossfire_retires_a_previously_valid_cover_hold(self):
        nav, scene = self.navigation()
        gun = SimpleNamespace(clip_size=1, clip=1, reload_time=0.)
        for index in range(25):
            scene.state['now'] = index*.1
            if nav.withdrawal(scene.state, scene.target, scene.entity, gun,
                              lambda *args: True, scene.ray) is not None:
                break
        scene.state.update(now=4., position=nav.cover_move['goal'])
        self.assertIsNone(nav.withdrawal(scene.state, scene.target, scene.entity, gun,
            lambda *args: True, lambda *args: True))
        self.assertIsNone(nav.cover_move)


if __name__ == '__main__':
    unittest.main()
