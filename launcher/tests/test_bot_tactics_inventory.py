"""Effective checks, draft geometry and real editor report interactions."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

import bot_tactics_inventory as inv
import bot_tactics_navigation as nav
import bot_tactics_store as storage
import bot_tactics_geometry as geometry
import bot_tactics_ui as ui

ROOT=Path(__file__).resolve().parents[2]
def review():return storage.contract.default_profile('Review test')


def unconfigured():
    profile=review()
    for entry in profile['maps'].values():
        entry['routes']=[r for r in entry['routes'] if r.get('purpose')!='spg_attack']
        for p in entry['positions']:
            p.pop('travel',None);p.pop('links',None)
    return profile


class InventoryTests(unittest.TestCase):
    def test_effective_class_override_and_disabled_family_are_not_duplicates(self):
        name='04_himmelsdorf';g=storage.graph_data(name);p=storage.contract.default_profile()
        e=p['maps'][name];r=e['default_routes'][0]
        shared=next(x for x in e['default_routes'] if x['team']==1 and x.get('class_tag','all')=='all')
        scoped=next((x for x in e['default_routes'] if x['team']==1 and x['id']==shared['id'] and x.get('class_tag')=='heavyTank'),None)
        if scoped is None:
            scoped=copy.deepcopy(shared);scoped['class_tag']='heavyTank';e['default_routes'].append(scoped)
        scoped['points'][1][0]+=1
        rows=inv.inventory(p,name,g,storage.contract)
        effective=[x for x in rows if x['identity']==shared['id'] and x['team']==1 and x['kind']=='route']
        self.assertEqual(4,len(effective))
        self.assertEqual(scoped['points'],next(x['points'] for x in effective if x['scope']=='heavyTank'))
        shared['disabled']=True
        self.assertTrue(all(x['disabled'] for x in inv.inventory(p,name,g,storage.contract) if x['identity']==shared['id'] and x['team']==1))

    def test_missing_is_separate_and_optional_defense_is_only_three_maps(self):
        p=unconfigured()
        for name in storage.contract.MAPS:
            rows=inv.inventory(p,name,storage.graph_data(name),storage.contract)
            self.assertEqual(name in inv.DEFENSE_MAPS,any(x['kind']=='defense' for x in rows))
            self.assertFalse(any(x['kind']=='deployment' for x in rows))
            self.assertFalse(any(x['kind']=='relocation' for x in rows))
            self.assertEqual(2,sum(x['kind']=='sortie' and not x['points'] for x in rows))

    def test_retired_parking_connections_are_not_missing_or_drawn_as_authored(self):
        name='04_himmelsdorf';p=review();g=storage.graph_data(name)
        peers=[x for x in p['maps'][name]['positions'] if x['team']==1];a,b=peers[:2]
        a['links']={b['id']:[a['point']+[0],b['point']+[0]]}
        a['travel']=[[0,0,0],a['point']+[0]]
        rows=inv.inventory(p,name,g,storage.contract)
        self.assertFalse(any(x['kind'] in ('deployment','relocation') for x in rows))

    def test_directional_failure_cannot_be_reported_as_pass_and_check_is_read_only(self):
        name='04_himmelsdorf';p=unconfigured();g=storage.graph_data(name)
        before=copy.deepcopy((p,g));receipts=[]
        def proof(grid,graph,a,b):return dict(connected=a[0]<=b[0],start=a[:2],end=b[:2])
        with mock.patch.object(nav,'connection',side_effect=proof):
            rows=inv.inspect(p,name,g,storage.contract,receipts.append)
        self.assertEqual(before,(p,g));self.assertEqual(rows,receipts[0]['inventory'])
        self.assertTrue(any(x['category']=='unconfigured' and not x['issues'] for x in rows))
        self.assertTrue(any(i.get('direction')=='reverse' for x in rows for i in x['issues']))

    def test_failed_wait_connections_retain_the_individual_wait_slot(self):
        name='04_himmelsdorf';p=storage.contract.default_profile();g=storage.graph_data(name)
        route=next(r for r in p['maps'][name]['default_routes'] if r.get('class_tag')=='heavyTank')
        route['points'][1]=route['points'][1][:2]+[1,0,[[20.,20.,60.],[24.,24.,60.]]]
        with mock.patch.object(nav,'connection',return_value={'connected':False}):
            rows=inv.inspect(p,name,g,storage.contract)
        issues=[i for r in rows for i in r['issues'] if i.get('direction','').startswith('wait_')]
        self.assertTrue(issues);self.assertTrue(all(i.get('wait_slot') in (1,2,3) for i in issues))
        self.assertTrue(any(i['wait_slot']==2 for i in issues))

    def test_shared_default_has_every_connection_and_valid_defense_junctions(self):
        p=review();baseline=storage.contract.default_profile()
        geometry.validate(p,storage.contract,storage.graph_data)
        counts=dict(deployment=0,relocation=0,sortie=0,defense=0)
        for name,e in p['maps'].items():
            g=storage.graph_data(name);rows=inv.inventory(p,name,g,storage.contract)
            for row in rows:
                if not row['disabled']:
                    self.assertTrue(row['points'],(name,row['kind'],row['identity']))
                    if row['kind'] in counts:counts[row['kind']]+=1
            for current in e['default_routes']:
                if current.get('defense'):
                    branch=current['defense'];ids=current['node_ids'];index=ids.index(branch['junction'])
                    self.assertTrue(0<index<len(ids)-1);self.assertFalse(current['points'][index][2])
                    self.assertEqual(current['points'][index][:2],branch['points'][0][:2])
                    self.assertTrue(geometry.same_point(g['objective_bases'][current['team']-1],branch['points'][-1]))
        self.assertEqual(0,counts['deployment']);self.assertEqual(0,counts['relocation']);self.assertEqual(82,counts['sortie'])
        with tempfile.TemporaryDirectory() as folder:
            store=storage.Store(folder);before=store.active();store.save(p,False)
            self.assertEqual(before,store.active());self.assertEqual(p,store.read(p['name']))
        self.assertEqual(baseline,storage.contract.default_profile())

    def test_regeneration_preserves_every_reviewed_path_and_never_duplicates_sorties(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('review_builder',ROOT/'tools/build_route_review_draft.py')
        builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        expected=review()
        with mock.patch.object(builder.Author,'path',side_effect=AssertionError('Reviewed path overwritten')):
            actual,evidence=builder.build(name=expected['name'],progress=lambda *args,**kwargs:None)
        self.assertEqual([],evidence);self.assertEqual(expected,actual)

    def test_every_generated_map_passes_shipping_navigation_in_both_directions(self):
        profile=review()
        for name in profile['maps']:
            with self.subTest(map=name):
                rows=inv.inspect(profile,name,storage.graph_data(name),storage.contract)
                failures=[(r['identity'],r['scope'],r['kind'],r['issues']) for r in rows
                    if not r['disabled'] and r['category']!='correct']
                self.assertEqual([],failures)

    def test_area_center_snap_does_not_hide_invalid_intermediate_node(self):
        name='04_himmelsdorf';p=review();g=storage.graph_data(name)
        route=p['maps'][name]['routes'][0]
        route['points'].insert(1,[-10000.,-10000.,0])
        rows=inv.inspect(p,name,g,storage.contract)
        row=next(r for r in rows if r['kind']=='sortie' and r['identity']==route['id'])
        self.assertEqual('incorrect',row['category'])
        self.assertTrue(any(i['reason']=='outside_bounds' for i in row['issues']))


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires Tk display')
class ReportUITests(unittest.TestCase):
    def test_report_groups_locates_connections_and_refuses_stale_location(self):
        with tempfile.TemporaryDirectory() as folder:
            store=storage.Store(folder);p=review();store.save(p,True)
            root=tk.Tk();root.withdraw()
            try:
                e=ui.BotTacticsEditor(root,store=store);e.book.select(1)
                e.map_name='100_thepit';e._load_map()
                name=e.map_name;row=next(x for x in inv.inventory(p,name,e.graph_cache[name],storage.contract) if x['kind']=='defense')
                row.update(category='correct',issues=[],proofs=[])
                import bot_tactics_check_ui as report
                with mock.patch.object(report.inventory,'inspect',return_value=[row]):window=report.show(e)
                root.update()
                tree=next(x for x in window.winfo_children() if isinstance(x,ttk.Treeview))
                self.assertEqual(('correct','incorrect','unconfigured'),tree.get_children())
                tree.selection_set('row0')
                locate=next(x for x in window.winfo_children() if isinstance(x,ttk.Button) and x.cget('text') in ('Locate selection','定位选中项'))
                before=copy.deepcopy(e.document);locate.invoke();root.update()
                self.assertEqual('defense',e.network_mode);self.assertEqual(row['identity'],e._selected_parent()['id'])
                self.assertEqual(before,e.document)
                e.document['maps'][name]['positions'][0]['priority']=9
                selection=e.selection;locate.invoke();self.assertEqual(selection,e.selection)
                window.destroy()
            finally:root.destroy()
