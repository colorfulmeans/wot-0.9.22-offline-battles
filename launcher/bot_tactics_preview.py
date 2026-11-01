"""Read-only, scope-complete preview of committed draft behavior rules."""
import copy
import json
import ui_layout
import tkinter as tk
from tkinter import ttk
import bot_tactics_labels as labels
import bot_tactics_store as storage
from gui.mods.offline_lan_0922 import bot_gunnery

FIELDS = ('skill','development','equipment','ammo_ratios','ammo_limit','consumables','outfit',
          'crew_preset','reaction_seconds','patience_seconds','converged_factor',
          'aim_bias_factor','lead_error')
DEFAULTS = {
    'development': ('stock','intermediate','full','full'),
    'equipment': ('none','single','standard','improved'),
    'consumables': ('none','once','repeat','large'),
    'outfit': ('off','off','off','on'),
    'crew_preset': ('50','75','repair','all'),
}


EN_PRESETS={
 'development':dict(stock='Stock',intermediate='Intermediate',full='Fully researched'),
 'equipment':dict(none='No equipment',single='One equipment item',standard='Three standard equipment items',improved='Three improved equipment items + matching directive'),
 'consumables':dict(none='No consumables',once='Small first aid + small repair + manual extinguisher; once',repeat='Small first aid + small repair + manual extinguisher; reusable',large='Large first aid + large repair + automatic extinguisher; reusable'),
 'crew_preset':{'50':'50%','75':'75%','repair':'100% + full Repair and Concealment','all':'100% + all skills fully trained'},
}


def grouped(document, team=0, tag='all', slots='', lineup=()):
    """Use precisely effective()'s ordered matching; retain each winning source."""
    from gui.mods.offline_lan_0922 import lineup_slots
    from gui.mods.offline_lan_0922.bot_fitting_data import CLASSES
    indexed = {(r['team'], r['slot']): r for r in lineup}
    explicit = lineup_slots.explicit(lineup)
    result = {}
    teams = (int(team),) if int(team) else (1,2)
    tags = (tag,) if tag!='all' else storage.contract.CLASSES
    selected = tuple(int(s)-1 for s in str(slots).split(',') if s) if slots else range(15)
    for t in teams:
        for c in tags:
            for slot in selected:
                pin = indexed.get((t, slot), {})
                if explicit and not pin.get('enabled'):
                    continue
                fixed_class = CLASSES.get(pin.get('vehicle')) or pin.get('vehicle_class')
                if explicit and fixed_class and fixed_class != c:
                    continue
                values,sources = {},{}
                if pin.get('skill'):
                    values['skill'] = pin['skill']
                    sources['skill'] = ('lineup', t, slot)
                for rule in document.get('behavior',()):
                    if rule['team'] in (0,t) and rule['class_tag'] in ('all',c) and rule['slot'] in (-1,slot):
                        values.update(rule['values'])
                        sources.update({key:(rule['team'],rule['class_tag'],rule['slot']) for key in rule['values']})
                identity=json.dumps([values,sources],sort_keys=True)
                group=result.setdefault(identity,dict(values=values,sources=sources,scopes=[]))
                group['scopes'].append((t,c,slot))
    return list(result.values())


