"""Readonly recruit controls embedded in the selected save's Members tab."""
try:
    from . import crew_store as store
except ImportError:
    import crew_store as store

ROLE_NAMES = dict(commander='Commander', gunner='Gunner', driver='Driver', loader='Loader', radioman='Radio operator')
NATION_NAMES = dict(zip(store.contract.NATIONS, ('USSR','Germany','USA','China','France','UK','Japan','Czech','Sweden','Poland')))


class CrewPanel(object):
    def __init__(self, owner, frame):
        self.owner, self.frame = owner, frame
        self.cached_root, self.vehicles = None, []
        tk, ttk = owner._tk, owner._ttk
        self.variables, self.labels, self.boxes = {}, {}, {}
        for index, key in enumerate(('nation', 'role', 'female', 'skills', 'vehicle')):
            self.labels[key] = tk.Label(frame, anchor='w')
            self.labels[key].grid(row=index, column=0, sticky='w', pady=3)
            var = tk.StringVar(master=frame)
            box = ttk.Combobox(frame, textvariable=var, state='readonly', width=65)
            box.grid(row=index, column=1, sticky='ew', pady=3)
            self.variables[key], self.boxes[key] = var, box
            if key in ('nation', 'role'):
                box.bind('<<ComboboxSelected>>', self.filter)
        self.button = tk.Button(frame, command=self.add)
        self.button.grid(row=5, column=0, columnspan=2, sticky='ew', pady=6)
        self.help = tk.Label(frame, justify='left', wraplength=620)
        self.help.grid(row=6, column=0, columnspan=2, sticky='ew', pady=6)
        self.feedback = tk.Label(frame, justify='left', wraplength=620)
        self.feedback.grid(row=7, column=0, columnspan=2, sticky='ew')
        frame.grid_columnconfigure(1, weight=1)
        self.translate()

    def translate(self):
        tr = self.owner._t
        names = dict(nation='Nation', role='Crew role', female='Gender', skills='Complete skills', vehicle='Trained vehicle')
        maps = dict(nation={tr(NATION_NAMES[k]): k for k in store.contract.NATIONS},
                    role={tr(ROLE_NAMES[k]): k for k in store.contract.ROLES},
                    female={tr('Male'): False, tr('Female'): True},
                    skills={str(k): k for k in range(store.contract.MAX_SKILLS + 1)})
        old = {key: getattr(self, 'maps', {}).get(key, {}).get(var.get()) for key, var in self.variables.items()}
        self.maps = maps
        for key, label in names.items():
            self.labels[key].config(text=tr(label))
            if key == 'vehicle':
                continue
            choices = maps[key]
            self.boxes[key].config(values=tuple(choices))
            self.variables[key].set(next((label for label, value in choices.items() if value == old.get(key)), next(iter(choices))))
        self.button.config(text=tr('Add to barracks'))
        self.help.config(text=tr('Adds one 100% crew member, with experience for the selected number of complete skills. Choose the skills in the client. No zero-skill perk is added. Close the game before adding; the next startup delivers the recruit and a system message. Insufficient barracks space leaves the request pending.'))
        self.filter()

    def refresh(self, unused=None):
        root = self.owner.game_root.get().strip()
        slot = self.owner._save_slot_id
        if getattr(self, 'selected_slot', None) != slot:
            self.feedback.config(text='')
            self.selected_slot = slot
        try:
            if root != self.cached_root:
                self.vehicles = store.catalogue(root)
                self.cached_root = root
            self.filter()
        except (OSError, ValueError, store.vehicle_overlays.VehicleOverlayError) as error:
            self.vehicles = []
            self.filter()
            self.feedback.config(text=self.owner._t(str(error)))

    def filter(self, unused=None):
        nation = self.maps['nation'].get(self.variables['nation'].get())
        role = self.maps['role'].get(self.variables['role'].get())
        self.by_label = {row['label'] + ' (' + row['name'] + ')': row['name'] for row in self.vehicles
                         if row['nation'] == nation and role in row['roles']}
        self.boxes['vehicle'].config(values=tuple(self.by_label))
        if self.variables['vehicle'].get() not in self.by_label:
            self.variables['vehicle'].set(next(iter(self.by_label), ''))
        self.button.config(state='normal' if self.by_label else 'disabled')

    def add(self):
        owner = self.owner
        if owner._busy or owner._maintenance_busy:
            return False
        try:
            store.add(owner._save_slot_id, owner.game_root.get().strip(),
                      self.by_label[self.variables['vehicle'].get()],
                      self.maps['role'][self.variables['role'].get()],
                      self.maps['female'][self.variables['female'].get()],
                      self.maps['skills'][self.variables['skills'].get()])
        except (OSError, ValueError, KeyError, store.save_ledger.SaveLedgerError,
                store.save_slots.SaveSlotError, store.vehicle_overlays.VehicleOverlayError) as error:
            self.feedback.config(text=owner._t(str(error)))
            return False
        self.feedback.config(text=owner._t('Crew member queued for this save. It arrives in the barracks on the next game startup.'))
        return True
