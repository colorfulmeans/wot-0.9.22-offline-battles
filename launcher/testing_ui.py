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
    'select_shell': ('Load selected shell', '装填指定弹种'), 'reload': ('Reload', '重新装填'),
    'wait_state': ('Wait for state', '等待状态'), 'assert_state': ('Assert state', '断言状态'),
    'aim_target': ('Hold aim on target', '持续瞄准目标'),
    'aim_point': ('Hold aim at point', '持续瞄准坐标'),
    'release_aim': ('Release held aim', '释放持续瞄准'),
    'use_equipment': ('Use selected equipment', '使用指定给养'),
    'set_siege': ('Set requested siege mode', '设置指定攻城模式'),
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
        check(body, 'control', 'Start automatic control at battle start', '开局自动接管')
        help_text(body, 'Checked channels take over when the battle is ready. Press ` to toggle control. Chat, menus and dialogs do not toggle it.',
                  '战斗就绪后自动接管已勾选的功能。按反引号键（`）切换接管状态。聊天、菜单及弹窗中不触发切换。')
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
                   180.0 if action in ('return_base', 'defend_base', 'hold_position', 'select_shell', 'reload') else
                   30.0 if action == 'wait_state' or action in
                       player_control_transport.AIM_ACTIONS | player_control_transport.NATIVE_ACTIONS else
                   10.0 if action == 'release_aim' else 15.0)
        command_id = self.transport.send(action, args=fields, timeout_seconds=timeout,
                                        replace=action not in player_control_transport.READ_ONLY_ACTIONS)
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
            'request_expired': ('The client received the request after its admission deadline; it was not executed.', '请求到达客户端时已超过接收期限，未执行。'),
            'invalid_expires_at': ('The request has no valid admission deadline.', '请求没有有效的接收期限。'),
            'invalid_duration': ('Duration must be from 0.1 to 10 seconds.', '持续时间必须为0.1至10秒。'),
            'invalid_position': ('Enter finite X, Y and Z coordinates from -100000 to 100000.', '请输入-100000至100000之间的有效X、Y、Z坐标。'),
            'invalid_radius': ('Radius must be from 2 to 150 metres, or left blank.', '半径须为2至150米，或留空使用默认值。'),
            'invalid_compact_descr': ('Shell compactDescr must be an integer from 1 to 2147483647.', '弹种compactDescr须为1至2147483647之间的整数。'),
            'invalid_target_id': ('Target ID must be an integer from 1 to 2147483647.', '目标ID须为1至2147483647之间的整数。'),
            'invalid_tolerance_deg': ('Aim tolerance must be from 0.05 to 5 degrees.', '瞄准容差须为0.05至5度。'),
            'invalid_command_id': ('An explicit command ID must contain 1 to 128 characters.', '指定命令ID须为1至128个字符。'),
            'invalid_equipment_id': ('Equipment ID must be an integer from 0 to 65535.', '给养ID须为0至65535之间的整数。'),
            'invalid_equipment_target': ('Choose a native device or crew target from the fixed list.', '请从固定列表中选择原生模块或成员目标。'),
            'invalid_active': ('RPM limiter active state must be a boolean.', '调速器启用状态须为布尔值。'),
            'invalid_enabled': ('Requested siege mode must be enabled or disabled.', '攻城模式须明确指定启用或关闭。'),
            'aim_busy': ('Another explicit aim owns the gun channel.', '另一条指定瞄准命令正持有火炮控制权。'),
            'aim_owner_mismatch': ('The release ID does not match the current aim holder.', '释放ID与当前瞄准持有者不一致。'),
            'aim_release_pending': ('The native aim source has not yet confirmed release.', '原生瞄准源尚未确认释放。'),
            'aim_not_aligned': ('The held aim is not currently aligned.', '当前持续瞄准尚未对准。'),
            'aim_target_unavailable': ('The requested target is no longer observable.', '请求的目标当前不可观察。'),
            'aim_unreachable': ('The requested aim cannot be reached by the current gun.', '当前火炮无法对准请求的位置。'),
            'aim_source_lost': ('The owned native aim source was replaced or lost.', '持有的原生瞄准源已被替换或丢失。'),
            'aim_acquiring': ('Waiting for the real gun direction to align.', '正在等待实际火炮方向对准。'),
            'aim_tracking': ('The held aim is tracking a changed position or gun state.', '持续瞄准正在跟随位置或火炮状态变化。'),
            'aim_aligned': ('The actual gun direction aligned with the requested aim.', '实际火炮方向已对准请求目标。'),
            'aim_released': ('The owned aim source was released.', '已释放持有的瞄准源。'),
            'aim_native_unavailable': ('The required native aiming interface is not available.', '所需原生瞄准接口不可用。'),
            'aim_observation_unavailable': ('A reliable current aiming observation is not available.', '当前无法取得可靠的瞄准观察结果。'),
            'aim_observation_changed': ('The target or loaded-shell observation changed during alignment checks.', '对准检查期间目标或装填炮弹状态发生改变。'),
            'aim_source_error': ('The native aiming source could not be installed.', '无法安装原生瞄准源。'),
            'aim_owner_changed': ('The aiming owner changed during admission.', '接收命令期间瞄准持有者发生改变。'),
            'entity_changed': ('The physical player vehicle entity changed.', '玩家的实际战车实体已更换。'),
            'vehicle_changed': ('The physical player vehicle entity changed.', '玩家的实际战车实体已更换。'),
            'gun_owner_changed': ('Gun control was stopped or replaced while selecting the operation.', '选择装填操作期间火炮控制已被停止或替换。'),
            'control_changed': ('Control ownership changed.', '控制权已变化。'),
            'equipment_state_unavailable': ('The canonical equipment state is not available.', '尚未取得权威给养状态。'),
            'equipment_native_busy': ('Another native equipment request is awaiting confirmation.', '另一条原生给养请求正在等待确认。'),
            'equipment_operation_busy': ('An equipment command is still pending.', '另一条给养命令尚未完成。'),
            'equipment_not_mounted': ('That equipment ID is not mounted on the player vehicle.', '玩家战车未装配该ID的给养。'),
            'ambiguous_mounted_equipment': ('The equipment ID matches more than one mounted item.', '该给养ID对应多个装配项。'),
            'equipment_not_activatable': ('This equipment has no explicit activation action.', '该给养不支持主动使用。'),
            'automatic_equipment_only': ('This extinguisher is automatically activated by the native state.', '该灭火器仅由原生状态自动触发。'),
            'unexpected_equipment_active': ('Only an RPM limiter accepts an explicit active state.', '仅调速器接受显式启用状态。'),
            'equipment_target_required': ('Choose a device or crew target for this small kit.', '请为小型修理箱/急救包选择模块或成员目标。'),
            'equipment_target_unavailable': ('That target is not supported by this equipment or vehicle.', '该给养或战车不支持所选目标。'),
            'unexpected_equipment_target': ('Clear the target for all-target equipment, extinguishers or RPM limiters.', '全目标给养、灭火器或调速器不接受指定目标，请留空。'),
            'equipment_active_required': ('Specify the requested RPM limiter enabled/disabled state.', '请明确指定调速器的启用/关闭状态。'),
            'equipment_not_ready': ('The equipment is cooling down or has no uses left.', '给养正在冷却或已无可用次数。'),
            'equipment_settings_unavailable': ('The native equipment input interface is not available.', '原生给养输入接口不可用。'),
            'automatic_consumables_active': ('Automatic consumables own this channel. Restore manual control first.', '自动给养正占用此通道，请先恢复手动控制。'),
            'equipment_submission_failed': ('The native equipment input did not confirm submission.', '原生给养输入未确认提交。'),
            'equipment_receipt_superseded': ('A newer equipment result superseded this command sequence.', '更晚的给养结果已覆盖该命令序号。'),
            'equipment_changed': ('The mounted equipment changed before confirmation.', '确认前已装配给养发生改变。'),
            'equipment_rejected': ('The authoritative state rejected this equipment request.', '权威状态拒绝了该给养请求。'),
            'equipment_already_set': ('The requested equipment state was already confirmed.', '已确认给养处于所请求的状态。'),
            'equipment_applied': ('The matching native equipment result was applied.', '对应序号的原生给养结果已生效。'),
            'siege_not_supported': ('This vehicle does not support siege mode.', '该战车不支持攻城模式。'),
            'siege_native_busy': ('The native siege controller is already braking or switching.', '原生攻城模式控制器正在刹车或切换。'),
            'siege_operation_busy': ('A siege mode command is still pending.', '另一条攻城模式命令尚未完成。'),
            'siege_state_unavailable': ('The canonical mode and native presentation are not synchronized.', '权威模式状态与原生显示尚未同步。'),
            'siege_settings_unavailable': ('The native siege input interface is not available.', '原生攻城模式输入接口不可用。'),
            'automatic_drive_active': ('Automatic driving owns this channel. Restore manual control first.', '自动驾驶正占用此通道，请先恢复手动控制。'),
            'siege_submission_failed': ('The native siege input did not confirm submission.', '原生攻城模式输入未确认提交。'),
            'siege_request_sequence_invalid': ('The mode acknowledgement does not match this request sequence.', '模式确认与该请求序号不匹配。'),
            'siege_rejected': ('The authoritative mode did not accept the requested state.', '权威模式未接受所请求的状态。'),
            'siege_already_set': ('The requested siege mode was already confirmed.', '已确认攻城模式处于所请求的状态。'),
            'siege_stable': ('The requested mode is stable and the matching native state is confirmed.', '所请求模式已稳定，对应的原生状态已确认。'),
            'siege_replaced': ('A newer native mode request replaced this command.', '更新的原生模式请求已替换该命令。'),
            'siege_not_submitted': ('The mode request was not submitted to the native input stream.', '该模式请求未提交到原生输入流。'),
            'position_unavailable': ('A current client position is not available.', '尚不能取得客户端当前位置。'),
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
            'shot_committed': ('Projectiles were committed locally; flight and combat observations are separate.', '弹体已在本地提交；飞行与战斗结果另行显示。'),
            'projectile_launch_rejected': ('The projectile launch was later rejected.', '弹体发射随后被拒绝。'),
            'condition_observed': ('The requested condition was observed.', '已观察到指定条件成立。'),
            'assertion_failed': ('The observed state does not satisfy the assertion.', '实际状态不满足断言。'),
            'observation_unavailable': ('The required state has not been observed.', '尚未观察到所需状态。'),
            'observation_limit': ('The client already has 32 pending state checks.', '客户端已有32个待完成的状态检查。'),
            'automatic_fire_active': ('Automatic aiming/fire owns this channel. Restore manual control first.', '自动瞄准/射击正占用此通道，请先恢复手动控制。'),
            'gun_operation_busy': ('Another ammunition operation is still pending.', '另一个弹药操作尚未结束。'),
            'shell_not_mounted': ('That shell compactDescr is not mounted on this vehicle.', '当前战车未配备该compactDescr弹种。'),
            'ambiguous_mounted_shell': ('That shell identifier matches more than one slot.', '该弹种标识对应多个弹种槽位。'),
            'shell_empty': ('The selected ammunition is exhausted.', '所选弹种已耗尽。'),
            'reload_not_supported': ('Partial-clip reload is not supported by this gun.', '此火炮不支持主动弹夹装填。'),
            'gun_settings_unavailable': ('Native ammunition controls are unavailable.', '原生弹药控制接口不可用。'),
            'gun_setting_rejected': ('The native client rejected the ammunition change.', '原生客户端拒绝了弹药调整。'),
            'shell_ready': ('The selected shell is confirmed ready by the client.', '客户端已确认指定弹种就绪。'),
            'reload_completed': ('The client confirmed reload completion.', '客户端已确认装填完成。'),
            'gun_changed': ('The gun changed before the operation completed.', '操作完成前火炮状态已更换。'),
            'shell_changed': ('The selected shell changed before confirmation.', '确认前所选弹种发生改变。'),
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
            'condition': ('Condition', '条件'), 'matched': ('Matched', '符合条件'),
            'observed': ('Observed', '实际观察'), 'value': ('Observed value', '观察值'),
            'compact_descr': ('compactDescr', 'compactDescr'),
            'known': ('Observation available', '观察可用'), 'stock': ('Mounted items', '已装配项目'),
            'stock_truncated': ('Shell list truncated', '弹种列表已截断'),
            'index': ('Shell index', '弹种索引'), 'ammo': ('Ammunition', '弹药'),
            'pending_index': ('Pending shell index', '待装填弹种索引'),
            'gun_pending': ('Gun transaction', '装填操作'),
            'held': ('Aim source held', '持有瞄准源'),
            'command_id': ('Command ID', '命令ID'),
            'tolerance_deg': ('Tolerance (degrees)', '容差（度）'),
            'error_deg': ('Direction error (degrees)', '方向误差（度）'),
            'targets': ('Valid targets', '有效目标'),
            'target_ids': ('Observed target IDs', '已观察目标ID'),
            'visible_targets': ('Visible targets', '可见目标'),
            'equipment_id': ('Equipment ID', '给养ID'), 'id': ('ID', 'ID'),
            'repair_all': ('All-target effect', '全目标效果'),
            'ready': ('Ready', '就绪'), 'uses_left': ('Uses left', '剩余使用次数'),
            'pending': ('Pending operation', '待确认操作'), 'last': ('Latest observation', '最近观察'),
            'intent_seq': ('Equipment intent sequence', '给养意图序号'),
            'request_seq': ('Request sequence', '请求序号'),
            'input_seq': ('Observed input sequence', '已观察输入序号'),
            'enabled': ('Siege enabled', '攻城模式启用'),
            'time_left_ms': ('Transition milliseconds', '切换剩余毫秒'),
            'revision': ('Canonical revision', '权威状态版本'),
            'presented': ('Native mode presentation', '原生模式显示'),
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
                if key in ('action', 'objective', 'kind', 'phase', 'state', 'status', 'condition') else self._describe(item))
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
            'acquiring': ('Acquiring aim source', '正在取得瞄准源'),
            'releasing': ('Releasing owned control', '正在释放持有的控制权'),
            'observing': ('Awaiting native observation', '等待原生状态观察'),
            'submitting': ('Submitting native input', '正在提交原生输入'),
            'braking': ('Braking before mode change', '模式切换前刹车'),
            'repairkit': ('Repair kit', '修理箱'), 'medkit': ('First aid kit', '急救包'),
            'extinguisher': ('Extinguisher', '灭火器'), 'rpm_limiter': ('RPM limiter', '调速器'),
            'travelling': ('Travelling', '行进中'), 'attacking': ('Attacking', '进攻中'),
            'capture_travel': ('Travelling to capture', '前往占领'), 'capturing': ('Capturing', '占领中'),
            'aiming': ('Aiming', '瞄准中'), 'arriving': ('Arriving', '正在抵达'),
            'defending': ('Defending', '守卫中'), 'captured': ('Captured', '已占领'),
            'ammo_ready': ('Ammunition ready', '弹药就绪'), 'ammo_empty': ('Ammunition empty', '弹药耗尽'),
            'halted': ('Hull stopped', '车体已停车'), 'active': ('Takeover active', '接管状态'),
            'mission_status': ('Mission status', '任务状态'), 'mission_phase': ('Mission phase', '任务阶段'),
            'shot_terminal': ('Projectile flight terminal', '弹体飞行终结'),
            'shot_effect': ('Projectile combat effect observed', '已观察到弹体战斗效果'),
        }
        if isinstance(value, str):
            pair = ACTION_LABELS.get(value) or states.get(value)
            if pair:
                return self._text(*pair)
        return self._describe(value)

    def _manual_aim_text(self, value):
        if isinstance(value, dict) and value.get('phase') == 'holding':
            value = dict(value, phase=self._text('Holding aim', '持续瞄准'))
        return self._describe(value)

    def _siege_text(self, value):
        if isinstance(value, dict):
            state = value.get('state')
            # Preserve the pinned #1513 enum alongside the localized caption.
            if isinstance(state, int) and not isinstance(state, bool) and 0 <= state <= 3:
                labels = (('Travel mode (0)', '行驶模式（0）'),
                          ('Switching to siege (1)', '正在进入攻城模式（1）'),
                          ('Siege mode (2)', '攻城模式（2）'),
                          ('Switching to travel (3)', '正在退出攻城模式（3）'))
                value = dict(value, state=self._text(*labels[state]))
        return self._describe(value)

    def _projectile_text(self):
        items = self.transport.projectile_results() if self.transport else []
        if not items:
            return self._text('No projectile observations yet.', '尚无弹体观察回执。')
        lines = [self._text('Recent shots and the latest shot command:', '近期弹体及最新射击命令：')]
        omitted = (self.transport.status or {}).get('shot_snapshot_omitted', 0)
        if isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0:
            lines.append(self._text('The latest repair snapshot omitted %s older shots.',
                                    '最新补充快照省略了%s条较早弹体记录。') % omitted)
        for item in items:
            if item['command_id']:
                source = self._text('Command [%s]', '命令[%s]') % item['command_id'][:8]
            elif item['claimed_command_id']:
                source = self._text('Command reference [%s]; receipt not observed', '命令引用[%s]；尚未观察到回执') % item['claimed_command_id'][:8]
            else:
                source = self._text('Automatic / unlinked', '自动射击／未关联命令')
            local = self._text('Local commit observed', '已观察到本地提交') if item['local_committed'] else self._text(
                'Local commit not observed', '尚未观察到本地提交')
            if item['flight_status'] == 'rejected':
                flight = self._text('Launch rejected', '发射已拒绝')
                reason = item['events'].get('rejected', {}).get('reason')
                if reason:
                    flight += ': ' + self._reason_text(reason)
            elif item['terminal_observed']:
                flight = self._text('Flight terminal observed', '已观察到飞行终结')
            else:
                flight = self._text('Awaiting flight terminal', '等待飞行终结')
            if item['combat_observed']:
                combat = self._text('Combat effects %s · Damage %s · Penetration %s',
                                    '战斗效果%s次 · 伤害%s · 击穿%s') % (
                    item['hit_count'], self._describe(item['damage_total']),
                    self._text('yes', '是') if item['penetrated'] else self._text('not observed', '未观察到'))
            else:
                # Native terminal contact and later canonical effects are
                # independent observations. Silence never proves a miss.
                combat = self._text('No combat effect observed yet', '尚未观察到战斗效果')
            lines.append('%s · %s — %s; %s; %s' % (item['projectile_id'], source, local, flight, combat))
        return '\n'.join(lines)

    def _update_control_view(self, poll=True):
        if self.transport and poll:
            self.transport.poll()
        available = bool(self.transport and self.transport.live and self.vars['control'].get())
        for button in self.action_buttons:
            can_submit = bool(self.transport and self.vars['control'].get() and
                              self.transport.can_submit(button._control_action) and
                              (not getattr(button, '_requires_live', False) or self.transport.live))
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
        manual_aim = status.get('manual_aim')
        held_aim = manual_aim if isinstance(manual_aim, dict) and manual_aim.get('held') is True else {}
        target = next((item[key] for item in (held_aim, aim, mission) if isinstance(item, dict)
                       for key in ('target_id', 'target', 'target_position', 'point') if item.get(key) is not None), None)
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
            if (result.get('action') == 'fire' and result.get('status') == 'completed' and
                    result.get('reason') == 'shot_committed'):
                states['completed'] = ('Local commit confirmed', '本地提交已确认')
            if (result.get('action') in player_control_transport.AIM_ACTIONS and
                    result.get('status') == 'completed'):
                states['completed'] = ('Alignment observed; current ownership is shown separately',
                                       '已观察到对准；当前控制权另行显示')
            if result.get('action') in player_control_transport.NATIVE_ACTIONS:
                states['accepted'] = ('Accepted; awaiting correlated native confirmation',
                                      '已接受；等待关联的原生状态确认')
                states['completed'] = ('Canonical state confirmed', '权威状态已确认')
            action = ACTION_LABELS.get(result.get('action'), (str(result.get('action', '?')), str(result.get('action', '?'))))
            result_text = '%s — %s [%s]' % (self._text(*action),
                self._text(*states.get(result.get('status'), (str(result.get('status')), str(result.get('status'))))),
                str(result.get('id', ''))[:8])
            if result.get('reason'):
                result_text += ': ' + self._reason_text(result['reason'])
            if (result.get('action') in ('wait_state', 'assert_state', 'select_shell', 'reload',
                                        'aim_target', 'aim_point', 'release_aim',
                                        'use_equipment', 'set_siege') and
                    isinstance(result.get('result'), dict)):
                describe_result = (self._manual_aim_text if result.get('action') in
                    player_control_transport.AIM_ACTIONS | {'release_aim'} else
                    self._siege_text if result.get('action') == 'set_siege' else self._describe)
                result_text += '\n' + describe_result(result['result'])
        if self.notice:
            result_text += '\n' + self._reason_text(self.notice)
        ammo = status.get('ammo')
        testing = status.get('testing')
        if isinstance(testing, dict) and isinstance(testing.get('gun'), dict):
            ammo = dict(ammo) if isinstance(ammo, dict) else {}
            for key in ('stock', 'stock_truncated', 'pending_index'):
                if key in testing['gun']:
                    ammo[key] = testing['gun'][key]
            if testing.get('gun_pending') is not None:
                ammo['gun_pending'] = testing['gun_pending']
        aim_ownership = self._manual_aim_text(manual_aim)
        if isinstance(manual_aim, dict) and manual_aim.get('held') is False:
            aim_ownership = self._text('No owned aim source. ', '当前未持有瞄准源。') + aim_ownership
        native_actions = status.get('native_actions')
        native_actions = native_actions if isinstance(native_actions, dict) else {}
        values = {'connection': connection,
                  'control': mode + ' · ' + (channels or self._text('No automatic channels', '没有自动控制通道')),
                  'mission': self._describe(mission), 'target': target_text,
                  'ammo': self._describe(ammo), 'pose': self._describe(status.get('pose')),
                  'aim': self._describe(aim), 'manual_aim': aim_ownership,
                  'equipment': self._describe(native_actions.get('equipment')),
                  'siege': self._siege_text(native_actions.get('siege')),
                  'result': result_text, 'projectiles': self._projectile_text()}
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

    def _refresh_point_fields(self):
        for entry in self.mission_entries:
            entry.config(state='normal' if self.mission_custom_point.get() else 'disabled')

    def _use_current_pose(self):
        if self.transport:
            self.transport.poll()
        if not self.transport or not self.transport.live:
            self.notice = self.transport.unavailable_reason() if self.transport else 'control_not_started'
            self._update_control_view(poll=False)
            return False
        pose = self.transport.status.get('pose')
        try:
            position = player_control_transport.validate_arguments('hold_position',
                {'position': pose.get('position') if isinstance(pose, dict) else None})['position']
        except (TypeError, ValueError):
            self.notice = 'position_unavailable'
            self._update_control_view(poll=False)
            return False
        for axis, value in zip(('x', 'y', 'z'), position):
            self.mission_position[axis].set(str(value))
        self.mission_custom_point.set(True)
        self._refresh_point_fields()
        self.notice = None
        self._update_control_view(poll=False)
        return True

    def _send_point_mission(self, action):
        args = {}
        if self.mission_custom_point.get():
            args['position'] = [self.mission_position[axis].get() for axis in ('x', 'y', 'z')]
        if self.mission_radius.get().strip():
            args['radius'] = self.mission_radius.get()
        try:
            args = player_control_transport.validate_arguments(action, args)
        except (TypeError, ValueError) as error:
            self.notice = str(error)
            self._update_control_view(poll=False)
            return False
        return self.send(action, **args)

    def _send_shell_selection(self):
        try:
            value = self.shell_compact_descr.get()
            if not isinstance(value, str) or not value.strip().isdigit():
                raise ValueError('invalid_compact_descr')
            args = player_control_transport.validate_arguments('select_shell', {'compact_descr': int(value, 10)})
        except (TypeError, ValueError, OverflowError):
            self.notice = 'invalid_compact_descr'
            self._update_control_view(poll=False)
            return False
        return self.send('select_shell', **args)

    def _send_aim(self, action):
        args = {'tolerance_deg': self.aim_tolerance.get()}
        try:
            if action == 'aim_target':
                value = self.aim_target_id.get()
                if not isinstance(value, str) or not value.strip().isdigit():
                    raise ValueError('invalid_target_id')
                args['target_id'] = int(value, 10)
            else:
                args['position'] = [self.aim_position[axis].get() for axis in ('x', 'y', 'z')]
            args = player_control_transport.validate_arguments(action, args)
        except (TypeError, ValueError, OverflowError) as error:
            self.notice = str(error)
            self._update_control_view(poll=False)
            return False
        return self.send(action, **args)

    def _release_aim(self):
        value = self.aim_release_id.get()
        try:
            if not isinstance(value, str):
                raise ValueError('invalid_command_id')
            args = {'command_id': value.strip()} if value.strip() else {}
            args = player_control_transport.validate_arguments('release_aim', args)
        except (TypeError, ValueError) as error:
            self.notice = str(error)
            self._update_control_view(poll=False)
            return False
        return self.send('release_aim', **args)

    def _send_equipment(self):
        try:
            value = self.equipment_id.get()
            if not isinstance(value, str) or not value.strip().isdigit():
                raise ValueError('invalid_equipment_id')
            args = {'equipment_id': int(value, 10)}
            target = self.equipment_target.get()
            if not isinstance(target, str):
                raise ValueError('invalid_equipment_target')
            if target.strip():
                args['target'] = target.strip()
            if self.equipment_use_active.get():
                args['active'] = self.equipment_active.get()
            args = player_control_transport.validate_arguments('use_equipment', args)
        except (TypeError, ValueError, OverflowError) as error:
            self.notice = str(error)
            self._update_control_view(poll=False)
            return False
        return self.send('use_equipment', **args)

    def _send_siege(self):
        try:
            args = player_control_transport.validate_arguments('set_siege',
                {'enabled': self.siege_enabled.get()})
        except (TypeError, ValueError) as error:
            self.notice = str(error)
            self._update_control_view(poll=False)
            return False
        return self.send('set_siege', **args)

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

        label(body, 'Commands require client receipts and admission within two seconds. Execution has a separate timeout. State checks only observe. Closing this panel requests Restore manual control (Stop); only Stop has no admission expiry.',
              '命令须在两秒内被客户端接收并以客户端回执确认；执行超时另行计算。状态检查只做观察。关闭面板请求恢复手动（Stop），仅Stop不因接收延迟过期。')
        state_body = section('Current client state', '客户端实际状态')
        for key, en, zh in (('connection', 'Connection', '连接'), ('control', 'Mode / enabled channels', '模式/已启用通道'),
                            ('mission', 'Task / phase', '任务/阶段'), ('target', 'Target / destination', '目标/目的地'),
                            ('ammo', 'Ammunition / clip / reload', '弹药/弹夹/装填'),
                            ('aim', 'Aiming / firing', '瞄准/射击'), ('pose', 'Position / movement', '位置/运动'),
                            ('manual_aim', 'Held aim / current alignment', '持续瞄准/当前对准状态'),
                            ('equipment', 'Equipment / native confirmation', '给养/原生确认'),
                            ('siege', 'Observed siege mode / transition', '攻城模式/切换实际状态'),
                            ('result', 'Latest command receipt', '最新命令回执'),
                            ('projectiles', 'Projectile observations', '弹体后续观察')):
            frame = tk.Frame(state_body)
            frame.pack(fill='x')
            heading = tk.Label(frame, width=23, anchor='nw', justify='left', wraplength=160)
            heading.pack(side='left', anchor='n')
            self.control_labels.append((heading, en, zh))
            value = tk.Label(frame, anchor='w', justify='left', wraplength=410)
            value.pack(side='left', fill='x', expand=True)
            self.status_labels[key] = value
        control_body = section('Takeover and battle tasks', '接管与战斗任务')
        self.mission_custom_point = tk.BooleanVar(value=False)
        custom = tk.Checkbutton(control_body, variable=self.mission_custom_point,
                                command=self._refresh_point_fields, anchor='w')
        custom.pack(fill='x')
        self.control_labels.append((custom, 'Use X/Y/Z destination for Attack and Hold', '进攻与驻守使用指定X/Y/Z目的地'))
        point_row = tk.Frame(control_body)
        point_row.pack(fill='x', pady=(0, ui_layout.GAP))
        self.mission_position, self.mission_entries = {}, []
        for axis in ('x', 'y', 'z'):
            tk.Label(point_row, text=axis.upper() + ':').pack(side='left')
            value = self.mission_position[axis] = tk.StringVar(value='0')
            entry = tk.Entry(point_row, width=10, textvariable=value)
            entry.pack(side='left', fill='x', expand=True)
            self.mission_entries.append(entry)
        current = tk.Button(point_row, command=self._use_current_pose, state='disabled')
        current._control_action = 'status'
        current._requires_live = True
        current.pack(side='left')
        self.control_labels.append((current, 'Use current pose', '使用当前位置'))
        self.action_buttons.append(current)
        radius_row = tk.Frame(control_body)
        radius_row.pack(fill='x', pady=(0, ui_layout.GAP))
        radius_label = tk.Label(radius_row, anchor='w')
        radius_label.pack(side='left')
        self.control_labels.append((radius_label, 'Radius (2–150 m; blank = default): ', '半径（2至150米；留空为默认值）：'))
        self.mission_radius = tk.StringVar(value='')
        tk.Entry(radius_row, width=8, textvariable=self.mission_radius).pack(side='left')
        label(control_body, 'Without a specified point, Hold uses the client position at admission and Attack seeks enemies. Other tasks use the current battle base geometry.',
              '未指定目的地时，驻守使用客户端接收命令时的位置，进攻主动寻找敌人；其他任务使用当前对局的基地范围。')
        self._refresh_point_fields()
        for actions in (('start', 'stop', 'halt'), ('attack', 'return_base', 'defend_base'),
                        ('hold_position', 'capture_base', 'status')):
            row(control_body, [(action, ACTION_LABELS[action][0], ACTION_LABELS[action][1],
                                lambda action=action: self._send_point_mission(action) if action in
                                ('attack', 'hold_position') else self.send(action)) for action in actions])
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
        aim_body = section('Explicit held aiming', '指定持续瞄准')
        target_row = tk.Frame(aim_body)
        target_row.pack(fill='x', pady=(0, ui_layout.GAP))
        target_label = tk.Label(target_row, anchor='w')
        target_label.pack(side='left')
        self.control_labels.append((target_label, 'Target ID: ', '目标ID：'))
        self.aim_target_id = tk.StringVar(value='')
        tk.Entry(target_row, width=12, textvariable=self.aim_target_id).pack(side='left')
        tolerance_label = tk.Label(target_row, anchor='w')
        tolerance_label.pack(side='left', padx=(ui_layout.GAP, 0))
        self.control_labels.append((tolerance_label, 'Tolerance (0.05–5 degrees): ', '容差（0.05至5度）：'))
        self.aim_tolerance = tk.StringVar(value='0.5')
        tk.Entry(target_row, width=7, textvariable=self.aim_tolerance).pack(side='left')
        aim_point_row = tk.Frame(aim_body)
        aim_point_row.pack(fill='x', pady=(0, ui_layout.GAP))
        self.aim_position = {}
        for axis in ('x', 'y', 'z'):
            tk.Label(aim_point_row, text=axis.upper() + ':').pack(side='left')
            value = self.aim_position[axis] = tk.StringVar(value='')
            tk.Entry(aim_point_row, width=10, textvariable=value).pack(side='left', fill='x', expand=True)
        row(aim_body, [(action, ACTION_LABELS[action][0], ACTION_LABELS[action][1],
                        lambda action=action: self._send_aim(action))
                       for action in ('aim_target', 'aim_point')])
        release_row = tk.Frame(aim_body)
        release_row.pack(fill='x', pady=(0, ui_layout.GAP))
        release_label = tk.Label(release_row, anchor='w')
        release_label.pack(side='left')
        self.control_labels.append((release_label, 'Aim command ID (optional): ', '瞄准命令ID（可选）：'))
        self.aim_release_id = tk.StringVar(value='')
        tk.Entry(release_row, width=28, textvariable=self.aim_release_id).pack(side='left', fill='x', expand=True)
        row(aim_body, [('release_aim', ACTION_LABELS['release_aim'][0], ACTION_LABELS['release_aim'][1], self._release_aim)])
        label(aim_body, 'Alignment is observed for up to 30 seconds; a completed aim stays held until released or replaced. It does not confirm a clear firing lane or a hit. A blank release ID releases the current owned aim; an ID only releases that exact holder.',
              '最长等待30秒确认对准；瞄准完成后仍持续持有，直到释放或替换。对准不代表射界畅通或命中。释放ID留空时释放当前持有的瞄准，指定ID时只释放该命令。')
        weapon_body = section('Ammunition and state checks', '弹药与状态检查')
        shell_row = tk.Frame(weapon_body)
        shell_row.pack(fill='x', pady=(0, ui_layout.GAP))
        shell_label = tk.Label(shell_row, anchor='w')
        shell_label.pack(side='left')
        self.control_labels.append((shell_label, 'Shell compactDescr: ', '弹种compactDescr：'))
        self.shell_compact_descr = tk.StringVar(value='')
        tk.Entry(shell_row, width=14, textvariable=self.shell_compact_descr).pack(side='left')
        row(weapon_body, [('select_shell', 'Load selected shell', '装填指定弹种', self._send_shell_selection),
                          ('reload', 'Reload', '重新装填', lambda: self.send('reload'))])
        row(weapon_body, [('wait_state', 'Wait for ammunition ready', '等待弹药就绪',
                           lambda: self.send('wait_state', condition='ammo_ready')),
                          ('assert_state', 'Assert ammunition empty', '断言弹药耗尽',
                           lambda: self.send('assert_state', condition='ammo_empty'))])
        label(weapon_body, 'Use a shell compactDescr configured on the current vehicle. Loading/reloading waits for native confirmation (up to 180 seconds); the ready check waits up to 30 seconds. A failed assertion does not change control.',
              '请输入当前战车配备弹种的compactDescr。装填/重新装填等待原生状态确认，最长180秒；就绪检查最长30秒。断言失败不会改变控制权。')
        native_body = section('Equipment and siege mode', '给养与攻城模式')
        equipment_row = tk.Frame(native_body)
        equipment_row.pack(fill='x', pady=(0, ui_layout.GAP))
        equipment_label = tk.Label(equipment_row, anchor='w')
        equipment_label.pack(side='left')
        self.control_labels.append((equipment_label, 'Mounted equipment ID (not compactDescr): ', '已装配给养ID（非compactDescr）：'))
        self.equipment_id = tk.StringVar(value='')
        tk.Entry(equipment_row, width=10, textvariable=self.equipment_id).pack(side='left')
        equipment_target_row = tk.Frame(native_body)
        equipment_target_row.pack(fill='x', pady=(0, ui_layout.GAP))
        equipment_target_label = tk.Label(equipment_target_row, anchor='w')
        equipment_target_label.pack(side='left')
        self.control_labels.append((equipment_target_label, 'Repair / crew target (blank for all-target): ', '修理/成员目标（全目标时留空）：'))
        self.equipment_target = tk.StringVar(value='')
        self.app._ttk.Combobox(equipment_target_row, state='readonly', width=24,
            textvariable=self.equipment_target,
            values=[''] + sorted(player_control_transport.EQUIPMENT_TARGETS)).pack(side='left', fill='x', expand=True)
        self.equipment_use_active = tk.BooleanVar(value=False)
        use_active = tk.Checkbutton(native_body, variable=self.equipment_use_active, anchor='w')
        use_active.pack(fill='x')
        self.control_labels.append((use_active, 'Specify RPM limiter state (RPM limiter only)', '指定调速器状态（仅限调速器给养）'))
        self.equipment_active = tk.BooleanVar(value=True)
        active = tk.Checkbutton(native_body, variable=self.equipment_active, anchor='w')
        active.pack(fill='x')
        self.control_labels.append((active, 'Requested RPM limiter enabled', '请求启用调速器'))
        row(native_body, [('use_equipment', ACTION_LABELS['use_equipment'][0],
                          ACTION_LABELS['use_equipment'][1], self._send_equipment)])
        self.siege_enabled = tk.BooleanVar(value=True)
        enabled = tk.Checkbutton(native_body, variable=self.siege_enabled, anchor='w')
        enabled.pack(fill='x')
        self.control_labels.append((enabled, 'Requested siege mode enabled', '请求启用攻城模式'))
        row(native_body, [('set_siege', ACTION_LABELS['set_siege'][0],
                          ACTION_LABELS['set_siege'][1], self._send_siege)])
        label(native_body, 'IDs, availability and valid repair/crew targets come from the client state above. Small kits require a target; all-target kits and extinguishers use a blank target. RPM limiter requests require an explicit enabled/disabled state. Accepted is not completed: equipment and mode changes wait up to 30 seconds for correlated native confirmation.',
              'ID、可用性及有效修理/成员目标以顶部客户端状态为准。小修理箱/急救包须选目标，大型全目标给养及灭火器须留空。调速器须明确指定启用/关闭。已接受不代表已完成；给养和模式切换最长等待30秒，确认关联的原生结果。')
        window.protocol('WM_DELETE_WINDOW', self._close_controls)
        self.translate()
        ui_layout.polish(window)
        self._poll_controls()
