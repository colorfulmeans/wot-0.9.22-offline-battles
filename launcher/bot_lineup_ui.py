"""Draft editor for sparse, explicitly enabled Bot lineup slots."""
from __future__ import annotations
import copy
from collections import Counter
try:
    from . import bot_lineup_profiles as profiles, vehicle_overlays, nation_choices
except ImportError:
    import bot_lineup_profiles as profiles
    import vehicle_overlays, nation_choices

SKILL_CHOICES = ((None, 'Random (mixed distribution)'), ('rookie', 'Rookie'),
                 ('regular', 'Regular'), ('veteran', 'Veteran'), ('elite', 'Elite'))
CLASSES = ((None, 'All'), ('lightTank', 'Light tank'), ('mediumTank', 'Medium tank'),
           ('heavyTank', 'Heavy tank'), ('AT-SPG', 'Tank destroyer'), ('SPG', 'SPG'))
ZH = {
    'Exact Bot lineup: %s': '自定义 Bot 阵容：%s', 'Team 1 Bot': '队伍 1 Bot',
    'Team 2 Bot': '队伍 2 Bot', 'Nation': '国家', 'Type': '类型', 'Vehicle': '车辆',
    'Difficulty': '难度', 'All': '全部', 'Light tank': '轻坦', 'Medium tank': '中坦',
    'Heavy tank': '重坦', 'Tank destroyer': '坦歼', 'SPG': '自行火炮',
    'Random vehicle': '随机车辆', 'Empty / do not participate': '空槽／不参战',
    'Clear all slots in this team': '清空本队全部槽位',
    'Individual slot settings': '各槽位独立设置',
    'Random (mixed distribution)': '随机（混合分布）', 'Rookie': '新手',
    'Regular': '普通', 'Veteran': '老兵', 'Elite': '精英', 'Save': '保存', 'Close': '关闭',
    'Save and close': '保存并关闭', 'Discard changes': '放弃修改', 'Cancel': '取消',
    'Unsaved changes': '尚未保存的修改', 'Save changes before closing?': '关闭前是否保存修改？',
    'Lineup saved.': '阵容保存成功。', 'Save failed: %s': '保存失败：%s',
    'No vehicles match this slot.': '没有符合此槽位筛选条件的车辆。',
    'Unavailable vehicle: %s': '车辆不可用：%s',
    'The lineup could not be saved.': '无法保存阵容。',
    'This lineup changed in another editor; reopen it before saving.': '此阵容已在另一个窗口中修改，请重新打开后再保存。',
    'Could not read vehicles: %s': '无法读取车辆列表：%s',
    'Team sizes: %d / %d': '队伍人数：%d／%d',
    'China': '中国', 'USSR': '苏联', 'USA': '美国', 'Germany': '德国', 'Czech': '捷克',
    'France': '法国', 'UK': '英国', 'Japan': '日本', 'Poland': '波兰', 'Sweden': '瑞典',
    'Empty teams cannot start a battle.': '队伍为空时不能开战。',
    'Slots keep their numbers. Humans replace enabled slots from first to last. Random difficulty is drawn once per Bot per round from the mixed distribution. Explicit tactics may override difficulty. Changes apply after saving and restarting the room.':
    '槽位编号保持不变。真人按有效槽位顺序替换 Bot。随机难度每局按混合分布为各 Bot 生成一次；明确的战术配置可覆盖难度。保存并重新开启房间后生效。',
}
RANDOM = '__random__'
CLEAR = '__clear__'
INDIVIDUAL = '__individual__'


def _skill_label(skill):
    return next((label for value, label in SKILL_CHOICES if value == skill), SKILL_CHOICES[0][1])


