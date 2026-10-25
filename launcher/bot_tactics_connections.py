"""Route tier and connection editing; all writes remain draft/undo owned."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from bot_tactics_artillery import ArtilleryEditorMixin

from gui.mods.offline_lan_0922 import route_network


class ConnectionEditorMixin(ArtilleryEditorMixin):
    def _build_connections(self, parent):
        panel = ttk.LabelFrame(parent, text=self.tr('回防路线编辑', 'Defense connection editor'))
        self.defense_panel=panel
        panel.grid(row=23, column=0, sticky='ew', pady=5)
        self.network_mode = ''
        self.network_link = ''
        self.defense_add = ttk.Button(panel, text=self.tr('添加回防路线', 'Add defense connection'), command=self.add_defense)
        self.defense_add.pack(fill='x')
        self.defense_delete = ttk.Button(panel, text=self.tr('删除回防路线', 'Delete defense connection'), command=self.delete_defense)
        self.defense_delete.pack(fill='x')
        self.defense_edit=ttk.Button(panel,text=self.tr('编辑／返回回防路线','Edit / leave defense connection'),command=self.edit_defense)
        self.defense_edit.pack(fill='x')
        ttk.Label(panel,text=self.tr('仅普通中间节点可挂接回防线；回防反向经过等待点不等待。',
            'Only ordinary intermediate nodes can own a defense branch. Reverse defense travel skips waits.'),wraplength=250).pack(anchor='w')
        panel=ttk.LabelFrame(parent,text=self.tr('火炮路线编辑','Artillery route editor'))
        self.artillery_panel=panel;panel.grid(row=24,column=0,sticky='ew',pady=5)
        self.network_box = ttk.Combobox(panel, state='readonly', values=(), width=28)
        self.network_box.pack(fill='x')
        self.network_box.bind('<<ComboboxSelected>>', self.choose_network)
        self.connect_all_var=tk.BooleanVar(value=False)
        self.connect_all_button=ttk.Checkbutton(panel,text=self.tr('连接全部炮位','Connect all parking positions'),
            variable=self.connect_all_var,command=self.connect_all_positions)
        self.connect_all_button.pack(anchor='w')
        self.link_target = ttk.Combobox(panel, state='readonly', width=28)
        self.link_target.pack(fill='x')
        self.link_add = ttk.Button(panel, text=self.tr('连接到炮位', 'Connect parking positions'), command=self.add_spg_link)
        self.link_add.pack(fill='x')
        self.link_delete=ttk.Button(panel,text=self.tr('删除炮位连接','Delete parking connection'),command=self.delete_spg_link)
        self.link_delete.pack(fill='x')
        ttk.Label(panel, wraplength=250, text=self.tr(
            '红色实线：基地到炮位的部署线、炮位间换位线；红色虚线：火炮进攻路线。己方只剩火炮时，选取最多3辆火炮BOT先回己方基地，再沿进攻路线行进。连接全部炮位是一次性补连接操作，完成后自动取消勾选；保留已有连接，生成直连后仍需编辑和检查。',
            'Red solid: deployment and relocation. Red dashed: artillery attack. When the own team has only artillery left, up to three artillery Bots return to the own base and follow an attack route. Connect all is a one-shot action which clears its check, preserves existing links and adds missing straight connections for editing and checking.')).pack(anchor='w')

    def _selected(self):
        item = self._selected_parent()
        mode = getattr(self, 'network_mode', '')
        if item is None or not mode:return item
        points = self._connection_points(item)
        return dict(item, points=points) if points else item

    def _connection_points(self, item):
        if self.network_mode == 'defense':return (item.get('defense') or {}).get('points')
        if self.network_mode == 'travel':return item.get('travel')
        if self.network_mode == 'link':return item.get('links', {}).get(self.network_link)

    def _editable_item(self):
        return self._editable_parent()

    def _editable_points(self):
        item = self._editable_parent()
        if getattr(self, 'network_mode', ''):return self._connection_points(item)
        return item['points']

    def _refresh_connections(self):
        if not hasattr(self, 'network_box'):return
        item = self._selected_parent()
        route = bool(item and self.selection[0] in ('builtin', 'routes'))
        parking = bool(item and self.selection[0] in ('positions', 'builtin_positions'))
        attack=bool(item and item.get('purpose')=='spg_attack')
        choices = [(self.tr('炮位','Parking'), '', '')]
        if parking:
            choices.append((self.tr('基地到炮位', 'Base to parking'), 'travel', ''))
            for key in sorted(item.get('links', {})):choices.append((self._connection_caption('link',key), 'link', key))
        self.network_choices = choices
        self.network_box.configure(values=[row[0] for row in choices],state='readonly' if parking else 'disabled')
        selected = next((i for i, row in enumerate(choices) if row[1:] == (self.network_mode, self.network_link)), 0)
        self.network_box.current(selected)
        if parking and selected==0 and self.network_mode!='travel':self.network_mode='';self.network_link=''
        if self.network_mode=='defense' and not (item or {}).get('defense'):self.network_mode=''
        if parking and self.network_mode=='link' and self.network_link not in item.get('links',{}):self.network_mode='';self.network_link=''
        ordinary_route=route and not attack
        artillery_view=parking or attack or self.route_class_var.get() in ('SPG','spg_attack')
        self.artillery_panel.grid() if artillery_view else self.artillery_panel.grid_remove()
        self.defense_panel.grid_remove() if artillery_view else self.defense_panel.grid()
        index = self.selected_point
        ordinary = (ordinary_route and not self.network_mode and index is not None and
                    0 < index < len(item['points'])-1 and not item['points'][index][2] and
                    not item.get('defense'))
        editable = not self.builtin and self.route_class_var.get() != 'total'
        self.defense_add.configure(state='normal' if editable and ordinary else 'disabled')
        self.defense_delete.configure(state='normal' if editable and ordinary_route and item.get('defense') else 'disabled')
        self.defense_edit.configure(state='normal' if ordinary_route and item.get('defense') else 'disabled')
        self.connect_all_button.configure(state='normal' if editable and self.route_class_var.get()=='SPG' and len(self._parking_items())>=2 else 'disabled')
        self.route_duplicate_button.configure(state='normal' if not self.builtin and item and not self.network_mode else 'disabled')
        self.link_add.configure(state='normal' if editable and parking else 'disabled')
        self.link_delete.configure(state='normal' if editable and parking and self.network_mode=='link' else 'disabled')
        peers = [p for p in self._parking_items() if parking and p['id']!=item['id']]
        self.link_targets = dict((p['id'], p) for p in peers)
        self.link_target.configure(values=sorted(self.link_targets))
        if self.link_target.get() not in self.link_targets:self.link_target.set('')
        if hasattr(self, 'route_delete_button'):
            self.route_delete_button.configure(state='normal' if not self.builtin and (parking or attack or bool(self.network_mode) or self.route_class_var.get()=='all') else 'disabled')
        for tier, button in getattr(self, 'tier_buttons', {}).items():
            button.configure(state='normal' if editable and ordinary_route and not self.network_mode and item.get('tier','main')!=tier else 'disabled')
        junction=bool(route and not self.network_mode and item.get('defense') and index is not None and 0<=index<len(item['points']) and route_network.nodes(item)[index]==item['defense']['junction'])
        if self.network_mode or junction or attack:
            for control in (self.wait_button,self.wait_edit_check,self.hold_button):control.configure(state='disabled')

    def choose_network(self, event=None):
        unused, self.network_mode, self.network_link = self.network_choices[self.network_box.current()]
        if self.network_mode == 'travel':
            item = self._selected_parent()
            if not item.get('travel'):
                if self.builtin:self.network_mode = '';return
                self.checkpoint()
                item = self._editable_parent()
                base = self.graph_cache[self.map_name]['objective_bases'][self.team-1]
                item['travel'] = [list(base)+[0], list(item['point'])+[0]]
                self.mark()
        self.wait_edit = False;self.selected_wait = None;self.selected_point = 0
        self._refresh_items()

    def _sync_connection_scope(self, fields=('defense',)):
        if self.route_class_var.get() != 'all' or not self.selection:return
        item = self._editable_parent()
        if self.selection[0] in ('builtin','routes'):
            rows = self.entry().get('default_routes' if self.selection[0]=='builtin' else 'routes', ())
            family=item.get('family',item['id'])
            targets=[row for row in rows if row['team']==self.team and row.get('family',row['id'])==family and row is not item]
            if 'defense' in fields and item.get('defense'):
                index=route_network.nodes(item).index(item['defense']['junction'])
                anchor=item['points'][index][:2];junctions={}
                for row in targets:
                    matches=[i for i,p in enumerate(row['points']) if 0<i<len(row['points'])-1 and p[:2]==anchor and not p[2]]
                    if len(matches)!=1:
                        raise ValueError(self.tr('部分车型没有对应的普通挂接点，请先对齐或按车型编辑回防线。','Some classes lack the matching ordinary junction; align nodes or edit defense by class.'))
                    junctions[id(row)]=matches[0]
            for row in targets:
                if 'defense' in fields and item.get('defense'):
                    row['node_ids']=list(route_network.nodes(row))
                    row['defense']=copy.deepcopy(item['defense'])
                    row['defense']['junction']=row['node_ids'][junctions[id(row)]]
                elif 'defense' in fields:row.pop('defense',None)
                if 'tier' in fields:row['tier']=item.get('tier','main')

    def add_defense(self):
        if self.builtin or str(self.defense_add.cget('state')) == 'disabled':return
        before = copy.deepcopy(self.document)
        history=copy.deepcopy(self.histories);selection=self.selection
        self.checkpoint()
        try:
            item = self._editable_parent();index = self.selected_point
            ids = route_network.ensure_nodes(item)
            base = self.graph_cache[self.map_name]['objective_bases'][self.team-1]
            item['defense'] = dict(junction=ids[index], points=[item['points'][index][:2]+[0], list(base)+[0]])
            self._sync_connection_scope()
        except ValueError as error:
            self.document=before;self.histories=history;self.selection=selection
            self._refresh_items();self.error(error);return
        self.network_mode = 'defense';self.network_link = '';self.selected_point = 0
        self._refresh_items();self.mark()

    def delete_defense(self):
        if self.builtin:return
        self.checkpoint();self._editable_parent().pop('defense', None)
        self._sync_connection_scope();self.network_mode = '';self._refresh_items();self.mark()

    def add_spg_link(self):
        peer = self.link_targets.get(self.link_target.get())
        if peer is None or self.builtin:return
        item=self._selected_parent()
        if peer['id'] not in item.get('links',{}):
            self.checkpoint();item=self._editable_parent()
            item.setdefault('links', {})[peer['id']] = [list(item['point'])+[0], list(peer['point'])+[0]]
        self.network_mode = 'link';self.network_link = peer['id'];self.selected_point = 0
        self._refresh_items();self.mark()

    def set_tier(self, tier):
        if self.builtin or self.route_class_var.get() == 'total' or self.network_mode or (self._selected_parent() or {}).get('purpose')=='spg_attack':return
        self.checkpoint();self._editable_parent()['tier'] = tier
        self._sync_connection_scope(('tier',));self._refresh_items();self.mark(sync=False)

    def restore_default_routes(self):
        if self.builtin:return
        if not messagebox.askyesno(self.tr('恢复默认路线', 'Restore default routes'), self.tr(
                '恢复所有地图的内置路线点位、等待位、主备用状态及回防线。保留自建路线。',
                'Restore built-in routes, waits, tiers and defense connections on every map. Keep custom routes.'), parent=self.root):return
        self.checkpoint()
        baseline = self.store.contract.default_profile() if hasattr(self.store, 'contract') else None
        if baseline is None:
            from gui.mods.offline_lan_0922 import bot_tactics
            baseline = bot_tactics.default_profile()
        for name, settings in baseline['maps'].items():
            entry = self.document['maps'].setdefault(name, dict(settings, routes=[], positions=[]))
            entry['default_routes'] = copy.deepcopy(settings.get('default_routes', []))
        self.network_mode = '';self.selection = None;self._refresh_items();self.mark()

    def delete_spg_link(self):
        if self.builtin or self.network_mode!='link':return
        self.checkpoint();self._editable_parent().get('links',{}).pop(self.network_link,None)
        self.network_mode='';self.network_link='';self._refresh_items();self.mark()

    def _draw_connection_set(self,item,color,selected=False):
        paths=[]
        if item.get('defense'):paths.append(('defense','',item['defense']['points'],color,(5,4),self.tr('回防','Defense')))
        if item.get('travel'):paths.append(('travel','',item['travel'],self.connection_colors['SPG'],(),self.tr('部署','Deploy')))
        for key,points in item.get('links',{}).items():paths.append(('link',key,points,self.connection_colors['SPG'],(),self.tr('换位','Relocate')))
        for mode,identity,points,color,dash,caption in paths:
            coords=[v for p in points for v in self.view.screen(p)]
            if len(coords)>=4:self.canvas.create_line(*coords,fill=color,width=3 if selected else 2,dash=dash,arrow='last',tags=('authored_connection',))
            x,y=self.view.screen(points[len(points)//2]);self.canvas.create_text(x,y-10,text=caption,fill=color)
            if selected and self.network_mode==mode and self.network_link==identity:
                for index,p in enumerate(points):self._draw_route_node(p,index,color,True,5,True)

    def _draw_connections(self):
        selected=self._selected_parent() if self.selection else None
        for route,tag,identity in self._builtin_views():
            edit=self._default_edit(route,tag)
            if edit:self._draw_connection_set(edit,self.connection_colors.get(tag,'black'),self.selection==('builtin',identity))
        positions=self.entry()['positions']+[p for p in self.spg_defaults if not any(v['id']==p['id'] for v in self.entry()['positions'])]
        for kind,rows in (('routes',self.entry()['routes']),('positions',positions)):
            for item in rows:
                if item['team']!=self.team or not self._visible_for_class(kind,item):continue
                tag='SPG' if kind=='positions' else self._route_scope()
                self._draw_connection_set(item,self.connection_colors.get(tag,'black'),bool(selected and selected['id']==item['id']))
