"""Opt-in verification of the actual packaged editor; writes only a temp store."""
import copy
import json
import tempfile
from pathlib import Path
import traceback


def run(destination):
    report = {'ok': False, 'native_gameplay_tested': False}
    root = None
    try:
        import tkinter as tk
        import PIL
        import bot_tactics_ui
        import bot_tactics_store as storage
        with tempfile.TemporaryDirectory(prefix='bot-editor-smoke-') as temp:
            root = tk.Tk(); root.withdraw()
            ui = bot_tactics_ui.BotTacticsEditor(root, store=storage.Store(temp), language='en')
            def fail(error):
                raise AssertionError(str(error))
            ui.error = fail
            assert ui.document == storage.contract.default_profile()
            report['adopted_baseline_maps']=len(ui.document['maps'])
            report['baseline_wait_places']=sum(len(storage.contract.waiting_positions(p))
                for e in ui.document['maps'].values() for r in e.get('default_routes',()) for p in r['points'])
            readonly=copy.deepcopy(ui.document)
            ui.new_route();ui.rule_vars['skill'].set('elite');ui.save_rule();ui.undo()
            assert ui.document==readonly and str(ui.save_button.cget('state'))=='disabled'
            report['default_readonly']=True
            ui.adopt(storage.contract.default_profile('Baseline verification'))
            ui.map_var.set('Ruinberg');ui.change_map()
            ui.route_class_var.set('AT-SPG');ui.change_route_class()
            original=next(r for r in storage.contract.default_map('08_ruinberg')['default_routes']
                if r['team']==ui.team and r.get('class_tag')=='AT-SPG' and not r.get('disabled'))
            ui.selection=('builtin',original['id']);ui._refresh_properties()
            ui._editable_item()['points'][1][0]+=8;ui.reset_builtin()
            assert ui._editable_item()==original
            report['baseline_route_restore']=True
            ui.store.save(storage.contract.empty('Smoke fixture'),apply=True)
            ui.adopt(ui.store.active())
            for key,value in dict(skill='regular',development='full',equipment='improved',consumables='large',crew_preset='all',outfit='off').items():ui.rule_vars[key].set(value)
            for var in ui.ammo_vars:var.set('0')
            ui.save_rule()
            report['independent_presets_and_empty_ammo']=True
            assert storage.contract.effective(ui.document,1,'heavyTank',0)['outfit']=='off'
            from types import SimpleNamespace
            from tkinter import ttk
            import crew_ui
            owner=SimpleNamespace(_tk=tk,_ttk=ttk,_t=lambda value:value,
                game_root=tk.StringVar(value='smoke fixture'),_save_slot_id='smoke',_busy=False,_maintenance_busy=False)
            panel=crew_ui.CrewPanel(owner,ttk.Frame(root))
            panel.vehicles=[dict(name='ussr:R11_MS-1',nation='ussr',label='MS-1',roles=('commander','driver'))]
            panel.filter();assert panel.by_label
            panel.variables['female'].set('Female');panel.variables['skills'].set('2')
            original_add=crew_ui.store.add;calls=[]
            try:
                crew_ui.store.add=lambda *args:calls.append(args)
                assert panel.add()
                assert calls==[('smoke','smoke fixture','ussr:R11_MS-1','commander',True,2)]
            finally:
                crew_ui.store.add=original_add
            panel.variables['role'].set('Loader');panel.filter();assert not panel.by_label
            assert str(panel.button.cget('state'))=='disabled'
            report['crew_controls_and_outfit_override']=True
            root.update(); ui.book.select(1); root.update()
            ui.map_var.set('Ruinberg'); ui.change_map()
            ui.route_class_var.set('heavyTank'); ui.change_route_class(); root.update()
            graph = storage.graph_data('08_ruinberg')
            # Actual canvas callbacks, not directly constructing the profile.
            ui.new_route(); root.update()
            assert ui._selected()['class_priorities'] == {'heavyTank': 5}
            for point in graph['routes']['1'][0]['waypoints'][:4]:
                x, y = ui.view.screen(point)
                ui.canvas.event_generate('<ButtonPress-1>', x=int(x), y=int(y))
                ui.canvas.event_generate('<ButtonRelease-1>', x=int(x), y=int(y))
                root.update()
            ui.item_vars['label'].set('Smoke route')
            ui.item_vars['policy'].set('fixed')
            assert ui.update_properties()
            ui.new_position(); root.update()
            x, y = ui.view.screen((-106., 346.))
            ui.canvas.event_generate('<ButtonPress-1>', x=int(x), y=int(y))
            ui.canvas.event_generate('<ButtonRelease-1>', x=int(x), y=int(y)); root.update()
            ui.item_vars['radius'].set('34')
            ui.profile_name.set('Packaged editor smoke')
            ui.save(True); root.update()
            active = ui.store.active()
            assert active['maps']['08_ruinberg']['routes'][0]['policy'] == 'fixed'
            assert active['maps']['08_ruinberg']['positions'][0]['radius'] == 34.
            assert not ui.dirty()
            values=storage.contract.effective(active,1,'heavyTank',0)
            assert values['development']=='full' and values['equipment']=='improved' and values['ammo_ratios']==[0,0,0]
            # Prove that the runtime plan reader, not just the form, sees it.
            spawn = graph['spawn_formations']['1'][0]
            state = dict(id=11, team=1, slot=0, vehicle='smoke:SPG', profile={'class_tag':'SPG'},
                         collision_shape=(1.8,4.,-.8,2.), x=spawn[0],y=spawn[1],z=spawn[2])
            plans, statuses = storage.runtime.assign_manual_positions(active, '08_ruinberg', graph, [state])
            assert statuses[11] == 'manual_selected' and plans[11]['source'] == 'launcher_manual_v1'
            assert len(storage.contract.MAPS) == 41
            # Verify translations from the real frozen executable, not just
            # source tests, while retaining the active canonical document.
            import bot_tactics_labels as labels
            active_bytes = ui.store.active_path.read_bytes()
            ui.set_language('zh'); root.update()
            assert ui.map_var.get() == '鲁别克'
            assert ui.rule_boxes['skill'].cget('values') == ('继承上级设置','新手','普通','老兵','精英')
            assert labels.map_label('04_himmelsdorf', 'zh') == '锡默尔斯多夫'
            assert labels.route_label('waterfall', 'zh') == '瀑布'
            ui.set_language('en'); root.update()
            assert ui.map_var.get() == 'Ruinberg'
            assert labels.map_label('86_himmelsdorf_winter', 'en') == 'Winter Himmelsdorf'
            assert active_bytes == ui.store.active_path.read_bytes()
            ui.map_var.set(labels.map_label('31_airfield','en'));ui.change_map()
            ui.route_class_var.set('SPG');ui.change_route_class();root.update()
            assert ui.items.get_children() and all(i.startswith('builtin_positions:') for i in ui.items.get_children())
            assert ui.symmetry_check.winfo_ismapped()
            assert ui.base_label.master == ui.symmetry_check.master
            report['airfield_parking_defaults']=len(ui.items.get_children())
            report.update(localization_checked=True, translated_map_count=len(labels.MAP_NAMES),
                          translated_route_count=len(labels.ROUTE_NAMES),
                          language_switch_preserves_active=True)
            report.update(ok=True, pillow=PIL.__version__, tk=tk.TkVersion,
                          map_count=41, canvas_route_points=len(active['maps']['08_ruinberg']['routes'][0]['points']),
                          manual_plan=plans[11], profile_sha256=storage.contract.digest(active),
                          isolated_profile=True)
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if root is not None:
            root.destroy()
        path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf8')
    return 0 if report['ok'] else 1
