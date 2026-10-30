"""Inventory editor for owned preset styles, including retail-hidden styles."""
try:
    from . import save_customizations as store, nation_choices, vehicle_editor_ui
except ImportError:
    import save_customizations as store, nation_choices, vehicle_editor_ui


class CustomizationsDialog(object):
    def __init__(self, owner):
        self.owner = owner
        self.slot = owner._save_slot_id
        self.game_root = owner.game_root.get().strip()
        self.items, self.vehicles = store.appearance_catalogue(self.game_root)
        self.styles = [i for i in self.items if i['kind'] == store.STYLE_TYPE]
        self.inventory = store.read_inventory(self.slot, self.game_root, self.styles, self.vehicles)
        unused_path, saved, unused_container, unused_key, has_garage = store._target(self.slot, self.game_root)
        self.garage_ids = set(saved.get('vehicles', {})) if has_garage else None
        tk, ttk, tr = owner._tk, owner._ttk, owner._t
        self.window = tk.Toplevel(owner.save_dialog)
        self.window.title(tr('Appearance inventory'))
        self.window.geometry('1180x650')
        self.window.transient(owner.save_dialog)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = tk.Frame(self.window, padx=12, pady=12)
        frame.pack(fill='both', expand=True)
        self.vehicle = tk.StringVar(value=tr('All compatible vehicles'))
        filters = tk.Frame(frame)
        filters.grid(row=0, column=0, columnspan=2, sticky='we')
        self.nation = tk.StringVar(value=tr('All'))
        self.vehicle_class = tk.StringVar(value=tr('All'))
        self.tier = tk.StringVar(value=tr('All'))
        self.category = tk.StringVar(value=tr('All'))
        self.search = tk.StringVar()
        self.garage_only = tk.BooleanVar(value=True)
        self.nations = {tr('All'): None}
        self.nations.update((nation_choices.caption(n,tr),n) for n in nation_choices.ordered(v['nation'] for v in self.vehicles))
        self.classes = {tr('All'): None}
        self.classes.update((tr(label),name) for name,label in vehicle_editor_ui.VEHICLE_CLASS_LABELS)
        self.tiers = {tr('All'): None}
        self.tiers.update((str(level),level) for level in sorted(set(
            v['level'] for v in self.vehicles if isinstance(v.get('level'),int))))
        self.categories = {tr('All'):None}
        self.categories.update((tr(name),name) for name in ('Paint','Camouflage','Emblem','Inscription','Wear'))
        for col, label, variable, values in ((0,'Nation',self.nation,self.nations),
                (1,'Type',self.vehicle_class,self.classes), (2,'Tier',self.tier,self.tiers),
                (4,'Category',self.category,self.categories)):
            tk.Label(filters,text=tr(label)).grid(row=0,column=col,sticky='w')
            box=ttk.Combobox(filters,textvariable=variable,values=tuple(values),state='readonly',width=15)
            box.grid(row=1,column=col,sticky='we',padx=(0,6))
            box.bind('<<ComboboxSelected>>',self.filter_vehicles if col<3 else self.refresh)
        tk.Label(filters,text=tr('Vehicle')).grid(row=0,column=3,sticky='w')
        self.vehicle_box=ttk.Combobox(filters,textvariable=self.vehicle,state='readonly',width=36)
        self.vehicle_box.grid(row=1,column=3,sticky='we',padx=(0,6))
        self.vehicle_box.bind('<<ComboboxSelected>>',self.refresh)
        tk.Label(filters,text=tr('Search')).grid(row=0,column=5,sticky='w')
        entry=ttk.Entry(filters,textvariable=self.search,width=18)
        entry.grid(row=1,column=5,sticky='we')
        entry.bind('<KeyRelease>',self.filter_vehicles)
        tk.Checkbutton(filters,text=tr('Garage vehicles only'),variable=self.garage_only,
                       command=self.filter_vehicles).grid(row=2,column=0,columnspan=3,sticky='w')
        filters.grid_columnconfigure(3,weight=1)
        self.notebook=ttk.Notebook(frame)
        self.notebook.grid(row=1,column=0,columnspan=2,sticky='nsew',pady=8)
        self.tables=[]
        for caption in ('My style','Preset styles'):
            page=ttk.Frame(self.notebook)
            self.notebook.add(page,text=tr(caption))
            table=ttk.Treeview(page,columns=('style','scope','availability','stock','vehicles'),show='headings',height=16,selectmode='extended')
            for name,label,width in (('style','Appearance item',210),('scope','Applicable range',480),
                    ('availability','Category',120),('stock','Inventory',100),('vehicles','Compatible vehicles',110)):
                table.heading(name,text=tr(label));table.column(name,width=width,anchor='w')
            table.grid(row=0,column=0,sticky='nsew')
            scroll=ttk.Scrollbar(page,orient='vertical',command=table.yview)
            scroll.grid(row=0,column=1,sticky='ns');table.config(yscrollcommand=scroll.set)
            scroll=ttk.Scrollbar(page,orient='horizontal',command=table.xview)
            scroll.grid(row=1,column=0,sticky='we');table.config(xscrollcommand=scroll.set)
            table.bind('<<TreeviewSelect>>',self.show_scope)
            page.grid_columnconfigure(0,weight=1);page.grid_rowconfigure(0,weight=1)
            self.tables.append(table)
        self.table=self.tables[0]
        self.notebook.bind('<<NotebookTabChanged>>',self.change_tab)
        controls = tk.Frame(frame)
        controls.grid(row=3, column=0, columnspan=2, sticky='we')
        tk.Label(controls, text=tr('Quantity to add per selected item')).pack(side='left')
        self.quantity = tk.StringVar(value='1')
        ttk.Spinbox(controls, from_=1, to=100000, textvariable=self.quantity, width=8).pack(side='left', padx=8)
        tk.Button(controls, text=tr('Add selected items'), command=self.add).pack(side='left', padx=4)
        tk.Label(frame, text=tr('Add the entered quantity to each selected item. Vehicle-bound items are added for each compatible target vehicle. '
            'Rental copies grant their original battle count. Save with the game closed; additions appear in game system messages.'),
            wraplength=1100, justify='left').grid(row=4, column=0, columnspan=2, sticky='we', pady=8)
        self.feedback = tk.Label(frame, text='', wraplength=610, justify='left')
        self.feedback.grid(row=5, column=0, columnspan=2, sticky='we')
        self.scope_detail=tk.Label(frame,text='',wraplength=1100,justify='left',anchor='w')
        self.scope_detail.grid(row=6,column=0,columnspan=2,sticky='we',pady=8)
        actions = tk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=2, sticky='we', pady=(8, 0))
        tk.Button(actions, text=tr('Save changes'), command=self.save).pack(side='left', expand=True, fill='x')
        tk.Button(actions, text=tr('Close'), command=self.close).pack(side='left', expand=True, fill='x')
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.filter_vehicles()
        self.window.grab_set()

    def change_tab(self, unused=None):
        self.table=self.tables[self.notebook.index(self.notebook.select())]
        self.refresh()

    def filter_vehicles(self, unused=None):
        tr=self.owner._t
        nation=self.nations.get(self.nation.get());kind=self.classes.get(self.vehicle_class.get())
        level=self.tiers.get(self.tier.get())
        text=self.search.get().strip().casefold()
        self.filtered_vehicles=[v for v in self.vehicles if (not nation or v['nation']==nation)
            and (not kind or v.get('vehicleClass')==kind)
            and (level is None or v.get('level')==level)
            and (not self.garage_only.get() or self.garage_ids is None or str(v['compact_descr']) in self.garage_ids)
            and (not text or text in (v['label']+' '+v['name']).casefold())]
        self.vehicle_by_label={tr('All compatible vehicles'):None}
        self.vehicle_by_label.update((v['label']+' ('+v['name']+')',v) for v in sorted(self.filtered_vehicles,
            key=lambda v:(nation_choices.ORDER.index(v['nation']),v.get('level',0),v['label'],v['name'])))
        self.vehicle_box.config(values=tuple(self.vehicle_by_label))
        if self.vehicle.get() not in self.vehicle_by_label:self.vehicle.set(tr('All compatible vehicles'))
        self.refresh()

    def targets(self):
        vehicle = self.vehicle_by_label.get(self.vehicle.get())
        return [vehicle] if vehicle is not None else self.filtered_vehicles

    def refresh(self, unused=None):
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        tr = self.owner._t
        preset=self.table is self.tables[1]
        def order(item):
            nations=[n for action,rule in item['rules'] if action=='include' for n in rule.get('nations',())]
            return (min([nation_choices.ORDER.index(n) for n in nations] or [len(nation_choices.ORDER)]),
                    {'Paint':0,'Camouflage':1,'Emblem':2,'Inscription':3,'Wear':4}.get(item['category'],5),item['id'])
        for style in sorted(self.items,key=order):
            if (style['kind']==store.STYLE_TYPE)!=preset:continue
            if not preset and self.categories.get(self.category.get()) not in (None,style['category']):continue
            applicable = [v for v in self.targets() if store.compatible(style, v)]
            if not applicable: continue
            bindings = self.inventory.get(str(style['kind']), {}).get(str(style['id']), {})
            count = bindings.get('0', 0) + sum(bindings.get(str(v['compact_descr']), 0) for v in applicable)
            category = ('Internet cafe' if style['igr'] else style['category']) if not preset else 'Hidden' if style['hidden'] else 'Rental' if style['rent_count'] else 'Permanent'
            caption = tr(category)
            if not preset:
                caption = tr(style['category'])
                if style['igr']: caption += ' / ' + tr('Internet cafe')
                if style.get('season','ALL').lower() != 'all': caption += ' / ' + tr(style['season'].lower())
            unit = tr('battles') if style['rent_count'] else tr('copies')
            self.table.insert('', 'end', iid='%d:%d'%(style['kind'],style['id']), values=(
                store.display_name(style,self.styles,tr) if preset else style['label'],store.applicability(style,self.vehicles,tr),
                caption, '%d %s' % (count, unit), len(applicable)))
        self.table.selection_set(*(key for key in selected if self.table.exists(key)))
        self.show_scope()

    def show_scope(self,unused=None):
        selected=self.table.selection()
        if not self.targets():
            self.scope_detail.config(text=self.owner._t('No vehicles match these filters.'))
            return
        text=(self.owner._t('Applicable range: %s') % self.table.item(selected[0],'values')[1]
              if selected else self.owner._t('Select a style to see its full applicable range.'))
        self.scope_detail.config(text=text)

    def add(self):
        try:
            copies = int(self.quantity.get())
            selected = set(self.table.selection())
            if not selected:
                self.feedback.config(text=self.owner._t('Select at least one appearance item.'))
                return
            import copy
            staged = copy.deepcopy(self.inventory)
            for style in self.items:
                if '%d:%d'%(style['kind'],style['id']) in selected:
                    store.add_item(staged, style, self.targets(), copies,
                        bound_vehicle=self.vehicle_by_label.get(self.vehicle.get()) is not None)
            self.inventory = staged
            self.refresh()
            self.feedback.config(text=self.owner._t('Inventory changed. Click Save to apply.'))
        except (ValueError, store.save_ledger.SaveLedgerError) as error:
            self.feedback.config(text=self.owner._t(str(error)))

    def save(self):
        try:
            store.write_inventory(self.slot, self.game_root, self.inventory)
            self.feedback.config(text=self.owner._t('Appearance inventory saved.'))
        except store.save_ledger.SaveLedgerError as error:
            self.feedback.config(text=self.owner._t(str(error)))

    def close(self):
        self.window.grab_release()
        self.window.destroy()
        self.owner.save_dialog.grab_set()
