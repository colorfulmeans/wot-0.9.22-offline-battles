import math
import types
import unittest
from test_port_0922_battle_runtime import BattleRuntime, _runtime, _Vehicle, _Vector
from test_port_0922_turret_obstacles import descriptor, row
from gui.mods.offline_lan_0922 import rigid_turret


class TurretRuntimeContactTests(unittest.TestCase):
    def setup_body(self):
        runtime = _runtime()
        battle = BattleRuntime(runtime)
        battle._avatar = runtime.bigworld.avatar
        td = descriptor()
        td.turret.weight, td.gun.weight = 4000., 1000.
        td.physics = {'weight': 50000.}
        for key, engine_id in (('bot:17', 117), ('player:1', 101)):
            runtime.bigworld.entities[engine_id] = _Vehicle(engine_id, td, _Vector(), (0,0,0), {'health': 500})
            battle._records[key] = dict(engine_id=engine_id, ready=True, kind=key.split(':')[0], network_id=int(key.split(':')[1]))
        battle.client = types.SimpleNamespace(player_id=1)
        battle._bots = types.SimpleNamespace(states={17: dict(id=17, x=100., y=0., z=0., yaw=0., speed=0., alive=False)})
        battle._collide_rigid_turret = lambda a,b: None
        battle._apply_turret_bot_response = lambda *args: None
        return runtime, battle

    def test_worker_consumes_one_momentum_checkpoint_even_after_player_leaves(self):
        runtime, battle = self.setup_body()
        accepted = row()
        accepted['flight']['origin'] = (0., 10., 0.)
        accepted['flight']['segments'][0]['origin'] = (0., 10., 0.)
        accepted['flight']['velocity'] = (0.,0.,0.)
        accepted['flight']['segments'][0]['velocity'] = (0.,0.,0.)
        battle._detached_turret_rows['bot:17'] = accepted
        player = dict(id=1, x=-100., y=0., z=0., yaw=0., speed=0.,
                      turret_pushes=[['bot:17', 3, 5000., 0., 0., 0., 0., 0.]])
        battle._authority_players = lambda: [player]
        battle._advance_turret_support(1040)
        body = battle._turret_bodies['bot:17']
        self.assertAlmostEqual(1., body.velocity[0])
        self.assertEqual([['player:1', 3, 5000., 0., 0., 0., 0., 0.]], body.acks)
        battle._advance_turret_support(1080)
        self.assertAlmostEqual(1., body.velocity[0])
        self.assertGreater(body.position[0], .07)
        proposal = battle._detached_turret_proposals['bot:17']
        self.assertEqual(2, proposal['motion_seq'])
        self.assertEqual(body.acks, proposal['flight']['body']['acks'])

    def test_visible_side_contact_publishes_reciprocal_momentum_and_can_reverse(self):
        runtime, battle = self.setup_body()
        td = runtime.bigworld.entities[117].typeDescriptor
        body = rigid_turret.Body(rigid_turret.geometry.turret_components(td),
                                dict(position=(0,1,0), attitude=(0,0,0), grounded=True))
        battle._detached_turret_rows['bot:17'] = rigid_turret.revision(row(), body, 1000)
        battle._local_physics = {'mass': 50000.}
        battle._local_speed = 5.
        battle._motion_is_clear = lambda *args, **kwargs: True
        player = runtime.bigworld.entities[101]
        position = (-1.4,1.,0.)
        result = battle._resolve_local_turret_contacts(player, position, math.pi/2, .04)
        sent = battle._local_turret_pushes['bot:17'][:]
        self.assertGreater(sent[2], 0)
        self.assertEqual(0., sent[3])
        self.assertLess(battle._local_speed, 5.)
        self.assertEqual(position[1], result[1])
        battle._local_speed = -5.
        battle._resolve_local_turret_contacts(player, result, math.pi/2, .04)
        self.assertEqual(sent, battle._local_turret_pushes['bot:17'])
        self.assertEqual(-5., battle._local_speed)

    def test_native_query_failure_rolls_back_pose_and_receipt_cursor_together(self):
        runtime, battle = self.setup_body()
        accepted = row()
        battle._detached_turret_rows['bot:17'] = accepted
        player = dict(id=1, x=-100., y=0., z=0., yaw=0., speed=0.,
                      turret_pushes=[['bot:17', 1, 5000., 0., 0., 0., 0., 0.]])
        battle._authority_players = lambda: [player]
        def fail(a, b):
            raise RuntimeError('scenery query failed')
        battle._collide_rigid_turret = fail
        battle._advance_turret_support(1040)
        self.assertEqual([], battle._turret_bodies['bot:17'].acks)
        self.assertEqual(0., battle._turret_bodies['bot:17'].velocity[0])
        self.assertNotIn('bot:17', battle._turret_sim_times)
        battle._collide_rigid_turret = lambda a,b: None
        battle._advance_turret_support(1080)
        self.assertAlmostEqual(1., battle._turret_bodies['bot:17'].velocity[0])
        self.assertAlmostEqual(.08, battle._turret_bodies['bot:17'].position[0])
