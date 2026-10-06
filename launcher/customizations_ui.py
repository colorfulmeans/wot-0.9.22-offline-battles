"""Inventory editor for owned preset styles, including retail-hidden styles."""
try:
    from . import save_customizations as store
except ImportError:
    import save_customizations as store


class CustomizationsDialog(object):
    def __init__(self, owner):
        self.owner = owner
        self.slot = owner._save_slot_id
        self.game_root = owner.game_root.get().strip()
        self.styles, self.vehicles = store.catalogue(self.game_root)
        self.inventory = store.read_inventory(self.slot, self.game_root, self.styles, self.vehicles)
        tk, ttk, tr = owner._tk, owner._ttk, owner._t
        self.window = tk.Toplevel(owner.save_dialog)
        self.window.title(tr('Coatings'))
        self.window.transient(owner.save_dialog)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        frame = tk.Frame(self.window, padx=12, pady=12)
        frame.pack(fill='both', expand=True)
        self.vehicle = tk.StringVar(value=tr('All compatible vehicles'))
        self.vehicle_by_label = {tr('All compatible vehicles'): None}
        self.vehicle_by_label.update((v['label'] + ' (' + v['name'] + ')', v) for v in self.vehicles)
        tk.Label(frame, text=tr('Vehicle')).grid(row=0, column=0, sticky='w')
        self.vehicle_box = ttk.Combobox(frame, textvariable=self.vehicle,
            values=tuple(self.vehicle_by_label), state='readonly', width=62)
        self.vehicle_box.grid(row=0, column=1, sticky='we', pady=4)
        self.vehicle_box.bind('<<ComboboxSelected>>', self.refresh)
        self.table = ttk.Treeview(frame, columns=('style', 'availability', 'stock', 'vehicles'),
                                  show='headings', height=13, selectmode='extended')
        for name, label, width in (('style', 'Preset style', 200),
                ('availability', 'Style type', 100), ('stock', 'Inventory', 90),
                ('vehicles', 'Compatible vehicles', 130)):
            self.table.heading(name, text=tr(label))
            self.table.column(name, width=width, anchor='w')
        self.table.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=8)
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.table.yview)
        scrollbar.grid(row=1, column=2, sticky='ns')
        self.table.configure(yscrollcommand=scrollbar.set)
        controls = tk.Frame(frame)
        controls.grid(row=2, column=0, columnspan=2, sticky='we')
        tk.Label(controls, text=tr('Copies per compatible vehicle')).pack(side='left')
        self.quantity = tk.StringVar(value='1')
        ttk.Spinbox(controls, from_=1, to=100000, textvariable=self.quantity, width=8).pack(side='left', padx=8)
        tk.Button(controls, text=tr('Add selected styles'), command=self.add).pack(side='left', padx=4)
        tk.Button(controls, text=tr('Fill all styles'), command=self.fill).pack(side='left', padx=4)
        tk.Label(frame, text=tr('Includes hidden preset styles. Only compatible vehicles receive stock. '
            'Each rental copy grants its original battle count. Save with the game closed; changes apply on next launch.'),
            wraplength=610, justify='left').grid(row=3, column=0, columnspan=2, sticky='we', pady=8)
        self.feedback = tk.Label(frame, text='', wraplength=610, justify='left')
        self.feedback.grid(row=4, column=0, columnspan=2, sticky='we')
        actions = tk.Frame(frame)
        actions.grid(row=5, column=0, columnspan=2, sticky='we', pady=(8, 0))
        tk.Button(actions, text=tr('Save'), command=self.save).pack(side='left', expand=True, fill='x')
        tk.Button(actions, text=tr('Close'), command=self.close).pack(side='left', expand=True, fill='x')
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)
        self.refresh()
        self.window.grab_set()

    def targets(self):
        vehicle = self.vehicle_by_label.get(self.vehicle.get())
        return [vehicle] if vehicle is not None else self.vehicles

    def refresh(self, unused=None):
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        tr = self.owner._t
        for style in self.styles:
            applicable = [v for v in self.targets() if store.compatible(style, v)]
            if not applicable: continue
            bindings = self.inventory.get(str(store.STYLE_TYPE), {}).get(str(style['id']), {})
            count = bindings.get('0', 0) + sum(bindings.get(str(v['compact_descr']), 0) for v in applicable)
            category = 'Hidden' if style['hidden'] else 'Rental' if style['rent_count'] else 'Permanent'
            unit = tr('battles') if style['rent_count'] else tr('copies')
            self.table.insert('', 'end', iid=str(style['id']), values=(
                style['label'], tr(category), '%d %s' % (count, unit), len(applicable)))
        self.table.selection_set(*(key for key in selected if self.table.exists(key)))

    def add(self):
        try:
            copies = int(self.quantity.get())
            selected = set(self.table.selection())
            if not selected:
                self.feedback.config(text=self.owner._t('Select at least one preset style.'))
                return
            import copy
            staged = copy.deepcopy(self.inventory)
            for style in self.styles:
                if str(style['id']) in selected:
                    store.add_style(staged, style, self.targets(), copies)
            self.inventory = staged
            self.refresh()
            self.feedback.config(text=self.owner._t('Inventory changed. Click Save to apply.'))
        except (ValueError, store.save_ledger.SaveLedgerError) as error:
            self.feedback.config(text=self.owner._t(str(error)))

    def fill(self):
        for style in self.styles:
            bindings = self.inventory.setdefault(str(store.STYLE_TYPE), {}).setdefault(str(style['id']), {})
            for vehicle in self.targets():
                if store.compatible(style, vehicle):
                    cd = str(vehicle['compact_descr'])
                    bindings[cd] = max(bindings.get(cd, 0), style['rent_count'] or 1)
        self.refresh()
        self.feedback.config(text=self.owner._t('Inventory changed. Click Save to apply.'))

    def save(self):
        try:
            store.write_inventory(self.slot, self.game_root, self.inventory)
            self.feedback.config(text=self.owner._t('Style inventory saved.'))
        except store.save_ledger.SaveLedgerError as error:
            self.feedback.config(text=self.owner._t(str(error)))

    def close(self):
        self.window.grab_release()
        self.window.destroy()
        self.owner.save_dialog.grab_set()
