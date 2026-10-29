"""T29/Tiger wreck rotation and Bat-Chat 12t passive rejection boundaries."""
import contextlib
import io
import json
import math
import os
import types
import unittest
from unittest import mock

import test_port_0922_bot_runtime as fixture


class PassiveWreckPoseTests(unittest.TestCase):
    setUp = fixture.ShovedWreckTests.setUp
    tearDown = fixture.ShovedWreckTests.tearDown

    def worker(self, status='clear'):
        worker = self.module.BotRuntime.__new__(self.module.BotRuntime)
        worker.round_id = 5
        worker._descriptors = {}
        worker._combat_diagnostics = None
        worker._contact_now = 1.0
        worker._physics_ground_probe = lambda *args: 0.
        worker._contact_motion_bodies = lambda unused: []
        worker._contact_motion_body = lambda state: dict(
            id=state['id'], x=state['x'], y=state['y'], z=state['z'],
            yaw=state['yaw'], shape=state['collision_shape'])
        worker._baked_pose_progress_clear = mock.Mock(return_value=True)
        worker._turret_pose_is_clear = mock.Mock(return_value=True)
        worker._wreck_rotation_probe = mock.Mock(return_value=True)
        worker._probe_timing_enabled = lambda: False
        worker.motion_resolver = mock.Mock(return_value=status)
        return worker

    def state(self, yaw=1.24765, relative=2.262):
        return dict(id=16, alive=False, x=0., y=0., z=0., yaw=yaw,
            aim_yaw=self.angle(yaw+relative), turret_yaw=relative,
            gun_pitch=.018, speed=0., push_x=0., push_z=0., push_yaw=0.,
            collision_shape=(1.7, 3.5), mass=29300., movement_dir=1)

    @staticmethod
    def angle(value):
        return math.atan2(math.sin(value), math.cos(value))

    def assert_pose(self, state, relative):
        # Native presentation derives relative yaw from the published world
        # direction; projectile collision consumes the retained relative yaw.
        displayed = self.angle(state['aim_yaw']-state['yaw'])
        self.assertAlmostEqual(relative, displayed)
        self.assertAlmostEqual(relative, state['turret_yaw'])
        self.assertEqual(.018, state['gun_pitch'])

    def test_both_rotation_paths_preserve_relative_aim_across_pi(self):
        for coupled in (False, True):
            for yaw, turn in ((1.24765, .38762), (3.13, .3), (-3.13, -.3)):
                with self.subTest(coupled=coupled, yaw=yaw):
                    worker = self.worker(); state = self.state(yaw)
                    with mock.patch.object(self.module.tank_collision,
                            'rotation_fraction', return_value=1.):
                        if coupled:
                            self.assertTrue(worker._try_wreck_swept_pose(
                                state, (.1, .2), turn, 1.))
                        else:
                            worker._advance_wreck_yaw(state, {'delta_yaw':turn}, 1.)
                    self.assertAlmostEqual(self.angle(yaw+turn), state['yaw'])
                    self.assert_pose(state, 2.262)

    def test_sweep_refusal_leaves_all_angles_and_position_unchanged(self):
        for gate in ('vehicle', 'baked', 'turret', 'world', 'rotation'):
            worker = self.worker('hard' if gate=='world' else 'clear')
            worker._baked_pose_progress_clear.return_value = gate!='baked'
            worker._turret_pose_is_clear.return_value = gate!='turret'
            worker._wreck_rotation_probe.return_value = gate!='rotation'
            state = self.state(); before = dict(state)
            with mock.patch.object(self.module.tank_collision,
                    'rotation_fraction', return_value=0. if gate=='vehicle' else 1.):
                self.assertFalse(worker._try_wreck_swept_pose(state, (.1,.2), .3, 1.))
            for key in ('x','y','z','yaw','aim_yaw','turret_yaw','gun_pitch'):
                self.assertEqual(before[key],state[key], (gate,key))

    def test_vertical_rollback_restores_world_aim_as_well_as_hull(self):
        worker = self.worker(); state = self.state(); before = dict(state)
        worker._physics_params_for = lambda unused: None
        worker._update_vertical_motion = mock.Mock(return_value=True)
        with mock.patch.object(self.module.tank_collision,
                'rotation_fraction', return_value=1.), mock.patch('sys.stdout'):
            worker._apply_wreck_contact_response(state, dict(
                delta_velocity=(1., .5), correction=(0.,0.), delta_yaw=.3), 1.)
        for key in ('x','y','z','yaw','aim_yaw','turret_yaw','gun_pitch'):
            self.assertAlmostEqual(before[key],state[key],key)

    def test_passive_status_contract_admits_crushed_but_not_pending_commit(self):
        for status in ('clear','crushed','soft','hard','commit_required'):
            for coupled in (False, True):
                worker = self.worker(status); state = self.state()
                with mock.patch.object(self.module.tank_collision,
                        'rotation_fraction', return_value=1.), \
                     mock.patch.object(self.module.tank_collision,
                        'translation_fraction', return_value=1.), \
                     mock.patch.object(self.module.tank_collision,
                        'slide_translation', side_effect=lambda body, move, peers, **kw:move), \
                     mock.patch('sys.stdout'):
                    if coupled:
                        moved = worker._try_wreck_swept_pose(state, (.1,.2), .3, 1.)
                    else:
                        worker._apply_tank_contact_response(state, dict(
                            delta_velocity=(1.,.5), correction=(0.,0.)), .1,
                            apply_friction=False)
                        moved = bool(state['x'] or state['z'])
                self.assertEqual(status in ('clear','crushed'),moved,(status,coupled))
                self.assertEqual(1,state['movement_dir'])
                self.assertAlmostEqual(1.24765,worker.motion_resolver.call_args.args[2])

    def test_diagnostic_status_is_lazy_bounded_and_preserves_result(self):
        worker = self.worker('soft'); state = self.state()
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_DIAGNOSTICS':'0'}):
            self.assertEqual('soft',worker._passive_motion_status(
                state,(0.,0.,0.),.5,1.,None,.1,1.))
        self.assertFalse(hasattr(worker,'_battle_review_records'))
        output = io.StringIO()
        with mock.patch.dict(os.environ, {'WOT_OFFLINE_DIAGNOSTICS':'1'}), \
                contextlib.redirect_stdout(output):
            for tick in range(100):
                self.assertEqual('soft',worker._passive_motion_status(
                    state,(0.,0.,0.),.5,1.,None,.1,1.+tick*.01))
        rows=[json.loads(line.split('BATTLE REVIEW ',1)[1])
              for line in output.getvalue().splitlines() if 'BATTLE REVIEW {' in line]
        self.assertEqual(1,len(rows))
        self.assertEqual('soft',rows[0]['raw_status'])
        self.assertFalse(rows[0]['admitted'])
        self.assertEqual(1,state['movement_dir'])


