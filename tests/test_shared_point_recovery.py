"""Selected-point recovery and checked native-geometry destination previews.

The owner seam tests bounded travel/recheck/route handoff; analytic native
components test the actual future-ray adapter without claiming Windows proof.
"""
import contextlib
import io
import unittest

from test_player_combat_stop import Scene
from test_player_combat_ownership import OwnershipScene


class PointRecoveryTests(unittest.TestCase):
    def scene(self, outcomes=None):
        scene = Scene()
        # Isolate the downstream consumer from authored-route confirmation.
        scene.owner._route_requires_confirmation = lambda order: False
        scene.raw_order.update(combat_mode='route', target_id=None, target_kind=None,
            move_position=(20., 0., -30.), throttle_override=None,
            aim_position=None, fire_allowed=False)
        scene.state['collision_shape'] = (1.7, 3.5, -.8, 2.)
        scene.candidate.update(sample=0, key=(0, ('bot', 2), 0, 'penetration'))
        scene.probes = []
        outcomes = list(outcomes or ())

        def probe(candidate, destination, now):
            scene.probes.append((candidate['key'], tuple(destination), now))
            value = outcomes.pop(0) if outcomes else dict(status='clear')
            return dict(value, position=tuple(destination), fire_permission=False)

        scene.runtime.point_recovery_probe = probe
        return scene

    def test_planning_positive_does_not_retire_unconfirmed_recovery(self):
        scene = self.scene()
        scene.apply(0.)
        original = scene.owner._physical_recovery
        self.assertIsNotNone(original)
        scene.candidate.update(line='clear', mechanical='reachable', armor='passed')
        scene.decide('aim')
        scene.apply(.1)
        self.assertIs(original, scene.owner._physical_recovery,
            'planning success must not destroy the task before actual geometry is checked')

    def test_policy_navigation_terminal_releases_authored_route(self):
        scene = self.scene()
        scene.apply(0.)
        scene.decide('navigate', candidate=False, reason='no_he_or_verified_penetration')
        result = scene.apply(.1)
        self.assertFalse(scene.owner.combat_owned)
        self.assertFalse(scene.owner.stop_allowed)
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        self.assertNotIn('_combat_movement_owner', scene.state)

    def test_pending_probe_never_selects_an_unchecked_destination(self):
        scene = self.scene((dict(status='pending'), dict(status='blocked'),
                            dict(status='clear')))
        order = scene.apply(0.)
        phase = scene.owner._physical_recovery
        self.assertEqual('engage', order['combat_mode'])
        self.assertIsNone(phase['goal'])
        self.assertEqual(0, phase['cursor'])
        self.assertEqual(1, len(scene.probes))
        order = scene.apply(.1)
        self.assertEqual('gun_angle_adjust', order['combat_mode'])
        self.assertEqual(2, phase['cursor'])
        self.assertEqual(phase['goal'], order['move_position'])
        self.assertEqual(3, len(scene.probes))
        self.assertFalse(order['fire_allowed'])

    def test_all_positions_fail_then_changed_geometry_requires_a_new_positive_probe(self):
        scene = self.scene([dict(status='blocked')] * 45)
        result = None
        for tick in range(15):
            result = scene.apply(tick * .1)
            if not scene.owner.combat_owned:
                break
        self.assertFalse(scene.owner.combat_owned)
        self.assertEqual('route', result['combat_mode'])
        self.assertEqual((20., 0., -30.), result['move_position'])
        count = len(scene.probes)
        # No one-shot failed task may instantly become the same parked task.
        for tick in range(15, 20):
            self.assertEqual('route', scene.apply(tick * .1)['combat_mode'])
        self.assertEqual(count, len(scene.probes))
        scene.position((1., 0., 0.))
        result = scene.apply(2.)
        self.assertFalse(scene.owner.combat_owned)
        self.assertTrue(scene.owner.physical_recovery_pending())
        scene.runtime.point_recovery_probe = lambda *args: dict(status='clear')
        result = scene.apply(2.1)
        self.assertTrue(scene.owner.combat_owned)
        self.assertTrue(scene.owner.stop_allowed)
        self.assertIsNotNone(scene.owner._physical_recovery)
        self.assertFalse(result['fire_allowed'])

    def test_expired_ready_without_reloading_returns_to_bounded_recheck(self):
        scene = self.scene()
        scene.apply(0.)
        phase = scene.owner._physical_recovery
        phase.update(goal=None, ready=True, verified_at=0.)
        scene.decide('wait', candidate=False, reason='native_line_refresh')
        result = scene.apply(.1)
        self.assertFalse(phase['ready'])
        self.assertTrue(phase['checking'])
        self.assertEqual('engage', result['combat_mode'])
        self.assertFalse(result['fire_allowed'])


class NativeProjectedPointTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)
        self.scene = OwnershipScene()
        self.scene.setUp()
        self.addCleanup(self.scene.doCleanups)
        self.scene.configure(clip=1, burst=1)
        enemy = self.scene.eligible_enemy(14, armor=10.)
        self.scene.pose(enemy, (24., 0., 50.))
        self.scene.sample_original_lanes()
        self.scene.fixture.now += .1
        self.scene.battle._last_frame_time = self.scene.now
        self.scene.control.update(.1, self.scene.now)
        self.runtime = self.scene.runtime
        self.policy = self.runtime.attack_policy
        self.evaluator = self.policy.evaluator
        self.frame = self.evaluator.snapshot(self.scene.now)
        self.candidate = self.policy.decision['candidate']
        self.assertEqual('aim', self.policy.decision['action'])

    def test_future_clear_ray_is_never_a_current_shot_authority(self):
        key = (self.candidate['shell_index'], self.candidate['target_key'],
               self.candidate['sample'])
        original = self.evaluator.predictions.get(key)
        before = (tuple(self.runtime.gun.ammo), self.runtime.gun.clip,
                  self.runtime.state['fire_seq'])
        self.evaluator._budgets['recovery'] = 0
        self.assertEqual('pending', self.evaluator.point_recovery_probe(
            self.frame, self.candidate, (4., 0., 8.), self.scene.now)['status'])
        self.evaluator._budgets['recovery'] = 6
        proved = self.evaluator.point_recovery_probe(
            self.frame, self.candidate, (4., 0., 8.), self.scene.now)
        self.assertEqual('clear', proved['status'])
        self.assertEqual(original, self.evaluator.predictions.get(key))
        self.assertEqual(before, (tuple(self.runtime.gun.ammo),
                                 self.runtime.gun.clip, self.runtime.state['fire_seq']))
        self.assertEqual('aim', self.policy.decision['action'])
        self.assertEqual((0., 0., 0.), self.frame['position'])
        self.assertFalse(self.scene.launches())

    def test_future_world_obstruction_prevents_destination_admission(self):
        # The same real native ray that is clear in the preceding test
        # intersects this actual synthetic world collider after translation.
        self.scene.world[:] = [((10., -20., 20.), (15., 20., 30.))]
        self.evaluator._budgets['recovery'] = 6
        result = self.evaluator.point_recovery_probe(
            self.frame, self.candidate, (4., 0., 8.), self.scene.now)
        self.assertEqual(('blocked', 'future_world_blocked'),
                         (result['status'], result['reason']))
        self.assertFalse(self.scene.launches())


if __name__ == '__main__':
    unittest.main()
