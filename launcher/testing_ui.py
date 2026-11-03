"""Launcher-owned test choices shared by normal and diagnostic startup."""
import os
import json
import tempfile

try:
    from . import ui_layout
except ImportError:
    import ui_layout

SCENES = (
    ('normal', 'Normal battle', '正常对局'),
    ('equipment', 'Equipment and crew test', '配件与成员测试'),
    ('drop', 'Shot-triggered drop test', '开炮触发掉车测试'),
    ('governor', 'Bot governor driving test', 'BOT调速器行驶测试'),
    ('equipment_baseline', 'Equipment control: baseline', '装备对照：无加成'),
    ('equipment_matrix', 'Equipment control: varied fittings', '装备对照：不同配置'),
    ('rewards', 'Earnings test: stationary targets', '收益测试：静止目标'),
)
ENV_KEYS = ('WOT_OFFLINE_EQUIPMENT_TEST', 'WOT_OFFLINE_ROOF_CRUSH_TEST',
            'WOT_OFFLINE_ROOF_SHOT_DROP', 'WOT_OFFLINE_COLLISION_DIAGNOSTICS',
            'WOT_OFFLINE_PLAYER_AUTOCONTROL')


def environment(settings, diagnostics=False, single=True):
    """Always replace stale test flags; fixtures are single-player only."""
    settings = settings if isinstance(settings, dict) else {}
    scene = settings.get('scene', 'normal') if single else 'normal'
    if scene not in {row[0] for row in SCENES}:
        scene = 'normal'
    result = dict.fromkeys(ENV_KEYS, '0')
    result['WOT_OFFLINE_EQUIPMENT_TEST'] = {
        'equipment': '1', 'governor': '2', 'equipment_baseline': '3',
        'equipment_matrix': '4', 'rewards': '3'}.get(scene, '0')
    result['WOT_OFFLINE_ROOF_CRUSH_TEST'] = '1' if scene == 'drop' else '0'
    result['WOT_OFFLINE_ROOF_SHOT_DROP'] = result['WOT_OFFLINE_ROOF_CRUSH_TEST']
    result['WOT_OFFLINE_COLLISION_DIAGNOSTICS'] = '1' if settings.get('collision') else '0'
    result['WOT_OFFLINE_DIAGNOSTICS'] = '1' if (
        diagnostics or settings.get('logs') or settings.get('collision') or settings.get('control') or scene != 'normal') else '0'
    if settings.get('control'):
        result['WOT_OFFLINE_PLAYER_AUTOCONTROL'] = ','.join(
            key for key in ('drive', 'fire', 'consumables') if settings.get(key)) or 'enabled'
    return result


