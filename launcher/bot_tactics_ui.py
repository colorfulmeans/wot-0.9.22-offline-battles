# -*- coding: utf-8 -*-
"""Tk Bot behavior / route / artillery editor, backed by the runtime contract."""
from __future__ import annotations
import copy
import math
from pathlib import Path
import uuid
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

try:
    from . import bot_tactics_store as storage
    from . import bot_tactics_labels as labels, i18n
    from . import bot_tactics_navigation as navigation_view
    from . import bot_tactics_geometry as route_geometry
    from .bot_tactics_connections import ConnectionEditorMixin
except ImportError:
    import bot_tactics_store as storage
    import bot_tactics_labels as labels
    import i18n
    import bot_tactics_navigation as navigation_view
    import bot_tactics_geometry as route_geometry
    from bot_tactics_connections import ConnectionEditorMixin

from gui.mods.offline_lan_0922 import route_network
contract = storage.contract
PARAM_LABELS = labels.PARAM_NAMES


class LocalizedCombobox(ttk.Combobox):
    """Translated captions with a separate canonical model variable.

    Changing the UI language never rewrites a profile, enum or selection. The
    existing form variables remain the API used by validation and runtime code.
    """
    def __init__(self, parent, *, variable, kind, values, language, **options):
        self.canonical = variable
        self.kind = kind
        self.keys = tuple(str(value) for value in values)
        self.language = language
        self.display = tk.StringVar(master=parent)
        super().__init__(parent, textvariable=self.display, state='readonly', **options)
        self._trace = variable.trace_add('write', self._from_model)
        self.bind('<<ComboboxSelected>>', self._from_view)
        self.set_language(language)

    def _from_model(self, *unused):
        self.display.set(labels.enum_label(self.kind, self.canonical.get(), self.language))

    def _from_view(self, unused=None):
        index = self.current()
        if 0 <= index < len(self.keys):
            self.canonical.set(self.keys[index])

    def set_language(self, language):
        self.language = language
        self.configure(values=tuple(labels.enum_label(self.kind, key, language) for key in self.keys))
        self._from_model()

    def destroy(self):
        if self._trace is not None:
            self.canonical.trace_remove('write', self._trace)
            self._trace = None
        super().destroy()



class SlotsDropdown(ttk.Menubutton):
    """Native dropdown checklist; no free-form comma-separated numeric input."""
    def __init__(self,parent,variable,language,**options):
        self.canonical=variable;self.display=tk.StringVar(master=parent)
        super().__init__(parent,textvariable=self.display,**options)
        self.menu=tk.Menu(self,tearoff=False);self.configure(menu=self.menu)
        self.choices=[tk.BooleanVar(master=parent) for unused in range(15)]
        self.language=language;self.set_language(language)
        self._trace=variable.trace_add('write',self._sync);self._sync()
    def set_language(self,language):
        self.language=language;self.menu.delete(0,'end')
        self.menu.add_command(label='全部槽位' if language=='zh' else 'All slots',command=lambda:self.canonical.set(''))
        for i,var in enumerate(self.choices):self.menu.add_checkbutton(label=str(i+1),variable=var,command=self._choose)
        self._sync()
    def _choose(self):
        self.canonical.set(','.join(str(i+1) for i,v in enumerate(self.choices) if v.get()))
    def _sync(self,*unused):
        chosen=set(self.canonical.get().split(','))
        for i,v in enumerate(self.choices):v.set(str(i+1) in chosen)
        self.display.set(self.canonical.get() or ('全部槽位' if self.language=='zh' else 'All slots'))
    def destroy(self):
        self.canonical.trace_remove('write',self._trace);super().destroy()


CLASS_COLORS = dict(zip(contract.CLASSES, ('#25a627', '#b1962d', '#a5a5a5', '#2c62aa', '#c83346')))
CLASS_COLORS['all'] = '#000000'


