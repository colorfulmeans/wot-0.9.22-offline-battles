"""Exercise visible legends, alpha context and picking with real Tk widgets."""
import os
import tkinter as tk
import unittest
from unittest import mock
import vehicle_armor_viewer as viewer


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
                           moduleEntity='crew', color='#72c485')
        self.panel._internal_scene = dict(parts=({'surfaces': (self.module,)},),
                                          warnings=('surveyingDevice',))
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
                    self.assertEqual(7, len(p._legend_cells))
                    columns = p._legend_columns
                    for index, cell in enumerate(p._legend_cells):
                        self.assertGreaterEqual(cell.winfo_x(), 0)
                        self.assertLessEqual(cell.winfo_x()+cell.winfo_width(), p.legend.winfo_width())
                        if index >= columns:
                            self.assertGreater(cell.winfo_y(), p._legend_cells[index % columns].winfo_y())
                    self.assertEqual(p.canvas.winfo_x(), p.reset_button.winfo_x())
                    self.assertEqual(p.canvas.winfo_width(), p.reset_button.winfo_width())
                    self.assertGreater(p.reset_button.winfo_y(), p.legend.master.winfo_y())
                    self.assertGreaterEqual(int(str(p.help_label.cget('wraplength'))),
                                            p.canvas.winfo_width() - 4)
        p.set_language('zh');p.set_view_mode('internal')
        self.assertIn('观察装置（无数据）', self.label_texts())
        self.assertIn('点击模块', p.help_label.cget('text'))

    def test_alpha_shell_is_behind_modules_and_never_intercepts_picking(self):
        p = self.panel
        p.set_view_mode('internal'); self.root.update()
        items = p.canvas.find_all()
        shell = p.canvas.find_withtag('context_shell')[0]
        module_id = next(iter(p._item_surface))
        self.assertLess(items.index(shell), items.index(module_id))
        self.assertNotIn(shell, p._item_surface)
        self.assertEqual('', p.canvas.itemcget(module_id, 'outline'))
        coords = p.canvas.coords(module_id)
        self.assertTrue(p._pick(sum(coords[::2])/3, sum(coords[1::2])/3))
        self.assertEqual('乘员1', p.selection.get())
        self.assertTrue(p.canvas.find_withtag('selection_edge'))
        self.assertFalse(p._pick(0, 0))
        self.assertEqual('乘员1', p.selection.get())
        p.set_view_mode('armor');self.root.update()
        self.assertFalse(p.canvas.find_withtag('context_shell'))
        module_id = next(iter(p._item_surface))
        coords=p.canvas.coords(module_id)
        self.assertTrue(p._pick(sum(coords[::2])/3,sum(coords[1::2])/3))
        self.assertEqual([('m','f')],self.selected)

    def test_missing_data_warning_only_on_first_load_and_selection_survives_translation(self):
        p = self.panel
        p._internal_scene = None
        with mock.patch('vehicle_internal_viewer.load_scene', return_value=dict(
                parts=({'surfaces': (self.module,)},), warnings=('surveyingDevice',))), \
                mock.patch('tkinter.messagebox.showwarning') as warning:
            p.set_view_mode('internal');p.set_view_mode('armor');p.set_view_mode('internal')
            self.assertEqual(1, warning.call_count)
            self.assertIn('观察装置', warning.call_args.args[1])
        p._selected_module=self.module
        p.set_language('en');self.assertIn('crew 1', p.selection.get())
        p.set_language('zh');self.assertEqual('乘员1',p.selection.get())