class TestingPanel:
    def __init__(self, app, parent, settings):
        self.app = app
        self.command_path = None
        self.control_window = None
        tk = app._tk
        canvas = tk.Canvas(parent, height=220, highlightthickness=0)
        scrollbar = app._ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        content = tk.Frame(canvas)
        item = canvas.create_window(0, 0, anchor='nw', window=content)
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        self.canvas, self.content = canvas, content
        parent = content
        self.vars = {key: tk.BooleanVar(value=bool(settings.get(key, False)))
                     for key in ('logs', 'collision', 'control', 'drive', 'fire', 'consumables')}
        for key in ('drive', 'fire', 'consumables'):
            self.vars[key].set(bool(settings.get(key, True)))
        self.scene = tk.StringVar()
        self.scene_id = settings.get('scene', 'normal')
        self.labels = []
        self.sections = []
        def section(en, zh):
            outer, body, title = ui_layout.section(tk, parent)
            outer.pack(fill='x', pady=(0, ui_layout.GAP))
            self.labels.append((title, en, zh))
            return body
        def check(body, key, en, zh):
            widget = tk.Checkbutton(body, variable=self.vars[key], anchor='w',
                                    command=self._control_changed if key == 'control' else app._save_settings)
            widget.pack(fill='x')
            self.labels.append((widget, en, zh))
        def help_text(body, en, zh):
            widget = tk.Label(body, anchor='w', justify='left', wraplength=620)
            widget.pack(fill='x', pady=(ui_layout.GAP, 0))
            self.labels.append((widget, en, zh))
        body = section('Diagnostic logs', '日志收集')
        check(body, 'logs', 'Collect detailed diagnostic logs', '收集详细诊断日志')
        check(body, 'collision', 'Collect detailed collision logs', '收集详细碰撞日志')
        help_text(body, 'Changes apply on the next launch. Detailed logs can be large; export them with the error report button.',
                  '设置在下次启动时生效。详细日志可能较大；测试后可通过“一键汇报错误”导出。')
        body = section('Test scene', '测试场景')
        self.scene_box = app._ttk.Combobox(body, state='readonly', textvariable=self.scene)
        self.scene_box.pack(fill='x')
        self.scene_box.bind('<<ComboboxSelected>>', self._select)
        help_text(body, 'Use the normal Start button. Fixtures select their own map and Bot roster in single player; network play uses a normal battle.',
                  '选择后使用正常启动按钮。专用场景在单人模式指定地图及BOT阵容；联网模式仍为正常对局。')
        body = section('Player automatic control', '玩家自动控制')
        row = tk.Frame(body)
        row.pack(fill='x')
        for key, en, zh in (('drive', 'Automatic driving', '自动驾驶'),
                            ('fire', 'Automatic aiming and fire', '自动瞄准与开火'),
                            ('consumables', 'Automatic consumables', '自动使用给养')):
            widget = tk.Checkbutton(row, variable=self.vars[key], command=app._save_settings)
            widget.pack(side='left', fill='x', expand=True)
            self.labels.append((widget, en, zh))
        check(body, 'control', 'Enable the ` key and mouse control panel', '启用·键与鼠标控制面板')
        help_text(body, 'Each battle starts under manual control. Press ` to take over or stop; native local messages show the state. Your own loadout remains in use. Chat, menus and dialogs do not toggle control.',
                  '每局默认手动控制。按·键接管或停止，原生本地消息提示状态；保留玩家自己的配装。聊天、菜单及弹窗中不触发切换。')
        help_text(body, 'Driving owns the hull only; aiming/fire owns target lock and shots. Unchecked features stay manual. Changes apply on the next game launch.',
                  '自动驾驶只接管车体；自动瞄准与开火接管炮塔锁定及射击。未勾选的功能保留手动操作；更改在下次启动游戏时生效。')
        button = tk.Button(body, command=self.open_controls)
        button.pack(fill='x', pady=(ui_layout.GAP, 0))
        self.labels.append((button, 'Open mouse control panel', '打开鼠标控制面板'))
        self.control_button = button
        self._refresh_controls()
        self.translate()
        def wheel(event):
            canvas.yview_scroll(-int(event.delta / 120), 'units')
            return 'break'
        for widget in [content, canvas, self.scene_box] + [row[0] for row in self.labels]:
            widget.bind('<MouseWheel>', wheel)

    def translate(self):
        chinese = self.app.language == 'zh'
        for widget, en, zh in self.labels:
            widget.config(text=zh if chinese else en)
        self.scene_box.config(values=[row[2 if chinese else 1] for row in SCENES])
        index = next((i for i, row in enumerate(SCENES) if row[0] == self.scene_id), 0)
        self.scene.set(SCENES[index][2 if chinese else 1])

    def _select(self, unused=None):
        self.scene_id = next(row[0] for row in SCENES if self.scene.get() in row[1:])
        self.app._save_settings()

    def settings(self):
        return dict(scene=self.scene_id, **{key: bool(value.get()) for key, value in self.vars.items()})

    def apply(self, single=True):
        os.environ.update(environment(self.settings(),
            diagnostics=getattr(self.app, '_diagnostic_entry', False), single=single))
        self.command_path = None
        os.environ.pop('WOT_OFFLINE_TEST_CONTROL_FILE', None)
        if self.vars['control'].get():
            fd, self.command_path = tempfile.mkstemp(prefix='wot-player-control-', suffix='.jsonl')
            os.close(fd)
            os.environ['WOT_OFFLINE_TEST_CONTROL_FILE'] = self.command_path

    def send(self, action, **fields):
        if not self.command_path:
            self.app._log('Player test control is available after starting with automatic control enabled.')
            return False
        with open(self.command_path, 'a', encoding='utf8') as stream:
            stream.write(json.dumps(dict(action=action, **fields)) + '\n')
        return True

    def _refresh_controls(self):
        enabled = self.vars['control'].get()
        self.control_button.config(state='normal' if enabled else 'disabled')
        if not enabled:
            self._close_controls()

    def _control_changed(self):
        self._refresh_controls()
        self.app._save_settings()

    def _close_controls(self):
        window, self.control_window = self.control_window, None
        if window is not None:
            try:
                if self.command_path:
                    self.send('stop')
            finally:
                window.destroy()

    def open_controls(self):
        if not self.vars['control'].get():
            return
        if self.control_window is not None:
            self.control_window.lift()
            return
        tk = self.app._tk
        window = self.control_window = tk.Toplevel(self.app.root)
        window.title('玩家测试控制' if self.app.language == 'zh' else 'Player test control')
        window.geometry('500x240')
        body = tk.Frame(window, padx=ui_layout.MARGIN, pady=ui_layout.MARGIN)
        body.pack(fill='both', expand=True)
        zh = self.app.language == 'zh'
        tk.Label(body, text=('定时行驶每次持续1秒；停止会取消接管和排队射击。\n只在已启用测试控制的当前战斗中生效。' if zh else
            'Timed driving lasts one second. Stop clears takeover and queued fire.\nOnly applies to the current battle with test control enabled.'),
            anchor='w', justify='left').pack(fill='x', pady=(0, ui_layout.GAP))
        rows = (
            (('接管／关闭', 'Toggle', lambda: self.send('toggle')),
             ('停止', 'Stop', lambda: self.send('stop')),
             ('开火', 'Fire', lambda: self.send('fire'))),
            (('前进1秒', 'Forward 1 s', lambda: self.send('drive', forward=1)),
             ('后退1秒', 'Reverse 1 s', lambda: self.send('drive', forward=-1))),
            (('左转1秒', 'Left 1 s', lambda: self.send('drive', turn=-1)),
             ('右转1秒', 'Right 1 s', lambda: self.send('drive', turn=1))))
        for buttons in rows:
            row = tk.Frame(body)
            row.pack(fill='x', pady=(0, ui_layout.GAP))
            for chinese, english, command in buttons:
                tk.Button(row, text=chinese if zh else english, command=command).pack(side='left', fill='x', expand=True)
        window.protocol('WM_DELETE_WINDOW', self._close_controls)
        ui_layout.polish(window)
