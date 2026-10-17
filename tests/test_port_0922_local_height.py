"""Local multi-surface admission; no replacement driver or route policy."""
import ast
import contextlib
import io
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from test_port_0922_navigation import TerrainGrid, StaticHullNavigationTests
from gui.mods.offline_lan_0922.ai.local_height import LocalHeightLinks, MAX_COLUMNS


def face(x,z,height,dx=0.,dz=0.):
    return dict(point=(x,height,z),normal=(-dx,1.,-dz))


class LocalHeightTests(unittest.TestCase):
    def links(self, surfaces):
        calls=[]
        def probe(x,z,low,high):
            calls.append((x,z,low,high))
            return dict(status='complete',surfaces=[r for r in surfaces(x,z)
                if low <= r['point'][1] <= high])
        links=LocalHeightLinks(probe);links.begin((6.,-15.,6.))
        return links,calls

    def test_bridge_lower_floor_is_kept_and_upper_target_is_not_reachable(self):
        links,calls=self.links(lambda x,z:[face(x,z,1.),face(x,z,-15.)])
        self.assertEqual(('other_surface',(9.,-15.,6.)),
            links.inspect((6.,-15.,6.),(9.,1.,6.),1.))
        self.assertEqual('connected',links.inspect((6.,-15.,6.),(9.,-15.,6.),1.)[0])
        before=len(calls)
        links.inspect((6.,-15.,6.),(9.,1.,6.),1.)
        self.assertEqual(before,len(calls))

    def test_same_xz_jump_and_tiny_horizontal_jump_are_disconnected(self):
        for dx in (0.,.1):
            with self.subTest(dx=dx):
                links,_=self.links(lambda x,z:[face(x,z,1.),face(x,z,-15.)])
                self.assertEqual('other_surface',links.inspect(
                    (6.,-15.,6.),(6.+dx,1.,6.),1.)[0])

    def test_captured_fv4005_target_cannot_borrow_the_deck(self):
        origin=(8.54669873568522,-14.663379669189453,109.25821356047132)
        links,_=self.links(lambda x,z:[face(x,z,1.109),face(x,z,-14.90)])
        links.begin(origin)
        self.assertEqual(('other_surface',(10.,-14.90,106.)),
            links.inspect(origin,(10.,1.109,106.),1.109))

    def test_lower_floor_cannot_borrow_a_dry_bridge_water_mask(self):
        def surfaces(x,z):
            lower=face(x,z,-15.);lower['navigation_water']=True
            return [face(x,z,1.),lower]
        links,_=self.links(surfaces)
        self.assertEqual('water',links.inspect((6.,-15.,6.),(9.,1.,6.),1.)[0])

    def test_continuous_large_slopes_are_not_a_new_veto_in_both_directions(self):
        for angle in (19.,35.,55.,-19.,-35.,-55.):
            grade=math.tan(math.radians(angle))
            links,_=self.links(lambda x,z:[face(x,z,-15.+grade*(x-6.),grade)])
            end=(9.,-15.+3.*grade,6.)
            self.assertEqual('connected',links.inspect((6.,-15.,6.),end,1.)[0],angle)

    def test_sharp_but_continuous_ramp_entry_is_not_a_height_jump(self):
        links,_=self.links(lambda x,z:[face(x,z,-15.+max(0.,x-7.)*1.2,
            1.2 if x>7. else 0.)])
        self.assertEqual('connected',links.inspect((6.,-15.,6.),(10.,-11.4,6.),1.)[0])

    def test_actual_step_without_an_upper_connection_is_disconnected(self):
        links,_=self.links(lambda x,z:[face(x,z,-15. if x<7. else 1.)])
        self.assertEqual('disconnected',links.inspect((6.,-15.,6.),(9.,1.,6.),1.)[0])

    def test_rearward_and_sideways_candidates_use_their_own_columns(self):
        for end in ((3.,1.,6.),(6.,1.,9.),(6.,1.,3.)):
            links,_=self.links(lambda x,z:[face(x,z,-15.),face(x,z,1.)])
            status,point=links.inspect((6.,-15.,6.),end,1.)
            self.assertEqual('other_surface',status)
            self.assertEqual((end[0],-15.,end[2]),point)

    def test_remote_goal_and_synthetic_anchor_do_not_own_a_local_surface(self):
        links,calls=self.links(lambda x,z:[face(x,z,1.)])
        self.assertEqual('unscoped',links.inspect((6.,-15.,6.),(50.,1.,6.),1.)[0])
        self.assertEqual('unscoped',links.inspect((-290.986,-13.516,205.101),
            (-350.,0.,258.),.734)[0])
        self.assertEqual([],calls)

    def test_authored_zero_goal_is_resolved_without_inventing_an_upper_floor(self):
        links,_=self.links(lambda x,z:[face(x,z,-15.),face(x,z,0.)])
        links.begin((6.,-15.,6.),((9.,0.,6.),))
        self.assertEqual(('connected',(9.,-15.,6.)),
            links.inspect((6.,-15.,6.),(9.,0.,6.),0.))

    def test_missing_truncated_and_failed_native_queries_are_unknown(self):
        for probe in (lambda *a:None,lambda *a:dict(status='layer_limit',surfaces=[]),
                      lambda *a:dict(status='complete',surfaces=[])):
            links=LocalHeightLinks(probe);links.begin((6.,-15.,6.))
            self.assertEqual('unknown',links.inspect((6.,-15.,6.),(9.,1.,6.),1.)[0])

    def test_query_budget_is_bounded_and_never_calls_unknown_a_disconnection(self):
        links,_=self.links(lambda x,z:[face(x,z,1.),face(x,z,-15.)])
        links.queries=MAX_COLUMNS
        self.assertEqual('unknown',links.inspect((6.,-15.,6.),(9.,1.,6.),1.)[0])
        self.assertEqual(MAX_COLUMNS,links.queries)

    def test_reuse_requires_a_fresh_root_generation_and_expires_when_idle(self):
        generation=[1,0];calls=[]
        def probe(x,z,low,high):
            calls.append((x,z))
            return dict(status='complete',generation=tuple(generation),surfaces=[
                face(x,z,1.),face(x,z,-15.)])
        links=LocalHeightLinks(probe)
        origin,end=(6.,-15.,6.),(9.,1.,6.)
        links.begin(origin,now=0.)
        self.assertEqual('other_surface',links.inspect(origin,end,1.)[0])
        first=links.queries
        links.begin(origin,now=.1)
        self.assertEqual('other_surface',links.inspect(origin,end,1.)[0])
        self.assertEqual(1,links.queries)
        self.assertGreater(links.cache_hits,0)
        generation[1]+=1
        links.begin(origin,now=.2)
        links.inspect(origin,end,1.)
        self.assertEqual(first,links.queries)
        links.begin(origin,now=1.)
        links.inspect(origin,end,1.)
        self.assertEqual(first,links.queries)

    def test_repeated_decisions_finish_all_spokes_without_resetting_route_retries(self):
        def probe(x,z,low,high):
            return dict(status='complete',generation=(1,0),surfaces=[
                face(x,z,0.),face(x,z,-15.)])
        links=LocalHeightLinks(probe);origin=(20.,-15.,20.)
        results=[]
        for decision in range(6):
            links.begin(origin,now=decision*.14)
            results=[]
            for i in range(18):
                yaw=i*math.pi/9
                end=(20.+math.sin(yaw)*3.12,0.,20.+math.cos(yaw)*3.12)
                results.append(links.inspect(origin,end,0.)[0])
            self.assertLessEqual(links.queries,MAX_COLUMNS)
        self.assertEqual(['other_surface']*18,results)

    def test_grid_uses_old_complete_ranking_after_resolving_the_local_floor(self):
        grid=TerrainGrid(lambda *a:1.,lambda *a:False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        # A deck-only XZ graph must not force the real lower pose onto its deck.
        links,_=self.links(lambda x,z:[face(x,z,0.),face(x,z,-15.)])
        grid.local_height_links=links
        for avoid in (None,[(6.,-15.,9.)]):
            links.begin((6.,-15.,6.))
            receipt={}
            target=grid.safe_local_target((6.,-15.,6.),(6.,0.,30.),0.,
                avoid_points=avoid,diagnostic=receipt)
            self.assertIsNotNone(target)
            self.assertEqual(-15.,target[1])
            admitted=[r for r in receipt['candidates'] if r.get('rejected') is None]
            expected=min(admitted,key=lambda r:(r['D']+r['C'],abs(r['theta'])))
            self.assertEqual(expected['point'],target)
            for row in admitted:
                self.assertAlmostEqual(row['C'],abs(row['theta'])*3.5+
                    grid._penalty(grid.cell_for(row['point']),avoid,False)*2.)
        links.begin((6.,-15.,6.))
        self.assertFalse(grid.segment_clear((6.,-15.,6.),(9.,0.,6.)))
        self.assertTrue(grid.segment_clear((6.,-15.,6.),(9.,-15.,6.)))

    def test_decision_reset_clears_previous_bot_surface_and_logs(self):
        links,_=self.links(lambda x,z:[face(x,z,1.),face(x,z,-15.)])
        links.inspect((6.,-15.,6.),(9.,1.,6.),1.)
        links.begin((6.,1.,6.))
        self.assertEqual([],links.receipts)
        self.assertEqual({},links.columns)
        self.assertEqual('unchanged',links.inspect((6.,1.,6.),(9.,1.,6.),1.)[0])


class NativeColumnContractTests(unittest.TestCase):
    def test_real_runtime_keeps_the_lower_target_and_releases_its_scope(self):
        from gui.mods.offline_lan_0922.bot_runtime import BotRuntime
        from gui.mods.offline_lan_0922.ai.navigation import TerrainNavigator
        probe=lambda x,z,low,high:dict(status='complete',surfaces=[
            face(x,z,y) for y in (-15.,0.) if low<=y<=high])
        runtime=BotRuntime(1,ground_probe=lambda *a:-15.,
            obstacle_probe=lambda *a:False,navigation_height_columns=probe)
        runtime.navigator=TerrainNavigator(lambda *a:-15.,lambda *a:False,
            baked_graph=StaticHullNavigationTests._flat_graph())
        runtime.states[7]=dict(id=7,team=2,x=6.,y=-15.,z=6.,yaw=0.,
            pitch=0.,roll=0.,speed=0.)
        runtime._occupied_route_target=lambda *a:None
        runtime._route_lane_target=lambda bot,pos,goal,target,*a:target
        with contextlib.redirect_stdout(io.StringIO()):
            target=runtime._navigation_target(7,(6.,-15.,6.),(9.,0.,6.),
                dict(combat_mode='route',route_id='test',route_index=1,
                    route_anchor=dict(x=6.,y=0.,z=6.)),dict(now=1.,speed=0.))
        self.assertEqual((9.,-15.,6.),target)
        self.assertIsNone(runtime.navigator.grid.local_height_links.origin)
        self.assertTrue(runtime.states[7]['_navigation_target_receipt']['height_links'])

    def method(self,name,file,class_name):
        source=Path(__file__).resolve().parents[1]/file
        cls=next(n for n in ast.parse(source.read_text(encoding='utf8')).body
            if isinstance(n,ast.ClassDef) and n.name==class_name)
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
        node.decorator_list=[]
        ns=dict(_xyz=lambda x:tuple(x),BOT_WATER_AVOID_DEPTH=1.2)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
        return ns[name]

    def test_native_column_recasts_below_each_layer_and_preserves_normals(self):
        call=self.method('_navigation_height_columns',
            'src/res/scripts/client/gui/mods/offline_lan_0922/battle_runtime.py','BattleRuntime')
        starts=[]
        def collide(start,end):
            starts.append(start)
            for y in (1.,.7,-15.):
                if end[1] <= y <= start[1]:return ((start[0],y,start[2]),
                    (0.,-1. if y==.7 else 1.,0.))
        result=call(SimpleNamespace(_vector=lambda p:p,_collide_navigation=collide,
            _water_depth=lambda p:0.),6.,6.,-18.,4.)
        self.assertEqual('complete',result['status'])
        self.assertEqual([1.,-15.],[r['point'][1] for r in result['surfaces']])
        self.assertEqual(4,len(starts))

    def test_scope_is_released_even_when_the_navigation_decision_throws(self):
        call=self.method('_navigation_target',
            'src/res/scripts/client/gui/mods/offline_lan_0922/bot_runtime.py','BotRuntime')
        links=SimpleNamespace(origin=(1.,2.,3.))
        def fail(*args):raise RuntimeError('fixture failure')
        runtime=SimpleNamespace(navigator=SimpleNamespace(grid=SimpleNamespace(
            local_height_links=links)),_navigation_target_impl=fail)
        with self.assertRaises(RuntimeError):call(runtime,1,(1.,2.,3.),(2.,3.,4.),{}, {})
        self.assertIsNone(links.origin)