class BotTacticsEditor(ConnectionEditorMixin):
    def __init__(self, parent, game_root='', store=None, language='zh', log=None, lineup=None):
        self.lineup = lineup or (lambda:[])
        self._ammo_identity=();self._ammo_updating=False
        self.language = i18n.resolve_language(language)
        self.zh = self.language == 'zh'; self.game_root = game_root
        self._translations = {}
        self.store = store or storage.Store(); self.log = log or (lambda message: None)
        self.document = self.store.active()
        self.original = copy.deepcopy(self.document)
        self.histories = {key: ([], []) for key in ('behavior', 'maps')}
        self.saved_name = self.document['name']; self.unsaved_new = False
        self.builtin = self.document['name'] == 'Default'
        self.history_buttons = []
        self.selection = None; self.selected_point = None; self.drag = None; self._drag_started = False
        self.network_mode = '';self.network_link = '';self.connection_colors = CLASS_COLORS
        self.wait_edit = False; self.selected_wait = None
        self._wait_add_at_parent = False
        self._wait_parent_cleared = False
        self.graph_cache = {}; self.image_cache = {}; self.background = None; self.photo = None
        self.navigation_image_cache = {}; self.navigation_photo = None
        self.danger_image_cache = {}; self.danger_photo = None
        self.danger_graph_cache = {}
        self.root = tk.Toplevel(parent)
        self.root.title(self.tr('Bot 配置与地图战术', 'Bot configuration and map tactics'))
        self.root.geometry('1200x820'); self.root.minsize(1000, 700)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._build()
        self.map_name = '33_fjord'; self.team = 1
        self._load_map(); self._refresh_rules(); self._refresh_profiles(); self._refresh_lock()
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-y>', lambda e: self.redo())
        self.root.bind('<Control-s>', lambda e: self.save(False))

    def tr(self, zh, en):
        self._translations[zh] = self._translations[en] = (zh, en)
        return zh if self.zh else en

    def _translated_text(self, text):
        pair = self._translations.get(text)
        if pair:
            return pair[0 if self.zh else 1]
        # Numeric limits, coordinates and a profile hash may follow a caption.
        for old in sorted(self._translations, key=len, reverse=True):
            if old and text.startswith(old):
                pair = self._translations[old]
                return pair[0 if self.zh else 1] + text[len(old):]
        return text

    def set_language(self, language):
        """Refresh an open window without discarding pending edits or view state."""
        language = i18n.resolve_language(language)
        if language == self.language:
            return
        self.language = language; self.zh = language == 'zh'
        def refresh(widget):
            if isinstance(widget, (LocalizedCombobox,SlotsDropdown)):
                widget.set_language(language)
            if isinstance(widget, (ttk.Label, ttk.Button, ttk.Menubutton, ttk.Checkbutton, ttk.LabelFrame)):
                text = str(widget.cget('text'))
                widget.configure(text=self._translated_text(text))
            if isinstance(widget, ttk.Notebook):
                for tab in widget.tabs():
                    widget.tab(tab, text=self._translated_text(widget.tab(tab, 'text')))
            for child in widget.winfo_children():
                refresh(child)
        refresh(self.root)
        self.route_restore_menu.entryconfigure(0,label=self.tr('恢复本路线','Reset route'))
        self.route_restore_menu.entryconfigure(1,label=self.tr('恢复默认路线','Restore default routes'))
        self.root.title(self.tr('Bot 配置与地图战术', 'Bot configuration and map tactics'))
        for key in ('team', 'class', 'slot', 'values'):
            self.rules.heading(key, text=self._translated_text(self.rules.heading(key, 'text')))
        self.map_labels = {labels.map_label(name, language): name for name in sorted(contract.MAPS)}
        self.map_box.configure(values=sorted(self.map_labels))
        self.map_var.set(labels.map_label(self.map_name, language))
        self.status.set(self._translated_text(self.status.get()))
        self._refresh_rules()
        # Update tree captions in-place: no selection callbacks, draft rewrites
        # or changes to waypoint selection, zoom, pan or partially edited forms.
        for iid in self.items.get_children():
            kind, identity = iid.split(':', 1)
            if kind == 'builtin':
                text = self._builtin_caption(identity)
            elif kind == 'builtin_positions':
                text = self._parking_caption(identity)
            else:
                item = next(v for v in self.entry()[kind] if v['id'] == identity.partition('@')[0])
                text = self._custom_caption(kind,item,identity.partition('@')[2] or None)
            self.items.item(iid, text=text)
        for key,(selection,mode,link) in getattr(self,'tree_connections',{}).items():
            if self.items.exists(key):self.items.item(key,text=self._connection_caption(mode,link))
        self.redraw()
        for preview in getattr(self,'previews',[]):
            if preview.root.winfo_exists():preview.set_language(language)

    def _build(self):
        head = ttk.Frame(self.root, padding=10); head.pack(fill='x')
        ttk.Label(head, text=self.tr('方案名称', 'Profile')).pack(side='left')
        self.profile_name = tk.StringVar(value=self.document['name'])
        self.profile_box = ttk.Combobox(head, textvariable=self.profile_name, width=28, state='readonly')
        self.profile_box.pack(side='left', padx=6)
        self.profile_box.bind('<<ComboboxSelected>>', self.open_profile)
        for key, zh, en, command in (
            ('new', '新建', 'New', self.new_profile),
            ('rename', '重命名', 'Rename', self.rename_profile),
            ('delete', '删除', 'Delete', self.delete_profile),
            ('import', '导入', 'Import', self.import_profile),
            ('export', '导出', 'Export', self.export_profile)):
            button=ttk.Button(head, text=self.tr(zh,en), command=command)
            button.pack(side='left', padx=2)
            setattr(self, key+'_button', button)
        self.book = ttk.Notebook(self.root)
        self.book.bind('<<NotebookTabChanged>>', lambda event: self._refresh_history())
        behavior = ttk.Frame(self.book, padding=12); maps = ttk.Frame(self.book, padding=6)
        self.book.add(behavior, text=self.tr('行为参数', 'Behavior'))
        self.book.add(maps, text=self.tr('进攻路线 / 火炮炮位', 'Routes / SPG positions'))
        self._build_behavior(behavior); self._build_maps(maps)
        foot = ttk.Frame(self.root, padding=10); foot.pack(fill='x')
        self.status = tk.StringVar(value=self.tr('已载入当前配置。修改先作为草稿，不影响进行中的战斗。',
                                               'Loaded active profile. Editing does not change an ongoing battle.'))
        ttk.Label(foot, textvariable=self.status, wraplength=670).pack(side='left', fill='x', expand=True)
        self.save_button=ttk.Button(foot, text=self.tr('保存草稿', 'Save draft'), command=lambda:self.save(False));self.save_button.pack(side='left', padx=5)
        self.apply_button=ttk.Button(foot, text=self.tr('保存并应用（下一局）', 'Apply next battle'), command=lambda:self.save(True));self.apply_button.pack(side='left')
        ttk.Button(foot, text=self.tr('关闭', 'Close'), command=self.close).pack(side='left', padx=5)
        self.book.pack(fill='both', expand=True, padx=10)

    def _build_behavior(self, parent):
        ttk.Label(parent, text=self.tr(
            'Default 为只读。修改请新建方案。继承顺序：全局 → 队伍 → 车型 → 指定槽位；每项独立覆盖，下一局生效。',
            'Default is read only. Create a profile to edit. Global → team → class → slot; independent overrides apply next battle.'),
            wraplength=1080).pack(anchor='w', pady=(0,8))
        main = ttk.Frame(parent); main.pack(fill='both', expand=True)
        self.rules = ttk.Treeview(main, columns=('team','class','slot','values'), show='headings', height=14)
        for key,label,width in [('team',self.tr('队伍','Team'),60),('class',self.tr('车型','Class'),90),
                                ('slot',self.tr('槽位','Slot'),55),('values',self.tr('覆盖参数','Overrides'),310)]:
            self.rules.heading(key,text=label); self.rules.column(key,width=width)
        self.rules.pack(side='left',fill='both',expand=True)
        self.rules.bind('<<TreeviewSelect>>',self._select_rule)
        form=ttk.Frame(main,padding=(14,0));form.pack(side='left',fill='y')
        self.rule_vars={}; self.rule_boxes={}
        fields=[('team',self.tr('队伍','Team'),('0','1','2')),
                ('class_tag',self.tr('车型','Class'),('all',)+contract.CLASSES),
                ('slot',self.tr('槽位','Slot'),('',)+tuple(str(i) for i in range(1,16))),
                ('skill',self.tr('难度','Difficulty'),('',)+contract.SKILLS)]
        for name in ('development','equipment','consumables','outfit','crew_preset'):
            fields.append((name,labels.parameter_label(name,self.language),('',)+contract.PRESETS[name]))
        for row,(name,label,values) in enumerate(fields):
            actual=row+1 if name in ('consumables','outfit','crew_preset') else row
            ttk.Label(form,text=label).grid(row=actual,column=0,sticky='w',pady=3)
            var=tk.StringVar(value='0' if name=='team' else 'all' if name=='class_tag' else '')
            self.rule_vars[name]=var
            box=LocalizedCombobox(form,variable=var,kind=name,values=values,language=self.language,width=35)
            actual=row+1 if name in ('consumables','outfit','crew_preset') else row
            box.grid(row=actual,column=1,sticky='ew');self.rule_boxes[name]=box
            box.bind('<FocusIn>',lambda e,k=name:self._behavior_help(k),add='+')
            box.bind('<<ComboboxSelected>>',lambda e,k=name:(self._refresh_equipment_choices(),self._refresh_ammunition(),self._behavior_help(k)),add='+')
        row=6
        ttk.Label(form,text=self.tr('弹药比例','Ammunition ratios')).grid(row=row,column=0,sticky='w')
        ammo=ttk.Frame(form);ammo.grid(row=row,column=1,sticky='ew')
        self.ammo_vars=[tk.StringVar(value='') for unused in range(3)]
        self.ammo_boxes=[]
        for i,var in enumerate(self.ammo_vars):
            if i:ttk.Label(ammo,text=' : ').pack(side='left')
            box=LocalizedCombobox(ammo,variable=var,kind='ratio',values=('',)+tuple(str(i) for i in range(10)),language=self.language,width=14)
            box.pack(side='left');self.ammo_boxes.append(box)
            box.bind('<FocusIn>',lambda e:self._behavior_help('ammo_ratios'),add='+')
            box.bind('<<ComboboxSelected>>',lambda e:self._behavior_help('ammo_ratios'),add='+')
        for row,key in enumerate(contract.PARAMETERS,len(fields)+1):
            ttk.Label(form,text=labels.parameter_label(key,self.language)).grid(row=row,column=0,sticky='w',pady=3)
            lo,hi=contract.PARAMETERS[key];scale=100 if key=='lead_error' else 10
            values=('',)+tuple(format(i/scale,'.6g') for i in range(round(lo*scale),round(hi*scale)+1))
            var=tk.StringVar();self.rule_vars[key]=var
            box=LocalizedCombobox(form,variable=var,kind='number',values=values,language=self.language,width=35)
            box.grid(row=row,column=1,sticky='ew');self.rule_boxes[key]=box
            box.bind('<FocusIn>',lambda e,k=key:self._behavior_help(k),add='+')
        actions=ttk.Frame(form);actions.grid(row=row+1,column=0,columnspan=2,sticky='ew',pady=3)
        actions.columnconfigure((0,1),weight=1,uniform='actions')
        for index,(zh,en,command) in enumerate([
                ('新增／更新规则','Add / update rule',self.save_rule),
                ('删除选中规则','Delete selected rule',self.delete_rule),
                ('撤销','Undo',lambda:self.undo('behavior')),
                ('重做','Redo',lambda:self.redo('behavior')),
                ('显示所选范围生效参数','Effective values',self.preview_rule)]):
            button=ttk.Button(actions,text=self.tr(zh,en),command=command)
            button.grid(row=index//2,column=index%2,columnspan=2 if index==4 else 1,
                        sticky='ew',padx=2,pady=3)
            if index in (2,3):self.history_buttons.append(('behavior',index==3,button))
        self.behavior_help=tk.StringVar()
        help_frame=ttk.Frame(form);help_frame.grid(row=row+4,column=0,columnspan=2,sticky='sew',pady=8)
        self.help_text=tk.Text(help_frame,height=7,width=53,wrap='word',state='disabled',background=self.root.cget('background'),relief='flat')
        scroll=ttk.Scrollbar(help_frame,orient='vertical',command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.help_text.pack(side='left',fill='both',expand=True)
        def show_help(*unused):
            self.help_text.configure(state='normal');self.help_text.delete('1.0','end');self.help_text.insert('1.0',self.behavior_help.get());self.help_text.configure(state='disabled')
        self.behavior_help.trace_add('write',show_help)
        self._behavior_help('equipment')

    def _refresh_equipment_choices(self):
        stock=self.rule_vars['development'].get()=='stock' or (not self.rule_vars['development'].get() and self.rule_vars['skill'].get()=='rookie')
        box=self.rule_boxes['equipment']
        box.keys=('none',) if stock else ('',)+contract.PRESETS['equipment']
        if stock:self.rule_vars['equipment'].set('none')
        box.set_language(self.language)

    def _preview_values(self, vehicle):
        from gui.mods.offline_lan_0922.bot_fittings import CLASSES
        team=int(self.rule_vars['team'].get());slot=int(self.rule_vars['slot'].get())-1
        tag=self.rule_vars['class_tag'].get()
        document=copy.deepcopy(self.document)
        document['behavior']=[r for r in document['behavior'] if (r['team'],r['class_tag'],r['slot'])!=(team,tag,slot)]
        pending=dict((k,v.get()) for k,v in self.rule_vars.items() if k in ('skill','development') and v.get())
        document['behavior'].append(dict(team=team,class_tag=tag,slot=slot,values=pending))
        return contract.effective(document,team,CLASSES[vehicle],slot)

    def _refresh_ammunition(self):
        if self._ammo_updating:return None
        try:
            team=int(self.rule_vars['team'].get());slot=int(self.rule_vars['slot'].get())-1
            vehicle=next(row['vehicle'] for row in self.lineup() if row.get('team')==team and row.get('slot')==slot and row.get('vehicle'))
            values=self._preview_values(vehicle)
            preview=storage.ammunition_preview(self.game_root,vehicle,values)
        except (ValueError,KeyError,StopIteration,OSError,contract.TacticsError):
            self._ammo_preview=None;self._ammo_identity=()
            # A previous one/two-shell pinned gun must not leave generic
            # scopes with disabled ratio controls.
            state='disabled' if self.builtin else 'readonly'
            for box in self.ammo_boxes:box.configure(state=state)
            return None
        identities=tuple(s['name'] for s in preview['shells'])
        old=dict(zip(self._ammo_identity,(v.get() for v in self.ammo_vars)))
        if self._ammo_identity and self._ammo_identity!=identities:
            self._ammo_updating=True
            carry=any(old.get(name,'')!='' for name in identities)
            for i,var in enumerate(self.ammo_vars):var.set(old.get(identities[i],'0') if i<len(identities) and carry else '')
            self._ammo_updating=False
        self._ammo_identity=identities;self._ammo_preview=preview
        for i,box in enumerate(self.ammo_boxes):
            box.configure(state='readonly' if i<len(identities) and not self.builtin else 'disabled')
        return preview

    def _behavior_help(self, key):
        explanations={
            'equipment': '配件优先顺序：垂稳 → 输弹机 → 炮控 → 通风 → 高级观察镜 → 工具箱；3 紫色配件包含对应指令。选择白板研发时只允许无配件；切回中间／完全体才开放其他配件选项。导入与开战同样校验。',
            'development': '白板／中间／完全体沿用现有主炮白名单与炮塔兼容规则。白板仅允许无配件，避免超重；金币车为固定研发配置。',
            'crew_preset': '50%、75% 不附加技能；100% 满修理满隐蔽，或 100% 全部满技能。等级与技能是一套配置。',
            'outfit': '使用现有原生各季节租用风格（F 系／M 系等），不选择具体花色，不受原生 100 场租用期限限制。锁定涂装的车辆仍保持原外观。继承上级设置跟随上级／难度；不使用涂装和使用现有涂装分别独立覆盖，切换难度不会改写。',
            'consumables': '一次档每种仅用一次，不解除眩晕、不修履带；重复档遵循原生冷却，可解除眩晕、修复断履带。手动灭火比自动灭火延迟 5 秒。小修理箱顺序：红火炮 → 红发动机 → 红炮塔 → 黄弹药架 → 黄火炮 → 黄发动机 → 黄炮塔 → 红观察孔 → 黄观察孔 → 黄油箱 → 红电台 → 黄电台 → 红履带；红油箱和黄履带跳过。治疗：装填手 → 炮手 → 驾驶员 → 车长 → 通信兵 → 眩晕；同职成员按座位顺序。大给养沿用现有群体效果与过滤规则。',
            'ammo_ratios': '0—9 为相对比例，不是发数。全部继承采用默认配比；全 0 为不携弹。正比例按容量近似装满；弹夹车按弹夹数量分配，不改变每夹数量。正比例至少一发／一夹（容量许可），同等条件优先主弹。0 不补回。比例框按该炮的银币 AP／APCR／HEAT／HE、金币 AP／APCR／HEAT／HE 顺序对应；手动比例可以选择该炮的原生弹种，覆盖默认炮弹白名单。例如 7 夹的 6:3:1 近似为 4:2:1。',
        }
        fallback=labels.parameter_label(key,self.language)+'：'+self.tr('继承上级设置不覆盖上级；0 是有效值。','Inherit does not override; zero is a value.')
        text=explanations.get(key,fallback) if self.zh else fallback
        if key=='outfit' and not self.zh:
            text='Use the existing native seasonal rented styles (F/M series), without a 100-battle expiry or a style picker. Locked outfits remain unchanged. Inherit follows the parent/difficulty; off and on override it independently.'
        if key=='development':
            preview=self._refresh_ammunition()
            if preview and preview.get('fixed'):text+='\n'+self.tr('当前金币车：固定配置，各研发档位不改变模块。','Current premium vehicle: fixed module configuration at every development tier.')
        if key=='ammo_ratios':
            preview=self._refresh_ammunition()
            if preview:
                choices=[v.get() for v in self.ammo_vars[:len(preview['shells'])]]
                try:shown=storage.ammunition_preview(self.game_root,preview['vehicle'],self._preview_values(preview['vehicle']),[int(v) for v in choices])
                except (ValueError,OSError):shown=preview
                kinds={'ARMOR_PIERCING':'AP','ARMOR_PIERCING_CR':'APCR','HOLLOW_CHARGE':'HEAT','HIGH_EXPLOSIVE':'HE'}
                text=preview['vehicle']+' / '+preview['gun']+'\n'+' : '.join(s.get('label',s['name'])+' ('+kinds.get(s['kind'],s['kind'])+') = '+str(shown['counts'][int(s['index'])]) for s in shown['shells'])+'\n\n'+text
            else:text+='\n'+self.tr('全局／未固定车辆：按最终主炮的弹种顺序应用；指定队伍与固定槽位可预览弹种及近似数量。','Global or automatic slots use the final gun. Select a pinned team and slot for a preview.')
        self.behavior_help.set(text)

    def _build_maps(self,parent):
        bar=ttk.Frame(parent);bar.pack(fill='x',pady=4)
        names=sorted(contract.MAPS)
        self.map_labels={labels.map_label(n,self.language):n for n in names}
        self.map_var=tk.StringVar(value=labels.map_label('33_fjord',self.language))
        box=ttk.Combobox(bar,textvariable=self.map_var,values=sorted(self.map_labels),state='readonly',width=35)
        self.map_box=box
        box.pack(side='left');box.bind('<<ComboboxSelected>>',lambda e:self.change_map())
        self.team_var=tk.StringVar(value='1')
        t=LocalizedCombobox(bar,variable=self.team_var,kind='team',values=('1','2'),language=self.language,width=9)
        ttk.Label(bar,text=self.tr('出生队伍','Spawn team')).pack(side='left',padx=6);t.pack(side='left')
        self.team_box=t
        t.bind('<<ComboboxSelected>>',lambda e:self.change_map(),add='+')
        self.route_class_var = tk.StringVar(value='total')
        ttk.Label(bar,text=self.tr('显示内容','Show content')).pack(side='left',padx=6)
        scope = LocalizedCombobox(bar,variable=self.route_class_var,
            kind='route_view',values=('total','all')+contract.CLASSES+('spg_attack',),
            language=self.language,width=20)
        scope.pack(side='left');self.route_class_box=scope
        scope.bind('<<ComboboxSelected>>',lambda e:self.change_route_class(),add='+')
        base_bar=ttk.Frame(parent);base_bar.pack(fill='x',pady=3)
        self.base_label=ttk.Label(base_bar,text='');self.base_label.pack(side='left',padx=8)
        self.symmetry_var=tk.BooleanVar(value=True)
        self.symmetry_check=ttk.Checkbutton(base_bar,text=self.tr('路线对称','Route symmetry'),
                                           variable=self.symmetry_var,command=self.change_symmetry)
        self.symmetry_check.pack(side='left')
        self.navigation_grid_var=tk.BooleanVar(value=False)
        self.navigation_grid_check=ttk.Checkbutton(base_bar,
            text=self.tr('显示导航网格','Show navigation grid'),
            variable=self.navigation_grid_var,command=self.redraw)
        self.navigation_grid_check.pack(side='left',padx=(12,0))
        self.danger_grid_var=tk.BooleanVar(value=False)
        self.danger_grid_check=ttk.Checkbutton(base_bar,
            text=self.tr('显示危险区网格','Show danger grid'),
            variable=self.danger_grid_var,command=self.redraw)
        self.danger_grid_check.pack(side='left',padx=(12,0))
        ttk.Label(bar,text=self.tr('模式：标准战','Mode: standard')).pack(side='right')
        legend=ttk.Frame(parent);legend.pack(fill='x')
        for tag,color in CLASS_COLORS.items():
            if tag=='SPG':continue
            tk.Label(legend,text='  ',background=color).pack(side='left',padx=(6,2))
            ttk.Label(legend,text=self.tr(*labels.ENUM_NAMES['class_tag'][tag])).pack(side='left',padx=(0,8))
        tk.Label(legend,text='■',foreground=CLASS_COLORS['SPG']).pack(side='left',padx=(6,2))
        ttk.Label(legend,text=self.tr('火炮驻炮点','SPG parking')).pack(side='left')
        tk.Label(legend,text=' ┄ ',foreground=CLASS_COLORS['SPG']).pack(side='left',padx=(6,2))
        ttk.Label(legend,text=self.tr('火炮进攻路线','Artillery attack route')).pack(side='left')
        tools=ttk.Frame(parent);tools.pack(fill='x');self.route_toolbar=tools
        for tool_index,(zh,en,command) in enumerate([('新建路线','New route',self.new_route),('新建炮位','New SPG',self.new_position),
                              ('复制','Duplicate',self.duplicate_item),('删除','Delete',self.delete_item),
                              ('撤销','Undo',lambda:self.undo('maps')),('重做','Redo',lambda:self.redo('maps')),
                              ('转换为主要路线','Make main',lambda:self.set_tier('main')),
                              ('转换为备用路线','Make reserve',lambda:self.set_tier('reserve')),
                              ('检查本图','Check map',self.check_map),('适应窗口','Fit view',self.fit_view),
                              ('导入地图','Load image',self.load_background)]):
            button=ttk.Button(tools,text=self.tr(zh,en),command=command);button.grid(row=tool_index//6,column=tool_index%6,sticky='ew',padx=1,pady=2);tools.columnconfigure(tool_index%6,weight=1,uniform='tools')
            if en=='Delete':self.route_delete_button=button
            if en=='Duplicate':self.route_duplicate_button=button
            if en in ('Make main','Make reserve'):
                if not hasattr(self,'tier_buttons'):self.tier_buttons={}
                self.tier_buttons['main' if en=='Make main' else 'reserve']=button
            if en in ('Undo','Redo'):self.history_buttons.append(('maps',en=='Redo',button))
        self.route_restore_button=ttk.Menubutton(tools,text=self.tr('恢复','Restore'))
        self.route_restore_menu=tk.Menu(self.route_restore_button,tearoff=False)
        self.route_restore_menu.add_command(label=self.tr('恢复本路线','Reset route'),command=self.reset_builtin)
        self.route_restore_menu.add_command(label=self.tr('恢复默认路线','Restore default routes'),command=self.restore_default_routes)
        self.route_restore_button.configure(menu=self.route_restore_menu)
        self.route_restore_button.grid(row=1,column=5,sticky='ew',padx=1,pady=2)
        body=ttk.Panedwindow(parent,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body,width=185);centre=ttk.Frame(body);right=ttk.Frame(body,width=280)
        body.add(left,weight=0);body.add(centre,weight=1);body.add(right,weight=0)
        # Keep the waiting controls and legend reachable on smaller displays.
        properties=tk.Canvas(right,width=260,highlightthickness=0)
        scrollbar=ttk.Scrollbar(right,orient='vertical',command=properties.yview)
        scrollbar.pack(side='right',fill='y');properties.pack(side='left',fill='both',expand=True)
        properties.configure(yscrollcommand=scrollbar.set)
        right=ttk.Frame(properties,width=260)
        properties_window=properties.create_window(0,0,anchor='nw',window=right)
        right.bind('<Configure>',lambda e:properties.configure(scrollregion=properties.bbox('all')))
        properties.bind('<Configure>',lambda e:properties.itemconfigure(properties_window,width=e.width))
        self.properties_canvas=properties
        self.items=ttk.Treeview(left,show='tree',height=16,selectmode='browse');self.items.column('#0',width=175)
        item_scroll=ttk.Scrollbar(left,orient='vertical',command=self.items.yview)
        self.items.configure(yscrollcommand=item_scroll.set);item_scroll.pack(side='right',fill='y')
        self.items.pack(side='left',fill='both',expand=True);self.items.bind('<<TreeviewSelect>>',self.select_item)
        self.canvas=tk.Canvas(centre,background='#202529',highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.redraw())
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Double-Button-1>',self.edit_point_condition)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<Button-4>',lambda e:self.wheel(e,1))
        self.canvas.bind('<Button-5>',lambda e:self.wheel(e,-1))
        self.canvas.bind('<ButtonPress-2>',self.pan_start)
        self.canvas.bind('<B2-Motion>',self.pan_move)
        self.canvas.bind('<Delete>',self.delete_selected_point)
        self.canvas.bind('<Motion>',self.cursor)
        self.coords=tk.StringVar(value='');ttk.Label(centre,textvariable=self.coords).pack(anchor='w')
        self.map_status=ttk.Label(centre,text='',wraplength=520);self.map_status.pack(anchor='w')
        self.item_vars={};self.item_fields={}
        for row,(key,zh,en) in enumerate([
            ('label','名称','Label'),('policy','路线模式','Route policy'),('capacity','本车型容量','Class capacity (up to 3)'),
            ('weight','路线分配权重','Route weight'),('slots','指定槽位','Slots'),
            ('radius','炮位区域半径（米）','SPG zone radius (m)'),
            ('heading','炮位朝向（度，0=北）','SPG heading (deg, 0=N)'),('priority','炮位优先级','SPG priority (0–9)'),
            ('route_priority','本车型路线优先级','Class route priority (0–9, higher first)')]):
            label=ttk.Label(right,text=self.tr(zh,en));label.grid(row=row*2,column=0,sticky='w')
            var=tk.StringVar();self.item_vars[key]=var
            if key=='policy':
                widget=LocalizedCombobox(right,variable=var,kind='policy',values=('preferred','fixed'),language=self.language,width=26)
            elif key=='slots':widget=SlotsDropdown(right,var,self.language,width=28)
            elif key in ('capacity','weight','radius','heading','priority','route_priority'):
                limits={'capacity':range(1,4),'weight':tuple(format(i/100,'.6g') for i in range(1,1001)),'radius':range(3,81),'heading':range(-180,181),'priority':range(10),'route_priority':range(10)}
                widget=ttk.Combobox(right,textvariable=var,values=tuple(map(str,limits[key])),state='readonly',width=28)
            else: widget=ttk.Entry(right,textvariable=var,width=28)
            widget.grid(row=row*2+1,column=0,sticky='ew',pady=(0,4));self.item_fields[key]=(label,widget)
        types=ttk.Frame(right);types.grid(row=18,column=0,sticky='ew');self.classes_frame=types
        self.class_vars={}
        for i,c in enumerate(contract.CLASSES[:-1]):
            var=tk.BooleanVar(value=True);self.class_vars[c]=var
            ttk.Checkbutton(types,text=self.tr(*labels.ENUM_NAMES['class_tag'][c]),variable=var).grid(row=i,column=0,sticky='w')
        ttk.Button(right,text=self.tr('应用属性到草稿','Update draft properties'),command=self.update_properties).grid(row=19,column=0,sticky='ew',pady=5)
        self.points=ttk.Combobox(right,state='readonly',width=28);self.points.grid(row=20,column=0,sticky='ew')
        self.points.bind('<<ComboboxSelected>>',lambda e:self.choose_point())
        actions=ttk.Frame(right);actions.grid(row=21,column=0,sticky='ew');self.point_actions=actions
        ttk.Button(actions,text=self.tr('删点','Delete point'),command=self.delete_point).pack(side='left')
        self.insert_button=ttk.Button(actions,text=self.tr('插入点','Insert point'),command=self.insert_point)
        self.insert_button.pack(side='left')
        self.hold_button=ttk.Button(actions,text=self.tr('切换驻留点','Toggle hold'),command=self.toggle_hold)
        # Independent waits are edited in the panel below, not a hold toggle.
        self.wait_button=ttk.Button(actions,text=self.tr('添加等待点','Add wait point'),command=self.edit_point_condition)
        self.wait_button.pack(side='left')
        self.wait_panel=ttk.LabelFrame(right,text=self.tr('等待点编辑','Wait point editor'))
        self.wait_panel.grid(row=22,column=0,sticky='ew',pady=(5,0))
        self.wait_edit_var=tk.BooleanVar(value=False)
        self.wait_edit_check=ttk.Checkbutton(self.wait_panel,text=self.tr('编辑等待点（最多3个）','Edit wait points (maximum 3)'),
            variable=self.wait_edit_var,command=self.change_wait_edit)
        self.wait_edit_check.pack(anchor='w')
        self.wait_list=ttk.Combobox(self.wait_panel,state='readonly',width=28)
        self.wait_list.pack(fill='x');self.wait_list.bind('<<ComboboxSelected>>',self.choose_wait)
        self.wait_list.bind('<Delete>',lambda event:self.delete_wait_point())
        ttk.Label(self.wait_panel,text=self.tr('本等待点停留秒数（-1一直停留）','Wait seconds for this place (-1 stays)')).pack(anchor='w')
        self.wait_seconds=tk.StringVar(value='60')
        self.wait_entry=ttk.Combobox(self.wait_panel,textvariable=self.wait_seconds,values=('-1',)+tuple(map(str,range(3601))),state='readonly',width=12)
        self.wait_entry.pack(fill='x');self.wait_entry.bind('<Return>',self.update_wait_time)
        ttk.Label(self.wait_panel,text=self.tr('就位偏好朝向（度，0=北；留空朝向下一点）','Arrival heading (deg, 0=N; blank=next waypoint)')).pack(anchor='w')
        self.wait_heading=tk.StringVar(value='')
        self.wait_heading_entry=ttk.Combobox(self.wait_panel,textvariable=self.wait_heading,values=('',)+tuple(map(str,range(-180,181))),state='readonly',width=12)
        self.wait_heading_entry.pack(fill='x');self.wait_heading_entry.bind('<Return>',self.update_wait_time)
        self.wait_heading_preview=tk.StringVar(value='')
        ttk.Label(self.wait_panel,textvariable=self.wait_heading_preview).pack(anchor='w')
        actions_wait=ttk.Frame(self.wait_panel);actions_wait.pack(fill='x')
        self.wait_apply=ttk.Button(actions_wait,text=self.tr('设置时间和朝向','Set time and heading'),command=self.update_wait_time);self.wait_apply.pack(side='left')
        self.wait_delete=ttk.Button(actions_wait,text=self.tr('删除等待点','Delete wait point'),command=self.delete_wait_point);self.wait_delete.pack(side='left')
        ttk.Label(self.wait_panel,text=self.tr('圆环为半径6米的实际抵达范围；箭头为偏好朝向，交战可自由转向。勾选后点击添加或拖动；Delete删除。',
            'Ring: actual 6 m arrival radius. Arrow: preferred idle heading; combat can turn freely. Click to add/drag; Delete removes.'),wraplength=250).pack(anchor='w')
        self.node_legend=ttk.LabelFrame(right,text=self.tr('节点图例','Node legend'))
        self._build_connections(right)
        self.node_legend.grid(row=25,column=0,sticky='ew',pady=(5,0))
        for row,(radius,zh,en) in enumerate(((4,'普通节点','Normal waypoint'),
                (7,'大圆点：等待点组（点击展开）','Large circle: wait group (click to expand)'),
                (4,'方点：等待位；圆环：抵达半径6米','Square: wait place; ring: 6 m arrival radius'))):
            marker=tk.Canvas(self.node_legend,width=22,height=20,background='#202529',highlightthickness=0)
            marker.grid(row=row,column=0,padx=4,pady=1)
            draw=marker.create_rectangle if row==2 else marker.create_oval
            if row==2:marker.create_oval(1,0,21,20,outline='white')
            draw(11-radius,10-radius,11+radius,10+radius,fill=CLASS_COLORS['heavyTank'],outline='white')
            ttk.Label(self.node_legend,text=self.tr(zh,en)).grid(row=row,column=1,sticky='w')
        ttk.Label(self.node_legend,text=self.tr('◇ 出生点中心；虚线圈：占领基地范围',
            '◇ Spawn centre; dashed circle: capture area'),wraplength=250).grid(row=3,column=0,columnspan=2,sticky='w')
        ttk.Label(right,text=self.tr(
            '总路线显示各车型生效路线，可选中拖动；重叠时从列表选择。\n选择车型后，默认路线修改只用于该车型。\n通用路线不覆盖已启用的车型专用路线；禁用条目只同步普通点。\n选中或双击大点展开等待点；右侧编辑各点时间。\n勾选路线对称后，两队反向共用节点。\n每条最多16点，保存并应用到下一局。\n普通点击空白不加点；Shift+点击插入中间点；固定首尾不可移动或删除。\n滚轮缩放；中键拖动。',
            'All class routes shows effective routes; select overlapping routes from the list.\nClass selection scopes default-route edits to that class.\nShared travel preserves enabled class variants; disabled records follow without waits.\nSelect or double-click a large node to expand wait places; edit times on the right.\nSymmetry shares reversed nodes between teams.\nUp to 16 points; save and apply next round.\nBlank clicks do not add points; Shift-click inserts between fixed endpoints.\nWheel zooms; middle-drag pans.'),justify='left',wraplength=250).grid(row=26,column=0,sticky='w',pady=8)

        danger=ttk.LabelFrame(right,text=self.tr('危险区参数（只读）','Danger parameters (read only)'))
        danger.grid(row=27,column=0,sticky='ew',pady=(0,8))
        self.danger_parameters_var=tk.StringVar()
        ttk.Label(danger,textvariable=self.danger_parameters_var,justify='left',wraplength=245).pack(anchor='w',padx=4,pady=4)
        ttk.Label(danger,text=self.tr(
            '红格表示危险标记，不代表全部绝对禁行。\n深水：超过水深上限；岸沿：支撑/坠落保护；特殊渡口：按已验证规则有条件通过。\n局部加密区优先使用实际局部网格。鼠标移到图内可查看该位置的标记。',
            'Red cells carry hazard flags; not all are absolute barriers.\nDeep water exceeds the depth limit. Edges protect support/falls. Reviewed fords remain conditional.\nLocal meshes use their actual flags. Hover the map to inspect them.'),
            justify='left',wraplength=245).pack(anchor='w',padx=4,pady=4)

    def _history_scope(self):
        return 'behavior' if self.book.index(self.book.select()) == 0 else 'maps'

    @property
    def undo_stack(self):
        return self.histories[self._history_scope()][0]

    @property
    def redo_stack(self):
        return self.histories[self._history_scope()][1]

    def checkpoint(self, scope='maps'):
        self._connection_snapshot=None
        if scope=='maps' and self.selection and self.selection[0] in ('builtin','routes'):
            self._connection_snapshot=(copy.deepcopy(self.document),{key:(list(pair[0]),list(pair[1])) for key,pair in self.histories.items()},
                self.selection,self.network_mode,self.network_link,self.selected_point,
                copy.deepcopy((self._selected_parent() or {}).get('defense')))
        undo,redo=self.histories[scope]
        undo.append(copy.deepcopy(self.document[scope]));del undo[:-50];redo.clear()

    def _refresh_history(self):
        for scope,redo,button in self.history_buttons:
            button.configure(state='normal' if not self.builtin and self.histories[scope][int(redo)] else 'disabled')

    def _refresh_lock(self):
        for widget,state in getattr(self,'_default_disabled',[]):
            if widget.winfo_exists():widget.configure(state=state)
        self._default_disabled=[]
        locked=self.builtin
        self.save_button.configure(state='disabled' if locked else 'normal')
        self.rename_button.configure(state='disabled' if locked else 'normal')
        self.delete_button.configure(state='disabled' if locked else 'normal')
        self._refresh_history()
        if not locked:return
        allowed={self.map_box,self.team_box,self.route_class_box,self.points,self.wait_list,self.rule_boxes['team'],self.rule_boxes['class_tag'],self.rule_boxes['slot']}
        view_labels={self.tr('检查本图','Check map'),self.tr('适应窗口','Fit view'),
                     self.tr('导入地图','Load image'),self.tr('显示所选范围生效参数','Effective values'),
                     self.tr('显示导航网格','Show navigation grid'),self.tr('显示危险区网格','Show danger grid')}
        def walk(parent):
            for widget in parent.winfo_children():
                if widget not in allowed and isinstance(widget,(ttk.Entry,ttk.Combobox,ttk.Checkbutton,ttk.Button,ttk.Menubutton,SlotsDropdown)):
                    if str(widget.cget('text')) not in view_labels if 'text' in widget.configure() else True:
                        self._default_disabled.append((widget,str(widget.cget('state'))));widget.configure(state='disabled')
                walk(widget)
        walk(self.book)
        self._refresh_history()

    def dirty(self):
        return self.unsaved_new or self.document!=self.original

    def mark(self, sync=True):
        snapshot=getattr(self,'_connection_snapshot',None)
        self._connection_snapshot=None
        if sync and snapshot and self.selection and self.selection[0] in ('builtin','routes'):
            current=(self._selected_parent() or {}).get('defense')
            if current!=snapshot[-1]:
                try:self._sync_connection_scope()
                except Exception as error:
                    self.document,self.histories,self.selection,self.network_mode,self.network_link,self.selected_point=snapshot[:6]
                    self._refresh_items();self.error(error);return False
        self.status.set(self.tr('尚未保存。','Unsaved changes.') if self.dirty() else self.tr('已保存。','Saved.'))
        self._refresh_history();self.redraw()

    def _restore_history(self, scope, redo):
        source=self.histories[scope][int(redo)];target=self.histories[scope][int(not redo)]
        if not source:return
        target.append(copy.deepcopy(self.document[scope]));self.document[scope]=source.pop()
        if scope=='maps':
            self.drag=None
            self._refresh_items()
        else:self._refresh_rules()
        self.mark(sync=False)

    def undo(self, scope=None):
        self._restore_history(scope or self._history_scope(),False)

    def redo(self, scope=None):
        self._restore_history(scope or self._history_scope(),True)

    def _refresh_profiles(self):
        self.profile_box.configure(values=list(dict.fromkeys(self.store.names()+[self.document['name']])))

    def _refresh_rules(self):
        keep = {str(i) for i in range(len(self.document['behavior']))}
        for iid in self.rules.get_children():
            if iid not in keep:self.rules.delete(iid)
        for i,r in enumerate(self.document['behavior']):
            values=(labels.enum_label('team',r['team'],self.language),
                    labels.enum_label('class_tag',r['class_tag'],self.language),
                    r['slot']+1 if r['slot']>=0 else self.tr('全部','All'),
                    labels.parameter_summary(r['values'],self.language))
            if self.rules.exists(str(i)):self.rules.item(str(i),values=values)
            else:self.rules.insert('', 'end',iid=str(i),values=values)

    def _select_rule(self,event=None):
        selected=self.rules.selection()
        if not selected:return
        r=self.document['behavior'][int(selected[0])]
        self._ammo_identity=();self._ammo_preview=None
        for key,var in self.rule_vars.items():
            value=r.get(key,r['values'].get(key,''))
            if key=='slot':value='' if value<0 else value+1
            if key=='crew_preset' and not value and 'crew_level' in r['values']:value='legacy'+str(r['values']['crew_level'])
            var.set(str(value))
            box=self.rule_boxes.get(key)
            if box is not None and str(value) not in box.keys:
                box.keys=tuple(box.keys)+(str(value),);box.set_language(self.language)
        for i,var in enumerate(self.ammo_vars):
            ratios=r['values'].get('ammo_ratios',[])
            var.set(str(ratios[i]) if i<len(ratios) else '')
        self._refresh_equipment_choices()

    def save_rule(self):
        try:
            values={}
            for key in ('skill',)+tuple(contract.PRESETS)+tuple(contract.PARAMETERS):
                value=self.rule_vars[key].get().strip()
                if value:
                    if key=='crew_preset' and value.startswith('legacy'):values['crew_level']=int(value[6:])
                    else:values[key]=value if key=='skill' or key in contract.PRESETS else float(value)
            preview=self._refresh_ammunition()
            ratios=[v.get() for v in self.ammo_vars[:len(preview['shells']) if preview else 3]]
            if any(v!='' for v in ratios):
                if any(v=='' for v in ratios):raise ValueError('Select all ammunition ratios or inherit all three')
                values['ammo_ratios']=[int(v) for v in ratios]
            slot=self.rule_vars['slot'].get()
            r=dict(team=int(self.rule_vars['team'].get()),class_tag=self.rule_vars['class_tag'].get(),
                   slot=int(slot)-1 if slot else -1,values=values)
            doc=copy.deepcopy(self.document)
            doc['behavior']=[a for a in doc['behavior'] if (a['team'],a['class_tag'],a['slot'])!=(r['team'],r['class_tag'],r['slot'])]
            doc['behavior'].append(r)
            # A new map draft may not yet have points; validate this rule alone.
            test=contract.empty();test['behavior']=doc['behavior'];clean=contract.canonical(test)
            self.checkpoint('behavior');self.document['behavior']=clean['behavior'];self._refresh_rules();self.mark()
        except (ValueError,contract.TacticsError) as e:self.error(e)

    def delete_rule(self):
        selected=self.rules.selection()
        if selected:self.checkpoint('behavior');del self.document['behavior'][int(selected[0])];self._refresh_rules();self.mark()

    def preview_rule(self):
        from bot_tactics_preview import PreviewWindow
        preview=PreviewWindow(self.root,self.document,self.rule_vars['team'].get(),
            self.rule_vars['class_tag'].get(),self.rule_vars['slot'].get(),self.language,
            self.lineup(),self.game_root)
        self.previews=[p for p in getattr(self,'previews',[]) if p.root.winfo_exists()]
        self.previews.append(preview)
        return preview

    def entry(self):
        return self.document['maps'].get(self.map_name,dict(mode='regular',resource_sha256=contract.MAPS[self.map_name]['resource_sha256'],routes=[],positions=[]))

    def _ensure_entry(self):
        return self.document['maps'].setdefault(self.map_name, self.entry())

    def _route_scope(self):
        if self.selection and self.selection[0]=='routes':
            item=next((r for r in self.entry()['routes'] if r['id']==self.selection[1].partition('@')[0]),None)
            if item and item.get('purpose')=='spg_attack':return 'SPG'
        if self.route_class_var.get() == 'total' and self.selection:
            return self.selection[1].partition('@')[2] or 'all'
        return self.route_class_var.get()

    def _route_identity(self):
        return self.selection[1].partition('@')[0]

    def _builtin_views(self):
        if self.route_class_var.get() in ('SPG','spg_attack'):return
        graph = self.graph_cache.get(self.map_name) or {}
        tags = contract.CLASSES[:-1] if self.route_class_var.get() == 'total' else (self.route_class_var.get(),)
        for route in graph.get('routes', {}).get(str(self.team), ()):
            for tag in tags:
                if tag == 'SPG':continue
                weights = route.get('class_weights') or {}
                edit=self._default_edit(route,tag) or {}
                # All existing class geometry remains visible; reserve lanes are not deletions.
                if edit.get('disabled') or any(v.get('disabled') and v.get('class_tag','all')=='all' and v['team']==self.team and v['id']==route['id'] for v in self.entry().get('default_routes',())):continue
                identity = route['id'] + '@' + tag if self.route_class_var.get() == 'total' else route['id']
                yield route, tag, identity

    def _selected_parent(self):
        if self.selection:
            kind,identity=self.selection
            if kind=='builtin_positions':
                return next((p for p in self.entry()['positions'] if p['id']==identity),
                            copy.deepcopy(next((p for p in self.spg_defaults if p['id']==identity),None)))
            if kind=='builtin':
                source=next((r for r in (self.graph_cache.get(self.map_name) or {}).get('routes',{}).get(str(self.team),())
                             if r['id']==identity.partition('@')[0]),None)
                if source is None:return None
                edit=self._default_edit(source,self._route_scope())
                result=dict(id=source['id'],label=self._default_name(source['id'],self._route_scope(),'zh'),team=self.team,class_tag=self._route_scope(),
                            symmetric=bool(edit.get('symmetric',False)) if edit else self._default_route_symmetry(),
                            points=copy.deepcopy(edit['points'] if edit else source['waypoints']))
                if edit:
                    for key in ('tier','node_ids','defense'):
                        if key in edit:result[key]=copy.deepcopy(edit[key])
                if self._route_scope() in contract.CLASSES[:-1]:
                    result['priority']=(edit or {}).get('priority',contract.DEFAULT_ROUTE_PRIORITY)
                return result
            item=next((v for v in self.entry()[kind] if v['id']==identity.partition('@')[0]),None)
            return item
        return None


    def _default_edit(self, source, scope=None):
        scope=self._route_scope() if scope is None else scope
        edits=[r for r in self.entry().get('default_routes',()) if r['id']==source['id'] and r['team']==self.team]
        return next((r for r in edits if r.get('class_tag','all')==scope),
                    next((r for r in edits if r.get('class_tag','all')=='all'),None))

    def _editable_parent(self):
        item=self._selected_parent()
        if self.selection[0] in ('positions','builtin_positions'):
            entries=self._ensure_entry()['positions']
            stored=next((p for p in entries if p['id']==item['id']),None)
            if stored is None:entries.append(item);stored=item
            return stored
        if self.selection[0]!='builtin':
            scope=self._route_scope()
            if self.selection[0]=='routes' and scope in contract.CLASSES and len(item['classes'])>1:
                entries=self._ensure_entry()['routes']
                peer=next((r for r in entries if r['id']==item.get('mirror_id')),None)
                new=copy.deepcopy(item);new['id']='r_'+uuid.uuid4().hex[:12];new['classes']=[scope]
                new['family']=item.get('family',item['id']);item.setdefault('family',item['id'])
                new.pop('mirror_id',None)
                item['classes'].remove(scope)
                if peer is not None:
                    other=copy.deepcopy(peer);other['id']='r_'+uuid.uuid4().hex[:12];other['classes']=[scope]
                    other['family']=peer.get('family',peer['id']);peer.setdefault('family',peer['id'])
                    peer['classes'].remove(scope)
                    other['mirror_id']=new['id'];new['mirror_id']=other['id'];entries.append(other)
                entries.append(new);self.selection=('routes',new['id']+('@'+scope if self.route_class_var.get()=='total' else ''));item=new
            return item
        edits=self._ensure_entry().setdefault('default_routes',[])
        edit=next((r for r in edits if r['id']==item['id'] and r['team']==self.team and
                   r.get('class_tag','all')==item['class_tag']),None)
        if edit is None:
            edit=item;edit.pop('label',None);edit['points']=[list(p[:2])+[int(bool(p[2]))]+list(p[3:]) for p in item['points']]
            edits.append(edit)
        return edit

    def _sync_shared_default_geometry(self, item):
        # Enabled class variants own independent travel and parking. Only
        # disabled remnants follow shared travel; they never own wait places.
        item['points']=[list(p[:2])+[0] for p in item['points']]
        for edit in self.entry().get('default_routes',()):
            if (edit['id']==item['id'] and edit['team']==item['team']
                    and edit.get('disabled')):
                edit['points']=copy.deepcopy(item['points'])

    def _symmetry_allowed(self):
        return route_geometry.symmetry_allowed(self.graph_cache.get(self.map_name) or {})

    def _fixed_point(self, index):
        item=self._selected()
        return bool(item and self.selection and self.selection[0] in ('builtin','routes')
            and index in (0,len(item['points'])-1)) or bool(item and self.network_mode and index in (0,len(item['points'])-1))

    def _sync_symmetry(self, geometry=False, item=None):
        if self.network_mode:return
        if item is None:item=self._editable_item()
        if item.get('purpose')=='spg_attack':return
        shared=geometry and self.selection[0]=='builtin' and item.get('class_tag','all')=='all'
        if shared:self._sync_shared_default_geometry(item)
        if not item.get('symmetric') or not self._symmetry_allowed():return
        other=3-self.team
        if self.selection[0]=='builtin':
            entries=self._ensure_entry().setdefault('default_routes',[])
            peer=next((r for r in entries if r['team']==other and r['id']==item['id'] and
                       r.get('class_tag','all')==item.get('class_tag','all')),None)
            if peer is None:peer=dict(id=item['id']);entries.append(peer)
            mirrored=self._mirrored_points(item,peer)
            if 'points' not in peer:peer['points']=copy.deepcopy(mirrored)
            route_network.replace_points(peer,mirrored)
            peer.update(team=other,class_tag=item.get('class_tag','all'),symmetric=True)
            if 'priority' in item:peer['priority']=item['priority']
            if 'label' in item:peer['label']=item['label']
            if shared:self._sync_shared_default_geometry(peer)
        else:
            entries=self._ensure_entry()['routes']
            peer=next((r for r in entries if r['id']==item.get('mirror_id')),None)
            if peer is None:
                peer=dict(id='r_'+uuid.uuid4().hex[:12]);entries.append(peer)
            identity=peer['id'];mirrored=self._mirrored_points(item,peer)
            values=copy.deepcopy(item)
            for field in ('defense','node_ids','points','family'):values.pop(field,None)
            peer.update(values)
            if 'points' not in peer:peer['points']=copy.deepcopy(mirrored)
            route_network.replace_points(peer,mirrored)
            peer.update(id=identity,team=other,mirror_id=item['id'])
            item['mirror_id']=identity

    def _mirrored_points(self, item, peer):
        points=copy.deepcopy(list(reversed(item['points'])))
        own,enemy=route_geometry.anchors(self.graph_cache[self.map_name],3-self.team)
        points[0][:2]=own[:2];points[-1][:2]=enemy[:2]
        if peer.get('disabled') or item.get('class_tag','all')=='all':
            return [p[:2]+[0] for p in points]
        # Waiting is local to a team; synchronizing travel cannot import or
        # delete its existing parked places. Match the source-node coordinates.
        old={tuple(p[:2]):p for p in peer.get('points',())}
        for i,p in enumerate(points):
            prior=old.get(tuple(p[:2]))
            points[i]=p[:2]+copy.deepcopy(prior[2:]) if prior is not None else p[:3]
        return points

    def change_symmetry(self):
        if self.wait_edit or not self._symmetry_allowed():
            self.symmetry_var.set(False)
            return
        if not self.selection or self.selection[0] not in ('builtin','routes'):return
        enabled=self.symmetry_var.get();self.checkpoint();item=self._editable_item()
        item['symmetric']=enabled
        if enabled:self._sync_symmetry()
        elif self.selection[0]=='builtin':
            for r in self.entry().get('default_routes',()):
                if r['id']==item['id'] and r.get('class_tag','all')==item.get('class_tag','all'):r['symmetric']=False
        else:
            for r in self.entry()['routes']:
                if r['id']==item.get('mirror_id'):r['symmetric']=False
        self._refresh_properties();self.redraw();self.mark()

    def _default_route_symmetry(self):
        graph=self.graph_cache.get(self.map_name) or {}
        spawns=graph.get('spawn_anchors') or ()
        bases=graph.get('objective_bases') or ()
        radii=graph.get('objective_base_radii') or ()
        return (len(spawns)==len(bases)==len(radii)==2 and all(
            math.hypot(spawn[0]-base[0],spawn[1]-base[1])<=radius
            for spawn,base,radius in zip(spawns,bases,radii)))

    def _load_map(self):
        meta=contract.MAPS[self.map_name]
        self.baseline_entry=contract.default_map(self.map_name)
        self.view=storage.ViewTransform(meta['bounds'],700,600)
        if self.map_name not in self.graph_cache:
            try:self.graph_cache[self.map_name]=storage.graph_data(self.map_name)
            except Exception as e:self.error(e);self.graph_cache[self.map_name]=None
        bases=(self.graph_cache.get(self.map_name) or {}).get('spawn_anchors') or meta['bases']
        self.base_label.config(text=self.tr('本侧出生点坐标：','Own spawn: ')+str(bases[self.team-1]))
        try:
            if self.map_name not in self.image_cache:
                try:
                    image=storage.minimap_image(self.game_root,self.map_name);label=self.tr('原版客户端小地图','Original client minimap')
                except (OSError,ValueError,KeyError,ImportError):
                    graph=self.graph_cache[self.map_name]
                    image=storage.navigation_image(graph) if graph else None
                    label=self.tr('导航栅格预览（非原版底图）；可导入完整小地图。','Navigation raster, NOT original map artwork; a full-map image can be loaded.')
                self.image_cache[self.map_name]=(image,label)
            self.background,label=self.image_cache[self.map_name]
        except (OSError,ValueError,ImportError,TypeError) as e:
            self.background=None;label=str(e)
        self.map_status.config(text=self._translated_text(label))
        self.symmetry_var.set(self._default_route_symmetry())
        self.selection=None;self.selected_point=None;self._refresh_items();self.redraw()

    def change_map(self):
        self.map_name=self.map_labels[self.map_var.get()];self.team=int(self.team_var.get());self._load_map()

    def change_route_class(self):
        self.network_mode='';self.network_link='';self.selection=None;self.selected_point=None;self.drag=None
        self._refresh_items()

    def _visible_for_class(self, kind, item):
        tag=self.route_class_var.get()
        if kind=='positions':return tag in ('total','SPG')
        if item.get('purpose')=='spg_attack' or item.get('classes')==['SPG']:
            return tag in ('total','spg_attack')
        if tag in ('SPG','spg_attack'):return False
        if tag in ('all','total'):return True
        if kind=='builtin':
            weights=item.get('class_weights') or {}
            return weights.get(tag,0.)>0. if weights else True
        return tag in item['classes']

    def _priority_caption(self, value):
        return self.tr(' [优先级 %d]',' [Priority %d]')%value

    def _default_name(self, identity, scope, language=None):
        edits=[r for r in self.entry().get('default_routes',()) if r['id']==identity and r['team']==self.team and 'label' in r]
        edit=next((r for r in edits if r.get('class_tag','all')==scope),
                  next((r for r in edits if r.get('class_tag','all')=='all'),None))
        return labels.tactic_name(edit['label'],language or self.language) if edit else labels.route_label(identity,language or self.language)

    def _sync_default_name(self, item):
        # Naming never copies geometry, priorities or deletion state.
        edits=self._ensure_entry().setdefault('default_routes',[])
        scope=item.get('class_tag','all')
        teams=(self.team,3-self.team) if item.get('symmetric') else (self.team,)
        for team in teams:
            peer=next((r for r in edits if r['id']==item['id'] and r['team']==team and r.get('class_tag','all')==scope),None)
            if peer is None:
                source=next((r for r in (self.graph_cache.get(self.map_name) or {}).get('routes',{}).get(str(team),()) if r['id']==item['id']),None)
                if source is None:continue
                inherited=next((r for r in edits if r['id']==item['id'] and r['team']==team and r.get('class_tag','all')=='all'),None)
                pts=(inherited or {}).get('points',source['waypoints'])
                peer=dict(id=item['id'],team=team,class_tag=scope,symmetric=bool(item.get('symmetric')),
                          points=[list(p[:2])+[int(bool(p[2]))]+list(p[3:]) for p in pts])
                edits.append(peer)
            peer['label']=item['label']
            if scope=='all':
                for edit in edits:
                    if edit['id']==item['id'] and edit['team']==team:edit['label']=item['label']

    def _builtin_caption(self, identity, scope=None):
        identity,_,tag=identity.partition('@')
        scope=scope or tag or self._route_scope()
        caption=labels.enum_label('class_tag',scope,self.language)
        edit=self._default_edit(dict(id=identity),scope)
        rows=getattr(self,'baseline_entry',{}).get('default_routes',())
        original=next((r for r in rows if r['team']==self.team and r['id']==identity and r.get('class_tag','all')==scope),
            next((r for r in rows if r['team']==self.team and r['id']==identity and r.get('class_tag','all')=='all'),None))
        marker=self.tr(' 已修改',' edited') if edit and edit!=original else ''
        priority=self._priority_caption((edit or {}).get('priority',contract.DEFAULT_ROUTE_PRIORITY)) if scope in contract.CLASSES[:-1] else ''
        name=self.tr('[默认/','[Default/')+caption+'] '+self._default_name(identity,scope)+marker
        return priority.strip()+' '+name if self.route_class_var.get()=='total' else name+priority

    def _parking_caption(self, identity):
        edit=next((p for p in self.entry()['positions'] if p['id']==identity),None)
        item=edit or next(p for p in self.spg_defaults if p['id']==identity)
        label=labels.tactic_name(item['label'],self.language)
        original=next((p for p in getattr(self,'baseline_entry',{}).get('positions',()) if p['id']==identity),None)
        name=self.tr('[默认驻炮点] ','[Default parking] ')+label+(self.tr(' 已修改',' edited') if edit and edit!=original else '')
        priority=self._priority_caption(item['priority'])
        return priority.strip()+' '+name if self.route_class_var.get()=='total' else name+priority

    def _custom_caption(self, kind, item, tag=None):
        caption=('['+labels.enum_label('class_tag',tag,self.language)+'] ') if tag else ''
        priority=self._priority_caption(item.get('class_priorities',{}).get(tag or self.route_class_var.get(),contract.DEFAULT_ROUTE_PRIORITY)) if kind=='routes' and self.route_class_var.get()!='all' else self._priority_caption(item['priority']) if kind=='positions' else ''
        name=caption+(self.tr('路线 ','Route ') if kind=='routes' else self.tr('炮位 ','SPG '))+labels.tactic_name(item['label'],self.language)
        if item.get('purpose')=='spg_attack':return self.tr('火炮进攻路线：','Artillery attack: ')+labels.tactic_name(item['label'],self.language)
        return priority.strip()+' '+name if self.route_class_var.get()=='total' else name+priority

    def _refresh_items(self):
        self.items.delete(*self.items.get_children())
        if not hasattr(self,'spg_default_cache'):self.spg_default_cache={}
        key=(self.map_name,repr(self.entry().get('default_routes',())),repr(self.entry().get('deleted_positions',())))
        if key not in self.spg_default_cache:
            self.spg_default_cache[key]=storage.default_spg_positions(self.map_name,self.graph_cache.get(self.map_name),self.document)
        self.spg_defaults=self.spg_default_cache[key]
        for tag,color in CLASS_COLORS.items():
            self.items.tag_configure('route_'+tag,foreground=color)
        self.items.tag_configure('artillery',foreground=CLASS_COLORS['SPG'])
        def insert_custom(item,tag=None):
            identity=item['id']+'@'+tag if tag else item['id']
            self.items.insert('','end',iid='routes:'+identity,text=self._custom_caption('routes',item,tag),
                tags=('artillery',) if item.get('purpose')=='spg_attack' else ('route_'+(tag or self.route_class_var.get()),))
        for item in self.entry()['routes']:
            if item['team']!=self.team or item.get('purpose')=='spg_attack' or not self._visible_for_class('routes',item):continue
            for tag in (item['classes'] if self.route_class_var.get()=='total' else (None,)):insert_custom(item,tag)
        for route,tag,identity in self._builtin_views():
            self.items.insert('','end',iid='builtin:'+identity,text=self._builtin_caption(route['id'],tag),tags=('route_'+tag,))
        if self.route_class_var.get() in ('SPG','total'):
            default_ids={p['id'] for p in self.spg_defaults}
            for item in self._parking_items():
                kind='builtin_positions' if item['id'] in default_ids else 'positions'
                self.items.insert('','end',iid=kind+':'+item['id'],text=self._parking_caption(item['id']) if kind=='builtin_positions' else self._custom_caption(kind,item),tags=('artillery',))
        for item in self.entry()['routes']:
            if item['team']!=self.team or item.get('purpose')!='spg_attack' or not self._visible_for_class('routes',item):continue
            insert_custom(item,'SPG' if self.route_class_var.get()=='total' else None)
        self._refresh_connection_tree()
        if self.selection and self.items.exists(':'.join(self.selection)):
            self.items.selection_set(self._connection_tree_key() or ':'.join(self.selection))
        else:self.selection=None
        self._refresh_properties();self.redraw()

    def select_item(self,event=None):
        values=self.items.selection();key=values[0] if values else None
        connection=getattr(self,'tree_connections',{}).get(key)
        selected,mode,link=connection if connection else (tuple(key.split(':',1)) if key else None,'','')
        if not connection and selected==self.selection and self.network_mode=='defense':mode='defense'
        if (selected,mode,link)!=(self.selection,self.network_mode,self.network_link):
            self.selection=selected;self.network_mode=mode;self.network_link=link
            self.selected_point=0 if mode else None;self.selected_wait=None;self.wait_edit=False
        self._refresh_properties();self.redraw()

    def _refresh_properties(self):
        parent=self._selected_parent()
        if self.network_mode and (parent is None or not self._connection_points(parent)):
            self.network_mode='';self.network_link='';self.selected_point=None
        item=self._selected()
        route = self.selection and (self.selection[0]=='routes' or bool(self.network_mode))
        builtin = self.selection and self.selection[0]=='builtin'
        parking = self.selection and self.selection[0] in ('positions','builtin_positions') and not self.network_mode
        attack=bool(item and item.get('purpose')=='spg_attack')
        self.insert_button.config(state='normal' if route or builtin else 'disabled')
        allowed = {'label','policy','weight','slots'} if route else {'label'} if builtin else {'label','radius','heading','priority'} if item else set()
        if (route or builtin) and self.route_class_var.get()!='all':allowed.add('route_priority')
        if parking and self.route_class_var.get()=='all':allowed.discard('priority')
        if attack:allowed={'label'}
        if self.network_mode:allowed=set()
        for key, widgets in self.item_fields.items():
            for widget in widgets:
                widget.grid() if key in allowed else widget.grid_remove()
        self.item_fields['route_priority'][1].config(state='readonly')
        self.item_fields['priority'][1].config(state='readonly')
        self.classes_frame.grid() if route and not attack and not self.network_mode and self.route_class_var.get()!='total' else self.classes_frame.grid_remove()
        self.wait_panel.grid_remove() if attack or self.network_mode else self.wait_panel.grid()
        for widget in (self.points,self.point_actions):
            widget.grid() if route or builtin else widget.grid_remove()
        self.wait_button.config(state='normal' if (route or builtin) and not
            (builtin and self._route_scope()=='all') else 'disabled')
        self.hold_button.config(text=self.tr('切换驻留点','Toggle hold'))
        if parking or attack or self.route_class_var.get() in ('SPG','spg_attack'):self.symmetry_var.set(False)
        elif route or builtin:self.symmetry_var.set(bool(item.get('symmetric',False)))
        if self.wait_edit:self.symmetry_var.set(False)
        self.symmetry_check.config(state='normal' if (route or builtin) and not attack and not self.wait_edit and self._symmetry_allowed() else 'disabled',
            text=self.tr('路线对称','Route symmetry'))
        for key,var in self.item_vars.items():
            val=(item or {}).get(key,'')
            if key=='route_priority' and item:
                val=item.get('priority',contract.DEFAULT_ROUTE_PRIORITY) if builtin else item.get('class_priorities',{}).get(self._route_scope(),contract.DEFAULT_ROUTE_PRIORITY)
            if key=='slots' and isinstance(val,list):val=','.join(str(v+1) for v in val)
            var.set(str(val))
        for key,var in self.class_vars.items():var.set(key in (item or {}).get('classes',()))
        pts=(item or {}).get('points',[])
        self.points.config(values=['%d: %.1f, %.1f%s'%(i+1,p[0],p[1],
            (' [%s]'%self.tr('一直停留','Hold')) if len(p)>3 and p[3]<0 else
            (' [%gs]'%p[3]) if len(p)>3 else ' *' if p[2] else '')
            for i,p in enumerate(pts)])
        if self.selected_point is not None and self.selected_point<len(pts):self.points.current(self.selected_point)
        elif parking and pts:self.points.current(0);self.selected_point=0
        else:self.points.set('')
        self._refresh_wait_panel()
        self._refresh_connections()
        self._refresh_lock()

    def new_route(self):
        if self.route_class_var.get()=='total':
            self.error(self.tr('请先选择具体车型或全部车型，再新建路线。','Choose a vehicle class or All classes before creating a route.'));return
        # SPG routes are explicit endgame routes, distinct from parking connections.
        self.checkpoint();identity='r_'+uuid.uuid4().hex[:12]
        scope=self.route_class_var.get()
        if scope in ('SPG','spg_attack'):scope='SPG';self.route_class_var.set('spg_attack')
        self.network_mode='';self.network_link=''
        self.wait_edit=False;self.selected_wait=None
        self._ensure_entry()['routes'].append(dict(id=identity,label=self.tr('新路线','New route'),team=self.team,
            classes=list(contract.CLASSES[:-1]) if scope=='all' else [scope],class_priorities={tag:contract.DEFAULT_ROUTE_PRIORITY for tag in (contract.CLASSES[:-1] if scope=='all' else (scope,)) if tag!='SPG'},slots=[],policy='preferred',capacity=3,weight=1.0,
            points=route_geometry.anchors(self.graph_cache[self.map_name],self.team),
            symmetric=self.symmetry_var.get() and self._symmetry_allowed()))
        if scope=='SPG':
            self.entry()['routes'][-1]['purpose']='spg_attack'
            self.entry()['routes'][-1]['points']=[list(p)+[0] for p in (self.graph_cache[self.map_name]['objective_bases'][self.team-1],self.graph_cache[self.map_name]['objective_bases'][2-self.team])]
        self.selection=('routes',identity);self.selected_point=0
        self._sync_symmetry();self._refresh_items();self.selected_point=0;self._refresh_properties();self.mark()
        self.status.set(self.tr('首尾点固定；Shift＋点击或右侧插入中间点，最多16点。','Endpoints are fixed; Shift-click or insert intermediate points on the right, up to 16 points.'))

    def new_position(self):
        self.route_class_var.set('SPG')
        self.network_mode='';self.network_link='';self.wait_edit=False;self.selected_wait=None
        self.checkpoint();identity='p_'+uuid.uuid4().hex[:12]
        base=self.graph_cache[self.map_name]['objective_bases'][self.team-1]
        other=contract.MAPS[self.map_name]['bases'][2-self.team]
        heading=math.degrees(math.atan2(other[0]-base[0],other[1]-base[1]))
        self._ensure_entry()['positions'].append(dict(id=identity,label=self.tr('新炮位','New SPG zone'),team=self.team,
            point=list(base),radius=16.0,heading=heading,priority=5))
        self.selection=('positions',identity);self._refresh_items();self.mark()

    def duplicate_item(self):
        if self.builtin or self.network_mode:return
        item=self._selected_parent()
        if self.selection and self.selection[0]=='builtin':
            source=next((v for v in self.graph_cache[self.map_name].get('routes',{}).get(str(self.team),()) if v['id']==self._route_identity()),None)
            if source:
                points=copy.deepcopy(item['points'])
                anchors=route_geometry.anchors(self.graph_cache[self.map_name],self.team)
                if points[-1][:2]!=anchors[-1][:2]:
                    if len(points)>=16:
                        self.error(self.tr('保留原末段并添加固定终点会超过16点，请先精简中间点。','Keeping the approach and adding the fixed endpoint exceeds 16 points; simplify intermediate points first.'));return
                    points.append(anchors[-1])
                self.checkpoint();identity='r_'+uuid.uuid4().hex[:12]
                new=dict(id=identity,label=self._default_name(source['id'],self._route_scope())+self.tr(' 副本',' copy'),team=self.team,
                    classes=list(contract.CLASSES[:-1]) if self._route_scope()=='all' else [self._route_scope()],slots=[],policy='preferred',capacity=3,weight=1.0,
                    points=[[float(p[0]),float(p[1]),int(bool(p[2]))]+list(p[3:]) for p in points])
                for field in ('tier','node_ids','defense'):
                    if field in item:new[field]=copy.deepcopy(item[field])
                if 'node_ids' in new and len(new['node_ids'])!=len(new['points']):new['node_ids'].append('n_'+uuid.uuid4().hex[:16])
                new=route_network.clone_route(new)
                self._ensure_entry()['routes'].append(new)
                identity += '@'+new['classes'][0] if self.route_class_var.get()=='total' else ''
                self.selection=('routes',identity);self._refresh_items();self.mark()
            return
        if item is None:return
        self.checkpoint();new=route_network.clone_route(item) if 'points' in item else copy.deepcopy(item)
        if self.selection[0]=='routes' and self.route_class_var.get()=='total':new['classes']=[self._route_scope()]
        new['id']=('r_' if self.selection[0]=='routes' else 'p_')+uuid.uuid4().hex[:12];new['label']+=self.tr(' 副本',' copy')
        new.pop('mirror_id',None);new.pop('symmetric',None);new.pop('family',None)
        new.pop('travel',None);new.pop('links',None)
        kind='positions' if self.selection[0]=='builtin_positions' else self.selection[0]
        self._ensure_entry()[kind].append(new)
        identity=new['id']+'@'+new['classes'][0] if kind=='routes' and self.route_class_var.get()=='total' else new['id']
        self.selection=(kind,identity);self._refresh_items();self.mark()

    def delete_item(self):
        if self.builtin:return
        if self.network_mode=='defense':return self.delete_defense()
        item=self._selected_parent()
        if item is None:return
        if self.selection[0] in ('builtin','routes') and self.route_class_var.get()!='all' and item.get('purpose')!='spg_attack':return
        if self.selection[0]=='builtin':
            if not messagebox.askyesno(self.tr('删除默认路线','Delete default route'),
                    self._builtin_caption(self.selection[1])+'?',parent=self.root):return
            self.checkpoint();scope=self._route_scope();identity=item['id']
            teams=(self.team,3-self.team) if item.get('symmetric') else (self.team,)
            edits=self._ensure_entry().setdefault('default_routes',[])
            for team in teams:
                target=next((r for r in edits if r['id']==identity and r['team']==team and r.get('class_tag','all')==scope),None)
                if target is None:
                    target=copy.deepcopy(item);target['team']=team
                    target['points']=[list(p[:2])+[int(bool(p[2]))]+list(p[3:]) for p in target['points']]
                    if team!=self.team:target['points'].reverse()
                    edits.append(target)
                target['disabled']=True
                if scope=='all':
                    for edit in edits:
                        if edit['id']==identity and edit['team']==team:edit['disabled']=True
            self.selection=None;self.selected_point=None;self._refresh_items();self.mark();return
        if self.selection[0]=='builtin_positions':
            if not messagebox.askyesno(self.tr('删除默认驻炮点','Delete default SPG parking'),item['label']+'?',parent=self.root):return
            self.checkpoint();entry=self._ensure_entry()
            deleted=entry.setdefault('deleted_positions',[])
            if item['id'] not in deleted:deleted.append(item['id'])
            entry['positions'][:]=[p for p in entry['positions'] if p['id']!=item['id']]
            self._remove_parking_references(item['id'])
            self.selection=None;self.selected_point=None;self._refresh_items();self.mark();return
        if not messagebox.askyesno(self.tr('删除','Delete'),item['label']+'?',parent=self.root):return
        self.checkpoint()
        if self.selection[0]=='routes':item=self._editable_item()
        if item.get('symmetric'):
            self.entry()['routes'][:]=[r for r in self.entry()['routes'] if r['id']!=item.get('mirror_id')]
        if self.selection[0]=='routes':
            family=item.get('family',item['id'])
            families={family}
            if item.get('symmetric'):
                rows=self.entry()['routes'];mirrors={r.get('mirror_id') for r in rows if r.get('family',r['id'])==family}
                families.update(r.get('family',r['id']) for r in rows if r['id'] in mirrors)
            self.entry()['routes'][:]=[r for r in self.entry()['routes'] if r.get('family',r['id']) not in families]
        else:
            self.entry()[self.selection[0]].remove(item)
            self._remove_parking_references(item['id'])
        self.selection=None;self.network_mode='';self._refresh_items();self.mark()

    def reset_builtin(self):
        baseline=contract.default_map(self.map_name)
        if self.selection and self.selection[0]=='builtin_positions':
            original=next((p for p in baseline.get('positions',()) if p['id']==self.selection[1]),None)
            if original is not None:
                self.checkpoint();entry=self._ensure_entry()
                entry['positions'][:]=[p for p in entry['positions'] if p['id']!=original['id']]
                restored=copy.deepcopy(original);entry['positions'].append(restored)
                self._sync_parking_endpoints(restored)
                entry['deleted_positions']=[p for p in entry.get('deleted_positions',()) if p!=original['id']]
                self.selected_point=None;self._refresh_items();self.mark();return
        if self.selection and self.selection[0]=='builtin':
            scope=self._route_scope();item=self._selected()
            originals=[r for r in baseline.get('default_routes',()) if r['id']==self._route_identity() and
                (r['team']==self.team or item.get('symmetric')) and
                (scope=='all' or r.get('class_tag','all')==scope)]
            if originals:
                self.checkpoint();entry=self._ensure_entry()
                keys={(r['team'],r['id'],r.get('class_tag','all')) for r in originals}
                entry['default_routes']=[r for r in entry.get('default_routes',()) if
                    (r['team'],r['id'],r.get('class_tag','all')) not in keys]+copy.deepcopy(originals)
                self.selected_point=None;self.selected_wait=None;self.wait_edit=False
                self._refresh_items();self.mark();return
        if self.selection and self.selection[0]=='builtin_positions':
            entries=self.entry()['positions'];remaining=[p for p in entries if p['id']!=self.selection[1]]
            if len(entries)!=len(remaining):
                self.checkpoint();self._ensure_entry()['positions']=remaining;self.selected_point=None;self._refresh_items();self.mark()
            return
        if not self.selection or self.selection[0]!='builtin':return
        edits=self.entry().get('default_routes',[])
        scope=self._route_scope();item=self._selected()
        remaining=copy.deepcopy([r for r in edits if not (r['id']==self._route_identity() and r.get('class_tag','all')==scope and
                   (r['team']==self.team or item.get('symmetric')))])
        if scope=='all':
            graph=self.graph_cache.get(self.map_name) or {}
            for edit in remaining:
                if (edit['id']!=item['id'] or edit.get('class_tag','all') not in contract.CLASSES[:-1] or
                        (edit['team']!=self.team and not item.get('symmetric'))):continue
                source=next((r for r in graph.get('routes',{}).get(str(edit['team']),()) if r['id']==item['id']),None)
                if source:edit['points']=[list(p[:2])+[0] for p in source['waypoints']]
        if remaining==edits:return
        self.checkpoint()
        if remaining:self.entry()['default_routes']=remaining
        else:self.entry().pop('default_routes',None)
        if not self.entry()['routes'] and not self.entry()['positions'] and not remaining and not self.entry().get('deleted_positions'):
            self.document['maps'].pop(self.map_name,None)
        self.selected_point=None;self.selected_wait=None;self.wait_edit=False;self._refresh_properties();self.redraw();self.mark()

    def update_properties(self):
        if self.network_mode:return True
        item=self._selected()
        if item is None:return
        if self.selection[0]=='builtin':
            try:
                name=contract._text(self.item_vars['label'].get())
                priority=item.get('priority',contract.DEFAULT_ROUTE_PRIORITY)
                if self._route_scope() in contract.CLASSES[:-1]:
                    priority=int(self.item_vars['route_priority'].get())
                    if not 0<=priority<=9:raise ValueError(self.tr('优先级应为0–9。','Priority must be 0–9.'))
                renamed=name!=item['label'];reprioritized=priority!=item.get('priority',contract.DEFAULT_ROUTE_PRIORITY)
                if not renamed and not reprioritized:return True
                self.checkpoint();edit=self._editable_item()
                if reprioritized:edit['priority']=priority;self._sync_symmetry()
                if renamed:edit['label']=name;self._sync_default_name(edit)
                self._refresh_items();self.mark();return True
            except (ValueError,contract.TacticsError) as e:self.error(e);return False
        try:
            new=copy.deepcopy(item);new['label']=self.item_vars['label'].get()
            kind='positions' if self.selection[0]=='builtin_positions' else self.selection[0]
            if self.selection[0]=='routes' and item.get('purpose')=='spg_attack':
                pass  # Only the name and authored nodes are editable for this purpose.
            elif self.selection[0]=='routes':
                if not 1<=int(self.item_vars['capacity'].get())<=3:raise ValueError(self.tr('本车型路线容量应为1–3辆。','Class route capacity must be 1–3.'))
                new.update(policy=self.item_vars['policy'].get(),capacity=int(self.item_vars['capacity'].get()),
                    weight=float(self.item_vars['weight'].get()),classes=[k for k,v in self.class_vars.items() if v.get()],
                    slots=[int(v.strip())-1 for v in self.item_vars['slots'].get().split(',') if v.strip()])
                if self._route_scope() in contract.CLASSES[:-1]:
                    priority=int(self.item_vars['route_priority'].get())
                    if not 0<=priority<=9:raise ValueError(self.tr('优先级应为0–9。','Priority must be 0–9.'))
                    new.setdefault('class_priorities',{})[self._route_scope()]=priority
            else:
                new.update(radius=float(self.item_vars['radius'].get()),heading=float(self.item_vars['heading'].get()),priority=int(self.item_vars['priority'].get()) if self.route_class_var.get() in ('SPG','total') else item['priority'])
            if new.get('purpose')=='spg_attack':new['classes']=['SPG']
            if new==item:return True
            # Validate atomically; malformed properties never mutate the draft.
            test=contract.empty();test['maps'][self.map_name]=copy.deepcopy(self.entry())
            test['maps'][self.map_name][kind]=[new]
            test['maps'][self.map_name]['positions' if kind=='routes' else 'routes']=[]
            contract.canonical(test)
            priority_only=kind=='routes' and {k:v for k,v in new.items() if k!='class_priorities'}=={k:v for k,v in item.items() if k!='class_priorities'}
            self.checkpoint()
            if not priority_only:item=self._editable_item()
            if kind=='routes' and self.route_class_var.get()=='total' and not priority_only:
                new.update(id=item['id'],classes=item['classes'])
                if 'mirror_id' in item:new['mirror_id']=item['mirror_id']
            item.clear();item.update(new)
            if self.selection[0]=='routes':self._sync_symmetry(item=item)
            self._refresh_items();self.mark();return True
        except (ValueError,contract.TacticsError) as e:self.error(e);return False

    def choose_point(self):
        self.selected_point=self.points.current();self.selected_wait=None;self.wait_edit=False;self._refresh_properties();self.redraw()

    def delete_point(self):
        item=self._selected()
        if self._fixed_point(self.selected_point):return
        if item is not None and self.selected_point is not None and self.selected_point<len(item.get('points',())):
            parking=self.selection[0] in ('positions','builtin_positions') and not self.network_mode
            if parking and len(item['points'])==1:return
            self.checkpoint()
            if self.network_mode:del self._editable_points()[self.selected_point]
            else:route_network.delete_node(self._editable_item(),self.selected_point)
            if parking:self._editable_item()['point']=self._editable_points()[0][:2]
            self._sync_symmetry(geometry=True);self.selected_point=None;self.selected_wait=None;self.wait_edit=False;self._refresh_properties();self.redraw();self.mark()

    def _insert_route_point(self, position):
        item=self._selected()
        if item is None or (self.selection[0] not in ('builtin','routes') and not self.network_mode):return
        points=item['points']
        if len(points)>=16:
            self.error(self.tr('每条路线最多16个点。','A route allows at most 16 points.'));return
        index=route_geometry.insertion_index(points,self.selected_point)
        if any(math.hypot(position[0]-p[0],position[1]-p[1])<1 for p in points[index-1:index+1]):
            self.error(self.tr('相邻点距离不足1米。','Adjacent points need at least one metre separation.'));return
        self.checkpoint()
        if self.network_mode:self._editable_points().insert(index,list(position)+[0])
        else:route_network.insert_node(self._editable_item(),index,list(position)+[0])
        self._sync_symmetry(geometry=True);self.selected_point=index
        self._refresh_items();self.selected_point=index;self._refresh_properties();self.mark()

    def insert_point(self):
        item=self._selected()
        if item is None or (self.selection[0] not in ('builtin','routes') and not self.network_mode):return
        index=route_geometry.insertion_index(item['points'],self.selected_point)
        first,last=item['points'][index-1:index+1]
        self._insert_route_point([(first[0]+last[0])*.5,(first[1]+last[1])*.5])

    def toggle_hold(self):
        if self.network_mode or self._wait_point() is None:return
        if self.selection and self.selection[0]=='builtin' and self._route_scope()=='all':return
        item=self._selected()
        if item is not None and self.selected_point is not None and self.selected_point<len(item.get('points',())):
            self.checkpoint();p=self._editable_points()[self.selected_point];p[2]=int(not p[2])
            if self.selection[0] in ('routes','builtin'):p[3:]=[-1.0 if p[2] else 0.0]
            self._sync_symmetry(geometry=True);self._refresh_properties();self.redraw();self.mark()

    def _wait_point(self):
        item=self._selected();index=self.selected_point
        if (item is None or not self.selection or self.selection[0] not in ('routes','builtin') or
                index is None or not 0<=index<len(item.get('points',()))):return None
        if self.selection[0]=='builtin' and self._route_scope()=='all':return None
        if self.network_mode or item.get('purpose')=='spg_attack':return None
        if item.get('defense') and route_network.nodes(item)[index]==item['defense']['junction']:return None
        return item['points'][index]

    def _refresh_wait_panel(self):
        point=self._wait_point()
        if point is None:self.wait_edit=False;self.selected_wait=None;self._wait_add_at_parent=False;self._wait_parent_cleared=False
        places=contract.waiting_positions(point) if point is not None else []
        self.wait_edit_var.set(self.wait_edit)
        self.wait_edit_check.config(state='normal' if point is not None else 'disabled')
        self.wait_list.config(values=[self.tr('等待点 %d：%gs','Wait place %d: %gs')%(i+1,p[2]) for i,p in enumerate(places)])
        if self.selected_wait is not None and self.selected_wait<len(places):
            self.wait_list.current(self.selected_wait);self.wait_seconds.set(str(places[self.selected_wait][2]));self.wait_heading.set(str(places[self.selected_wait][3]) if len(places[self.selected_wait])>3 else '')
        else:self.selected_wait=None;self.wait_list.set('')
        angle=None
        if self.selected_wait is not None:
            item=self._selected();following=item['points'][self.selected_point+1] if self.selected_point+1<len(item['points']) else None
            angle=contract.waiting_heading(places[self.selected_wait],following)
        self.wait_heading_preview.set(self.tr('自动朝向下一个路线点：%.1f°','Automatic next-waypoint heading: %.1f°')%angle if angle is not None and self.selected_wait is not None and len(places[self.selected_wait])==3 else self.tr('已到末端：保持当前朝向','End of route: keep current heading') if self.selected_wait is not None and angle is None else '')
        enabled=self.wait_edit and self.selected_wait is not None
        for widget in (self.wait_entry,self.wait_heading_entry,self.wait_apply,self.wait_delete):
            widget.config(state=('readonly' if isinstance(widget,ttk.Combobox) else 'normal') if enabled else 'disabled')
        self.wait_list.config(state='readonly' if self.wait_edit else 'disabled')

    def change_wait_edit(self):
        self._wait_add_at_parent=False
        self.wait_edit=bool(self.wait_edit_var.get()) and self._wait_point() is not None
        if self.wait_edit:self._detach_wait_symmetry()
        self.drag=None;self._refresh_properties();self.redraw()

    def _detach_wait_symmetry(self, checkpoint=True):
        """Parking places belong to this team; keep the peer's existing draft."""
        item=self._selected()
        if item is None or not item.get('symmetric',True):return
        if checkpoint:self.checkpoint()
        item=self._editable_item();item['symmetric']=False
        if self.selection[0]=='builtin':
            for peer in self.entry().get('default_routes',()):
                if peer['id']==item['id'] and peer.get('class_tag','all')==item.get('class_tag','all'):
                    peer['symmetric']=False
        else:
            for peer in self.entry().get('routes',()):
                if peer['id']==item.get('mirror_id'):peer['symmetric']=False
        self.symmetry_var.set(False);self.mark()

    def edit_point_condition(self,event=None):
        if event is not None:
            item=self._selected()
            if item is None:return
            index=next((i for i,p in enumerate(item.get('points',()))
                if math.hypot(*(a-b for a,b in zip(self.view.screen(p),(event.x,event.y))))<12),None)
            if index is None:return
            if self.wait_edit and index==self.selected_point:
                if self._wait_add_at_parent:
                    self._press_wait(event)
                    return 'break'
                # A double-click on the parent only selects/focuses its editor;
                # it is not an instruction to recreate a deleted small place.
                self._wait_add_at_parent=False
            self.selected_point=index;self.selected_wait=None
        if self._wait_point() is None:return
        self._detach_wait_symmetry()
        self._wait_add_at_parent = event is None
        if event is None:self._wait_parent_cleared=False
        self.wait_edit=True;self.drag=None;self._refresh_properties();self.redraw()
        self.root.update_idletasks()
        region=self.properties_canvas.bbox('all')
        if region and region[3]>self.properties_canvas.winfo_height():
            self.properties_canvas.yview_moveto(float(self.wait_panel.winfo_y())/region[3])
        self.wait_panel.focus_set()
        return 'break'

    def _store_wait_places(self, places):
        if self._wait_point() is None:return False
        self._detach_wait_symmetry(checkpoint=False)
        point=self._editable_points()[self.selected_point]
        point[3:]=[0.0,copy.deepcopy(places)] if places else []
        self._wait_parent_cleared=not bool(places)
        point[2]=int(bool(places));self._sync_symmetry(geometry=True)

    def choose_wait(self,event=None):
        self.selected_wait=self.wait_list.current();self._refresh_wait_panel();self.redraw()

    def update_wait_time(self,event=None):
        point=self._wait_point()
        if not self.wait_edit or point is None or self.selected_wait is None:return
        try:
            seconds=contract.number(float(self.wait_seconds.get()),-1,3600)
            if -1<seconds<0:raise ValueError()
            heading=contract.number(float(self.wait_heading.get()),-180,180) if self.wait_heading.get().strip() else None
        except (ValueError,contract.TacticsError):
            self.error(self.tr('时间应为-1或0–3600秒，朝向应为-180至180度或留空。','Use -1 or 0–3600 seconds; heading must be -180 to 180 or blank.'));return False
        places=copy.deepcopy(contract.waiting_positions(point))
        if self.selected_wait>=len(places):return
        updated=places[self.selected_wait][:2]+[seconds]+([heading] if heading is not None else [])
        if places[self.selected_wait]!=updated:
            self.checkpoint();places[self.selected_wait]=updated;self._store_wait_places(places);self.mark()
        self._refresh_properties();return True

    def delete_wait_point(self):
        point=self._wait_point()
        if not self.wait_edit or point is None or self.selected_wait is None:return
        places=copy.deepcopy(contract.waiting_positions(point))
        if not 0<=self.selected_wait<len(places):return
        self.checkpoint();del places[self.selected_wait];self._store_wait_places(places)
        self._wait_add_at_parent=False
        self.selected_wait=None;self.drag=None;self._refresh_properties();self.mark()
        return 'break'

    def delete_selected_point(self,event=None):
        if self.wait_edit:self.delete_wait_point()
        else:self.delete_point()
        return 'break'

    def _press_wait(self,event):
        point=self._wait_point()
        if point is None:return
        places=copy.deepcopy(contract.waiting_positions(point))
        selected=next((i for i,p in enumerate(places) if math.hypot(*(a-b for a,b in
            zip(self.view.screen(p),(event.x,event.y))))<10),None)
        created=selected is None
        if selected is None:
            if (math.hypot(*(a-b for a,b in zip(self.view.screen(point),(event.x,event.y))))<12
                    and not self._wait_add_at_parent):
                self.selected_wait=None;self.drag=None;self._refresh_properties();self.redraw()
                return 'break'
            if len(places)>=3:
                self.error(self.tr('每个路线节点最多3个等待点。','A route node allows at most 3 wait places.'));return
            p=list(self.view.world(event.x,event.y))
            if any(math.hypot(p[0]-q[0],p[1]-q[1])<1 for q in places):return
            self.checkpoint();places.append(p+[60.0]);selected=len(places)-1;self._store_wait_places(places)
        self._drag_started=created
        self._wait_add_at_parent=False
        self.selected_wait=selected;self.drag=('wait',selected);self._refresh_properties();self.mark()

    def press(self,event):
        self.canvas.focus_set();self.drag=None;self._drag_started=False
        if self.wait_edit:return self._press_wait(event)
        if self.route_class_var.get()=='total' and not self.network_mode and not event.state & 1:
            targets=[v for v in self.route_hit_targets if math.hypot(v[2][0]-event.x,v[2][1]-event.y)<10]
            if targets:
                target=min(targets,key=lambda v:(v[0]!=self.selection,math.hypot(v[2][0]-event.x,v[2][1]-event.y)))
                self.selection=target[0];self.selected_point=target[1]
                self.items.selection_set(':'.join(self.selection));self._refresh_properties()
        item=self._selected()
        if item is None:
            if event.state & 1:self.error(self.tr('请先选择路线。','Select a route first.'))
            return
        p=self.view.world(event.x,event.y)
        if self.selection[0] in ('positions','builtin_positions') and not self.network_mode:
            if list(item['point'])!=list(p):
                self.checkpoint();self._editable_item()['point']=list(p)
                zone=self._editable_item()
                self._sync_parking_endpoints(zone)
                self.mark()
            self.selected_point=0;self.drag=('position',0);self._drag_started=True
            self._refresh_properties();return
        pts=item['points']
        nearest=next((i for i,pt in enumerate(pts) if math.hypot(*(a-b for a,b in zip(self.view.screen(pt),(event.x,event.y))))<10),None)
        if nearest is None:
            if event.state & 1:self._insert_route_point(p)
            return
        self.selected_point=nearest;self.selected_wait=None
        if not self._fixed_point(nearest):self.drag=('route',nearest)
        self._refresh_properties();self.redraw()

    def motion(self,event):
        item=self._selected()
        if item is None or self.drag is None:return
        p=list(self.view.world(event.x,event.y))
        if self.drag[0]=='route' and self._fixed_point(self.drag[1]):return
        if self.drag[0]=='wait':
            places=copy.deepcopy(contract.waiting_positions(self._wait_point()))
            current=places[self.drag[1]][:2]
        elif self.drag[0]=='position':current=item['point']
        else:current=item['points'][self.drag[1]][:2]
        if list(current)==p:return
        if not self._drag_started:self.checkpoint();self._drag_started=True
        if self.drag[0]=='wait':
            places[self.drag[1]][:2]=p;self._store_wait_places(places)
        elif self.drag[0]=='position':
            zone=self._editable_item();zone['point']=p
            self._sync_parking_endpoints(zone)
        else:
            self._editable_points()[self.drag[1]][:2]=p
            if not self.network_mode:route_network.sync_junction(self._editable_item())
            self._sync_symmetry(geometry=True)
        self.redraw()

    def release(self,event):
        changed=getattr(self,'_drag_started',False)
        self.drag=None;self._drag_started=False
        if changed:self._refresh_items();self.mark()
        else:self._refresh_properties();self.redraw()

    def cursor(self,event):
        if hasattr(self,'view'):
            x,z=self.view.world(event.x,event.y)
            text='X %.2f   Z %.2f'%(x,z)
            if self.danger_grid_var.get():
                graph=self._danger_graph()
                if graph:
                    flags=navigation_view.hazard_at(graph,(x,z))
                    names=[self.tr(zh,en) for bit,zh,en in (
                        (1,'深水','Deep water'),(2,'支撑边沿','Support edge'),
                        (4,'特殊渡口','Reviewed ford'),(8,'近水岸沿保护','Wet-edge protection')) if flags&bit]
                    text+='  '+(' / '.join(names) if names else self.tr('无危险标记','No hazard flag'))
            self.coords.set(text)

    def pan_start(self,event):self.pan=(event.x,event.y,self.view.pan_x,self.view.pan_y)
    def pan_move(self,event):
        if hasattr(self,'pan'):
            self.view.pan_x=self.pan[2]+event.x-self.pan[0];self.view.pan_y=self.pan[3]+event.y-self.pan[1];self.redraw()

    def wheel(self,event,delta=None):
        if not hasattr(self,'view'):return
        delta=delta if delta is not None else 1 if event.delta>0 else -1
        before=self.view.world(event.x,event.y);self.view.zoom=max(.5,min(4,self.view.zoom*(1.15 if delta>0 else 1/1.15)))
        x,y=self.view.screen(before);self.view.pan_x+=event.x-x;self.view.pan_y+=event.y-y;self.redraw()

    def fit_view(self):
        self.view.zoom=1;self.view.pan_x=self.view.pan_y=0;self.redraw()

    def redraw(self):
        if not hasattr(self,'view'):return
        c=self.canvas;c.delete('all');self.view.width=max(150,c.winfo_width());self.view.height=max(150,c.winfo_height())
        b=self.view.bounds;left,top,scale=self.view.frame();w=(b[2]-b[0])*scale;h=(b[3]-b[1])*scale
        if self.background is not None:
            from PIL import Image,ImageTk
            # Draw only the visible crop at high zoom; bounded pixels/memory.
            resized=self.background.resize((max(1,int(w)),max(1,int(h))),Image.Resampling.BILINEAR)
            self.photo=ImageTk.PhotoImage(resized,master=self.root);c.create_image(left,top,image=self.photo,anchor='nw')
        if self.navigation_grid_var.get():
            self._draw_navigation_grid()
        else:
            self.navigation_photo = None
        if self.danger_grid_var.get():
            self._draw_navigation_grid(danger=True)
        else:
            self.danger_photo=None
        self._refresh_danger_parameters()
        c.create_rectangle(left,top,left+w,top+h,outline='#c6cece')
        for i in range(11):
            c.create_line(left+w*i/10,top,left+w*i/10,top+h,fill='#6d787d',dash=(2,6))
            c.create_line(left,top+h*i/10,left+w,top+h*i/10,fill='#6d787d',dash=(2,6))
            if i<10:
                c.create_text(left+w*(i+.5)/10,top-12,text='1234567890'[i],fill='white')
                c.create_text(left-12,top+h*(i+.5)/10,text='ABCDEFGHJK'[i],fill='white')
        # Total view draws effective class routes, without a separate all-class line.
        self.route_hit_targets=[]
        for r,tag,identity in sorted(self._builtin_views(),key=lambda v:self.selection==('builtin',v[2])):
            edit=self._default_edit(r,tag)
            pts=edit['points'] if edit else r.get('waypoints',())
            chosen=self.selection==('builtin',identity)
            color=CLASS_COLORS[tag]
            coords=[v for p in pts for v in self.view.screen(p)]
            if len(coords)>=4:c.create_line(*coords,fill=color,width=3 if chosen else 2,dash=(5,5) if (edit or {}).get('tier')=='reserve' else ())
            for i,p in enumerate(pts):
                self.route_hit_targets.append((('builtin',identity),i,self.view.screen(p)))
                self._draw_route_node(p,i,color,chosen,4,chosen)
        # Route endpoints use validated spawn anchors, not capture objectives.
        # Spawn areas and capture circles are separate on several maps.
        bases=(self.graph_cache.get(self.map_name) or {}).get('spawn_anchors') or ()
        for i,p in enumerate(bases,1):
            x,y=self.view.screen(p);c.create_polygon(x,y-9,x+9,y,x,y+9,x-9,y,outline='#8de3cf' if i==self.team else '#ddaaaa',fill='',width=2,tags=('spawn_anchor','spawn_anchor_'+str(i)))
            c.create_text(x,y-18,text=self.tr('出生','Spawn ')+str(i),fill='white')
        graph=self.graph_cache.get(self.map_name) or {}
        scale=self.view.frame()[2]
        for i,(p,radius) in enumerate(zip(graph.get('objective_bases',()),graph.get('objective_base_radii',())),1):
            x,y=self.view.screen(p);r=radius*scale
            c.create_oval(x-r,y-r,x+r,y+r,outline='#8de3cf' if i==self.team else '#ddaaaa',width=2,dash=(6,4),tags=('capture_base','capture_base_'+str(i)))
            c.create_text(x,y+16,text=self.tr('基地','Base ')+str(i),fill='white')
        defaults=[p for p in self.spg_defaults if not any(v['id']==p['id'] for v in self.entry()['positions'])]
        for kind in ('routes','positions'):
            for item in self.entry()[kind]+(defaults if kind=='positions' else []):
                if item['team']!=self.team or not self._visible_for_class(kind,item):continue
                chosen=self.selection==(kind,item['id']) or self.selection==('builtin_positions',item['id'])
                if kind=='routes':
                    tags=('SPG',) if item.get('purpose')=='spg_attack' else item['classes'] if self.route_class_var.get()=='total' else (self.route_class_var.get(),)
                    for tag in sorted(tags,key=lambda tag:self.selection==('routes',item['id']+'@'+tag)):
                        identity=item['id']+'@'+tag if self.route_class_var.get()=='total' else item['id']
                        selected=self.selection==('routes',identity)
                        color=CLASS_COLORS[tag]
                        coords=[v for p in item['points'] for v in self.view.screen(p)]
                        if len(coords)>=4:c.create_line(*coords,fill=color,width=3 if selected else 2,arrow='last',dash=(5,5) if item.get('tier')=='reserve' or item.get('purpose')=='spg_attack' else (),tags=('artillery_attack',) if item.get('purpose')=='spg_attack' else ('authored_route',))
                        for i,p in enumerate(item['points']):
                            x,y=self.view.screen(p)
                            self.route_hit_targets.append((('routes',identity),i,(x,y)))
                            self._draw_route_node(p,i,color,selected,5,selected)
                else:
                    color=CLASS_COLORS['SPG']
                    key=('builtin_positions' if any(p['id']==item['id'] for p in self.spg_defaults) else 'positions',item['id'])
                    self.route_hit_targets.append((key,0,self.view.screen(item['point'])))
                    x,y=self.view.screen(item['point']);radius=item['radius']*scale;angle=math.radians(item['heading'])
                    c.create_oval(x-radius,y-radius,x+radius,y+radius,outline=color,width=2)
                    c.create_rectangle(x-5,y-5,x+5,y+5,fill=color,outline='white')
                    c.create_line(x,y,x+math.sin(angle)*28,y-math.cos(angle)*28,fill=color,width=2,arrow='last')
                    c.create_text(x+12,y+12,text=labels.tactic_name(item['label'],self.language),fill='white',anchor='nw')
        self._draw_connections()
        if self.navigation_grid_var.get():
            captions = (
                ('available','有高度及连接','Height and links'),
                ('missing_ground','缺地面高度','Missing height'),
                ('navigation_hazard','危险标记','Hazard flag'),
                ('no_navigation_links','无连接','No links'))
            for index,(key,zh,en) in enumerate(captions):
                x=12+index*155
                c.create_rectangle(x,12,x+145,38,fill='#202529',outline='')
                c.create_rectangle(x+5,20,x+15,30,fill=navigation_view.COLORS[key][0],outline='')
                c.create_text(x+20,25,text=self.tr(zh,en),anchor='w',fill='white')

    def _draw_route_node(self, point, index, color, editing, normal_radius, visible=True):
        # Only explicit nonzero waits stop route progression; legacy hold flags do not.
        places=contract.waiting_positions(point)
        waiting=bool(places)
        if not visible and not waiting:return
        x,y=self.view.screen(point)
        if waiting:
            radius=10 if editing and index==self.selected_point else 7
        else:
            radius=7 if editing and index==self.selected_point else normal_radius
        self.canvas.create_oval(x-radius,y-radius,x+radius,y+radius,fill=color,
            outline='white' if waiting or editing or point[2] else color,
            tags=('route_wait' if waiting else 'route_node',))
        if editing:self.canvas.create_text(x+radius+3,y-radius-3,text=str(index+1),fill='white',anchor='w')
        if editing and index==self.selected_point:
            ring=contract.ROUTE_ARRIVAL_RADIUS*self.view.frame()[2]
            self.canvas.create_oval(x-ring,y-ring,x+ring,y+ring,outline='white',width=2,dash=(3,2),
                tags=('route_arrival',))
            for slot,place in enumerate(places):
                px,py=self.view.screen(place);size=6 if self.selected_wait==slot else 4
                self.canvas.create_line(x,y,px,py,fill=color,dash=(2,3),tags=('wait_connector',))
                ring=contract.WAIT_AVOIDANCE_RADIUS*self.view.frame()[2]
                self.canvas.create_oval(px-ring,py-ring,px+ring,py+ring,outline=color,width=2,tags=('wait_avoidance',))
                self.canvas.create_rectangle(px-size,py-size,px+size,py+size,fill=color,outline='white',tags=('wait_place',))
                item=self._selected();following=item['points'][index+1] if item and index+1<len(item['points']) else None
                heading=contract.waiting_heading(place,following)
                if heading is not None:
                    angle=math.radians(heading);length=max(18,ring)
                    self.canvas.create_line(px,py,px+math.sin(angle)*length,py-math.cos(angle)*length,fill=color,width=2,arrow='last',tags=('wait_heading',))
                caption='%d: %s'%(slot+1,self.tr('一直停留','Stay') if place[2]<0 else '%gs'%place[2])
                self.canvas.create_text(px+size+3,py-size-3,text=caption,fill='white',anchor='w',tags=('wait_caption',))

    def _danger_graph(self):
        graph=self.graph_cache.get(self.map_name)
        if graph and self.map_name not in self.danger_graph_cache:
            self.danger_graph_cache.clear()
            self.danger_graph_cache[self.map_name]=navigation_view.classified_hazards(graph)
        return self.danger_graph_cache.get(self.map_name)

    def _refresh_danger_parameters(self):
        graph=self.graph_cache.get(self.map_name)
        if not graph:return
        p=navigation_view.danger_parameters(graph)
        def value(number):
            return '%g'%number if number is not None else self.tr('未记录','Unrecorded')
        text=self.tr('水深上限：%s 米\n主网格岸沿采样半径：%s 米\n网格连接坡度上限：%s\n烘焙参考半宽：%s 米\n主网格：%s 米；局部：%s 米',
            'Water limit: %s m\nBase edge sample radii: %s m\nGrid link grade limit: %s\nBake reference half-width: %s m\nBase grid: %s m; local: %s m')%(
            value(p['water_depth']),'/'.join(map(value,p['edge_radii'])) or '—',
            ('%.1f°'%math.degrees(math.atan(p['max_grade']))) if p['max_grade'] is not None else '—',
            value(p['half_width']),value(p['base_cell_size']),'/'.join(map(value,p['local_cell_sizes'])) or '—')
        if p['ford_depths']:
            text+='\n'+self.tr('单独验证渡口上限：%s 米','Separately reviewed ford limits: %s m')%'/'.join(map(value,p['ford_depths']))
        self.danger_parameters_var.set(text)

    def _draw_navigation_grid(self,danger=False):
        graph=self.graph_cache.get(self.map_name)
        if not graph:return
        from PIL import Image,ImageTk
        cache=self.danger_image_cache if danger else self.navigation_image_cache
        if self.map_name not in cache:
            cache.clear()
            render=navigation_view.danger_overlay_image if danger else navigation_view.overlay_image
            cache[self.map_name]=render(graph,self.view.bounds)
        image=cache[self.map_name]
        cell=graph['cell_size'];ox,oz=graph['origin']
        left,top=self.view.screen((ox-cell*.5,oz+(graph['height']-.5)*cell))
        scale=self.view.frame()[2]
        width=max(1,round(graph['width']*cell*scale))
        height=max(1,round(graph['height']*cell*scale))
        # Crop to the visible canvas before scaling; zoom/pan stay bounded.
        x0=max(0,int(math.floor(-left/width*image.width)))
        y0=max(0,int(math.floor(-top/height*image.height)))
        x1=min(image.width,int(math.ceil((self.view.width-left)/width*image.width)))
        y1=min(image.height,int(math.ceil((self.view.height-top)/height*image.height)))
        if x1<=x0 or y1<=y0:
            if danger:self.danger_photo=None
            else:self.navigation_photo=None
            return
        crop=image.crop((x0,y0,x1,y1))
        resized=crop.resize((max(1,round((x1-x0)*width/image.width)),
                             max(1,round((y1-y0)*height/image.height))),Image.Resampling.NEAREST)
        photo=ImageTk.PhotoImage(resized,master=self.root)
        if danger:self.danger_photo=photo
        else:self.navigation_photo=photo
        self.canvas.create_image(left+x0*width/image.width,top+y0*height/image.height,
                                 image=photo,anchor='nw',tags=('danger_grid' if danger else 'navigation_grid',))

    def check_map(self):
        try:
            import bot_tactics_check_ui
            return bot_tactics_check_ui.show(self)
        except Exception as e:self.error(e)

    def load_background(self):
        filename=filedialog.askopenfilename(parent=self.root,filetypes=[(self.tr('图片','Image'),'*.png *.jpg *.jpeg *.bmp')])
        if not filename:return
        if not messagebox.askokcancel(self.tr('底图校准','Map calibration'),self.tr(
            '必须是北朝上的完整地图，四边对应本图边界。不接受裁剪图；图片不会作为战术数据分发。',
            'Use a north-up, uncropped full-map image matching arena bounds. Image bytes are not included in exported tactics.'),parent=self.root):return
        try:
            from PIL import Image
            with Image.open(filename) as image:
                if image.width>4096 or image.height>4096:raise ValueError(self.tr('图片尺寸过大','Image too large'))
                self.background=image.convert('RGB')
            self.image_cache[self.map_name]=(self.background,self.tr('手动导入底图：需自行确认边界对应','Imported image: confirm arena alignment'))
            self.map_status.config(text=self.image_cache[self.map_name][1]);self.redraw()
        except Exception as e:self.error(e)

    def save(self,apply=False):
        if self.builtin:
            if apply:
                try:
                    self.store.save(contract.default_profile(),True)
                    self.status.set(self.tr('已应用默认配置，下一局生效。','Default applied for the next battle.'))
                except Exception as e:self.error(e)
            return
        if self.wait_edit and self.selected_wait is not None and self.update_wait_time() is False:return
        if self._selected() is not None and not self.update_properties():return
        try:
            doc=self.store.save(self.document,apply,previous_name=self.saved_name)
            self.document=doc;self.original=copy.deepcopy(doc)
            self.saved_name=doc['name'];self.unsaved_new=False;self.profile_name.set(doc['name'])
            self._refresh_profiles();self._refresh_items();self._refresh_lock()
            self.status.set(self.tr('已保存，下一局读取当前应用方案的最新文件。','Saved. Next battle reads the latest applied profile file.'))
            if apply:self.log('BOT TACTICS applied '+contract.digest(doc)[:12])
        except Exception as e:self.error(e)

    def discard_prompt(self):
        return not self.dirty() or messagebox.askyesno(self.tr('未保存','Unsaved changes'),self.tr('放弃未保存的草稿？','Discard unsaved draft?'),parent=self.root)

    def adopt(self,doc,*,unsaved=False,imported=False):
        self.document=copy.deepcopy(doc);self.original=copy.deepcopy(doc);self.profile_name.set(doc['name'])
        self.saved_name=None if unsaved else doc['name'];self.unsaved_new=unsaved
        self.builtin=doc['name']=='Default' and not imported
        self.histories={key:([],[]) for key in ('behavior','maps')}
        self.selection=None;self.selected_point=None;self.selected_wait=None;self.wait_edit=False;self.drag=None
        self.wait_edit_var.set(False);self.wait_seconds.set('60');self.wait_heading.set('')
        self._ammo_identity=();self._ammo_preview=None
        self._wait_add_at_parent=False;self._wait_parent_cleared=False
        for key,var in self.rule_vars.items():var.set('0' if key=='team' else 'all' if key=='class_tag' else '')
        for var in self.ammo_vars:var.set('')
        for var in self.item_vars.values():var.set('')
        self._refresh_equipment_choices();self._refresh_rules();self._refresh_items();self._refresh_lock()
        self._refresh_profiles()
        self.status.set(self.tr('尚未保存。','Unsaved changes.') if unsaved else self.tr('已打开方案，当前应用方案未改变。','Profile opened; applied selection unchanged.'))

    def open_profile(self,event=None):
        name=self.profile_name.get()
        if name==self.document['name']:return
        self.profile_name.set(self.document['name'])
        if not self.discard_prompt():return
        try:
            doc=self.store.read(name)
            self.adopt(doc)
        except Exception as e:self.error(e)

    def new_profile(self):
        if not self.discard_prompt():return
        name=simpledialog.askstring(self.tr('新建方案','New profile'),self.tr('方案名称','Profile name'),
                                    initialvalue=self.tr('新方案','New profile'),parent=self.root)
        if name is None:return
        try:
            name=self.store.check_name(name.strip())
            self.adopt(contract.default_profile(name),unsaved=True)
        except Exception as e:self.error(e)

    def rename_profile(self):
        if self.builtin:return
        name=simpledialog.askstring(self.tr('重命名','Rename'),self.tr('方案名称','Profile name'),
                                    initialvalue=self.document['name'],parent=self.root)
        if name is None:return
        try:
            name=contract._text(name.strip(),48)
            self.store.check_name(name,self.saved_name)
            if name!=self.document['name']:
                self.document['name']=name;self.profile_name.set(name);self._refresh_profiles();self.mark()
        except Exception as e:self.error(e)

    def delete_profile(self):
        if self.builtin:return
        try:
            active=self.store.active()['name']==self.saved_name
            text=self.tr('删除当前方案并丢弃未保存修改？','Delete this profile and discard unsaved changes?')
            if active:text+='\n'+self.tr('下一局将恢复 Default，当前战斗不变。','Next battle will use Default. The current battle is unchanged.')
            if not messagebox.askyesno(self.tr('删除方案','Delete profile'),text,parent=self.root):return
            if self.saved_name is not None:self.store.delete(self.saved_name)
            self.adopt(contract.default_profile())
        except Exception as e:self.error(e)

    def import_profile(self):
        filename=filedialog.askopenfilename(parent=self.root,filetypes=[(self.tr('Bot 战术配置','Bot tactics'),'*.json')])
        if filename and self.discard_prompt():
            try:
                doc=self.store.import_file(filename)
                if any(n.casefold()==doc['name'].casefold() for n in self.store.names()):
                    name=simpledialog.askstring(self.tr('名称已存在','Name already exists'),
                        self.tr('导入方案名称已存在，请输入其他名称。','Choose another name for the imported profile.'),
                        initialvalue=doc['name'],parent=self.root)
                    if name is None:return
                    doc['name']=name.strip()
                self.store.check_name(doc['name'])
                self.adopt(doc,unsaved=True,imported=True)
            except Exception as e:self.error(e)

    def export_profile(self):
        if self.dirty():
            messagebox.showinfo(self.tr('需要保存','Save required'),self.tr('请先保存后再导出。','Save the profile before exporting.'),parent=self.root)
            return
        filename=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',filetypes=[(self.tr('Bot 战术配置','Bot tactics'),'*.json')])
        if filename:
            try:
                self.store.export(self.document,filename)
                self.status.set(self.tr('方案已导出，不包含游戏资源或账户数据。','Exported configuration; no game artwork or account data.'))
            except Exception as e:self.error(e)

    def error(self,error):
        text=str(error)
        if text.startswith('Route endpoints are fixed: '):text=self.tr('路线首尾固定，请检查路线：','Route endpoints are fixed; check the route: ')+text.split(': ',1)[1]
        if text.startswith('Route symmetry is unavailable on this map: '):text=self.tr('此地图不支持路线对称：','Route symmetry is unavailable on this map: ')+text.split(': ',1)[1]
        if text.startswith('Name already exists: '):text=self.tr('方案名称已存在，请使用其他名称：','Profile name already exists; choose another name: ')+text.split(': ',1)[1]
        if text=='Stock development only allows no equipment':text=self.tr('白板研发仅允许无配件；请明确选择无配件，或改用中间／完全体研发。','Stock development only allows no equipment. Select none or intermediate/full development.')
        messagebox.showerror(self.tr('Bot 配置','Bot configuration'),text,parent=self.root)

    def close(self):
        if self.discard_prompt():self.root.destroy()


def _editable_handler(function):
    import functools
    @functools.wraps(function)
    def invoke(self,*args,**kwargs):
        if self.builtin:return False
        return function(self,*args,**kwargs)
    return invoke

for _method in ('undo','redo','save_rule','delete_rule','change_symmetry',
        'new_route','new_position','duplicate_item',
        'delete_item','reset_builtin','update_properties','delete_point','insert_point',
        'toggle_hold','change_wait_edit','edit_point_condition','update_wait_time',
        'delete_wait_point','delete_selected_point','_press_wait','press','motion','release'):
    setattr(BotTacticsEditor,_method,_editable_handler(getattr(BotTacticsEditor,_method)))


def open_editor(parent,game_root='',language='zh',log=None,lineup=None):
    return BotTacticsEditor(parent,game_root,language=language,log=log,lineup=lineup)