def rows(group, language):
    zh=language=='zh'
    tr=lambda a,b:a if zh else b
    values,sources=group['values'],group['sources']
    tier=values.get('skill')
    params=bot_gunnery.skill_parameters(tier) if tier else {}
    def source(key):
        t,c,s=sources[key]
        if t == 'lineup':
            return tr('阵容：队伍 %d／槽位 %d', 'Lineup: team %d / slot %d') % (c,s+1)
        return ' / '.join((labels.enum_label('team',t,language),labels.enum_label('class_tag',c,language),
            tr('槽位 %d','Slot %d')%(s+1) if s>=0 else tr('全部槽位','All slots')))
    result=[]
    for key in FIELDS:
        origin=source(key) if key in sources else tr('难度默认','Difficulty default')
        if key in values:
            value=values[key]
        elif key=='skill':
            value=tr('继承房间难度；按每辆 BOT 评分确定','Room difficulty; sampled separately for each Bot')
            origin=tr('客户端房间设置','Client room settings')
        elif key=='crew_preset' and 'crew_level' in values:
            value=tr('%s%%（旧方案等级；技能跟随难度）','%s%% (legacy level; skills follow difficulty)')%values['crew_level']
            origin=source('crew_level')
        elif key=='ammo_limit':
            value=tr('继承车辆原携弹容量','Inherit vehicle ammunition capacity')
            origin=tr('现有装弹规则','Current ammunition rules')
        elif key=='ammo_ratios':
            value=tr('按实际主炮及弹种白名单自动配比','Automatic ratios for the actual gun and shell whitelist')
            origin=tr('现有装弹规则','Current ammunition rules')
        elif not tier:
            value=tr('随每辆 BOT 的评分／档位确定','Depends on each Bot rating / tier')
        elif key in DEFAULTS:
            value=DEFAULTS[key][bot_gunnery.SKILL_TIERS.index(tier)]
            origin=tr('难度默认：','Difficulty default: ')+labels.enum_label('skill',tier,language)
        else:
            value=params[key]
            origin=tr('难度默认：','Difficulty default: ')+labels.enum_label('skill',tier,language)
        if key=='ammo_ratios' and isinstance(value,(tuple,list)):
            display=' : '.join(str(v) for v in value)
            if not any(value):display+=tr('（不携带炮弹）',' (no ammunition)')
        elif key in labels.ENUM_NAMES and str(value) in labels.ENUM_NAMES[key]:
            display=EN_PRESETS.get(key,{}).get(str(value),labels.enum_label(key,value,language)) if not zh else labels.enum_label(key,value,language)
        elif isinstance(value,(int,float)):
            display='%g'%value
        else:display=str(value)
        result.append((labels.parameter_label(key,language),display,origin))
    return result


