"""Real Tk category, vehicle, and additive editor interactions on disposable data."""
import os
import types
import unittest
from unittest import mock
import tkinter as tk
from tkinter import ttk
import customizations_ui as ui
import wot_launcher


@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'requires Tk display')
class WidgetTests(unittest.TestCase):
    def test_both_languages_share_native_nation_order_and_add_only_current_selection(self):
        for chinese in (False,True):
            with self.subTest(chinese=chinese):
                root=tk.Tk();root.withdraw()
                try:
                    tr=lambda value:wot_launcher._CHINESE.get(value,value) if chinese else value
                    vehicles=[dict(nation=n,name=n+':Tank',vehicle='Tank',label=n,level=10,
                        vehicleClass='heavyTank',compact_descr=i,tags=['heavyTank'])
                        for n,i in (('germany',101),('china',102),('ussr',103))]
                    items=[dict(kind=1,id=137,label='Paint',category='Paint',rules=[],igr=False,
                                hidden=False,rent_count=0,vehicle_bound=False),
                           dict(kind=4,id=128,label='Style',category='Preset style',rules=[],igr=False,
                                hidden=True,rent_count=0)]
                    owner=types.SimpleNamespace(_save_slot_id='fixture',game_root=tk.StringVar(value='unused'),
                        save_dialog=root,_tk=tk,_ttk=ttk,_t=tr)
                    with mock.patch.object(ui.store,'appearance_catalogue',return_value=(items,vehicles)), \
                         mock.patch.object(ui.store,'read_inventory',return_value={}), \
                         mock.patch.object(ui.store,'_target',return_value=('unused',{'vehicles':{'101':{},'102':{}}},{},'',True)):
                        dialog=ui.CustomizationsDialog(owner);root.update()
                    self.assertEqual([None,'china','ussr','germany'],list(dialog.nations.values()))
                    self.assertEqual({'china:Tank','germany:Tank'},set(v['name'] for v in dialog.targets()))
                    dialog.nation.set(ui.nation_choices.caption('germany',tr));dialog.filter_vehicles()
                    self.assertEqual(['germany:Tank'],[v['name'] for v in dialog.targets()])
                    self.assertEqual(('1:137',),dialog.table.get_children())
                    dialog.table.selection_set('1:137');dialog.quantity.set('7');dialog.add()
                    self.assertEqual({'0':7},dialog.inventory['1']['137'])
                    dialog.table.selection_set('1:137');dialog.add()
                    self.assertEqual({'0':14},dialog.inventory['1']['137'])
                    dialog.notebook.select(1);root.update()
                    self.assertEqual(('4:128',),dialog.table.get_children())
                    dialog.table.selection_set('4:128');dialog.quantity.set('2');dialog.add()
                    self.assertEqual({'0':14},dialog.inventory['1']['137'])
                    self.assertEqual({'0':2},dialog.inventory['4']['128'])
                    dialog.close()
                finally:root.destroy()


if __name__=='__main__':unittest.main()