class BotLineupEditorWindow:
    def __init__(self, parent, game_root, profile_name, store, on_save,
                 tk_module, ttk_module, messagebox_module, log=None, language='zh'):
        self._tk, self._ttk, self._messagebox = tk_module, ttk_module, messagebox_module
        self._game_root, self._profile_name = game_root, profile_name
        self._store, self._on_save = copy.deepcopy(store), on_save
        self.language, self._log = language, log or (lambda unused: None)
        self._rows, self._bulk, self._choices = {}, {}, []
        self._bulk_states = {1: {}, 2: {}}
        self._parent = parent
        self._draft = profiles.runtime_assignments(store, profile_name)
        self._original = copy.deepcopy(self._draft)
        self._dirty = False
        self._catalog_ready = False
        self._build(parent)
        self._load_choices()

    def _t(self, text):
        return ZH.get(text, text) if self.language == 'zh' else text

    def _build(self, parent):
        tk = self._tk
        self.root = tk.Toplevel(parent)
        self.root.title(self._t('Exact Bot lineup: %s') % self._profile_name)
        self.root.protocol('WM_DELETE_WINDOW', self._close)
        frame = self._ttk.Frame(self.root, padding=12)
        frame.pack(fill='both', expand=True)
        note = 'Slots keep their numbers. Humans replace enabled slots from first to last. Random difficulty is drawn once per Bot per round from the mixed distribution. Explicit tactics may override difficulty. Changes apply after saving and restarting the room.'
        self._ttk.Label(frame, text=self._t(note), wraplength=1180).grid(row=0, column=0, columnspan=10, sticky='w', pady=(0, 8))
        for team in (1, 2):
            offset = (team - 1) * 5
            for column, text in enumerate(('Team %d Bot' % team, 'Nation', 'Type', 'Vehicle', 'Difficulty')):
                self._ttk.Label(frame, text=self._t(text)).grid(row=1, column=offset+column, sticky='w', padx=3)
            self._make_row(frame, 2, team, None, offset)
            for slot in range(15):
                self._make_row(frame, slot+3, team, slot, offset)
            frame.columnconfigure(offset+3, weight=1)
        self.status = tk.StringVar(value='')
        self._ttk.Label(frame, textvariable=self.status).grid(row=18, column=0, columnspan=10, sticky='w', pady=8)
        self._ttk.Button(frame, text=self._t('Save'), command=self._save).grid(row=19, column=0, columnspan=5, sticky='we', padx=(0, 4))
        self._ttk.Button(frame, text=self._t('Close'), command=self._close).grid(row=19, column=5, columnspan=5, sticky='we', padx=(4, 0))

    def _make_row(self, frame, gridrow, team, slot, offset):
        self._ttk.Label(frame, text=self._t('All') if slot is None else str(slot+1)).grid(row=gridrow, column=offset, padx=3)
        row = {}
        for column, field in enumerate(('nation', 'vehicle_class', 'vehicle', 'skill'), 1):
            row[field] = self._tk.StringVar(value='')
            width = {'nation': 20, 'vehicle_class': 20, 'vehicle': 28, 'skill': 27}[field]
            box = self._ttk.Combobox(frame, textvariable=row[field], state='readonly', width=width)
            box.grid(row=gridrow, column=offset+column, sticky='we', padx=3, pady=1)
            row[field+'_box'] = box
            box.bind('<<ComboboxSelected>>', lambda event, t=team, s=slot, f=field: self._changed(t, s, f))
        (self._bulk if slot is None else self._rows)[team if slot is None else (team, slot)] = row

    def _load_choices(self):
        try:
            self._choices = profiles.eligible_vehicle_choices(vehicle_overlays.list_vehicle_choices(self._game_root))
            self._choices.sort(key=lambda r: (-r.get('level', 0), r['nation'], r['vehicle']))
            counts = Counter((r['nation'], r['label']) for r in self._choices)
            for choice in self._choices:
                caption = '%s — %d' % (choice['label'], choice.get('level', 0))
                if counts[(choice['nation'], choice['label'])] > 1:
                    caption += ' [%s]' % choice['vehicle']
                choice['caption'] = caption
            self._catalog_ready = True
            self._render()
        except (profiles.BotLineupProfileError, vehicle_overlays.VehicleOverlayError) as error:
            self.status.set(self._t('Could not read vehicles: %s') % error)

    def _options(self, values):
        return [(value, self._t(label)) for value, label in values]

    def _populate(self, row, field, options, value):
        row[field+'_options'] = options
        row[field+'_box'].configure(values=tuple(label for unused, label in options))
        row[field].set(next((label for actual, label in options if actual == value), ''))

    def _read(self, row, field):
        label = row[field].get()
        return next((value for value, caption in row[field+'_options'] if caption == label), None)

    def _pool(self, state):
        return [c for c in self._choices if
                (not state.get('nation') or c['nation'] == state['nation']) and
                (not state.get('vehicle_class') or c.get('vehicleClass') == state['vehicle_class'])]

    def _render_row(self, row, state, bulk=False):
        prefix = [(INDIVIDUAL, 'Individual slot settings')] if bulk else []
        nations = [(None, 'All')] + [(n, nation_choices.EN_NAMES[n]) for n in nation_choices.ordered(c['nation'] for c in self._choices)]
        self._populate(row, 'nation', self._options(prefix+nations), state.get('nation', INDIVIDUAL if bulk else None))
        self._populate(row, 'vehicle_class', self._options(prefix+list(CLASSES)), state.get('vehicle_class', INDIVIDUAL if bulk else None))
        vehicles = ([(CLEAR, self._t('Clear all slots in this team')), (INDIVIDUAL, self._t('Individual slot settings'))] if bulk else [(None, self._t('Empty / do not participate'))])
        vehicles += [(RANDOM, self._t('Random vehicle'))] + [(c['type_name'], c['caption']) for c in self._pool(state)]
        if state.get('vehicle') and not any(v == state['vehicle'] for v, label in vehicles):
            vehicles.append((state['vehicle'], self._t('Unavailable vehicle: %s') % state['vehicle']))
        self._populate(row, 'vehicle', vehicles, state.get('vehicle', RANDOM) if state.get('enabled') else (INDIVIDUAL if bulk else None))
        self._populate(row, 'skill', self._options(prefix+list(SKILL_CHOICES)), state.get('skill', INDIVIDUAL if bulk else None))

    def _render(self):
        for state in self._draft:
            self._render_row(self._rows[(state['team'], state['slot'])], state)
        for team in (1, 2):
            self._render_row(self._bulk[team], self._bulk_states[team], True)
        self._update_status()

    def _update_status(self):
        self._dirty = self._draft != self._original
        sizes = [sum(bool(r.get('enabled')) for r in self._draft if r['team'] == t) for t in (1, 2)]
        self.status.set(self._t('Team sizes: %d / %d') % tuple(sizes))

    def _apply(self, state, field, value):
        if field == 'vehicle':
            if value in (None, CLEAR):
                state.clear()
                state['enabled'] = False
            else:
                state['enabled'] = True
                state.pop('vehicle', None)
                if value != RANDOM:
                    state['vehicle'] = value
                    choice = next(c for c in self._choices if c['type_name'] == value)
                    state['nation'] = choice['nation']
                    state['vehicle_class'] = choice.get('vehicleClass')
        elif value is None:
            state.pop(field, None)
        else:
            state[field] = value
        if field in ('nation', 'vehicle_class') and state.get('vehicle'):
            if not any(c['type_name'] == state['vehicle'] for c in self._pool(state)):
                state.pop('vehicle', None)
                state['enabled'] = False

    def _changed(self, team, slot, field):
        if not self._catalog_ready:
            return
        row = self._bulk[team] if slot is None else self._rows[(team, slot)]
        value = self._read(row, field)
        if value == INDIVIDUAL:
            return
        targets = [s for s in self._draft if s['team'] == team and (slot is None or s['slot'] == slot)]
        for state in targets:
            key = state['team'], state['slot']
            self._apply(state, field, value)
            state.update(team=key[0], slot=key[1])
        if slot is None:
            bulk_state = self._bulk_states[team]
            if value == CLEAR:
                bulk_state.clear()
            elif field == 'vehicle':
                self._apply(bulk_state, field, value)
            else:
                bulk_state[field] = value
                if field in ('nation', 'vehicle_class'):
                    bulk_state.pop('vehicle', None)
                    bulk_state.pop('enabled', None)
        else:
            self._bulk_states[team] = {}
        self._render()

    def set_language(self, language):
        if language == self.language:
            return
        old_root = self.root
        self.language = language
        self._rows, self._bulk = {}, {}
        self._build(self._parent)
        self._render()
        old_root.destroy()

    def _save(self):
        if not self._catalog_ready:
            return False
        try:
            for state in self._draft:
                pool = self._pool(state)
                if state.get('enabled') and (not pool or (state.get('vehicle') and
                        not any(c['type_name'] == state['vehicle'] for c in pool))):
                    raise ValueError(self._t('No vehicles match this slot.'))
            store = profiles.replace_assignments(self._store, self._profile_name, self._draft)
            if self._on_save(store) is False:
                raise IOError(self._t('The lineup could not be saved.'))
            self._store = store
            self._draft = profiles.runtime_assignments(store, self._profile_name)
            self._original = copy.deepcopy(self._draft)
            self._render()
            self._messagebox.showinfo(self._t('Save'), self._t('Lineup saved.'), parent=self.root)
            return True
        except (OSError, ValueError) as error:
            self._messagebox.showerror(self._t('Save'), self._t('Save failed: %s') % self._t(str(error)), parent=self.root)
            return False

    def _close(self):
        if not self._dirty:
            self.root.destroy()
            return
        dialog = self._tk.Toplevel(self.root)
        dialog.title(self._t('Unsaved changes'))
        dialog.transient(self.root)
        self._ttk.Label(dialog, text=self._t('Save changes before closing?'), padding=12).pack()
        buttons = self._ttk.Frame(dialog, padding=(12, 0, 12, 12))
        buttons.pack()
        def choose(action):
            dialog.destroy()
            if action == 'discard' or (action == 'save' and self._save()):
                self.root.destroy()
        for text, action in (('Save and close', 'save'), ('Discard changes', 'discard'), ('Cancel', 'cancel')):
            self._ttk.Button(buttons, text=self._t(text), width=0,
                             command=lambda a=action: choose(a)).pack(side='left', padx=4, ipadx=8, ipady=3)
        dialog.grab_set()


def open_bot_lineup_editor(parent, game_root, profile_name, store, on_save,
                           log=None, tk_module=None, ttk_module=None,
                           messagebox_module=None, language='zh'):
    if tk_module is None or ttk_module is None:
        import tkinter as tk
        from tkinter import messagebox, ttk
        tk_module, ttk_module, messagebox_module = tk, ttk, messagebox
    return BotLineupEditorWindow(parent, game_root, profile_name, store, on_save,
        tk_module, ttk_module, messagebox_module, log=log, language=language)
