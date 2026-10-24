"""Vehicle-sized passage guidance retains route and native proof ownership."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest import mock

from test_port_0922_navigation import TerrainNavigator
from gui.mods.offline_lan_0922 import bot_tactics


def graph(diagonal=False):
    width,height,cell=25,25,2.
    origin=(-24.,-24.)
    heights=[]
    for z in range(height):
        for x in range(width):
            px,pz=origin[0]+x*cell,origin[1]+z*cell
            open_cell=(abs(pz)>10. or abs(px)<=2.) if not diagonal else (abs(px+pz)>20. or abs(px-pz)<=2.)
            heights.append(0 if open_cell else None)
    directions=((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1))
    links=[]
    for z in range(height):
        for x in range(width):
            mask=0
            if heights[z*width+x] is not None:
                for bit,(dx,dz) in enumerate(directions):
                    nx,nz=x+dx,z+dz
                    if 0<=nx<width and 0<=nz<height and heights[nz*width+nx] is not None:
                        mask|=1<<bit
            links.append(mask)
    return dict(format='offline-lan-0922-navgraph',version=2,width=width,height=height,
                origin=list(origin),bounds=[-24.,-24.,24.,24.],cell_size=cell,
                heights_mm=heights,links=links,hazards=[0]*len(heights))


class NarrowPassageTests(unittest.TestCase):
    def scene(self, diagonal=False):
        nav=TerrainNavigator(lambda *args:0.,lambda *args:False,baked_graph=graph(diagonal))
        nav.bot_states[7]={}
        return nav

    def select(self,nav,position=(0.,0.,0.),goal=(3.,0.,18.),selected=None,now=1.,yaw=0.):
        return nav.narrow_passage_target(7,position,goal,goal if selected is None else selected,
                                        now,yaw,3.5,1.5)

    def test_final_leg_aligns_without_consuming_route_or_local_path_vertices(self):
        nav=self.scene();nav.bot_states[7].update(index=3,request_key=('fixed',7))
        result=self.select(nav)
        self.assertEqual(0.,result[0]);self.assertGreater(result[2],0.);self.assertLess(result[2],18.)
        self.assertEqual(3,nav.bot_states[7]['index'])
        self.assertEqual(('fixed',7),nav.bot_states[7]['request_key'])
        self.assertEqual('guided',nav.bot_states[7]['narrow_passage_receipt']['outcome'])

    def test_arbitrary_diagonal_bridge_uses_its_own_axis(self):
        nav=self.scene(True)
        result=self.select(nav,goal=(16.,0.,17.),yaw=math.pi/4.)
        self.assertAlmostEqual(result[0],result[2],places=6)
        self.assertGreater(result[0],0.)

    def test_same_endpoint_is_retained_until_real_arrival_and_tail_must_clear(self):
        nav=self.scene();first=self.select(nav)
        self.assertEqual(first,self.select(nav,position=(0.,0.,1.),now=2.))
        extended=self.select(nav,position=(0.,0.,12.),now=3.)
        self.assertEqual(0.,extended[0]);self.assertGreater(extended[2],12.)
        goal=(3.,0.,22.)
        self.assertEqual(goal,self.select(nav,position=(0.,0.,17.),goal=goal,now=4.))
        self.assertNotIn('narrow_passage_target',nav.bot_states[7])
        self.assertEqual('body_clear_of_passage',nav.bot_states[7]['narrow_passage_receipt']['outcome'])

    def test_owned_bend_and_nearby_goal_are_not_replaced(self):
        nav=self.scene();goal=(3.,0.,18.)
        bend=(0.,0.,4.)
        self.assertEqual(bend,self.select(nav,goal=goal,selected=bend))
        nearby=(1.,0.,1.)
        self.assertEqual(nearby,self.select(nav,goal=nearby))

    def test_opposite_order_cancels_the_old_direction_and_does_not_overshoot_new_goal(self):
        nav=self.scene();self.select(nav)
        result=self.select(nav,goal=(-2.,0.,-18.))
        self.assertLess(result[2],0.)
        nearer=(1.,0.,5.)
        result=self.select(nav,goal=nearer)
        self.assertLessEqual(result[2],nearer[2])

    def test_static_private_native_and_deferred_refusals_keep_original_target(self):
        for kind in ('static','private','native','deferred','revision','water'):
            with self.subTest(kind=kind):
                nav=self.scene();goal=(3.,0.,18.)
                with mock.patch.object(nav.grid,'segment_penalty',return_value=1. if kind=='static' else 0.), \
                     mock.patch.object(nav,'_bot_edges_penalized',return_value=kind=='private'):
                    if kind=='deferred':nav.grid._proof_deferred=True
                    if kind=='water':
                        cell=nav.grid.cell_for((0.,0.,6.))
                        nav.grid._baked_hazards[nav.grid._baked_flat_index(cell)]=1
                    if kind in ('native','revision'):
                        def proof(*args,**kwargs):
                            if kind=='revision':nav.grid._native_proof_revision+=1
                            return kind=='revision'
                        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=proof):
                            self.assertEqual(goal,self.select(nav,goal=goal))
                    else:self.assertEqual(goal,self.select(nav,goal=goal))
                self.assertNotIn('narrow_passage_target',nav.bot_states[7])
                self.assertIsNone(nav._boundary_actor)

    def test_passage_native_proof_uses_this_actors_boundary_and_is_fresh(self):
        nav=self.scene();nav._boundary_actor=91
        def refused(*args,**kwargs):
            self.assertEqual(7,nav._boundary_actor)
            return False
        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=refused):
            self.assertEqual((3.,0.,18.),self.select(nav))
        self.assertEqual(91,nav._boundary_actor)
        self.select(nav)
        with mock.patch.object(nav.grid,'dry_segment_clear',side_effect=refused):
            self.assertEqual((3.,0.,18.),self.select(nav,now=2.))
        self.assertEqual('corridor_refused',nav.bot_states[7]['narrow_passage_receipt']['outcome'])

    def test_hold_clears_only_passage_memory_and_diagnostics_do_not_log(self):
        nav=self.scene();self.select(nav)
        with mock.patch('sys.stdout.write') as output:
            nav.end_narrow_passage(7,2.,'tactical_hold')
        output.assert_not_called()
        self.assertNotIn('narrow_passage_target',nav.bot_states[7])

    def test_current_default_passes_the_captured_opposed_gate_scene(self):
        import test_port_0922_great_wall_gate as gate
        import test_port_0922_bot_runtime as fixtures
        original=fixtures._load
        issued=[]
        def load():
            module=original();start=module.BotRuntime.battle_start
            remember=TerrainNavigator.remember_runtime_target
            def tracked(nav,bot,current,goal,target,now):
                accepted=remember(nav,bot,current,goal,target,now)
                receipt=nav.bot_states.get(int(bot),{}).get('narrow_passage_receipt') or {}
                if receipt.get('outcome')=='guided' and tuple(receipt['target'])==tuple(target):
                    issued.append((accepted,nav.bot_states[int(bot)].get('local_fallback_target'),tuple(target)))
                return accepted
            patcher=mock.patch.object(TerrainNavigator,'remember_runtime_target',tracked)
            patcher.start();self.addCleanup(patcher.stop)
            def configured(runtime,message):
                document=bot_tactics.for_round(bot_tactics.default_profile(),message['map'])
                return start(runtime,dict(message,bot_tactics=document))
            module.BotRuntime.battle_start=configured
            return module
        case=gate.GreatWallGateTests('test_opposed_hulls_in_the_gatehouse_both_leave_the_passage')
        case.setUp();case.authoritative=True
        try:
            with mock.patch.object(fixtures,'_load',side_effect=load):
                case.test_opposed_hulls_in_the_gatehouse_both_leave_the_passage()
            self.assertTrue(issued,'The passage target must enter the existing finite progress owner')
            self.assertTrue(all(accepted and remembered==target for accepted,remembered,target in issued))
        finally:
            case.doCleanups();case.tearDown()


if __name__=='__main__':unittest.main()
