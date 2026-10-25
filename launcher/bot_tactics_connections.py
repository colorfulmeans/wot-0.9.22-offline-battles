"""Route tier and connection editing; all writes remain draft/undo owned."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from bot_tactics_artillery import ArtilleryEditorMixin

from gui.mods.offline_lan_0922 import route_network, bot_tactics as contract


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
        ttk.Label(panel,text=self.tr('仅普通中间节点可挂接回防线；回防经过等待点不等待。全部车型共同覆盖后续回防路径，保留各车型已有挂接点；单车型及总路线只改选中车型。最后一次实际编辑生效，开启路线对称才同步另一队。',
            'Only ordinary intermediate nodes can own a defense branch; reverse travel skips waits. All classes shares later defense bends while preserving existing class junctions. A class or Total view edits only the selected class. Last edits win; route symmetry alone also updates the other team.'),wraplength=250).pack(anchor='w')
        panel=ttk.LabelFrame(parent,text=self.tr('火炮路线编辑','Artillery route editor'))
        self.artillery_panel=panel;panel.grid(row=24,column=0,sticky='ew',pady=5)
        ttk.Label(panel,wraplength=250,text=self.tr(
            '炮位部署、换位及返回炮位使用自动寻路。红色虚线仅用于残局进攻：最多3辆火炮先回己方基地，再沿进攻路线行进；途中回防反向沿进攻路线返回，不另设回防支线。',
            'Parking deployment, relocation and parking return use automatic navigation. Red dashed routes are endgame attacks: up to three artillery Bots return to their base before following an attack route. Defense reverses the attack route; no artillery defense branch is needed.')).pack(anchor='w')

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
        if not hasattr(self, 'defense_panel'):return
        item = self._selected_parent()
        route = bool(item and self.selection[0] in ('builtin', 'routes'))
        parking = bool(item and self.selection[0] in ('positions', 'builtin_positions'))
        attack=bool(item and item.get('purpose')=='spg_attack')
        if self.network_mode=='defense' and not (item or {}).get('defense'):self.network_mode=''
        ordinary_route=route and not attack
        artillery_view=parking or attack or self.route_class_var.get() in ('SPG','spg_attack')
        self.artillery_panel.grid() if artillery_view else self.artillery_panel.grid_remove()
        self.defense_panel.grid_remove() if artillery_view else self.defense_panel.grid()
        index = self.selected_point
        ordinary = (ordinary_route and not self.network_mode and index is not None and
                    0 < index < len(item['points'])-1 and not item['points'][index][2] and
                    not item.get('defense'))
        editable = not self.builtin
        self.defense_add.configure(state='normal' if editable and ordinary else 'disabled')
        self.defense_delete.configure(state='normal' if editable and ordinary_route and item.get('defense') else 'disabled')
        self.defense_edit.configure(state='normal' if ordinary_route and item.get('defense') else 'disabled')
        self.route_duplicate_button.configure(state='normal' if not self.builtin and item and not self.network_mode else 'disabled')
        if hasattr(self, 'route_delete_button'):
            self.route_delete_button.configure(state='normal' if not self.builtin and (parking or attack or bool(self.network_mode) or self.route_class_var.get()=='all') else 'disabled')
        for tier, button in getattr(self, 'tier_buttons', {}).items():
            button.configure(state='normal' if editable and self.route_class_var.get()!='total' and ordinary_route and not self.network_mode and item.get('tier','main')!=tier else 'disabled')
        junction=bool(route and not self.network_mode and item.get('defense') and index is not None and 0<=index<len(item['points']) and route_network.nodes(item)[index]==item['defense']['junction'])
        if self.network_mode or junction or attack:
            for control in (self.wait_button,self.wait_edit_check,self.hold_button):control.configure(state='disabled')

    def _sync_connection_scope(self, fields=('defense',)):
        if not self.selection or self.selection[0] not in ('builtin','routes'):return
        item=self._editable_parent()
        if item.get('purpose')=='spg_attack':return
        shared=self._route_scope()=='all'
        rows=self._ensure_entry().setdefault('default_routes' if self.selection[0]=='builtin' else 'routes',[])
        family=item.get('family',item['id'])
        peers=[r for r in rows if r['team']==self.team and r.get('family',r['id'])==family
               and r is not item and r.get('purpose')!='spg_attack'
               and r.get('classes')!=['SPG']] if shared else []
        if 'tier' in fields:
            for row in peers:row['tier']=item.get('tier','main')
            return
        for row in peers:self._copy_defense(item,row)
        if not item.get('symmetric') or not self._symmetry_allowed():return
        other=3-self.team
        if self.selection[0]=='builtin':
            scope=item.get('class_tag','all')
            counterpart=next((r for r in rows if r['team']==other and r['id']==item['id']
                              and r.get('class_tag','all')==scope),None)
            if counterpart is None:
                inherited=next((r for r in rows if r['team']==other and r['id']==item['id']
                                and r.get('class_tag','all')=='all'),None)
                if inherited is None:raise ValueError(self.tr('另一队缺少对应路线。','The other team has no matching route.'))
                counterpart=copy.deepcopy(inherited);counterpart['class_tag']=scope;rows.append(counterpart)
            targets=[r for r in rows if r['team']==other and r['id']==item['id']] if shared else [counterpart]
        else:
            counterpart=next((r for r in rows if r['id']==item.get('mirror_id')),None)
            if counterpart is None:raise ValueError(self.tr('另一队缺少对应路线。','The other team has no matching route.'))
            targets=[r for r in rows if r['team']==other and r.get('family',r['id'])==counterpart.get('family',counterpart['id'])] if shared else [counterpart]
        for row in targets:
            if row.get('purpose')!='spg_attack' and row.get('classes')!=['SPG']:self._copy_defense(item,row)

    def _copy_defense(self, source, target):
        if target.get('disabled'):return
        branch=source.get('defense')
        if not branch:target.pop('defense',None);return
        points=copy.deepcopy(branch['points'])
        # Route symmetry reverses the authored road in world coordinates;
        # shared branch bends keep those coordinates and each team owns its base.
        old=target.get('defense')
        ids=list(route_network.nodes(target))
        # Existing class junctions are stable owners, not interchangeable indices.
        if old and old['junction'] in ids[1:-1]:index=ids.index(old['junction'])
        else:
            matches=[i for i,p in enumerate(target['points']) if 0<i<len(ids)-1
                     and abs(p[0]-points[0][0])<.00011 and abs(p[1]-points[0][1])<.00011
                     and not p[2] and not contract.waiting_positions(p)]
            if len(matches)!=1:raise ValueError(self.tr(
                '部分车型没有对应的普通挂接点，请先对齐或按车型编辑回防线。',
                'Some classes lack the matching ordinary junction; align nodes or edit defense by class.'))
            index=matches[0]
        if target['points'][index][2] or contract.waiting_positions(target['points'][index]):raise ValueError(self.tr('等待点不能挂接回防线。','A waiting node cannot own a defense branch.'))
        target['node_ids']=ids
        points[0]=target['points'][index][:2]+[0]
        points[-1]=list(self.graph_cache[self.map_name]['objective_bases'][target['team']-1])+[0]
        target['defense']=dict(junction=ids[index],points=points)

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
        except ValueError as error:
            self.document=before;self.histories=history;self.selection=selection
            self._refresh_items();self.error(error);return
        self.network_mode = 'defense';self.network_link = '';self.selected_point = 0
        self._refresh_items();self.mark()

    def delete_defense(self):
        if self.builtin:return
        self.checkpoint();self._editable_parent().pop('defense', None)
        self.network_mode = '';self._refresh_items();self.mark()

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

    def _draw_connection_set(self,item,color,selected=False):
        paths=[]
        if item.get('defense'):paths.append(('defense','',item['defense']['points'],color,(5,4),self.tr('回防','Defense')))
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
