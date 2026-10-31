"""Exercise visible legends, alpha context and picking with real Tk widgets."""
import os
import tkinter as tk
import unittest
import numpy as np
from unittest import mock
import vehicle_armor_viewer as viewer
from vehicle_internal_viewer import crew_slots


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'requires Tk display')
class ViewerWidgetTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.selected = []
        self.panel = viewer.ArmorViewerPanel(self.root, tk, self.selected.append, 'zh', '')
        self.panel.frame.pack(fill='both', expand=True)
        triangle = ((-1., -1., 0.), (1., -1., 0.), (1., 1., 0.))
        self.surface = dict(role='hull', component='hull', fieldKey=('m', 'f'),
                            thickness=50, triangles=(triangle,))
        self.panel._scene = dict(bounds=((-1., -1., -1.), (1., 1., 1.)),
                                parts=({'surfaces': (self.surface,)},))
        self.panel._record_by_key = {('m', 'f'): {}}
        self.module = dict(self.surface, fieldKey=None, moduleLabel='crew 1 / crew_00',
                           moduleEntity='crew', crewSlot=crew_slots((('commander', 'loader'),))[0], color='#29bdcd')
        self.panel._internal_scene = dict(parts=({'surfaces': (self.module,)},),
                                          warnings=('surveyingDevice',), crewSlots=crew_slots((('commander', 'loader'),)))
        self.root.geometry('560x740'); self.root.update()

    def label_texts(self):
        return [child.cget('text') for cell in self.panel._legend_cells
                for child in cell.winfo_children() if isinstance(child, tk.Label)]

    def test_legend_reflows_without_clipping_in_both_languages_and_modes(self):
        p = self.panel
        for language in ('zh', 'en'):
            p.set_language(language)
            for width in (380, 620):
                self.root.geometry('%dx820' % width)
                for mode in ('armor', 'internal'):
                    p.set_view_mode(mode); self.root.update()
                    self.assertEqual(9 if mode == "internal" else 6, len(p._legend_cells))
                    columns = p._legend_columns
                    for index, cell in enumerate(p._legend_cells):
                        self.assertGreaterEqual(cell.winfo_x(), 0)
                        self.assertLessEqual(cell.winfo_x()+cell.winfo_width(), p.legend.winfo_width())
                        for child in cell.winfo_children():
                            if isinstance(child, tk.Label):
                                self.assertGreaterEqual(child.winfo_width(), child.winfo_reqwidth())
                        if index:
                            self.assertGreaterEqual(cell.winfo_y(), p._legend_cells[index-1].winfo_y())
                    self.assertEqual(p.canvas.winfo_x(), p.reset_button.winfo_x())
                    self.assertEqual(p.canvas.winfo_width(), p.reset_button.winfo_width())
                    self.assertGreater(p.reset_button.winfo_y(), p.legend.master.winfo_y())
                    self.assertGreaterEqual(int(str(p.help_label.cget('wraplength'))),
                                            p.canvas.winfo_width() - 4)
        p.set_language('zh');p.set_view_mode('internal')
        self.assertIn('观察装置（无数据）', self.label_texts())
        self.assertIn('点击模块', p.help_label.cget('text'))

    def test_depth_shell_never_intercepts_picking_and_hidden_objects_are_unpickable(self):
        p = self.panel
        p.set_view_mode('internal'); self.root.update()
        self.assertTrue(p.canvas.find_withtag('depth_scene'))
        ys, xs = np.where(p._pick_buffer != 0)
        x, y = int(xs[len(xs)//2]), int(ys[len(ys)//2])
        h, w = p._pick_buffer.shape; cw, ch = p._pick_size
        self.assertTrue(p._pick(x*cw/w, y*ch/h))
        self.assertEqual('车长（兼装填手）', p.selection.get())
        p._hidden.add(p._surface_identity(self.module)); p._redraw()
        self.assertFalse(p._pick(x*cw/w, y*ch/h))
        self.assertFalse(p._pick_buffer.any())
        p.set_view_mode('armor'); self.root.update()
        self.assertTrue(p._pick(x*cw/w, y*ch/h))
        self.assertEqual([('m','f')],self.selected)

    def test_missing_data_warning_only_on_first_load_and_selection_survives_translation(self):
        p = self.panel
        p._internal_scene = None
        with mock.patch('vehicle_internal_viewer.load_scene', return_value=dict(
                parts=({'surfaces': (self.module,)},), warnings=('surveyingDevice',), crewSlots=crew_slots((('commander', 'loader'),)))), \
                mock.patch('tkinter.messagebox.showwarning') as warning:
            p.set_view_mode('internal');p.set_view_mode('armor');p.set_view_mode('internal')
            self.assertEqual(1, warning.call_count)
            self.assertIn('观察装置', warning.call_args.args[1])
        p._selected_module=self.module
        p.set_language('en');self.assertEqual('Commander (also Loader)', p.selection.get())
        p.set_language('zh');self.assertEqual('车长（兼装填手）',p.selection.get())

    def test_vehicle_reload_clears_module_selection_and_refreshes_unmapped_legend(self):
        p = self.panel
        p._vehicle_member = 'scripts/item_defs/vehicles/usa/A_Test.xml'
        p._selected_module = self.module
        p._scene_loader = lambda *a, **k: dict(p._scene, parts=({'surfaces': (
            dict(self.surface, thickness=None),)},))
        self.assertTrue(p._load_scene())
        self.root.update()
        self.assertIsNone(p._selected_module)
        self.assertIn('未映射', self.label_texts())
        p._scene_loader = lambda *a, **k: dict(p._scene, parts=({'surfaces': (self.surface,)},))
        self.assertTrue(p._load_scene())
        self.root.update()
        self.assertNotIn('未映射', self.label_texts())

    def test_crew_groups_duplicate_roles_and_complete_labels(self):
        p = self.panel
        slots = crew_slots((('commander', 'radioman'), ('loader',), ('loader',)))
        surfaces = tuple(dict(self.module, moduleLabel=slot['identity'], crewSlot=slot,
                              color=slot['color']) for slot in slots)
        p._internal_scene = dict(parts=({'surfaces': surfaces},), crewSlots=slots, warnings=())
        p.set_view_mode('internal'); self.root.update()
        self.assertEqual(['外部模块', '内部模块', '乘员'], [h.cget('text') for _,h in p._legend_headers])
        self.assertIn('车长（兼通信兵）', self.label_texts())
        self.assertIn('装填手1', self.label_texts())
        self.assertIn('装填手2', self.label_texts())
        self.assertNotEqual(slots[1]['color'], slots[2]['color'])
        for language in ('zh', 'en'):
            p.set_language(language)
            self.root.geometry('380x1000'); self.root.update()
            for cell in p._legend_cells:
                self.assertLessEqual(cell.winfo_x()+cell.winfo_width(), p.legend.winfo_width())
                for child in cell.winfo_children():
                    if isinstance(child, tk.Label):
                        self.assertGreaterEqual(child.winfo_width(), child.winfo_reqwidth())
        p.set_language('zh')
        self.assertEqual('炮塔旋转机构', p._module_caption({'moduleLabel':'turretRotator / zone0'}))
        self.assertIn('炮塔旋转机构', p._internal_warning('turretRotator: component frame mismatch'))
        # Same base color for the selected seat and its legend swatch.
        for cell, slot in zip(p._legend_cells[8:], slots):
            swatch = next(child for child in cell.winfo_children() if isinstance(child, tk.Canvas))
            self.assertEqual(slot['color'], swatch.itemcget(swatch.find_all()[0], 'fill'))

    def test_armor_legend_matches_current_vehicle_scales_and_refreshes_after_edit(self):
        p=self.panel
        plates=tuple(dict(self.surface, thickness=value, fieldKey=('m',str(value))) for value in (0,8,16,22))
        track=dict(self.surface, thickness=5, armorKind='tracks')
        p._scene=dict(p._scene, parts=({'surfaces':plates+(track,)},))
        p._draw_legend();self.root.update()
        self.assertEqual(['主装甲','间隙装甲','外部模块'],
                         [h.cget('text') for _,h in p._legend_headers])
        self.assertEqual(['0','8','16','22','无几何数据','履带','炮管（无数据）','观察装置（无数据）'],self.label_texts())
        p._record_by_key={('m','22'):dict(currentValue='22')}
        p.update_field('m','22','30');self.root.update()
        self.assertIn('30',self.label_texts())
        self.assertNotIn('22',self.label_texts())

    def test_group_and_seat_controls_do_not_conflate_hidden_and_missing_data(self):
        p = self.panel
        slots = crew_slots((('loader',), ('loader',)))
        p._internal_scene = dict(parts=({'surfaces': tuple(dict(self.module,
            moduleLabel=s['identity'], crewSlot=s) for s in slots)},),
            crewSlots=slots, warnings=())
        p.set_view_mode('internal'); self.root.update()
        self.assertEqual(['外部模块','内部模块','乘员'],
                         [b.cget('text') for b, _ in p._display_buttons])
        p._display_buttons[2][0].invoke()
        self.assertFalse(p._pick_buffer.any())
        p._display_buttons[2][0].invoke()
        self.assertEqual('观察装置 / 车体', p._surface_name(dict(armorKind='observation',role='hull')))
        self.assertEqual('观察装置 / 炮塔', p._surface_name(dict(armorKind='observation',role='turret')))
        p._open_settings(); self.root.update()
        def children(widget):
            yield widget
            for child in widget.winfo_children(): yield from children(child)
        buttons = {w.cget('text'): w for w in children(p._settings_window)
                   if isinstance(w, tk.Checkbutton)}
        self.assertIn('装填手1', buttons); self.assertIn('装填手2', buttons)
        self.assertEqual('disabled', buttons['发动机（无数据）'].cget('state'))
        buttons['装填手1'].invoke()
        self.assertFalse(p._visible(dict(self.module,moduleLabel='crew 1')))
        self.assertTrue(p._visible(dict(self.module,moduleLabel='crew 2')))
        p.set_language('en')
        self.assertIsNone(p._settings_window)
