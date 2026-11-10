"""Worker recovery uses one checked same-point movement owner.

The production planner, shared combat controller and driver consume analytic
native geometry. No selected candidate, policy decision or movement result is
prescribed; these tests do not measure the Windows client's frame pacing.
"""
import contextlib
import io
import unittest

from shared_multi_bot_scene import MultiBotScene
from test_player_fire_admission_complete import f


class RecoveryWorld(MultiBotScene):
    """The same native component world with a measured flat ground surface."""
    def world_probe(self, space, first, last, mask):
        hit = super(RecoveryWorld, self).world_probe(space, first, last, mask)
        start, end = tuple(first), tuple(last)
        if start[1] > 0. >= end[1]:
            fraction = start[1] / (start[1] - end[1])
            point = tuple(start[axis] + fraction * (end[axis] - start[axis])
                          for axis in range(3))
            if hit is None or sum((point[axis] - start[axis]) ** 2
                                  for axis in range(3)) < sum(
                    (tuple(hit[0])[axis] - start[axis]) ** 2 for axis in range(3)):
                return (f._Vector(point), f._Vector((0., 1., 0.)), 0)
        return hit


class SharedBotFriendlyRecoveryTests(unittest.TestCase):
    def setUp(self):
        silence = contextlib.redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def scene(self, count=2):
        scene = RecoveryWorld()
        scene.setUp()
        self.addCleanup(scene.doCleanups)
        scene.configure_workers(count, diverse=False)
        return scene

    def test_unchecked_blocked_destination_cannot_acquire_the_original_route(self):
        scene = self.scene()
        # This wall blocks every candidate near the route without obstructing
        # the authored route itself. An observed obstruction is not evidence
        # that a useful recovery destination exists.
        scene.world[:] = [((-200., -100., -1.), (200., 100., 1.))]
        for unused in range(80):
            scene.step()
            binding = scene.engine._actor_controls[11]
            self.assertFalse(binding.combat_stop.combat_owned,
                'An unchecked/blocked recovery interrupted the original route: %r' %
                (binding.combat_stop.receipt,))
            self.assertFalse(binding.state.get('_combat_movement_owner'))
            self.assertEqual(0, binding.state['fire_seq'])
        self.assertTrue(any(row[1] == 11 and row[4] == 'world_blocked'
                            for row in scene.evaluations))


if __name__ == '__main__':
    unittest.main()
