"""Launcher-owned test choices shared by normal and diagnostic startup."""
import os
import math
import tempfile
import uuid

try:
    from . import ui_layout, player_control_transport
except ImportError:
    import ui_layout
    import player_control_transport

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


ACTION_LABELS = {
    'start': ('Start takeover', '开始接管'), 'stop': ('Restore manual control', '恢复手动'),
    'halt': ('Force stop', '强制停车'), 'attack': ('Attack', '进攻'),
    'return_base': ('Return to base', '返回基地'), 'defend_base': ('Defend base', '守卫基地'),
    'hold_position': ('Hold position', '原地驻守'), 'capture_base': ('Capture base', '占领基地'),
    'drive': ('Timed driving', '定时行驶'), 'fire': ('Fire once', '开火一次'),
    'status': ('Refresh status', '刷新状态'),
}


class TestingPanel:
    def __init__(self, app, parent, settings):
        self.app = app
        self.command_path = None
        self.result_path = None
        self.session_id = None
        self.transport = None
        self.control_window = None
        self.control_labels = []
        self.action_buttons = []
        self.status_labels = {}
        self._poll_job = None
        self.notice = None
        self.last_command_id = None
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
        features = (
            ('drive', 'Automatic driving', '自动驾驶'),
            ('fire', 'Automatic aiming and fire', '自动瞄准与开火'),
            ('consumables', 'Automatic consumables', '自动使用给养'),
        )
        for column, (key, en, zh) in enumerate(features):
            row.grid_columnconfigure(column, weight=1, uniform='features')
            widget = tk.Checkbutton(row, variable=self.vars[key], anchor='w',
                                    command=app._save_settings)
            widget.grid(row=0, column=column, sticky='ew')
            self.labels.append((widget, en, zh))
        check(body, 'control', 'Enable the ` key and mouse control panel', '启用·键与鼠标控制面板')
        help_text(body, 'Each battle starts under manual control. Press ` to take over or stop; native local messages show the state. Your own loadout remains in use. Chat, menus and dialogs do not toggle control.',
                  '每局默认手动控制。按·键接管或停止，原生本地消息提示状态；保留玩家自己的配装。聊天、菜单及弹窗中不触发切换。')
        help_text(body, 'Driving owns the hull only; aiming/fire owns target lock and shots. Unchecked features stay manual. Changes apply on the next game launch.',
                  '自动驾驶只接管车体；自动瞄准与开火接管炮塔锁定及射击。未勾选的功能保留手动操作；更改在下次启动游戏时生效。')
        button = tk.Button(body, command=self.open_controls)
        button.pack(fill='x', pady=(ui_layout.GAP, 0))
        self.labels.append((button, 'Open player control panel', '打开玩家控制面板'))
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
        if self.control_window is not None:
            self.control_window.title('玩家测试控制' if chinese else 'Player test control')
            for widget, en, zh in self.control_labels:
                widget.config(text=zh if chinese else en)
            self._update_control_view(poll=False)

    def _select(self, unused=None):
        self.scene_id = next(row[0] for row in SCENES if self.scene.get() in row[1:])
        self.app._save_settings()

    def settings(self):
        return dict(scene=self.scene_id, **{key: bool(value.get()) for key, value in self.vars.items()})

    def apply(self, single=True):
        os.environ.update(environment(self.settings(),
            diagnostics=getattr(self.app, '_diagnostic_entry', False), single=single))
        self.command_path = self.result_path = self.session_id = None
        self.transport = None
        self.notice = self.last_command_id = None
        for key in (player_control_transport.COMMAND_ENV,
                    player_control_transport.RESULT_ENV,
                    player_control_transport.SESSION_ENV):
            os.environ.pop(key, None)
        if self.vars['control'].get():
            paths = []
            try:
                for suffix in ('commands', 'results'):
                    fd, path = tempfile.mkstemp(prefix='wot-player-control-' + suffix + '-', suffix='.jsonl')
                    os.close(fd)
                    paths.append(path)
            except OSError:
                for path in paths:
                    os.unlink(path)
                raise
            self.command_path, self.result_path = paths
            self.session_id = uuid.uuid4().hex
            self.transport = player_control_transport.PlayerControlTransport(
                self.command_path, self.result_path, self.session_id)
            os.environ.update({player_control_transport.COMMAND_ENV: self.command_path,
                               player_control_transport.RESULT_ENV: self.result_path,
                               player_control_transport.SESSION_ENV: self.session_id})
        self._update_control_view(poll=False)

    def send(self, action, **fields):
        if not self.transport or not self.command_path:
            self.notice = 'control_not_started'
            self.app._log('Player test control is available after starting with automatic control enabled.')
            self._update_control_view(poll=False)
            return False
        if action != 'stop' and not self.vars['control'].get():
            self.notice = 'control_disabled'
            self._update_control_view(poll=False)
            return False
        timeout = (600.0 if action in ('attack', 'capture_base') else
                   180.0 if action in ('return_base', 'defend_base', 'hold_position') else 15.0)
        command_id = self.transport.send(action, args=fields, timeout_seconds=timeout, replace=True)
        self.last_command_id = command_id
        self.notice = self.transport.error if command_id is None else None
        if command_id is None:
            self.app._log('Player test control %s was not submitted: %s%s' % (
                action, self.transport.error,
                ': ' + self.transport.error_detail if self.transport.error_detail else ''))
        self._update_control_view(poll=False)
        return command_id is not None

    def _refresh_controls(self):
        enabled = self.vars['control'].get()
        self.control_button.config(state='normal' if enabled else 'disabled')
        if not enabled:
            self._close_controls(send_stop=False)

    def _control_changed(self):
        if not self.vars['control'].get() and self.command_path:
            # The client can be active even if this window was never opened.
            self.send('stop')
        self._refresh_controls()
        self.app._save_settings()

    def _close_controls(self, send_stop=True):
        window, self.control_window = self.control_window, None
        if window is not None:
            try:
                if self._poll_job is not None:
                    try:
                        window.after_cancel(self._poll_job)
                    except Exception:
                        pass
                self._poll_job = None
                if send_stop and self.command_path:
                    self.send('stop')
            finally:
                self.control_labels = []
                self.action_buttons = []
                self.status_labels = {}
                window.destroy()

    def _text(self, en, zh):
        return zh if self.app.language == 'zh' else en

    def _reason_text(self, reason):
        descriptions = {
            'control_not_started': ('Start the game with test control enabled.', '请启用测试控制后启动游戏。'),
            'control_disabled': ('Test control is disabled.', '测试控制已禁用。'),
            'waiting_for_battle': ('Waiting for the current battle and player identity.', '等待当前对局及玩家身份。'),
            'waiting_for_status': ('Waiting for a complete client status update.', '等待完整的客户端状态。'),
            'battle_not_live': ('The player is not in a live battle.', '玩家当前不在可控制的战斗中。'),
            'status_stale': ('Client status expired; waiting for a fresh update.', '客户端状态已过期，等待新的状态。'),
            'result_read_failed': ('Cannot read client responses.', '无法读取客户端回执。'),
            'command_write_failed': ('Cannot send the command.', '命令发送失败。'),
            'response_timeout': ('No terminal receipt received; completion is unconfirmed.', '尚未收到结束回执，不能确认命令是否完成。'),
            'invalid_duration': ('Duration must be from 0.1 to 10 seconds.', '持续时间必须为0.1至10秒。'),
            'dead': ('The player vehicle is destroyed.', '玩家战车已被击毁。'),
            'destroyed': ('The player vehicle is destroyed.', '玩家战车已被击毁。'),
            'spectator': ('Spectator mode.', '当前为观战状态。'),
            'detached': ('The battle has ended.', '已离开战斗。'),
            'not_live': ('The player is not in a live battle.', '玩家当前不在可控制的战斗中。'),
            'no_ammo': ('No ammunition remains.', '弹药耗尽。'),
            'no_target': ('No valid target.', '没有有效目标。'),
            'timeout': ('The command timed out.', '命令超时。'),
            'replaced': ('Replaced by a new command.', '已被新命令替换。'),
            'manual': ('Manual control.', '当前为手动控制。'),
            'manual_control': ('Manual control restored.', '已恢复手动控制。'),
            'battle_exit': ('The battle has ended.', '已离开战斗。'),
            'player_dead': ('The player vehicle is destroyed.', '玩家战车已被击毁。'),
            'drive_disabled': ('Automatic driving was not enabled at launch.', '启动时未启用自动驾驶。'),
            'no_enabled_features': ('No automatic channels were enabled at launch.', '启动时未启用任何自动控制通道。'),
            'movement_busy': ('Movement is controlled by another task.', '行驶通道正由其他任务控制。'),
            'ammunition_unknown': ('Ammunition state is unavailable.', '尚不能确认弹药状态。'),
            'empty_ammo': ('No ammunition remains.', '弹药耗尽。'),
            'gun_not_ready': ('The gun is not ready to fire.', '火炮尚未准备就绪。'),
            'start_failed': ('Takeover could not start.', '无法开始接管。'),
            'command_timeout': ('The command timed out.', '命令超时。'),
            'execution_error': ('The client reported an execution error.', '客户端报告执行异常。'),
            'status_published': ('Client status refreshed.', '客户端状态已刷新。'),
            'halted': ('The hull is stopped with the brake held.', '车体已停车并保持制动。'),
            'active': ('Automatic takeover is active.', '自动接管已启用。'),
            'validated': ('The client accepted the command.', '客户端已接受命令。'),
            'arrived_and_held': ('Arrived and holding position.', '已抵达并驻守。'),
            'base_geometry_unavailable': ('No confirmed base geometry is available.', '没有可确认的基地位置和范围。'),
            'base_captured': ('The base has been captured.', '基地已被占领。'),
            'base_clear_and_held': ('The base is clear and defended.', '基地威胁已解除并保持驻守。'),
            'battle_finished_before_objective': ('The battle ended before the objective was completed.', '对局已结束，目标尚未完成。'),
            'mission_timeout': ('The task timed out.', '任务超时。'),
            'no_navigation_progress': ('The vehicle made no navigation progress.', '战车未能取得行驶进展。'),
            'inside_flag_circle': ('Inside the capture circle.', '已进入占领圈。'),
        }
        if not reason:
            return ''
        pair = descriptions.get(str(reason))
        return self._text(*pair) if pair else str(reason)

    def _describe(self, value):
        names = {
            'kind': ('Kind', '类型'), 'name': ('Task', '任务'), 'task': ('Task', '任务'),
            'phase': ('Phase', '阶段'), 'state': ('State', '状态'),
            'target_id': ('Target', '目标'), 'target': ('Target', '目标'),
            'target_position': ('Destination', '目的地'), 'reason': ('Reason', '原因'),
            'selected': ('Selected shell', '所选炮弹'), 'selected_kind': ('Selected shell', '所选炮弹'),
            'shell_kind': ('Shell', '炮弹'), 'remaining': ('Remaining', '剩余'),
            'total': ('Total shells', '剩余总弹量'), 'count': ('Shell count', '炮弹数量'),
            'total_remaining': ('Total shells', '剩余总弹量'),
            'clip': ('Clip', '弹夹'), 'clip_size': ('Clip size', '弹夹容量'),
            'clip_capacity': ('Clip capacity', '弹夹容量'), 'clip_left': ('Clip remaining', '弹夹余弹'),
            'clip_remaining': ('Clip remaining', '弹夹余弹'),
            'reloading': ('Reloading', '装填中'), 'reload_remaining': ('Reload seconds', '剩余装填秒数'),
            'reload_seconds': ('Reload seconds', '剩余装填秒数'), 'has_ammo': ('Ammunition available', '有弹药'),
            'can_fire': ('Can fire', '可开火'), 'status': ('Status', '状态'),
            'active': ('Active', '已启用'), 'position': ('Position', '位置'),
            'current': ('Selected shell count', '当前弹种余弹'), 'shell_index': ('Shell slot', '弹种槽位'),
            'empty': ('Empty', '无弹'), 'available': ('State known', '状态已确认'),
            'action': ('Task', '任务'), 'objective': ('Objective', '当前目标'),
            'progress': ('Progress', '进度'), 'holding': ('Holding', '驻守中'),
            'aligned': ('Aligned', '已瞄准'), 'distance': ('Distance', '距离'),
            'point': ('Aim point', '瞄准点'), 'mode': ('Mode', '模式'),
            'fire_clear': ('Clear firing lane', '射界畅通'), 'reload': ('Reload', '装填'),
            'dispersion': ('Dispersion', '散布'), 'speed': ('Speed', '速度'), 'yaw': ('Yaw', '朝向'),
            'reachable': ('Ballistic solution', '弹道可达'), 'arc': ('Trajectory', '弹道'),
            'velocity': ('Target velocity', '目标速度'), 'client_mode': ('Client aiming', '客户端瞄准'),
        }
        if value is None:
            return self._text('Unavailable', '暂无')
        if isinstance(value, bool):
            return self._text('Yes', '是') if value else self._text('No', '否')
        if isinstance(value, float):
            return '%.2f' % value
        if isinstance(value, dict):
            return ' · '.join('%s: %s' % (
                self._text(*names.get(key, (str(key), str(key)))),
                self._reason_text(item) if key == 'reason' else self._state_text(item)
                if key in ('action', 'objective', 'kind', 'phase', 'state', 'status') else self._describe(item))
                for key, item in value.items()) or self._text('Unavailable', '暂无')
        if isinstance(value, (list, tuple)):
            return ', '.join(self._describe(item) for item in value)
        return str(value)

    def _state_text(self, value):
        states = {
            'unknown': ('Unknown', '未知'), 'idle': ('Idle', '空闲'), 'empty': ('Empty', '无弹'),
            'shell_empty': ('Selected shell empty', '当前弹种耗尽'), 'reloading': ('Reloading', '装填中'),
            'ready': ('Ready', '就绪'), 'busy': ('Busy', '忙碌'),
            'pending': ('Pending', '待执行'), 'accepted': ('Accepted', '已接受'),
            'completed': ('Completed', '已完成'), 'failed': ('Failed', '失败'),
            'cancelled': ('Cancelled', '已取消'), 'holding': ('Holding', '驻守中'),
            'travelling': ('Travelling', '行进中'), 'attacking': ('Attacking', '进攻中'),
            'capture_travel': ('Travelling to capture', '前往占领'), 'capturing': ('Capturing', '占领中'),
            'aiming': ('Aiming', '瞄准中'), 'arriving': ('Arriving', '正在抵达'),
            'defending': ('Defending', '守卫中'), 'captured': ('Captured', '已占领'),
        }
        if isinstance(value, str):
            pair = ACTION_LABELS.get(value) or states.get(value)
            if pair:
                return self._text(*pair)
        return self._describe(value)

    def _update_control_view(self, poll=True):
        if self.transport and poll:
            self.transport.poll()
        available = bool(self.transport and self.transport.live and self.vars['control'].get())
        for button in self.action_buttons:
            can_submit = bool(self.transport and self.vars['control'].get() and
                              self.transport.can_submit(button._control_action))
            button.config(state='normal' if can_submit else 'disabled')
        if not self.status_labels:
            return
        status = self.transport.status if self.transport and self.transport.status else {}
        reason = self.transport.unavailable_reason() if self.transport else 'control_not_started'
        connection = self._text('Live client', '客户端在线') if available else self._reason_text(reason)
        if status:
            connection += self._text(' · Round %s · Player %s', ' · 对局%s · 玩家%s') % (
                status.get('round_id', '?'), status.get('player_id', '?'))
        features = status.get('features', {})
        if isinstance(features, dict):
            features = [key for key, enabled in features.items() if enabled]
        if isinstance(features, str):
            features = features.split(',')
        channel_names = {'drive': ('Driving', '驾驶'), 'fire': ('Aiming/fire', '瞄准/射击'),
                         'consumables': ('Consumables', '给养')}
        channels = ', '.join(self._text(*channel_names.get(key, (str(key), str(key))))
                             for key in features) if isinstance(features, (list, tuple)) else ''
        mode = (self._text('Forced stop', '保持停车') if status.get('halted') else
                self._text('Automatic takeover', '自动接管') if status.get('active') else
                self._text('Automatic takeover off', '自动接管未启用'))
        mission, aim = status.get('mission'), status.get('aim')
        target = next((item[key] for item in (aim, mission) if isinstance(item, dict)
                       for key in ('target_id', 'target', 'target_position') if item.get(key) is not None), None)
        target_text = self._describe(target)
        if isinstance(mission, dict) and mission.get('goal') is not None:
            target_text += self._text(' · Destination: ', ' · 目的地：') + self._describe(mission['goal'])
        if isinstance(mission, dict):
            mission = {key: mission[key] for key in ('action', 'kind', 'name', 'objective', 'phase',
                       'status', 'progress', 'reason') if key in mission}
        result = self.transport.last_result if self.transport else None
        result_text = self._text('No command submitted.', '尚未发送命令。')
        if result:
            states = {'submitted': ('Sent; awaiting acknowledgement', '已发送，等待确认'),
                      'accepted': ('Accepted; awaiting completion', '已接受，等待完成'),
                      'completed': ('Completed', '已完成'), 'rejected': ('Rejected', '已拒绝'),
                      'failed': ('Failed', '执行失败'), 'cancelled': ('Cancelled', '已取消'),
                      'unconfirmed': ('Completion unconfirmed', '完成情况未确认')}
            action = ACTION_LABELS.get(result.get('action'), (str(result.get('action', '?')), str(result.get('action', '?'))))
            result_text = '%s — %s [%s]' % (self._text(*action),
                self._text(*states.get(result.get('status'), (str(result.get('status')), str(result.get('status'))))),
                str(result.get('id', ''))[:8])
            if result.get('reason'):
                result_text += ': ' + self._reason_text(result['reason'])
        if self.notice:
            result_text += '\n' + self._reason_text(self.notice)
        values = {'connection': connection,
                  'control': mode + ' · ' + (channels or self._text('No automatic channels', '没有自动控制通道')),
                  'mission': self._describe(mission), 'target': target_text,
                  'ammo': self._describe(status.get('ammo')), 'pose': self._describe(status.get('pose')),
                  'aim': self._describe(aim), 'result': result_text}
        for key, widget in self.status_labels.items():
            widget.config(text=values[key])

    def _poll_controls(self):
        self._poll_job = None
        if self.control_window is None:
            return
        self._update_control_view()
        self._poll_job = self.control_window.after(300, self._poll_controls)

    def _send_drive(self, **axes):
        try:
            seconds = float(self.drive_seconds.get())
            if not math.isfinite(seconds) or not 0.1 <= seconds <= 10.0:
                raise ValueError('duration out of range')
        except (TypeError, ValueError):
            self.notice = 'invalid_duration'
            self._update_control_view(poll=False)
            return False
        return self.send('drive', seconds=seconds, **axes)

    def open_controls(self):
        if not self.vars['control'].get():
            return
        if self.control_window is not None:
            self.control_window.lift()
            self._update_control_view()
            return
        tk = self.app._tk
        window = self.control_window = tk.Toplevel(self.app.root)
        window.geometry('660x680')
        canvas = tk.Canvas(window, highlightthickness=0)
        scrollbar = self.app._ttk.Scrollbar(window, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        body = tk.Frame(canvas, padx=ui_layout.MARGIN, pady=ui_layout.MARGIN)
        item = canvas.create_window(0, 0, anchor='nw', window=body)
        body.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        window.bind('<MouseWheel>', lambda event: canvas.yview_scroll(-int(event.delta / 120), 'units'))
        self.control_labels, self.action_buttons, self.status_labels = [], [], {}

        def label(parent, en, zh):
            widget = tk.Label(parent, anchor='w', justify='left', wraplength=610)
            widget.pack(fill='x', pady=(0, ui_layout.GAP))
            self.control_labels.append((widget, en, zh))
            return widget

        def section(en, zh):
            outer, content, title = ui_layout.section(tk, body)
            outer.pack(fill='x', pady=(0, ui_layout.GAP))
            self.control_labels.append((title, en, zh))
            return content

        def row(parent, actions):
            frame = tk.Frame(parent)
            frame.pack(fill='x', pady=(0, ui_layout.GAP))
            for action, en, zh, callback in actions:
                button = tk.Button(frame, command=callback, state='disabled')
                button._control_action = action
                button.pack(side='left', fill='x', expand=True)
                self.control_labels.append((button, en, zh))
                self.action_buttons.append(button)

        label(body, 'Commands replace the current task. A sent command is not complete until the client confirms it. Closing this panel requests manual control.',
              '新命令替换当前任务；发送后需等待客户端执行回执。关闭面板会请求恢复手动。')
        state_body = section('Current client state', '客户端实际状态')
        for key, en, zh in (('connection', 'Connection', '连接'), ('control', 'Mode / enabled channels', '模式/已启用通道'),
                            ('mission', 'Task / phase', '任务/阶段'), ('target', 'Target / destination', '目标/目的地'),
                            ('ammo', 'Ammunition / clip / reload', '弹药/弹夹/装填'),
                            ('aim', 'Aiming / firing', '瞄准/射击'), ('pose', 'Position / movement', '位置/运动'),
                            ('result', 'Latest command receipt', '最新命令回执')):
            frame = tk.Frame(state_body)
            frame.pack(fill='x')
            heading = tk.Label(frame, width=23, anchor='nw', justify='left')
            heading.pack(side='left', anchor='n')
            self.control_labels.append((heading, en, zh))
            value = tk.Label(frame, anchor='w', justify='left', wraplength=410)
            value.pack(side='left', fill='x', expand=True)
            self.status_labels[key] = value
        control_body = section('Takeover and battle tasks', '接管与战斗任务')
        for actions in (('start', 'stop', 'halt'), ('attack', 'return_base', 'defend_base'),
                        ('hold_position', 'capture_base', 'status')):
            row(control_body, [(action, ACTION_LABELS[action][0], ACTION_LABELS[action][1],
                                lambda action=action: self.send(action)) for action in actions])
        input_body = section('Timed input and one shot', '定时输入与单次开火')
        duration_row = tk.Frame(input_body)
        duration_row.pack(fill='x', pady=(0, ui_layout.GAP))
        duration_label = tk.Label(duration_row, anchor='w')
        duration_label.pack(side='left')
        self.control_labels.append((duration_label, 'Duration (0.1–10 seconds): ', '持续时间（0.1至10秒）：'))
        self.drive_seconds = tk.StringVar(value='1.0')
        self.app._ttk.Spinbox(duration_row, from_=0.1, to=10.0, increment=0.1,
                             width=6, textvariable=self.drive_seconds).pack(side='left')
        row(input_body, [('drive', 'Forward', '前进', lambda: self._send_drive(forward=1)),
                         ('drive', 'Reverse', '后退', lambda: self._send_drive(forward=-1)),
                         ('drive', 'Left', '左转', lambda: self._send_drive(turn=-1)),
                         ('drive', 'Right', '右转', lambda: self._send_drive(turn=1))])
        row(input_body, [('fire', ACTION_LABELS['fire'][0], ACTION_LABELS['fire'][1], lambda: self.send('fire'))])
        window.protocol('WM_DELETE_WINDOW', self._close_controls)
        self.translate()
        ui_layout.polish(window)
        self._poll_controls()