class WreckLaneEvidenceTests(unittest.TestCase):
    def test_real_lane_path_records_clear_and_blocked_without_extra_collision_queries(self):
        import test_port_0922_battle_runtime as battle
        for diagnostics in (False,True):
            for blocked in (False,True):
                runtime=battle.NativeBattleRuntime.__new__(battle.NativeBattleRuntime)
                runtime.client=types.SimpleNamespace(round_id=1)
                runtime._last_frame_time=3.
                runtime._vector=lambda value:value
                matrix=mock.Mock(side_effect=lambda value:value)
                runtime._runtime=types.SimpleNamespace(math=types.SimpleNamespace(Matrix=matrix))
                vehicle=types.SimpleNamespace(
                    collideSegmentExt=mock.Mock(return_value=[object()] if blocked else []),
                    appearance=types.SimpleNamespace(
                        turretMatrix=types.SimpleNamespace(yaw=2.262),
                        gunMatrix=types.SimpleNamespace(pitch=.018)))
                record=dict(engine_id=44,network_id=16,state=dict(alive=False),
                    projectile_collision_pose=dict(turret_yaw=2.262))
                output=io.StringIO()
                with mock.patch.dict(os.environ,{'WOT_OFFLINE_DIAGNOSTICS':'1' if diagnostics else '0'}), \
                        contextlib.redirect_stdout(output):
                    result=runtime._bot_lane_row_contact(
                        [(record,vehicle,(0.,0.,0.))],[(-1.,0.,0.),(1.,0.,0.)])
                self.assertEqual(blocked,result is not None)
                self.assertEqual(1,vehicle.collideSegmentExt.call_count)
                self.assertEqual(2*int(diagnostics),matrix.call_count)
                if diagnostics:
                    row=json.loads(output.getvalue().split('BATTLE REVIEW ',1)[1])
                    self.assertEqual('wreck_firing_lane',row['stage'])
                    self.assertEqual(1,row['round'])
                    self.assertEqual(blocked,row['blocked'])
                    self.assertEqual([2.262,.018],row['native_aim'])
                else:
                    self.assertNotIn('BATTLE REVIEW',output.getvalue())


if __name__ == '__main__':
    unittest.main()
