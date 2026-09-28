"""Report 115952: solid motion across live, wreck and native world owners."""
import math
import unittest
from unittest import mock

from test_port_0922_tank_collision import tank_collision as contact, _tank
import test_port_0922_bot_runtime as bot_tests


class TranslationSweepTests(unittest.TestCase):
    def test_visible_drive_and_residual_push_stop_at_the_actual_remote_hull(self):
        import test_port_0922_battle_runtime as t
        for alive in (True, False):
            for hz in (25,60,144):
                runtime = t._runtime()
                battle = t.BattleRuntime(runtime)
                battle.client = t._Client()
                battle._avatar = runtime.bigworld.avatar
                battle._local_physics = dict(t._effective_params_snapshot()['physics'],mass=100575.)
                local = t._Vehicle(10,t._Descriptor(),t._Vector(),(0,0,0),{'health':500})
                peer = _tank(1000011,0.,8.,mass=31370.)
                peer.update(network_id=11,kind='bot',alive=alive)
                battle._collision_shape = lambda unused: contact.DEFAULT_SHAPE
                battle._contact_tanks = lambda *args, **kw: [peer]
                battle._motion_is_clear = lambda *args, **kw: True
                battle._baked_pose_safe = lambda *args: True
                battle._poll_local_ram_contact_episodes = lambda *args: None
                position = (0.,0.,0.)
                with mock.patch('sys.stdout'):
                    for unused in range(hz):
                        battle._local_speed = 10.
                        battle._local_contact_start_position = position
                        position = battle._resolve_local_tank_contacts(
                            local,(0.,0.,position[2]+10./hz),0.,1./hz)
                        self.assertLessEqual(position[2],1.0101)
                for row in battle._local_contact_pushes.values():
                    self.assertEqual([0.,0.],row[4:])

    def test_a_clear_endpoint_cannot_skip_an_intervening_hull(self):
        for yaw in (0., .7, math.pi/2, -2.1):
            for distance in (10., 100.):
                with self.subTest(yaw=yaw, distance=distance):
                    moving = _tank(1, 0., 0.)
                    blocker = _tank(2, 0., 8., yaw=yaw)
                    fraction = contact.translation_fraction(moving, (0., distance), [blocker])
                    self.assertGreater(fraction, 0.)
                    self.assertLess(fraction, 1.)
                    hit = contact.obb_contact(0., distance*fraction, 0., moving['shape'],
                                              0., 8., yaw, blocker['shape'])
                    self.assertAlmostEqual(contact.POSITION_SLOP, hit[2], places=8)

    def test_overlap_can_escape_or_slide_but_cannot_deepen(self):
        a, b = _tank(1, 0., 0.), _tank(2, 0., 6.)
        self.assertEqual(1., contact.translation_fraction(a, (0., -100.), [b]))
        self.assertEqual(1., contact.translation_fraction(a, (10., 0.), [b]))
        self.assertEqual(0., contact.translation_fraction(a, (0., 100.), [b]))
        b['y'] = 20.
        self.assertEqual(1., contact.translation_fraction(a, (0., 100.), [b]))

    def test_position_ownership_cannot_change_the_mass_weighted_impulse(self):
        for first_mass, second_mass in ((100575., 31370.), (31370., 100575.)):
            a = _tank(1, 0., 0., mass=first_mass, vz=10.)
            b = _tank(2, 0., 6.9, mass=second_mass)
            free = contact.resolve_pairs([a,b], .1)
            b['position_fixed'] = True
            fixed = contact.resolve_pairs([a,b], .1)
            for actor in (1,2):
                self.assertEqual(free[actor]['delta_velocity'], fixed[actor]['delta_velocity'])
            self.assertEqual((0.,0.), fixed[2]['correction'])
            total = first_mass*fixed[1]['delta_velocity'][1] + second_mass*fixed[2]['delta_velocity'][1]
            self.assertAlmostEqual(0., total, places=6)


