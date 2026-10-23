"""Exact-seat recruit controls embedded in the selected save's Members tab."""
try:
    from . import crew_store as store
except ImportError:
    import crew_store as store

ROLE_NAMES=dict(commander='Commander',gunner='Gunner',driver='Driver',loader='Loader',radioman='Radio operator')
NATION_NAMES=dict(zip(store.contract.NATIONS,('USSR','Germany','USA','China','France','UK','Japan','Czech','Sweden','Poland')))
CLASS_NAMES={'all':'All','lightTank':'Light tank','mediumTank':'Medium tank','heavyTank':'Heavy tank','AT-SPG':'Tank destroyer','SPG':'Self-propelled gun'}
HELP='Choose a vehicle and its actual crew seat. The skill limit includes its combined roles, with shared skills counted once. Below 100% training, ordinary skills are unavailable. Female crew always have zero-skill Brothers in Arms; it counts as one selected skill. At 100%, choose the other skills in the client. Grants belong to the member and are not renewed by moving seats. Close the game before adding; delivery and a system message occur next startup. Insufficient barracks space leaves the request pending.'


class CrewPanel(object):
    def __init__(self,owner,frame):
        self.owner,self.frame=owner,frame
        self.cached_root,self.vehicles=None,[]
        self.variables,self.labels,self.boxes={},{},{}
        tk,ttk=owner._tk,owner._ttk
        for index,key in enumerate(('nation','class','vehicle','seat','female','training','skills')):
            label=tk.Label(frame,anchor='w');label.grid(row=index,column=0,sticky='w',pady=3)
            var=tk.StringVar(master=frame)
            box=ttk.Combobox(frame,textvariable=var,state='readonly',width=65)
            box.grid(row=index,column=1,sticky='ew',pady=3)
            self.variables[key],self.labels[key],self.boxes[key]=var,label,box
            if key in ('nation','class'):box.bind('<<ComboboxSelected>>',self.filter)
            elif key=='vehicle':box.bind('<<ComboboxSelected>>',self.select_vehicle)
            elif key in ('seat','female','training'):box.bind('<<ComboboxSelected>>',self.update_skills)
        self.button=tk.Button(frame,command=self.add);self.button.grid(row=7,column=0,columnspan=2,sticky='ew',pady=6)
        self.help=tk.Label(frame,justify='left',wraplength=620);self.help.grid(row=8,column=0,columnspan=2,sticky='ew',pady=6)
        self.feedback=tk.Label(frame,justify='left',wraplength=620);self.feedback.grid(row=9,column=0,columnspan=2,sticky='ew')
        frame.grid_columnconfigure(1,weight=1)
        self.maps={};self.translate()

    def _choices(self,key,choices,selected=None):
        if selected is None:selected=self.maps.get(key,{}).get(self.variables[key].get())
        self.maps[key]=choices;self.boxes[key].config(values=tuple(choices))
        self.variables[key].set(next((k for k,v in choices.items() if v==selected),next(iter(choices),'')))

    def translate(self):
        tr=self.owner._t
        old={k:self.maps.get(k,{}).get(v.get()) for k,v in self.variables.items()}
        names=dict(nation='Nation',**{'class':'Tank type'},vehicle='Vehicle',seat='Profession',female='Gender',training='Training level',skills='Skills and perks')
        for k,name in names.items():self.labels[k].config(text=tr(name))
        self._choices('nation',{tr(NATION_NAMES[k]):k for k in store.contract.NATIONS},old.get('nation'))
        self._choices('class',{tr(v):k for k,v in CLASS_NAMES.items()},old.get('class'))
        self._choices('female',{tr('Male'):False,tr('Female'):True},old.get('female'))
        self._choices('training',{str(k)+'%':k for k in (50,75,100)},old.get('training') or 100)
        self.button.config(text=tr('Add to barracks'));self.help.config(text=tr(HELP))
        self.filter(vehicle=old.get('vehicle'),seat=old.get('seat'),skills=old.get('skills'))

    def refresh(self,unused=None):
        root=self.owner.game_root.get().strip();slot=self.owner._save_slot_id
        if getattr(self,'selected_slot',None)!=slot:self.feedback.config(text='');self.selected_slot=slot
        try:
            if root!=self.cached_root:self.vehicles=store.catalogue(root);self.cached_root=root
            self.filter()
        except (OSError,ValueError,store.vehicle_overlays.VehicleOverlayError) as error:
            self.vehicles=[];self.filter();self.feedback.config(text=self.owner._t(str(error)))

    def filter(self,unused=None,vehicle=None,seat=None,skills=None):
        nation=self.maps['nation'].get(self.variables['nation'].get())
        tag=self.maps['class'].get(self.variables['class'].get())
        choices={r['label']+' ('+r['name']+')':r['name'] for r in self.vehicles
                 if r['nation']==nation and (tag=='all' or r['vehicleClass']==tag)}
        self._choices('vehicle',choices,vehicle);self.by_label=choices
        self.select_vehicle(seat=seat,skills=skills)

    def select_vehicle(self,unused=None,seat=None,skills=None):
        name=self.maps['vehicle'].get(self.variables['vehicle'].get())
        rows=store.crew_skills.seats(name)
        if getattr(self,'_seat_vehicle',None)!=name and seat is None:seat=0
        self._seat_vehicle=name
        tr=self.owner._t;choices={};counts={r[0]:sum(x[0]==r[0] for x in rows) for r in rows};seen={}
        for index,roles in enumerate(rows):
            role=roles[0];seen[role]=seen.get(role,0)+1
            caption=tr(ROLE_NAMES[role])+(str(seen[role]) if counts[role]>1 else '')
            if len(roles)>1:caption+=' ('+tr('Also')+' '+', '.join(tr(ROLE_NAMES[r]) for r in roles[1:])+')'
            choices[caption]=index
        self._choices('seat',choices,seat)
        self.button.config(state='normal' if choices else 'disabled')
        self.boxes['vehicle'].config(state='readonly' if self.by_label else 'disabled')
        self.boxes['seat'].config(state='readonly' if choices else 'disabled')
        self.update_skills(selected=skills)

    def update_skills(self,unused=None,selected=None):
        vehicle=self.maps['vehicle'].get(self.variables['vehicle'].get());seat=self.maps['seat'].get(self.variables['seat'].get())
        female=self.maps['female'][self.variables['female'].get()];training=self.maps['training'][self.variables['training'].get()]
        if selected is None:selected=self.maps.get('skills',{}).get(self.variables['skills'].get(),int(female))
        if vehicle is None or seat is None:low=high=int(female)
        else:low,high=store.crew_skills.bounds(vehicle,seat,female,training)
        actual=max(low,min(high,selected if selected is not None else low))
        self._choices('skills',{str(k):k for k in range(low,high+1)},actual)
        self.boxes['skills'].config(state='readonly' if training==100 and vehicle is not None else 'disabled')
        if selected is not None and selected>high:
            self.feedback.config(text=self.owner._t('Skill count reduced to the current seat limit: ')+str(high))

    def add(self):
        owner=self.owner
        if owner._busy or owner._maintenance_busy:return False
        try:
            store.add(owner._save_slot_id,owner.game_root.get().strip(),
                self.maps['vehicle'][self.variables['vehicle'].get()],self.maps['seat'][self.variables['seat'].get()],
                self.maps['female'][self.variables['female'].get()],self.maps['skills'][self.variables['skills'].get()],
                training=self.maps['training'][self.variables['training'].get()])
        except (OSError,ValueError,KeyError,store.save_ledger.SaveLedgerError,store.save_slots.SaveSlotError,store.vehicle_overlays.VehicleOverlayError) as error:
            self.feedback.config(text=owner._t(str(error)));return False
        self.feedback.config(text=owner._t('Crew member queued for this save. It arrives in the barracks on the next game startup.'))
        return True