class PreviewWindow:
    def __init__(self, parent, document, team, tag, slots, language, lineup=(), game_root=''):
        self.groups=grouped(copy.deepcopy(document),team,tag,slots,lineup)
        if not self.groups:
            self.groups = [dict(values={},sources={},scopes=[])]
        self.language=language
        self.lineup=copy.deepcopy(list(lineup));self.game_root=game_root
        self.root=tk.Toplevel(parent)
        self.root.geometry('1040x570');self.root.minsize(850,470)
        self.note=ttk.Label(self.root,wraplength=990,justify='left',padding=10)
        self.note.pack(fill='x')
        self.choice=ttk.Combobox(self.root,state='readonly')
        self.choice.pack(fill='x',padx=10,pady=4)
        self.choice.bind('<<ComboboxSelected>>',lambda event:self.refresh_rows())
        self.scope_note=ttk.Label(self.root,wraplength=990,justify='left',padding=(10,0))
        self.scope_note.pack(fill='x')
        frame=ttk.Frame(self.root,padding=10);frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(frame,columns=('field','value','source'),show='headings',height=13)
        for key,width in (('field',220),('value',430),('source',330)):
            self.table.column(key,width=width,minwidth=100)
        scrollbar=ttk.Scrollbar(frame,orient='horizontal',command=self.table.xview)
        self.table.configure(xscrollcommand=scrollbar.set)
        vertical=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview)
        self.table.configure(yscrollcommand=vertical.set)
        self.table.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns')
        scrollbar.grid(row=1,column=0,sticky='ew')
        frame.grid_rowconfigure(0,weight=1);frame.grid_columnconfigure(0,weight=1)
        notes_frame=ttk.Frame(self.root,padding=(10,0));notes_frame.pack(fill='x')
        self.ammo_note=tk.Text(notes_frame,height=3,wrap='word',state='disabled',font='TkDefaultFont')
        notes_scroll=ttk.Scrollbar(notes_frame,orient='vertical',command=self.ammo_note.yview)
        self.ammo_note.configure(yscrollcommand=notes_scroll.set)
        notes_scroll.pack(side='right',fill='y');self.ammo_note.pack(fill='x',expand=True)
        self.close_button=tk.Button(self.root,command=self.root.destroy)
        self.close_button.pack(fill='x',padx=10,pady=8)
        self.set_language(language)
        ui_layout.polish(self.root)

    def set_language(self,language):
        self.language=language;zh=language=='zh'
        tr=lambda a,b:a if zh else b
        self.root.title(tr('生效值预览','Effective settings preview'))
        self.note.configure(text=tr('预览当前方案草稿中已新增／更新的规则；不包含右侧尚未提交的表单，不会保存或应用。相同生效设置及来源合并显示。未固定难度时保留房间评分分布，具体车辆与主炮会影响最终配置和装弹。','Previews rules already added/updated in this draft. Unsubmitted form fields are excluded. Nothing is saved or applied. Identical settings and sources are grouped. Inherited room difficulty retains its rating distribution; the actual vehicle and gun affect final fittings and ammunition.'))
        index=max(0,self.choice.current())
        captions=[]
        for i,group in enumerate(self.groups):
            parts=[]
            for team,tag in dict.fromkeys((t,c) for t,c,s in group['scopes']):
                slots=[str(s+1) for t,c,s in group['scopes'] if t==team and c==tag]
                parts.append('%s / %s / %s'%(labels.enum_label('team',team,language),labels.enum_label('class_tag',tag,language),tr('全部槽位','All slots') if len(slots)==15 else tr('槽位 ','Slots ')+','.join(slots)))
            captions.append('%d. %s'%(i+1,'; '.join(parts)))
        self.scope_captions=captions
        self.choice.configure(values=[c if len(c)<120 else c[:117]+'...' for c in captions]);self.choice.current(min(index,len(captions)-1))
        for key,text in zip(('field','value','source'),(tr('项目','Setting'),tr('生效设置','Effective value'),tr('设置来源','Source'))):
            self.table.heading(key,text=text)
        self.close_button.configure(text=tr('关闭','Close'))
        self.refresh_rows()

    def refresh_rows(self):
        self.table.delete(*self.table.get_children())
        group=self.groups[self.choice.current()]
        self.scope_note.configure(text=self.scope_captions[self.choice.current()])
        for row in rows(group,self.language):
            self.table.insert('', 'end',values=row)
        zh=self.language=='zh'
        notes=[]
        for member in self.lineup:
            scopes=group['scopes']
            vehicle=member.get('vehicle')
            from gui.mods.offline_lan_0922.bot_fitting_data import CLASSES
            if not vehicle or (member.get('team'),CLASSES.get(vehicle),member.get('slot')) not in scopes:continue
            values=group['values']
            if 'skill' not in values and 'development' not in values:
                notes.append(('%s：主炮随实际 BOT 档位确定' if zh else '%s: gun depends on the actual Bot tier')%vehicle)
                continue
            try:
                ammo=storage.ammunition_preview(self.game_root,vehicle,values,values.get('ammo_ratios'))
                text='; '.join('%s × %s'%(shell['label'],ammo['counts'][shell['index']]) for shell in ammo['shells'])
                notes.append('%s / %s: %s'%(vehicle,ammo['gun'],text))
            except (OSError,ValueError,KeyError):
                notes.append(('%s：无法读取主炮数据，未推测弹种／数量' if zh else '%s: gun data unavailable; shell types/counts are not estimated')%vehicle)
        self.ammo_note.configure(state='normal');self.ammo_note.delete('1.0','end')
        self.ammo_note.insert('1.0','\n'.join(dict.fromkeys(notes)) or ('未指定固定车辆；弹种和数量在分配车辆及主炮后确定。' if zh else 'No fixed vehicle specified; shell types and counts depend on the allocated vehicle and gun.'))
        self.ammo_note.configure(state='disabled')