class WorkerSolidMotionTests(unittest.TestCase):
    setUp = bot_tests.ShovedWreckTests.setUp
    tearDown = bot_tests.ShovedWreckTests.tearDown
    _runtime = bot_tests.ShovedWreckTests._runtime

    def prepare(self):
        runtime = self._runtime()
        for i, z in ((11,0.), (12,8.)):
            runtime.states[i].update(x=0.,y=0.,z=z,yaw=0.,speed=0.,
                pitch=0.,roll=0.,push_x=0.,push_z=0.,collision_shape=contact.DEFAULT_SHAPE)
        runtime._clear = lambda *args: True
        return runtime

    def test_a_shoved_wreck_cannot_cross_a_third_vehicle(self):
        runtime = self.prepare()
        state = runtime.states[11]
        state['alive'] = False
        runtime._bleed_contact_push = lambda state,x,z,dt: (x,z)
        runtime._apply_tank_contact_response(state,
            {'delta_velocity': (0.,100.), 'correction': (0.,20.)}, .1)
        self.assertAlmostEqual(1.01, state['z'], places=8)
        self.assertLess(state['z'], runtime.states[12]['z'])

    def test_native_hull_sweep_vetoes_a_nudge_missed_by_planning_rays(self):
        for step in (0., .1):
            runtime = self.prepare()
            runtime.states.pop(12)
            state = runtime.states[11]
            state['movement_dir'] = 1
            seen = []
            def wall(actor, position, yaw, speed, descriptor, dt, now,
                     commit_enabled, motion_yaw=None):
                seen.append((actor, speed*dt, descriptor, commit_enabled, motion_yaw))
                self.assertEqual(0, state['movement_dir'])
                return 'hard'
            runtime.motion_resolver = wall
            runtime._apply_tank_contact_response(state,
                {'delta_velocity': (0.,0.), 'correction': (.2,.3)}, step)
            self.assertEqual((0.,0.), (state['x'],state['z']))
            self.assertEqual(1, state['movement_dir'])
            self.assertEqual(1, len(seen))
            self.assertAlmostEqual(math.hypot(.2,.3), seen[0][1])
            self.assertIs(runtime._descriptors[11], seen[0][2])
            self.assertFalse(seen[0][3])
            self.assertAlmostEqual(math.atan2(.2,.3), seen[0][4])

    def test_drive_sweep_keeps_a_live_player_solid_with_receipt_transport(self):
        runtime = self.prepare()
        runtime.states.pop(12)
        state = runtime.states[11]
        runtime._player_collision_profile = lambda raw: dict(
            mass=100575.,shape=contact.DEFAULT_SHAPE,ram_profile={},
            physics=runtime._physics_params_for(11))
        player = dict(id=1,x=0.,y=0.,z=8.,yaw=0.,alive=True,speed=0.,
                      team=1,tank_pushes=[])
        state['z'] = 20.
        state['speed'] = 10.
        runtime._guard_tank_translations([player], {11:(0.,0.,0.)})
        self.assertAlmostEqual(1.01,state['z'])
        runtime._resolve_tank_contacts([player],1.,.1)
        self.assertLessEqual(state['z'],1.011)

    def test_contact_recovery_cannot_ignore_a_live_player(self):
        runtime = self.prepare()
        runtime.states.pop(12)
        runtime._player_collision_profile = lambda raw: dict(
            mass=100575.,shape=contact.DEFAULT_SHAPE,ram_profile={},
            physics=runtime._physics_params_for(11))
        player = dict(id=1,x=0.,y=0.,z=-6.,yaw=0.,alive=True,speed=0.,
                      team=1,tank_pushes=[])
        runtime._resolve_tank_contacts([player],1.,.1)
        self.assertGreater(runtime.states[11]['z'],.9899)

    def test_opposing_drive_endpoints_cannot_exchange_sides(self):
        runtime = self.prepare()
        for state in runtime.states.values():
            state['speed'] = 100.
        runtime.states[11]['z'], runtime.states[12]['z'] = 20., -12.
        runtime._guard_tank_translations([], {11:(0.,0.,0.),12:(0.,0.,8.)})
        self.assertLess(runtime.states[11]['z'],runtime.states[12]['z'])
        runtime._resolve_tank_contacts([],1.,.1)
        self.assertLess(runtime.states[11]['z'],runtime.states[12]['z'])

    def test_wreck_and_bot_stay_out_of_each_other_and_the_world_under_repeated_push(self):
        runtime = self.prepare()
        wreck, bot = runtime.states[11], runtime.states[12]
        wreck['alive'] = False
        wall_z = bot['z']
        def wall(actor, position, yaw, speed, descriptor, dt, now,
                 commit_enabled, motion_yaw=None):
            end = position[2] + math.cos(motion_yaw)*abs(speed)*dt
            return 'hard' if actor == 12 and end > wall_z+1.e-9 else 'clear'
        runtime.motion_resolver = wall
        with mock.patch('sys.stdout'):
            for index in range(100):
                runtime._apply_tank_contact_response(wreck,
                    {'delta_velocity': (0.,2.), 'correction': (0.,0.)}, 0.,
                    advance_push=False, apply_correction=False)
                runtime._resolve_tank_contacts([], index*.1, .1)
                self.assertLessEqual(bot['z'],wall_z+1.e-8)
                hit = contact.obb_contact(wreck['x'],wreck['z'],0.,wreck['collision_shape'],
                                          bot['x'],bot['z'],0.,bot['collision_shape'])
                self.assertTrue(hit is None or hit[2] <= contact.POSITION_SLOP+1.e-6)
