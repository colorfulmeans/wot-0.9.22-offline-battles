"""Banked planning lanes use the occupied support plane, not world-Y sides.

Analytic fixtures reproduce the frame mismatch seen in report 003525 BOT18.
They do not establish exact Windows terrain or playability acceptance.
"""
import math
import unittest
from test_port_0922_battle_runtime import _runtime, _Vector, BattleRuntime


class PosedDirectionProbeTests(unittest.TestCase):
    def scene(self, wall=False, missing=False):
        runtime = _runtime()
        rays = []
        dx, dz = .6, -.45
        def height(x,z):
            return 5.+dx*x+dz*z
        normal = _Vector(-dx, 1., -dz)
        def collide(unused_space, start, end, unused_mask):
            if start.x == end.x and start.z == end.z:
                return None if missing else (_Vector(start.x, height(start.x,start.z), start.z), normal)
            rays.append((start,end))
            if wall or min(start.y-height(start.x,start.z), end.y-height(end.x,end.z)) <= 0.:
                return (end, normal)
            return None
        runtime.bigworld.wg_collideSegment = collide
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        pitch = math.atan(-dz)
        pose = (0., pitch, math.atan(dx*math.cos(pitch)))
        return battle, rays, pose, height

    def test_banked_downhill_exit_keeps_all_lanes_above_the_surface(self):
        for distance in (.5,1.,2.,4.):
            for yaw in (0.,math.pi):
                # Only the admitted downhill direction is under the old grade limit.
                battle,rays,pose,height = self.scene()
                old = battle._direction_probe((0.,5.,0.),yaw,0.,None,distance)
                self.assertEqual('planning_collision', old['reason'])
                rays[:] = []
                fixed = battle._direction_probe((0.,5.,0.),yaw,0.,None,distance,
                    body_pose=pose)
                self.assertTrue(fixed['clear'], fixed)
                self.assertEqual(6,len(rays))
                for start,end in rays:
                    self.assertGreater(start.y-height(start.x,start.z), .69)
                    self.assertGreater(end.y-height(end.x,end.z), .69)

    def test_posed_lanes_keep_real_wall_and_missing_ground_vetoes(self):
        for wall,missing,reason in ((True,False,'planning_collision'),
                                    (False,True,'planning_ground_missing')):
            battle,rays,pose,height = self.scene(wall,missing)
            result = battle._direction_probe((0.,5.,0.),0.,0.,None,.5,body_pose=pose)
            self.assertFalse(result['clear'])
            self.assertEqual(reason,result['reason'])


if __name__ == '__main__':
    unittest.main()
