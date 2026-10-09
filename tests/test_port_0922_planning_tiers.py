"""Planning cadence uses live humans without changing physical detail."""
import copy
import math
import unittest
from unittest import mock

import test_port_0922_bot_runtime as bot_fixture
import test_port_0922_battle_runtime as battle_fixture
from test_port_0922_authority_worker_client import _human
from gui.mods.offline_lan_0922 import authority_worker, lan_client


class BotPlanningTierTests(unittest.TestCase):
    def setUp(self):
        self.base = bot_fixture.BotRuntimeTests('test_runtime_owned_numeric_helpers_do_not_reparse_state')
        self.base.setUp()
        self.module = self.base.module
        self.now = 10.0
        self.epoch = 1
        self.generation = 1
        self.descriptor = bot_fixture._combat_descriptor(
            reload_time=4.0, clip=(8, 2.0), max_ammo=30, dispersion=.01)
        self.descriptor.gun.burst = (3, .1)
        self.command = dict(target_yaw=0., throttle=0., turn=0., shell_index=0,
            fire_allowed=False, target_id=None, fire_range=500.,
            combat_mode='route', aim_position=(0., 1., 100.),
            face_position=(0., 0., 100.), move_position=(0., 0., 0.),
            recovery_mode='arrived', movement_intent=False)
        self.adapter = bot_fixture._FixedAdapter(self.command)
        self.runtime = self.module.BotRuntime(
            1, descriptor_resolver=lambda unused: self.descriptor,
            adapter_factory=lambda *unused, **kwargs: self.adapter,
            direction_probe=lambda *unused: {'clear': True, 'slope': 0.},
            visibility_probe=lambda *unused: False,
            firing_lane_probe=lambda *unused: True,
            friendly_lane_probe=lambda *unused: True,
            direct_launch_origin_probe=lambda state, *unused: (
                state['x'], state['y'] + 1., state['z']),
            ground_probe=lambda *unused: 0.,
            physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=bot_fixture._spawn_resolver,
            baked_graph=bot_fixture._flat_open_graph(),
            control_seconds=self.module.WORKER_CONTROL_SECONDS)
        self.start = dict(self.base.start)
        self.runtime.battle_start(self.start)
        self.runtime.states[11].update(x=0., y=0., z=0., yaw=0., speed=0.,
            pitch=0., roll=0., terrain_pitch=0., grounded_once=True,
            turret_yaw=0., aim_yaw=0., gun_pitch=0.)
        self.runtime._next_observation = 1000.
        self.runtime._next_shot_lane_refresh = 1000.
        self.runtime._next_cover_refresh = 1000.

    def tearDown(self):
        self.runtime.close()
        self.base.tearDown()

    def human(self, identity=2, x=500., z=0., sequence=1, **values):
        result = dict(id=identity, team=1, participating=True, world_pose=True,
            alive=True, x=float(x), y=0., z=float(z), yaw=0., speed=0.,
            input_seq=sequence, health=1000, max_health=1000)
        result.update(values)
        return bot_fixture._admit_player(result)

    def snapshot(self, rows, round_id=None):
        return dict(round_id=self.runtime.round_id if round_id is None else round_id,
            authority_epoch=self.epoch, players=copy.deepcopy(rows))

    def step(self, rows, dt=.1, advance=True, message=None):
        if advance:
            self.now += dt
        self.runtime.set_planning_snapshot(
            self.snapshot(rows) if message is None else message,
            self.now, self.generation)
        physics = [row for row in rows if row.get('world_pose') is True and
            row.get('participating') is True and row.get('id', -1) > 0 and
            all(isinstance(row.get(key), (int, float)) and
                math.isfinite(row[key]) for key in ('x', 'y', 'z'))]
        return self.runtime.update(dt, self.now, players=physics)

    def warm(self, rows):
        self.runtime.set_planning_snapshot(self.snapshot(rows), self.now-.1,
                                           self.generation)
        for row in rows:
            row['input_seq'] += 1
        self.step(rows, advance=False)
        return rows

    def next_decision(self, rows):
        previous = self.runtime._decision_counts.get(11, 0)
        for unused in range(15):
            for row in rows:
                row['input_seq'] += 1
            self.step(rows)
            if self.runtime._decision_counts.get(11, 0) != previous:
                return
        self.fail('decision did not arrive')

    def test_live_worker_keeps_release_cadence_at_all_player_distances(self):
        for distance in (0., 149., 150., 151., 349., 350., 351., 1000.):
            with self.subTest(distance=distance):
                self.runtime.states[11].update(x=0., z=0.)
                rows=[self.human(x=distance, sequence=1)]
                self.step(rows)
                rows[0]['input_seq']=2
                self.step(rows)
                state=self.runtime.states[11]
                self.assertEqual(self.runtime._detail_tier(state),
                                 self.runtime._planning_detail_tier(state))
                self.assertEqual(0,self.runtime._planning_detail_tier(state))
                self.assertEqual(self.module.DECISION_SECONDS,
                                 self.runtime._planning_decision_intervals[11])

    def test_existing_camera_tiers_are_retained(self):
        self.runtime.set_camera_position((1000.,0.,0.))
        state=self.runtime.states[11]
        self.assertEqual(2,self.runtime._detail_tier(state))
        self.assertEqual(self.runtime._detail_tier(state),
                         self.runtime._planning_detail_tier(state))

    def test_unknown_or_stale_observers_cannot_extend_decision_interval(self):
        self.runtime.set_planning_snapshot(self.snapshot([]),self.now,self.generation)
        self.step([])
        self.assertEqual(self.module.DECISION_SECONDS,
                         self.runtime._planning_decision_intervals[11])


if __name__ == '__main__':
    unittest.main()
