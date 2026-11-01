"""Save-local personal reserve stock editor; active reserves remain untouched."""
try:
    from . import save_services as store
except ImportError:
    import save_services as store


class ReservesPanel(object):
    def __init__(self, owner, frame):
        self.owner, self.frame = owner, frame
        tk, ttk = owner._tk, owner._ttk
        self.tree = ttk.Treeview(frame, columns=('name', 'effect', 'duration', 'stock'),
                                 show='headings', height=16, selectmode='extended')
        self.tree.grid(row=0, column=0, columnspan=3, sticky='nsew')
        for name, width in (('name', 200), ('effect', 80), ('duration', 80), ('stock', 80)):
            self.tree.column(name, width=width, anchor='w')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scroll.grid(row=0, column=3, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        controls = tk.Frame(frame)
        controls.grid(row=1, column=0, columnspan=4, sticky='ew', pady=6)
        for column in (0, 1):
            controls.grid_columnconfigure(column, weight=1, uniform='reserve_actions')
        quantity_row = tk.Frame(controls)
        quantity_row.grid(row=0, column=0, sticky='ew', padx=(0, 3))
        self.quantity_label = tk.Label(quantity_row)
        self.quantity_label.pack(side='left', padx=(0, 6))
        self.quantity = tk.StringVar(master=frame, value='0')
        self.quantity_box = ttk.Spinbox(quantity_row, from_=0,
            to=store.save_ledger.MAX_BALANCE, textvariable=self.quantity, width=12)
        self.quantity_box.pack(side='left', fill='x', expand=True)
        self.set_button = tk.Button(controls, command=self.set_quantity)
        self.set_button.grid(row=0, column=1, sticky='ew', padx=(3, 0))
        self.save_button = tk.Button(frame, command=self.save)
        self.save_button.grid(row=2, column=0, columnspan=4, sticky='ew')
        self.feedback = tk.Label(frame, justify='left', anchor='w', wraplength=620)
        self.feedback.grid(row=3, column=0, columnspan=4, sticky='ew', pady=8)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.counts, self.loaded_slot = {}, None
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.translate()

    def translate(self):
        tr = self.owner._t
        for name, text in (('name', 'Personal reserves'), ('effect', 'Bonus'),
                           ('duration', 'Duration (hours)'), ('stock', 'Inventory')):
            self.tree.heading(name, text=tr(text))
        self.quantity_label.config(text=tr('Quantity'))
        self.set_button.config(text=tr('Set selected quantities'))
        self.save_button.config(text=tr('Save changes'))
        self.render()

    def refresh(self):
        try:
            self.counts = store.read_reserves(self.owner._save_slot_id,
                                             self.owner.game_root.get().strip() or None)
            self.loaded_slot = self.owner._save_slot_id
            self.feedback.config(text='')
            self.render()
        except (ValueError, OSError, store.save_ledger.SaveLedgerError) as error:
            self.loaded_slot = None
            self.feedback.config(text=self.owner._t(str(error)))

    def render(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in store.policy.RESERVES:
            self.tree.insert('', 'end', iid=row.key, values=(self.owner._t(row.label),
                '+%d%%' % row.percent, row.duration // 3600, self.counts.get(row.key, 0)))
        self.tree.selection_set(*(key for key in selected if self.tree.exists(key)))

    def select(self, unused=None):
        selected = self.tree.selection()
        if selected:
            self.quantity.set(str(self.counts.get(selected[0], 0)))

    def set_quantity(self):
        try:
            value = store._count(int(self.quantity.get()))
            selected = self.tree.selection()
            if not selected:
                raise ValueError('Select a personal reserve.')
            for key in selected:
                self.counts[key] = value
            self.render()
        except (ValueError, store.save_ledger.SaveLedgerError) as error:
            self.feedback.config(text=self.owner._t(str(error)))

    def save(self):
        try:
            if self.loaded_slot != self.owner._save_slot_id:
                raise ValueError('Select the save again before editing.')
            self.counts = store.write_reserves(self.loaded_slot, self.counts,
                                              self.owner.game_root.get().strip() or None)
            self.feedback.config(text=self.owner._t('Personal reserves saved.'))
        except (ValueError, OSError, store.save_ledger.SaveLedgerError,
                store.save_slots.SaveSlotError) as error:
            self.feedback.config(text=self.owner._t(str(error)))
