"""Opt-in verification of the actual packaged editor; writes only a temp store."""
import copy
import json
import tempfile
from pathlib import Path
import traceback


def _verify_vehicle_editor_language(root, tk, ttk):
    """Exercise shipped widgets with an isolated, read-only numeric fixture."""
    from types import SimpleNamespace
    import vehicle_editor_ui as editor_ui
    member = editor_ui.DEFAULT_MEMBER
    path = 'turrets0/Turret/guns/Gun/burst/count'
    field = dict(member=member, fieldPath=path, categoryLabel='Gun', category='guns',
                 fieldLabel='Gun / Magazine / Rounds per trigger', shared=False,
                 affectedVehicles=['R11_MS-1'], displayVehicle='MS-1', scope='Affects this vehicle only.')
    result = dict(member=member, fieldPath=path, originalValue=1, currentValue=1,
                  packedType='integer', constraint='magazine capacity must be a positive integer',
                  overlayPath='isolated smoke fixture')
    calls = []
    def inspect(*unused):
        calls.append('inspect')
        return result
    service = SimpleNamespace(VehicleOverlayError=ValueError,
        list_vehicle_choices=lambda *a: [dict(nation='ussr', vehicle='R11_MS-1',
            label='MS-1', vehicleClass='lightTank', level=1, member=member)],
        get_vehicle_profile_options=lambda *a: dict(excludeEditedVehiclesFromBots=False),
        list_vehicle_profile_field_choices=lambda *a: [field], inspect_profile_field=inspect)
    editor = editor_ui.VehicleEditorWindow(root, 'isolated fixture', 'Smoke', tk, ttk,
        SimpleNamespace(), service=service, language='en',
        armor_viewer_factory=editor_ui.vehicle_armor_viewer.NullArmorViewerPanel)
    try:
        editor.replacement.set('unfinished.12')
        editor._show_error('This field uses the Packed integer type; enter a whole number.')
        before = list(calls)
        for language in ('zh', 'en', 'zh', 'en'):
            editor.set_language(language)
            root.update()
            assert editor._selection() == (member, path)
            assert editor.replacement.get() == 'unfinished.12'
            assert str(editor.apply_button.cget('state')) == 'disabled'
            assert calls == before
            if language == 'zh':
                assert '1—64' in editor.constraint.get() and '请输入整数' in editor.status.get()
            else:
                assert 'whole number' in editor.status.get()
    finally:
        editor.root.destroy()


