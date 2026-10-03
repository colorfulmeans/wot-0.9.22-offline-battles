"""Physical withdrawal through the production adapter/runtime, with engine stubs."""
import contextlib
import io
import unittest
import test_port_0922_bot_runtime as harness


class RuntimeWithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = harness.BotRuntimeTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_reverse_stopping_uses_signed_grade_and_a_distinct_cache_entry(self):
        runtime = self.fixture.module.BotRuntime(1)
        params = self.fixture.module.vehicle_physics.derive_params({})
        source = dict(id=11, speed=10., last_drive_pitch=.05)
        forward = runtime._cached_traffic_stopping_distance(source, dict(turn=0.), params)
        source['speed'] = -10.
        reverse = runtime._cached_traffic_stopping_distance(source, dict(turn=0.), params)
        self.assertNotEqual(forward, reverse)
        source['last_drive_pitch'] = -.05
        mirrored = runtime._cached_traffic_stopping_distance(source, dict(turn=0.), params)
        self.assertNotEqual(reverse, mirrored)
        self.assertGreater(mirrored, 0.)

    def test_limited_gun_backs_toward_cover_and_keeps_front_on_received_enemy(self):
        descriptor = harness._combat_descriptor(turret_yaw_limits=(-.1, .1))
        runtime = self.fixture.module.BotRuntime(
            1, descriptor_resolver=lambda unused: descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            visibility_probe=lambda *unused: True,
            firing_lane_probe=lambda *unused: True,
            baked_graph=harness._flat_open_graph())
        runtime.battle_start(self.fixture.start)
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            id=11, team=2, combat_mode='low_health_retreat', target_kind='human',
            target_id=2, move_position=(0., 0., -20.),
            aim_position=(0., 0., 100.), face_position=(0., 0., 100.),
            fire_range=500., fire_allowed=True, throttle_override=None)]))
        player = harness._admit_player(dict(
            id=2, team=1, alive=True, x=0., y=0., z=100.))
        headings, modes = [], set()
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 121):
                runtime.update(.05, frame*.05, players=[player])
                headings.append(runtime.states[11]['yaw'])
                modes.add(runtime._decision_cache[11][3]['recovery_mode'])
        state = runtime.states[11]
        self.assertLess(state['z'], -5.)
        self.assertLess(max(abs(yaw) for yaw in headings), .1)
        self.assertIn('reverse_withdraw', modes)
        self.assertGreater(state['z'], -22.)
        self.assertFalse(state['hull_aiming'])


    def contact_runtime(self, peer_position, mode):
        descriptor = harness._combat_descriptor(turret_yaw_limits=(-.1, .1))
        runtime = self.fixture.module.BotRuntime(
            1, descriptor_resolver=lambda unused: descriptor,
            direction_probe=lambda *unused: dict(clear=True, slope=0.),
            ground_probe=lambda *unused: 0., physics_ground_probe=lambda *unused: 0.,
            spawn_resolver=lambda *unused: ((0., 0., 0.), 0.),
            baked_graph=harness._flat_open_graph())
        start = dict(self.fixture.start)
        start['bots'] = [dict(id=11, team=2, slot=0, name='Bot'),
                         dict(id=12, team=2, slot=1, name='Wreck')]
        runtime.battle_start(start)
        for state in runtime.states.values():
            state.update(yaw=0., speed=0., grounded_once=True,
                         collision_shape=(1.5, 3.5, -.8, 2.),
                         half_length=3.5, half_width=1.5)
        runtime.states[12].update(alive=False, health=0.,
                                 x=peer_position[0], y=0., z=peer_position[2])
        runtime._apply_orders(dict(bot_order_revision=1, bot_orders=[dict(
            id=11, team=2, combat_mode=mode,
            move_position=(0., 0., 100.) if mode=='route' else (0., 0., 0.),
            aim_position=(100., 0., 0.), face_position=(100., 0., 0.),
            fire_range=500., fire_allowed=False,
            throttle_override=None if mode=='route' else 0.)]))
        return runtime

    def test_side_wreck_firing_hold_uses_real_adapter_and_integrated_exit(self):
        runtime = self.contact_runtime((2.99, 0., 0.), 'engage')
        modes=set()
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 81):
                runtime.update(.05, frame*.05)
                modes.add(runtime._decision_cache[11][3]['recovery_mode'])
        self.assertIn('contact_escape', modes)
        self.assertGreater(abs(runtime.states[11]['z']), 1.)

    def test_front_wreck_push_spends_motor_force_in_contact_solver(self):
        runtime = self.contact_runtime((0., 0., 6.99), 'route')
        # A lighter passive body proves that admitted controls reach the real
        # contact solver. An equal/heavier wreck is allowed to resist the push.
        runtime.states[12]['mass'] = 1500.
        modes=set()
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(1, 61):
                runtime.update(.05, frame*.05)
                modes.add(runtime._decision_cache[11][3]['recovery_mode'])
        self.assertIn('wreck_push', modes)
        self.assertGreater(runtime.states[11]['z'], .1)
        self.assertGreater(runtime.states[12]['z'], 7.1)


if __name__ == '__main__':
    unittest.main()