def _verify_maintenance_controls(root, tk):
    """Exercise the shipped two-by-two layout without invoking destructive work."""
    from types import SimpleNamespace
    import wot_launcher
    window = tk.Toplevel(root)
    window.withdraw()
    reference = tk.Button(window, text='Reference button')
    reference.pack(side='bottom')
    panel = tk.Frame(window)
    panel.pack(fill='both', expand=True)
    owner = SimpleNamespace(_tk=tk, repair_panel=panel,
        _repair_startup=lambda: None, _reset_offline_client_settings=lambda: None,
        _reset_all_state=lambda: None, _factory_reset=lambda: None)
    wot_launcher.LauncherWindow._build_maintenance_controls(owner)
    buttons = (owner.repair_button, owner.offline_preferences_button,
               owner.reset_button, owner.factory_reset_button)
    labels = ('Repair mod installation', 'Reset all offline client settings',
              'Clear all offline saves', 'Delete all data and restore factory defaults')
    for language in ('en', 'zh'):
        for button, text in zip(buttons, labels):
            button.config(text=wot_launcher._CHINESE[text] if language == 'zh' else text)
        owner.maintenance_help.config(text='\n'.join(
            wot_launcher._CHINESE[line] if language == 'zh' else line
            for line in wot_launcher._MAINTENANCE_HELP))
        window.update_idletasks()
        width = panel.winfo_reqwidth()
        height = panel.winfo_reqheight()
        window.geometry('%dx%d' % (width, height + reference.winfo_reqheight()))
        window.deiconify()
        window.update()
        for button, position in zip(buttons, ((0, 0), (0, 1), (1, 0), (1, 1))):
            info = button.grid_info()
            assert (int(info['row']), int(info['column'])) == position
            assert int(info['padx']) == 3 and int(info['pady']) == 3
        assert len({b.winfo_width() for b in buttons}) <= 2
        assert min(b.winfo_width() for b in buttons) > 1
        assert max(b.winfo_width() for b in buttons) - min(b.winfo_width() for b in buttons) <= 1
        assert max(b.winfo_height() for b in buttons) - min(b.winfo_height() for b in buttons) <= 1
        assert all(abs(b.winfo_height() - reference.winfo_height()) <= 1 for b in buttons)
        assert owner.maintenance_help.winfo_y() >= max(b.winfo_y()+b.winfo_height() for b in buttons)
        heights = [b.winfo_height() for b in buttons]
        window.geometry('%dx%d' % (width + 120, height + 240))
        window.update()
        assert heights == [b.winfo_height() for b in buttons]
        assert owner.maintenance_help.winfo_y()+owner.maintenance_help.winfo_height() <= panel.winfo_height()
    window.destroy()


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
            _verify_maintenance_controls(root, tk)
            report['maintenance_equal_grid_en_zh'] = True
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
            toolbar=sorted(ui.route_toolbar.winfo_children(),key=lambda w:(int(w.grid_info()['row']),int(w.grid_info()['column'])))
            assert [str(w.cget('text')) for w in toolbar]==[
                'New route','New SPG','Duplicate','Delete','Undo','Redo',
                'Make main','Make reserve','Check map','Fit view','Load image','Restore']
            assert [(int(w.grid_info()['row']),int(w.grid_info()['column'])) for w in toolbar]==[(i//6,i%6) for i in range(12)]
            assert str(ui.route_restore_button.cget('state'))=='disabled'
            ui.set_language('zh')
            assert ui.route_restore_button.cget('text')=='恢复'
            assert ui.route_restore_menu.entrycget(0,'label')=='恢复本路线'
            assert ui.route_restore_menu.entrycget(1,'label')=='恢复默认路线'
            ui.set_language('en')
            assert ui.route_restore_menu.entrycget(0,'label')=='Reset route'
            assert ui.route_restore_menu.entrycget(1,'label')=='Restore default routes'
            assert ui.document==readonly
            report['default_readonly']=True
            ui.adopt(storage.contract.default_profile('Baseline verification'))
            assert str(ui.route_restore_button.cget('state'))=='normal'
            ui.map_var.set('Ruinberg');ui.change_map()
            ui.route_class_var.set('AT-SPG');ui.change_route_class()
            original=next(r for r in storage.contract.default_map('08_ruinberg')['default_routes']
                if r['team']==ui.team and r.get('class_tag')=='AT-SPG' and not r.get('disabled'))
            ui.selection=('builtin',original['id']);ui._refresh_properties()
            ui._editable_item()['points'][1][0]+=8;ui.route_restore_menu.invoke(0)
            assert ui._editable_item()==original
            report['route_toolbar_and_restore_menu']=True
            report['baseline_route_restore']=True
            from bot_tactics_ui import CLASS_COLORS
            ui.route_class_var.set('total');ui.change_route_class()
            for key in ui.items.get_children():
                if key.startswith('builtin:'):
                    tag='route_'+key.rsplit('@',1)[1]
                    assert tag in ui.items.item(key,'tags')
                    assert str(ui.items.tag_configure(tag,'foreground'))==CLASS_COLORS[tag[6:]]
            report['route_tree_class_colors']=True
            ui.store.save(storage.contract.empty('Smoke fixture'),apply=True)
            ui.adopt(ui.store.active())
            for key,value in dict(skill='regular',development='full',equipment='improved',consumables='large',crew_preset='all',outfit='off',ammo_limit='0').items():ui.rule_vars[key].set(value)
            for var in ui.ammo_vars:var.set('0')
            ui.save_rule()
            report['independent_presets_and_empty_ammo']=True
            preview=ui.preview_rule();root.update()
            rendered=[preview.table.item(i,'values') for i in preview.table.get_children()]
            assert len(rendered)==13 and any('0 : 0 : 0' in str(row) for row in rendered)
            assert sum(row[0]=='Crew preset' for row in rendered)==1
            assert any(row[0]=='Ammunition count limit' and row[1]=='0' for row in rendered)
            ui.set_language('zh');root.update()
            assert preview.root.title()=='生效值预览'
            assert any('成员配置' in str(preview.table.item(i,'values')) for i in preview.table.get_children())
            ui.set_language('en');root.update();preview.root.destroy()
            ui.rule_vars['ammo_limit'].set('1');ui.save_rule()
            assert any(row['values'].get('ammo_limit')==1 for row in ui.document['behavior'])
            report['zero_one_ammo_limit']=True
            report['scoped_effective_preview']=True
            import save_slots
            slots_root=Path(temp)/'isolated-saves'
            record=save_slots.create_slot('Full unlock smoke',save_slots.MODE_UNLOCKED,root=str(slots_root))
            slot=Path(record['path']);(slot/'garage_state.json').write_text('{}')
            (slot/'launcher_crew_inbox.json').write_text('{"pending":"old"}')
            reset=save_slots.initialize_slot(record['id'],root=str(slots_root),is_running=lambda:False)
            assert not reset['record']['has_state'] and not (slot/'launcher_crew_inbox.json').exists()
            assert Path(reset['backup']).is_file()
            assert json.loads((slot/'save.json').read_text())['skip_legacy_import'] is True
            report['save_initialization_and_backup']=True
            import wot_launcher
            owner=type('SaveActionsFixture',(),{})()
            owner._tk=tk;owner.save_panel=tk.Frame(root);owner.save_panel.pack(fill='x')
            for method in ('_open_save_dialog','_new_save_slot','_rename_save_slot','_delete_save_slot',
                           '_open_save_folder','_backup_save_slot','_restore_save_slot','_initialize_save_slot'):
                setattr(owner,method,lambda:None)
            wot_launcher.LauncherWindow._build_save_actions(owner)
            buttons=[owner.customize_save_button,owner.new_save_slot_button,owner.rename_save_slot_button,
                owner.delete_save_slot_button,owner.open_save_folder_button,owner.backup_save_button,
                owner.restore_save_button,owner.initialize_save_button]
            for i,button in enumerate(buttons):button.configure(text='Button %d'%i)
            root.geometry('1000x300');root.deiconify();root.update()
            assert len({button.winfo_width() for button in buttons})<=2
            assert [int(button.grid_info()['row']) for button in buttons]==[0]*4+[1]*4
            assert [int(button.grid_info()['column']) for button in buttons]==list(range(4))*2
            owner.save_panel.destroy();root.withdraw()
            report['save_actions_two_by_four']=True


            assert storage.contract.effective(ui.document,1,'heavyTank',0)['outfit']=='off'
            from types import SimpleNamespace
            from tkinter import ttk
            import crew_ui
            owner=SimpleNamespace(_tk=tk,_ttk=ttk,_t=lambda value:value,
                game_root=tk.StringVar(value='smoke fixture'),_save_slot_id='smoke',_busy=False,_maintenance_busy=False)
            panel=crew_ui.CrewPanel(owner,ttk.Frame(root))
            panel.vehicles=[dict(name='ussr:R11_MS-1',nation='ussr',label='MS-1',roles=('commander','driver'),vehicleClass='lightTank',seats=crew_ui.store.crew_skills.seats('ussr:R11_MS-1'))]
            panel.capacity_state=dict(total=2000,occupied=0,pending=0,available=2000)
            panel.filter();assert panel.by_label
            panel.variables['female'].set('Female');panel.variables['skills'].set('2')
            original_add=crew_ui.store.add;calls=[]
            try:
                crew_ui.store.add=lambda *args,**kwargs:calls.append((args,kwargs))
                original_capacity=crew_ui.store.capacity
                crew_ui.store.capacity=lambda *a,**k:dict(total=2000,occupied=0,pending=1,available=1999)
                assert panel.add()
                assert calls==[(('smoke','smoke fixture','ussr:R11_MS-1',0,True,2),{'training':100})]
            finally:
                crew_ui.store.add=original_add
                crew_ui.store.capacity=original_capacity
            panel.variables['class'].set('Heavy tank');panel.filter();assert not panel.by_label
            assert str(panel.button.cget('state'))=='disabled'
            report['crew_controls_and_outfit_override']=True
            name='ussr:R45_IS-7'
            panel.vehicles=[dict(name=name,nation='ussr',label='IS-7',vehicleClass='heavyTank',
                seats=crew_ui.store.crew_skills.seats(name))]
            panel.filter();panel.variables['seat'].set('Loader2 (Also Radio operator)');panel.update_skills()
            assert max(panel.maps['skills'].values())==11
            panel.variables['skills'].set('11');panel.variables['seat'].set('Loader1');panel.update_skills()
            assert panel.variables['skills'].get()=='7'
            panel.variables['training'].set('50%');panel.update_skills()
            assert panel.variables['skills'].get()=='1' and str(panel.boxes['skills'].cget('state'))=='disabled'
            panel.variables['training'].set('100%');panel.update_skills()
            assert min(panel.maps['skills'].values())==1
            report['seat_aware_recruits']=True
            import nation_choices
            assert list(panel.maps['nation'].values())==list(nation_choices.ORDER)
            assert panel.boxes['nation'].cget('values')[0]=='China'
            assert panel.expand_button.cget('text')=='Add 16 barracks berths'
            with tempfile.TemporaryDirectory(prefix='barracks-smoke-') as beds:
                record=save_slots.create_slot('Career',save_slots.MODE_NEW_ACCOUNT,root=beds)
                identity=record['id']
                assert crew_ui.store.capacity(identity,root=beds)['total']==30
                for total in (46,62):
                    assert crew_ui.store.expand_berths(identity,root=beds,is_running=lambda:False)['total']==total
                assert json.loads((Path(record['path'])/'save.json').read_text())['initial_berths']==62
            report['nation_order_and_barracks_capacity']=True

            _verify_vehicle_editor_language(root, tk, ttk)
            report['vehicle_editor_language_preserved']=True

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
            ui.document['name']='Packaged editor smoke'
            ui.profile_name.set(ui.document['name'])
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
            # Drive connection controls through the frozen editor's save owner.
            ui.route_class_var.set('heavyTank');ui.change_route_class()
            ui.selection=('routes',next(r['id'] for r in active['maps']['08_ruinberg']['routes'] if r['team']==ui.team and 'heavyTank' in r['classes']))
            ui.selected_point=0;ui.insert_point();ui._refresh_properties()
            assert str(ui.defense_add.cget('state'))=='normal',(ui.selection,ui.selected_point,ui.network_mode,ui._selected_parent())
            ui.add_defense();ui.selected_point=0;ui.insert_point();ui.save(True)
            active=ui.store.active()
            authored=next(r for r in active['maps']['08_ruinberg']['routes'] if r['team']==ui.team and 'heavyTank' in r['classes'])
            assert len(authored['defense']['points'])==3 and not ui.dirty()
            ui.network_mode='';ui.set_tier('reserve');ui.save(True)
            assert next(r for r in ui.store.active()['maps']['08_ruinberg']['routes'] if r['team']==ui.team and 'heavyTank' in r['classes'])['tier']=='reserve'
            ui.route_class_var.set('SPG');ui.change_route_class();ui.new_route();ui.save(True)
            active=ui.store.active()
            assert any(r.get('purpose')=='spg_attack' for r in active['maps']['08_ruinberg']['routes'])
            assert all(not p.get('travel') and not p.get('links') for p in active['maps']['08_ruinberg']['positions'])
            report['authored_connections_and_route_tiers']=True
            assert ui.route_class_var.get()=='spg_attack'
            assert ui.canvas.find_withtag('artillery_attack')
            assert not ui.item_fields['route_priority'][0].grid_info()
            assert not ui.classes_frame.grid_info()
            assert str(ui.tier_buttons['main'].cget('state'))=='disabled'
            ui.route_class_var.set('all');ui.change_route_class()
            assert not ui.canvas.find_withtag('artillery_attack')
            ui.route_class_var.set('SPG');ui.change_route_class()
            assert not hasattr(ui,'connect_all_button') and not hasattr(ui,'network_box')
            assert not ui.tree_connections
            ui.save(True);assert not ui.dirty()
            assert ui.defense_panel!=ui.artillery_panel
            report['automatic_parking_navigation']=True
            report['separate_artillery_editor']=True
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
            # Exercise shared defense ownership in the actual frozen widgets.
            from gui.mods.offline_lan_0922 import route_network
            ui.map_var.set('Ruinberg');ui.change_map()
            ui.route_class_var.set('all');ui.change_route_class();root.update()
            source=next(r for r in ui.entry()['routes'] if r['team']==ui.team and 'heavyTank' in r['classes'])
            source['symmetric']=False;source.pop('mirror_id',None);source['family']=source['id']
            peer=route_network.clone_route(source);peer.update(id='smoke_shared_peer',classes=['mediumTank'],family=source['id'])
            route_network.insert_node(peer,1,[peer['points'][0][0]+5,peer['points'][0][1]+5,0])
            ui.entry()['routes'].append(peer)
            ui.selection=('routes',source['id']);ui.network_mode='defense';ui.selected_point=0;ui._refresh_items()
            before=copy.deepcopy(ui.document);ui.insert_point();root.update()
            assert ui.network_mode=='defense',(ui.selection,ui.map_name,ui.route_class_var.get(),ui.items.selection(),source['id'])
            assert [[round(v,4) for v in p] for p in source['defense']['points']]==[[round(v,4) for v in p] for p in peer['defense']['points']]
            assert source['points']==peer['points']
            assert source['node_ids']==peer['node_ids']
            shared=copy.deepcopy(ui.document);ui.undo('maps');assert ui.document==before
            ui.redo('maps');assert ui.document==shared
            ui.save(True);assert not ui.dirty()
            report['shared_defense_transactions']=True
            report['common_route_reset']=True
            import bot_tactics_geometry as geometry
            for name in ('13_erlenberg','63_tundra'):
                graph=storage.graph_data(name);ends=geometry.anchors(graph,1)
                expected=graph['spawn_anchors'][1] if geometry.symmetry_allowed(graph) else graph['objective_bases'][1]
                assert geometry.same_point(ends[-1],expected)
            ui.adopt(storage.contract.default_profile('Endpoint verification'))
            ui.map_var.set('Tundra');ui.change_map();ui.route_class_var.set('total');ui.change_route_class()
            for team in (1,2,1):
                ui.team_var.set(str(team));ui.change_map();ui.redraw()
                assert ui.canvas.find_withtag('connection_team_'+str(team))
                assert not ui.canvas.find_withtag('connection_team_'+str(3-team))
                assert ui.network_mode==''
            report['map_endpoint_policy_and_team_connections']=True
            ui.selection=('builtin','village@heavyTank');ui._refresh_items()
            before=copy.deepcopy(ui.document)
            assert str(ui.tier_buttons['reserve'].cget('state'))=='normal'
            ui.tier_buttons['reserve'].invoke()
            expected=copy.deepcopy(before)
            selected=next(r for r in expected['maps']['63_tundra']['default_routes']
                if r['team']==1 and r['id']=='village' and r.get('class_tag')=='heavyTank')
            selected['tier']='reserve'
            assert ui.document==expected
            assert str(ui.tier_buttons['main'].cget('state'))=='normal'
            ui.undo('maps');assert ui.document==before
            ui.redo('maps');assert ui.document==expected
            ui.save(False);assert not ui.dirty()
            report['total_view_route_tier_controls']=True
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
